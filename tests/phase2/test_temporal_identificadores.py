"""Testes unitários de tempo e identificadores tipados da Fase 2.

Os identificadores, inclusive UUIDs e metadados de proveniência, são gerados
em tempo de teste. Os timestamps são exemplos sintéticos e não há acesso a
fontes externas.

Validates: Requirements 6.1, 6.2, 6.3, 6.7, 6.8, 7.1, 7.6, 8.2.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from log_analyzer.core.identificadores import NormalizadorDeIdentificador
from log_analyzer.core.modelos import EntradaDeLog, Proveniencia, TipoIdentificador
from log_analyzer.core.ordenacao import particionar_linha_do_tempo
from log_analyzer.core.temporal import NormalizadorTemporal


def _proveniencia(nome_campo: str, *, linha: int = 1) -> Proveniencia:
    """Cria metadados sintéticos e únicos para cada extração do teste."""

    return Proveniencia(
        arquivo_token=f"<ARQUIVO_{uuid4().hex}>",
        entrada_id=f"entrada-{uuid4().hex}",
        linha_inicial=linha,
        linha_final=linha,
        span_inicial=0,
        span_final=32,
        nome_campo=nome_campo,
        regra_extracao="regra-unitaria-v1",
    )


def _identificador_opaco() -> str:
    """Gera um identificador de chamada opaco, sintético e não UUID."""

    return f"CALL-{uuid4().hex}-ABCDEF"


@pytest.mark.parametrize(
    ("original", "esperado", "texto_utc", "precisao"),
    (
        (
            "2032-06-15T10:20:30.123456-03:00",
            datetime(2032, 6, 15, 13, 20, 30, 123456, tzinfo=timezone.utc),
            "2032-06-15T13:20:30.123456+00:00",
            6,
        ),
        (
            "2032-06-15T10:20:30.12+05:30",
            datetime(2032, 6, 15, 4, 50, 30, 120000, tzinfo=timezone.utc),
            "2032-06-15T04:50:30.12+00:00",
            2,
        ),
        (
            "2032-06-15T10:20:30Z",
            datetime(2032, 6, 15, 10, 20, 30, tzinfo=timezone.utc),
            "2032-06-15T10:20:30+00:00",
            0,
        ),
    ),
    ids=("offset-negativo", "offset-positivo-fracionario", "utc-z"),
)
def test_ork_respeita_offset_e_produz_utc_com_precisao_original(
    original: str,
    esperado: datetime,
    texto_utc: str,
    precisao: int,
) -> None:
    resultado = NormalizadorTemporal().normalizar_ork(
        original,
        _proveniencia("timestamp"),
    )

    assert resultado.resolvido
    assert resultado.timestamp_original == original
    assert resultado.timestamp_normalizado == esperado
    assert resultado.timestamp_normalizado is not None
    assert resultado.timestamp_normalizado.tzinfo is timezone.utc
    assert resultado.precisao_fracionaria == precisao
    assert resultado.timestamp_normalizado_texto == texto_utc
    assert resultado.falhas == ()


@pytest.mark.parametrize("precisao", range(7))
def test_vpl_e_ork_preservam_precisao_de_zero_a_seis_digitos(
    precisao: int,
) -> None:
    digitos = "120450"[:precisao]
    fracao = f".{digitos}" if digitos else ""
    original_vpl = f"2032-07-08 09:10:11{fracao}"
    original_ork = f"2032-07-08T12:10:11{fracao}Z"
    proveniencia_vpl = _proveniencia("timestamp_vpl")
    proveniencia_ork = _proveniencia("timestamp_ork")

    vpl = NormalizadorTemporal().normalizar_vpl(
        original_vpl,
        proveniencia_vpl,
    )
    ork = NormalizadorTemporal().normalizar_ork(
        original_ork,
        proveniencia_ork,
    )

    texto_esperado = f"2032-07-08T12:10:11{fracao}+00:00"
    assert vpl.timestamp_normalizado == ork.timestamp_normalizado
    assert vpl.timestamp_normalizado_texto == texto_esperado
    assert ork.timestamp_normalizado_texto == texto_esperado
    assert vpl.precisao_fracionaria == precisao
    assert ork.precisao_fracionaria == precisao
    assert vpl.timestamp_original == original_vpl
    assert ork.timestamp_original == original_ork


@pytest.mark.parametrize(
    ("aplicacao", "original"),
    (
        ("VPL", "2032-07-08 09:10:11.1234567"),
        ("ORK", "2032-07-08T09:10:11.1234567-03:00"),
    ),
)
def test_precisao_superior_a_seis_falha_sem_truncamento(
    aplicacao: str,
    original: str,
) -> None:
    proveniencia = _proveniencia("timestamp")

    resultado = NormalizadorTemporal().normalizar(
        aplicacao,
        original,
        proveniencia,
    )

    assert not resultado.resolvido
    assert resultado.timestamp_original == original
    assert resultado.timestamp_normalizado is None
    assert resultado.precisao_fracionaria is None
    assert resultado.falha is not None
    assert resultado.falha.codigo == (
        NormalizadorTemporal.CODIGO_PRECISAO_NAO_SUPORTADA
    )
    assert resultado.falha.proveniencia is proveniencia
    assert original not in resultado.falha.detalhe_seguro


@pytest.mark.parametrize(
    ("original", "codigo"),
    (
        (
            "2018-11-04 00:30:00",
            NormalizadorTemporal.CODIGO_HORARIO_INEXISTENTE,
        ),
        (
            "2018-02-17 23:30:00",
            NormalizadorTemporal.CODIGO_HORARIO_AMBIGUO,
        ),
    ),
    ids=("inicio-horario-de-verao", "fim-horario-de-verao"),
)
def test_vpl_rejeita_horarios_de_transicao_sem_escolha_silenciosa(
    original: str,
    codigo: str,
) -> None:
    proveniencia = _proveniencia("timestamp")

    resultado = NormalizadorTemporal().normalizar_vpl(original, proveniencia)

    assert not resultado.resolvido
    assert resultado.timestamp_original == original
    assert resultado.timestamp_normalizado is None
    assert resultado.precisao_fracionaria == 0
    assert resultado.falha is not None
    assert resultado.falha.codigo == codigo
    assert resultado.falha.proveniencia is proveniencia
    assert original not in resultado.falha.detalhe_seguro


@pytest.mark.parametrize(
    ("original", "esperado"),
    (
        (
            "2018-11-03 23:30:00",
            datetime(2018, 11, 4, 2, 30, tzinfo=timezone.utc),
        ),
        (
            "2018-11-04 01:30:00",
            datetime(2018, 11, 4, 3, 30, tzinfo=timezone.utc),
        ),
        (
            "2018-02-17 22:30:00",
            datetime(2018, 2, 18, 0, 30, tzinfo=timezone.utc),
        ),
        (
            "2018-02-18 00:30:00",
            datetime(2018, 2, 18, 3, 30, tzinfo=timezone.utc),
        ),
    ),
    ids=("antes-inicio", "depois-inicio", "antes-fim", "depois-fim"),
)
def test_vpl_aplica_regras_historicas_nas_bordas_das_transicoes(
    original: str,
    esperado: datetime,
) -> None:
    resultado = NormalizadorTemporal().normalizar_vpl(
        original,
        _proveniencia("timestamp"),
    )

    assert resultado.resolvido
    assert resultado.timestamp_original == original
    assert resultado.timestamp_normalizado == esperado
    assert resultado.timestamp_normalizado is not None
    assert resultado.timestamp_normalizado.tzinfo is timezone.utc


def test_timestamp_ork_legado_sem_offset_fica_fora_da_cronologia_com_falha() -> None:
    original = "2032-07-08T09:10:11.123"
    proveniencia = _proveniencia("timestamp")
    resultado = NormalizadorTemporal().normalizar_ork(original, proveniencia)

    assert not resultado.resolvido
    assert resultado.timestamp_original == original
    assert resultado.timestamp_normalizado is None
    assert resultado.falha is not None
    assert resultado.falha.codigo == NormalizadorTemporal.CODIGO_OFFSET_AUSENTE
    assert resultado.falha.proveniencia is proveniencia
    assert original not in resultado.falha.detalhe_seguro

    entrada = EntradaDeLog(
        texto_original="evento temporal sintético",
        aplicacao="ORK",
        ordem_de_leitura=0,
        interpretada=True,
        carimbo_de_tempo=datetime(2032, 7, 8, 9, 10, 11, 123000),
        nivel_de_severidade="INFO",
        mensagem="evento temporal sintético",
        entrada_id=proveniencia.entrada_id,
        arquivo_token=proveniencia.arquivo_token,
        posicao_inicial=proveniencia.linha_inicial,
        posicao_final=proveniencia.linha_final,
        timestamp_original=resultado.timestamp_original,
        timestamp_normalizado=resultado.timestamp_normalizado,
        precisao_fracionaria=resultado.precisao_fracionaria,
        falhas=resultado.falhas,
    )

    linha_do_tempo, sem_ordenacao_temporal = particionar_linha_do_tempo([entrada])

    assert linha_do_tempo == []
    assert sem_ordenacao_temporal == [entrada]
    assert entrada.timestamp_original == original
    assert entrada.falhas == resultado.falhas


@pytest.mark.parametrize(
    ("abertura", "fechamento"),
    (
        ('"', '"'),
        ("'", "'"),
        ("<", ">"),
        ("[", "]"),
        ("(", ")"),
        ("{", "}"),
    ),
)
def test_identificador_remove_delimitadores_aprovados_e_aplica_casefold(
    abertura: str,
    fechamento: str,
) -> None:
    valor_sem_sintaxe = _identificador_opaco().upper()
    valor_original = f" \t{abertura}{valor_sem_sintaxe}{fechamento}\n"
    proveniencia = _proveniencia("CallId")

    identificador = NormalizadorDeIdentificador().normalizar(
        TipoIdentificador.CALL_ID,
        "CallId",
        valor_original,
        proveniencia,
    )

    assert identificador.tipo is TipoIdentificador.CALL_ID
    assert identificador.namespace_comparacao == "chamada_externa"
    assert identificador.nome_campo == "CallId"
    assert identificador.valor_original == valor_original
    assert identificador.valor_normalizado == valor_sem_sintaxe.casefold()
    assert identificador.proveniencia is proveniencia


def test_identificador_preserva_delimitadores_nao_aprovados_e_caracteres_internos() -> None:
    valor_gerado = _identificador_opaco().upper()
    valor_original = f"`{valor_gerado}-(INTERNO)`"

    identificador = NormalizadorDeIdentificador().normalizar(
        TipoIdentificador.CALL_ID,
        "CallId",
        valor_original,
        _proveniencia("CallId"),
    )

    assert identificador.valor_original == valor_original
    assert identificador.valor_normalizado == valor_original.casefold()
    assert "-(interno)" in identificador.valor_normalizado


def test_uuid_e_validado_exclusivamente_em_contexto_tipado() -> None:
    normalizador = NormalizadorDeIdentificador()
    uuid_gerado = str(uuid4()).upper()
    valor_nao_uuid = f"OPAQUE-{uuid4().hex}"

    uuid_sessao = normalizador.normalizar(
        TipoIdentificador.UUID_SESSAO,
        "SessionUuid",
        f"{{{uuid_gerado}}}",
        _proveniencia("SessionUuid"),
    )
    opaco_em_contexto_nao_uuid = normalizador.normalizar(
        TipoIdentificador.CALL_ID,
        "CallId",
        valor_nao_uuid,
        _proveniencia("CallId"),
    )

    assert uuid_sessao.valor_original == f"{{{uuid_gerado}}}"
    assert uuid_sessao.valor_normalizado == uuid_gerado.casefold()
    assert uuid_sessao.namespace_comparacao == "uuid_sessao"
    assert opaco_em_contexto_nao_uuid.valor_normalizado == valor_nao_uuid.casefold()

    with pytest.raises(ValueError, match="UUID válido"):
        normalizador.normalizar(
            TipoIdentificador.UUID_CANAL,
            "ChannelUuid",
            valor_nao_uuid,
            _proveniencia("ChannelUuid"),
        )


def test_mesmo_valor_textual_nao_colide_entre_namespaces() -> None:
    normalizador = NormalizadorDeIdentificador()
    valor_gerado = str(uuid4()).upper()

    chamada = normalizador.normalizar(
        TipoIdentificador.CALL_ID,
        "CallId",
        valor_gerado,
        _proveniencia("CallId", linha=1),
    )
    canal = normalizador.normalizar(
        TipoIdentificador.UUID_CANAL,
        "ChannelUuid",
        valor_gerado,
        _proveniencia("ChannelUuid", linha=2),
    )
    sessao = normalizador.normalizar(
        TipoIdentificador.UUID_SESSAO,
        "SessionUuid",
        valor_gerado,
        _proveniencia("SessionUuid", linha=3),
    )

    assert chamada.valor_normalizado == canal.valor_normalizado
    assert canal.valor_normalizado == sessao.valor_normalizado
    assert {chamada.namespace_comparacao, canal.namespace_comparacao, sessao.namespace_comparacao} == {
        "chamada_externa",
        "uuid_canal",
        "uuid_sessao",
    }
    assert len(
        {
            (identificador.tipo, identificador.namespace_comparacao, identificador.valor_normalizado)
            for identificador in (chamada, canal, sessao)
        }
    ) == 3
    assert chamada != canal
    assert canal != sessao
    assert chamada != sessao
