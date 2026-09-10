"""Pipeline streaming e fail-closed da Fase 2 para fontes VPL/ORK.

O módulo orquestra somente contratos do núcleo. Parsers concretos nunca são
importados: cada fonte é resolvida por :class:`Registro_de_Aplicacoes` e só
entra neste fluxo quando o parser implementa o protocolo opcional
:class:`Parser_de_Bloco`.

O primeiro passe mantém um bloco por vez, indexa apenas metadados/HMACs e
registra no máximo a informação de que houve fallback literal. O texto completo
só volta a existir para os intervalos selecionados no segundo passe. O índice e
seus temporários são fechados em ``finally`` em todos os caminhos.

Requirements: 1.1, 4.1, 5.1, 7.2, 8.3, 9.4, 10.3, 14.7,
15.1, 15.2, 15.3, 15.6, 15.8.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
import hashlib
import os
from pathlib import Path
import re
from typing import Final, cast

from log_analyzer.core.busca import (
    BuscadorDeCenario,
    ResultadoBusca,
    normalizar_consulta_de_cenario,
)
from log_analyzer.core.catalogo import (
    CatalogoDeRegras,
    CarregadorCatalogo,
)
from log_analyzer.core.classificacao import (
    ClassificadorDeCenario,
    ResultadoClassificacaoCenario,
)
from log_analyzer.core.composicao import (
    COBERTURA_ROTULADA_FASE2,
    compor_resultado_fase2,
)
from log_analyzer.core.correlacao import (
    CorrelacionadorVplOrk,
    ResultadoCorrelacaoVplOrk,
)
from log_analyzer.core.dsl_regras import (
    ContextoAvaliacaoDSL,
    ReferenciaEvidenciaDSL,
    TipoReferenciaDSL,
)
from log_analyzer.core.excecoes import (
    ErroDeArquivo,
    ErroDeCatalogo,
    ErroDeDecodificacao,
    ErroDeIntegridadeDaFonte,
    ErroDeRegistro,
    ErroDeSanitizacao,
)
from log_analyzer.core.explicabilidade import (
    CompositorDeExplicabilidade,
    MENSAGEM_CAUSA_RAIZ_NAO_DETERMINADA,
    MENSAGEM_SEM_REGRA_CORRESPONDENTE,
)
from log_analyzer.core.indice import IndiceTemporario
from log_analyzer.core.interfaces import (
    Padrao_de_Analise,
    Parser_de_Aplicacao,
    Parser_de_Bloco,
    TipoInicio,
)
from log_analyzer.core.materializacao import (
    FonteMaterializacao,
    MaterializadorSeletivo,
    ResultadoMaterializacao,
)
from log_analyzer.core.modelos import (
    ArquivoSelecionado,
    BaseCorrelacao,
    CampoEstruturado,
    Categoria,
    EntradaDeLog,
    EntradaIndexada,
    EstadoSanitizacao,
    Evidencia,
    FalhaDeEntrada,
    IdentificadorTecnico,
    MensagemDeErro,
    Proveniencia,
    ReferenciaTextoOriginal,
    ResultadoCorrelacao,
    ResultadoCausaRaiz,
    ResultadoDeAnalise,
    VinculoIdentificadores,
)
from log_analyzer.core.multiline import AgrupadorMultiline, BlocoLog
from log_analyzer.core.registro import Registro_de_Aplicacoes
from log_analyzer.core.streaming import (
    LeitorStreaming,
    LinhaFisica,
    MAXIMO_ARQUIVOS_POR_LOTE,
)
from log_analyzer.core.validacao import validar_identificador
from log_analyzer.core.vinculos import GrafoDeVinculos
from log_analyzer.core.visao_segura import SanitizadorDeResultado


_APLICACOES_CORRELACIONAVEIS: Final = ("VPL", "ORK")
_CATALOGO_PADRAO: Final = object()
_TOKEN_FONTE: Final = re.compile(r"<ARQUIVO_([1-9][0-9]*)>\Z")
_CODIGO_SEGURO: Final = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")
_REGRA_PIPELINE: Final = "pipeline-fase2-v1"

_CODIGO_PARSER = "PARSER_FAILURE"
_CODIGO_INDICE = "INDEX_FAILURE"
_CODIGO_PROCESSAMENTO = "SOURCE_PROCESSING_FAILURE"
_CODIGO_PROTOCOLO = "BLOCK_PARSER_REQUIRED"
_CODIGO_APLICACAO = "APPLICATION_UNAVAILABLE"
_CODIGO_APLICACAO_AUSENTE = "APPLICATION_NOT_INFORMED"
_CODIGO_MATERIALIZACAO = "MATERIALIZATION_FAILURE"
_CODIGO_CATALOGO = "CATALOG_ERROR"

_DETALHES_FALHA_ENTRADA: Final = {
    _CODIGO_PARSER: "A entrada não pôde ser interpretada pelo parser registrado.",
    "INVALID_UTF8": "A entrada contém uma sequência UTF-8 inválida.",
    "INDEX_IDENTIFIER_FAILURE": "Um identificador da entrada não pôde ser indexado.",
    "ENTRY_CLASSIFICATION_FAILURE": "A categoria por entrada não pôde ser calculada.",
}

_PRIORIDADE_FALHA_FONTE: Final = {
    "SOURCE_CHANGED": 100,
    "INVALID_UTF8": 90,
    _CODIGO_MATERIALIZACAO: 80,
    _CODIGO_INDICE: 70,
    _CODIGO_PROCESSAMENTO: 60,
}

FabricaIndice = Callable[[], IndiceTemporario]
FabricaGrafo = Callable[[], GrafoDeVinculos]
FabricaMaterializador = Callable[
    [Iterable[FonteMaterializacao]], MaterializadorSeletivo
]


class _FalhaLocalDeEntrada(Exception):
    """Sentinela interna sem conteúdo da fonte ou da exceção original."""


@dataclass(frozen=True, slots=True)
class _FontePreparada:
    arquivo_token: str
    app_id: str
    caminho: str = field(repr=False)
    parser: Parser_de_Aplicacao = field(repr=False)
    parser_de_bloco: Parser_de_Bloco = field(repr=False)
    padrao: Padrao_de_Analise = field(repr=False)
    leitor: LeitorStreaming = field(repr=False)


class _DetectorSeguro:
    """Isola falhas do detector trivalente na linha que as provocou."""

    __slots__ = ("_parser", "_linhas_com_falha")

    def __init__(self, parser: Parser_de_Bloco) -> None:
        self._parser = parser
        self._linhas_com_falha: set[int] = set()

    def detectar_inicio(self, linha: LinhaFisica) -> TipoInicio:
        try:
            tipo = self._parser.detectar_inicio(linha)
            if not isinstance(tipo, TipoInicio):
                raise TypeError
            return tipo
        except Exception:
            self._linhas_com_falha.add(linha.numero_1_based)
            # Uma falha de detecção não pode anexar o possível evento à entrada
            # anterior. O início aparente inválido cria uma entrada isolada.
            return TipoInicio.CABECALHO_APARENTE_INVALIDO

    def consumir_falha_do_bloco(self, bloco: BlocoLog) -> bool:
        linhas = {linha.numero_1_based for linha in bloco.linhas}
        encontradas = self._linhas_com_falha.intersection(linhas)
        self._linhas_com_falha.difference_update(encontradas)
        return bool(encontradas)


class _FalhasPorFonte:
    """Mantém exatamente uma falha segura por token de fonte."""

    __slots__ = ("_falhas",)

    def __init__(self) -> None:
        self._falhas: dict[str, tuple[int, str]] = {}

    def adicionar(self, arquivo_token: str, codigo: object) -> None:
        codigo_seguro = (
            str(codigo)
            if isinstance(codigo, str) and _CODIGO_SEGURO.fullmatch(codigo)
            else _CODIGO_PROCESSAMENTO
        )
        prioridade = _PRIORIDADE_FALHA_FONTE.get(codigo_seguro, 10)
        atual = self._falhas.get(arquivo_token)
        if atual is None or prioridade > atual[0]:
            self._falhas[arquivo_token] = (prioridade, codigo_seguro)

    def contem(self, arquivo_token: str) -> bool:
        return arquivo_token in self._falhas

    def mensagens(self) -> list[MensagemDeErro]:
        return [
            MensagemDeErro(arquivo_token, self._falhas[arquivo_token][1])
            for arquivo_token in sorted(self._falhas, key=_ordem_token)
        ]


class PipelineFase2:
    """Orquestrador streaming, isolado do fluxo legado/VOCI.

    A instância guarda apenas dependências imutáveis. Cada chamada cria índice,
    grafo, tokens e seleção novos; portanto uma análise não contamina a
    seguinte. A fachada pública decide quando chamar este pipeline na tarefa
    12.2 — este módulo não altera ``Analisador_de_Logs``.
    """

    def __init__(
        self,
        registro: Registro_de_Aplicacoes,
        *,
        catalogo: object = _CATALOGO_PADRAO,
        fabrica_indice: FabricaIndice = IndiceTemporario,
        fabrica_grafo: FabricaGrafo = GrafoDeVinculos,
        fabrica_materializador: FabricaMaterializador = MaterializadorSeletivo,
        sanitizador: SanitizadorDeResultado | None = None,
    ) -> None:
        if not isinstance(registro, Registro_de_Aplicacoes):
            raise TypeError("registro deve ser Registro_de_Aplicacoes.")
        for nome, fabrica in (
            ("fabrica_indice", fabrica_indice),
            ("fabrica_grafo", fabrica_grafo),
            ("fabrica_materializador", fabrica_materializador),
        ):
            if not callable(fabrica):
                raise TypeError(f"{nome} deve ser chamável.")
        if sanitizador is not None and not callable(
            getattr(sanitizador, "criar_visao_segura", None)
        ):
            raise TypeError(
                "sanitizador deve fornecer criar_visao_segura()."
            )

        self._registro = registro
        self._catalogo_configurado = catalogo
        self._fabrica_indice = fabrica_indice
        self._fabrica_grafo = fabrica_grafo
        self._fabrica_materializador = fabrica_materializador
        self._sanitizador = sanitizador or SanitizadorDeResultado()

    def executar(
        self,
        selecao: Iterable[ArquivoSelecionado],
        identificador: str,
    ) -> ResultadoDeAnalise:
        """Executa a análise e retorna somente a visão sanitizada concluída.

        A consulta é validada antes de enumerar ``selecao``, resolver plugins,
        abrir arquivos ou criar recursos temporários. Assim, rejeições mantêm
        todo estado externo observável inalterado.
        """

        # Esta ordem é requisito de atomicidade e é intencional.
        validar_identificador(identificador)
        consulta_normalizada = normalizar_consulta_de_cenario(
            identificador, validar=False
        )
        fontes_solicitadas = _materializar_selecao(selecao)

        indice: IndiceTemporario | None = None
        try:
            indice = self._fabrica_indice()
            if not isinstance(indice, IndiceTemporario):
                raise TypeError("fabrica_indice deve produzir IndiceTemporario.")
            grafo = self._fabrica_grafo()
            if not isinstance(grafo, GrafoDeVinculos):
                raise TypeError("fabrica_grafo deve produzir GrafoDeVinculos.")

            falhas_fontes = _FalhasPorFonte()
            fontes, app_por_token = self._preparar_fontes(
                fontes_solicitadas,
                falhas_fontes,
            )

            entradas_indexadas: list[EntradaIndexada] = []
            fontes_materializacao: list[FonteMaterializacao] = []
            fontes_por_token: dict[str, _FontePreparada] = {}
            tokens_concluidos: set[str] = set()
            ids_fallback_literal: set[str] = set()
            falhas_extras: dict[str, list[FalhaDeEntrada]] = {}

            for fonte in fontes:
                fontes_por_token[fonte.arquivo_token] = fonte
                concluiu = self._indexar_fonte(
                    fonte,
                    indice,
                    grafo,
                    consulta_normalizada=consulta_normalizada,
                    consulta_literal=identificador.casefold(),
                    entradas_indexadas=entradas_indexadas,
                    ids_fallback_literal=ids_fallback_literal,
                    falhas_extras=falhas_extras,
                    falhas_fontes=falhas_fontes,
                )
                if concluiu:
                    tokens_concluidos.add(fonte.arquivo_token)
                try:
                    fontes_materializacao.append(
                        FonteMaterializacao(
                            fonte.arquivo_token,
                            fonte.caminho,
                            fonte.leitor.fingerprint,
                        )
                    )
                except Exception:
                    falhas_fontes.adicionar(
                        fonte.arquivo_token, _CODIGO_PROCESSAMENTO
                    )
                    tokens_concluidos.discard(fonte.arquivo_token)

            self._indexar_vinculos(grafo, indice, entradas_indexadas)
            busca = self._buscar(
                entradas_indexadas,
                ids_fallback_literal,
                identificador,
                indice,
                grafo,
                falhas_fontes,
                fontes,
            )
            ids_selecionados = set(busca.entrada_ids)
            selecionadas = tuple(
                entrada
                for entrada in entradas_indexadas
                if entrada.entrada_id in ids_selecionados
            )

            materializacao = self._materializar(
                selecionadas,
                fontes_materializacao,
                indice,
                falhas_fontes,
            )
            for falha in materializacao.falhas:
                falhas_fontes.adicionar(
                    falha.arquivo_token or "<ARQUIVO_1>",
                    falha.codigo,
                )

            entradas_finais = self._reconstruir_entradas(
                materializacao,
                fontes_por_token,
                falhas_extras,
            )
            correlacao, entradas_correlacionadas = _correlacionar(
                entradas_finais,
                grafo,
                busca,
            )

            tokens_alterados = {
                falha.arquivo_token
                for falha in materializacao.falhas
                if isinstance(falha, ErroDeIntegridadeDaFonte)
                and falha.arquivo_token is not None
            }
            tokens_validos = tokens_concluidos - tokens_alterados
            aplicacoes_analisadas = _aplicacoes_analisadas(
                fontes, tokens_validos
            )
            aplicacoes_ausentes = _aplicacoes_ausentes_ou_invalidas(
                aplicacoes_analisadas,
                app_por_token,
            )

            vinculos_cenario = _vinculos_do_cenario(busca, correlacao)
            catalogo, erro_catalogo = self._resolver_catalogo()
            contexto = ContextoAvaliacaoDSL(
                entradas=tuple(entradas_correlacionadas),
                aplicacoes=tuple(aplicacoes_analisadas),
                vinculos=vinculos_cenario,
            )
            classificacao = ClassificadorDeCenario(catalogo).classificar(
                contexto
            )
            classificacao, evidencias_classificacao = (
                _materializar_evidencias_da_classificacao(
                    classificacao,
                    entradas_correlacionadas,
                    vinculos_cenario,
                )
            )

            evidencias = _sem_duplicatas(
                (*correlacao.correlacao.evidencias, *evidencias_classificacao)
            )
            mensagens = _mensagens_explicaveis(
                entradas_correlacionadas,
                classificacao,
                evidencias,
                correlacao.correlacao.vinculos_percorridos,
            )
            if not entradas_correlacionadas:
                mensagens.append(
                    "Nenhuma entrada correspondeu integralmente à consulta."
                )

            erros = falhas_fontes.mensagens()
            if erro_catalogo is not None:
                erros.append(
                    MensagemDeErro("<CATALOGO_FASE2>", erro_catalogo)
                )

            cobertura = (
                catalogo.cobertura.declaracao
                if isinstance(catalogo, CatalogoDeRegras)
                else COBERTURA_ROTULADA_FASE2
            )
            resultado_interno = compor_resultado_fase2(
                identificador,
                entradas_correlacionadas,
                categoria_de_cenario=classificacao.categoria_de_cenario,
                vinculos=vinculos_cenario,
                correlacao=correlacao.correlacao,
                evidencias=evidencias,
                regra_aplicada=classificacao.regra_aplicada,
                versao_catalogo=classificacao.versao_catalogo,
                estado_sanitizacao=EstadoSanitizacao.INTERNA_BRUTA,
                causa_raiz=classificacao.causa_raiz,
                aplicacoes_analisadas=aplicacoes_analisadas,
                aplicacoes_ausentes_ou_invalidas=aplicacoes_ausentes,
                cobertura_rotulada=cobertura,
                erros=erros,
                mensagens=mensagens,
            )
            return self._sanitizar(resultado_interno)
        finally:
            # ``MaterializadorSeletivo`` também pode fechar o índice, mas o
            # fechamento é idempotente. Este finally cobre falhas anteriores à
            # segunda passagem e garante a remoção de qualquer spill SQLite.
            if indice is not None:
                indice.close()

    analisar = executar

    def _preparar_fontes(
        self,
        selecao: tuple[ArquivoSelecionado, ...],
        falhas: _FalhasPorFonte,
    ) -> tuple[list[_FontePreparada], dict[str, str]]:
        preparadas: list[_FontePreparada] = []
        app_por_token: dict[str, str] = {}

        for numero, arquivo in enumerate(selecao, start=1):
            token = f"<ARQUIVO_{numero}>"
            if numero > MAXIMO_ARQUIVOS_POR_LOTE:
                falhas.adicionar(token, "BATCH_LIMIT_EXCEEDED")
                continue
            if arquivo.app_id is None:
                falhas.adicionar(token, _CODIGO_APLICACAO_AUSENTE)
                continue

            try:
                parser, padrao = self._registro.obter(arquivo.app_id)
            except ErroDeRegistro:
                falhas.adicionar(token, _CODIGO_APLICACAO)
                continue

            app_por_token[token] = arquivo.app_id
            if not isinstance(parser, Parser_de_Bloco):
                # VOCI e plugins line-based pertencem ao fluxo legado. A
                # fachada da tarefa 12.2 evita enviá-los para cá.
                falhas.adicionar(token, _CODIGO_PROTOCOLO)
                continue

            try:
                caminho = os.fspath(arquivo.caminho)
                leitor = LeitorStreaming(caminho, token)
            except ErroDeArquivo as erro:
                falhas.adicionar(token, erro.contexto.get("codigo"))
                continue
            except (TypeError, ValueError, OSError):
                falhas.adicionar(token, "FILE_UNAVAILABLE")
                continue

            preparadas.append(
                _FontePreparada(
                    arquivo_token=token,
                    app_id=arquivo.app_id,
                    caminho=caminho,
                    parser=parser,
                    parser_de_bloco=cast(Parser_de_Bloco, parser),
                    padrao=padrao,
                    leitor=leitor,
                )
            )

        return preparadas, app_por_token

    def _indexar_fonte(
        self,
        fonte: _FontePreparada,
        indice: IndiceTemporario,
        grafo: GrafoDeVinculos,
        *,
        consulta_normalizada: str,
        consulta_literal: str,
        entradas_indexadas: list[EntradaIndexada],
        ids_fallback_literal: set[str],
        falhas_extras: dict[str, list[FalhaDeEntrada]],
        falhas_fontes: _FalhasPorFonte,
    ) -> bool:
        detector = _DetectorSeguro(fonte.parser_de_bloco)
        agrupador = AgrupadorMultiline(
            detector,
            fonte.arquivo_token,
            fabrica_entrada_id=_entrada_id_seguro,
        )
        concluiu = True

        def processar(bloco: BlocoLog) -> None:
            nonlocal concluiu
            if not self._indexar_bloco(
                fonte,
                bloco,
                detector,
                indice,
                grafo,
                consulta_normalizada=consulta_normalizada,
                consulta_literal=consulta_literal,
                entradas_indexadas=entradas_indexadas,
                ids_fallback_literal=ids_fallback_literal,
                falhas_extras=falhas_extras,
                falhas_fontes=falhas_fontes,
            ):
                concluiu = False

        try:
            for linha in fonte.leitor.iterar_linhas():
                for bloco in agrupador.processar_linha(linha):
                    processar(bloco)
        except ErroDeArquivo as erro:
            falhas_fontes.adicionar(
                fonte.arquivo_token, erro.contexto.get("codigo")
            )
            concluiu = False
        except Exception:
            falhas_fontes.adicionar(
                fonte.arquivo_token, _CODIGO_PROCESSAMENTO
            )
            concluiu = False
        finally:
            try:
                for bloco in agrupador.finalizar():
                    processar(bloco)
            except Exception:
                falhas_fontes.adicionar(
                    fonte.arquivo_token, _CODIGO_PROCESSAMENTO
                )
                concluiu = False

        return concluiu

    def _indexar_bloco(
        self,
        fonte: _FontePreparada,
        bloco: BlocoLog,
        detector: _DetectorSeguro,
        indice: IndiceTemporario,
        grafo: GrafoDeVinculos,
        *,
        consulta_normalizada: str,
        consulta_literal: str,
        entradas_indexadas: list[EntradaIndexada],
        ids_fallback_literal: set[str],
        falhas_extras: dict[str, list[FalhaDeEntrada]],
        falhas_fontes: _FalhasPorFonte,
    ) -> bool:
        try:
            referencia = _referencia_exata(bloco, fonte.caminho)
        except Exception:
            falhas_fontes.adicionar(
                fonte.arquivo_token, _CODIGO_PROCESSAMENTO
            )
            return False

        falha_detector = detector.consumir_falha_do_bloco(bloco)
        texto = bloco.texto_original
        if falha_detector:
            indexada = _entrada_indexada_com_falha(
                fonte.app_id,
                bloco,
                referencia,
                (_CODIGO_PARSER,),
            )
        elif texto is None:
            indexada = _entrada_indexada_com_falha(
                fonte.app_id,
                bloco,
                referencia,
                ("INVALID_UTF8",),
            )
        else:
            try:
                produzida = fonte.parser_de_bloco.interpretar_bloco(bloco)
                indexada = _normalizar_indexada(
                    produzida,
                    fonte.app_id,
                    bloco,
                    referencia,
                )
            except Exception:
                indexada = _entrada_indexada_com_falha(
                    fonte.app_id,
                    bloco,
                    referencia,
                    (_CODIGO_PARSER,),
                )

        entrada_transitoria: EntradaDeLog | None = None
        if texto is not None and indexada.interpretada:
            try:
                entrada_transitoria = _reconstruir_entrada(
                    fonte.parser,
                    indexada,
                    texto,
                    arquivo_origem=None,
                )
            except Exception:
                indexada = _entrada_indexada_com_falha(
                    fonte.app_id,
                    bloco,
                    referencia,
                    (_CODIGO_PARSER,),
                )

        codigos = tuple(
            falha.codigo
            for falha in indexada.falhas
            if _CODIGO_SEGURO.fullmatch(falha.codigo) is not None
        )
        try:
            indice.adicionar_entrada(
                entrada_id=indexada.entrada_id,
                arquivo_token=indexada.texto_ref.arquivo_token,
                aplicacao_codigo=indexada.aplicacao,
                ordem_de_leitura=indexada.ordem_de_leitura,
                inicio_byte=indexada.texto_ref.inicio_byte,
                fim_byte=indexada.texto_ref.fim_byte,
                linha_inicial=indexada.texto_ref.linha_inicial,
                linha_final=indexada.texto_ref.linha_final,
                timestamp_normalizado=indexada.timestamp_normalizado,
                codigos=codigos,
            )
        except Exception:
            falhas_fontes.adicionar(fonte.arquivo_token, _CODIGO_INDICE)
            return False

        digests: list[str] = []
        igualdade_estruturada_indexada = False
        if entrada_transitoria is not None:
            for identificador_tecnico in entrada_transitoria.identificadores:
                try:
                    identificador_indexado = indice.indexar_identificador(
                        entrada_id=indexada.entrada_id,
                        namespace=(
                            identificador_tecnico.namespace_comparacao
                        ),
                        valor_normalizado=(
                            identificador_tecnico.valor_normalizado
                        ),
                    )
                    grafo.adicionar_identificador(identificador_tecnico)
                except Exception:
                    _adicionar_falha_extra(
                        falhas_extras,
                        indexada,
                        "INDEX_IDENTIFIER_FAILURE",
                    )
                    continue
                digests.append(identificador_indexado.hmac_sha256)
                if (
                    identificador_tecnico.valor_normalizado
                    == consulta_normalizada
                ):
                    igualdade_estruturada_indexada = True

        indexada = replace(
            indexada,
            identificadores_digest=tuple(digests),
        )
        entradas_indexadas.append(indexada)

        if (
            texto is not None
            and not igualdade_estruturada_indexada
            and consulta_literal in texto.casefold()
        ):
            # O texto não é guardado: apenas o fato de que o fallback literal
            # casou. O Buscador receberá a própria consulta como marcador.
            ids_fallback_literal.add(indexada.entrada_id)
        return True

    @staticmethod
    def _indexar_vinculos(
        grafo: GrafoDeVinculos,
        indice: IndiceTemporario,
        entradas_indexadas: list[EntradaIndexada],
    ) -> None:
        ids_indexados = {entrada.entrada_id for entrada in entradas_indexadas}
        for vinculo in grafo.arestas:
            if vinculo.evidencia.entrada_id not in ids_indexados:
                continue
            try:
                indice.adicionar_aresta(
                    origem_namespace=vinculo.origem.namespace_comparacao,
                    origem_valor_normalizado=vinculo.origem.valor_normalizado,
                    destino_namespace=vinculo.destino.namespace_comparacao,
                    destino_valor_normalizado=vinculo.destino.valor_normalizado,
                    relacao_codigo=vinculo.tipo_relacao,
                    evidencia_entrada_id=vinculo.evidencia.entrada_id,
                )
            except Exception:
                # A busca percorre somente o grafo validado; uma falha em sua
                # cópia não reversível no índice não cria relação implícita.
                continue

    @staticmethod
    def _buscar(
        entradas_indexadas: list[EntradaIndexada],
        ids_fallback_literal: set[str],
        identificador: str,
        indice: IndiceTemporario,
        grafo: GrafoDeVinculos,
        falhas_fontes: _FalhasPorFonte,
        fontes: list[_FontePreparada],
    ) -> ResultadoBusca:
        textos_minimos = {
            entrada_id: identificador
            for entrada_id in ids_fallback_literal
        }
        try:
            indice.flush()
            return BuscadorDeCenario(indice, grafo).buscar(
                entradas_indexadas,
                identificador,
                textos_por_entrada_id=textos_minimos,
            )
        except Exception:
            for fonte in fontes:
                falhas_fontes.adicionar(
                    fonte.arquivo_token, _CODIGO_INDICE
                )
            return ResultadoBusca(
                consulta_normalizada=normalizar_consulta_de_cenario(
                    identificador, validar=False
                )
            )

    def _materializar(
        self,
        selecionadas: tuple[EntradaIndexada, ...],
        fontes: list[FonteMaterializacao],
        indice: IndiceTemporario,
        falhas: _FalhasPorFonte,
    ) -> ResultadoMaterializacao:
        try:
            materializador = self._fabrica_materializador(fontes)
            if not callable(getattr(materializador, "materializar", None)):
                raise TypeError
            return materializador.materializar(
                selecionadas,
                indice_temporario=indice,
            )
        except (ErroDeIntegridadeDaFonte, ErroDeDecodificacao) as erro:
            if erro.arquivo_token is not None:
                falhas.adicionar(erro.arquivo_token, erro.codigo)
            return ResultadoMaterializacao(falhas=(erro,))
        except Exception:
            for entrada in selecionadas:
                falhas.adicionar(
                    entrada.texto_ref.arquivo_token,
                    _CODIGO_MATERIALIZACAO,
                )
            return ResultadoMaterializacao()

    @staticmethod
    def _reconstruir_entradas(
        materializacao: ResultadoMaterializacao,
        fontes_por_token: dict[str, _FontePreparada],
        falhas_extras: dict[str, list[FalhaDeEntrada]],
    ) -> list[EntradaDeLog]:
        entradas: list[EntradaDeLog] = []
        for materializada in materializacao.entradas:
            indexada = materializada.entrada_indexada
            fonte = fontes_por_token.get(indexada.texto_ref.arquivo_token)
            if fonte is None:
                continue
            try:
                entrada = _reconstruir_entrada(
                    fonte.parser,
                    indexada,
                    materializada.texto_original,
                    arquivo_origem=fonte.caminho,
                )
            except Exception:
                entrada = _entrada_nao_interpretada(
                    indexada,
                    materializada.texto_original,
                    arquivo_origem=fonte.caminho,
                    falhas_adicionais=(
                        _falha_de_entrada(indexada, _CODIGO_PARSER),
                    ),
                )

            extras = falhas_extras.get(indexada.entrada_id, ())
            if extras:
                entrada = replace(
                    entrada,
                    falhas=_sem_duplicatas((*entrada.falhas, *extras)),
                )
            entrada = _classificar_entrada(entrada, fonte.padrao)
            entradas.append(entrada)
        return entradas

    def _resolver_catalogo(
        self,
    ) -> tuple[CatalogoDeRegras | None, str | None]:
        configurado = self._catalogo_configurado
        if configurado is _CATALOGO_PADRAO:
            caminho = (
                Path(__file__).resolve().parent.parent
                / "catalogos"
                / "fase2.json"
            )
            try:
                return CarregadorCatalogo().carregar(caminho), None
            except ErroDeCatalogo:
                return None, _CODIGO_CATALOGO
        if isinstance(configurado, CatalogoDeRegras):
            return configurado, None
        if configurado is None:
            return None, None
        # Objetos inválidos são entregues ao classificador como ausência; não
        # se tenta interpretar dados executáveis nem adaptar formatos.
        return None, _CODIGO_CATALOGO

    def _sanitizar(self, resultado: ResultadoDeAnalise) -> ResultadoDeAnalise:
        try:
            visao = self._sanitizador.criar_visao_segura(resultado)
        except ErroDeSanitizacao:
            raise
        except Exception:
            raise ErroDeSanitizacao() from None
        if (
            not isinstance(visao, ResultadoDeAnalise)
            or visao.estado_sanitizacao is not EstadoSanitizacao.CONCLUIDA
        ):
            raise ErroDeSanitizacao() from None
        return visao


PipelineStreamingFase2 = PipelineFase2


def executar_pipeline_fase2(
    selecao: Iterable[ArquivoSelecionado],
    identificador: str,
    *,
    registro: Registro_de_Aplicacoes,
    catalogo: object = _CATALOGO_PADRAO,
    fabrica_indice: FabricaIndice = IndiceTemporario,
    fabrica_grafo: FabricaGrafo = GrafoDeVinculos,
    fabrica_materializador: FabricaMaterializador = MaterializadorSeletivo,
    sanitizador: SanitizadorDeResultado | None = None,
) -> ResultadoDeAnalise:
    """Atalho funcional para uma execução independente do pipeline."""

    return PipelineFase2(
        registro,
        catalogo=catalogo,
        fabrica_indice=fabrica_indice,
        fabrica_grafo=fabrica_grafo,
        fabrica_materializador=fabrica_materializador,
        sanitizador=sanitizador,
    ).executar(selecao, identificador)


def _materializar_selecao(
    selecao: Iterable[ArquivoSelecionado],
) -> tuple[ArquivoSelecionado, ...]:
    if isinstance(selecao, (str, bytes)):
        raise TypeError("selecao deve ser um iterável de ArquivoSelecionado.")
    try:
        itens = tuple(selecao)
    except TypeError:
        raise TypeError(
            "selecao deve ser um iterável de ArquivoSelecionado."
        ) from None
    if not all(isinstance(item, ArquivoSelecionado) for item in itens):
        raise TypeError("selecao deve conter somente ArquivoSelecionado.")
    return itens


def _entrada_id_seguro(arquivo_token: str, ordem: int) -> str:
    correspondencia = _TOKEN_FONTE.fullmatch(arquivo_token)
    if correspondencia is None:
        raise ValueError("Token local de arquivo inválido.")
    return f"ARQUIVO_{correspondencia.group(1)}_ENTRADA_{ordem}"


def _ordem_token(token: str) -> tuple[int, str]:
    correspondencia = _TOKEN_FONTE.fullmatch(token)
    if correspondencia is None:
        return (2**31 - 1, token)
    return (int(correspondencia.group(1)), token)


def _referencia_exata(
    bloco: BlocoLog,
    caminho: str,
) -> ReferenciaTextoOriginal:
    referencia = bloco.texto_ref
    if referencia is not None:
        return referencia

    # Blocos mistos com bytes indecodificáveis não podem reconstruir o SHA a
    # partir de texto. Calcula-se somente o digest do intervalo, em chunks
    # fixos, sem manter ou decodificar os bytes.
    restante = bloco.fim_byte - bloco.inicio_byte
    digest = hashlib.sha256()
    with open(caminho, "rb", buffering=0) as stream:
        stream.seek(bloco.inicio_byte, os.SEEK_SET)
        while restante:
            parte = stream.read(min(restante, 64 * 1024))
            if not parte:
                raise OSError
            digest.update(parte)
            restante -= len(parte)
    return ReferenciaTextoOriginal(
        arquivo_token=bloco.arquivo_token,
        inicio_byte=bloco.inicio_byte,
        fim_byte=bloco.fim_byte,
        linha_inicial=bloco.linha_inicial,
        linha_final=bloco.linha_final,
        sha256=digest.hexdigest(),
    )


def _normalizar_indexada(
    produzida: object,
    aplicacao: str,
    bloco: BlocoLog,
    referencia: ReferenciaTextoOriginal,
) -> EntradaIndexada:
    if not isinstance(produzida, EntradaIndexada):
        raise _FalhaLocalDeEntrada
    if (
        produzida.entrada_id != bloco.entrada_id
        or produzida.ordem_de_leitura != bloco.ordem_de_leitura
        or produzida.texto_ref != referencia
    ):
        raise _FalhaLocalDeEntrada

    cabecalho = tuple(
        replace(
            campo,
            proveniencia=_normalizar_proveniencia_indexada(
                campo.proveniencia, bloco
            ),
        )
        for campo in produzida.cabecalho
    )
    falhas = tuple(
        replace(
            falha,
            proveniencia=_normalizar_proveniencia_indexada(
                falha.proveniencia, bloco
            ),
        )
        for falha in produzida.falhas
    )
    return replace(
        produzida,
        aplicacao=aplicacao,
        texto_ref=referencia,
        cabecalho=cabecalho,
        identificadores_digest=(),
        falhas=falhas,
    )


def _normalizar_proveniencia_indexada(
    proveniencia: Proveniencia,
    bloco: BlocoLog,
) -> Proveniencia:
    linha_inicial = proveniencia.linha_inicial
    linha_final = proveniencia.linha_final
    if (
        linha_inicial < bloco.linha_inicial
        or linha_final > bloco.linha_final
    ):
        linha_inicial = bloco.linha_inicial
        linha_final = bloco.linha_final
    return replace(
        proveniencia,
        arquivo_token=bloco.arquivo_token,
        entrada_id=bloco.entrada_id,
        linha_inicial=linha_inicial,
        linha_final=linha_final,
    )


def _entrada_indexada_com_falha(
    aplicacao: str,
    bloco: BlocoLog,
    referencia: ReferenciaTextoOriginal,
    codigos: Iterable[str],
) -> EntradaIndexada:
    base = EntradaIndexada(
        entrada_id=bloco.entrada_id,
        aplicacao=aplicacao,
        ordem_de_leitura=bloco.ordem_de_leitura,
        texto_ref=referencia,
        cabecalho=(),
        identificadores_digest=(),
        timestamp_original=None,
        timestamp_normalizado=None,
        falhas=(),
        interpretada=False,
    )
    falhas = _sem_duplicatas(
        tuple(_falha_de_entrada(base, codigo) for codigo in codigos)
    )
    return replace(base, falhas=falhas)


def _falha_de_entrada(
    entrada: EntradaIndexada,
    codigo: str,
) -> FalhaDeEntrada:
    detalhe = _DETALHES_FALHA_ENTRADA.get(
        codigo, "A entrada apresentou uma falha isolada e segura."
    )
    return FalhaDeEntrada(
        codigo=codigo,
        proveniencia=Proveniencia(
            arquivo_token=entrada.texto_ref.arquivo_token,
            entrada_id=entrada.entrada_id,
            linha_inicial=entrada.texto_ref.linha_inicial,
            linha_final=entrada.texto_ref.linha_final,
            regra_extracao=_REGRA_PIPELINE,
        ),
        detalhe_seguro=detalhe,
    )


def _adicionar_falha_extra(
    destino: dict[str, list[FalhaDeEntrada]],
    entrada: EntradaIndexada,
    codigo: str,
) -> None:
    falha = _falha_de_entrada(entrada, codigo)
    colecao = destino.setdefault(entrada.entrada_id, [])
    if falha not in colecao:
        colecao.append(falha)


def _reconstruir_entrada(
    parser: Parser_de_Aplicacao,
    indexada: EntradaIndexada,
    texto_original: str,
    *,
    arquivo_origem: str | None,
) -> EntradaDeLog:
    if not indexada.interpretada:
        return _entrada_nao_interpretada(
            indexada,
            texto_original,
            arquivo_origem=arquivo_origem,
        )

    try:
        direta = parser.interpretar_entrada(texto_original)
    except Exception:
        raise _FalhaLocalDeEntrada from None
    if (
        not isinstance(direta, EntradaDeLog)
        or not direta.interpretada
        or direta.texto_original != texto_original
        or direta.timestamp_original != indexada.timestamp_original
        or direta.timestamp_normalizado != indexada.timestamp_normalizado
    ):
        raise _FalhaLocalDeEntrada

    campos = tuple(
        replace(
            campo,
            proveniencia=_deslocar_proveniencia_direta(
                campo.proveniencia, indexada
            ),
        )
        for campo in direta.campos_estruturados
    )
    identificadores = tuple(
        replace(
            identificador,
            proveniencia=_deslocar_proveniencia_direta(
                identificador.proveniencia, indexada
            ),
        )
        for identificador in direta.identificadores
    )
    falhas_diretas = tuple(
        replace(
            falha,
            proveniencia=_deslocar_proveniencia_direta(
                falha.proveniencia, indexada
            ),
        )
        for falha in direta.falhas
    )
    falhas = _sem_duplicatas((*indexada.falhas, *falhas_diretas))
    referencia = indexada.texto_ref
    return replace(
        direta,
        texto_original=texto_original,
        aplicacao=indexada.aplicacao,
        ordem_de_leitura=indexada.ordem_de_leitura,
        correlacionada=False,
        entrada_id=indexada.entrada_id,
        arquivo_origem=arquivo_origem,
        arquivo_token=referencia.arquivo_token,
        posicao_inicial=referencia.linha_inicial,
        posicao_final=referencia.linha_final,
        campos_estruturados=campos,
        identificadores=identificadores,
        falhas=falhas,
        representacao_sanitizada=None,
    )


def _deslocar_proveniencia_direta(
    proveniencia: Proveniencia,
    indexada: EntradaIndexada,
) -> Proveniencia:
    referencia = indexada.texto_ref
    deslocamento = referencia.linha_inicial - 1
    linha_inicial = proveniencia.linha_inicial + deslocamento
    linha_final = proveniencia.linha_final + deslocamento
    if (
        linha_inicial < referencia.linha_inicial
        or linha_final > referencia.linha_final
    ):
        linha_inicial = referencia.linha_inicial
        linha_final = referencia.linha_final
    return replace(
        proveniencia,
        arquivo_token=referencia.arquivo_token,
        entrada_id=indexada.entrada_id,
        linha_inicial=linha_inicial,
        linha_final=linha_final,
    )


def _entrada_nao_interpretada(
    indexada: EntradaIndexada,
    texto_original: str,
    *,
    arquivo_origem: str | None,
    falhas_adicionais: Iterable[FalhaDeEntrada] = (),
) -> EntradaDeLog:
    referencia = indexada.texto_ref
    return EntradaDeLog(
        texto_original=texto_original,
        aplicacao=indexada.aplicacao,
        ordem_de_leitura=indexada.ordem_de_leitura,
        interpretada=False,
        entrada_id=indexada.entrada_id,
        arquivo_origem=arquivo_origem,
        arquivo_token=referencia.arquivo_token,
        posicao_inicial=referencia.linha_inicial,
        posicao_final=referencia.linha_final,
        falhas=_sem_duplicatas(
            (*indexada.falhas, *tuple(falhas_adicionais))
        ),
    )


def _classificar_entrada(
    entrada: EntradaDeLog,
    padrao: Padrao_de_Analise,
) -> EntradaDeLog:
    try:
        categoria = padrao.classificar(entrada)
        if not isinstance(categoria, Categoria):
            raise TypeError
        return replace(entrada, categoria=categoria)
    except Exception:
        if entrada.entrada_id is None or entrada.arquivo_token is None:
            return entrada
        referencia = ReferenciaTextoOriginal(
            arquivo_token=entrada.arquivo_token,
            inicio_byte=0,
            fim_byte=0,
            linha_inicial=entrada.posicao_inicial or 1,
            linha_final=entrada.posicao_final or 1,
            sha256="0" * 64,
        )
        indexada = EntradaIndexada(
            entrada_id=entrada.entrada_id,
            aplicacao=entrada.aplicacao,
            ordem_de_leitura=entrada.ordem_de_leitura,
            texto_ref=referencia,
            cabecalho=(),
            identificadores_digest=(),
            timestamp_original=None,
            timestamp_normalizado=None,
            falhas=(),
            interpretada=False,
        )
        falha = _falha_de_entrada(
            indexada, "ENTRY_CLASSIFICATION_FAILURE"
        )
        return replace(
            entrada,
            falhas=_sem_duplicatas((*entrada.falhas, falha)),
        )


def _correlacionar(
    entradas: list[EntradaDeLog],
    grafo: GrafoDeVinculos,
    busca: ResultadoBusca,
) -> tuple[ResultadoCorrelacaoVplOrk, list[EntradaDeLog]]:
    vpl = tuple(entrada for entrada in entradas if entrada.aplicacao == "VPL")
    ork = tuple(entrada for entrada in entradas if entrada.aplicacao == "ORK")
    try:
        resultado = CorrelacionadorVplOrk(grafo).correlacionar(
            vpl,
            ork,
            caminhos_evidenciados=busca.caminhos_evidenciados,
        )
    except Exception:
        try:
            resultado = CorrelacionadorVplOrk().correlacionar(vpl, ork)
        except Exception:
            correlacao = ResultadoCorrelacao(
                encontrada=False,
                base_primaria=BaseCorrelacao.NENHUMA,
                bases=(BaseCorrelacao.NENHUMA,),
                motivo_seguro=(
                    "Nenhuma evidência válida sustenta a correlação."
                ),
            )
            resultado = ResultadoCorrelacaoVplOrk(
                entradas_vpl=vpl,
                entradas_ork=ork,
                correlacao=correlacao,
            )

    atualizadas = {
        entrada.entrada_id: entrada
        for entrada in (*resultado.entradas_vpl, *resultado.entradas_ork)
        if entrada.entrada_id is not None
    }
    ordenadas = [
        atualizadas.get(entrada.entrada_id, entrada) for entrada in entradas
    ]
    return resultado, ordenadas


def _aplicacoes_analisadas(
    fontes: list[_FontePreparada],
    tokens_validos: set[str],
) -> list[str]:
    resultado: list[str] = []
    for fonte in fontes:
        if (
            fonte.arquivo_token in tokens_validos
            and fonte.app_id not in resultado
        ):
            resultado.append(fonte.app_id)
    return resultado


def _aplicacoes_ausentes_ou_invalidas(
    analisadas: list[str],
    app_por_token: dict[str, str],
) -> list[str]:
    resultado = [
        app for app in _APLICACOES_CORRELACIONAVEIS if app not in analisadas
    ]
    for app in app_por_token.values():
        if app not in analisadas and app not in resultado:
            resultado.append(app)
    return resultado


def _vinculos_do_cenario(
    busca: ResultadoBusca,
    correlacao: ResultadoCorrelacaoVplOrk,
) -> tuple[VinculoIdentificadores, ...]:
    return _sem_duplicatas(
        (
            *cast(tuple[VinculoIdentificadores, ...], busca.vinculos_percorridos),
            *correlacao.correlacao.vinculos_percorridos,
        )
    )


def _materializar_evidencias_da_classificacao(
    classificacao: ResultadoClassificacaoCenario,
    entradas: list[EntradaDeLog],
    vinculos: tuple[VinculoIdentificadores, ...],
) -> tuple[ResultadoClassificacaoCenario, tuple[Evidencia, ...]]:
    if not classificacao.classificada:
        return classificacao, ()

    compositor = CompositorDeExplicabilidade()
    evidencias: list[Evidencia] = []
    try:
        for cobertura in classificacao.evidencias:
            produzidas = tuple(
                evidencia
                for referencia in cobertura.evidencias
                if (
                    evidencia := _evidencia_da_referencia(
                        compositor,
                        cobertura.condicao_id,
                        referencia,
                        classificacao,
                        entradas,
                        vinculos,
                    )
                )
                is not None
            )
            if not produzidas:
                raise _FalhaLocalDeEntrada
            for evidencia in produzidas:
                if evidencia not in evidencias:
                    evidencias.append(evidencia)
    except Exception:
        return (
            ResultadoClassificacaoCenario(
                categoria_de_cenario=Categoria.NAO_CLASSIFICADA,
                versao_catalogo=classificacao.versao_catalogo,
            ),
            (),
        )
    return classificacao, tuple(evidencias)


def _evidencia_da_referencia(
    compositor: CompositorDeExplicabilidade,
    condicao_id: str,
    referencia: ReferenciaEvidenciaDSL,
    classificacao: ResultadoClassificacaoCenario,
    entradas: list[EntradaDeLog],
    vinculos: tuple[VinculoIdentificadores, ...],
) -> Evidencia | None:
    entrada = _entrada_da_referencia(referencia, entradas)
    if entrada is None:
        return None

    if referencia.tipo is TipoReferenciaDSL.CAMPO:
        campo = next(
            (
                item
                for item in entrada.campos_estruturados
                if item.nome == referencia.nome_estrutural
            ),
            None,
        )
        if campo is None:
            return None
        return compositor.construir_evidencia_de_campo(
            entrada,
            campo,
            condicao_id,
            f"{campo.nome}={campo.valor_original}",
            tipo="condicao_de_campo",
        )

    if referencia.tipo is TipoReferenciaDSL.VINCULO:
        vinculo = next(
            (
                item
                for item in vinculos
                if item.evidencia.entrada_id == entrada.entrada_id
                and item.evidencia.arquivo_token == entrada.arquivo_token
            ),
            None,
        )
        if vinculo is None:
            return None
        return compositor.construir_evidencia_de_vinculo(
            entrada,
            vinculo,
            f"vinculo={vinculo.tipo_relacao}",
            campo_ou_condicao=condicao_id,
        )

    regra = classificacao.regra_aplicada
    if regra is None:
        return None
    return compositor.construir_evidencia_de_entrada(
        entrada,
        condicao_id,
        f"aplicacao={entrada.aplicacao}",
        tipo="condicao_estruturada",
        regra_extracao_ou_vinculo=(
            f"catalogo:{regra.rule_id}:v{regra.versao}"
        ),
    )


def _entrada_da_referencia(
    referencia: ReferenciaEvidenciaDSL,
    entradas: list[EntradaDeLog],
) -> EntradaDeLog | None:
    candidatas = entradas
    if referencia.entrada_id is not None:
        candidatas = [
            entrada
            for entrada in candidatas
            if entrada.entrada_id == referencia.entrada_id
        ]
    if referencia.arquivo_token is not None:
        candidatas = [
            entrada
            for entrada in candidatas
            if entrada.arquivo_token == referencia.arquivo_token
        ]
    if referencia.aplicacao is not None:
        candidatas = [
            entrada
            for entrada in candidatas
            if entrada.aplicacao == referencia.aplicacao
        ]
    return candidatas[0] if candidatas else None


def _mensagens_explicaveis(
    entradas: list[EntradaDeLog],
    classificacao: ResultadoClassificacaoCenario,
    evidencias: tuple[Evidencia, ...],
    vinculos: tuple[VinculoIdentificadores, ...],
) -> list[str]:
    try:
        explicacao = CompositorDeExplicabilidade().compor(
            entradas,
            classificacao.categoria_de_cenario,
            regra_aplicada=classificacao.regra_aplicada,
            condicoes_satisfeitas=classificacao.condicoes_satisfeitas,
            evidencias=evidencias,
            vinculos_percorridos=vinculos,
            causa_raiz=classificacao.causa_raiz,
        )
        return [
            mensagem.descricao_segura for mensagem in explicacao.mensagens
        ]
    except Exception:
        mensagens: list[str] = []
        if (
            classificacao.categoria_de_cenario
            is Categoria.NAO_CLASSIFICADA
        ):
            mensagens.append(MENSAGEM_SEM_REGRA_CORRESPONDENTE)
        if classificacao.causa_raiz == ResultadoCausaRaiz():
            mensagens.append(MENSAGEM_CAUSA_RAIZ_NAO_DETERMINADA)
        return mensagens


def _sem_duplicatas(valores: Iterable[object]):
    resultado: list[object] = []
    for valor in valores:
        if valor not in resultado:
            resultado.append(valor)
    return tuple(resultado)


__all__ = [
    "PipelineFase2",
    "PipelineStreamingFase2",
    "executar_pipeline_fase2",
]
