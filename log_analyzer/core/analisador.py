"""Fachada preservada do Analisador de Logs.

A fachada mantém o contrato público da Fase 1 e roteia internamente cada
seleção efetiva para um único fluxo:

* VPL/ORK com a capacidade opcional ``Parser_de_Bloco`` usam
  :class:`PipelineFase2`;
* VOCI, plugins line-based e VPL/ORK sem essa capacidade permanecem no fluxo
  legado.

O roteamento ocorre antes de qualquer arquivo ser aberto. Assim, fontes da
Fase 2 nunca são materializadas pelo carregador legado e entradas com
metadados novos nunca passam pela timeline ou pela correlação presumida da
Fase 1.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable, TypeVar

from log_analyzer.core.agrupamento import agrupar_por_aplicacao
from log_analyzer.core.carregador import carregar_arquivo
from log_analyzer.core.composicao import compor_resultado_fase2
from log_analyzer.core.contagens import calcular_contagens
from log_analyzer.core.correlacao import correlacionar_vpl_ork
from log_analyzer.core.excecoes import ErroDeRegistro
from log_analyzer.core.filtro import filtrar_por_identificador
from log_analyzer.core.interfaces import Parser_de_Bloco
from log_analyzer.core.modelos import (
    ArquivoSelecionado,
    EntradaDeLog,
    EstadoSanitizacao,
    MensagemDeErro,
    ResultadoDeAnalise,
)
from log_analyzer.core.ordenacao import ordenar_linha_do_tempo
from log_analyzer.core.pipeline_fase2 import PipelineFase2
from log_analyzer.core.registro import Registro_de_Aplicacoes
from log_analyzer.core.validacao import validar_identificador


_APLICACOES_FASE2 = frozenset({"VPL", "ORK"})
_MENSAGEM_SEM_CORRESPONDENCIA_FASE2 = (
    "Nenhuma entrada correspondeu integralmente à consulta."
)
_PREFIXO_SEM_CORRESPONDENCIA_LEGADO = (
    "Nenhuma correspondência encontrada para o identificador "
)

_T = TypeVar("_T")


@dataclass(frozen=True)
class _ExecucaoLegada:
    """Resultado legado e metadados internos usados apenas na composição mista."""

    resultado: ResultadoDeAnalise
    aplicacoes_analisadas: tuple[str, ...] = ()
    aplicacoes_invalidas: tuple[str, ...] = ()


def _sem_duplicatas(valores: Iterable[_T]) -> list[_T]:
    resultado: list[_T] = []
    for valor in valores:
        if valor not in resultado:
            resultado.append(valor)
    return resultado


def _entradas_do_resultado(
    resultado: ResultadoDeAnalise,
) -> list[EntradaDeLog]:
    """Obtém cada ocorrência pela coleção canônica agrupada do resultado."""

    return [
        entrada
        for entradas in resultado.entradas_por_aplicacao.values()
        for entrada in entradas
    ]


class Analisador_de_Logs:
    """Orquestrador público que depende somente do registro e dos contratos."""

    def __init__(self, registro: Registro_de_Aplicacoes) -> None:
        self._registro = registro

    def analisar(
        self, selecao: list[ArquivoSelecionado], identificador: str
    ) -> ResultadoDeAnalise:
        """Analisa a seleção preservando a assinatura e o retorno públicos.

        A validação da consulta ocorre antes da reassociação, da resolução de
        plugins e de qualquer acesso a arquivo. Para caminhos repetidos, somente
        a última associação é efetiva. Depois disso, a capacidade opcional do
        parser decide o fluxo sem importar implementações concretas no núcleo.
        """

        validar_identificador(identificador)

        if not selecao:
            return ResultadoDeAnalise(
                identificador=identificador,
                mensagens=[
                    "Nenhum Arquivo de Log selecionado. "
                    "Selecione ao menos um arquivo para análise."
                ],
            )

        selecao_efetiva = self._aplicar_reassociacao(selecao)
        selecao_fase2, selecao_legada = self._separar_fluxos(
            selecao_efetiva
        )

        resultado_fase2: ResultadoDeAnalise | None = None
        if selecao_fase2:
            resultado_fase2 = PipelineFase2(self._registro).executar(
                selecao_fase2,
                identificador,
            )

        execucao_legada: _ExecucaoLegada | None = None
        if selecao_legada:
            execucao_legada = self._executar_fluxo_legado(
                selecao_legada,
                identificador,
            )

        if resultado_fase2 is None:
            # Há pelo menos uma seleção efetiva, portanto o fluxo legado existe.
            assert execucao_legada is not None
            return execucao_legada.resultado
        if execucao_legada is None:
            return resultado_fase2

        return self._combinar_resultados(
            resultado_fase2,
            execucao_legada,
        )

    def _aplicar_reassociacao(
        self,
        selecao: list[ArquivoSelecionado],
    ) -> list[ArquivoSelecionado]:
        """Mantém a última associação registrada e todos os erros de tentativa.

        ``None`` e IDs não registrados não são associações efetivas: continuam
        na seleção para produzir o erro legado correspondente, mas não
        substituem nem são substituídos no mapa caminho→Aplicação.
        """

        ultima_posicao_por_caminho = {
            arquivo.caminho: indice
            for indice, arquivo in enumerate(selecao)
            if arquivo.app_id is not None
            and self._registro.esta_registrada(arquivo.app_id)
        }
        return [
            arquivo
            for indice, arquivo in enumerate(selecao)
            if arquivo.app_id is None
            or not self._registro.esta_registrada(arquivo.app_id)
            or ultima_posicao_por_caminho[arquivo.caminho] == indice
        ]

    def _separar_fluxos(
        self,
        selecao: list[ArquivoSelecionado],
    ) -> tuple[list[ArquivoSelecionado], list[ArquivoSelecionado]]:
        """Roteia por app e capacidade sem abrir ou carregar as fontes."""

        fase2: list[ArquivoSelecionado] = []
        legado: list[ArquivoSelecionado] = []

        for arquivo in selecao:
            if arquivo.app_id not in _APLICACOES_FASE2:
                legado.append(arquivo)
                continue

            try:
                parser, _ = self._registro.obter(arquivo.app_id)
            except ErroDeRegistro:
                # O fluxo legado preserva a mensagem pública de registro.
                legado.append(arquivo)
                continue

            if isinstance(parser, Parser_de_Bloco):
                fase2.append(arquivo)
            else:
                legado.append(arquivo)

        return fase2, legado

    def _executar_fluxo_legado(
        self,
        selecao: list[ArquivoSelecionado],
        identificador: str,
    ) -> _ExecucaoLegada:
        """Executa literalmente o pipeline line-based preservado da Fase 1."""

        erros: list[MensagemDeErro] = []
        todas_entradas: list[EntradaDeLog] = []
        aplicacoes_analisadas: list[str] = []
        aplicacoes_invalidas: list[str] = []

        for arquivo in selecao:
            if arquivo.app_id is None:
                erros.append(
                    MensagemDeErro(
                        arquivo_ou_app=arquivo.caminho,
                        descricao="Aplicação não informada para este arquivo.",
                    )
                )
                continue

            try:
                parser, padrao = self._registro.obter(arquivo.app_id)
            except ErroDeRegistro as erro:
                erros.append(
                    MensagemDeErro(
                        arquivo_ou_app=arquivo.app_id,
                        descricao=erro.mensagem,
                    )
                )
                aplicacoes_invalidas.append(arquivo.app_id)
                continue

            resultado_carga = carregar_arquivo(arquivo.caminho)
            if isinstance(resultado_carga, MensagemDeErro):
                erros.append(resultado_carga)
                aplicacoes_invalidas.append(arquivo.app_id)
                continue

            entradas_interpretadas = parser.interpretar_arquivo(
                resultado_carga
            )
            entradas_com_ordem = [
                replace(
                    entrada,
                    aplicacao=arquivo.app_id,
                    ordem_de_leitura=indice,
                )
                for indice, entrada in enumerate(entradas_interpretadas)
            ]
            entradas_filtradas = filtrar_por_identificador(
                entradas_com_ordem,
                identificador,
            )

            entradas_classificadas: list[EntradaDeLog] = []
            for entrada in entradas_filtradas:
                try:
                    categoria = padrao.classificar(entrada)
                    entradas_classificadas.append(
                        replace(entrada, categoria=categoria)
                    )
                except Exception:
                    erros.append(
                        MensagemDeErro(
                            arquivo_ou_app=arquivo.app_id,
                            descricao=(
                                "Erro ao classificar entrada da aplicação "
                                f"'{arquivo.app_id}'."
                            ),
                        )
                    )
                    entradas_classificadas.append(entrada)

            todas_entradas.extend(entradas_classificadas)
            aplicacoes_analisadas.append(arquivo.app_id)

        entradas_vpl = [
            entrada
            for entrada in todas_entradas
            if entrada.aplicacao == "VPL"
        ]
        entradas_ork = [
            entrada
            for entrada in todas_entradas
            if entrada.aplicacao == "ORK"
        ]
        entradas_outras = [
            entrada
            for entrada in todas_entradas
            if entrada.aplicacao not in _APLICACOES_FASE2
        ]

        correlacao_encontrada = False
        if entradas_vpl and entradas_ork:
            entradas_vpl, entradas_ork, correlacao_encontrada, erros_corr = (
                correlacionar_vpl_ork(
                    entradas_vpl,
                    entradas_ork,
                    identificador,
                )
            )
            erros.extend(erros_corr)
            todas_entradas = entradas_vpl + entradas_ork + entradas_outras
        elif entradas_vpl or entradas_ork:
            apps_selecionadas = {
                arquivo.app_id
                for arquivo in selecao
                if arquivo.app_id is not None
            }
            if _APLICACOES_FASE2.issubset(apps_selecionadas):
                entradas_vpl, entradas_ork, correlacao_encontrada, erros_corr = (
                    correlacionar_vpl_ork(
                        entradas_vpl,
                        entradas_ork,
                        identificador,
                    )
                )
                erros.extend(erros_corr)
                todas_entradas = (
                    entradas_vpl + entradas_ork + entradas_outras
                )

        linha_do_tempo = ordenar_linha_do_tempo(todas_entradas)
        entradas_por_aplicacao = agrupar_por_aplicacao(todas_entradas)
        contagem_por_categoria, contagem_por_aplicacao = calcular_contagens(
            todas_entradas
        )

        mensagens: list[str] = []
        if not todas_entradas and not erros:
            mensagens.append(
                "Nenhuma correspondência encontrada para o identificador "
                f"'{identificador}'."
            )

        return _ExecucaoLegada(
            resultado=ResultadoDeAnalise(
                identificador=identificador,
                entradas_por_aplicacao=entradas_por_aplicacao,
                linha_do_tempo=linha_do_tempo,
                contagem_por_categoria=contagem_por_categoria,
                contagem_por_aplicacao=contagem_por_aplicacao,
                correlacao_encontrada=correlacao_encontrada,
                erros=erros,
                mensagens=mensagens,
            ),
            aplicacoes_analisadas=tuple(
                _sem_duplicatas(aplicacoes_analisadas)
            ),
            aplicacoes_invalidas=tuple(
                _sem_duplicatas(aplicacoes_invalidas)
            ),
        )

    @staticmethod
    def _combinar_resultados(
        fase2: ResultadoDeAnalise,
        legado: _ExecucaoLegada,
    ) -> ResultadoDeAnalise:
        """Combina fluxos sem aplicar adapters legados às entradas Fase 2."""

        entradas = [
            *_entradas_do_resultado(fase2),
            *_entradas_do_resultado(legado.resultado),
        ]
        aplicacoes_analisadas = _sem_duplicatas(
            (
                *fase2.aplicacoes_analisadas,
                *legado.aplicacoes_analisadas,
            )
        )
        aplicacoes_ausentes_ou_invalidas = _sem_duplicatas(
            (
                *(
                    app
                    for app in fase2.aplicacoes_ausentes_ou_invalidas
                    if app not in aplicacoes_analisadas
                ),
                *(
                    app
                    for app in legado.aplicacoes_invalidas
                    if app not in aplicacoes_analisadas
                ),
            )
        )

        mensagens = [
            mensagem
            for mensagem in fase2.mensagens
            if entradas
            and mensagem != _MENSAGEM_SEM_CORRESPONDENCIA_FASE2
            or not entradas
        ]
        mensagens.extend(
            mensagem
            for mensagem in legado.resultado.mensagens
            if not mensagem.startswith(
                _PREFIXO_SEM_CORRESPONDENCIA_LEGADO
            )
        )

        return compor_resultado_fase2(
            legado.resultado.identificador,
            entradas,
            categoria_de_cenario=fase2.categoria_de_cenario,
            identificadores_extraidos=fase2.identificadores_extraidos,
            vinculos=fase2.vinculos,
            correlacao=fase2.correlacao,
            correlacao_encontrada=fase2.correlacao_encontrada,
            evidencias=fase2.evidencias,
            regra_aplicada=fase2.regra_aplicada,
            versao_catalogo=fase2.versao_catalogo,
            # A parte legada ainda contém o objeto interno bruto. Marcar a
            # composição como concluída faria a CLI confiar em uma visão
            # parcialmente sanitizada; a fronteira de saída deve sanitizar a
            # combinação inteira uma única vez.
            estado_sanitizacao=EstadoSanitizacao.INTERNA_BRUTA,
            causa_raiz=fase2.causa_raiz,
            aplicacoes_analisadas=aplicacoes_analisadas,
            aplicacoes_ausentes_ou_invalidas=(
                aplicacoes_ausentes_ou_invalidas
            ),
            cobertura_rotulada=fase2.cobertura_rotulada,
            erros=(*fase2.erros, *legado.resultado.erros),
            mensagens=_sem_duplicatas(mensagens),
        )
