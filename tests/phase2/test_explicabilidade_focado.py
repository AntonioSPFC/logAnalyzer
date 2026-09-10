"""Testes focados da composição rastreável de explicações.

Os dados são totalmente sintéticos e nenhuma representação é derivada de fonte
real.

Validates: Requirements 13.1–13.7, 17.4.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from log_analyzer.core.explicabilidade import (
    CodigoMensagemExplicabilidade,
    CompositorDeExplicabilidade,
    compor_diagnostico_sem_regra,
    referencia_regra_de_vinculo,
)
from log_analyzer.core.modelos import (
    CampoEstruturado,
    Categoria,
    EntradaDeLog,
    IdentificadorTecnico,
    Proveniencia,
    ReferenciaRegra,
    ResultadoCausaRaiz,
    TipoIdentificador,
    VinculoIdentificadores,
)

_INSTANTE = datetime(2032, 4, 5, 12, 30, tzinfo=timezone.utc)


def _proveniencia(
    *, nome_campo: str = "CallId", regra: str | None = "extrator-call-id-v1"
) -> Proveniencia:
    return Proveniencia(
        arquivo_token="<ARQUIVO_1>",
        entrada_id="entrada-sintetica-1",
        linha_inicial=10,
        linha_final=11,
        span_inicial=3,
        span_final=14,
        nome_campo=nome_campo,
        regra_extracao=regra,
    )


def _entrada() -> EntradaDeLog:
    proveniencia = _proveniencia()
    campo = CampoEstruturado(
        nome="CallId",
        valor_original="<CALL_ID_1>",
        proveniencia=proveniencia,
    )
    return EntradaDeLog(
        texto_original="conteúdo sintético que não deve ser copiado",
        aplicacao="ORK",
        ordem_de_leitura=0,
        interpretada=True,
        carimbo_de_tempo=_INSTANTE,
        nivel_de_severidade="ERROR",
        mensagem="mensagem sintética",
        categoria=Categoria.NAO_CLASSIFICADA,
        entrada_id="entrada-sintetica-1",
        arquivo_token="<ARQUIVO_1>",
        posicao_inicial=10,
        posicao_final=11,
        timestamp_original="2032-04-05T12:30:00+00:00",
        timestamp_normalizado=_INSTANTE,
        campos_estruturados=(campo,),
    )


def _vinculo() -> VinculoIdentificadores:
    origem = IdentificadorTecnico(
        tipo=TipoIdentificador.CALL_ID,
        namespace_comparacao="chamada_externa",
        nome_campo="CallId",
        valor_original="<CALL_ID_1>",
        valor_normalizado="<call_id_1>",
        proveniencia=_proveniencia(),
    )
    destino = IdentificadorTecnico(
        tipo=TipoIdentificador.UUID_SESSAO,
        namespace_comparacao="uuid_sessao",
        nome_campo="SessionId",
        valor_original="<UUID_SESSAO_1>",
        valor_normalizado="<uuid_sessao_1>",
        proveniencia=_proveniencia(
            nome_campo="SessionId", regra="extrator-session-id-v1"
        ),
    )
    return VinculoIdentificadores(
        origem=origem,
        destino=destino,
        tipo_relacao="mapeia_sessao",
        evidencia=_proveniencia(
            nome_campo="CallId", regra="detector-declaracao-v1"
        ),
        esquema_id="esquema-sintetico",
        esquema_versao=2,
        permite_correlacao=True,
    )


def test_constroi_evidencia_de_campo_com_localizacao_tempo_e_regra() -> None:
    entrada = _entrada()
    compositor = CompositorDeExplicabilidade()

    evidencia = compositor.construir_evidencia_de_campo(
        entrada,
        entrada.campos_estruturados[0],
        "CallId presente",
        "CallId=<CALL_ID_1>",
    )

    assert evidencia.aplicacao == "ORK"
    assert evidencia.proveniencia.entrada_id == "entrada-sintetica-1"
    assert evidencia.proveniencia.linha_inicial == 10
    assert evidencia.proveniencia.linha_final == 11
    assert evidencia.proveniencia.regra_extracao == "extrator-call-id-v1"
    assert evidencia.timestamp_original == "2032-04-05T12:30:00+00:00"
    assert evidencia.timestamp_normalizado == _INSTANTE
    assert evidencia.campo_ou_condicao == "CallId presente"
    assert evidencia.representacao_sanitizada == "CallId=<CALL_ID_1>"
    assert entrada.texto_original not in evidencia.representacao_sanitizada


def test_compoe_regra_condicoes_vinculo_e_dimensoes_sem_confundi_las() -> None:
    entrada = _entrada()
    vinculo = _vinculo()
    compositor = CompositorDeExplicabilidade()
    evidencia_campo = compositor.construir_evidencia_de_campo(
        entrada,
        entrada.campos_estruturados[0],
        "CallId presente",
        "CallId=<CALL_ID_1>",
    )
    evidencia_vinculo = compositor.construir_evidencia_de_vinculo(
        entrada,
        vinculo,
        "CallId=<CALL_ID_1> -> SessionId=<UUID_SESSAO_1>",
    )
    regra = ReferenciaRegra("regra-sintetica", 3, "catalogo-v3")

    explicacao = compositor.compor(
        [entrada],
        Categoria.SUCESSO,
        regra_aplicada=regra,
        condicoes_satisfeitas=("CallId presente",),
        evidencias=(evidencia_campo, evidencia_vinculo),
        vinculos_percorridos=(vinculo,),
    )

    assert explicacao.regra_aplicada == regra
    assert explicacao.condicoes_satisfeitas == ("CallId presente",)
    assert explicacao.vinculos_percorridos == (vinculo,)
    assert (
        evidencia_vinculo.proveniencia.regra_extracao
        == referencia_regra_de_vinculo(vinculo)
    )
    aspecto = explicacao.dimensoes.entradas[0]
    assert aspecto.severidade_de_log == "ERROR"
    assert aspecto.categoria_da_entrada is Categoria.NAO_CLASSIFICADA
    assert explicacao.categoria_de_cenario is Categoria.SUCESSO
    assert explicacao.causa_raiz == ResultadoCausaRaiz()
    assert [mensagem.codigo for mensagem in explicacao.mensagens] == [
        CodigoMensagemExplicabilidade.CAUSA_RAIZ_NAO_DETERMINADA
    ]
    assert explicacao.mensagens[0].hipotese_causal is None


def test_diagnostico_sem_regra_e_fail_closed_sem_hipotese_causal() -> None:
    explicacao = compor_diagnostico_sem_regra([_entrada()])

    assert explicacao.categoria_de_cenario is Categoria.NAO_CLASSIFICADA
    assert explicacao.regra_aplicada is None
    assert explicacao.condicoes_satisfeitas == ()
    assert explicacao.causa_raiz == ResultadoCausaRaiz()
    assert [mensagem.codigo for mensagem in explicacao.mensagens] == [
        CodigoMensagemExplicabilidade.NENHUMA_REGRA_VALIDADA_CORRESPONDEU,
        CodigoMensagemExplicabilidade.CAUSA_RAIZ_NAO_DETERMINADA,
    ]
    assert all(
        mensagem.hipotese_causal is None
        for mensagem in explicacao.mensagens
    )


def test_rejeita_evidencia_sem_rastreabilidade_ou_regra() -> None:
    compositor = CompositorDeExplicabilidade()
    entrada_legada = EntradaDeLog(
        texto_original="linha sintética",
        aplicacao="VOCI",
        ordem_de_leitura=0,
        interpretada=False,
    )
    with pytest.raises(ValueError, match="entrada_id"):
        compositor.construir_evidencia_de_entrada(
            entrada_legada,
            "condição sintética",
            "representação sintética",
            regra_extracao_ou_vinculo="regra-sintetica-v1",
        )

    entrada = _entrada()
    proveniencia_sem_regra = _proveniencia(regra=None)
    with pytest.raises(ValueError, match="regra de extração ou vínculo"):
        compositor.construir_evidencia_de_entrada(
            entrada,
            "condição sintética",
            "representação sintética",
            proveniencia=proveniencia_sem_regra,
        )


def test_rejeita_classificacao_sem_regra_condicoes_ou_evidencias() -> None:
    with pytest.raises(ValueError, match="regra aplicada"):
        CompositorDeExplicabilidade().compor(
            [_entrada()],
            Categoria.ERRO,
        )
