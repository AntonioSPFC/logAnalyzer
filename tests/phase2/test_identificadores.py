"""Testes focados da normalização tipada de identificadores.

Validates: Requirements 2.2, 2.3, 2.4, 3.2, 3.3, 7.1, 7.6, 8.2.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from log_analyzer.core.identificadores import NormalizadorDeIdentificador
from log_analyzer.core.modelos import Proveniencia, TipoIdentificador


def _proveniencia(nome_campo: str, *, regra: str | None = "extrator-teste-v3") -> Proveniencia:
    return Proveniencia(
        arquivo_token="<ARQUIVO_SINTETICO_1>",
        entrada_id="entrada-sintetica-7",
        linha_inicial=7,
        linha_final=8,
        span_inicial=19,
        span_final=57,
        nome_campo=nome_campo,
        regra_extracao=regra,
    )


@pytest.mark.parametrize(
    ("tipo", "nome_campo"),
    (
        (TipoIdentificador.CHAMADA_EXTERNA, "SipUser"),
        (TipoIdentificador.TELECOM_CALL_ID, "TelecomCallId"),
        (TipoIdentificador.CALL_ID, "CallId"),
    ),
)
def test_identificadores_de_chamada_compartilham_namespace_e_preservam_auditoria(
    tipo: TipoIdentificador,
    nome_campo: str,
) -> None:
    normalizador = NormalizadorDeIdentificador()
    proveniencia = _proveniencia(nome_campo)
    valor_original = '  ["SYN-Call-ÁBC-001"]\t'

    identificador = normalizador.normalizar(
        tipo,
        nome_campo,
        valor_original,
        proveniencia,
    )

    assert identificador.tipo is tipo
    assert identificador.namespace_comparacao == "chamada_externa"
    assert identificador.nome_campo == nome_campo
    assert identificador.valor_original == valor_original
    assert identificador.valor_normalizado == "syn-call-ábc-001"
    assert identificador.proveniencia is proveniencia
    assert identificador.proveniencia.span_inicial == 19
    assert identificador.proveniencia.span_final == 57
    assert identificador.proveniencia.entrada_id == "entrada-sintetica-7"
    assert identificador.proveniencia.arquivo_token == "<ARQUIVO_SINTETICO_1>"
    assert identificador.proveniencia.regra_extracao == "extrator-teste-v3"


@pytest.mark.parametrize(
    ("valor_original", "esperado"),
    (
        ("  'SYN-ID-(A B)-01'  ", "syn-id-(a b)-01"),
        ('"SYN-ID-01', '"syn-id-01'),
        ("`SYN-ID-01`", "`syn-id-01`"),
        ("SYN-ID-01,", "syn-id-01,"),
        ("SYN<INNER>ID", "syn<inner>id"),
        ("  SYN-A\tSYN-B  ", "syn-a\tsyn-b"),
    ),
)
def test_remove_somente_sintaxe_externa_aprovada(
    valor_original: str,
    esperado: str,
) -> None:
    identificador = NormalizadorDeIdentificador().normalizar(
        TipoIdentificador.CALL_ID,
        "CallId",
        valor_original,
        _proveniencia("CallId"),
    )

    assert identificador.valor_normalizado == esperado


def test_uuid_e_validado_somente_quando_o_tipo_declara_contexto_uuid() -> None:
    normalizador = NormalizadorDeIdentificador()
    uuid_sintetico = str(uuid4()).upper()

    uuid_canal = normalizador.normalizar(
        TipoIdentificador.UUID_CANAL,
        "ChannelUuid",
        f"{{{uuid_sintetico}}}",
        _proveniencia("ChannelUuid"),
    )
    identificador_opaco = normalizador.normalizar(
        TipoIdentificador.CALL_ID,
        "SessionUuid",
        "'SYN-NAO-E-UUID'",
        _proveniencia("SessionUuid"),
    )

    assert uuid_canal.valor_normalizado == uuid_sintetico.casefold()
    assert "-" in uuid_canal.valor_normalizado
    assert identificador_opaco.valor_normalizado == "syn-nao-e-uuid"

    with pytest.raises(ValueError, match="UUID válido"):
        normalizador.normalizar(
            TipoIdentificador.UUID_SESSAO,
            "SessionUuid",
            "SYN-NAO-E-UUID",
            _proveniencia("SessionUuid"),
        )


def test_uuid_de_canal_e_sessao_permanecem_semanticamente_distintos() -> None:
    normalizador = NormalizadorDeIdentificador()
    uuid_sintetico = str(uuid4())

    canal = normalizador.normalizar(
        TipoIdentificador.UUID_CANAL,
        "ChannelUuid",
        uuid_sintetico,
        _proveniencia("ChannelUuid"),
    )
    sessao = normalizador.normalizar(
        TipoIdentificador.UUID_SESSAO,
        "SessionUuid",
        uuid_sintetico,
        _proveniencia("SessionUuid"),
    )

    assert canal.valor_normalizado == sessao.valor_normalizado
    assert canal.tipo is not sessao.tipo
    assert canal.namespace_comparacao == "uuid_canal"
    assert sessao.namespace_comparacao == "uuid_sessao"


def test_contexto_auditavel_incompleto_ou_incoerente_e_rejeitado() -> None:
    normalizador = NormalizadorDeIdentificador()

    with pytest.raises(ValueError, match="corresponder"):
        normalizador.normalizar(
            TipoIdentificador.CALL_ID,
            "CallId",
            "SYN-CALL-001",
            _proveniencia("TelecomCallId"),
        )

    with pytest.raises(ValueError, match="regra_extracao"):
        normalizador.normalizar(
            TipoIdentificador.CALL_ID,
            "CallId",
            "SYN-CALL-001",
            _proveniencia("CallId", regra=None),
        )


@pytest.mark.parametrize("valor", ("   ", "''", '""', "[ ]"))
def test_valor_vazio_apos_sintaxe_externa_e_rejeitado(valor: str) -> None:
    with pytest.raises(ValueError, match="valor"):
        NormalizadorDeIdentificador().normalizar(
            TipoIdentificador.CALL_ID,
            "CallId",
            valor,
            _proveniencia("CallId"),
        )
