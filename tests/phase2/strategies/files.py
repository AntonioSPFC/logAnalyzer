"""Factories de arquivos temporários sintéticos com terminadores explícitos."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
from typing import Iterable

from .blocks import BlockSpec, CRLF, LF
from .common import assert_no_raw_source_reference

_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


@dataclass(frozen=True)
class TemporaryLogFile:
    """Arquivo escrito e seu payload conhecido, sem reler a fonte do disco."""

    path: Path
    payload: bytes
    line_count: int
    terminators: tuple[str, ...]

    @property
    def digest(self) -> str:
        return sha256(self.payload).hexdigest()

    def decode_utf8(self) -> str:
        return self.payload.decode("utf-8", errors="strict")


class TemporaryLogFactory:
    """Escreve somente payloads fornecidos em uma raiz temporária isolada.

    Não há operação de leitura, importação ou cópia de outro arquivo.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ValueError("raiz temporária deve ser um diretório existente")
        assert_no_raw_source_reference(self.root)
        self._next_index = 1

    def _target(self, filename: str | None) -> Path:
        selected = filename or f"synthetic-{self._next_index}.log"
        self._next_index += 1
        if not _FILENAME_RE.fullmatch(selected) or Path(selected).name != selected:
            raise ValueError("nome de arquivo temporário inválido")
        assert_no_raw_source_reference(selected)
        target = (self.root / selected).resolve()
        try:
            target.relative_to(self.root)
        except ValueError as error:
            raise ValueError("arquivo deve permanecer na raiz temporária") from error
        return target

    def _write(
        self,
        payload: bytes,
        *,
        line_count: int,
        terminators: tuple[str, ...],
        filename: str | None,
    ) -> TemporaryLogFile:
        assert_no_raw_source_reference(payload)
        target = self._target(filename)
        with target.open("xb") as stream:
            stream.write(payload)
        return TemporaryLogFile(
            path=target,
            payload=payload,
            line_count=line_count,
            terminators=terminators,
        )

    def write_lines(
        self,
        lines: Iterable[str],
        *,
        newline: str = LF,
        final_newline: bool = True,
        filename: str | None = None,
    ) -> TemporaryLogFile:
        """Escreve linhas UTF-8 usando exclusivamente LF ou CRLF."""

        if newline not in {LF, CRLF}:
            raise ValueError("newline deve ser LF ou CRLF")
        materialized = tuple(lines)
        if any("\n" in line or "\r" in line for line in materialized):
            raise ValueError("linhas devem ser fornecidas sem terminadores")
        assert_no_raw_source_reference(materialized)
        text = newline.join(materialized)
        if materialized and final_newline:
            text += newline
        terminators = tuple(
            newline if index < len(materialized) - 1 or final_newline else ""
            for index in range(len(materialized))
        )
        return self._write(
            text.encode("utf-8"),
            line_count=len(materialized),
            terminators=terminators,
            filename=filename,
        )

    def write_blocks(
        self,
        blocks: Iterable[BlockSpec],
        *,
        filename: str | None = None,
    ) -> TemporaryLogFile:
        """Escreve blocos sem normalizar seus terminadores individuais."""

        materialized = tuple(blocks)
        assert_no_raw_source_reference(materialized)
        lines = tuple(line for block in materialized for line in block.lines)
        payload = b"".join(block.payload for block in materialized)
        return self._write(
            payload,
            line_count=len(lines),
            terminators=tuple(line.terminator for line in lines),
            filename=filename,
        )

    def write_invalid_utf8(
        self,
        *,
        prefix: str = "SYN_VALID_PREFIX",
        invalid_chunk: bytes = b"\xff",
        suffix: str = "SYN_VALID_SUFFIX",
        filename: str | None = None,
    ) -> TemporaryLogFile:
        """Cria falha de decodificação conhecida sem transportar bytes reais."""

        assert_no_raw_source_reference((prefix, invalid_chunk, suffix))
        payload = prefix.encode("utf-8") + invalid_chunk + suffix.encode("utf-8")
        try:
            payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            pass
        else:
            raise ValueError("invalid_chunk deve produzir UTF-8 inválido")
        return self._write(
            payload,
            line_count=1,
            terminators=("",),
            filename=filename,
        )
