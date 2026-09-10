"""Construção fail-closed da visão segura de um resultado de análise.

O resultado interno nunca é alterado nem devolvido parcialmente. A construção
ocorre em quatro etapas deliberadamente separadas:

1. captura de um snapshot raso das coleções mutáveis do resultado;
2. registro e cópia dos campos estruturados sensíveis;
3. sanitização dos textos livres e montagem de uma cópia ainda interna;
4. varredura independente da forma serializada e, somente depois, marcação
   como :class:`~log_analyzer.core.modelos.EstadoSanitizacao.CONCLUIDA`.

Qualquer falha, inclusive na cópia, no scanner ou no descarte do contexto, é
convertida em uma nova :class:`ErroDeSanitizacao`, cujo código e mensagem são
constantes. A visão intermediária permanece local e nunca atravessa a API.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, replace
import json
import re
from typing import Protocol

from log_analyzer.core.excecoes import ErroDeSanitizacao
from log_analyzer.core.governanca import ScannerDeFixtures
from log_analyzer.core.modelos import (
    BaseCorrelacao,
    CampoEstruturado,
    Categoria,
    EntradaDeLog,
    EstadoSanitizacao,
    Evidencia,
    FalhaDeEntrada,
    IdentificadorTecnico,
    MensagemDeErro,
    Proveniencia,
    ReferenciaRegra,
    ResultadoCausaRaiz,
    ResultadoCorrelacao,
    ResultadoDeAnalise,
    VinculoIdentificadores,
)
from log_analyzer.core.sanitizacao import (
    SanitizationContext,
    TipoDadoSensivel,
)
from log_analyzer.core.serializacao import serializar_resultado_de_analise


CODIGO_FALHA_VISAO_SEGURA = ErroDeSanitizacao.CODIGO_PADRAO
MENSAGEM_FALHA_VISAO_SEGURA = ErroDeSanitizacao.MENSAGEM_SEGURA

_PADRAO_TOKEN_ARQUIVO = re.compile(r"<ARQUIVO_([1-9][0-9]*)>\Z")
_PADRAO_TOKEN_ARQUIVO_EM_TEXTO = re.compile(r"<ARQUIVO_[1-9][0-9]*>")
_PADRAO_APP_ID_SEGURO = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")


class _ScannerTextual(Protocol):
    def inspecionar_texto(
        self,
        texto: str,
        *,
        arquivo: str = "<ARQUIVO>",
        linha_inicial: int = 1,
    ) -> Iterable[object]: ...


@dataclass(frozen=True, slots=True)
class _ErroSnapshot:
    arquivo_ou_app: str
    descricao: str


@dataclass(frozen=True, slots=True)
class _SnapshotResultado:
    identificador: str
    entradas_por_aplicacao: tuple[tuple[str, tuple[EntradaDeLog, ...]], ...]
    linha_do_tempo: tuple[EntradaDeLog, ...]
    contagem_por_categoria: tuple[tuple[Categoria, int], ...]
    contagem_por_aplicacao: tuple[tuple[str, int], ...]
    correlacao_encontrada: bool
    erros: tuple[_ErroSnapshot, ...]
    mensagens: tuple[str, ...]
    categoria_de_cenario: Categoria
    entradas_sem_ordenacao_temporal: tuple[EntradaDeLog, ...]
    identificadores_extraidos: tuple[IdentificadorTecnico, ...]
    vinculos: tuple[VinculoIdentificadores, ...]
    correlacao: ResultadoCorrelacao | None
    evidencias: tuple[Evidencia, ...]
    regra_aplicada: ReferenciaRegra | None
    versao_catalogo: str
    causa_raiz: ResultadoCausaRaiz
    aplicacoes_analisadas: tuple[str, ...]
    aplicacoes_ausentes_ou_invalidas: tuple[str, ...]
    cobertura_rotulada: str


def _capturar_snapshot(resultado: ResultadoDeAnalise) -> _SnapshotResultado:
    """Copia todas as coleções mutáveis sem compartilhar containers internos."""

    if not isinstance(resultado, ResultadoDeAnalise):
        raise TypeError("resultado deve ser ResultadoDeAnalise.")

    erros: list[_ErroSnapshot] = []
    for erro in resultado.erros:
        if not isinstance(erro, MensagemDeErro):
            raise TypeError("erros deve conter MensagemDeErro.")
        erros.append(_ErroSnapshot(erro.arquivo_ou_app, erro.descricao))

    return _SnapshotResultado(
        identificador=resultado.identificador,
        entradas_por_aplicacao=tuple(
            (aplicacao, tuple(entradas))
            for aplicacao, entradas in resultado.entradas_por_aplicacao.items()
        ),
        linha_do_tempo=tuple(resultado.linha_do_tempo),
        contagem_por_categoria=tuple(resultado.contagem_por_categoria.items()),
        contagem_por_aplicacao=tuple(resultado.contagem_por_aplicacao.items()),
        correlacao_encontrada=resultado.correlacao_encontrada,
        erros=tuple(erros),
        mensagens=tuple(resultado.mensagens),
        categoria_de_cenario=resultado.categoria_de_cenario,
        entradas_sem_ordenacao_temporal=tuple(
            resultado.entradas_sem_ordenacao_temporal
        ),
        identificadores_extraidos=tuple(resultado.identificadores_extraidos),
        vinculos=tuple(resultado.vinculos),
        correlacao=resultado.correlacao,
        evidencias=tuple(resultado.evidencias),
        regra_aplicada=resultado.regra_aplicada,
        versao_catalogo=resultado.versao_catalogo,
        causa_raiz=resultado.causa_raiz,
        aplicacoes_analisadas=tuple(resultado.aplicacoes_analisadas),
        aplicacoes_ausentes_ou_invalidas=tuple(
            resultado.aplicacoes_ausentes_ou_invalidas
        ),
        cobertura_rotulada=resultado.cobertura_rotulada,
    )


class ScannerFinalDeResultado:
    """Scanner independente aplicado à representação serializada completa.

    A política reutiliza o scanner defensivo de fixtures, cuja implementação é
    independente do mapa do :class:`SanitizationContext`. Tokens locais de
    arquivo já aprovados pelo pipeline são mascarados apenas na cópia enviada
    ao scanner, pois não constituem dados de origem e não fazem parte do
    vocabulário de placeholders de fixtures.
    """

    __slots__ = ("_scanner",)

    def __init__(self, scanner: _ScannerTextual | None = None) -> None:
        self._scanner = ScannerDeFixtures() if scanner is None else scanner

    def validar(self, resultado: ResultadoDeAnalise) -> None:
        """Rejeita integralmente a visão se qualquer achado permanecer."""

        try:
            serializado = serializar_resultado_de_analise(resultado)
            texto = json.dumps(
                serializado,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            texto_para_scanner = _PADRAO_TOKEN_ARQUIVO_EM_TEXTO.sub(
                "ARQUIVO_TOKEN_SEGURO",
                texto,
            )
            diagnosticos = tuple(
                self._scanner.inspecionar_texto(
                    texto_para_scanner,
                    arquivo="<ARQUIVO>",
                )
            )
            if diagnosticos:
                raise ValueError("scanner final rejeitou a visão.")
        except Exception:
            raise ErroDeSanitizacao() from None

    verificar = validar


class _ConstrutorDeVisao:
    """Estado transitório de uma única construção; nunca escapa da API."""

    def __init__(
        self,
        snapshot: _SnapshotResultado,
        contexto: SanitizationContext,
    ) -> None:
        self._snapshot = snapshot
        self._contexto = contexto
        self._preparado = False

        self._metadados: dict[tuple[str, str], str] = {}
        self._mapa_arquivos: dict[str, str] = {}
        self._indices_arquivo_usados: set[int] = set()
        self._proximo_indice_arquivo = 1
        self._tokens_entradas: dict[int, str | None] = {}
        self._referencias_erros: dict[int, str] = {}

        self._placeholders_identificadores: dict[int, str] = {}
        self._proveniencias: dict[int, Proveniencia] = {}
        self._campos: dict[int, CampoEstruturado] = {}
        self._identificadores: dict[int, IdentificadorTecnico] = {}
        self._vinculos: dict[int, VinculoIdentificadores] = {}
        self._regras: dict[int, ReferenciaRegra] = {}

        self._entradas_preparadas: set[int] = set()
        self._falhas_preparadas: set[int] = set()
        self._evidencias_preparadas: set[int] = set()

        self._entradas_copiadas: dict[int, EntradaDeLog] = {}
        self._falhas_copiadas: dict[int, FalhaDeEntrada] = {}
        self._evidencias_copiadas: dict[int, Evidencia] = {}

        self._identificador_seguro: str | None = None

    def preparar_estruturas(self) -> None:
        """Registra toda estrutura sensível antes do primeiro texto livre."""

        self._reservar_indices_de_arquivo()

        self._identificador_seguro = self._contexto.placeholder_para(
            TipoDadoSensivel.CALL_ID,
            self._snapshot.identificador,
        )

        identificadores = tuple(self._iterar_identificadores())
        for identificador in identificadores:
            self._registrar_identificador(identificador)

        campos = tuple(self._iterar_campos())
        for campo in campos:
            self._registrar_campo(campo)

        # Valores semanticamente tipados recebem seus placeholders antes das
        # referências opacas de arquivo. Estas precisam ser conhecidas para a
        # substituição textual, mas não podem antecipar a numeração de
        # DADO_CLIENTE destinada aos campos estruturados.
        self._preparar_referencias_de_arquivo()

        for entrada in self._iterar_entradas():
            self._preparar_entrada(entrada)
        for identificador in identificadores:
            self._preparar_identificador(identificador)
        for campo in campos:
            self._preparar_campo(campo)

        for vinculo in self._snapshot.vinculos:
            self._preparar_vinculo(vinculo)
        if self._snapshot.correlacao is not None:
            for vinculo in self._snapshot.correlacao.vinculos_percorridos:
                self._preparar_vinculo(vinculo)
            for evidencia in self._snapshot.correlacao.evidencias:
                self._preparar_evidencia(evidencia)
        for evidencia in self._snapshot.evidencias:
            self._preparar_evidencia(evidencia)

        self._preparar_regra(self._snapshot.regra_aplicada)
        self._preparar_regra(self._snapshot.causa_raiz.regra)
        self._preparar_resultado_superficial()
        self._preparado = True

    def montar_resultado_interno(self) -> ResultadoDeAnalise:
        """Monta uma cópia sanitizada ainda não autorizada para saída."""

        if not self._preparado or self._identificador_seguro is None:
            raise RuntimeError("estruturas não foram preparadas.")

        entradas_por_aplicacao: dict[str, list[EntradaDeLog]] = {}
        for aplicacao, entradas in self._snapshot.entradas_por_aplicacao:
            aplicacao_segura = self._obter_metadado("aplicacao", aplicacao)
            if aplicacao_segura in entradas_por_aplicacao:
                raise ValueError("aplicações colidiram após sanitização.")
            entradas_por_aplicacao[aplicacao_segura] = [
                self._copiar_entrada(entrada) for entrada in entradas
            ]

        contagem_por_categoria: dict[Categoria, int] = {}
        for categoria, quantidade in self._snapshot.contagem_por_categoria:
            if not isinstance(categoria, Categoria):
                raise TypeError("categoria de contagem inválida.")
            if categoria in contagem_por_categoria:
                raise ValueError("categoria duplicada na contagem.")
            contagem_por_categoria[categoria] = quantidade

        contagem_por_aplicacao: dict[str, int] = {}
        for aplicacao, quantidade in self._snapshot.contagem_por_aplicacao:
            aplicacao_segura = self._obter_metadado("aplicacao", aplicacao)
            if aplicacao_segura in contagem_por_aplicacao:
                raise ValueError("aplicações colidiram após sanitização.")
            contagem_por_aplicacao[aplicacao_segura] = quantidade

        correlacao = self._copiar_correlacao(self._snapshot.correlacao)
        causa_raiz = ResultadoCausaRaiz(
            estado=self._snapshot.causa_raiz.estado,
            descricao_sanitizada=self._sanitizar_texto(
                self._snapshot.causa_raiz.descricao_sanitizada
            ),
            regra=self._copiar_regra(self._snapshot.causa_raiz.regra),
        )

        return ResultadoDeAnalise(
            identificador=self._identificador_seguro,
            entradas_por_aplicacao=entradas_por_aplicacao,
            linha_do_tempo=[
                self._copiar_entrada(entrada)
                for entrada in self._snapshot.linha_do_tempo
            ],
            contagem_por_categoria=contagem_por_categoria,
            contagem_por_aplicacao=contagem_por_aplicacao,
            correlacao_encontrada=self._snapshot.correlacao_encontrada,
            erros=[
                MensagemDeErro(
                    arquivo_ou_app=self._referencias_erros[indice],
                    descricao=self._sanitizar_texto(erro.descricao),
                )
                for indice, erro in enumerate(self._snapshot.erros)
            ],
            mensagens=[
                self._sanitizar_texto(mensagem)
                for mensagem in self._snapshot.mensagens
            ],
            categoria_de_cenario=self._snapshot.categoria_de_cenario,
            entradas_sem_ordenacao_temporal=[
                self._copiar_entrada(entrada)
                for entrada in self._snapshot.entradas_sem_ordenacao_temporal
            ],
            identificadores_extraidos=[
                self._identificadores[id(identificador)]
                for identificador in self._snapshot.identificadores_extraidos
            ],
            vinculos=[
                self._vinculos[id(vinculo)] for vinculo in self._snapshot.vinculos
            ],
            correlacao=correlacao,
            evidencias=[
                self._copiar_evidencia(evidencia)
                for evidencia in self._snapshot.evidencias
            ],
            regra_aplicada=self._copiar_regra(
                self._snapshot.regra_aplicada
            ),
            versao_catalogo=self._obter_metadado(
                "catalogo_versao",
                self._snapshot.versao_catalogo,
            ),
            estado_sanitizacao=EstadoSanitizacao.INTERNA_BRUTA,
            causa_raiz=causa_raiz,
            aplicacoes_analisadas=[
                self._obter_metadado("aplicacao", aplicacao)
                for aplicacao in self._snapshot.aplicacoes_analisadas
            ],
            aplicacoes_ausentes_ou_invalidas=[
                self._obter_metadado("aplicacao", aplicacao)
                for aplicacao in self._snapshot.aplicacoes_ausentes_ou_invalidas
            ],
            cobertura_rotulada=self._obter_metadado(
                "cobertura_rotulada",
                self._snapshot.cobertura_rotulada,
            ),
        )

    def limpar(self) -> None:
        """Descarta caches, inclusive todas as chaves que continham texto bruto."""

        self._metadados.clear()
        self._mapa_arquivos.clear()
        self._indices_arquivo_usados.clear()
        self._tokens_entradas.clear()
        self._referencias_erros.clear()
        self._placeholders_identificadores.clear()
        self._proveniencias.clear()
        self._campos.clear()
        self._identificadores.clear()
        self._vinculos.clear()
        self._regras.clear()
        self._entradas_preparadas.clear()
        self._falhas_preparadas.clear()
        self._evidencias_preparadas.clear()
        self._entradas_copiadas.clear()
        self._falhas_copiadas.clear()
        self._evidencias_copiadas.clear()
        self._identificador_seguro = None
        self._preparado = False

    def _iterar_entradas(self) -> Iterator[EntradaDeLog]:
        vistas: set[int] = set()
        colecoes: list[Iterable[EntradaDeLog]] = [
            *(entradas for _, entradas in self._snapshot.entradas_por_aplicacao),
            self._snapshot.linha_do_tempo,
            self._snapshot.entradas_sem_ordenacao_temporal,
        ]
        for colecao in colecoes:
            for entrada in colecao:
                if not isinstance(entrada, EntradaDeLog):
                    raise TypeError("coleção de entradas inválida.")
                chave = id(entrada)
                if chave not in vistas:
                    vistas.add(chave)
                    yield entrada

    def _iterar_identificadores(self) -> Iterator[IdentificadorTecnico]:
        vistos: set[int] = set()

        def emitir(valor: object) -> Iterator[IdentificadorTecnico]:
            if not isinstance(valor, IdentificadorTecnico):
                raise TypeError("identificador técnico inválido.")
            chave = id(valor)
            if chave not in vistos:
                vistos.add(chave)
                yield valor

        for entrada in self._iterar_entradas():
            for identificador in entrada.identificadores:
                yield from emitir(identificador)
        for identificador in self._snapshot.identificadores_extraidos:
            yield from emitir(identificador)
        for vinculo in self._iterar_todos_vinculos():
            yield from emitir(vinculo.origem)
            yield from emitir(vinculo.destino)

    def _iterar_campos(self) -> Iterator[CampoEstruturado]:
        vistos: set[int] = set()
        for entrada in self._iterar_entradas():
            for campo in entrada.campos_estruturados:
                if not isinstance(campo, CampoEstruturado):
                    raise TypeError("campo estruturado inválido.")
                chave = id(campo)
                if chave not in vistos:
                    vistos.add(chave)
                    yield campo

    def _iterar_todos_vinculos(self) -> Iterator[VinculoIdentificadores]:
        for vinculo in self._snapshot.vinculos:
            if not isinstance(vinculo, VinculoIdentificadores):
                raise TypeError("vínculo inválido.")
            yield vinculo
        if self._snapshot.correlacao is not None:
            if not isinstance(self._snapshot.correlacao, ResultadoCorrelacao):
                raise TypeError("resultado de correlação inválido.")
            for vinculo in self._snapshot.correlacao.vinculos_percorridos:
                if not isinstance(vinculo, VinculoIdentificadores):
                    raise TypeError("vínculo de correlação inválido.")
                yield vinculo

    def _iterar_proveniencias(self) -> Iterator[Proveniencia]:
        for entrada in self._iterar_entradas():
            for campo in entrada.campos_estruturados:
                yield campo.proveniencia
            for identificador in entrada.identificadores:
                yield identificador.proveniencia
            for falha in entrada.falhas:
                if not isinstance(falha, FalhaDeEntrada):
                    raise TypeError("falha de entrada inválida.")
                yield falha.proveniencia
        for identificador in self._snapshot.identificadores_extraidos:
            yield identificador.proveniencia
        for vinculo in self._iterar_todos_vinculos():
            yield vinculo.origem.proveniencia
            yield vinculo.destino.proveniencia
            yield vinculo.evidencia
        for evidencia in self._snapshot.evidencias:
            if not isinstance(evidencia, Evidencia):
                raise TypeError("evidência inválida.")
            yield evidencia.proveniencia
        if self._snapshot.correlacao is not None:
            for evidencia in self._snapshot.correlacao.evidencias:
                if not isinstance(evidencia, Evidencia):
                    raise TypeError("evidência de correlação inválida.")
                yield evidencia.proveniencia

    def _reservar_indices_de_arquivo(self) -> None:
        valores: list[str] = []
        for entrada in self._iterar_entradas():
            if entrada.arquivo_token is not None:
                valores.append(entrada.arquivo_token)
        valores.extend(
            proveniencia.arquivo_token
            for proveniencia in self._iterar_proveniencias()
        )
        for valor in valores:
            if not isinstance(valor, str):
                raise TypeError("token de arquivo inválido.")
            correspondencia = _PADRAO_TOKEN_ARQUIVO.fullmatch(valor)
            if correspondencia is not None:
                self._indices_arquivo_usados.add(int(correspondencia.group(1)))

    def _preparar_referencias_de_arquivo(self) -> None:
        aplicacoes_conhecidas: set[str] = set()
        for aplicacao, _ in self._snapshot.entradas_por_aplicacao:
            aplicacoes_conhecidas.add(aplicacao)
        for entrada in self._iterar_entradas():
            aplicacoes_conhecidas.add(entrada.aplicacao)
            token = self._associar_arquivo_da_entrada(entrada)
            self._tokens_entradas[id(entrada)] = token
        for aplicacao, _ in self._snapshot.contagem_por_aplicacao:
            aplicacoes_conhecidas.add(aplicacao)
        aplicacoes_conhecidas.update(self._snapshot.aplicacoes_analisadas)
        aplicacoes_conhecidas.update(
            self._snapshot.aplicacoes_ausentes_ou_invalidas
        )

        for proveniencia in self._iterar_proveniencias():
            self._token_para_referencia(proveniencia.arquivo_token)

        for indice, erro in enumerate(self._snapshot.erros):
            referencia = erro.arquivo_ou_app
            if (
                referencia in aplicacoes_conhecidas
                or _PADRAO_APP_ID_SEGURO.fullmatch(referencia) is not None
            ):
                segura = self._preparar_metadado("aplicacao", referencia)
            else:
                segura = self._token_para_referencia(referencia)
            self._referencias_erros[indice] = segura

    def _associar_arquivo_da_entrada(
        self,
        entrada: EntradaDeLog,
    ) -> str | None:
        token_bruto = entrada.arquivo_token
        origem_bruta = entrada.arquivo_origem
        if token_bruto is None and origem_bruta is None:
            return None

        if token_bruto is not None:
            token_seguro = self._token_para_referencia(token_bruto)
        else:
            token_seguro = self._novo_token_arquivo()

        if origem_bruta is not None:
            # O mesmo caminho físico pode aparecer em mais de um slot do lote
            # com tokens distintos (ex.: mesmo arquivo VPL enviado duas vezes).
            # Registra-se apenas a primeira associação; tokens subsequentes do
            # mesmo caminho são legítimos e já resolvidos por arquivo_token.
            existente = self._mapa_arquivos.get(origem_bruta)
            if existente is None:
                self._vincular_referencia_arquivo(origem_bruta, token_seguro)
            self._registrar_referencia_bruta(origem_bruta)
        return token_seguro

    def _token_para_referencia(self, valor: str) -> str:
        if not isinstance(valor, str) or not valor:
            raise ValueError("referência de arquivo inválida.")
        existente = self._mapa_arquivos.get(valor)
        if existente is not None:
            return existente

        correspondencia = _PADRAO_TOKEN_ARQUIVO.fullmatch(valor)
        if correspondencia is not None:
            token = valor
            self._indices_arquivo_usados.add(int(correspondencia.group(1)))
        else:
            token = self._novo_token_arquivo()
            self._registrar_referencia_bruta(valor)
        self._vincular_referencia_arquivo(valor, token)
        return token

    def _novo_token_arquivo(self) -> str:
        while self._proximo_indice_arquivo in self._indices_arquivo_usados:
            self._proximo_indice_arquivo += 1
        indice = self._proximo_indice_arquivo
        self._indices_arquivo_usados.add(indice)
        self._proximo_indice_arquivo += 1
        return f"<ARQUIVO_{indice}>"

    def _vincular_referencia_arquivo(self, bruto: str, seguro: str) -> None:
        anterior = self._mapa_arquivos.get(bruto)
        if anterior is not None and anterior != seguro:
            raise ValueError("referência de arquivo inconsistente.")
        self._mapa_arquivos[bruto] = seguro

    def _registrar_referencia_bruta(self, valor: str) -> None:
        if _PADRAO_TOKEN_ARQUIVO.fullmatch(valor) is not None:
            return
        self._contexto.placeholder_para(TipoDadoSensivel.DADO_CLIENTE, valor)

    def _registrar_identificador(
        self,
        identificador: IdentificadorTecnico,
    ) -> None:
        if not isinstance(identificador, IdentificadorTecnico):
            raise TypeError("identificador técnico inválido.")
        chave = id(identificador)
        if chave in self._placeholders_identificadores:
            return
        self._placeholders_identificadores[chave] = (
            self._contexto.placeholder_para(
                identificador.tipo,
                identificador.valor_original,
                valor_normalizado=identificador.valor_normalizado,
            )
        )

    def _registrar_campo(self, campo: CampoEstruturado) -> None:
        if not isinstance(campo, CampoEstruturado):
            raise TypeError("campo estruturado inválido.")
        chave = id(campo)
        if chave in self._campos:
            return
        campo_sanitizado = self._contexto.sanitizar_valor_estruturado(
            campo.nome,
            campo.valor_original,
        )
        nome = self._preparar_metadado("nome_campo", campo.nome)
        # A proveniência será copiada depois que todos os valores estruturados
        # tiverem sido registrados no contexto.
        self._campos[chave] = CampoEstruturado(
            nome=nome,
            valor_original=campo_sanitizado.valor,
            proveniencia=self._preparar_proveniencia(campo.proveniencia),
        )

    def _preparar_resultado_superficial(self) -> None:
        for aplicacao, _ in self._snapshot.entradas_por_aplicacao:
            self._preparar_metadado("aplicacao", aplicacao)
        for aplicacao, _ in self._snapshot.contagem_por_aplicacao:
            self._preparar_metadado("aplicacao", aplicacao)
        for aplicacao in self._snapshot.aplicacoes_analisadas:
            self._preparar_metadado("aplicacao", aplicacao)
        for aplicacao in self._snapshot.aplicacoes_ausentes_ou_invalidas:
            self._preparar_metadado("aplicacao", aplicacao)
        self._preparar_metadado(
            "catalogo_versao", self._snapshot.versao_catalogo
        )
        self._preparar_metadado(
            "cobertura_rotulada", self._snapshot.cobertura_rotulada
        )

    def _preparar_entrada(self, entrada: EntradaDeLog) -> None:
        if not isinstance(entrada, EntradaDeLog):
            raise TypeError("entrada inválida.")
        chave = id(entrada)
        if chave in self._entradas_preparadas:
            return
        self._entradas_preparadas.add(chave)

        self._preparar_metadado("aplicacao", entrada.aplicacao)
        self._preparar_metadado_opcional("entrada_id", entrada.entrada_id)
        self._preparar_metadado_opcional(
            "nivel_de_severidade", entrada.nivel_de_severidade
        )
        self._preparar_metadado_opcional(
            "timestamp_original", entrada.timestamp_original
        )
        self._preparar_metadado_opcional(
            "origem_evento", entrada.origem_evento
        )
        self._preparar_metadado_opcional(
            "formato_origem", entrada.formato_origem
        )

        for campo in entrada.campos_estruturados:
            self._preparar_campo(campo)
        for identificador in entrada.identificadores:
            self._preparar_identificador(identificador)
        for falha in entrada.falhas:
            self._preparar_falha(falha)

    def _preparar_proveniencia(
        self,
        proveniencia: Proveniencia,
    ) -> Proveniencia:
        if not isinstance(proveniencia, Proveniencia):
            raise TypeError("proveniência inválida.")
        chave = id(proveniencia)
        existente = self._proveniencias.get(chave)
        if existente is not None:
            return existente

        segura = Proveniencia(
            arquivo_token=self._token_para_referencia(
                proveniencia.arquivo_token
            ),
            entrada_id=self._preparar_metadado(
                "entrada_id", proveniencia.entrada_id
            ),
            linha_inicial=proveniencia.linha_inicial,
            linha_final=proveniencia.linha_final,
            span_inicial=proveniencia.span_inicial,
            span_final=proveniencia.span_final,
            nome_campo=self._preparar_metadado_opcional(
                "nome_campo", proveniencia.nome_campo
            ),
            regra_extracao=self._preparar_metadado_opcional(
                "regra_extracao", proveniencia.regra_extracao
            ),
        )
        self._proveniencias[chave] = segura
        return segura

    def _preparar_campo(self, campo: CampoEstruturado) -> CampoEstruturado:
        if not isinstance(campo, CampoEstruturado):
            raise TypeError("campo estruturado inválido.")
        chave = id(campo)
        existente = self._campos.get(chave)
        if existente is None:
            self._registrar_campo(campo)
            existente = self._campos[chave]
        return existente

    def _preparar_identificador(
        self,
        identificador: IdentificadorTecnico,
    ) -> IdentificadorTecnico:
        if not isinstance(identificador, IdentificadorTecnico):
            raise TypeError("identificador técnico inválido.")
        chave = id(identificador)
        existente = self._identificadores.get(chave)
        if existente is not None:
            return existente
        placeholder = self._placeholders_identificadores.get(chave)
        if placeholder is None:
            raise RuntimeError("identificador não foi registrado.")

        seguro = IdentificadorTecnico(
            tipo=identificador.tipo,
            namespace_comparacao=self._preparar_metadado(
                "namespace_comparacao",
                identificador.namespace_comparacao,
            ),
            nome_campo=self._preparar_metadado(
                "nome_campo", identificador.nome_campo
            ),
            valor_original=placeholder,
            valor_normalizado=placeholder,
            proveniencia=self._preparar_proveniencia(
                identificador.proveniencia
            ),
        )
        self._identificadores[chave] = seguro
        return seguro

    def _preparar_falha(self, falha: FalhaDeEntrada) -> None:
        if not isinstance(falha, FalhaDeEntrada):
            raise TypeError("falha de entrada inválida.")
        chave = id(falha)
        if chave in self._falhas_preparadas:
            return
        self._preparar_metadado("codigo_falha", falha.codigo)
        self._preparar_proveniencia(falha.proveniencia)
        self._falhas_preparadas.add(chave)

    def _preparar_vinculo(
        self,
        vinculo: VinculoIdentificadores,
    ) -> VinculoIdentificadores:
        if not isinstance(vinculo, VinculoIdentificadores):
            raise TypeError("vínculo inválido.")
        chave = id(vinculo)
        existente = self._vinculos.get(chave)
        if existente is not None:
            return existente
        seguro = VinculoIdentificadores(
            origem=self._preparar_identificador(vinculo.origem),
            destino=self._preparar_identificador(vinculo.destino),
            tipo_relacao=self._preparar_metadado(
                "tipo_relacao", vinculo.tipo_relacao
            ),
            evidencia=self._preparar_proveniencia(vinculo.evidencia),
            esquema_id=self._preparar_metadado(
                "esquema_id", vinculo.esquema_id
            ),
            esquema_versao=vinculo.esquema_versao,
            permite_correlacao=vinculo.permite_correlacao,
            ambiguo=vinculo.ambiguo,
        )
        self._vinculos[chave] = seguro
        return seguro

    def _preparar_evidencia(self, evidencia: Evidencia) -> None:
        if not isinstance(evidencia, Evidencia):
            raise TypeError("evidência inválida.")
        chave = id(evidencia)
        if chave in self._evidencias_preparadas:
            return
        self._preparar_metadado("tipo_evidencia", evidencia.tipo)
        self._preparar_metadado("aplicacao", evidencia.aplicacao)
        self._preparar_metadado(
            "campo_ou_condicao", evidencia.campo_ou_condicao
        )
        self._preparar_metadado_opcional(
            "timestamp_original", evidencia.timestamp_original
        )
        self._preparar_proveniencia(evidencia.proveniencia)
        self._evidencias_preparadas.add(chave)

    def _preparar_regra(
        self,
        regra: ReferenciaRegra | None,
    ) -> ReferenciaRegra | None:
        if regra is None:
            return None
        if not isinstance(regra, ReferenciaRegra):
            raise TypeError("referência de regra inválida.")
        chave = id(regra)
        existente = self._regras.get(chave)
        if existente is not None:
            return existente
        segura = ReferenciaRegra(
            rule_id=self._preparar_metadado("rule_id", regra.rule_id),
            versao=regra.versao,
            catalogo_versao=self._preparar_metadado(
                "catalogo_versao", regra.catalogo_versao
            ),
        )
        self._regras[chave] = segura
        return segura

    def _preparar_metadado(self, papel: str, valor: str) -> str:
        if not isinstance(valor, str) or not valor:
            raise ValueError("metadado textual inválido.")
        chave = (papel, valor)
        existente = self._metadados.get(chave)
        if existente is not None:
            return existente
        sanitizado = self._contexto.sanitizar_valor_estruturado(
            "metadado_estrutural",
            valor,
        ).valor
        self._metadados[chave] = sanitizado
        return sanitizado

    def _preparar_metadado_opcional(
        self,
        papel: str,
        valor: str | None,
    ) -> str | None:
        if valor is None:
            return None
        return self._preparar_metadado(papel, valor)

    def _obter_metadado(self, papel: str, valor: str) -> str:
        try:
            return self._metadados[(papel, valor)]
        except KeyError:
            raise RuntimeError("metadado não foi preparado.") from None

    def _obter_metadado_opcional(
        self,
        papel: str,
        valor: str | None,
    ) -> str | None:
        if valor is None:
            return None
        return self._obter_metadado(papel, valor)

    def _sanitizar_texto(self, texto: str) -> str:
        if not isinstance(texto, str):
            raise TypeError("texto livre inválido.")
        return self._contexto.sanitizar_texto(texto)

    def _copiar_entrada(self, entrada: EntradaDeLog) -> EntradaDeLog:
        chave = id(entrada)
        existente = self._entradas_copiadas.get(chave)
        if existente is not None:
            return existente
        if chave not in self._entradas_preparadas:
            raise RuntimeError("entrada não foi preparada.")

        texto_original = self._sanitizar_texto(entrada.texto_original)
        if entrada.representacao_sanitizada is not None:
            representacao = self._sanitizar_texto(
                entrada.representacao_sanitizada
            )
        elif _entrada_tem_metadados_fase2(entrada):
            representacao = texto_original
        else:
            # Entradas puramente legadas continuam válidas sem exigir um campo
            # aditivo; seu próprio texto_original já é a cópia sanitizada.
            representacao = None

        segura = EntradaDeLog(
            texto_original=texto_original,
            aplicacao=self._obter_metadado("aplicacao", entrada.aplicacao),
            ordem_de_leitura=entrada.ordem_de_leitura,
            interpretada=entrada.interpretada,
            carimbo_de_tempo=entrada.carimbo_de_tempo,
            nivel_de_severidade=self._obter_metadado_opcional(
                "nivel_de_severidade", entrada.nivel_de_severidade
            ),
            mensagem=(
                None
                if entrada.mensagem is None
                else self._sanitizar_texto(entrada.mensagem)
            ),
            categoria=entrada.categoria,
            correlacionada=entrada.correlacionada,
            entrada_id=self._obter_metadado_opcional(
                "entrada_id", entrada.entrada_id
            ),
            arquivo_origem=None,
            arquivo_token=self._tokens_entradas.get(chave),
            posicao_inicial=entrada.posicao_inicial,
            posicao_final=entrada.posicao_final,
            timestamp_original=self._obter_metadado_opcional(
                "timestamp_original", entrada.timestamp_original
            ),
            timestamp_normalizado=entrada.timestamp_normalizado,
            precisao_fracionaria=entrada.precisao_fracionaria,
            origem_evento=self._obter_metadado_opcional(
                "origem_evento", entrada.origem_evento
            ),
            formato_origem=self._obter_metadado_opcional(
                "formato_origem", entrada.formato_origem
            ),
            campos_estruturados=tuple(
                self._campos[id(campo)] for campo in entrada.campos_estruturados
            ),
            identificadores=tuple(
                self._identificadores[id(identificador)]
                for identificador in entrada.identificadores
            ),
            falhas=tuple(self._copiar_falha(falha) for falha in entrada.falhas),
            representacao_sanitizada=representacao,
        )
        self._entradas_copiadas[chave] = segura
        return segura

    def _copiar_falha(self, falha: FalhaDeEntrada) -> FalhaDeEntrada:
        chave = id(falha)
        existente = self._falhas_copiadas.get(chave)
        if existente is not None:
            return existente
        if chave not in self._falhas_preparadas:
            raise RuntimeError("falha não foi preparada.")
        segura = FalhaDeEntrada(
            codigo=self._obter_metadado("codigo_falha", falha.codigo),
            proveniencia=self._proveniencias[id(falha.proveniencia)],
            detalhe_seguro=self._sanitizar_texto(falha.detalhe_seguro),
        )
        self._falhas_copiadas[chave] = segura
        return segura

    def _copiar_evidencia(self, evidencia: Evidencia) -> Evidencia:
        chave = id(evidencia)
        existente = self._evidencias_copiadas.get(chave)
        if existente is not None:
            return existente
        if chave not in self._evidencias_preparadas:
            raise RuntimeError("evidência não foi preparada.")
        segura = Evidencia(
            tipo=self._obter_metadado("tipo_evidencia", evidencia.tipo),
            aplicacao=self._obter_metadado(
                "aplicacao", evidencia.aplicacao
            ),
            proveniencia=self._proveniencias[id(evidencia.proveniencia)],
            timestamp_original=self._obter_metadado_opcional(
                "timestamp_original", evidencia.timestamp_original
            ),
            timestamp_normalizado=evidencia.timestamp_normalizado,
            campo_ou_condicao=self._obter_metadado(
                "campo_ou_condicao", evidencia.campo_ou_condicao
            ),
            representacao_sanitizada=self._sanitizar_texto(
                evidencia.representacao_sanitizada
            ),
        )
        self._evidencias_copiadas[chave] = segura
        return segura

    def _copiar_regra(
        self,
        regra: ReferenciaRegra | None,
    ) -> ReferenciaRegra | None:
        if regra is None:
            return None
        try:
            return self._regras[id(regra)]
        except KeyError:
            raise RuntimeError("regra não foi preparada.") from None

    def _copiar_correlacao(
        self,
        correlacao: ResultadoCorrelacao | None,
    ) -> ResultadoCorrelacao | None:
        if correlacao is None:
            return None
        if not isinstance(correlacao, ResultadoCorrelacao):
            raise TypeError("resultado de correlação inválido.")
        return ResultadoCorrelacao(
            encontrada=correlacao.encontrada,
            base_primaria=correlacao.base_primaria,
            bases=tuple(correlacao.bases),
            evidencias=tuple(
                self._copiar_evidencia(evidencia)
                for evidencia in correlacao.evidencias
            ),
            vinculos_percorridos=tuple(
                self._vinculos[id(vinculo)]
                for vinculo in correlacao.vinculos_percorridos
            ),
            motivo_seguro=(
                None
                if correlacao.motivo_seguro is None
                else self._sanitizar_texto(correlacao.motivo_seguro)
            ),
        )


def _entrada_tem_metadados_fase2(entrada: EntradaDeLog) -> bool:
    return any(
        (
            entrada.entrada_id is not None,
            entrada.arquivo_origem is not None,
            entrada.arquivo_token is not None,
            entrada.posicao_inicial is not None,
            entrada.posicao_final is not None,
            entrada.timestamp_original is not None,
            entrada.timestamp_normalizado is not None,
            entrada.precisao_fracionaria is not None,
            entrada.origem_evento is not None,
            entrada.formato_origem is not None,
            bool(entrada.campos_estruturados),
            bool(entrada.identificadores),
            bool(entrada.falhas),
            entrada.representacao_sanitizada is not None,
        )
    )


class SanitizadorDeResultado:
    """Produz uma visão segura sem alterar o ``ResultadoDeAnalise`` interno."""

    __slots__ = ("_fabrica_contexto", "_scanner_final")

    def __init__(
        self,
        *,
        fabrica_contexto: Callable[[], SanitizationContext] = SanitizationContext,
        scanner_final: ScannerFinalDeResultado | None = None,
    ) -> None:
        self._fabrica_contexto = fabrica_contexto
        self._scanner_final = (
            ScannerFinalDeResultado() if scanner_final is None else scanner_final
        )

    def criar_visao_segura(
        self,
        resultado: ResultadoDeAnalise,
    ) -> ResultadoDeAnalise:
        """Retorna somente a visão concluída ou sinaliza falha constante.

        Nenhuma exceção capturada é encadeada, interpolada ou reaproveitada. O
        descarte do contexto ocorre em ``finally`` e uma falha de descarte
        também invalida integralmente a visão.
        """

        contexto: SanitizationContext | None = None
        construtor: _ConstrutorDeVisao | None = None
        visao_concluida: ResultadoDeAnalise | None = None
        falhou = False

        try:
            snapshot = _capturar_snapshot(resultado)
            contexto = self._fabrica_contexto()
            construtor = _ConstrutorDeVisao(snapshot, contexto)
            construtor.preparar_estruturas()
            visao_interna = construtor.montar_resultado_interno()
            self._scanner_final.validar(visao_interna)
            # A única mutação lógica após o scanner é a troca por um enum
            # constante. ``replace`` cria outro objeto e reexecuta invariantes.
            visao_concluida = replace(
                visao_interna,
                estado_sanitizacao=EstadoSanitizacao.CONCLUIDA,
            )
        except Exception:
            falhou = True
        finally:
            if construtor is not None:
                try:
                    construtor.limpar()
                except Exception:
                    falhou = True
            if contexto is not None:
                try:
                    contexto.descartar_mapa_bruto()
                except Exception:
                    falhou = True

        if falhou or visao_concluida is None:
            raise ErroDeSanitizacao() from None
        return visao_concluida

    sanitizar = criar_visao_segura
    produzir = criar_visao_segura


def criar_visao_segura(resultado: ResultadoDeAnalise) -> ResultadoDeAnalise:
    """Atalho fail-closed com dependências padrão."""

    return SanitizadorDeResultado().criar_visao_segura(resultado)


produzir_visao_segura = criar_visao_segura
sanitizar_resultado = criar_visao_segura


__all__ = [
    "CODIGO_FALHA_VISAO_SEGURA",
    "MENSAGEM_FALHA_VISAO_SEGURA",
    "SanitizadorDeResultado",
    "ScannerFinalDeResultado",
    "criar_visao_segura",
    "produzir_visao_segura",
    "sanitizar_resultado",
]
