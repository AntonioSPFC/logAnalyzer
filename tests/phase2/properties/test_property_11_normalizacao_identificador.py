"""Property 11 da normalização auditável de identificadores da Fase 2.

Todos os identificadores, UUIDs e metadados de proveniência são gerados pelo
Hypothesis. O teste não lê arquivos, dados reais ou serviços externos.
"""

from __future__ import annotations

import string
from uuid import UUID

from hypothesis import given, settings, strategies as st

from log_analyzer.core.identificadores import NormalizadorDeIdentificador
from log_analyzer.core.modelos import Proveniencia, TipoIdentificador


_CAMPOS_CONHECIDOS = (
    (
        TipoIdentificador.CHAMADA_EXTERNA,
        "SipUser",
        "chamada_externa",
        False,
    ),
    (
        TipoIdentificador.TELECOM_CALL_ID,
        "TelecomCallId",
        "chamada_externa",
        False,
    ),
    (TipoIdentificador.CALL_ID, "CALLID", "chamada_externa", False),
    (TipoIdentificador.CALL_ID, "CallId", "chamada_externa", False),
    (TipoIdentificador.CALL_ID, "call-id", "chamada_externa", False),
    (TipoIdentificador.SIP, "SipCallId", "sip", False),
    (TipoIdentificador.UUID_CANAL, "ChannelUuid", "uuid_canal", True),
    (TipoIdentificador.UUID_SESSAO, "SessionUuid", "uuid_sessao", True),
)

_DELIMITADORES_EXTERNOS_APROVADOS = (
    ('"', '"'),
    ("'", "'"),
    ("<", ">"),
    ("[", "]"),
    ("(", ")"),
    ("{", "}"),
)

_SEGMENTO_OPACO = st.text(
    alphabet=string.ascii_letters + string.digits,
    min_size=1,
    max_size=12,
)
_ESPACO_EXTERNO = st.sampled_from(("", " ", "\t", "\n", " \t"))


