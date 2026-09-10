"""Guardas comuns para dados de teste totalmente sintéticos."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import fields, is_dataclass
from pathlib import Path
import re
from typing import Any, Final

_TYPED_PLACEHOLDER_RE: Final = re.compile(r"^<[A-Z][A-Z0-9_]*_[1-9][0-9]*>$")
_SYNTHETIC_TOKEN_RE: Final = re.compile(r"^SYN_[A-Z][A-Z0-9_]*_[0-9A-F]+$")
_FORBIDDEN_DIRECTORY_NAMES: Final = frozenset({"logs"})
_FORBIDDEN_FILE_NAMES: Final = frozenset({"curation.db"})


def is_typed_placeholder(value: str) -> bool:
    """Retorna se ``value`` segue o formato de placeholder tipado da spec."""

    return bool(_TYPED_PLACEHOLDER_RE.fullmatch(value))


def is_synthetic_token(value: str) -> bool:
    """Retorna se ``value`` é um token opaco marcado como sintético."""

    return bool(_SYNTHETIC_TOKEN_RE.fullmatch(value))


def _text_references_raw_source(value: str) -> bool:
    normalized = value.replace("\\", "/").casefold()
    parts = tuple(part for part in normalized.split("/") if part not in {"", "."})
    return (
        any(part in _FORBIDDEN_DIRECTORY_NAMES for part in parts)
        or any(part in _FORBIDDEN_FILE_NAMES for part in parts)
    )


def assert_no_raw_source_reference(value: Any) -> None:
    """Rejeita referências a fontes brutas locais sem abrir qualquer caminho.

    A validação é estrutural e recursiva. Ela nunca lê arquivos e sua mensagem
    não ecoa o valor rejeitado.
    """

    if value is None:
        return
    if isinstance(value, Path):
        if _text_references_raw_source(str(value)):
            raise ValueError("referência a fonte bruta local não permitida")
        return
    if isinstance(value, str):
        if _text_references_raw_source(value):
            raise ValueError("referência a fonte bruta local não permitida")
        return
    if isinstance(value, bytes):
        if _text_references_raw_source(value.decode("latin-1")):
            raise ValueError("referência a fonte bruta local não permitida")
        return
    if is_dataclass(value) and not isinstance(value, type):
        for item in fields(value):
            assert_no_raw_source_reference(getattr(value, item.name))
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            assert_no_raw_source_reference(key)
            assert_no_raw_source_reference(item)
        return
    if isinstance(value, Iterable):
        for item in value:
            assert_no_raw_source_reference(item)
