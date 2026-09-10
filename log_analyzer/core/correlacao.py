"""Correlação evidenciada entre entradas VPL e ORK.

``CorrelacionadorVplOrk`` é o serviço da Fase 2. Ele usa exclusivamente dois
mecanismos de correlação: igualdade de identificadores normalizados no mesmo
namespace de comparação e caminhos explícitos, autorizados e não ambíguos do
grafo de vínculos. Texto livre, consulta literal, timestamps, ordem, mera
coexistência e similaridade não participam da decisão.

A função ``correlacionar_vpl_ork`` permanece como adapter da Fase 1. Seu
comportamento intencionalmente não é reutilizado pelo pipeline novo: as listas
recebidas pelo adapter legado já foram filtradas e, por compatibilidade, a
presença dos dois lados continua sendo suficiente apenas nesse fluxo.

Requirements: 1.4, 9.1, 9.2, 9.4, 9.5, 9.6, 9.7.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from enum import Enum

from log_analyzer.core.modelos import (
    BaseCorrelacao,
    EntradaDeLog,
    Evidencia,
    IdentificadorTecnico,
    MensagemDeErro,
    Proveniencia,
    ResultadoCorrelacao,
    TipoIdentificador,
    VinculoIdentificadores,
)
from log_analyzer.core.vinculos import CaminhoEvidenciado, GrafoDeVinculos


MOTIVO_VPL_AUSENTE = "Lado VPL ausente para correlação evidenciada."
MOTIVO_ORK_AUSENTE = "Lado ORK ausente para correlação evidenciada."
MOTIVO_AMBOS_LADOS_AUSENTES = (
    "Lados VPL e ORK ausentes para correlação evidenciada."
)
MOTIVO_SEM_EVIDENCIA = (
    "Nenhum valor compartilhado ou caminho explícito válido sustenta a correlação."
)
MOTIVO_AMBIGUIDADE = (
    "A associação disponível é ambígua e foi rejeitada de forma fail-closed."
)
MOTIVO_AMBIGUIDADE_ISOLADA = (
    "Associações ambíguas foram isoladas e não sustentaram a correlação."
)


class LacunaCorrelacao(Enum):
    """Lacunas estruturadas e seguras observadas durante a correlação."""

    VPL_AUSENTE = "vpl_ausente"
    ORK_AUSENTE = "ork_ausente"
    SEM_EVIDENCIA = "sem_evidencia"
    ASSOCIACAO_AMBIGUA = "associacao_ambigua"
    AMBIGUIDADE_ISOLADA = "ambiguidade_isolada"


@dataclass(frozen=True)
class ResultadoCorrelacaoVplOrk:
    """Entradas separadas e decisão estruturada produzidas pela Fase 2.

    As entradas são cópias imutáveis na mesma ordem recebida. Somente entradas
    cobertas por uma evidência válida recebem ``correlacionada=True``. Caminhos
    ambíguos são mantidos separadamente para auditoria interna e nunca aparecem
    em ``ResultadoCorrelacao.vinculos_percorridos``.
    """

    entradas_vpl: tuple[EntradaDeLog, ...] = field(repr=False)
    entradas_ork: tuple[EntradaDeLog, ...] = field(repr=False)
    correlacao: ResultadoCorrelacao
    caminhos_evidenciados: tuple[CaminhoEvidenciado, ...] = field(
        default=(), repr=False
    )
    caminhos_bloqueados_por_ambiguidade: tuple[
        CaminhoEvidenciado, ...
    ] = field(default=(), repr=False)
    lacunas: tuple[LacunaCorrelacao, ...] = ()
    entrada_ids_cobertas: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for nome, entradas in (
            ("entradas_vpl", self.entradas_vpl),
            ("entradas_ork", self.entradas_ork),
        ):
            if not isinstance(entradas, tuple) or not all(
                isinstance(entrada, EntradaDeLog) for entrada in entradas
            ):
                raise TypeError(f"{nome} deve ser uma tupla de EntradaDeLog.")
        if not isinstance(self.correlacao, ResultadoCorrelacao):
            raise TypeError("correlacao deve ser ResultadoCorrelacao.")
        for nome, caminhos in (
            ("caminhos_evidenciados", self.caminhos_evidenciados),
            (
                "caminhos_bloqueados_por_ambiguidade",
                self.caminhos_bloqueados_por_ambiguidade,
            ),
        ):
            if not isinstance(caminhos, tuple) or not all(
                isinstance(caminho, CaminhoEvidenciado)
                for caminho in caminhos
            ):
                raise TypeError(f"{nome} deve conter CaminhoEvidenciado.")
        if not isinstance(self.lacunas, tuple) or not all(
            isinstance(lacuna, LacunaCorrelacao) for lacuna in self.lacunas
        ):
            raise TypeError("lacunas deve ser uma tupla de LacunaCorrelacao.")
        if len(set(self.lacunas)) != len(self.lacunas):
            raise ValueError("lacunas não pode conter duplicatas.")
        if not isinstance(self.entrada_ids_cobertas, tuple) or not all(
            isinstance(entrada_id, str) and entrada_id.strip()
            for entrada_id in self.entrada_ids_cobertas
        ):
            raise TypeError(
                "entrada_ids_cobertas deve conter strings não vazias."
            )
        if len(set(self.entrada_ids_cobertas)) != len(
            self.entrada_ids_cobertas
        ):
            raise ValueError("entrada_ids_cobertas não pode conter duplicatas.")

        marcadas_vpl = tuple(
            entrada for entrada in self.entradas_vpl if entrada.correlacionada
        )
        marcadas_ork = tuple(
            entrada for entrada in self.entradas_ork if entrada.correlacionada
        )
        if self.correlacao.encontrada:
            if not marcadas_vpl or not marcadas_ork:
                raise ValueError(
                    "correlação encontrada requer entradas cobertas nos dois lados."
                )
        elif marcadas_vpl or marcadas_ork:
            raise ValueError(
                "correlação não encontrada não pode marcar entradas como correlacionadas."
            )

        if self.caminhos_evidenciados and (
            BaseCorrelacao.CADEIA_DE_VINCULOS
            not in self.correlacao.bases
        ):
            raise ValueError(
                "caminhos evidenciados requerem base CADEIA_DE_VINCULOS."
            )
        if (
            BaseCorrelacao.CADEIA_DE_VINCULOS in self.correlacao.bases
            and not self.caminhos_evidenciados
        ):
            raise ValueError(
                "base CADEIA_DE_VINCULOS requer caminhos evidenciados."
            )

    @property
    def resultado(self) -> ResultadoCorrelacao:
        """Alias para consumidores que nomeiam a decisão como resultado."""

        return self.correlacao

    @property
    def encontrada(self) -> bool:
        return self.correlacao.encontrada

    @property
    def correlacao_encontrada(self) -> bool:
        return self.correlacao.encontrada

    @property
    def base_primaria(self) -> BaseCorrelacao:
        return self.correlacao.base_primaria

    @property
    def bases(self) -> tuple[BaseCorrelacao, ...]:
        return self.correlacao.bases

    @property
    def evidencias(self) -> tuple[Evidencia, ...]:
        return self.correlacao.evidencias

    @property
    def vinculos_percorridos(self) -> tuple[VinculoIdentificadores, ...]:
        return self.correlacao.vinculos_percorridos

    @property
    def caminhos(self) -> tuple[CaminhoEvidenciado, ...]:
        return self.caminhos_evidenciados

    @property
    def aplicacoes_ausentes(self) -> tuple[str, ...]:
        ausentes: list[str] = []
        if LacunaCorrelacao.VPL_AUSENTE in self.lacunas:
            ausentes.append("VPL")
        if LacunaCorrelacao.ORK_AUSENTE in self.lacunas:
            ausentes.append("ORK")
        return tuple(ausentes)

    def __iter__(self):
        """Permite desempacotar ``VPL, ORK, ResultadoCorrelacao``.

        A forma principal continua sendo o objeto nomeado; o desempacotamento é
        apenas uma conveniência de migração e devolve listas independentes.
        """

        yield list(self.entradas_vpl)
        yield list(self.entradas_ork)
        yield self.correlacao


@dataclass(frozen=True)
class _OcorrenciaIdentificador:
    entrada: EntradaDeLog = field(repr=False)
    identificador: IdentificadorTecnico = field(repr=False)
    chave_entrada: tuple[str, str]

    @property
    def chave_comparacao(self) -> tuple[str, str]:
        return (
            self.identificador.namespace_comparacao,
            self.identificador.valor_normalizado,
        )

    @property
    def chave_no(self) -> tuple[TipoIdentificador, str, str]:
        return _chave_no(self.identificador)


class _EstadoCaminho(Enum):
    VALIDO = "valido"
    AMBIGUO = "ambiguo"
    INVALIDO = "invalido"


class CorrelacionadorVplOrk:
    """Correlaciona VPL e ORK somente por evidência estruturada aprovada.

    O grafo pode ser fornecido no construtor ou na chamada. Caminhos previamente
    calculados (por exemplo, pela busca) também podem ser passados, mas são
    revalidados: precisam ligar identificadores das duas coleções, possuir ao
    menos uma aresta, referenciar entradas fornecidas e usar somente vínculos
    ``permite_correlacao=True`` e ``ambiguo=False``.
    """

    def __init__(self, grafo: GrafoDeVinculos | None = None) -> None:
        if grafo is not None and not isinstance(grafo, GrafoDeVinculos):
            raise TypeError("grafo deve ser GrafoDeVinculos ou None.")
        self._grafo = grafo

    @property
    def grafo(self) -> GrafoDeVinculos | None:
        return self._grafo

    def correlacionar(
        self,
        entradas_vpl: Iterable[EntradaDeLog],
        entradas_ork: Iterable[EntradaDeLog],
        *,
        grafo: GrafoDeVinculos | None = None,
        caminhos_evidenciados: Iterable[CaminhoEvidenciado] = (),
    ) -> ResultadoCorrelacaoVplOrk:
        """Produz uma correlação nova sem recorrer a heurísticas implícitas.

        Identificadores sem proveniência completa e versionada não participam da
        decisão. Isso mantém o serviço fail-closed e separa explicitamente o
        fluxo novo do adapter legado.
        """

        vpl = _materializar_entradas(entradas_vpl, "VPL")
        ork = _materializar_entradas(entradas_ork, "ORK")
        grafo_final = self._resolver_grafo(grafo)
        caminhos_fornecidos = _materializar_caminhos(caminhos_evidenciados)

        ocorrencias_vpl = _extrair_ocorrencias_rastreaveis(vpl)
        ocorrencias_ork = _extrair_ocorrencias_rastreaveis(ork)
        entradas_por_chave = _indexar_entradas(vpl, ork)

        chaves_cobertas: set[tuple[str, str]] = set()
        evidencias: list[Evidencia] = []
        caminhos_validos: list[CaminhoEvidenciado] = []
        caminhos_ambiguos: list[CaminhoEvidenciado] = []
        vinculos_validos: list[VinculoIdentificadores] = []
        encontrou_valor_compartilhado = False
        encontrou_cadeia = False
        detectou_ambiguidade = False

        por_comparacao_vpl = _agrupar_por_comparacao(ocorrencias_vpl)
        por_comparacao_ork = _agrupar_por_comparacao(ocorrencias_ork)
        for chave in sorted(set(por_comparacao_vpl) & set(por_comparacao_ork)):
            candidatas_vpl = por_comparacao_vpl[chave]
            candidatas_ork = por_comparacao_ork[chave]
            validas_vpl = tuple(
                ocorrencia
                for ocorrencia in candidatas_vpl
                if not _identificador_ambiguo(
                    grafo_final, ocorrencia.identificador
                )
            )
            validas_ork = tuple(
                ocorrencia
                for ocorrencia in candidatas_ork
                if not _identificador_ambiguo(
                    grafo_final, ocorrencia.identificador
                )
            )
            if len(validas_vpl) != len(candidatas_vpl) or len(
                validas_ork
            ) != len(candidatas_ork):
                detectou_ambiguidade = True
            if not validas_vpl or not validas_ork:
                continue

            encontrou_valor_compartilhado = True
            for ocorrencia in (*validas_vpl, *validas_ork):
                chaves_cobertas.add(ocorrencia.chave_entrada)
                _adicionar_unico(
                    evidencias,
                    _evidencia_de_identificador(
                        ocorrencia,
                        tipo="identificador_compartilhado",
                        condicao=(
                            "valor_compartilhado:"
                            f"{ocorrencia.identificador.namespace_comparacao}"
                        ),
                    ),
                )

        candidatos_de_caminho: list[CaminhoEvidenciado] = list(
            caminhos_fornecidos
        )
        if grafo_final is not None and ocorrencias_vpl and ocorrencias_ork:
            novos, bloqueados = _descobrir_caminhos_no_grafo(
                grafo_final,
                ocorrencias_vpl,
                ocorrencias_ork,
            )
            for caminho in novos:
                _adicionar_unico(candidatos_de_caminho, caminho)
            for caminho in bloqueados:
                _adicionar_unico(caminhos_ambiguos, caminho)
            if bloqueados:
                detectou_ambiguidade = True

        nos_vpl = {ocorrencia.chave_no for ocorrencia in ocorrencias_vpl}
        nos_ork = {ocorrencia.chave_no for ocorrencia in ocorrencias_ork}
        arestas_do_grafo = (
            frozenset(grafo_final.arestas)
            if grafo_final is not None
            else None
        )
        for caminho in candidatos_de_caminho:
            estado = _validar_caminho(
                caminho,
                nos_vpl,
                nos_ork,
                entradas_por_chave,
                arestas_do_grafo,
            )
            if estado is _EstadoCaminho.AMBIGUO:
                detectou_ambiguidade = True
                _adicionar_unico(caminhos_ambiguos, caminho)
                continue
            if estado is not _EstadoCaminho.VALIDO:
                continue

            encontrou_cadeia = True
            _adicionar_unico(caminhos_validos, caminho)
            nos_do_caminho = _nos_do_caminho(caminho)
            for ocorrencia in (*ocorrencias_vpl, *ocorrencias_ork):
                if ocorrencia.chave_no in nos_do_caminho:
                    chaves_cobertas.add(ocorrencia.chave_entrada)
                    _adicionar_unico(
                        evidencias,
                        _evidencia_de_identificador(
                            ocorrencia,
                            tipo="identificador_de_cadeia",
                            condicao="extremo_ou_no_de_cadeia",
                        ),
                    )
            for vinculo in caminho.vinculos:
                entrada_evidencia = _entrada_da_proveniencia(
                    vinculo.evidencia, entradas_por_chave
                )
                if entrada_evidencia is None:
                    # A validação anterior torna este ramo defensivo.
                    continue
                chave_evidencia = _chave_entrada(entrada_evidencia)
                if chave_evidencia is not None:
                    chaves_cobertas.add(chave_evidencia)
                _adicionar_unico(vinculos_validos, vinculo)
                _adicionar_unico(
                    evidencias,
                    _evidencia_de_vinculo(entrada_evidencia, vinculo),
                )

        bases: list[BaseCorrelacao] = []
        if encontrou_valor_compartilhado:
            bases.append(BaseCorrelacao.VALOR_COMPARTILHADO)
        if encontrou_cadeia:
            bases.append(BaseCorrelacao.CADEIA_DE_VINCULOS)
        encontrada = bool(bases)

        vpl_atualizadas = _marcar_cobertura(vpl, chaves_cobertas if encontrada else set())
        ork_atualizadas = _marcar_cobertura(ork, chaves_cobertas if encontrada else set())
        lacunas = _compor_lacunas(
            vpl,
            ork,
            encontrada=encontrada,
            detectou_ambiguidade=detectou_ambiguidade,
        )

        if encontrada:
            motivo = (
                MOTIVO_AMBIGUIDADE_ISOLADA
                if detectou_ambiguidade
                else None
            )
            correlacao = ResultadoCorrelacao(
                encontrada=True,
                base_primaria=bases[0],
                bases=tuple(bases),
                evidencias=tuple(evidencias),
                vinculos_percorridos=tuple(vinculos_validos),
                motivo_seguro=motivo,
            )
        else:
            base = (
                BaseCorrelacao.AMBIGUA
                if detectou_ambiguidade
                else BaseCorrelacao.NENHUMA
            )
            correlacao = ResultadoCorrelacao(
                encontrada=False,
                base_primaria=base,
                bases=(base,),
                motivo_seguro=_motivo_sem_correlacao(
                    vpl,
                    ork,
                    detectou_ambiguidade=detectou_ambiguidade,
                ),
            )

        ids_cobertas: list[str] = []
        for entrada in (*vpl_atualizadas, *ork_atualizadas):
            if (
                entrada.correlacionada
                and entrada.entrada_id is not None
                and entrada.entrada_id not in ids_cobertas
            ):
                ids_cobertas.append(entrada.entrada_id)

        return ResultadoCorrelacaoVplOrk(
            entradas_vpl=vpl_atualizadas,
            entradas_ork=ork_atualizadas,
            correlacao=correlacao,
            caminhos_evidenciados=tuple(caminhos_validos),
            caminhos_bloqueados_por_ambiguidade=tuple(caminhos_ambiguos),
            lacunas=lacunas,
            entrada_ids_cobertas=tuple(ids_cobertas),
        )

    executar = correlacionar

    def _resolver_grafo(
        self, grafo: GrafoDeVinculos | None
    ) -> GrafoDeVinculos | None:
        if grafo is not None and not isinstance(grafo, GrafoDeVinculos):
            raise TypeError("grafo deve ser GrafoDeVinculos ou None.")
        if grafo is not None and self._grafo is not None and grafo is not self._grafo:
            raise ValueError(
                "informe o grafo no construtor ou na chamada, não ambos."
            )
        return grafo if grafo is not None else self._grafo


def _materializar_entradas(
    entradas: Iterable[EntradaDeLog], aplicacao_esperada: str
) -> tuple[EntradaDeLog, ...]:
    if isinstance(entradas, (str, bytes)):
        raise TypeError("entradas deve ser um iterável de EntradaDeLog.")
    try:
        materializadas = tuple(entradas)
    except TypeError:
        raise TypeError(
            "entradas deve ser um iterável de EntradaDeLog."
        ) from None
    if not all(isinstance(entrada, EntradaDeLog) for entrada in materializadas):
        raise TypeError("entradas deve conter somente EntradaDeLog.")
    if any(entrada.aplicacao != aplicacao_esperada for entrada in materializadas):
        raise ValueError(
            f"a coleção {aplicacao_esperada} contém entrada de outra aplicação."
        )
    return materializadas


def _materializar_caminhos(
    caminhos: Iterable[CaminhoEvidenciado],
) -> tuple[CaminhoEvidenciado, ...]:
    if isinstance(caminhos, (str, bytes)):
        raise TypeError("caminhos_evidenciados deve ser um iterável de caminhos.")
    try:
        materializados = tuple(caminhos)
    except TypeError:
        raise TypeError(
            "caminhos_evidenciados deve ser um iterável de caminhos."
        ) from None
    if not all(
        isinstance(caminho, CaminhoEvidenciado)
        for caminho in materializados
    ):
        raise TypeError(
            "caminhos_evidenciados deve conter CaminhoEvidenciado."
        )
    return materializados


def _chave_entrada(entrada: EntradaDeLog) -> tuple[str, str] | None:
    if entrada.arquivo_token is None or entrada.entrada_id is None:
        return None
    return (entrada.arquivo_token, entrada.entrada_id)


def _proveniencia_pertence_a_entrada(
    proveniencia: Proveniencia, entrada: EntradaDeLog
) -> bool:
    chave = _chave_entrada(entrada)
    return bool(
        chave is not None
        and chave == (proveniencia.arquivo_token, proveniencia.entrada_id)
        and entrada.posicao_inicial is not None
        and entrada.posicao_final is not None
        and entrada.posicao_inicial <= proveniencia.linha_inicial
        and proveniencia.linha_final <= entrada.posicao_final
    )


def _identificador_rastreavel(
    identificador: IdentificadorTecnico, entrada: EntradaDeLog
) -> bool:
    proveniencia = identificador.proveniencia
    return bool(
        _proveniencia_pertence_a_entrada(proveniencia, entrada)
        and proveniencia.nome_campo == identificador.nome_campo
        and proveniencia.regra_extracao is not None
        and proveniencia.regra_extracao.strip()
    )


def _extrair_ocorrencias_rastreaveis(
    entradas: tuple[EntradaDeLog, ...],
) -> tuple[_OcorrenciaIdentificador, ...]:
    ocorrencias: list[_OcorrenciaIdentificador] = []
    for entrada in entradas:
        chave = _chave_entrada(entrada)
        if chave is None:
            continue
        for identificador in entrada.identificadores:
            if _identificador_rastreavel(identificador, entrada):
                ocorrencias.append(
                    _OcorrenciaIdentificador(
                        entrada=entrada,
                        identificador=identificador,
                        chave_entrada=chave,
                    )
                )
    return tuple(ocorrencias)


def _agrupar_por_comparacao(
    ocorrencias: tuple[_OcorrenciaIdentificador, ...],
) -> dict[tuple[str, str], tuple[_OcorrenciaIdentificador, ...]]:
    mutavel: dict[tuple[str, str], list[_OcorrenciaIdentificador]] = {}
    for ocorrencia in ocorrencias:
        mutavel.setdefault(ocorrencia.chave_comparacao, []).append(ocorrencia)
    return {chave: tuple(valores) for chave, valores in mutavel.items()}


def _indexar_entradas(
    vpl: tuple[EntradaDeLog, ...],
    ork: tuple[EntradaDeLog, ...],
) -> dict[tuple[str, str], tuple[EntradaDeLog, ...]]:
    indice: dict[tuple[str, str], list[EntradaDeLog]] = {}
    for entrada in (*vpl, *ork):
        chave = _chave_entrada(entrada)
        if chave is not None:
            indice.setdefault(chave, []).append(entrada)
    return {chave: tuple(entradas) for chave, entradas in indice.items()}


def _chave_no(
    identificador: IdentificadorTecnico,
) -> tuple[TipoIdentificador, str, str]:
    return (
        identificador.tipo,
        identificador.namespace_comparacao,
        identificador.valor_normalizado,
    )


def _identificador_ambiguo(
    grafo: GrafoDeVinculos | None,
    identificador: IdentificadorTecnico,
) -> bool:
    return grafo is not None and grafo.eh_ambiguo(identificador)


def _descobrir_caminhos_no_grafo(
    grafo: GrafoDeVinculos,
    ocorrencias_vpl: tuple[_OcorrenciaIdentificador, ...],
    ocorrencias_ork: tuple[_OcorrenciaIdentificador, ...],
) -> tuple[tuple[CaminhoEvidenciado, ...], tuple[CaminhoEvidenciado, ...]]:
    validos: list[CaminhoEvidenciado] = []
    ambiguos: list[CaminhoEvidenciado] = []
    vpl_por_no = _primeira_ocorrencia_por_no(ocorrencias_vpl)
    ork_por_no = _primeira_ocorrencia_por_no(ocorrencias_ork)

    for chave_vpl in sorted(vpl_por_no, key=_ordem_chave_no):
        for chave_ork in sorted(ork_por_no, key=_ordem_chave_no):
            identificador_vpl = vpl_por_no[chave_vpl].identificador
            identificador_ork = ork_por_no[chave_ork].identificador
            caminho = grafo.encontrar_caminho(
                identificador_vpl,
                identificador_ork,
            )
            if caminho is not None and caminho.passos:
                _adicionar_unico(validos, caminho)
                continue
            diagnostico = grafo.encontrar_caminho(
                identificador_vpl,
                identificador_ork,
                incluir_componentes_ambiguos=True,
                somente_arestas_expansiveis=True,
            )
            if (
                diagnostico is not None
                and diagnostico.passos
                and any(vinculo.ambiguo for vinculo in diagnostico.vinculos)
            ):
                _adicionar_unico(ambiguos, diagnostico)
    return tuple(validos), tuple(ambiguos)


def _primeira_ocorrencia_por_no(
    ocorrencias: tuple[_OcorrenciaIdentificador, ...],
) -> dict[tuple[TipoIdentificador, str, str], _OcorrenciaIdentificador]:
    resultado: dict[
        tuple[TipoIdentificador, str, str], _OcorrenciaIdentificador
    ] = {}
    for ocorrencia in ocorrencias:
        resultado.setdefault(ocorrencia.chave_no, ocorrencia)
    return resultado


def _ordem_chave_no(
    chave: tuple[TipoIdentificador, str, str],
) -> tuple[str, str, str]:
    return (chave[0].value, chave[1], chave[2])


def _validar_caminho(
    caminho: CaminhoEvidenciado,
    nos_vpl: set[tuple[TipoIdentificador, str, str]],
    nos_ork: set[tuple[TipoIdentificador, str, str]],
    entradas_por_chave: dict[tuple[str, str], tuple[EntradaDeLog, ...]],
    arestas_do_grafo: frozenset[VinculoIdentificadores] | None,
) -> _EstadoCaminho:
    if not caminho.passos:
        return _EstadoCaminho.INVALIDO
    semente = _chave_no(caminho.semente)
    destino = _chave_no(caminho.destino)
    liga_lados = (semente in nos_vpl and destino in nos_ork) or (
        semente in nos_ork and destino in nos_vpl
    )
    if not liga_lados:
        return _EstadoCaminho.INVALIDO

    if any(vinculo.ambiguo for vinculo in caminho.vinculos):
        return _EstadoCaminho.AMBIGUO
    for vinculo in caminho.vinculos:
        if not vinculo.permite_correlacao:
            return _EstadoCaminho.INVALIDO
        if arestas_do_grafo is not None and vinculo not in arestas_do_grafo:
            return _EstadoCaminho.INVALIDO
        if not _vinculo_tem_declaracao_rastreavel(vinculo):
            return _EstadoCaminho.INVALIDO
        if (
            _entrada_da_proveniencia(
                vinculo.evidencia, entradas_por_chave
            )
            is None
        ):
            return _EstadoCaminho.INVALIDO
    return _EstadoCaminho.VALIDO


def _vinculo_tem_declaracao_rastreavel(
    vinculo: VinculoIdentificadores,
) -> bool:
    evidencia = vinculo.evidencia
    return bool(
        vinculo.esquema_id.strip()
        and vinculo.esquema_versao >= 1
        and vinculo.origem.proveniencia.arquivo_token
        == evidencia.arquivo_token
        and vinculo.origem.proveniencia.entrada_id == evidencia.entrada_id
        and vinculo.destino.proveniencia.arquivo_token
        == evidencia.arquivo_token
        and vinculo.destino.proveniencia.entrada_id == evidencia.entrada_id
    )


def _entrada_da_proveniencia(
    proveniencia: Proveniencia,
    entradas_por_chave: dict[tuple[str, str], tuple[EntradaDeLog, ...]],
) -> EntradaDeLog | None:
    candidatas = entradas_por_chave.get(
        (proveniencia.arquivo_token, proveniencia.entrada_id), ()
    )
    validas = tuple(
        entrada
        for entrada in candidatas
        if _proveniencia_pertence_a_entrada(proveniencia, entrada)
    )
    if not validas:
        return None
    aplicacoes = {entrada.aplicacao for entrada in validas}
    if len(aplicacoes) != 1:
        return None
    return validas[0]


def _nos_do_caminho(
    caminho: CaminhoEvidenciado,
) -> set[tuple[TipoIdentificador, str, str]]:
    nos = {_chave_no(caminho.semente), _chave_no(caminho.destino)}
    for passo in caminho.passos:
        nos.add(_chave_no(passo.origem))
        nos.add(_chave_no(passo.destino))
    return nos


def _evidencia_de_identificador(
    ocorrencia: _OcorrenciaIdentificador,
    *,
    tipo: str,
    condicao: str,
) -> Evidencia:
    identificador = ocorrencia.identificador
    entrada = ocorrencia.entrada
    return Evidencia(
        tipo=tipo,
        aplicacao=entrada.aplicacao,
        proveniencia=identificador.proveniencia,
        timestamp_original=entrada.timestamp_original,
        timestamp_normalizado=entrada.timestamp_normalizado,
        campo_ou_condicao=condicao,
        # O valor permanece interno e será substituído pela visão segura antes
        # de qualquer fronteira de saída.
        representacao_sanitizada=identificador.valor_original,
    )


def _evidencia_de_vinculo(
    entrada: EntradaDeLog,
    vinculo: VinculoIdentificadores,
) -> Evidencia:
    proveniencia = replace(
        vinculo.evidencia,
        regra_extracao=(
            f"vinculo:{vinculo.esquema_id}:v{vinculo.esquema_versao}"
        ),
    )
    return Evidencia(
        tipo="vinculo",
        aplicacao=entrada.aplicacao,
        proveniencia=proveniencia,
        timestamp_original=entrada.timestamp_original,
        timestamp_normalizado=entrada.timestamp_normalizado,
        campo_ou_condicao=vinculo.tipo_relacao,
        representacao_sanitizada=(
            f"{vinculo.origem.valor_original} -> "
            f"{vinculo.destino.valor_original}"
        ),
    )


def _marcar_cobertura(
    entradas: tuple[EntradaDeLog, ...],
    chaves_cobertas: set[tuple[str, str]],
) -> tuple[EntradaDeLog, ...]:
    resultado: list[EntradaDeLog] = []
    for entrada in entradas:
        chave = _chave_entrada(entrada)
        coberta = chave is not None and chave in chaves_cobertas
        resultado.append(replace(entrada, correlacionada=coberta))
    return tuple(resultado)


def _compor_lacunas(
    vpl: tuple[EntradaDeLog, ...],
    ork: tuple[EntradaDeLog, ...],
    *,
    encontrada: bool,
    detectou_ambiguidade: bool,
) -> tuple[LacunaCorrelacao, ...]:
    lacunas: list[LacunaCorrelacao] = []
    if not vpl:
        lacunas.append(LacunaCorrelacao.VPL_AUSENTE)
    if not ork:
        lacunas.append(LacunaCorrelacao.ORK_AUSENTE)
    if vpl and ork:
        if encontrada and detectou_ambiguidade:
            lacunas.append(LacunaCorrelacao.AMBIGUIDADE_ISOLADA)
        elif not encontrada and detectou_ambiguidade:
            lacunas.append(LacunaCorrelacao.ASSOCIACAO_AMBIGUA)
        elif not encontrada:
            lacunas.append(LacunaCorrelacao.SEM_EVIDENCIA)
    return tuple(lacunas)


def _motivo_sem_correlacao(
    vpl: tuple[EntradaDeLog, ...],
    ork: tuple[EntradaDeLog, ...],
    *,
    detectou_ambiguidade: bool,
) -> str:
    if not vpl and not ork:
        return MOTIVO_AMBOS_LADOS_AUSENTES
    if not vpl:
        return MOTIVO_VPL_AUSENTE
    if not ork:
        return MOTIVO_ORK_AUSENTE
    if detectou_ambiguidade:
        return MOTIVO_AMBIGUIDADE
    return MOTIVO_SEM_EVIDENCIA


def _adicionar_unico(lista: list[object], item: object) -> None:
    if item not in lista:
        lista.append(item)


# Adapter público legado: assinatura e comportamento da Fase 1 preservados.
def correlacionar_vpl_ork(
    entradas_vpl: list[EntradaDeLog],
    entradas_ork: list[EntradaDeLog],
    identificador: str,
) -> tuple[list[EntradaDeLog], list[EntradaDeLog], bool, list[MensagemDeErro]]:
    """Correlaciona entradas VPL e ORK que compartilham o mesmo identificador.

    As entradas recebidas já foram filtradas pelo identificador. Portanto, se ambos
    os lados possuem entradas, todas elas são consideradas correlacionadas
    (compartilham o identificador).

    Args:
        entradas_vpl: Entradas de log da aplicação VPL (já filtradas pelo identificador).
        entradas_ork: Entradas de log da aplicação ORK (já filtradas pelo identificador).
        identificador: O identificador usado na busca.

    Returns:
        Tupla com:
        - Lista de entradas VPL atualizadas (correlacionada=True quando aplicável)
        - Lista de entradas ORK atualizadas (correlacionada=True quando aplicável)
        - correlacao_encontrada: True se ambos os lados possuem entradas
        - Lista de MensagemDeErro se um dos lados estiver indisponível
    """
    erros: list[MensagemDeErro] = []

    # Se ambos os lados possuem entradas, há correlação
    if entradas_vpl and entradas_ork:
        vpl_atualizadas = [
            replace(entrada, correlacionada=True) for entrada in entradas_vpl
        ]
        ork_atualizadas = [
            replace(entrada, correlacionada=True) for entrada in entradas_ork
        ]
        return vpl_atualizadas, ork_atualizadas, True, erros

    # Se nenhum dos lados possui entradas, não há correlação
    if not entradas_vpl and not entradas_ork:
        return [], [], False, erros

    # Um dos lados está indisponível — registrar erro e preservar o outro lado
    if not entradas_vpl:
        erros.append(
            MensagemDeErro(
                arquivo_ou_app="VPL",
                descricao=(
                    f"Nenhuma entrada VPL disponível para o identificador "
                    f"'{identificador}' durante a correlação."
                ),
            )
        )
        return [], list(entradas_ork), False, erros

    # not entradas_ork
    erros.append(
        MensagemDeErro(
            arquivo_ou_app="ORK",
            descricao=(
                f"Nenhuma entrada ORK disponível para o identificador "
                f"'{identificador}' durante a correlação."
            ),
        )
    )
    return list(entradas_vpl), [], False, erros


__all__ = [
    "CorrelacionadorVplOrk",
    "LacunaCorrelacao",
    "MOTIVO_AMBIGUIDADE",
    "MOTIVO_AMBIGUIDADE_ISOLADA",
    "MOTIVO_AMBOS_LADOS_AUSENTES",
    "MOTIVO_ORK_AUSENTE",
    "MOTIVO_SEM_EVIDENCIA",
    "MOTIVO_VPL_AUSENTE",
    "ResultadoCorrelacaoVplOrk",
    "correlacionar_vpl_ork",
]
