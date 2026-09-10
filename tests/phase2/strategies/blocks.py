"""Strategies para linhas físicas e blocos multiline lossless."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Iterable

from hypothesis import strategies as st
from hypothesis.strategies import SearchStrategy

from .common import assert_no_raw_source_reference
from .fields import opaque_values

LF = "\n"
CRLF = "\r\n"
LINE_TERMINATORS = (LF, CRLF)


class LineKind(str, Enum):
    VALID_HEADER = "valid_header"
    INVALID_HEADER = "invalid_header"
    CONTINUATION = "continuation"


@dataclass(frozen=True)
class PhysicalLineSpec:
    """Linha física sintética com terminador preservado separadamente."""

    kind: LineKind
    text: str
    terminator: str

    def __post_init__(self) -> None:
        if "\n" in self.text or "\r" in self.text:
            raise ValueError("texto da linha não pode conter terminador")
        if self.terminator not in {"", LF, CRLF}:
            raise ValueError("terminador de linha não suportado")
        assert_no_raw_source_reference(self.text)

    @property
    def serialized(self) -> str:
        return self.text + self.terminator


@dataclass(frozen=True)
class BlockSpec:
    """Bloco sintético cuja serialização conserva caracteres e terminadores."""

    lines: tuple[PhysicalLineSpec, ...]

    def __post_init__(self) -> None:
        if not self.lines:
            raise ValueError("um bloco deve conter ao menos uma linha")
        if any(line.terminator == "" for line in self.lines[:-1]):
            raise ValueError("somente a última linha pode representar EOF sem terminador")
        assert_no_raw_source_reference(self.lines)

    @property
    def text(self) -> str:
        return "".join(line.serialized for line in self.lines)

    @property
    def payload(self) -> bytes:
        return self.text.encode("utf-8")


def line_terminators(*, allow_eof: bool = False) -> SearchStrategy[str]:
    choices = LINE_TERMINATORS + (("",) if allow_eof else ())
    return st.sampled_from(choices)


def _line_texts(kind: LineKind) -> SearchStrategy[str]:
    prefixes = {
        LineKind.VALID_HEADER: "HEADER_VALID",
        LineKind.INVALID_HEADER: "HEADER_INVALID",
        LineKind.CONTINUATION: "CONTINUATION",
    }
    return opaque_values(prefixes[kind])


def physical_lines(
    kind: LineKind | None = None,
    *,
    allow_eof: bool = False,
    texts: SearchStrategy[str] | None = None,
) -> SearchStrategy[PhysicalLineSpec]:
    """Gera linhas físicas sem incorporar a quebra ao texto."""

    kinds = st.just(kind) if kind is not None else st.sampled_from(tuple(LineKind))
    selected_texts = texts or st.one_of(*(_line_texts(item) for item in LineKind))
    return st.builds(
        PhysicalLineSpec,
        kind=kinds,
        text=selected_texts,
        terminator=line_terminators(allow_eof=allow_eof),
    )


def blocks(
    *,
    min_continuations: int = 0,
    max_continuations: int = 6,
    header_kinds: Iterable[LineKind] = (
        LineKind.VALID_HEADER,
        LineKind.INVALID_HEADER,
    ),
    header_texts: SearchStrategy[str] | None = None,
    continuation_texts: SearchStrategy[str] | None = None,
    final_newline: bool | None = None,
) -> SearchStrategy[BlockSpec]:
    """Gera bloco com cabeçalho e continuações, preservando LF/CRLF/EOF."""

    selected_header_kinds = tuple(header_kinds)
    if not selected_header_kinds or any(
        kind is LineKind.CONTINUATION for kind in selected_header_kinds
    ):
        raise ValueError("bloco deve começar por tipo de cabeçalho")
    if min_continuations < 0 or max_continuations < min_continuations:
        raise ValueError("limites de continuação inválidos")

    @st.composite
    def _strategy(draw):
        header_kind = draw(st.sampled_from(selected_header_kinds))
        header_text = draw(header_texts or _line_texts(header_kind))
        continuation_count = draw(
            st.integers(
                min_value=min_continuations,
                max_value=max_continuations,
            )
        )
        continuation_values = draw(
            st.lists(
                continuation_texts or _line_texts(LineKind.CONTINUATION),
                min_size=continuation_count,
                max_size=continuation_count,
            )
        )
        texts = (header_text, *continuation_values)
        kinds = (
            header_kind,
            *(LineKind.CONTINUATION for _ in continuation_values),
        )
        has_final_newline = (
            draw(st.booleans()) if final_newline is None else final_newline
        )
        generated_lines: list[PhysicalLineSpec] = []
        for index, (line_kind, text) in enumerate(zip(kinds, texts)):
            is_last = index == len(texts) - 1
            terminator = (
                draw(line_terminators())
                if not is_last or has_final_newline
                else ""
            )
            generated_lines.append(
                PhysicalLineSpec(line_kind, text, terminator)
            )
        return BlockSpec(tuple(generated_lines))

    return _strategy()


def block_sequences(
    *,
    min_size: int = 1,
    max_size: int = 8,
    allow_final_eof: bool = True,
) -> SearchStrategy[tuple[BlockSpec, ...]]:
    """Gera uma sequência serializável sem perder fronteiras físicas."""

    if min_size < 1 or max_size < min_size:
        raise ValueError("limites de sequência inválidos")

    @st.composite
    def _strategy(draw):
        count = draw(st.integers(min_value=min_size, max_value=max_size))
        generated = [draw(blocks(final_newline=True)) for _ in range(count)]
        if allow_final_eof and draw(st.booleans()):
            final_block = generated[-1]
            final_lines = list(final_block.lines)
            final_lines[-1] = replace(final_lines[-1], terminator="")
            generated[-1] = replace(final_block, lines=tuple(final_lines))
        return tuple(generated)

    return _strategy()
