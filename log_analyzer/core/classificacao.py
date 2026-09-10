"""Classificação de cenário por regras autorizadas, total e fail-closed.

O classificador recebe somente o snapshot imutável do catálogo e o contexto
estruturado da DSL. Texto original, mensagem e severidade não participam da
decisão. Uma conclusão é emitida apenas quando uma regra declarada ``ACTIVE``
também consta entre as identidades autorizadas pelo validador do catálogo e
todos os seus predicados são satisfeitos.

Catálogo ausente ou inconsistente, ambiguidade, conflito de precedência,
avaliação parcial e qualquer erro da DSL produzem o mesmo resultado seguro:
``Categoria.NAO_CLASSIFICADA``, sem regra ou evidência parcial. A causa-raiz só
é determinada quando a própria regra ativa selecionada declara uma causa
causal validada.

Requirements: 10.3, 10.4, 10.5, 10.6, 11.2, 11.5, 13.1, 13.2,
13.5, 13.7, 17.4, 17.6
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Final

from log_analyzer.core.catalogo import (
    CatalogoDeRegras,
    CondicaoRegra,
    EstadoRegra,
    PrecedenciaRegra,
    RegraValidada,
)
from log_analyzer.core.dsl_regras import (
    AvaliadorDSL,
    ContextoAvaliacaoDSL,
    EstadoAvaliacaoDSL,
    ReferenciaCondicaoSatisfeita,
    ReferenciaEvidenciaDSL,
    ResultadoAvaliacaoDSL,
)
from log_analyzer.core.modelos import (
    Categoria,
    EstadoCausaRaiz,
    ReferenciaRegra,
    ResultadoCausaRaiz,
)


SEM_CATALOGO_ATIVO: Final = "sem-catalogo-ativo"

_ID_RE: Final = re.compile(r"[A-Za-z][A-Za-z0-9._:-]{0,127}\Z")
_APPLICATION_RE: Final = re.compile(r"[A-Z][A-Z0-9_]{0,31}\Z")
_DIGEST_RE: Final = re.compile(r"[0-9a-fA-F]{64}\Z")


@dataclass(frozen=True, slots=True)
class ResultadoClassificacaoCenario:
    """Decisão imutável, explicável e sem correspondências parciais.

    ``evidencias`` preserva a associação entre cada seletor de evidência da
    regra e as referências estruturais produzidas pela DSL. Os valores de
    campos e identificadores usados na comparação não fazem parte do modelo.
    """

    categoria_de_cenario: Categoria
    regra_aplicada: ReferenciaRegra | None = None
    condicoes_satisfeitas: tuple[str, ...] = ()
    evidencias: tuple[ReferenciaCondicaoSatisfeita, ...] = field(
        default=(), repr=False
    )
    causa_raiz: ResultadoCausaRaiz = field(
        default_factory=ResultadoCausaRaiz
    )
    versao_catalogo: str = SEM_CATALOGO_ATIVO

    def __post_init__(self) -> None:
        if not isinstance(self.categoria_de_cenario, Categoria):
            raise TypeError("categoria_de_cenario deve ser Categoria.")
        if self.regra_aplicada is not None and not isinstance(
            self.regra_aplicada, ReferenciaRegra
        ):
            raise TypeError(
                "regra_aplicada deve ser ReferenciaRegra ou None."
            )
        if not isinstance(self.condicoes_satisfeitas, tuple) or not all(
            isinstance(item, str) and _ID_RE.fullmatch(item) is not None
            for item in self.condicoes_satisfeitas
        ):
            raise TypeError(
                "condicoes_satisfeitas deve conter identificadores seguros."
            )
        if len(self.condicoes_satisfeitas) != len(
            set(self.condicoes_satisfeitas)
        ):
            raise ValueError(
                "condicoes_satisfeitas não pode conter duplicatas."
            )
        if not isinstance(self.evidencias, tuple) or not all(
            isinstance(item, ReferenciaCondicaoSatisfeita)
            for item in self.evidencias
        ):
            raise TypeError(
                "evidencias deve conter ReferenciaCondicaoSatisfeita."
            )
        if len(self.evidencias) != len(set(self.evidencias)):
            raise ValueError("evidencias não pode conter duplicatas.")
        if not isinstance(self.causa_raiz, ResultadoCausaRaiz):
            raise TypeError("causa_raiz deve ser ResultadoCausaRaiz.")
        if (
            not isinstance(self.versao_catalogo, str)
            or _ID_RE.fullmatch(self.versao_catalogo) is None
        ):
            raise ValueError("versao_catalogo inválida.")

        classificada = (
            self.categoria_de_cenario is not Categoria.NAO_CLASSIFICADA
        )
        if not classificada:
            if self.regra_aplicada is not None:
                raise ValueError(
                    "cenário não classificado não pode declarar regra."
                )
            if self.condicoes_satisfeitas or self.evidencias:
                raise ValueError(
                    "cenário não classificado não pode expor match parcial."
                )
            if self.causa_raiz != ResultadoCausaRaiz():
                raise ValueError(
                    "cenário não classificado requer causa não determinada."
                )
            return

        if self.regra_aplicada is None:
            raise ValueError("classificação requer regra aplicada.")
        if not self.condicoes_satisfeitas:
            raise ValueError("classificação requer condições satisfeitas.")
        if not self.evidencias:
            raise ValueError("classificação requer evidências estruturais.")
        if self.regra_aplicada.catalogo_versao != self.versao_catalogo:
            raise ValueError(
                "versao_catalogo deve corresponder à regra aplicada."
            )

        condicoes = set(self.condicoes_satisfeitas)
        if any(
            evidencia.condicao_id not in condicoes
            for evidencia in self.evidencias
        ):
            raise ValueError(
                "evidência deve corresponder a uma condição satisfeita."
            )

        if self.causa_raiz.estado is EstadoCausaRaiz.DETERMINADA:
            if self.categoria_de_cenario is not Categoria.ERRO:
                raise ValueError(
                    "causa-raiz determinada requer categoria ERRO."
                )
            if self.causa_raiz.regra != self.regra_aplicada:
                raise ValueError(
                    "causa-raiz deve usar a regra causal selecionada."
                )
        elif self.causa_raiz != ResultadoCausaRaiz():
            raise ValueError(
                "ausência de regra causal requer causa não determinada."
            )

    @property
    def categoria(self) -> Categoria:
        return self.categoria_de_cenario

    @property
    def regra(self) -> ReferenciaRegra | None:
        return self.regra_aplicada

    @property
    def referencia_regra(self) -> ReferenciaRegra | None:
        return self.regra_aplicada

    @property
    def condicoes(self) -> tuple[str, ...]:
        return self.condicoes_satisfeitas

    @property
    def referencias_satisfeitas(
        self,
    ) -> tuple[ReferenciaCondicaoSatisfeita, ...]:
        return self.evidencias

    @property
    def referencias_evidencia(
        self,
    ) -> tuple[ReferenciaEvidenciaDSL, ...]:
        """Achata referências concretas sem perder a ordem determinística."""

        unicas: list[ReferenciaEvidenciaDSL] = []
        for cobertura in self.evidencias:
            for referencia in cobertura.evidencias:
                if referencia not in unicas:
                    unicas.append(referencia)
        return tuple(unicas)

    @property
    def classificada(self) -> bool:
        return self.categoria_de_cenario is not Categoria.NAO_CLASSIFICADA

    @property
    def correspondencia_integral(self) -> bool:
        return self.classificada

    # Aliases em inglês para consumidores que usam os nomes do catálogo JSON.
    @property
    def category(self) -> Categoria:
        return self.categoria_de_cenario

    @property
    def rule(self) -> ReferenciaRegra | None:
        return self.regra_aplicada

    @property
    def conditions(self) -> tuple[str, ...]:
        return self.condicoes_satisfeitas

    @property
    def evidence(self) -> tuple[ReferenciaCondicaoSatisfeita, ...]:
        return self.evidencias

    @property
    def root_cause(self) -> ResultadoCausaRaiz:
        return self.causa_raiz

    @property
    def catalog_version(self) -> str:
        return self.versao_catalogo


# Nomes alternativos mantêm o contrato fácil de descobrir sem criar estado.
ResultadoClassificacao = ResultadoClassificacaoCenario
ResultadoDeClassificacao = ResultadoClassificacaoCenario


@dataclass(frozen=True, slots=True)
class _CatalogoPreparado:
    versao: str
    regras: tuple[RegraValidada, ...]


@dataclass(frozen=True, slots=True)
class _CorrespondenciaIntegral:
    regra: RegraValidada
    condicoes: tuple[str, ...]
    evidencias: tuple[ReferenciaCondicaoSatisfeita, ...]


class ClassificadorDeCenario:
    """Seleciona uma regra integralmente satisfeita ou falha fechado.

    O catálogo pode ser fornecido no construtor ou em ``classificar``. Um
    snapshot apenas estrutural, ainda sem identidades autorizadas, é aceito,
    mas não possui regras elegíveis e portanto não classifica.
    """

    def __init__(
        self,
        catalogo: object | None = None,
        *,
        avaliador: AvaliadorDSL | None = None,
    ) -> None:
        self._catalogo = catalogo
        if avaliador is None:
            self._avaliador: AvaliadorDSL | None = AvaliadorDSL()
        elif isinstance(avaliador, AvaliadorDSL):
            self._avaliador = avaliador
        else:
            # Dependência inválida também permanece fail-closed na avaliação.
            self._avaliador = None

    @property
    def catalogo(self) -> CatalogoDeRegras | None:
        return (
            self._catalogo
            if isinstance(self._catalogo, CatalogoDeRegras)
            else None
        )

    def classificar(
        self,
        contexto: object,
        catalogo: object | None = None,
    ) -> ResultadoClassificacaoCenario:
        """Classifica sem propagar exceções nem correspondências parciais."""

        catalogo_efetivo = self._catalogo if catalogo is None else catalogo
        preparado = _preparar_catalogo(catalogo_efetivo)
        if preparado is None:
            return _nao_classificada()

        sem_match = _nao_classificada(preparado.versao)
        if self._avaliador is None or not isinstance(
            contexto, ContextoAvaliacaoDSL
        ):
            return sem_match

        try:
            # Componentes ambíguos nunca sustentam nenhuma classificação.
            if any(vinculo.ambiguo for vinculo in contexto.vinculos):
                return sem_match

            correspondencias: list[_CorrespondenciaIntegral] = []
            aplicacoes = set(contexto.aplicacoes_presentes)
            for regra in preparado.regras:
                # Toda regra autorizada é totalizada, mesmo quando seu escopo
                # de Aplicações não está presente. Assim, uma regra ativa
                # malformada nunca fica oculta por um cenário parcial.
                resultado = self._avaliador.avaliar_condicoes(
                    regra.condicoes, contexto
                )
                if not isinstance(resultado, ResultadoAvaliacaoDSL):
                    return sem_match
                if resultado.estado is EstadoAvaliacaoDSL.ERRO_SEGURO:
                    return sem_match
                if not set(regra.aplicacoes).issubset(aplicacoes):
                    continue
                if resultado.estado is EstadoAvaliacaoDSL.NAO_SATISFEITA:
                    continue
                if resultado.estado is not EstadoAvaliacaoDSL.SATISFEITA:
                    return sem_match

                integral = _materializar_correspondencia(regra, resultado)
                if integral is None:
                    return sem_match
                correspondencias.append(integral)

            if not correspondencias:
                return sem_match

            escolhida = min(
                correspondencias,
                key=lambda item: (
                    item.regra.precedencia,
                    item.regra.rule_id,
                    item.regra.versao,
                ),
            )
            referencia = ReferenciaRegra(
                rule_id=escolhida.regra.rule_id,
                versao=escolhida.regra.versao,
                catalogo_versao=preparado.versao,
            )
            causa_raiz = ResultadoCausaRaiz()
            if escolhida.regra.causa_raiz is not None:
                causa_raiz = ResultadoCausaRaiz(
                    estado=EstadoCausaRaiz.DETERMINADA,
                    descricao_sanitizada=escolhida.regra.causa_raiz,
                    regra=referencia,
                )

            return ResultadoClassificacaoCenario(
                categoria_de_cenario=escolhida.regra.categoria,
                regra_aplicada=referencia,
                condicoes_satisfeitas=escolhida.condicoes,
                evidencias=escolhida.evidencias,
                causa_raiz=causa_raiz,
                versao_catalogo=preparado.versao,
            )
        except Exception:
            # Dados do cenário ou do catálogo nunca atravessam esta fronteira.
            return sem_match

    avaliar = classificar
    classificar_cenario = classificar


ClassificadorCenario = ClassificadorDeCenario


def classificar_cenario(
    catalogo: object,
    contexto: object,
    *,
    avaliador: AvaliadorDSL | None = None,
) -> ResultadoClassificacaoCenario:
    """Atalho funcional para classificação integral e fail-closed."""

    return ClassificadorDeCenario(
        catalogo, avaliador=avaliador
    ).classificar(contexto)


def _nao_classificada(
    versao_catalogo: str = SEM_CATALOGO_ATIVO,
) -> ResultadoClassificacaoCenario:
    return ResultadoClassificacaoCenario(
        categoria_de_cenario=Categoria.NAO_CLASSIFICADA,
        versao_catalogo=versao_catalogo,
    )


def _preparar_catalogo(catalogo: object) -> _CatalogoPreparado | None:
    """Confere os invariantes consumidos sem reexecutar gates de governança."""

    if not isinstance(catalogo, CatalogoDeRegras):
        return None
    try:
        if (
            catalogo.schema_version != 1
            or _ID_RE.fullmatch(catalogo.versao) is None
            or _DIGEST_RE.fullmatch(catalogo.digest_sha256) is None
            or not isinstance(catalogo.regras, tuple)
            or not all(
                isinstance(regra, RegraValidada)
                for regra in catalogo.regras
            )
        ):
            return None

        identidades = tuple(
            (regra.rule_id, regra.versao) for regra in catalogo.regras
        )
        if len(identidades) != len(set(identidades)):
            return None
        identidades_set = set(identidades)

        if not isinstance(catalogo.precedencia, tuple) or not all(
            isinstance(item, PrecedenciaRegra)
            for item in catalogo.precedencia
        ):
            return None
        precedencia: dict[tuple[str, int], int] = {}
        for item in catalogo.precedencia:
            identidade = (item.rule_id, item.versao)
            if identidade in precedencia or identidade not in identidades_set:
                return None
            if type(item.ordem) is not int or item.ordem < 0:
                return None
            precedencia[identidade] = item.ordem
        if set(precedencia) != identidades_set:
            return None

        for regra in catalogo.regras:
            if not _regra_estruturalmente_valida(regra):
                return None
            if precedencia[(regra.rule_id, regra.versao)] != regra.precedencia:
                return None

        autorizadas_raw = catalogo.regras_autorizadas
        if not isinstance(autorizadas_raw, tuple):
            return None
        autorizadas: set[tuple[str, int]] = set()
        for identidade in autorizadas_raw:
            if (
                not isinstance(identidade, tuple)
                or len(identidade) != 2
                or not isinstance(identidade[0], str)
                or type(identidade[1]) is not int
                or identidade not in identidades_set
                or identidade in autorizadas
            ):
                return None
            autorizadas.add(identidade)

        declaradas_ativas = {
            (regra.rule_id, regra.versao)
            for regra in catalogo.regras
            if regra.estado is EstadoRegra.ACTIVE
        }
        # Vazio representa catálogo apenas carregado, ainda não publicado. Se
        # há alguma autorização, a publicação deve ser integral e atômica.
        if autorizadas and autorizadas != declaradas_ativas:
            return None

        regras_ativas = tuple(
            regra
            for regra in catalogo.regras
            if (regra.rule_id, regra.versao) in autorizadas
            and regra.estado is EstadoRegra.ACTIVE
        )
        ordens = tuple(regra.precedencia for regra in regras_ativas)
        if len(ordens) != len(set(ordens)):
            return None
        if any(
            regra.categoria is Categoria.NAO_CLASSIFICADA
            or (
                regra.causa_raiz is not None
                and regra.categoria is not Categoria.ERRO
            )
            for regra in regras_ativas
        ):
            return None

        return _CatalogoPreparado(
            versao=catalogo.versao,
            regras=tuple(
                sorted(
                    regras_ativas,
                    key=lambda regra: (
                        regra.precedencia,
                        regra.rule_id,
                        regra.versao,
                    ),
                )
            ),
        )
    except Exception:
        return None


def _regra_estruturalmente_valida(regra: RegraValidada) -> bool:
    if (
        _ID_RE.fullmatch(regra.rule_id) is None
        or type(regra.versao) is not int
        or regra.versao < 1
        or not isinstance(regra.categoria, Categoria)
        or not isinstance(regra.estado, EstadoRegra)
        or type(regra.precedencia) is not int
        or regra.precedencia < 0
        or _DIGEST_RE.fullmatch(regra.digest_historico) is None
    ):
        return False
    if (
        not isinstance(regra.aplicacoes, tuple)
        or not regra.aplicacoes
        or any(
            not isinstance(item, str)
            or _APPLICATION_RE.fullmatch(item) is None
            for item in regra.aplicacoes
        )
        or len(regra.aplicacoes) != len(set(regra.aplicacoes))
    ):
        return False
    if (
        not isinstance(regra.condicoes, tuple)
        or not regra.condicoes
        or not all(
            isinstance(item, CondicaoRegra)
            and _ID_RE.fullmatch(item.condition_id) is not None
            and _ID_RE.fullmatch(item.operator) is not None
            and isinstance(item.parametros, tuple)
            for item in regra.condicoes
        )
    ):
        return False
    condicoes = tuple(item.condition_id for item in regra.condicoes)
    if len(condicoes) != len(set(condicoes)):
        return False
    if (
        not isinstance(regra.seletores_evidencia, tuple)
        or not regra.seletores_evidencia
        or len(regra.seletores_evidencia)
        != len(set(regra.seletores_evidencia))
        or not set(regra.seletores_evidencia).issubset(condicoes)
    ):
        return False
    if (
        not isinstance(regra.fixture_ids, tuple)
        or not isinstance(regra.fixture_digests, tuple)
        or len(regra.fixture_ids) != len(regra.fixture_digests)
        or len(regra.fixture_ids) != len(set(regra.fixture_ids))
        or any(_ID_RE.fullmatch(item) is None for item in regra.fixture_ids)
        or any(
            _DIGEST_RE.fullmatch(item) is None
            for item in regra.fixture_digests
        )
    ):
        return False
    if regra.estado is not EstadoRegra.DRAFT and not regra.fixture_ids:
        return False
    if (
        not isinstance(regra.aprovado_por, str)
        or not regra.aprovado_por.strip()
        or not isinstance(regra.referencia_aprovacao, str)
        or not regra.referencia_aprovacao.strip()
        or not isinstance(regra.aprovado_em, datetime)
        or regra.aprovado_em.tzinfo is None
        or regra.aprovado_em.utcoffset() is None
    ):
        return False
    if regra.causa_raiz is not None and (
        not isinstance(regra.causa_raiz, str)
        or _ID_RE.fullmatch(regra.causa_raiz) is None
    ):
        return False
    return True


def _materializar_correspondencia(
    regra: RegraValidada,
    resultado: ResultadoAvaliacaoDSL,
) -> _CorrespondenciaIntegral | None:
    esperados = {
        condicao.condition_id: condicao.operator
        for condicao in regra.condicoes
    }
    resultados = resultado.resultados
    if (
        len(resultados) != len(esperados)
        or any(
            item.estado is not EstadoAvaliacaoDSL.SATISFEITA
            or esperados.get(item.condicao_id) != item.operador
            for item in resultados
        )
        or {item.condicao_id for item in resultados} != set(esperados)
    ):
        return None

    referencias = resultado.referencias_satisfeitas
    if (
        len(referencias) != len(esperados)
        or {item.condicao_id for item in referencias} != set(esperados)
        or any(
            esperados.get(item.condicao_id) != item.operador
            for item in referencias
        )
    ):
        return None

    por_condicao = {item.condicao_id: item for item in referencias}
    seletores = tuple(sorted(regra.seletores_evidencia))
    evidencias = tuple(por_condicao[item] for item in seletores)
    if not evidencias:
        return None

    return _CorrespondenciaIntegral(
        regra=regra,
        condicoes=tuple(sorted(esperados)),
        evidencias=evidencias,
    )


__all__ = [
    "ClassificadorCenario",
    "ClassificadorDeCenario",
    "ResultadoClassificacao",
    "ResultadoClassificacaoCenario",
    "ResultadoDeClassificacao",
    "SEM_CATALOGO_ATIVO",
    "classificar_cenario",
]
