"""Property 3 do parsing ORK real completo e tipado.

Todos os campos, identificadores e UUIDs são sintéticos e gerados em memória.
O teste não lê arquivos, fontes locais, banco de dados ou serviços externos.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import timedelta, timezone

from hypothesis import given, settings, strategies as st
from hypothesis.strategies import SearchStrategy

from log_analyzer.apps.ork import OrkParser
from log_analyzer.core.modelos import TipoIdentificador
from tests.phase2.strategies.fields import opaque_values
from tests.phase2.strategies.timestamps import TimestampSpec, ork_timestamps


_CAMPOS_CABECALHO = frozenset(
    {"timestamp", "host", "processo", "pid", "severidade", "logger", "mensagem"}
)
_NIVEIS_ORK = ("DEBUG", "INFO", "WARN", "ERROR", "FATAL")
_ROTULOS_SESSAO = ("session_uuid", "SessionUuid", "session_id", "SESSIONID")
_DELIMITADORES_EXTERNOS = (
    ("", ""),
    ('"', '"'),
    ("'", "'"),
    ("<", ">"),
    ("[", "]"),
    ("(", ")"),
    ("{", "}"),
)
_SEPARADORES_CAMPO = ("=", ":", " = ", " : ", "= ", ": ")
_ALFABETO_UNICODE_SEGURO = " áéíóúçãõΩЖ東京🙂0123456789_"


@dataclass(frozen=True, slots=True)
class _IdentificadorEsperado:
    tipo: TipoIdentificador
    namespace: str
    nome_campo: str
    valor_original: str
    valor_normalizado: str
    regra_extracao: str


@dataclass(frozen=True, slots=True)
class _CasoOrkReal:
    texto: str
    timestamp: TimestampSpec
    host: str
    processo: str
    pid: str
    severidade_original: str
    logger: str
    mensagem: str
    identificadores: tuple[_IdentificadorEsperado, ...]
    valores_incidentais_normalizados: tuple[str, ...]


def _campo_rotulado(
    draw: st.DrawFn,
    nome: str,
    valor_sem_sintaxe: str,
) -> tuple[str, str]:
    abertura, fechamento = draw(st.sampled_from(_DELIMITADORES_EXTERNOS))
    valor_original = f"{abertura}{valor_sem_sintaxe}{fechamento}"
    aspas_nome = draw(st.sampled_from(("", '"', "'")))
    separador = draw(st.sampled_from(_SEPARADORES_CAMPO))
    texto = f"{aspas_nome}{nome}{aspas_nome}{separador}{valor_original}"
    return texto, valor_original


@st.composite
def _casos_ork_reais(draw: st.DrawFn) -> _CasoOrkReal:
    timestamp = draw(ork_timestamps())
    host_token = draw(opaque_values("HOST", min_bytes=3, max_bytes=10))
    processo_token = draw(opaque_values("PROCESS", min_bytes=3, max_bytes=10))
    logger_token = draw(opaque_values("LOGGER", min_bytes=3, max_bytes=10))
    host = f"{host_token.casefold()}.invalid"
    processo = processo_token.casefold()
    pid = str(draw(st.integers(min_value=1, max_value=999_999)))

    nivel = draw(st.sampled_from(_NIVEIS_ORK))
    severidade_original = nivel.lower() if draw(st.booleans()) else nivel

    valores_chamada = draw(
        st.lists(
            opaque_values("CALL", min_bytes=4, max_bytes=12),
            min_size=4,
            max_size=4,
            unique=True,
        )
    )
    uuids = draw(
        st.lists(
            st.uuids(version=4),
            min_size=2,
            max_size=2,
            unique=True,
        )
    )
    uuid_sessao = str(uuids[0])
    if draw(st.booleans()):
        uuid_sessao = uuid_sessao.upper()
    uuid_incidental = str(uuids[1])

    telecom_texto, telecom_original = _campo_rotulado(
        draw,
        "TelecomCallId",
        valores_chamada[0],
    )
    call_texto, call_original = _campo_rotulado(
        draw,
        "CallId",
        valores_chamada[1],
    )
    rotulo_sessao = draw(st.sampled_from(_ROTULOS_SESSAO))
    sessao_texto, sessao_original = _campo_rotulado(
        draw,
        rotulo_sessao,
        uuid_sessao,
    )

    telecom_esperado = _IdentificadorEsperado(
        tipo=TipoIdentificador.TELECOM_CALL_ID,
        namespace="chamada_externa",
        nome_campo="TelecomCallId",
        valor_original=telecom_original,
        valor_normalizado=valores_chamada[0].casefold(),
        regra_extracao="ork.telecom-identificador-chamada.v1",
    )
    call_esperado = _IdentificadorEsperado(
        tipo=TipoIdentificador.CALL_ID,
        namespace="chamada_externa",
        nome_campo="CallId",
        valor_original=call_original,
        valor_normalizado=valores_chamada[1].casefold(),
        regra_extracao="ork.identificador-chamada.v1",
    )
    sessao_esperada = _IdentificadorEsperado(
        tipo=TipoIdentificador.UUID_SESSAO,
        namespace="uuid_sessao",
        nome_campo=rotulo_sessao,
        valor_original=sessao_original,
        valor_normalizado=uuid_sessao.casefold(),
        regra_extracao="ork.uuid-sessao-rotulado.v1",
    )

    campos_chamada = [
        (telecom_texto, telecom_esperado),
        (call_texto, call_esperado),
    ]
    if draw(st.booleans()):
        campos_chamada.reverse()

    logger_base = (
        f"logger.{logger_token.casefold()}.açãoΩ.{uuid_incidental}"
    )
    sessao_no_logger = draw(st.booleans())
    logger = (
        f"{logger_base} {sessao_texto}"
        if sessao_no_logger
        else logger_base
    )

    campos_mensagem = list(campos_chamada)
    if not sessao_no_logger:
        posicao_sessao = draw(
            st.integers(min_value=0, max_value=len(campos_mensagem))
        )
        campos_mensagem.insert(
            posicao_sessao,
            (sessao_texto, sessao_esperada),
        )

    complemento_unicode = draw(
        st.text(
            alphabet=_ALFABETO_UNICODE_SEGURO,
            min_size=0,
            max_size=24,
        )
    )
    partes_mensagem = [
        f"Evento sintético Unicode ação Ω 東京 {complemento_unicode}".rstrip(),
        *(texto for texto, _ in campos_mensagem),
        f"CorrelationId={valores_chamada[2]}",
        f"telecomcallid={valores_chamada[3]}",
        f"SessionToken={uuid_incidental}",
        f"UUID incidental {uuid_incidental}",
        "fim✓",
    ]
    mensagem = "; ".join(partes_mensagem)
    texto = (
        f"{timestamp.original} {host} {processo}[{pid}]: "
        f"{severidade_original} - {logger} - {mensagem}"
    )

    identificadores = [telecom_esperado, call_esperado, sessao_esperada]
    identificadores.sort(
        key=lambda esperado: texto.index(esperado.valor_original)
    )
    return _CasoOrkReal(
        texto=texto,
        timestamp=timestamp,
        host=host,
        processo=processo,
        pid=pid,
        severidade_original=severidade_original,
        logger=logger,
        mensagem=mensagem,
        identificadores=tuple(identificadores),
        valores_incidentais_normalizados=(
            valores_chamada[2].casefold(),
            valores_chamada[3].casefold(),
            uuid_incidental.casefold(),
        ),
    )


_CASOS_ORK_REAIS: SearchStrategy[_CasoOrkReal] = _casos_ork_reais()


# Feature: log-analyzer-phase-2, Property 3: Parsing ORK completo e tipado
@given(caso=_CASOS_ORK_REAIS)
@settings(max_examples=100)
def test_property_03_parsing_ork_completo_e_tipado(caso: _CasoOrkReal) -> None:
    """O perfil real preserva campos e extrai somente rótulos aprovados.

    **Validates: Requirements 3.1, 3.2, 3.3, 3.5, 7.1**
    """

    entrada = OrkParser().interpretar_entrada(caso.texto)

    assert entrada.interpretada is True
    assert entrada.aplicacao == "ORK"
    assert entrada.formato_origem == "ork-real"
    assert entrada.texto_original == caso.texto
    assert entrada.entrada_id == "<ARQUIVO_1>:entrada:0"
    assert entrada.arquivo_token == "<ARQUIVO_1>"
    assert (entrada.posicao_inicial, entrada.posicao_final) == (1, 1)
    assert entrada.falhas == ()

    assert entrada.timestamp_original == caso.timestamp.original
    assert entrada.carimbo_de_tempo == caso.timestamp.source_datetime
    assert entrada.carimbo_de_tempo is not None
    assert caso.timestamp.offset_minutes is not None
    assert entrada.carimbo_de_tempo.utcoffset() == timedelta(
        minutes=caso.timestamp.offset_minutes
    )
    assert entrada.timestamp_normalizado == caso.timestamp.expected_utc
    assert entrada.timestamp_normalizado is not None
    assert entrada.timestamp_normalizado.tzinfo is timezone.utc
    assert entrada.precisao_fracionaria == caso.timestamp.precision

    assert entrada.nivel_de_severidade == caso.severidade_original.upper()
    assert entrada.origem_evento == caso.logger
    assert entrada.mensagem == caso.mensagem
    assert "ação Ω 東京" in entrada.mensagem
    assert "açãoΩ" in entrada.origem_evento

    campos_cabecalho = {
        campo.nome: campo.valor_original
        for campo in entrada.campos_estruturados
        if campo.nome in _CAMPOS_CABECALHO
    }
    assert campos_cabecalho == {
        "timestamp": caso.timestamp.original,
        "host": caso.host,
        "processo": caso.processo,
        "pid": caso.pid,
        "severidade": caso.severidade_original,
        "logger": caso.logger,
        "mensagem": caso.mensagem,
    }
    assert Counter(
        campo.nome
        for campo in entrada.campos_estruturados
        if campo.nome in _CAMPOS_CABECALHO
    ) == Counter(_CAMPOS_CABECALHO)

    esperado_campos_identificadores = Counter(
        (esperado.nome_campo, esperado.valor_original)
        for esperado in caso.identificadores
    )
    observado_campos_identificadores = Counter(
        (campo.nome, campo.valor_original)
        for campo in entrada.campos_estruturados
        if campo.nome not in _CAMPOS_CABECALHO
    )
    assert observado_campos_identificadores == esperado_campos_identificadores

    assinatura_observada = tuple(
        (
            identificador.tipo,
            identificador.namespace_comparacao,
            identificador.nome_campo,
            identificador.valor_original,
            identificador.valor_normalizado,
        )
        for identificador in entrada.identificadores
    )
    assinatura_esperada = tuple(
        (
            esperado.tipo,
            esperado.namespace,
            esperado.nome_campo,
            esperado.valor_original,
            esperado.valor_normalizado,
        )
        for esperado in caso.identificadores
    )
    assert assinatura_observada == assinatura_esperada

    for identificador, esperado in zip(
        entrada.identificadores,
        caso.identificadores,
        strict=True,
    ):
        proveniencia = identificador.proveniencia
        assert proveniencia.arquivo_token == entrada.arquivo_token
        assert proveniencia.entrada_id == entrada.entrada_id
        assert (proveniencia.linha_inicial, proveniencia.linha_final) == (1, 1)
        assert proveniencia.nome_campo == esperado.nome_campo
        assert proveniencia.regra_extracao == esperado.regra_extracao
        assert proveniencia.span_inicial is not None
        assert proveniencia.span_final is not None
        assert caso.texto[
            proveniencia.span_inicial : proveniencia.span_final
        ] == esperado.valor_original

        campos_correspondentes = [
            campo
            for campo in entrada.campos_estruturados
            if campo.nome == esperado.nome_campo
            and campo.valor_original == esperado.valor_original
        ]
        assert len(campos_correspondentes) == 1
        assert proveniencia is campos_correspondentes[0].proveniencia

    normalizados_observados = {
        identificador.valor_normalizado
        for identificador in entrada.identificadores
    }
    assert len(entrada.identificadores) == 3
    assert all(
        valor_incidental not in normalizados_observados
        for valor_incidental in caso.valores_incidentais_normalizados
    )

    for campo in entrada.campos_estruturados:
        proveniencia = campo.proveniencia
        assert proveniencia.nome_campo == campo.nome
        assert proveniencia.regra_extracao
        assert proveniencia.span_inicial is not None
        assert proveniencia.span_final is not None
        assert caso.texto[
            proveniencia.span_inicial : proveniencia.span_final
        ] == campo.valor_original
