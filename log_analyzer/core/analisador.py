"""Orquestrador principal do Analisador de Logs.

Coordena o fluxo completo de análise: validação de entradas, resolução de
parser/padrão via Registro, carregamento, interpretação, filtragem,
classificação, correlação e composição do resultado.

Acumula erros sem abortar (Req 1.2, 10.x). Trata "nenhum arquivo" (Req 3.6, 10.1)
e "Aplicação não informada" (Req 2.3, 2.4).

Requirements: 2.3, 2.4, 2.5, 3.6, 10.1, 1.2, 5.6
"""

from __future__ import annotations

from dataclasses import replace

from log_analyzer.core.agrupamento import agrupar_por_aplicacao
from log_analyzer.core.carregador import carregar_arquivo
from log_analyzer.core.contagens import calcular_contagens
from log_analyzer.core.correlacao import correlacionar_vpl_ork
from log_analyzer.core.excecoes import ErroDeIdentificador, ErroDeRegistro
from log_analyzer.core.filtro import filtrar_por_identificador
from log_analyzer.core.modelos import (
    ArquivoSelecionado,
    MensagemDeErro,
    ResultadoDeAnalise,
)
from log_analyzer.core.ordenacao import ordenar_linha_do_tempo
from log_analyzer.core.registro import Registro_de_Aplicacoes
from log_analyzer.core.validacao import validar_identificador


