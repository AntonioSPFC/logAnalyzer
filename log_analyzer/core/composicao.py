"""Composição aditiva e determinística do resultado da Fase 2.

A composição recebe as entradas finais já selecionadas pelo pipeline e não
executa parsing, busca, correlação, classificação ou sanitização. Ela apenas
consolida os contratos dessas etapas em :class:`ResultadoDeAnalise`, mantendo
os campos da Fase 1 e acrescentando a partição temporal e os metadados da Fase
2.

A lista de entradas é materializada uma única vez e nenhuma deduplicação é
aplicada. Assim, agrupamentos, contagens e coleções temporais são derivados das
mesmas ocorrências, preservando ordem e multiplicidade. Categoria e severidade
de cada entrada permanecem intactas e independentes da categoria do cenário.

Requirements: 6.5, 6.7, 9.4, 13.6, 16.1, 16.2, 16.3, 17.1, 17.2, 17.3.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TypeVar

from log_analyzer.core.agrupamento import agrupar_por_aplicacao
from log_analyzer.core.contagens import calcular_contagens
from log_analyzer.core.modelos import (
    Categoria,
    EntradaDeLog,
    EstadoSanitizacao,
    Evidencia,
    IdentificadorTecnico,
    MensagemDeErro,
    ReferenciaRegra,
    ResultadoCausaRaiz,
    ResultadoCorrelacao,
    ResultadoDeAnalise,
    VinculoIdentificadores,
)
from log_analyzer.core.ordenacao import particionar_linha_do_tempo


VERSAO_SEM_CATALOGO_ATIVO = "sem-catalogo-ativo"
COBERTURA_ROTULADA_FASE2 = "1 cenário de sucesso; 0 cenários de erro"

_T = TypeVar("_T")


def _materializar_tipos(
    valores: Iterable[_T],
    tipo: type[_T],
    nome: str,
) -> list[_T]:
    """Materializa um iterável sem aceitar strings ou itens de outro contrato."""

    if isinstance(valores, (str, bytes)):
        raise TypeError(f"{nome} deve ser um iterável de {tipo.__name__}.")
    try:
        materializados = list(valores)
    except TypeError as exc:
        raise TypeError(
            f"{nome} deve ser um iterável de {tipo.__name__}."
        ) from exc
    if not all(isinstance(valor, tipo) for valor in materializados):
        raise TypeError(f"{nome} deve conter somente {tipo.__name__}.")
    return materializados


def _materializar_textos(valores: Iterable[str], nome: str) -> list[str]:
    """Copia textos de metadados sem normalizar ou reordenar o chamador."""

    if isinstance(valores, (str, bytes)):
        raise TypeError(f"{nome} deve ser um iterável de strings.")
    try:
        materializados = list(valores)
    except TypeError as exc:
        raise TypeError(f"{nome} deve ser um iterável de strings.") from exc
    if not all(isinstance(valor, str) for valor in materializados):
        raise TypeError(f"{nome} deve conter somente strings.")
    return materializados


def _aplicacoes_em_ordem_de_aparicao(
    entradas: list[EntradaDeLog],
) -> list[str]:
    """Deriva Aplicações analisadas sem perder a ordem da seleção."""

    resultado: list[str] = []
    conhecidas: set[str] = set()
    for entrada in entradas:
        if entrada.aplicacao not in conhecidas:
            conhecidas.add(entrada.aplicacao)
            resultado.append(entrada.aplicacao)
    return resultado


def compor_resultado_fase2(
    identificador: str,
    entradas_selecionadas: Iterable[EntradaDeLog],
    *,
    categoria_de_cenario: Categoria = Categoria.NAO_CLASSIFICADA,
    identificadores_extraidos: Iterable[IdentificadorTecnico] | None = None,
    vinculos: Iterable[VinculoIdentificadores] = (),
    correlacao: ResultadoCorrelacao | None = None,
    correlacao_encontrada: bool | None = None,
    evidencias: Iterable[Evidencia] = (),
    regra_aplicada: ReferenciaRegra | None = None,
    versao_catalogo: str = VERSAO_SEM_CATALOGO_ATIVO,
    estado_sanitizacao: EstadoSanitizacao = EstadoSanitizacao.INTERNA_BRUTA,
    causa_raiz: ResultadoCausaRaiz | None = None,
    aplicacoes_analisadas: Iterable[str] | None = None,
    aplicacoes_ausentes_ou_invalidas: Iterable[str] = (),
    cobertura_rotulada: str = COBERTURA_ROTULADA_FASE2,
    erros: Iterable[MensagemDeErro] = (),
    mensagens: Iterable[str] = (),
) -> ResultadoDeAnalise:
    """Compõe um :class:`ResultadoDeAnalise` aditivo a partir da seleção final.

    ``entradas_selecionadas`` deve conter as ocorrências finais do pipeline,
    inclusive eventuais cópias imutáveis marcadas pelo correlacionador. A função
    não deduplica, não substitui e não reclassifica entradas. A mesma lista
    materializada alimenta agrupamento, contagens e partição temporal, de modo
    que a união de ``linha_do_tempo`` com
    ``entradas_sem_ordenacao_temporal`` preserve exatamente a multiplicidade da
    seleção.

    Quando ``identificadores_extraidos`` é ``None``, todas as ocorrências de
    identificadores das entradas são achatadas na ordem recebida, sem colapsar
    valores iguais com proveniências distintas. Quando
    ``aplicacoes_analisadas`` é ``None``, os nomes são derivados pela primeira
    aparição; o chamador deve fornecer a lista explicitamente para registrar
    Aplicações processadas que não produziram entradas selecionadas.

    ``correlacao_encontrada`` existe somente para adapters transitórios da Fase
    1. Por padrão ele deriva do resultado estruturado de ``correlacao``; se os
    dois forem fornecidos, os invariantes de ``ResultadoDeAnalise`` exigem que
    sejam coerentes.
    """

    entradas = _materializar_tipos(
        entradas_selecionadas,
        EntradaDeLog,
        "entradas_selecionadas",
    )

    if correlacao is not None and not isinstance(
        correlacao, ResultadoCorrelacao
    ):
        raise TypeError("correlacao deve ser ResultadoCorrelacao ou None.")
    if correlacao_encontrada is not None and not isinstance(
        correlacao_encontrada, bool
    ):
        raise TypeError("correlacao_encontrada deve ser bool ou None.")

    if identificadores_extraidos is None:
        identificadores = [
            identificador_tecnico
            for entrada in entradas
            for identificador_tecnico in entrada.identificadores
        ]
    else:
        identificadores = _materializar_tipos(
            identificadores_extraidos,
            IdentificadorTecnico,
            "identificadores_extraidos",
        )

    vinculos_materializados = _materializar_tipos(
        vinculos,
        VinculoIdentificadores,
        "vinculos",
    )
    evidencias_materializadas = _materializar_tipos(
        evidencias,
        Evidencia,
        "evidencias",
    )
    erros_materializados = _materializar_tipos(
        erros,
        MensagemDeErro,
        "erros",
    )
    mensagens_materializadas = _materializar_textos(mensagens, "mensagens")

    if aplicacoes_analisadas is None:
        analisadas = _aplicacoes_em_ordem_de_aparicao(entradas)
    else:
        analisadas = _materializar_textos(
            aplicacoes_analisadas,
            "aplicacoes_analisadas",
        )
    ausentes_ou_invalidas = _materializar_textos(
        aplicacoes_ausentes_ou_invalidas,
        "aplicacoes_ausentes_ou_invalidas",
    )

    linha_do_tempo, sem_ordenacao_temporal = particionar_linha_do_tempo(
        entradas
    )
    entradas_por_aplicacao = agrupar_por_aplicacao(entradas)
    contagem_por_categoria, contagem_por_aplicacao = calcular_contagens(
        entradas
    )

    encontrada = (
        correlacao.encontrada
        if correlacao_encontrada is None and correlacao is not None
        else bool(correlacao_encontrada)
    )

    return ResultadoDeAnalise(
        identificador=identificador,
        entradas_por_aplicacao=entradas_por_aplicacao,
        linha_do_tempo=linha_do_tempo,
        contagem_por_categoria=contagem_por_categoria,
        contagem_por_aplicacao=contagem_por_aplicacao,
        correlacao_encontrada=encontrada,
        erros=erros_materializados,
        mensagens=mensagens_materializadas,
        categoria_de_cenario=categoria_de_cenario,
        entradas_sem_ordenacao_temporal=sem_ordenacao_temporal,
        identificadores_extraidos=identificadores,
        vinculos=vinculos_materializados,
        correlacao=correlacao,
        evidencias=evidencias_materializadas,
        regra_aplicada=regra_aplicada,
        versao_catalogo=versao_catalogo,
        estado_sanitizacao=estado_sanitizacao,
        causa_raiz=causa_raiz if causa_raiz is not None else ResultadoCausaRaiz(),
        aplicacoes_analisadas=analisadas,
        aplicacoes_ausentes_ou_invalidas=ausentes_ou_invalidas,
        cobertura_rotulada=cobertura_rotulada,
    )


__all__ = ["compor_resultado_fase2"]