# Feature: log-analyzer-phase-2, Property 11: Normalização de identificador é auditável e não colide semanticamente
@given(
    campo_conhecido=st.sampled_from(_CAMPOS_CONHECIDOS),
    valor_uuid=st.uuids(version=4),
    uuid_para_colisao=st.uuids(version=4),
    arquivo_uuid=st.uuids(version=4),
    regra_uuid=st.uuids(version=4),
    entradas_uuid=st.lists(
        st.uuids(version=4),
        min_size=4,
        max_size=4,
        unique=True,
    ),
    segmento_esquerdo=_SEGMENTO_OPACO,
    segmento_direito=_SEGMENTO_OPACO,
    camadas_externas=st.lists(
        st.sampled_from(_DELIMITADORES_EXTERNOS_APROVADOS),
        min_size=0,
        max_size=3,
    ),
    delimitadores_colisao=st.lists(
        st.sampled_from(_DELIMITADORES_EXTERNOS_APROVADOS),
        min_size=3,
        max_size=3,
    ),
    espacos_externos=st.tuples(_ESPACO_EXTERNO, _ESPACO_EXTERNO),
    linha_inicial=st.integers(min_value=1, max_value=100_000),
    extensao_linhas=st.integers(min_value=0, max_value=5),
    span_inicial=st.integers(min_value=0, max_value=10_000),
    versao_regra=st.integers(min_value=1, max_value=100),
)
@settings(max_examples=100)
def test_property_11_normalizacao_identificador_auditavel_sem_colisao(
    campo_conhecido: tuple[TipoIdentificador, str, str, bool],
    valor_uuid: UUID,
    uuid_para_colisao: UUID,
    arquivo_uuid: UUID,
    regra_uuid: UUID,
    entradas_uuid: list[UUID],
    segmento_esquerdo: str,
    segmento_direito: str,
    camadas_externas: list[tuple[str, str]],
    delimitadores_colisao: list[tuple[str, str]],
    espacos_externos: tuple[str, str],
    linha_inicial: int,
    extensao_linhas: int,
    span_inicial: int,
    versao_regra: int,
) -> None:
    """A normalização é limitada, auditável e mantém nós semânticos.

    **Validates: Requirements 7.1, 7.6, 8.2**
    """

    tipo, nome_campo, namespace_esperado, exige_uuid = campo_conhecido
    texto_uuid = str(valor_uuid).upper()
    if exige_uuid:
        valor_sem_sintaxe = texto_uuid
    else:
        valor_sem_sintaxe = (
            f"`{segmento_esquerdo.swapcase()}-{valor_uuid.hex.upper()} "
            f"[{segmento_direito.swapcase()}]`"
        )

    aberturas = "".join(abertura for abertura, _ in camadas_externas)
    fechamentos = "".join(
        fechamento for _, fechamento in reversed(camadas_externas)
    )
    valor_original = (
        f"{espacos_externos[0]}{aberturas}{valor_sem_sintaxe}"
        f"{fechamentos}{espacos_externos[1]}"
    )
    arquivo_token = f"<ARQUIVO_SINTETICO_{arquivo_uuid.hex}>"
    entrada_id = f"entrada-{entradas_uuid[0].hex}"
    regra_extracao = f"extrator-{regra_uuid.hex}-v{versao_regra}"
    linha_final = linha_inicial + extensao_linhas
    proveniencia = Proveniencia(
        arquivo_token=arquivo_token,
        entrada_id=entrada_id,
        linha_inicial=linha_inicial,
        linha_final=linha_final,
        span_inicial=span_inicial,
        span_final=span_inicial + len(valor_original),
        nome_campo=nome_campo,
        regra_extracao=regra_extracao,
    )

    identificador = NormalizadorDeIdentificador().normalizar(
        tipo,
        nome_campo,
        valor_original,
        proveniencia,
    )

    assert identificador.tipo is tipo
    assert identificador.namespace_comparacao == namespace_esperado
    assert identificador.nome_campo == nome_campo
    assert identificador.valor_original == valor_original
    assert identificador.valor_normalizado == valor_sem_sintaxe.casefold()
    assert identificador.proveniencia is proveniencia
    assert identificador.proveniencia == proveniencia
    assert (
        identificador.proveniencia.arquivo_token,
        identificador.proveniencia.entrada_id,
        identificador.proveniencia.linha_inicial,
        identificador.proveniencia.linha_final,
        identificador.proveniencia.span_inicial,
        identificador.proveniencia.span_final,
        identificador.proveniencia.nome_campo,
        identificador.proveniencia.regra_extracao,
    ) == (
        arquivo_token,
        entrada_id,
        linha_inicial,
        linha_final,
        span_inicial,
        span_inicial + len(valor_original),
        nome_campo,
        regra_extracao,
    )

    if exige_uuid:
        assert UUID(identificador.valor_normalizado) == valor_uuid
        assert identificador.valor_normalizado.count("-") == 4
    else:
        assert identificador.valor_normalizado.startswith("`")
        assert identificador.valor_normalizado.endswith("`")
        assert " [" in identificador.valor_normalizado
        assert identificador.valor_normalizado.count("-") >= 1
        assert valor_uuid.hex in identificador.valor_normalizado

    texto_colisao = str(uuid_para_colisao).upper()
    especificacoes_colisao = (
        (TipoIdentificador.CALL_ID, "CallId", "chamada_externa"),
        (TipoIdentificador.UUID_CANAL, "ChannelUuid", "uuid_canal"),
        (TipoIdentificador.UUID_SESSAO, "SessionUuid", "uuid_sessao"),
    )
    nos_colisao = []
    auditoria_colisao = []
    for indice, (tipo_no, campo_no, namespace_no) in enumerate(
        especificacoes_colisao
    ):
        abertura, fechamento = delimitadores_colisao[indice]
        original_no = f"{abertura}{texto_colisao}{fechamento}"
        proveniencia_no = Proveniencia(
            arquivo_token=arquivo_token,
            entrada_id=f"entrada-{entradas_uuid[indice + 1].hex}",
            linha_inicial=linha_inicial + indice,
            linha_final=linha_inicial + indice,
            span_inicial=span_inicial + indice,
            span_final=span_inicial + indice + len(original_no),
            nome_campo=campo_no,
            regra_extracao=(
                f"extrator-{regra_uuid.hex}-{tipo_no.value}-v{versao_regra}"
            ),
        )
        no = NormalizadorDeIdentificador().normalizar(
            tipo_no,
            campo_no,
            original_no,
            proveniencia_no,
        )
        assert no.namespace_comparacao == namespace_no
        nos_colisao.append(no)
        auditoria_colisao.append((original_no, proveniencia_no))

    assert {no.valor_normalizado for no in nos_colisao} == {
        texto_colisao.casefold()
    }
    assert {no.tipo for no in nos_colisao} == {
        TipoIdentificador.CALL_ID,
        TipoIdentificador.UUID_CANAL,
        TipoIdentificador.UUID_SESSAO,
    }
    assert {no.namespace_comparacao for no in nos_colisao} == {
        "chamada_externa",
        "uuid_canal",
        "uuid_sessao",
    }
    assert len(
        {
            (no.tipo, no.namespace_comparacao, no.valor_normalizado)
            for no in nos_colisao
        }
    ) == 3
    assert len(
        {
            (no.namespace_comparacao, no.valor_normalizado)
            for no in nos_colisao
        }
    ) == 3
    for no, (original_no, proveniencia_no) in zip(
        nos_colisao,
        auditoria_colisao,
        strict=True,
    ):
        assert no.valor_original == original_no
        assert no.proveniencia is proveniencia_no