class Analisador_de_Logs:
    """Orquestrador principal que coordena todo o pipeline de análise.

    Não conhece Aplicações concretas — apenas o Registro e as interfaces comuns.
    """

    def __init__(self, registro: Registro_de_Aplicacoes) -> None:
        self._registro = registro

    def analisar(
        self, selecao: list[ArquivoSelecionado], identificador: str
    ) -> ResultadoDeAnalise:
        """Executa o pipeline completo de análise.

        Passos:
        1. Validar identificador — se inválido, levanta ErroDeIdentificador.
        2. Se seleção é vazia — retorna resultado com mensagem de erro (Req 3.6, 10.1).
        3. Para cada ArquivoSelecionado:
           a. Se app_id é None → erro "Aplicação não informada", skip.
           b. Resolver parser/padrão via registro → falha → erro, skip.
           c. Carregar arquivo → falha → erro, skip.
           d. Interpretar linhas (com ordem_de_leitura correta).
           e. Filtrar pelo identificador.
           f. Classificar cada entrada filtrada.
        4. Correlacionar VPL ↔ ORK se ambos presentes.
        5. Compor resultado: ordenar, agrupar, calcular contagens.
        6. Retornar ResultadoDeAnalise.

        Reassociação (Req 2.5): como cada ArquivoSelecionado é processado
        independentemente em ordem, a última aparição de um mesmo caminho com
        app_ids diferentes resulta na prevalência da última associação.

        Args:
            selecao: Lista de ArquivoSelecionado com caminho e app_id.
            identificador: Cadeia de texto a ser buscada nos logs.

        Returns:
            ResultadoDeAnalise com entradas filtradas, agrupadas, ordenadas,
            contagens e erros acumulados.

        Raises:
            ErroDeIdentificador: Se o identificador é inválido.
        """
        # 1. Validar identificador
        validar_identificador(identificador)

        # 2. Verificar se seleção é vazia (Req 3.6, 10.1)
        if not selecao:
            return ResultadoDeAnalise(
                identificador=identificador,
                mensagens=[
                    "Nenhum Arquivo de Log selecionado. "
                    "Selecione ao menos um arquivo para análise."
                ],
            )

        erros: list[MensagemDeErro] = []
        # Acumula entradas por app_id para posterior correlação e composição.
        # Reassociação: se o mesmo caminho aparece múltiplas vezes, apenas a
        # última iteração efetiva contribui (processamos todas em sequência,
        # cada uma é independente).
        from log_analyzer.core.modelos import EntradaDeLog

        todas_entradas: list[EntradaDeLog] = []

        # 3. Processar cada arquivo selecionado
        for arquivo in selecao:
            # 3a. Aplicação não informada (Req 2.3, 2.4)
            if arquivo.app_id is None:
                erros.append(
                    MensagemDeErro(
                        arquivo_ou_app=arquivo.caminho,
                        descricao="Aplicação não informada para este arquivo.",
                    )
                )
                continue

            # 3b. Resolver parser/padrão via registro
            try:
                parser, padrao = self._registro.obter(arquivo.app_id)
            except ErroDeRegistro as e:
                erros.append(
                    MensagemDeErro(
                        arquivo_ou_app=arquivo.app_id,
                        descricao=e.mensagem,
                    )
                )
                continue

            # 3c. Carregar arquivo
            resultado_carga = carregar_arquivo(arquivo.caminho)
            if isinstance(resultado_carga, MensagemDeErro):
                erros.append(resultado_carga)
                continue

            linhas: list[str] = resultado_carga

            # 3d. Interpretar linhas com parser (definir ordem_de_leitura correta)
            entradas_interpretadas = parser.interpretar_arquivo(linhas)
            # Atualizar ordem_de_leitura e aplicacao para cada entrada
            entradas_com_ordem: list[EntradaDeLog] = []
            for idx, entrada in enumerate(entradas_interpretadas):
                # O parser pode já definir o campo aplicacao, mas para garantir
                # consistência com a associação do ArquivoSelecionado, sobreescrevemos.
                entrada_atualizada = replace(
                    entrada,
                    aplicacao=arquivo.app_id,
                    ordem_de_leitura=idx,
                )
                entradas_com_ordem.append(entrada_atualizada)

            # 3e. Filtrar pelo identificador
            entradas_filtradas = filtrar_por_identificador(
                entradas_com_ordem, identificador
            )

            # 3f. Classificar cada entrada filtrada com o padrão da aplicação
            entradas_classificadas: list[EntradaDeLog] = []
            for entrada in entradas_filtradas:
                try:
                    categoria = padrao.classificar(entrada)
                    entradas_classificadas.append(
                        replace(entrada, categoria=categoria)
                    )
                except Exception:
                    # Req 5.6: se não for possível classificar, registrar erro
                    erros.append(
                        MensagemDeErro(
                            arquivo_ou_app=arquivo.app_id,
                            descricao=(
                                f"Erro ao classificar entrada da aplicação "
                                f"'{arquivo.app_id}'."
                            ),
                        )
                    )
                    entradas_classificadas.append(entrada)

            todas_entradas.extend(entradas_classificadas)

        # 4. Correlacionar VPL ↔ ORK se ambos presentes
        entradas_vpl = [e for e in todas_entradas if e.aplicacao == "VPL"]
        entradas_ork = [e for e in todas_entradas if e.aplicacao == "ORK"]
        entradas_outras = [
            e for e in todas_entradas if e.aplicacao not in ("VPL", "ORK")
        ]

        correlacao_encontrada = False
        if entradas_vpl and entradas_ork:
            # Ambos os lados presentes — correlacionar
            vpl_corr, ork_corr, correlacao_encontrada, erros_corr = (
                correlacionar_vpl_ork(entradas_vpl, entradas_ork, identificador)
            )
            erros.extend(erros_corr)
            todas_entradas = vpl_corr + ork_corr + entradas_outras
        elif entradas_vpl or entradas_ork:
            # Apenas um lado presente — verificar se o outro lado foi tentado
            # (i.e., havia arquivos selecionados para a outra app que falharam)
            apps_selecionadas = {
                a.app_id for a in selecao if a.app_id is not None
            }
            if "VPL" in apps_selecionadas and "ORK" in apps_selecionadas:
                # Ambos foram selecionados, mas um lado não produziu entradas
                vpl_corr, ork_corr, correlacao_encontrada, erros_corr = (
                    correlacionar_vpl_ork(
                        entradas_vpl, entradas_ork, identificador
                    )
                )
                erros.extend(erros_corr)
                todas_entradas = vpl_corr + ork_corr + entradas_outras

        # 5. Compor resultado
        linha_do_tempo = ordenar_linha_do_tempo(todas_entradas)
        entradas_por_aplicacao = agrupar_por_aplicacao(todas_entradas)
        contagem_por_categoria, contagem_por_aplicacao = calcular_contagens(
            todas_entradas
        )

        # Mensagens informativas
        mensagens: list[str] = []
        if not todas_entradas and not erros:
            mensagens.append(
                f"Nenhuma correspondência encontrada para o identificador "
                f"'{identificador}'."
            )

        # 6. Retornar ResultadoDeAnalise
        return ResultadoDeAnalise(
            identificador=identificador,
            entradas_por_aplicacao=entradas_por_aplicacao,
            linha_do_tempo=linha_do_tempo,
            contagem_por_categoria=contagem_por_categoria,
            contagem_por_aplicacao=contagem_por_aplicacao,
            correlacao_encontrada=correlacao_encontrada,
            erros=erros,
            mensagens=mensagens,
        )
