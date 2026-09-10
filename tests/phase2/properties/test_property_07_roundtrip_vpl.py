"""Property 7 do round-trip dos perfis VPL real e legado.

Todos os dados são sintéticos e gerados em memória. Nenhum arquivo, banco de
dados, serviço externo ou fonte real é consultado.
"""

from __future__ import annotations

from datetime import datetime
import string

from hypothesis import given, settings, strategies as st
from hypothesis.strategies import SearchStrategy

from log_analyzer.apps.vpl import VplParser
from log_analyzer.core.modelos import EntradaDeLog
from tests.phase2.strategies import (
    assert_no_raw_source_reference,
    opaque_values,
    vpl_timestamps,
)

_SEVERIDADES = ("DEBUG", "INFO", "NOTICE", "WARNING", "ERR", "CRIT", "ALERT")
_UNICODE_SINTETICO = tuple("áéíóúçãõÁÉÍÓÚÇÃÕΩЖŁ漢字🙂🚀")
_CARACTERES_ORIGEM = string.ascii_letters + string.digits + "_.:-"


def _uuid_sintetico() -> SearchStrategy[str]:
    return st.tuples(st.uuids(version=4), st.booleans()).map(
        lambda partes: (
            str(partes[0]).upper() if partes[1] else str(partes[0])
        )
    )


@st.composite
def _mensagens_vpl(draw: st.DrawFn) -> str:
    chamadas = draw(
        st.lists(
            opaque_values("CALL", min_bytes=2, max_bytes=8),
            min_size=3,
            max_size=3,
            unique=True,
        )
    )
    uuid_canal, uuid_sessao = draw(
        st.lists(
            _uuid_sintetico(),
            min_size=2,
            max_size=2,
            unique_by=str.casefold,
        )
    )
    unicode_sintetico = draw(
        st.text(alphabet=_UNICODE_SINTETICO, min_size=1, max_size=10)
    )
    nome_call_id = draw(st.sampled_from(("CALLID", "CallId", "call-id")))

    mensagem = (
        f"evento-sintetico-{unicode_sintetico} "
        f"{nome_call_id}=<{chamadas[0]}> "
        f"canal=sofia/internal/<{chamadas[1]}>@sip.synthetic.invalid "
        f"channel_uuid=<{uuid_canal}> session_uuid=<{uuid_sessao}>"
    )
    if draw(st.booleans()):
        terminador = draw(st.sampled_from(("\n", "\r\n")))
        mensagem += (
            f"{terminador}continuacao-sintetica "
            f"CALLID=<{chamadas[2]}>"
        )
    return mensagem


def _percentuais_vpl() -> SearchStrategy[str]:
    return st.tuples(
        st.integers(min_value=0, max_value=100_000),
        st.one_of(
            st.none(),
            st.text(alphabet=string.digits, min_size=1, max_size=6),
        ),
    ).map(
        lambda partes: (
            f"{partes[0]}%"
            if partes[1] is None
            else f"{partes[0]}.{partes[1]}%"
        )
    )


def _origens_reais() -> SearchStrategy[str]:
    return st.tuples(
        st.sampled_from(tuple(string.ascii_letters)),
        st.text(alphabet=_CARACTERES_ORIGEM, min_size=0, max_size=16),
        st.integers(min_value=1, max_value=99_999),
    ).map(lambda partes: f"{partes[0]}{partes[1]}.c:{partes[2]}")


@st.composite
def _entradas_vpl_reais(draw: st.DrawFn) -> str:
    timestamp = draw(
        vpl_timestamps().filter(lambda valor: valor.precision >= 1)
    )
    percentual = draw(_percentuais_vpl())
    severidade = draw(st.sampled_from(_SEVERIDADES))
    origem = draw(_origens_reais())
    mensagem = draw(_mensagens_vpl())
    uuid_prefixo = draw(st.one_of(st.none(), _uuid_sintetico()))
    prefixo = "" if uuid_prefixo is None else f"{uuid_prefixo} "
    return (
        f"{prefixo}{timestamp.original} {percentual} "
        f"[{severidade}] {origem} {mensagem}"
    )


def _timestamp_legado(carimbo: datetime) -> str:
    milissegundos = carimbo.microsecond // 1_000
    return carimbo.strftime("%Y-%m-%d %H:%M:%S") + f".{milissegundos:03d}"


@st.composite
def _entradas_vpl_legadas(draw: st.DrawFn) -> str:
    timestamp = _timestamp_legado(draw(vpl_timestamps()).source_datetime)
    severidade = draw(st.sampled_from(_SEVERIDADES))
    # ``SYN_SRC_XX`` e ``vpl_source`` têm o mesmo tamanho. Assim, uma eventual
    # diferença semântica de origem não é confundida com mudança de spans.
    origem = draw(
        st.one_of(
            st.just("vpl_source"),
            opaque_values("SRC", min_bytes=1, max_bytes=1),
        )
    )
    mensagem = draw(_mensagens_vpl())
    return f"{timestamp} [{severidade}] {origem} {mensagem}"


def _estado_estruturado(entrada: EntradaDeLog) -> tuple[object, ...]:
    """Retorna todos os campos da entrada, exceto sua representação textual."""

    return (
        entrada.aplicacao,
        entrada.ordem_de_leitura,
        entrada.interpretada,
        entrada.carimbo_de_tempo,
        entrada.nivel_de_severidade,
        entrada.mensagem,
        entrada.categoria,
        entrada.correlacionada,
        entrada.entrada_id,
        entrada.arquivo_origem,
        entrada.arquivo_token,
        entrada.posicao_inicial,
        entrada.posicao_final,
        entrada.timestamp_original,
        entrada.timestamp_normalizado,
        entrada.precisao_fracionaria,
        entrada.origem_evento,
        entrada.formato_origem,
        entrada.campos_estruturados,
        entrada.identificadores,
        entrada.falhas,
        entrada.representacao_sanitizada,
    )


# Feature: log-analyzer-phase-2, Property 7: Round-trip VPL
@given(
    texto_real=_entradas_vpl_reais(),
    texto_legado=_entradas_vpl_legadas(),
)
@settings(max_examples=100)
def test_property_07_roundtrip_vpl(
    texto_real: str,
    texto_legado: str,
) -> None:
    """Parsear a impressão preserva campos e identificadores VPL.

    **Validates: Requirements 5.4**
    """

    assert_no_raw_source_reference((texto_real, texto_legado))
    parser = VplParser()

    for texto, perfil in (
        (texto_real, "vpl-real"),
        (texto_legado, "vpl-legado"),
    ):
        primeira = parser.interpretar_entrada(texto)
        assert primeira.interpretada is True
        assert primeira.formato_origem == perfil
        assert primeira.campos_estruturados
        assert primeira.identificadores

        impresso = parser.imprimir_entrada(primeira)
        segunda = parser.interpretar_entrada(impresso)

        assert segunda.interpretada is True
        assert segunda.texto_original == impresso
        assert _estado_estruturado(segunda) == _estado_estruturado(primeira)
