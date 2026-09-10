"""Busca estruturada, literal e evidenciada de cenários da Fase 2.

O serviço deste módulo é separado de :func:`filtrar_por_identificador`, cujo
comportamento da Fase 1 permanece uma busca literal simples. A busca nova usa o
índice HMAC para igualdade em campos conhecidos e consulta o texto somente como
fallback por entrada. Relações entre entradas são percorridas exclusivamente
pelo :class:`~log_analyzer.core.vinculos.GrafoDeVinculos`, que já restringe a
travessia a arestas explicitamente reconhecidas, autorizadas e não ambíguas.

Nenhuma etapa usa timestamp, ordem de leitura, coexistência de valores ou
similaridade. A consulta é validada antes de entradas, índice ou grafo serem
consultados. O estado confirmado do buscador só é substituído ao final de uma
busca bem-sucedida, tornando a rejeição de consulta atômica.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
import hmac
from typing import Protocol, TypeAlias

from log_analyzer.core.modelos import EntradaDeLog, EntradaIndexada
from log_analyzer.core.validacao import validar_identificador
from log_analyzer.core.vinculos import (
    CaminhoEvidenciado,
    GrafoDeVinculos,
    PassoDeVinculo,
)


__all__ = [
    "BuscadorDeCenario",
    "InclusaoDeBusca",
    "InclusaoNaBusca",
    "MotivoInclusao",
    "MotivoInclusaoBusca",
    "ResultadoBusca",
    "ResultadoDaBusca",
    "buscar_cenario",
    "normalizar_consulta_de_cenario",
]


_PARES_DELIMITADORES_EXTERNOS = {
    '"': '"',
    "'": "'",
    "<": ">",
    "[": "]",
    "(": ")",
    "{": "}",
}


class _IdentificadorIndexado(Protocol):
    entrada_id: str
    namespace: str
    hmac_sha256: str


class _IndiceDeBusca(Protocol):
    """Operações somente de consulta exigidas do índice temporário."""

    def iterar_identificadores(self) -> Iterable[_IdentificadorIndexado]: ...

    def buscar_identificador(
        self, namespace: str, valor_normalizado: str
    ) -> tuple[str, ...]: ...

    def calcular_hmac(self, namespace: str, valor_normalizado: str) -> str: ...


EntradaPesquisavel: TypeAlias = EntradaDeLog | EntradaIndexada


class MotivoInclusaoBusca(Enum):
    """Mecanismo auditável que incluiu uma entrada na seleção."""

    IGUALDADE_ESTRUTURADA = "igualdade_estruturada"
    FALLBACK_LITERAL = "fallback_literal"
    EXPANSAO_POR_VINCULO = "expansao_por_vinculo"
    EVIDENCIA_DE_VINCULO = "evidencia_de_vinculo"

    # Aliases descritivos para consumidores que usam a terminologia da spec.
    CAMPO_ESTRUTURADO = IGUALDADE_ESTRUTURADA
    OCORRENCIA_LITERAL = FALLBACK_LITERAL
    CADEIA_DE_VINCULOS = EXPANSAO_POR_VINCULO


MotivoInclusao = MotivoInclusaoBusca


_ORDEM_MOTIVOS = {
    MotivoInclusaoBusca.IGUALDADE_ESTRUTURADA: 0,
    MotivoInclusaoBusca.FALLBACK_LITERAL: 1,
    MotivoInclusaoBusca.EXPANSAO_POR_VINCULO: 2,
    MotivoInclusaoBusca.EVIDENCIA_DE_VINCULO: 3,
}


@dataclass(frozen=True, slots=True)
class InclusaoNaBusca:
    """Justificativa consolidada de uma entrada selecionada.

    ``motivos`` pode ter mais de um item porque uma entrada pode ser, por
    exemplo, semente estruturada e também evidência de uma aresta. A seleção em
    :class:`ResultadoBusca` continua contendo o ``entrada_id`` exatamente uma
    vez. Caminhos são obrigatórios somente para inclusões decorrentes de
    vínculos; uma semente ou ocorrência literal não inventa uma aresta vazia.
    """

    entrada_id: str
    motivos: tuple[MotivoInclusaoBusca, ...]
    namespaces_correspondentes: tuple[str, ...] = ()
    caminhos_evidenciados: tuple[CaminhoEvidenciado, ...] = ()

    def __post_init__(self) -> None:
        _validar_entrada_id(self.entrada_id)
        if not isinstance(self.motivos, tuple) or not self.motivos:
            raise ValueError("motivos deve ser uma tupla não vazia.")
        if not all(
            isinstance(motivo, MotivoInclusaoBusca) for motivo in self.motivos
        ):
            raise TypeError("motivos deve conter MotivoInclusaoBusca.")
        if len(set(self.motivos)) != len(self.motivos):
            raise ValueError("motivos não pode conter duplicatas.")
        if tuple(sorted(self.motivos, key=_ORDEM_MOTIVOS.__getitem__)) != self.motivos:
            raise ValueError("motivos deve usar a ordem canônica.")

        if not isinstance(self.namespaces_correspondentes, tuple) or not all(
            isinstance(namespace, str) and bool(namespace.strip())
            for namespace in self.namespaces_correspondentes
        ):
            raise TypeError(
                "namespaces_correspondentes deve conter strings não vazias."
            )
        if tuple(sorted(set(self.namespaces_correspondentes))) != (
            self.namespaces_correspondentes
        ):
            raise ValueError(
                "namespaces_correspondentes deve ser único e ordenado."
            )
        if (
            self.namespaces_correspondentes
            and MotivoInclusaoBusca.IGUALDADE_ESTRUTURADA not in self.motivos
        ):
            raise ValueError(
                "namespace correspondente requer igualdade estruturada."
            )

        if not isinstance(self.caminhos_evidenciados, tuple) or not all(
            isinstance(caminho, CaminhoEvidenciado)
            for caminho in self.caminhos_evidenciados
        ):
            raise TypeError(
                "caminhos_evidenciados deve conter CaminhoEvidenciado."
            )
        if len(set(self.caminhos_evidenciados)) != len(
            self.caminhos_evidenciados
        ):
            raise ValueError("caminhos_evidenciados não pode conter duplicatas.")

        motivos_de_vinculo = {
            MotivoInclusaoBusca.EXPANSAO_POR_VINCULO,
            MotivoInclusaoBusca.EVIDENCIA_DE_VINCULO,
        }
        if motivos_de_vinculo.intersection(self.motivos):
            if not self.caminhos_evidenciados:
                raise ValueError(
                    "inclusão por vínculo requer caminho evidenciado."
                )
            if any(not caminho.passos for caminho in self.caminhos_evidenciados):
                raise ValueError(
                    "caminho de inclusão por vínculo deve conter ao menos um passo."
                )
            if any(
                passo.vinculo.ambiguo
                or not passo.vinculo.permite_correlacao
                for caminho in self.caminhos_evidenciados
                for passo in caminho.passos
            ):
                raise ValueError(
                    "caminho ambíguo ou não autorizado não pode incluir entrada."
                )

    @property
    def motivo(self) -> MotivoInclusaoBusca:
        """Motivo primário, segundo a precedência canônica de auditoria."""

        return self.motivos[0]

    @property
    def caminho_evidenciado(self) -> CaminhoEvidenciado | None:
        """Primeiro caminho determinístico, quando a inclusão veio do grafo."""

        return self.caminhos_evidenciados[0] if self.caminhos_evidenciados else None

    @property
    def vinculos_percorridos(self):
        """Vínculos distintos usados pelos caminhos desta inclusão."""

        vistos: set[object] = set()
        vinculos: list[object] = []
        for caminho in self.caminhos_evidenciados:
            for vinculo in caminho.vinculos:
                if vinculo not in vistos:
                    vistos.add(vinculo)
                    vinculos.append(vinculo)
        return tuple(vinculos)


InclusaoDeBusca = InclusaoNaBusca


@dataclass(frozen=True, slots=True)
class ResultadoBusca:
    """Seleção imutável e deduplicada produzida pelo buscador de cenário."""

    consulta_normalizada: str
    inclusoes: tuple[InclusaoNaBusca, ...] = ()
    entradas: tuple[EntradaPesquisavel, ...] = field(
        default=(), repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if not isinstance(self.consulta_normalizada, str) or not (
            self.consulta_normalizada
        ):
            raise ValueError("consulta_normalizada deve ser string não vazia.")
        if not isinstance(self.inclusoes, tuple) or not all(
            isinstance(inclusao, InclusaoNaBusca) for inclusao in self.inclusoes
        ):
            raise TypeError("inclusoes deve conter InclusaoNaBusca.")
        entrada_ids = tuple(inclusao.entrada_id for inclusao in self.inclusoes)
        if entrada_ids != tuple(sorted(set(entrada_ids))):
            raise ValueError(
                "inclusoes deve estar ordenada e deduplicada por entrada_id."
            )
        if not isinstance(self.entradas, tuple) or not all(
            isinstance(entrada, (EntradaDeLog, EntradaIndexada))
            for entrada in self.entradas
        ):
            raise TypeError(
                "entradas deve conter EntradaDeLog ou EntradaIndexada."
            )
        ids_materializados = tuple(_entrada_id_de(entrada) for entrada in self.entradas)
        if len(set(ids_materializados)) != len(ids_materializados):
            raise ValueError("entradas não pode repetir entrada_id.")
        if any(entrada_id not in set(entrada_ids) for entrada_id in ids_materializados):
            raise ValueError("toda entrada materializada deve constar na seleção.")

    @property
    def entrada_ids(self) -> tuple[str, ...]:
        return tuple(inclusao.entrada_id for inclusao in self.inclusoes)

    @property
    def entradas_selecionadas(self) -> tuple[EntradaPesquisavel, ...]:
        """Objetos fornecidos ao buscador que pertencem à seleção."""

        return self.entradas

    @property
    def selecao(self) -> tuple[str, ...]:
        """Alias compacto para os IDs selecionados."""

        return self.entrada_ids

    @property
    def encontrou(self) -> bool:
        return bool(self.inclusoes)

    @property
    def caminhos_evidenciados(self) -> tuple[CaminhoEvidenciado, ...]:
        caminhos: list[CaminhoEvidenciado] = []
        vistos: set[CaminhoEvidenciado] = set()
        for inclusao in self.inclusoes:
            for caminho in inclusao.caminhos_evidenciados:
                if caminho not in vistos:
                    vistos.add(caminho)
                    caminhos.append(caminho)
        return tuple(caminhos)

    @property
    def vinculos_percorridos(self):
        vinculos: list[object] = []
        vistos: set[object] = set()
        for caminho in self.caminhos_evidenciados:
            for vinculo in caminho.vinculos:
                if vinculo not in vistos:
                    vistos.add(vinculo)
                    vinculos.append(vinculo)
        return tuple(vinculos)

    def inclusao_de(self, entrada_id: str) -> InclusaoNaBusca | None:
        _validar_entrada_id(entrada_id)
        return next(
            (
                inclusao
                for inclusao in self.inclusoes
                if inclusao.entrada_id == entrada_id
            ),
            None,
        )


ResultadoDaBusca = ResultadoBusca


@dataclass(slots=True)
class _InclusaoPendente:
    motivos: set[MotivoInclusaoBusca] = field(default_factory=set)
    namespaces: set[str] = field(default_factory=set)
    caminhos: list[CaminhoEvidenciado] = field(default_factory=list)

    def adicionar_caminho(self, caminho: CaminhoEvidenciado) -> None:
        if caminho not in self.caminhos:
            self.caminhos.append(caminho)


class BuscadorDeCenario:
    """Busca entradas por campo, literal e fechamento explícito de vínculos.

    O construtor recebe o índice da análise e, opcionalmente, seu grafo de
    vínculos. :meth:`buscar` aceita a ordem posicional legada
    ``(entradas, identificador)`` e também ``(identificador, entradas)``; o uso
    por palavras-chave ``entradas=..., consulta=...`` é inequívoco.
    """

    def __init__(
        self,
        indice: _IndiceDeBusca,
        grafo: GrafoDeVinculos | None = None,
    ) -> None:
        _validar_indice(indice)
        if grafo is not None and not isinstance(grafo, GrafoDeVinculos):
            raise TypeError("grafo deve ser GrafoDeVinculos ou None.")
        self._indice = indice
        self._grafo = grafo
        self._resultado_atual: ResultadoBusca | None = None

    @property
    def resultado_atual(self) -> ResultadoBusca | None:
        """Último resultado integralmente calculado."""

        return self._resultado_atual

    @property
    def selecao_atual(self) -> tuple[str, ...]:
        """Snapshot imutável dos IDs da última busca confirmada."""

        if self._resultado_atual is None:
            return ()
        return self._resultado_atual.entrada_ids

    @property
    def indice(self) -> _IndiceDeBusca:
        return self._indice

    @property
    def grafo(self) -> GrafoDeVinculos | None:
        return self._grafo

    def buscar(
        self,
        entradas: Iterable[EntradaPesquisavel] | Mapping[str, object] | str,
        identificador: str | Iterable[EntradaPesquisavel] | Mapping[str, object] | None = None,
        *,
        consulta: str | None = None,
        textos_por_entrada_id: Mapping[str, str] | None = None,
        namespaces: Iterable[str] | str | None = None,
    ) -> ResultadoBusca:
        """Executa uma busca e confirma o novo estado somente no sucesso.

        A validação da consulta ocorre antes de enumerar ``entradas``, validar
        textos, descobrir namespaces ou chamar qualquer método do índice. Isso
        garante que consulta vazia, whitespace ou maior que 256 caracteres não
        altere seleção, lotes pendentes ou qualquer outro estado observável.
        """

        entradas_resolvidas, consulta_resolvida = _resolver_argumentos_busca(
            entradas,
            identificador,
            consulta,
        )

        # Esta chamada precisa permanecer antes de qualquer acesso às fontes.
        validar_identificador(consulta_resolvida)
        consulta_normalizada = normalizar_consulta_de_cenario(
            consulta_resolvida,
            validar=False,
        )

        objetos_por_id, textos = _preparar_entradas(
            entradas_resolvidas,
            textos_por_entrada_id,
        )
        namespaces_resolvidos = _resolver_namespaces(
            self._indice,
            namespaces,
        )

        pendentes: dict[str, _InclusaoPendente] = defaultdict(_InclusaoPendente)
        correspondencias_estruturadas: dict[str, set[str]] = defaultdict(set)
        digests_consulta: dict[str, str] = {}

        for namespace in namespaces_resolvidos:
            digest_consulta = self._indice.calcular_hmac(
                namespace,
                consulta_normalizada,
            )
            digests_consulta[namespace] = digest_consulta
            for entrada_id in self._indice.buscar_identificador(
                namespace,
                consulta_normalizada,
            ):
                _validar_entrada_id(entrada_id)
                correspondencias_estruturadas[entrada_id].add(namespace)

        for entrada_id, namespaces_da_entrada in (
            correspondencias_estruturadas.items()
        ):
            inclusao = pendentes[entrada_id]
            inclusao.motivos.add(MotivoInclusaoBusca.IGUALDADE_ESTRUTURADA)
            inclusao.namespaces.update(namespaces_da_entrada)

        # O literal original (não o valor normalizado) é o fallback aprovado.
        consulta_literal = consulta_resolvida.casefold()
        for entrada_id in sorted(textos):
            if entrada_id in correspondencias_estruturadas:
                continue
            if consulta_literal in textos[entrada_id].casefold():
                pendentes[entrada_id].motivos.add(
                    MotivoInclusaoBusca.FALLBACK_LITERAL
                )

        if self._grafo is not None and correspondencias_estruturadas:
            self._expandir_por_vinculos(
                correspondencias_estruturadas,
                digests_consulta,
                pendentes,
            )

        inclusoes = tuple(
            _consolidar_inclusao(entrada_id, pendentes[entrada_id])
            for entrada_id in sorted(pendentes)
        )
        ids_selecionados = {inclusao.entrada_id for inclusao in inclusoes}
        entradas_selecionadas = tuple(
            objetos_por_id[entrada_id]
            for entrada_id in sorted(objetos_por_id)
            if entrada_id in ids_selecionados
        )
        resultado = ResultadoBusca(
            consulta_normalizada=consulta_normalizada,
            inclusoes=inclusoes,
            entradas=entradas_selecionadas,
        )

        # Commit único: nenhuma exceção anterior altera o estado confirmado.
        self._resultado_atual = resultado
        return resultado

    pesquisar = buscar

    def _expandir_por_vinculos(
        self,
        correspondencias_estruturadas: Mapping[str, set[str]],
        digests_consulta: Mapping[str, str],
        pendentes: dict[str, _InclusaoPendente],
    ) -> None:
        grafo = self._grafo
        if grafo is None:
            return

        sementes = []
        for no in grafo.nos:
            for ocorrencia in grafo.ocorrencias_de(no):
                entrada_id = ocorrencia.proveniencia.entrada_id
                namespace = ocorrencia.namespace_comparacao
                if namespace not in correspondencias_estruturadas.get(
                    entrada_id, set()
                ):
                    continue
                digest_consulta = digests_consulta.get(namespace)
                if digest_consulta is None:
                    continue
                digest_ocorrencia = self._indice.calcular_hmac(
                    namespace,
                    ocorrencia.valor_normalizado,
                )
                if hmac.compare_digest(digest_consulta, digest_ocorrencia):
                    sementes.append(ocorrencia)

        if not sementes:
            return

        travessia = grafo.percorrer_bfs(
            sementes,
            incluir_componentes_ambiguos=False,
            somente_arestas_expansiveis=True,
        )
        for caminho in travessia.caminhos:
            # Defesa em profundidade: a BFS já aplica os dois filtros.
            if any(
                passo.vinculo.ambiguo
                or not passo.vinculo.permite_correlacao
                for passo in caminho.passos
            ):
                continue

            for ocorrencia in grafo.ocorrencias_de(caminho.destino):
                inclusao = pendentes[ocorrencia.proveniencia.entrada_id]
                inclusao.motivos.add(
                    MotivoInclusaoBusca.EXPANSAO_POR_VINCULO
                )
                inclusao.adicionar_caminho(caminho)

            for indice_passo, passo in enumerate(caminho.passos):
                prefixo = _prefixo_do_caminho(caminho, indice_passo)
                inclusao_evidencia = pendentes[
                    passo.evidencia.entrada_id
                ]
                inclusao_evidencia.motivos.add(
                    MotivoInclusaoBusca.EVIDENCIA_DE_VINCULO
                )
                inclusao_evidencia.adicionar_caminho(prefixo)


def normalizar_consulta_de_cenario(
    consulta: str,
    *,
    validar: bool = True,
) -> str:
    """Normaliza a consulta como os campos conhecidos, sem inferir seu tipo.

    Remove whitespace periférico e pares completos de delimitadores externos
    aprovados, depois aplica :meth:`str.casefold`. Se os delimitadores formarem
    todo o conteúdo (por exemplo ``<>``), a consulta bruta sem whitespace é
    preservada para não ampliar os três casos de rejeição definidos na spec.
    """

    if not isinstance(consulta, str):
        raise TypeError("consulta deve ser string.")
    if validar:
        validar_identificador(consulta)

    sem_whitespace = consulta.strip()
    resultado = sem_whitespace
    while len(resultado) >= 2:
        fechamento = _PARES_DELIMITADORES_EXTERNOS.get(resultado[0])
        if fechamento is None or resultado[-1] != fechamento:
            break
        resultado = resultado[1:-1].strip()
    if not resultado:
        resultado = sem_whitespace
    return resultado.casefold()


def buscar_cenario(
    entradas: Iterable[EntradaPesquisavel] | Mapping[str, object],
    identificador: str,
    *,
    indice: _IndiceDeBusca,
    grafo: GrafoDeVinculos | None = None,
    textos_por_entrada_id: Mapping[str, str] | None = None,
    namespaces: Iterable[str] | str | None = None,
) -> ResultadoBusca:
    """Atalho funcional para uma busca sem estado prévio."""

    return BuscadorDeCenario(indice, grafo).buscar(
        entradas,
        identificador,
        textos_por_entrada_id=textos_por_entrada_id,
        namespaces=namespaces,
    )


def _resolver_argumentos_busca(
    entradas: Iterable[EntradaPesquisavel] | Mapping[str, object] | str,
    identificador: str | Iterable[EntradaPesquisavel] | Mapping[str, object] | None,
    consulta: str | None,
) -> tuple[
    Iterable[EntradaPesquisavel] | Mapping[str, object],
    str,
]:
    if consulta is not None:
        if identificador is not None:
            raise TypeError("informe apenas identificador ou consulta.")
        if isinstance(entradas, str):
            raise TypeError(
                "entradas deve ser fornecido separadamente da consulta."
            )
        if not isinstance(consulta, str):
            raise TypeError("consulta deve ser string.")
        return entradas, consulta

    # Forma alternativa: buscar(identificador, entradas).
    if isinstance(entradas, str) and identificador is not None and not isinstance(
        identificador, str
    ):
        return identificador, entradas

    if isinstance(entradas, str):
        raise TypeError("entradas deve ser um iterável, não string.")
    if not isinstance(identificador, str):
        raise TypeError("identificador deve ser string.")
    return entradas, identificador


def _preparar_entradas(
    entradas: Iterable[EntradaPesquisavel] | Mapping[str, object],
    textos_adicionais: Mapping[str, str] | None,
) -> tuple[dict[str, EntradaPesquisavel], dict[str, str]]:
    objetos_por_id: dict[str, EntradaPesquisavel] = {}
    textos: dict[str, str] = {}

    if isinstance(entradas, Mapping):
        itens: Iterable[tuple[object, object]] = entradas.items()
        for chave, valor in itens:
            entrada_id = _validar_entrada_id(chave)
            if isinstance(valor, str):
                textos[entrada_id] = valor
                continue
            if not isinstance(valor, (EntradaDeLog, EntradaIndexada)):
                raise TypeError(
                    "mapeamento de entradas deve conter texto ou entrada pesquisável."
                )
            id_do_objeto = _entrada_id_de(valor)
            if id_do_objeto != entrada_id:
                raise ValueError(
                    "chave do mapeamento deve corresponder ao entrada_id."
                )
            objetos_por_id.setdefault(entrada_id, valor)
            if isinstance(valor, EntradaDeLog):
                textos.setdefault(entrada_id, valor.texto_original)
    else:
        if isinstance(entradas, (str, bytes)):
            raise TypeError("entradas deve ser um iterável de entradas pesquisáveis.")
        try:
            for entrada in entradas:
                if not isinstance(entrada, (EntradaDeLog, EntradaIndexada)):
                    raise TypeError(
                        "entradas deve conter EntradaDeLog ou EntradaIndexada."
                    )
                entrada_id = _entrada_id_de(entrada)
                objetos_por_id.setdefault(entrada_id, entrada)
                if isinstance(entrada, EntradaDeLog):
                    texto_existente = textos.get(entrada_id)
                    if (
                        texto_existente is not None
                        and texto_existente != entrada.texto_original
                    ):
                        raise ValueError(
                            "entrada_id duplicado possui texto divergente."
                        )
                    textos.setdefault(entrada_id, entrada.texto_original)
        except TypeError as erro:
            if str(erro) == (
                "entradas deve conter EntradaDeLog ou EntradaIndexada."
            ):
                raise
            raise TypeError(
                "entradas deve ser um iterável de entradas pesquisáveis."
            ) from None

    if textos_adicionais is not None:
        if not isinstance(textos_adicionais, Mapping):
            raise TypeError("textos_por_entrada_id deve ser um mapeamento.")
        for chave, texto in textos_adicionais.items():
            entrada_id = _validar_entrada_id(chave)
            if not isinstance(texto, str):
                raise TypeError(
                    "textos_por_entrada_id deve conter somente strings."
                )
            textos[entrada_id] = texto

    return objetos_por_id, textos


def _resolver_namespaces(
    indice: _IndiceDeBusca,
    namespaces: Iterable[str] | str | None,
) -> tuple[str, ...]:
    if namespaces is None:
        candidatos = (
            identificador.namespace
            for identificador in indice.iterar_identificadores()
        )
    elif isinstance(namespaces, str):
        candidatos = (namespaces,)
    else:
        if isinstance(namespaces, bytes):
            raise TypeError("namespaces deve conter strings.")
        candidatos = namespaces

    try:
        normalizados = {
            _validar_namespace(namespace) for namespace in candidatos
        }
    except TypeError as erro:
        if str(erro) == "namespace deve ser string.":
            raise
        raise TypeError("namespaces deve ser um iterável de strings.") from None
    return tuple(sorted(normalizados))


def _prefixo_do_caminho(
    caminho: CaminhoEvidenciado,
    indice_passo: int,
) -> CaminhoEvidenciado:
    passos: tuple[PassoDeVinculo, ...] = caminho.passos[: indice_passo + 1]
    return CaminhoEvidenciado(
        semente=caminho.semente,
        destino=passos[-1].destino,
        passos=passos,
    )


def _consolidar_inclusao(
    entrada_id: str,
    pendente: _InclusaoPendente,
) -> InclusaoNaBusca:
    motivos = tuple(sorted(pendente.motivos, key=_ORDEM_MOTIVOS.__getitem__))
    caminhos = tuple(pendente.caminhos)
    return InclusaoNaBusca(
        entrada_id=entrada_id,
        motivos=motivos,
        namespaces_correspondentes=tuple(sorted(pendente.namespaces)),
        caminhos_evidenciados=caminhos,
    )


def _validar_indice(indice: object) -> None:
    metodos = (
        "iterar_identificadores",
        "buscar_identificador",
        "calcular_hmac",
    )
    if any(not callable(getattr(indice, metodo, None)) for metodo in metodos):
        raise TypeError("indice não implementa as operações de busca exigidas.")


def _validar_namespace(namespace: object) -> str:
    if not isinstance(namespace, str):
        raise TypeError("namespace deve ser string.")
    normalizado = namespace.strip()
    if not normalizado:
        raise ValueError("namespace deve ser uma string não vazia.")
    return normalizado


def _validar_entrada_id(entrada_id: object) -> str:
    if not isinstance(entrada_id, str):
        raise TypeError("entrada_id deve ser string.")
    normalizado = entrada_id.strip()
    if not normalizado:
        raise ValueError("entrada_id deve ser uma string não vazia.")
    if normalizado != entrada_id:
        raise ValueError("entrada_id não pode possuir whitespace periférico.")
    return entrada_id


def _entrada_id_de(entrada: EntradaPesquisavel) -> str:
    entrada_id = entrada.entrada_id
    if entrada_id is None:
        raise ValueError("entrada pesquisável requer entrada_id.")
    return _validar_entrada_id(entrada_id)
