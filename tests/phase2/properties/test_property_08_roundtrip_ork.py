"""Property 8 do round-trip dos perfis ORK real e legado.

Todos os textos e identificadores são sintéticos e gerados em memória. O teste
não lê arquivos, logs locais, bancos de dados ou serviços externos.
"""

from __future__ import annotations

from dataclasses import dataclass

from hypothesis import event, given, settings, strategies as st
from hypothesis.strategies import SearchStrategy

from log_analyzer.apps.ork import OrkParser
from log_analyzer.core.modelos import EntradaDeLog
from tests.phase2.strategies import (
    assert_no_raw_source_reference,
    opaque_values,
    ork_timestamps,
)

_FORMATOS = ("ork-real", "ork-legado")
_NIVEIS = tuple(
    variante
    for nivel in ("DEBUG", "INFO", "WARN", "ERROR", "FATAL")
    for variante in (nivel, nivel.lower())
)
_ROTULOS_SESSAO = (
    "session_uuid",
    "SessionUuid",
    "session_id",
    "SESSIONID",
)
_DELIMITADORES = (
    ("", ""),
    ('"', '"'),
    ("'", "'"),
    ("<", ">"),
    ("[", "]"),
    ("(", ")"),
    ("{", "}"),
)
_UNICODE_SINTETICO = tuple("açãoÁÉÍÓÚçãõΩЖ東京🙂")


@dataclass(frozen=True, slots=True)
class _CasoOrk:
    texto: str
    formato: str
    severidade_original: str
    possui_offset: bool


def _rotular(nome: str, valor: str, delimitador: tuple[str, str]) -> str:
    abertura, fechamento = delimitador
    return f"{nome}={abertura}{valor}{fechamento}"


@st.composite
def _casos_ork_interpretados(draw: st.DrawFn) -> _CasoOrk:
    formato = draw(st.sampled_from(_FORMATOS))
    timestamp = draw(ork_timestamps()).original
    possui_offset = formato == "ork-real" or draw(st.booleans())
    if not possui_offset:
        timestamp = timestamp[:-6]

    severidade = draw(st.sampled_from(_NIVEIS))
    valores_chamada = draw(
        st.lists(
            opaque_values("CALL", min_bytes=3, max_bytes=10),
            min_size=2,
            max_size=2,
            unique=True,
        )
    )
    uuid_sessao = str(draw(st.uuids(version=4)))
    if draw(st.booleans()):
        uuid_sessao = uuid_sessao.upper()

    delimitadores = draw(
        st.lists(
            st.sampled_from(_DELIMITADORES),
            min_size=3,
            max_size=3,
        )
    )
    rotulo_sessao = draw(st.sampled_from(_ROTULOS_SESSAO))
    campos = (
        _rotular("TelecomCallId", valores_chamada[0], delimitadores[0]),
        _rotular("CallId", valores_chamada[1], delimitadores[1]),
        _rotular(rotulo_sessao, uuid_sessao, delimitadores[2]),
    )
    campos_ordenados = draw(st.permutations(campos))
    trecho_unicode = draw(
        st.text(alphabet=_UNICODE_SINTETICO, min_size=1, max_size=16)
    )
    mensagem = (
        f"evento sintético Unicode {trecho_unicode}; "
        + "; ".join(campos_ordenados)
    )
    if draw(st.booleans()):
        mensagem += "\ncontinuação sintética Ω | detalhe"

    if formato == "ork-real":
        host = (
            draw(opaque_values("HOST", min_bytes=3, max_bytes=8)).casefold()
            + ".synthetic.invalid"
        )
        processo = draw(
            opaque_values("PROCESS", min_bytes=3, max_bytes=8)
        ).casefold()
        pid = str(draw(st.integers(min_value=1, max_value=999_999)))
        logger = (
            "logger."
            + draw(
                opaque_values("LOGGER", min_bytes=3, max_bytes=8)
            ).casefold()
        )
        texto = (
            f"{timestamp} {host} {processo}[{pid}]: "
            f"{severidade} - {logger} - {mensagem}"
        )
    else:
        texto = f"{timestamp} | {severidade} | {mensagem}"

    assert_no_raw_source_reference(texto)
    return _CasoOrk(
        texto=texto,
        formato=formato,
        severidade_original=severidade,
        possui_offset=possui_offset,
    )


_CASOS_ORK: SearchStrategy[_CasoOrk] = _casos_ork_interpretados()


def _assinatura_semantica(entrada: EntradaDeLog) -> tuple[object, ...]:
    return (
        entrada.aplicacao,
        entrada.interpretada,
        entrada.carimbo_de_tempo,
        entrada.nivel_de_severidade,
        entrada.mensagem,
        entrada.timestamp_original,
        entrada.timestamp_normalizado,
        entrada.precisao_fracionaria,
        entrada.origem_evento,
        entrada.formato_origem,
        entrada.falhas,
    )


# Feature: log-analyzer-phase-2, Property 8: Round-trip ORK
@given(caso=_CASOS_ORK)
@settings(max_examples=100)
def test_property_08_roundtrip_ork(caso: _CasoOrk) -> None:
    """Imprimir e reinterpretar preserva toda a estrutura ORK interpretada.

    **Validates: Requirements 5.5**
    """

    parser = OrkParser()
    primeira = parser.interpretar_entrada(caso.texto)

    assert primeira.interpretada is True
    assert primeira.formato_origem == caso.formato

    segunda = parser.interpretar_entrada(parser.imprimir_entrada(primeira))

    event(f"formato={caso.formato}")
    event(f"severidade_canonica={caso.severidade_original.isupper()}")
    if caso.formato == "ork-legado":
        event(f"legado_com_offset={caso.possui_offset}")

    assert segunda.interpretada is True
    assert _assinatura_semantica(segunda) == _assinatura_semantica(primeira)
    assert segunda.campos_estruturados == primeira.campos_estruturados
    assert segunda.identificadores == primeira.identificadores
