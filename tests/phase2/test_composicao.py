"""Testes sintéticos da composição aditiva do ResultadoDeAnalise.

Validates: Requirements 6.5, 6.7, 9.4, 13.6, 16.1, 16.2, 16.3,
17.1, 17.2, 17.3.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

import pytest

import log_analyzer.core as core
from log_analyzer.core.composicao import compor_resultado_fase2
from log_analyzer.core.modelos import (
    BaseCorrelacao,
    Categoria,
    EntradaDeLog,
    EstadoSanitizacao,
    Evidencia,
    IdentificadorTecnico,
    MensagemDeErro,
    Proveniencia,
    ReferenciaRegra,
    ResultadoCorrelacao,
    ResultadoCausaRaiz,
    TipoIdentificador,
    VinculoIdentificadores,
)
from log_analyzer.core.serializacao import serializar_resultado_de_analise


UTC = timezone.utc
INSTANTE = datetime(2042, 5, 6, 12, 30, tzinfo=UTC)


def _proveniencia(
    aplicacao: str,
    entrada_id: str,
    linha: int,
    *,
    campo: str = "CallId",
    regra: str = "extrator-sintetico-v1",
) -> Proveniencia:
    return Proveniencia(
        arquivo_token=f"<ARQUIVO_{aplicacao}>",
        entrada_id=entrada_id,
        linha_inicial=linha,
        linha_final=linha,
        nome_campo=campo,
        regra_extracao=regra,
    )


def _identificador(
    aplicacao: str,
    entrada_id: str,
    linha: int,
) -> IdentificadorTecnico:
    tipo = (
        TipoIdentificador.CHAMADA_EXTERNA
        if aplicacao == "VPL"
        else TipoIdentificador.TELECOM_CALL_ID
    )
    return IdentificadorTecnico(
        tipo=tipo,
        namespace_comparacao="chamada-sintetica",
        nome_campo="CallId",
        valor_original="<CALL_ID_SINTETICO_1>",
        valor_normalizado="<call_id_sintetico_1>",
        proveniencia=_proveniencia(aplicacao, entrada_id, linha),
    )


def _entrada(
    aplicacao: str,
    entrada_id: str,
    linha: int,
    ordem: int,
    *,
    timestamp_normalizado: datetime | None,
    categoria: Categoria,
    severidade: str,
    texto: str,
    correlacionada: bool = False,
    sanitizada: bool = False,
) -> EntradaDeLog:
    identificador = _identificador(aplicacao, entrada_id, linha)
    return EntradaDeLog(
        texto_original=texto,
        aplicacao=aplicacao,
        ordem_de_leitura=ordem,
        interpretada=True,
        carimbo_de_tempo=INSTANTE.replace(tzinfo=None),
        nivel_de_severidade=severidade,
        mensagem=texto,
        categoria=categoria,
        correlacionada=correlacionada,
        entrada_id=entrada_id,
        arquivo_token=f"<ARQUIVO_{aplicacao}>",
        posicao_inicial=linha,
        posicao_final=linha,
        timestamp_original="2042-05-06T09:30:00-03:00",
        timestamp_normalizado=timestamp_normalizado,
        identificadores=(identificador,),
        representacao_sanitizada=(
            "evento=<DADO_CLIENTE_1> CallId=<CALL_ID_1>"
            if sanitizada
            else None
        ),
    )


def test_compoe_todos_os_campos_sem_perder_ou_duplicar_ocorrencias() -> None:
    vpl_sem_utc_1 = _entrada(
        "VPL",
        "entrada-vpl-repetida-1",
        3,
        2,
        timestamp_normalizado=None,
        categoria=Categoria.ERRO,
        severidade="ERROR",
        texto="evento sintético repetido",
    )
    vpl_utc = _entrada(
        "VPL",
        "entrada-vpl-utc",
        2,
        1,
        timestamp_normalizado=INSTANTE,
        categoria=Categoria.SUCESSO,
        severidade="ERROR",
        texto="evento sintético VPL UTC",
        correlacionada=True,
    )
    ork_utc = _entrada(
        "ORK",
        "entrada-ork-utc",
        1,
        0,
        timestamp_normalizado=INSTANTE,
        categoria=Categoria.NAO_CLASSIFICADA,
        severidade="WARNING",
        texto="evento sintético ORK UTC",
        correlacionada=True,
    )
    vpl_sem_utc_2 = _entrada(
        "VPL",
        "entrada-vpl-repetida-2",
        4,
        3,
        timestamp_normalizado=None,
        categoria=Categoria.ERRO,
        severidade="ERROR",
        texto="evento sintético repetido",
    )
    selecionadas = [vpl_sem_utc_1, vpl_utc, ork_utc, vpl_sem_utc_2]
    snapshot = list(selecionadas)

    evidencia = Evidencia(
        tipo="condicao_sintetica",
        aplicacao="ORK",
        proveniencia=ork_utc.identificadores[0].proveniencia,
        timestamp_original=ork_utc.timestamp_original,
        timestamp_normalizado=ork_utc.timestamp_normalizado,
        campo_ou_condicao="condicao-sintetica-satisfeita",
        representacao_sanitizada="CallId=<CALL_ID_1>",
    )
    vinculo = VinculoIdentificadores(
        origem=vpl_utc.identificadores[0],
        destino=ork_utc.identificadores[0],
        tipo_relacao="relacao-sintetica-explicita",
        evidencia=vpl_utc.identificadores[0].proveniencia,
        esquema_id="esquema-sintetico",
        esquema_versao=1,
        permite_correlacao=True,
    )
    correlacao = ResultadoCorrelacao(
        encontrada=True,
        base_primaria=BaseCorrelacao.VALOR_COMPARTILHADO,
        bases=(BaseCorrelacao.VALOR_COMPARTILHADO,),
        evidencias=(evidencia,),
    )
    regra = ReferenciaRegra(
        "regra-sintetica",
        2,
        "catalogo-sintetico-v2",
    )
    erros = [MensagemDeErro("<ARQUIVO_INVALIDO_1>", "falha sintética")]
    mensagens = ["composição sintética concluída"]

    resultado = compor_resultado_fase2(
        "<CALL_ID_SINTETICO_1>",
        selecionadas,
        categoria_de_cenario=Categoria.SUCESSO,
        vinculos=(vinculo,),
        correlacao=correlacao,
        evidencias=(evidencia,),
        regra_aplicada=regra,
        versao_catalogo=regra.catalogo_versao,
        estado_sanitizacao=EstadoSanitizacao.INTERNA_BRUTA,
        causa_raiz=ResultadoCausaRaiz(),
        aplicacoes_analisadas=("VPL", "ORK"),
        aplicacoes_ausentes_ou_invalidas=("VOCI",),
        cobertura_rotulada="2 cenários sintéticos de sucesso; 0 de erro",
        erros=erros,
        mensagens=mensagens,
    )

    assert selecionadas == snapshot
    assert resultado.entradas_por_aplicacao == {
        "VPL": [vpl_sem_utc_1, vpl_utc, vpl_sem_utc_2],
        "ORK": [ork_utc],
    }
    assert resultado.linha_do_tempo == [ork_utc, vpl_utc]
    assert resultado.entradas_sem_ordenacao_temporal == [
        vpl_sem_utc_1,
        vpl_sem_utc_2,
    ]
    ids_selecionadas = Counter(
        entrada.entrada_id for entrada in snapshot
    )
    ids_particao = Counter(
        entrada.entrada_id
        for entrada in (
            resultado.linha_do_tempo
            + resultado.entradas_sem_ordenacao_temporal
        )
    )
    assert ids_particao == ids_selecionadas
    assert len(resultado.linha_do_tempo) + len(
        resultado.entradas_sem_ordenacao_temporal
    ) == len(snapshot)

    assert resultado.contagem_por_aplicacao == {"VPL": 3, "ORK": 1}
    assert resultado.contagem_por_categoria == {
        Categoria.ERRO: 2,
        Categoria.SUCESSO: 1,
        Categoria.NAO_CLASSIFICADA: 1,
    }
    assert resultado.categoria_de_cenario is Categoria.SUCESSO
    assert [entrada.categoria for entrada in snapshot] == [
        Categoria.ERRO,
        Categoria.SUCESSO,
        Categoria.NAO_CLASSIFICADA,
        Categoria.ERRO,
    ]
    assert [entrada.nivel_de_severidade for entrada in snapshot] == [
        "ERROR",
        "ERROR",
        "WARNING",
        "ERROR",
    ]

    assert resultado.identificadores_extraidos == [
        identificador
        for entrada in snapshot
        for identificador in entrada.identificadores
    ]
    assert len(resultado.identificadores_extraidos) == 4
    assert resultado.vinculos == [vinculo]
    assert resultado.correlacao is correlacao
    assert resultado.correlacao_encontrada is True
    assert resultado.evidencias == [evidencia]
    assert resultado.regra_aplicada is regra
    assert resultado.versao_catalogo == "catalogo-sintetico-v2"
    assert resultado.estado_sanitizacao is EstadoSanitizacao.INTERNA_BRUTA
    assert resultado.causa_raiz == ResultadoCausaRaiz()
    assert resultado.aplicacoes_analisadas == ["VPL", "ORK"]
    assert resultado.aplicacoes_ausentes_ou_invalidas == ["VOCI"]
    assert resultado.cobertura_rotulada == (
        "2 cenários sintéticos de sucesso; 0 de erro"
    )
    assert resultado.erros == erros
    assert resultado.mensagens == mensagens

    selecionadas.clear()
    erros.clear()
    mensagens.clear()
    assert resultado.contagem_por_aplicacao == {"VPL": 3, "ORK": 1}
    assert len(resultado.erros) == 1
    assert resultado.mensagens == ["composição sintética concluída"]


def test_defaults_derivam_ids_e_apps_e_preservam_cenario_independente() -> None:
    entrada = _entrada(
        "VPL",
        "entrada-segura-sem-utc",
        1,
        0,
        timestamp_normalizado=None,
        categoria=Categoria.ERRO,
        severidade="ERROR",
        texto="evento sintético seguro",
        sanitizada=True,
    )

    resultado = compor_resultado_fase2(
        "<CALL_ID_SINTETICO_1>",
        (entrada,),
        estado_sanitizacao=EstadoSanitizacao.CONCLUIDA,
    )

    assert core.compor_resultado_fase2 is compor_resultado_fase2
    assert resultado.categoria_de_cenario is Categoria.NAO_CLASSIFICADA
    assert resultado.entradas_por_aplicacao == {"VPL": [entrada]}
    assert resultado.linha_do_tempo == []
    assert resultado.entradas_sem_ordenacao_temporal == [entrada]
    assert resultado.identificadores_extraidos == [entrada.identificadores[0]]
    assert resultado.aplicacoes_analisadas == ["VPL"]
    assert resultado.aplicacoes_ausentes_ou_invalidas == []
    assert resultado.correlacao is None
    assert resultado.correlacao_encontrada is False
    assert resultado.regra_aplicada is None
    assert resultado.versao_catalogo == "sem-catalogo-ativo"
    assert resultado.causa_raiz == ResultadoCausaRaiz()
    assert resultado.cobertura_rotulada == (
        "1 cenário de sucesso; 0 cenários de erro"
    )
    assert entrada.categoria is Categoria.ERRO
    assert entrada.nivel_de_severidade == "ERROR"
    assert serializar_resultado_de_analise(resultado)[
        "estado_sanitizacao"
    ] == "concluida"


def test_identidades_repetidas_sao_rejeitadas_sem_deduplicacao_silenciosa() -> None:
    primeira = _entrada(
        "VPL",
        "entrada-id-repetido",
        1,
        0,
        timestamp_normalizado=INSTANTE,
        categoria=Categoria.NAO_CLASSIFICADA,
        severidade="INFO",
        texto="primeira ocorrência sintética",
    )
    segunda = _entrada(
        "VPL",
        "entrada-id-repetido",
        2,
        1,
        timestamp_normalizado=INSTANTE,
        categoria=Categoria.NAO_CLASSIFICADA,
        severidade="INFO",
        texto="segunda ocorrência sintética",
    )

    with pytest.raises(ValueError, match="identidade única"):
        compor_resultado_fase2(
            "<CALL_ID_SINTETICO_1>",
            [primeira, segunda],
        )
