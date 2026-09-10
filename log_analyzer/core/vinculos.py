"""Esquemas explícitos e grafo determinístico de vínculos da Fase 2.

O módulo não contém esquemas concretos e não examina texto, timestamps, ordem de
leitura ou similaridade. Uma aresta nasce exclusivamente quando um
:class:`EsquemaDeVinculo` aprovado e registrado reconhece uma
:class:`DeclaracaoSemanticaDeVinculo`. Identificadores adicionados isoladamente
permanecem nós desconectados.

As relações são armazenadas com a versão do esquema e a proveniência da entrada
que declarou os dois papéis. A travessia segura ignora relações sem permissão de
expansão e componentes cuja cardinalidade foi violada; uma travessia diagnóstica
pode, explicitamente, inspecionar essas relações sem torná-las aptas a sustentar
classificação.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from enum import Enum
from hashlib import sha256

from log_analyzer.core.modelos import (
    IdentificadorTecnico,
    Proveniencia,
    TipoIdentificador,
    VinculoIdentificadores,
)


__all__ = [
    "CaminhoDeVinculos",
    "CaminhoEvidenciado",
    "Cardinalidade",
    "CardinalidadeDeVinculo",
    "ChaveDeIdentificador",
    "DeclaracaoSemanticaDeVinculo",
    "EsquemaDeVinculo",
    "GrafoDeVinculos",
    "PapelCardinalidade",
    "PassoDeVinculo",
    "RegistroDeEsquemas",
    "RegistroDeEsquemasDeVinculo",
    "Registro_de_Esquemas_de_Vinculo",
    "ResultadoTravessia",
    "ViolacaoDeCardinalidade",
]


def _exigir_texto(valor: object, nome: str) -> str:
    if not isinstance(valor, str):
        raise TypeError(f"{nome} deve ser string.")
    normalizado = valor.strip()
    if not normalizado:
        raise ValueError(f"{nome} deve ser uma string não vazia.")
    return normalizado


def _identidade(identificador: IdentificadorTecnico) -> tuple[object, str, str]:
    """Identidade lógica; proveniências distintas continuam ocorrências do nó."""

    return (
        identificador.tipo,
        identificador.namespace_comparacao,
        identificador.valor_normalizado,
    )


def _mesma_entrada(
    proveniencia: Proveniencia,
    evidencia: Proveniencia,
) -> bool:
    return (
        proveniencia.arquivo_token == evidencia.arquivo_token
        and proveniencia.entrada_id == evidencia.entrada_id
    )


def _ordem_proveniencia(proveniencia: Proveniencia) -> tuple[object, ...]:
    return (
        proveniencia.entrada_id,
        proveniencia.arquivo_token,
        proveniencia.linha_inicial,
        proveniencia.linha_final,
        -1 if proveniencia.span_inicial is None else proveniencia.span_inicial,
        -1 if proveniencia.span_final is None else proveniencia.span_final,
        proveniencia.nome_campo or "",
        proveniencia.regra_extracao or "",
    )


class Cardinalidade(Enum):
    """Cardinalidade direcional de um esquema.

    Cada valor armazena ``(máximo de destinos por origem, máximo de origens por
    destino)``. ``None`` significa que o papel não impõe limite. A direção é a
    direção semântica declarada pelo esquema; a travessia do grafo continua
    bidirecional.
    """

    UM_PARA_UM = (1, 1)
    UM_PARA_MUITOS = (None, 1)
    MUITOS_PARA_UM = (1, None)
    MUITOS_PARA_MUITOS = (None, None)

    # Formas usuais alternativas, mantidas como aliases do mesmo contrato.
    UM_PARA_N = UM_PARA_MUITOS
    N_PARA_UM = MUITOS_PARA_UM
    N_PARA_N = MUITOS_PARA_MUITOS

    @property
    def max_destinos_por_origem(self) -> int | None:
        return self.value[0]

    @property
    def max_origens_por_destino(self) -> int | None:
        return self.value[1]


CardinalidadeDeVinculo = Cardinalidade


class PapelCardinalidade(Enum):
    """Papel cujo limite foi excedido em uma relação direcionada."""

    ORIGEM = "origem"
    DESTINO = "destino"


@dataclass(frozen=True)
class ChaveDeIdentificador:
    """Chave lógica tipada usada internamente pelos componentes do grafo.

    O valor normalizado participa da igualdade, mas é omitido de ``repr``. O
    digest serve exclusivamente para ordenação determinística e não é tratado
    como índice seguro ou representação sanitizada.
    """

    tipo: TipoIdentificador
    namespace_comparacao: str
    valor_normalizado: str = field(repr=False)
    digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.tipo, TipoIdentificador):
            raise TypeError("tipo deve ser TipoIdentificador.")
        namespace = _exigir_texto(
            self.namespace_comparacao, "namespace_comparacao"
        )
        valor = _exigir_texto(self.valor_normalizado, "valor_normalizado")
        object.__setattr__(self, "namespace_comparacao", namespace)
        object.__setattr__(self, "valor_normalizado", valor)
        material = f"{namespace}\0{valor}".encode("utf-8")
        object.__setattr__(self, "digest", sha256(material).hexdigest())

    @classmethod
    def de_identificador(
        cls, identificador: IdentificadorTecnico
    ) -> ChaveDeIdentificador:
        if not isinstance(identificador, IdentificadorTecnico):
            raise TypeError("identificador deve ser IdentificadorTecnico.")
        return cls(
            tipo=identificador.tipo,
            namespace_comparacao=identificador.namespace_comparacao,
            valor_normalizado=identificador.valor_normalizado,
        )


@dataclass(frozen=True)
class DeclaracaoSemanticaDeVinculo:
    """Fato estruturado de que uma entrada declarou dois papéis relacionados.

    A classe não é criada automaticamente a partir da coexistência de valores.
    Ambos os identificadores e a evidência precisam pertencer à mesma entrada;
    ``codigo_semantico`` e ``fatos`` são interpretados somente por esquemas
    aprovados fornecidos externamente.
    """

    origem: IdentificadorTecnico
    destino: IdentificadorTecnico
    evidencia: Proveniencia
    codigo_semantico: str
    fatos: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not isinstance(self.origem, IdentificadorTecnico):
            raise TypeError("origem deve ser IdentificadorTecnico.")
        if not isinstance(self.destino, IdentificadorTecnico):
            raise TypeError("destino deve ser IdentificadorTecnico.")
        if not isinstance(self.evidencia, Proveniencia):
            raise TypeError("evidencia deve ser Proveniencia.")

        codigo = _exigir_texto(self.codigo_semantico, "codigo_semantico")
        object.__setattr__(self, "codigo_semantico", codigo)

        if isinstance(self.fatos, str):
            raise TypeError("fatos deve ser uma coleção de strings.")
        try:
            fatos = frozenset(self.fatos)
        except TypeError as erro:
            raise TypeError("fatos deve ser uma coleção de strings.") from erro
        if not all(isinstance(fato, str) and fato.strip() for fato in fatos):
            raise ValueError("fatos deve conter somente strings não vazias.")
        object.__setattr__(self, "fatos", frozenset(fato.strip() for fato in fatos))

        if _identidade(self.origem) == _identidade(self.destino):
            raise ValueError(
                "uma declaração de vínculo requer dois identificadores distintos."
            )
        if not _mesma_entrada(self.origem.proveniencia, self.evidencia):
            raise ValueError(
                "a origem e a evidência devem pertencer à mesma entrada."
            )
        if not _mesma_entrada(self.destino.proveniencia, self.evidencia):
            raise ValueError(
                "o destino e a evidência devem pertencer à mesma entrada."
            )

    @property
    def tipo_declaracao(self) -> str:
        """Alias legível para consumidores que chamam o código de tipo."""

        return self.codigo_semantico


ReconhecedorDeDeclaracao = Callable[[DeclaracaoSemanticaDeVinculo], bool]


def _normalizar_tipos(
    plural: Iterable[TipoIdentificador] | TipoIdentificador | None,
    singular: TipoIdentificador | None,
    nome: str,
) -> frozenset[TipoIdentificador]:
    if plural is not None and singular is not None:
        raise ValueError(f"informe apenas {nome} ou sua forma singular.")
    valor = singular if singular is not None else plural
    if valor is None:
        raise ValueError(f"{nome} deve ser informado.")
    if isinstance(valor, TipoIdentificador):
        tipos = frozenset((valor,))
    else:
        if isinstance(valor, str):
            raise TypeError(f"{nome} deve conter TipoIdentificador.")
        try:
            tipos = frozenset(valor)
        except TypeError as erro:
            raise TypeError(
                f"{nome} deve ser uma coleção de TipoIdentificador."
            ) from erro
    if not tipos:
        raise ValueError(f"{nome} não pode ser vazio.")
    if not all(isinstance(tipo, TipoIdentificador) for tipo in tipos):
        raise TypeError(f"{nome} deve conter somente TipoIdentificador.")
    return tipos


@dataclass(frozen=True, init=False)
class EsquemaDeVinculo:
    """Regra versionada que reconhece uma declaração semântica explícita.

    O reconhecedor recebe apenas o fato estruturado; o motor não fornece tempo,
    ordem de linhas ou uma API de similaridade. O esquema pode estar registrado
    como histórico/rascunho, mas somente ``aprovado=True`` participa do
    reconhecimento.
    """

    esquema_id: str
    versao: int
    tipo_relacao: str
    tipos_origem: frozenset[TipoIdentificador]
    tipos_destino: frozenset[TipoIdentificador]
    cardinalidade: Cardinalidade
    permite_expansao_de_cenario: bool
    aprovado: bool
    reconhecedor: ReconhecedorDeDeclaracao = field(repr=False, compare=False)

    def __init__(
        self,
        esquema_id: str,
        versao: int,
        tipo_relacao: str,
        tipos_origem: Iterable[TipoIdentificador] | TipoIdentificador | None = None,
        tipos_destino: Iterable[TipoIdentificador] | TipoIdentificador | None = None,
        cardinalidade: Cardinalidade = Cardinalidade.MUITOS_PARA_MUITOS,
        permite_expansao_de_cenario: bool = False,
        aprovado: bool = False,
        reconhecedor: ReconhecedorDeDeclaracao | None = None,
        *,
        tipo_origem: TipoIdentificador | None = None,
        tipo_destino: TipoIdentificador | None = None,
        permite_correlacao: bool | None = None,
    ) -> None:
        esquema_id_normalizado = _exigir_texto(esquema_id, "esquema_id")
        tipo_relacao_normalizado = _exigir_texto(
            tipo_relacao, "tipo_relacao"
        )
        if isinstance(versao, bool) or not isinstance(versao, int) or versao < 1:
            raise ValueError("versao deve ser um inteiro positivo.")
        if not isinstance(cardinalidade, Cardinalidade):
            raise TypeError("cardinalidade deve ser Cardinalidade.")
        if not isinstance(permite_expansao_de_cenario, bool):
            raise TypeError(
                "permite_expansao_de_cenario deve ser booleano."
            )
        if permite_correlacao is not None:
            if not isinstance(permite_correlacao, bool):
                raise TypeError("permite_correlacao deve ser booleano.")
            if permite_expansao_de_cenario and not permite_correlacao:
                raise ValueError(
                    "permissões de expansão informadas são contraditórias."
                )
            permite_expansao_de_cenario = permite_correlacao
        if not isinstance(aprovado, bool):
            raise TypeError("aprovado deve ser booleano.")
        if reconhecedor is None or not callable(reconhecedor):
            raise TypeError("reconhecedor deve ser chamável.")

        object.__setattr__(self, "esquema_id", esquema_id_normalizado)
        object.__setattr__(self, "versao", versao)
        object.__setattr__(self, "tipo_relacao", tipo_relacao_normalizado)
        object.__setattr__(
            self,
            "tipos_origem",
            _normalizar_tipos(tipos_origem, tipo_origem, "tipos_origem"),
        )
        object.__setattr__(
            self,
            "tipos_destino",
            _normalizar_tipos(tipos_destino, tipo_destino, "tipos_destino"),
        )
        object.__setattr__(self, "cardinalidade", cardinalidade)
        object.__setattr__(
            self,
            "permite_expansao_de_cenario",
            permite_expansao_de_cenario,
        )
        object.__setattr__(self, "aprovado", aprovado)
        object.__setattr__(self, "reconhecedor", reconhecedor)

    @property
    def permite_correlacao(self) -> bool:
        """Permissão transportada para ``VinculoIdentificadores``."""

        return self.permite_expansao_de_cenario

    @property
    def chave_versao(self) -> tuple[str, int]:
        return (self.esquema_id, self.versao)

    @property
    def tipo_origem(self) -> TipoIdentificador | None:
        if len(self.tipos_origem) != 1:
            return None
        return next(iter(self.tipos_origem))

    @property
    def tipo_destino(self) -> TipoIdentificador | None:
        if len(self.tipos_destino) != 1:
            return None
        return next(iter(self.tipos_destino))

    def reconhecer(self, declaracao: DeclaracaoSemanticaDeVinculo) -> bool:
        """Reconhece o fato somente se o esquema estiver aprovado e tipado."""

        if not isinstance(declaracao, DeclaracaoSemanticaDeVinculo):
            raise TypeError(
                "declaracao deve ser DeclaracaoSemanticaDeVinculo."
            )
        if not self.aprovado:
            return False
        if declaracao.origem.tipo not in self.tipos_origem:
            return False
        if declaracao.destino.tipo not in self.tipos_destino:
            return False
        resultado = self.reconhecedor(declaracao)
        if not isinstance(resultado, bool):
            raise TypeError("reconhecedor deve retornar bool.")
        return resultado

    def criar_vinculo(
        self, declaracao: DeclaracaoSemanticaDeVinculo
    ) -> VinculoIdentificadores | None:
        """Converte um reconhecimento aprovado em uma aresta evidenciada."""

        if not self.reconhecer(declaracao):
            return None
        return VinculoIdentificadores(
            origem=declaracao.origem,
            destino=declaracao.destino,
            tipo_relacao=self.tipo_relacao,
            evidencia=declaracao.evidencia,
            esquema_id=self.esquema_id,
            esquema_versao=self.versao,
            permite_correlacao=self.permite_expansao_de_cenario,
            ambiguo=False,
        )


class RegistroDeEsquemasDeVinculo:
    """Registro append-only de esquemas, indexado por ID e versão.

    Versões históricas permanecem resolvíveis. Para reconhecimento automático,
    participa apenas a versão aprovada mais alta de cada ID, evitando que duas
    versões do mesmo esquema criem a mesma aresta.
    """

    def __init__(self) -> None:
        self._catalogo: dict[str, dict[int, EsquemaDeVinculo]] = {}

    def registrar(self, esquema: EsquemaDeVinculo) -> None:
        if not isinstance(esquema, EsquemaDeVinculo):
            raise TypeError("esquema deve ser EsquemaDeVinculo.")
        versoes = self._catalogo.setdefault(esquema.esquema_id, {})
        if esquema.versao in versoes:
            raise ValueError("esquema e versão já estão registrados.")
        versoes[esquema.versao] = esquema

    def obter(
        self, esquema_id: str, versao: int | None = None
    ) -> EsquemaDeVinculo:
        esquema_id = _exigir_texto(esquema_id, "esquema_id")
        versoes = self._catalogo.get(esquema_id)
        if not versoes:
            raise KeyError("esquema não registrado.")
        if versao is None:
            versao = max(versoes)
        if isinstance(versao, bool) or not isinstance(versao, int) or versao < 1:
            raise ValueError("versao deve ser um inteiro positivo.")
        try:
            return versoes[versao]
        except KeyError:
            raise KeyError("versão de esquema não registrada.") from None

    def obter_aprovado(
        self, esquema_id: str, versao: int | None = None
    ) -> EsquemaDeVinculo:
        esquema_id = _exigir_texto(esquema_id, "esquema_id")
        if versao is not None:
            esquema = self.obter(esquema_id, versao)
            if not esquema.aprovado:
                raise KeyError("versão de esquema não aprovada.")
            return esquema
        versoes = self._catalogo.get(esquema_id, {})
        aprovadas = [
            item for item in versoes.values() if item.aprovado
        ]
        if not aprovadas:
            raise KeyError("esquema não possui versão aprovada.")
        return max(aprovadas, key=lambda item: item.versao)

    def esta_registrado(
        self, esquema_id: str, versao: int | None = None
    ) -> bool:
        if not isinstance(esquema_id, str) or not esquema_id.strip():
            return False
        versoes = self._catalogo.get(esquema_id.strip(), {})
        return bool(versoes) if versao is None else versao in versoes

    def versoes(self, esquema_id: str) -> tuple[int, ...]:
        esquema_id = _exigir_texto(esquema_id, "esquema_id")
        return tuple(sorted(self._catalogo.get(esquema_id, {})))

    def esquemas(
        self,
        *,
        apenas_aprovados: bool = False,
        apenas_versao_mais_recente: bool = False,
    ) -> tuple[EsquemaDeVinculo, ...]:
        if not isinstance(apenas_aprovados, bool):
            raise TypeError("apenas_aprovados deve ser booleano.")
        if not isinstance(apenas_versao_mais_recente, bool):
            raise TypeError(
                "apenas_versao_mais_recente deve ser booleano."
            )

        resultado: list[EsquemaDeVinculo] = []
        for esquema_id in sorted(self._catalogo):
            candidatos = list(self._catalogo[esquema_id].values())
            if apenas_aprovados:
                candidatos = [item for item in candidatos if item.aprovado]
            if apenas_versao_mais_recente and candidatos:
                candidatos = [max(candidatos, key=lambda item: item.versao)]
            resultado.extend(sorted(candidatos, key=lambda item: item.versao))
        return tuple(resultado)

    def esquemas_aprovados(
        self, *, todas_as_versoes: bool = False
    ) -> tuple[EsquemaDeVinculo, ...]:
        if not isinstance(todas_as_versoes, bool):
            raise TypeError("todas_as_versoes deve ser booleano.")
        return self.esquemas(
            apenas_aprovados=True,
            apenas_versao_mais_recente=not todas_as_versoes,
        )

    def reconhecer(
        self, declaracao: DeclaracaoSemanticaDeVinculo
    ) -> tuple[EsquemaDeVinculo, ...]:
        if not isinstance(declaracao, DeclaracaoSemanticaDeVinculo):
            raise TypeError(
                "declaracao deve ser DeclaracaoSemanticaDeVinculo."
            )
        return tuple(
            esquema
            for esquema in self.esquemas_aprovados()
            if esquema.reconhecer(declaracao)
        )

    def __len__(self) -> int:
        return sum(len(versoes) for versoes in self._catalogo.values())


RegistroDeEsquemas = RegistroDeEsquemasDeVinculo
Registro_de_Esquemas_de_Vinculo = RegistroDeEsquemasDeVinculo


@dataclass(frozen=True)
class ViolacaoDeCardinalidade:
    """Descrição estruturada de um limite excedido."""

    esquema_id: str
    esquema_versao: int
    papel: PapelCardinalidade
    identificador: IdentificadorTecnico
    quantidade: int
    limite: int

    def __post_init__(self) -> None:
        _exigir_texto(self.esquema_id, "esquema_id")
        if (
            isinstance(self.esquema_versao, bool)
            or not isinstance(self.esquema_versao, int)
            or self.esquema_versao < 1
        ):
            raise ValueError("esquema_versao deve ser um inteiro positivo.")
        if not isinstance(self.papel, PapelCardinalidade):
            raise TypeError("papel deve ser PapelCardinalidade.")
        if not isinstance(self.identificador, IdentificadorTecnico):
            raise TypeError("identificador deve ser IdentificadorTecnico.")
        if self.limite < 1 or self.quantidade <= self.limite:
            raise ValueError("violação requer quantidade superior ao limite.")


@dataclass(frozen=True)
class PassoDeVinculo:
    """Uma aresta percorrida, orientada no sentido da travessia."""

    origem: IdentificadorTecnico
    destino: IdentificadorTecnico
    vinculo: VinculoIdentificadores
    sentido_original: bool

    def __post_init__(self) -> None:
        if not isinstance(self.origem, IdentificadorTecnico):
            raise TypeError("origem deve ser IdentificadorTecnico.")
        if not isinstance(self.destino, IdentificadorTecnico):
            raise TypeError("destino deve ser IdentificadorTecnico.")
        if not isinstance(self.vinculo, VinculoIdentificadores):
            raise TypeError("vinculo deve ser VinculoIdentificadores.")
        if not isinstance(self.sentido_original, bool):
            raise TypeError("sentido_original deve ser booleano.")
        extremos_passo = {_identidade(self.origem), _identidade(self.destino)}
        extremos_vinculo = {
            _identidade(self.vinculo.origem),
            _identidade(self.vinculo.destino),
        }
        if extremos_passo != extremos_vinculo:
            raise ValueError("passo e vínculo devem possuir os mesmos extremos.")

    @property
    def evidencia(self) -> Proveniencia:
        return self.vinculo.evidencia


@dataclass(frozen=True)
class CaminhoEvidenciado:
    """Caminho BFS com uma evidência rastreável em cada passo."""

    semente: IdentificadorTecnico
    destino: IdentificadorTecnico
    passos: tuple[PassoDeVinculo, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.semente, IdentificadorTecnico):
            raise TypeError("semente deve ser IdentificadorTecnico.")
        if not isinstance(self.destino, IdentificadorTecnico):
            raise TypeError("destino deve ser IdentificadorTecnico.")
        if not isinstance(self.passos, tuple) or not all(
            isinstance(passo, PassoDeVinculo) for passo in self.passos
        ):
            raise TypeError("passos deve ser uma tupla de PassoDeVinculo.")
        if not self.passos:
            if _identidade(self.semente) != _identidade(self.destino):
                raise ValueError("caminho vazio deve terminar na semente.")
            return
        if _identidade(self.passos[0].origem) != _identidade(self.semente):
            raise ValueError("o primeiro passo deve partir da semente.")
        for anterior, seguinte in zip(self.passos, self.passos[1:]):
            if _identidade(anterior.destino) != _identidade(seguinte.origem):
                raise ValueError("os passos do caminho devem ser contíguos.")
        if _identidade(self.passos[-1].destino) != _identidade(self.destino):
            raise ValueError("o último passo deve alcançar o destino.")

    @property
    def vinculos(self) -> tuple[VinculoIdentificadores, ...]:
        return tuple(passo.vinculo for passo in self.passos)

    @property
    def evidencias(self) -> tuple[Proveniencia, ...]:
        return tuple(passo.evidencia for passo in self.passos)


CaminhoDeVinculos = CaminhoEvidenciado


@dataclass(frozen=True)
class ResultadoTravessia:
    """Fechamento alcançável e caminhos mínimos escolhidos pela BFS."""

    sementes: tuple[IdentificadorTecnico, ...]
    identificadores: tuple[IdentificadorTecnico, ...]
    caminhos: tuple[CaminhoEvidenciado, ...]
    componente_ambiguo: bool = False
    bloqueada_por_ambiguidade: bool = False

    def __post_init__(self) -> None:
        for nome, valores, tipo in (
            ("sementes", self.sementes, IdentificadorTecnico),
            ("identificadores", self.identificadores, IdentificadorTecnico),
            ("caminhos", self.caminhos, CaminhoEvidenciado),
        ):
            if not isinstance(valores, tuple) or not all(
                isinstance(item, tipo) for item in valores
            ):
                raise TypeError(f"{nome} possui tipo inválido.")
        if not isinstance(self.componente_ambiguo, bool):
            raise TypeError("componente_ambiguo deve ser booleano.")
        if not isinstance(self.bloqueada_por_ambiguidade, bool):
            raise TypeError(
                "bloqueada_por_ambiguidade deve ser booleano."
            )
        identificadores = {_identidade(item) for item in self.identificadores}
        if any(_identidade(item) not in identificadores for item in self.sementes):
            raise ValueError("toda semente deve constar nos identificadores.")

    @property
    def nos(self) -> tuple[IdentificadorTecnico, ...]:
        return self.identificadores

    @property
    def vinculos_percorridos(self) -> tuple[VinculoIdentificadores, ...]:
        resultado: list[VinculoIdentificadores] = []
        vistos: set[VinculoIdentificadores] = set()
        for caminho in self.caminhos:
            for vinculo in caminho.vinculos:
                if vinculo not in vistos:
                    vistos.add(vinculo)
                    resultado.append(vinculo)
        return tuple(resultado)

    @property
    def evidencias(self) -> tuple[Proveniencia, ...]:
        return tuple(
            vinculo.evidencia for vinculo in self.vinculos_percorridos
        )

    def caminho_para(
        self, identificador: IdentificadorTecnico
    ) -> CaminhoEvidenciado | None:
        if not isinstance(identificador, IdentificadorTecnico):
            raise TypeError("identificador deve ser IdentificadorTecnico.")
        chave = _identidade(identificador)
        if any(_identidade(semente) == chave for semente in self.sementes):
            semente = next(
                item for item in self.sementes if _identidade(item) == chave
            )
            return CaminhoEvidenciado(semente=semente, destino=semente)
        return next(
            (
                caminho
                for caminho in self.caminhos
                if _identidade(caminho.destino) == chave
            ),
            None,
        )

    def __iter__(self):
        return iter(self.identificadores)

    def __len__(self) -> int:
        return len(self.identificadores)


class GrafoDeVinculos:
    """Grafo aditivo de identificadores e vínculos explicitamente reconhecidos."""

    def __init__(
        self, registro: RegistroDeEsquemasDeVinculo | None = None
    ) -> None:
        if registro is not None and not isinstance(
            registro, RegistroDeEsquemasDeVinculo
        ):
            raise TypeError(
                "registro deve ser RegistroDeEsquemasDeVinculo ou None."
            )
        self._registro = (
            registro
            if registro is not None
            else RegistroDeEsquemasDeVinculo()
        )
        self._ocorrencias: dict[
            ChaveDeIdentificador,
            dict[tuple[object, ...], IdentificadorTecnico],
        ] = {}
        self._arestas_por_chave: dict[
            tuple[object, ...], VinculoIdentificadores
        ] = {}
        self._nos_ambiguos: frozenset[ChaveDeIdentificador] = frozenset()
        self._componentes_ambiguos: tuple[
            frozenset[ChaveDeIdentificador], ...
        ] = ()
        self._violacoes: tuple[ViolacaoDeCardinalidade, ...] = ()

    @property
    def registro(self) -> RegistroDeEsquemasDeVinculo:
        return self._registro

    @property
    def nos(self) -> tuple[IdentificadorTecnico, ...]:
        return tuple(
            self._representante(chave)
            for chave in sorted(self._ocorrencias, key=self._ordem_no)
        )

    @property
    def arestas(self) -> tuple[VinculoIdentificadores, ...]:
        return tuple(
            sorted(self._arestas_por_chave.values(), key=self._ordem_aresta)
        )

    @property
    def vinculos(self) -> tuple[VinculoIdentificadores, ...]:
        return self.arestas

    @property
    def violacoes_cardinalidade(self) -> tuple[ViolacaoDeCardinalidade, ...]:
        return self._violacoes

    @property
    def componentes_ambiguos(
        self,
    ) -> tuple[tuple[IdentificadorTecnico, ...], ...]:
        resultado: list[tuple[IdentificadorTecnico, ...]] = []
        for componente in self._componentes_ambiguos:
            resultado.append(
                tuple(
                    self._representante(chave)
                    for chave in sorted(componente, key=self._ordem_no)
                )
            )
        return tuple(resultado)

    def registrar_esquema(self, esquema: EsquemaDeVinculo) -> None:
        self._registro.registrar(esquema)

    def adicionar_identificador(
        self, identificador: IdentificadorTecnico
    ) -> ChaveDeIdentificador:
        """Adiciona um nó isolado; nunca procura ou cria relação implícita."""

        if not isinstance(identificador, IdentificadorTecnico):
            raise TypeError("identificador deve ser IdentificadorTecnico.")
        chave = ChaveDeIdentificador.de_identificador(identificador)
        ocorrencias = self._ocorrencias.setdefault(chave, {})
        ocorrencias[self._ordem_ocorrencia(identificador)] = identificador
        return chave

    def adicionar_identificadores(
        self, identificadores: Iterable[IdentificadorTecnico]
    ) -> tuple[ChaveDeIdentificador, ...]:
        if isinstance(identificadores, (str, bytes)):
            raise TypeError(
                "identificadores deve ser iterável de IdentificadorTecnico."
            )
        return tuple(
            self.adicionar_identificador(identificador)
            for identificador in identificadores
        )

    def adicionar_declaracao(
        self, declaracao: DeclaracaoSemanticaDeVinculo
    ) -> tuple[VinculoIdentificadores, ...]:
        """Reconhece uma declaração com esquemas aprovados e cria suas arestas.

        Sem reconhecimento, os dois identificadores são mantidos como nós
        independentes e o retorno é vazio. Exceção no reconhecedor ocorre antes
        de qualquer aresta ser adicionada.
        """

        if not isinstance(declaracao, DeclaracaoSemanticaDeVinculo):
            raise TypeError(
                "declaracao deve ser DeclaracaoSemanticaDeVinculo."
            )
        candidatos = tuple(
            vinculo
            for esquema in self._registro.esquemas_aprovados()
            if (vinculo := esquema.criar_vinculo(declaracao)) is not None
        )

        self.adicionar_identificador(declaracao.origem)
        self.adicionar_identificador(declaracao.destino)
        if not candidatos:
            return ()
        return self._adicionar_vinculos_validados(candidatos)

    registrar_declaracao = adicionar_declaracao

    def adicionar_declaracoes(
        self, declaracoes: Iterable[DeclaracaoSemanticaDeVinculo]
    ) -> tuple[VinculoIdentificadores, ...]:
        if isinstance(declaracoes, (str, bytes)):
            raise TypeError(
                "declaracoes deve ser iterável de declarações semânticas."
            )
        chaves: set[tuple[object, ...]] = set()
        for declaracao in declaracoes:
            for vinculo in self.adicionar_declaracao(declaracao):
                chaves.add(self._chave_aresta(vinculo))
        return tuple(
            sorted(
                (self._arestas_por_chave[chave] for chave in chaves),
                key=self._ordem_aresta,
            )
        )

    def adicionar_aresta(
        self,
        vinculo: VinculoIdentificadores,
        *,
        declaracao: DeclaracaoSemanticaDeVinculo,
    ) -> VinculoIdentificadores:
        """Adiciona uma aresta já materializada, sempre revalidando o esquema.

        O parâmetro ``declaracao`` é obrigatório de propósito: não há caminho
        público para inserir uma aresta sem novo reconhecimento aprovado.
        """

        if not isinstance(vinculo, VinculoIdentificadores):
            raise TypeError("vinculo deve ser VinculoIdentificadores.")
        if not isinstance(declaracao, DeclaracaoSemanticaDeVinculo):
            raise TypeError(
                "declaracao deve ser DeclaracaoSemanticaDeVinculo."
            )
        esquema = self._registro.obter_aprovado(
            vinculo.esquema_id, vinculo.esquema_versao
        )
        esperado = esquema.criar_vinculo(declaracao)
        if esperado is None or replace(vinculo, ambiguo=False) != esperado:
            raise ValueError(
                "a aresta não corresponde ao reconhecimento do esquema."
            )
        return self._adicionar_vinculos_validados((esperado,))[0]

    adicionar_vinculo = adicionar_aresta

    def ocorrencias_de(
        self, identificador: IdentificadorTecnico
    ) -> tuple[IdentificadorTecnico, ...]:
        chave = self._chave_no(identificador)
        ocorrencias = self._ocorrencias.get(chave, {})
        return tuple(
            sorted(ocorrencias.values(), key=self._ordem_ocorrencia)
        )

    def eh_ambiguo(self, identificador: IdentificadorTecnico) -> bool:
        return self._chave_no(identificador) in self._nos_ambiguos

    esta_ambiguo = eh_ambiguo

    def pode_sustentar_classificacao(
        self, identificador: IdentificadorTecnico | None = None
    ) -> bool:
        """Indica se o grafo/componente está livre de ambiguidade."""

        if identificador is None:
            return not self._nos_ambiguos
        return not self.eh_ambiguo(identificador)

    def componente_de(
        self, identificador: IdentificadorTecnico
    ) -> tuple[IdentificadorTecnico, ...]:
        chave = self._chave_no(identificador)
        if chave not in self._ocorrencias:
            return (identificador,)
        componente = self._componente(chave, self._adjacencia())
        return tuple(
            self._representante(item)
            for item in sorted(componente, key=self._ordem_no)
        )

    def percorrer_bfs(
        self,
        sementes: IdentificadorTecnico | Iterable[IdentificadorTecnico],
        *,
        incluir_componentes_ambiguos: bool = False,
        somente_arestas_expansiveis: bool = True,
    ) -> ResultadoTravessia:
        """Executa BFS determinística e devolve um caminho evidenciado por nó.

        Por padrão, esta é a expansão segura para cenário: arestas não
        autorizadas e componentes ambíguos ficam fora do fechamento. Para
        auditoria, ``incluir_componentes_ambiguos=True`` permite inspecioná-los,
        sem alterar ``ambiguo`` nas arestas nem torná-los classificáveis.
        """

        if not isinstance(incluir_componentes_ambiguos, bool):
            raise TypeError(
                "incluir_componentes_ambiguos deve ser booleano."
            )
        if not isinstance(somente_arestas_expansiveis, bool):
            raise TypeError(
                "somente_arestas_expansiveis deve ser booleano."
            )
        sementes_normalizadas = self._normalizar_sementes(sementes)
        if not sementes_normalizadas:
            return ResultadoTravessia((), (), ())

        sementes_por_chave = {
            self._chave_no(semente): semente
            for semente in sementes_normalizadas
        }
        chaves_sementes = tuple(
            sorted(sementes_por_chave, key=self._ordem_no_externo)
        )
        visitados = set(chaves_sementes)
        ordem_descoberta = list(chaves_sementes)
        fila: deque[ChaveDeIdentificador] = deque(chaves_sementes)
        pais: dict[
            ChaveDeIdentificador,
            tuple[ChaveDeIdentificador, VinculoIdentificadores],
        ] = {}
        raiz: dict[ChaveDeIdentificador, ChaveDeIdentificador] = {
            chave: chave for chave in chaves_sementes
        }
        adjacencia = self._adjacencia()

        while fila:
            atual = fila.popleft()
            vizinhos = sorted(
                adjacencia.get(atual, ()),
                key=lambda item: self._ordem_vizinho(item[0], item[1]),
            )
            for vizinho, vinculo in vizinhos:
                if (
                    somente_arestas_expansiveis
                    and not vinculo.permite_correlacao
                ):
                    continue
                if not incluir_componentes_ambiguos and vinculo.ambiguo:
                    continue
                if vizinho in visitados:
                    continue
                visitados.add(vizinho)
                ordem_descoberta.append(vizinho)
                pais[vizinho] = (atual, vinculo)
                raiz[vizinho] = raiz[atual]
                fila.append(vizinho)

        identificadores: list[IdentificadorTecnico] = []
        for chave in ordem_descoberta:
            if chave in sementes_por_chave:
                identificadores.append(sementes_por_chave[chave])
            else:
                identificadores.append(self._representante(chave))

        caminhos: list[CaminhoEvidenciado] = []
        for chave in ordem_descoberta:
            if chave in sementes_por_chave:
                continue
            chave_raiz = raiz[chave]
            caminhos.append(
                CaminhoEvidenciado(
                    semente=sementes_por_chave[chave_raiz],
                    destino=self._representante(chave),
                    passos=self._reconstruir_passos(
                        chave,
                        chave_raiz,
                        pais,
                        sementes_por_chave[chave_raiz],
                    ),
                )
            )

        toca_ambiguo = any(chave in self._nos_ambiguos for chave in visitados)
        bloqueada = (
            not incluir_componentes_ambiguos
            and any(chave in self._nos_ambiguos for chave in chaves_sementes)
        )
        return ResultadoTravessia(
            sementes=tuple(
                sementes_por_chave[chave] for chave in chaves_sementes
            ),
            identificadores=tuple(identificadores),
            caminhos=tuple(caminhos),
            componente_ambiguo=toca_ambiguo,
            bloqueada_por_ambiguidade=bloqueada,
        )

    bfs = percorrer_bfs
    expandir = percorrer_bfs

    def inspecionar_componente(
        self, identificador: IdentificadorTecnico
    ) -> ResultadoTravessia:
        return self.percorrer_bfs(
            identificador,
            incluir_componentes_ambiguos=True,
            somente_arestas_expansiveis=False,
        )

    def encontrar_caminho(
        self,
        origem: IdentificadorTecnico,
        destino: IdentificadorTecnico,
        *,
        incluir_componentes_ambiguos: bool = False,
        somente_arestas_expansiveis: bool = True,
    ) -> CaminhoEvidenciado | None:
        if not isinstance(destino, IdentificadorTecnico):
            raise TypeError("destino deve ser IdentificadorTecnico.")
        resultado = self.percorrer_bfs(
            origem,
            incluir_componentes_ambiguos=incluir_componentes_ambiguos,
            somente_arestas_expansiveis=somente_arestas_expansiveis,
        )
        return resultado.caminho_para(destino)

    def _adicionar_vinculos_validados(
        self, vinculos: Iterable[VinculoIdentificadores]
    ) -> tuple[VinculoIdentificadores, ...]:
        chaves_solicitadas: list[tuple[object, ...]] = []
        alterou = False
        for vinculo in vinculos:
            self.adicionar_identificador(vinculo.origem)
            self.adicionar_identificador(vinculo.destino)
            chave = self._chave_aresta(vinculo)
            chaves_solicitadas.append(chave)
            if chave not in self._arestas_por_chave:
                self._arestas_por_chave[chave] = replace(
                    vinculo, ambiguo=False
                )
                alterou = True
        if alterou:
            self._recalcular_ambiguidade()
        return tuple(
            sorted(
                {
                    self._arestas_por_chave[chave]
                    for chave in chaves_solicitadas
                },
                key=self._ordem_aresta,
            )
        )

    def _recalcular_ambiguidade(self) -> None:
        por_esquema: dict[
            tuple[str, int], list[VinculoIdentificadores]
        ] = defaultdict(list)
        for vinculo in self._arestas_por_chave.values():
            por_esquema[(vinculo.esquema_id, vinculo.esquema_versao)].append(
                vinculo
            )

        dados_violacoes: list[
            tuple[
                str,
                int,
                PapelCardinalidade,
                ChaveDeIdentificador,
                int,
                int,
            ]
        ] = []
        chaves_em_violacao: set[ChaveDeIdentificador] = set()

        for (esquema_id, versao), vinculos in sorted(por_esquema.items()):
            esquema = self._registro.obter(esquema_id, versao)
            destinos_por_origem: dict[
                ChaveDeIdentificador, set[ChaveDeIdentificador]
            ] = defaultdict(set)
            origens_por_destino: dict[
                ChaveDeIdentificador, set[ChaveDeIdentificador]
            ] = defaultdict(set)
            for vinculo in vinculos:
                origem = self._chave_no(vinculo.origem)
                destino = self._chave_no(vinculo.destino)
                destinos_por_origem[origem].add(destino)
                origens_por_destino[destino].add(origem)

            limite_destinos = esquema.cardinalidade.max_destinos_por_origem
            if limite_destinos is not None:
                for origem, destinos in destinos_por_origem.items():
                    if len(destinos) > limite_destinos:
                        chaves_em_violacao.add(origem)
                        dados_violacoes.append(
                            (
                                esquema_id,
                                versao,
                                PapelCardinalidade.ORIGEM,
                                origem,
                                len(destinos),
                                limite_destinos,
                            )
                        )

            limite_origens = esquema.cardinalidade.max_origens_por_destino
            if limite_origens is not None:
                for destino, origens in origens_por_destino.items():
                    if len(origens) > limite_origens:
                        chaves_em_violacao.add(destino)
                        dados_violacoes.append(
                            (
                                esquema_id,
                                versao,
                                PapelCardinalidade.DESTINO,
                                destino,
                                len(origens),
                                limite_origens,
                            )
                        )

        adjacencia = self._adjacencia()
        componentes: list[frozenset[ChaveDeIdentificador]] = []
        pendentes = set(self._ocorrencias)
        while pendentes:
            inicio = min(pendentes, key=self._ordem_no)
            componente = frozenset(self._componente(inicio, adjacencia))
            componentes.append(componente)
            pendentes.difference_update(componente)

        ambiguos = tuple(
            componente
            for componente in componentes
            if componente.intersection(chaves_em_violacao)
        )
        ambiguos = tuple(
            sorted(
                ambiguos,
                key=lambda componente: self._ordem_no(
                    min(componente, key=self._ordem_no)
                ),
            )
        )
        nos_ambiguos = frozenset().union(*ambiguos) if ambiguos else frozenset()

        atualizadas: dict[tuple[object, ...], VinculoIdentificadores] = {}
        for chave, vinculo in self._arestas_por_chave.items():
            origem = self._chave_no(vinculo.origem)
            atualizadas[chave] = replace(
                vinculo,
                ambiguo=origem in nos_ambiguos,
            )
        self._arestas_por_chave = atualizadas
        self._nos_ambiguos = nos_ambiguos
        self._componentes_ambiguos = ambiguos

        violacoes = [
            ViolacaoDeCardinalidade(
                esquema_id=esquema_id,
                esquema_versao=versao,
                papel=papel,
                identificador=self._representante(chave),
                quantidade=quantidade,
                limite=limite,
            )
            for esquema_id, versao, papel, chave, quantidade, limite in dados_violacoes
        ]
        self._violacoes = tuple(
            sorted(
                violacoes,
                key=lambda item: (
                    item.esquema_id,
                    item.esquema_versao,
                    item.papel.value,
                    self._ordem_no(self._chave_no(item.identificador)),
                ),
            )
        )

    def _adjacencia(
        self,
    ) -> dict[
        ChaveDeIdentificador,
        list[tuple[ChaveDeIdentificador, VinculoIdentificadores]],
    ]:
        resultado: dict[
            ChaveDeIdentificador,
            list[tuple[ChaveDeIdentificador, VinculoIdentificadores]],
        ] = {chave: [] for chave in self._ocorrencias}
        for vinculo in self._arestas_por_chave.values():
            origem = self._chave_no(vinculo.origem)
            destino = self._chave_no(vinculo.destino)
            resultado.setdefault(origem, []).append((destino, vinculo))
            resultado.setdefault(destino, []).append((origem, vinculo))
        return resultado

    @staticmethod
    def _componente(
        inicio: ChaveDeIdentificador,
        adjacencia: dict[
            ChaveDeIdentificador,
            list[tuple[ChaveDeIdentificador, VinculoIdentificadores]],
        ],
    ) -> set[ChaveDeIdentificador]:
        visitados = {inicio}
        fila = deque((inicio,))
        while fila:
            atual = fila.popleft()
            for vizinho, _ in adjacencia.get(atual, ()):
                if vizinho not in visitados:
                    visitados.add(vizinho)
                    fila.append(vizinho)
        return visitados

    def _reconstruir_passos(
        self,
        destino: ChaveDeIdentificador,
        raiz: ChaveDeIdentificador,
        pais: dict[
            ChaveDeIdentificador,
            tuple[ChaveDeIdentificador, VinculoIdentificadores],
        ],
        semente: IdentificadorTecnico,
    ) -> tuple[PassoDeVinculo, ...]:
        segmentos: list[
            tuple[
                ChaveDeIdentificador,
                ChaveDeIdentificador,
                VinculoIdentificadores,
            ]
        ] = []
        atual = destino
        while atual != raiz:
            anterior, vinculo = pais[atual]
            segmentos.append((anterior, atual, vinculo))
            atual = anterior
        segmentos.reverse()

        passos: list[PassoDeVinculo] = []
        for indice, (anterior, atual, vinculo) in enumerate(segmentos):
            origem = semente if indice == 0 else self._representante(anterior)
            destino_identificador = self._representante(atual)
            sentido_original = self._chave_no(vinculo.origem) == anterior
            passos.append(
                PassoDeVinculo(
                    origem=origem,
                    destino=destino_identificador,
                    vinculo=vinculo,
                    sentido_original=sentido_original,
                )
            )
        return tuple(passos)

    def _normalizar_sementes(
        self,
        sementes: IdentificadorTecnico | Iterable[IdentificadorTecnico],
    ) -> tuple[IdentificadorTecnico, ...]:
        if isinstance(sementes, IdentificadorTecnico):
            candidatos = (sementes,)
        else:
            if isinstance(sementes, (str, bytes)):
                raise TypeError(
                    "sementes deve conter IdentificadorTecnico."
                )
            try:
                candidatos = tuple(sementes)
            except TypeError as erro:
                raise TypeError(
                    "sementes deve ser IdentificadorTecnico ou iterável."
                ) from erro
        if not all(
            isinstance(item, IdentificadorTecnico) for item in candidatos
        ):
            raise TypeError("sementes deve conter IdentificadorTecnico.")

        por_chave: dict[ChaveDeIdentificador, IdentificadorTecnico] = {}
        for identificador in candidatos:
            chave = self._chave_no(identificador)
            existente = por_chave.get(chave)
            if existente is None or self._ordem_ocorrencia(
                identificador
            ) < self._ordem_ocorrencia(existente):
                por_chave[chave] = identificador
        return tuple(
            por_chave[chave]
            for chave in sorted(por_chave, key=self._ordem_no_externo)
        )

    def _representante(
        self, chave: ChaveDeIdentificador
    ) -> IdentificadorTecnico:
        return min(
            self._ocorrencias[chave].values(),
            key=self._ordem_ocorrencia,
        )

    @staticmethod
    def _chave_no(
        identificador: IdentificadorTecnico,
    ) -> ChaveDeIdentificador:
        return ChaveDeIdentificador.de_identificador(identificador)

    @staticmethod
    def _ordem_ocorrencia(
        identificador: IdentificadorTecnico,
    ) -> tuple[object, ...]:
        chave = ChaveDeIdentificador.de_identificador(identificador)
        return (
            identificador.tipo.value,
            chave.digest,
            *_ordem_proveniencia(identificador.proveniencia),
            identificador.nome_campo,
            identificador.namespace_comparacao,
            identificador.valor_normalizado,
        )

    def _ordem_no(
        self, chave: ChaveDeIdentificador
    ) -> tuple[object, ...]:
        representante = self._representante(chave)
        return (
            chave.tipo.value,
            chave.digest,
            representante.proveniencia.entrada_id,
            representante.proveniencia.arquivo_token,
            chave.namespace_comparacao,
            chave.valor_normalizado,
        )

    @staticmethod
    def _ordem_no_externo(
        chave: ChaveDeIdentificador,
    ) -> tuple[object, ...]:
        return (
            chave.tipo.value,
            chave.digest,
            chave.namespace_comparacao,
            chave.valor_normalizado,
        )

    def _ordem_vizinho(
        self,
        vizinho: ChaveDeIdentificador,
        vinculo: VinculoIdentificadores,
    ) -> tuple[object, ...]:
        return (
            vizinho.tipo.value,
            vizinho.digest,
            vinculo.evidencia.entrada_id,
            vinculo.esquema_id,
            vinculo.esquema_versao,
            vinculo.tipo_relacao,
            *_ordem_proveniencia(vinculo.evidencia),
            self._ordem_no_externo(vizinho),
        )

    def _ordem_aresta(
        self, vinculo: VinculoIdentificadores
    ) -> tuple[object, ...]:
        return (
            self._ordem_no_externo(self._chave_no(vinculo.origem)),
            self._ordem_no_externo(self._chave_no(vinculo.destino)),
            vinculo.evidencia.entrada_id,
            vinculo.esquema_id,
            vinculo.esquema_versao,
            vinculo.tipo_relacao,
            *_ordem_proveniencia(vinculo.evidencia),
        )

    def _chave_aresta(
        self, vinculo: VinculoIdentificadores
    ) -> tuple[object, ...]:
        return (
            self._chave_no(vinculo.origem),
            self._chave_no(vinculo.destino),
            vinculo.tipo_relacao,
            vinculo.esquema_id,
            vinculo.esquema_versao,
            _ordem_proveniencia(vinculo.evidencia),
        )

    def __len__(self) -> int:
        return len(self._ocorrencias)
