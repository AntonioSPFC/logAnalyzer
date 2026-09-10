"""Gates fail-closed para ativação e publicação do catálogo de regras.

O carregamento estrutural permanece em :mod:`log_analyzer.core.catalogo`.
Este módulo decide quais regras declaradas como ``ACTIVE`` podem ser expostas
como efetivamente ativas. A decisão usa apenas modelos imutáveis, resultados da
governança de fixtures e a DSL fechada; nenhum conteúdo do catálogo é executado.

A validação é deliberadamente separada da leitura de arquivos. Assim, o
pipeline pode produzir provas de fixtures em diretórios temporários controlados
e entregar somente digests, metadados estruturados e contextos da DSL.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
import hmac
import re
from typing import Final

from log_analyzer.core.catalogo import (
    CatalogoDeRegras,
    EstadoRegra,
    RegraValidada,
)
from log_analyzer.core.dsl_regras import (
    AvaliadorDSL,
    ContextoAvaliacaoDSL,
    EstadoAvaliacaoDSL,
)
from log_analyzer.core.excecoes import ErroDeCatalogo
from log_analyzer.core.governanca import ResultadoGovernanca
from log_analyzer.core.modelos import Categoria


_ID_RE: Final = re.compile(r"[A-Za-z][A-Za-z0-9._:-]{0,127}\Z")
_DIMENSAO_RE: Final = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,127}\Z")
_DIGEST_RE: Final = re.compile(r"[0-9a-fA-F]{64}\Z")


class CodigoValidacaoCatalogo(str, Enum):
    """Códigos constantes; nenhum incorpora dados de catálogo ou fixture."""

    ATIVACAO_SEM_EVIDENCIA = "CATALOG_ACTIVATION_EVIDENCE_REQUIRED"
    COBERTURA_INCOMPLETA = "CATALOG_CONDITION_COVERAGE_ERROR"
    FIXTURE_NAO_GOVERNADA = "CATALOG_FIXTURE_GOVERNANCE_ERROR"
    POLITICA_DE_AMOSTRAS = "CATALOG_SAMPLE_POLICY_ERROR"
    AVALIACAO_DE_EXEMPLO = "CATALOG_EXAMPLE_EVALUATION_ERROR"
    APROVACAO_INCOMPLETA = "CATALOG_APPROVAL_ERROR"
    REFERENCIA_INVALIDA = "CATALOG_REFERENCE_ERROR"
    DIGEST_INVALIDO = "CATALOG_DIGEST_ERROR"
    PRECEDENCIA_CONFLITANTE = "CATALOG_PRECEDENCE_ERROR"
    ERRO_SEM_EXEMPLO = "CATALOG_ERROR_RULE_WITHOUT_SAMPLE"
    CAUSA_RAIZ_SEM_EXEMPLO = "CATALOG_ROOT_CAUSE_WITHOUT_SAMPLE"
    HISTORICO_INVALIDO = "CATALOG_HISTORY_ERROR"
    VERSAO_INVALIDA = "CATALOG_VERSION_ERROR"
    VALIDACAO_FALHOU = "CATALOG_VALIDATION_ERROR"


@dataclass(frozen=True, slots=True, order=True)
class ReferenciaVersaoRegra:
    """Identidade estável e versionada usada pelo pacote de ativação."""

    rule_id: str
    versao: int

    def __post_init__(self) -> None:
        _validar_id(self.rule_id, "rule_id")
        _validar_inteiro_positivo(self.versao, "versao")

    @property
    def version(self) -> int:
        return self.versao


@dataclass(frozen=True, slots=True)
class PoliticaDeAmostras:
    """Quantidade e diversidade mínimas declaradas para uma regra.

    ``dimensoes_diversidade`` nomeia dimensões estruturais, por exemplo perfil
    de parser ou origem sintética. Os valores são opacos e nunca aparecem em
    diagnósticos. Todas as dimensões usam o mesmo mínimo de valores distintos.
    """

    quantidade_minima: int
    dimensoes_diversidade: tuple[str, ...]
    minimo_distintos_por_dimensao: int = 1

    def __post_init__(self) -> None:
        _validar_inteiro_positivo(
            self.quantidade_minima, "quantidade_minima"
        )
        _validar_inteiro_positivo(
            self.minimo_distintos_por_dimensao,
            "minimo_distintos_por_dimensao",
        )
        if (
            not isinstance(self.dimensoes_diversidade, tuple)
            or not self.dimensoes_diversidade
        ):
            raise ValueError(
                "dimensoes_diversidade deve ser uma tupla não vazia."
            )
        for dimensao in self.dimensoes_diversidade:
            if (
                not isinstance(dimensao, str)
                or _DIMENSAO_RE.fullmatch(dimensao) is None
            ):
                raise ValueError("Dimensão de diversidade inválida.")
        if len(self.dimensoes_diversidade) != len(
            set(self.dimensoes_diversidade)
        ):
            raise ValueError("Dimensões de diversidade devem ser únicas.")

    @property
    def minimum_examples(self) -> int:
        return self.quantidade_minima

    @property
    def diversity_dimensions(self) -> tuple[str, ...]:
        return self.dimensoes_diversidade


PoliticaAmostras = PoliticaDeAmostras


@dataclass(frozen=True, slots=True)
class CoberturaDeCondicao:
    """Declara quais fixtures demonstram uma condição específica."""

    condicao_id: str
    fixture_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _validar_id(self.condicao_id, "condicao_id")
        if not isinstance(self.fixture_ids, tuple) or not self.fixture_ids:
            raise ValueError("fixture_ids deve ser uma tupla não vazia.")
        for fixture_id in self.fixture_ids:
            _validar_id(fixture_id, "fixture_id")
        if len(self.fixture_ids) != len(set(self.fixture_ids)):
            raise ValueError("fixture_ids deve conter referências únicas.")

    @property
    def condition_id(self) -> str:
        return self.condicao_id


@dataclass(frozen=True, slots=True)
class ExemploRotuladoCatalogo:
    """Prova transitória de um exemplo sanitizado e governado.

    O digest é calculado pelo chamador sobre o artefato governado e comparado
    às duas referências declarativas do catálogo. ``diversidade`` contém pares
    ``(dimensão, valor opaco)``. ``regras_aplicaveis`` permite declarar escopo;
    quando vazio, a aplicabilidade é inferida exclusivamente pelas aplicações
    estruturadas do contexto.
    """

    fixture_id: str
    digest_sha256: str
    rotulo: Categoria
    contexto: ContextoAvaliacaoDSL
    governanca: ResultadoGovernanca
    diversidade: tuple[tuple[str, str], ...]
    aplicacoes: tuple[str, ...] = ()
    regras_aplicaveis: tuple[ReferenciaVersaoRegra, ...] = ()

    def __post_init__(self) -> None:
        _validar_id(self.fixture_id, "fixture_id")
        _validar_digest(self.digest_sha256)
        if not isinstance(self.rotulo, Categoria):
            raise TypeError("rotulo deve ser Categoria.")
        if not isinstance(self.contexto, ContextoAvaliacaoDSL):
            raise TypeError("contexto deve ser ContextoAvaliacaoDSL.")
        if not isinstance(self.governanca, ResultadoGovernanca):
            raise TypeError("governanca deve ser ResultadoGovernanca.")
        if not isinstance(self.diversidade, tuple):
            raise TypeError("diversidade deve ser uma tupla.")
        dimensoes: set[str] = set()
        for item in self.diversidade:
            if (
                not isinstance(item, tuple)
                or len(item) != 2
                or not isinstance(item[0], str)
                or _DIMENSAO_RE.fullmatch(item[0]) is None
                or not isinstance(item[1], str)
                or not item[1].strip()
            ):
                raise ValueError("Declaração de diversidade inválida.")
            if item[0] in dimensoes:
                raise ValueError("Dimensão de diversidade duplicada.")
            dimensoes.add(item[0])
        if not isinstance(self.aplicacoes, tuple) or any(
            not isinstance(item, str) or not item.strip()
            for item in self.aplicacoes
        ):
            raise TypeError("aplicacoes deve ser uma tupla de textos.")
        if len(self.aplicacoes) != len(set(self.aplicacoes)):
            raise ValueError("aplicacoes deve conter valores únicos.")
        if not isinstance(self.regras_aplicaveis, tuple) or not all(
            isinstance(item, ReferenciaVersaoRegra)
            for item in self.regras_aplicaveis
        ):
            raise TypeError(
                "regras_aplicaveis deve ser uma tupla de referências."
            )
        if len(self.regras_aplicaveis) != len(set(self.regras_aplicaveis)):
            raise ValueError("regras_aplicaveis deve conter valores únicos.")

    @property
    def digest(self) -> str:
        return self.digest_sha256

    @property
    def label(self) -> Categoria:
        return self.rotulo

    @property
    def dimensoes(self) -> dict[str, str]:
        return dict(self.diversidade)

    @property
    def aplicacoes_efetivas(self) -> frozenset[str]:
        if self.aplicacoes:
            return frozenset(self.aplicacoes)
        return frozenset(self.contexto.aplicacoes_presentes)


ExemploRotuladoParaValidacao = ExemploRotuladoCatalogo


@dataclass(frozen=True, slots=True)
class ManifestoAtivacaoRegra:
    """Metadados externos necessários para tentar ativar uma versão."""

    rule_id: str
    versao: int
    politica_amostras: PoliticaDeAmostras
    cobertura_condicoes: tuple[CoberturaDeCondicao, ...]
    exemplos_aplicaveis: tuple[str, ...]
    produz_causa_raiz: bool = False

    def __post_init__(self) -> None:
        _validar_id(self.rule_id, "rule_id")
        _validar_inteiro_positivo(self.versao, "versao")
        if not isinstance(self.politica_amostras, PoliticaDeAmostras):
            raise TypeError("politica_amostras deve ser PoliticaDeAmostras.")
        if (
            not isinstance(self.cobertura_condicoes, tuple)
            or not self.cobertura_condicoes
            or not all(
                isinstance(item, CoberturaDeCondicao)
                for item in self.cobertura_condicoes
            )
        ):
            raise TypeError(
                "cobertura_condicoes deve ser uma tupla não vazia."
            )
        ids = tuple(item.condicao_id for item in self.cobertura_condicoes)
        if len(ids) != len(set(ids)):
            raise ValueError("Condições de cobertura devem ser únicas.")
        if not isinstance(self.exemplos_aplicaveis, tuple) or not (
            self.exemplos_aplicaveis
        ):
            raise ValueError(
                "exemplos_aplicaveis deve ser uma tupla não vazia."
            )
        for fixture_id in self.exemplos_aplicaveis:
            _validar_id(fixture_id, "fixture_id")
        if len(self.exemplos_aplicaveis) != len(
            set(self.exemplos_aplicaveis)
        ):
            raise ValueError("Exemplos aplicáveis devem ser únicos.")
        if not isinstance(self.produz_causa_raiz, bool):
            raise TypeError("produz_causa_raiz deve ser booleano.")

    @property
    def referencia(self) -> ReferenciaVersaoRegra:
        return ReferenciaVersaoRegra(self.rule_id, self.versao)

    @property
    def sample_policy(self) -> PoliticaDeAmostras:
        return self.politica_amostras


@dataclass(frozen=True, slots=True)
class PacoteValidacaoCatalogo:
    """Pacote imutável de manifestos e exemplos para uma publicação."""

    manifestos: tuple[ManifestoAtivacaoRegra, ...] = ()
    exemplos: tuple[ExemploRotuladoCatalogo, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.manifestos, tuple) or not all(
            isinstance(item, ManifestoAtivacaoRegra)
            for item in self.manifestos
        ):
            raise TypeError("manifestos deve ser uma tupla de manifestos.")
        if not isinstance(self.exemplos, tuple) or not all(
            isinstance(item, ExemploRotuladoCatalogo) for item in self.exemplos
        ):
            raise TypeError("exemplos deve ser uma tupla de exemplos.")
        referencias = tuple(item.referencia for item in self.manifestos)
        fixture_ids = tuple(item.fixture_id for item in self.exemplos)
        if len(referencias) != len(set(referencias)):
            raise ValueError("Manifestos de ativação devem ser únicos.")
        if len(fixture_ids) != len(set(fixture_ids)):
            raise ValueError("Exemplos rotulados devem ser únicos.")


EvidenciasValidacaoCatalogo = PacoteValidacaoCatalogo


@dataclass(frozen=True, slots=True)
class AvaliacaoExemploRegra:
    """Registro seguro e estrutural de uma avaliação executada pela DSL."""

    regra: ReferenciaVersaoRegra
    fixture_id: str
    condicoes_satisfeitas: tuple[str, ...]
    correspondencia_integral: bool

    def __post_init__(self) -> None:
        if not isinstance(self.regra, ReferenciaVersaoRegra):
            raise TypeError("regra deve ser ReferenciaVersaoRegra.")
        _validar_id(self.fixture_id, "fixture_id")
        if not isinstance(self.condicoes_satisfeitas, tuple):
            raise TypeError("condicoes_satisfeitas deve ser uma tupla.")
        for condicao_id in self.condicoes_satisfeitas:
            _validar_id(condicao_id, "condicao_id")
        if not isinstance(self.correspondencia_integral, bool):
            raise TypeError("correspondencia_integral deve ser booleano.")


@dataclass(frozen=True, slots=True)
class ResultadoValidacaoCatalogo:
    """Snapshot autorizado e trilha estrutural das avaliações realizadas."""

    catalogo: CatalogoDeRegras
    regras_autorizadas: tuple[ReferenciaVersaoRegra, ...]
    avaliacoes: tuple[AvaliacaoExemploRegra, ...] = ()


class _FalhaValidacao(Exception):
    def __init__(self, codigo: CodigoValidacaoCatalogo) -> None:
        super().__init__(codigo.value)
        self.codigo = codigo


def _falhar(codigo: CodigoValidacaoCatalogo) -> None:
    raise _FalhaValidacao(codigo)


class ValidadorCatalogo:
    """Aplica gates e retorna um novo snapshot ou falha sem publicar nada."""

    def __init__(
        self,
        pacote: PacoteValidacaoCatalogo | None = None,
        *,
        avaliador: AvaliadorDSL | None = None,
    ) -> None:
        if pacote is not None and not isinstance(
            pacote, PacoteValidacaoCatalogo
        ):
            raise TypeError("pacote deve ser PacoteValidacaoCatalogo ou None.")
        if avaliador is not None and not isinstance(avaliador, AvaliadorDSL):
            raise TypeError("avaliador deve ser AvaliadorDSL ou None.")
        self._pacote = pacote or PacoteValidacaoCatalogo()
        self._avaliador = avaliador or AvaliadorDSL()

    def validar(
        self,
        candidato: CatalogoDeRegras,
        *,
        anterior: CatalogoDeRegras | None = None,
        pacote: PacoteValidacaoCatalogo | None = None,
    ) -> CatalogoDeRegras:
        """Valida integralmente e devolve o snapshot autorizado.

        O objeto anterior nunca é alterado. A publicação do retorno cabe ao
        ``CarregadorCatalogo``, que mantém o lock durante esta chamada.
        """

        return self.validar_com_relatorio(
            candidato, anterior=anterior, pacote=pacote
        ).catalogo

    def validar_com_relatorio(
        self,
        candidato: CatalogoDeRegras,
        *,
        anterior: CatalogoDeRegras | None = None,
        pacote: PacoteValidacaoCatalogo | None = None,
    ) -> ResultadoValidacaoCatalogo:
        if not isinstance(candidato, CatalogoDeRegras):
            raise TypeError("candidato deve ser CatalogoDeRegras.")
        if anterior is not None and not isinstance(anterior, CatalogoDeRegras):
            raise TypeError("anterior deve ser CatalogoDeRegras ou None.")
        pacote_efetivo = self._pacote if pacote is None else pacote
        if not isinstance(pacote_efetivo, PacoteValidacaoCatalogo):
            raise TypeError("pacote deve ser PacoteValidacaoCatalogo.")

        try:
            return self._validar(candidato, anterior, pacote_efetivo)
        except _FalhaValidacao as falha:
            raise ErroDeCatalogo(codigo=falha.codigo.value) from None
        except ErroDeCatalogo:
            raise
        except Exception:
            raise ErroDeCatalogo(
                codigo=CodigoValidacaoCatalogo.VALIDACAO_FALHOU.value
            ) from None

    def _validar(
        self,
        candidato: CatalogoDeRegras,
        anterior: CatalogoDeRegras | None,
        pacote: PacoteValidacaoCatalogo,
    ) -> ResultadoValidacaoCatalogo:
        validar_historico_append_only(anterior, candidato)
        declaradas = candidato.regras_declaradas_ativas
        _validar_precedencia(candidato, declaradas)

        manifestos = {item.referencia: item for item in pacote.manifestos}
        exemplos = {item.fixture_id: item for item in pacote.exemplos}
        autorizadas_anteriores = (
            set() if anterior is None else set(anterior.regras_autorizadas)
        )
        regras_anteriores = (
            {}
            if anterior is None
            else {
                (item.rule_id, item.versao): item for item in anterior.regras
            }
        )

        autorizadas: set[tuple[str, int]] = set()
        avaliacoes: list[AvaliacaoExemploRegra] = []
        for regra in declaradas:
            identidade = (regra.rule_id, regra.versao)
            if (
                identidade in autorizadas_anteriores
                and regras_anteriores.get(identidade) == regra
            ):
                autorizadas.add(identidade)
                continue

            referencia = ReferenciaVersaoRegra(*identidade)
            manifesto = manifestos.get(referencia)
            if manifesto is None:
                _falhar(CodigoValidacaoCatalogo.ATIVACAO_SEM_EVIDENCIA)
            avaliacoes.extend(
                self._validar_regra(
                    candidato,
                    regra,
                    manifesto,
                    exemplos,
                )
            )
            autorizadas.add(identidade)

        snapshot = replace(
            candidato,
            regras_autorizadas=tuple(sorted(autorizadas)),
        )
        referencias = tuple(
            ReferenciaVersaoRegra(rule_id, versao)
            for rule_id, versao in sorted(autorizadas)
        )
        return ResultadoValidacaoCatalogo(
            catalogo=snapshot,
            regras_autorizadas=referencias,
            avaliacoes=tuple(
                sorted(
                    avaliacoes,
                    key=lambda item: (
                        item.regra.rule_id,
                        item.regra.versao,
                        item.fixture_id,
                    ),
                )
            ),
        )

    def _validar_regra(
        self,
        catalogo: CatalogoDeRegras,
        regra: RegraValidada,
        manifesto: ManifestoAtivacaoRegra,
        exemplos: dict[str, ExemploRotuladoCatalogo],
    ) -> tuple[AvaliacaoExemploRegra, ...]:
        _validar_aprovacao(regra)
        exemplos_suporte = _validar_fixtures(
            catalogo, regra, manifesto, exemplos
        )
        _validar_politica(manifesto.politica_amostras, exemplos_suporte)

        aplicaveis_derivados = {
            exemplo.fixture_id
            for exemplo in exemplos.values()
            if _exemplo_aplicavel(exemplo, regra)
        }
        declarados = set(manifesto.exemplos_aplicaveis)
        if declarados != aplicaveis_derivados:
            _falhar(CodigoValidacaoCatalogo.REFERENCIA_INVALIDA)
        if not set(regra.fixture_ids).issubset(declarados):
            _falhar(CodigoValidacaoCatalogo.REFERENCIA_INVALIDA)

        resultados_dsl = {}
        registros: list[AvaliacaoExemploRegra] = []
        for fixture_id in sorted(declarados):
            exemplo = exemplos.get(fixture_id)
            if exemplo is None:
                _falhar(CodigoValidacaoCatalogo.REFERENCIA_INVALIDA)
            resultado = self._avaliador.avaliar_condicoes(
                regra.condicoes, exemplo.contexto
            )
            if resultado.estado is EstadoAvaliacaoDSL.ERRO_SEGURO:
                _falhar(CodigoValidacaoCatalogo.AVALIACAO_DE_EXEMPLO)
            resultados_dsl[fixture_id] = resultado
            registros.append(
                AvaliacaoExemploRegra(
                    regra=manifesto.referencia,
                    fixture_id=fixture_id,
                    condicoes_satisfeitas=resultado.condicoes_satisfeitas,
                    correspondencia_integral=resultado.satisfeita,
                )
            )

        for fixture_id in regra.fixture_ids:
            resultado = resultados_dsl.get(fixture_id)
            if resultado is None or not resultado.satisfeita:
                _falhar(CodigoValidacaoCatalogo.AVALIACAO_DE_EXEMPLO)

        _validar_cobertura(regra, manifesto, resultados_dsl)
        _validar_regra_de_erro_ou_causal(
            catalogo, regra, manifesto, exemplos_suporte, resultados_dsl
        )
        return tuple(registros)


GerenciadorValidacaoCatalogo = ValidadorCatalogo


def validar_catalogo_para_publicacao(
    candidato: CatalogoDeRegras,
    *,
    anterior: CatalogoDeRegras | None = None,
    pacote: PacoteValidacaoCatalogo | None = None,
) -> CatalogoDeRegras:
    """Atalho funcional para a validação fail-closed de publicação."""

    return ValidadorCatalogo(pacote).validar(candidato, anterior=anterior)


def validar_historico_append_only(
    anterior: CatalogoDeRegras | None,
    candidato: CatalogoDeRegras,
) -> None:
    """Exige nova versão e preservação de regras/digests históricos."""

    if anterior is None:
        return
    regras_anteriores = {
        (item.rule_id, item.versao): item for item in anterior.regras
    }
    regras_candidatas = {
        (item.rule_id, item.versao): item for item in candidato.regras
    }
    for identidade, regra_anterior in regras_anteriores.items():
        regra_candidata = regras_candidatas.get(identidade)
        if (
            regra_candidata is None
            or regra_candidata != regra_anterior
            or regra_candidata.digest_historico
            != regra_anterior.digest_historico
        ):
            _falhar(CodigoValidacaoCatalogo.HISTORICO_INVALIDO)

    fixtures_candidatas = {
        item.fixture_id: item for item in candidato.fixtures
    }
    for fixture_anterior in anterior.fixtures:
        fixture_candidata = fixtures_candidatas.get(
            fixture_anterior.fixture_id
        )
        if fixture_candidata is None or not hmac.compare_digest(
            fixture_anterior.digest_sha256,
            fixture_candidata.digest_sha256,
        ):
            _falhar(CodigoValidacaoCatalogo.HISTORICO_INVALIDO)

    maximo_por_regra: dict[str, int] = {}
    for regra in anterior.regras:
        maximo_por_regra[regra.rule_id] = max(
            maximo_por_regra.get(regra.rule_id, 0), regra.versao
        )
    for identidade, regra in regras_candidatas.items():
        if identidade in regras_anteriores:
            continue
        maximo = maximo_por_regra.get(regra.rule_id)
        if maximo is not None and regra.versao <= maximo:
            _falhar(CodigoValidacaoCatalogo.HISTORICO_INVALIDO)

    if (
        candidato.digest_sha256 != anterior.digest_sha256
        and candidato.versao == anterior.versao
    ):
        _falhar(CodigoValidacaoCatalogo.VERSAO_INVALIDA)


def _validar_precedencia(
    catalogo: CatalogoDeRegras,
    regras: tuple[RegraValidada, ...],
) -> None:
    ordens = tuple(item.precedencia for item in regras)
    if len(ordens) != len(set(ordens)):
        _falhar(CodigoValidacaoCatalogo.PRECEDENCIA_CONFLITANTE)
    declarada = {
        (item.rule_id, item.versao): item.ordem
        for item in catalogo.precedencia
    }
    for regra in regras:
        if declarada.get((regra.rule_id, regra.versao)) != regra.precedencia:
            _falhar(CodigoValidacaoCatalogo.PRECEDENCIA_CONFLITANTE)


def _validar_aprovacao(regra: RegraValidada) -> None:
    aprovacao = regra.aprovacao
    if (
        regra.estado is not EstadoRegra.ACTIVE
        or not aprovacao.aprovado_por.strip()
        or not aprovacao.referencia_aprovacao.strip()
        or aprovacao.aprovado_em.tzinfo is None
        or aprovacao.aprovado_em.utcoffset() is None
    ):
        _falhar(CodigoValidacaoCatalogo.APROVACAO_INCOMPLETA)


def _validar_fixtures(
    catalogo: CatalogoDeRegras,
    regra: RegraValidada,
    manifesto: ManifestoAtivacaoRegra,
    exemplos: dict[str, ExemploRotuladoCatalogo],
) -> tuple[ExemploRotuladoCatalogo, ...]:
    cobertura_refs = {
        fixture_id
        for cobertura in manifesto.cobertura_condicoes
        for fixture_id in cobertura.fixture_ids
    }
    if not cobertura_refs.issubset(set(regra.fixture_ids)):
        _falhar(CodigoValidacaoCatalogo.REFERENCIA_INVALIDA)

    suporte: list[ExemploRotuladoCatalogo] = []
    for fixture_id, digest_regra in zip(
        regra.fixture_ids, regra.fixture_digests, strict=True
    ):
        fixture = catalogo.obter_fixture(fixture_id)
        exemplo = exemplos.get(fixture_id)
        if fixture is None or exemplo is None:
            _falhar(CodigoValidacaoCatalogo.REFERENCIA_INVALIDA)
        if not (
            hmac.compare_digest(digest_regra, fixture.digest_sha256)
            and hmac.compare_digest(digest_regra, exemplo.digest_sha256)
        ):
            _falhar(CodigoValidacaoCatalogo.DIGEST_INVALIDO)
        origem = (fixture.origem_sanitizada or "").strip().casefold()
        origem_aprovada = origem.startswith(
            ("sanit", "synt", "sint")
        )
        if (
            not fixture.incorporada
            or fixture.rotulo is None
            or fixture.rotulo is not exemplo.rotulo
            or fixture.rotulo is not regra.categoria
            or not origem_aprovada
            or fixture.validada_em is None
            or not (fixture.responsavel_dominio or "").strip()
            or not (fixture.versao_sanitizador or "").strip()
            or not exemplo.governanca.aprovada
        ):
            _falhar(CodigoValidacaoCatalogo.FIXTURE_NAO_GOVERNADA)
        suporte.append(exemplo)
    return tuple(suporte)


def _validar_politica(
    politica: PoliticaDeAmostras,
    exemplos: tuple[ExemploRotuladoCatalogo, ...],
) -> None:
    if len(exemplos) < politica.quantidade_minima:
        _falhar(CodigoValidacaoCatalogo.POLITICA_DE_AMOSTRAS)
    for dimensao in politica.dimensoes_diversidade:
        valores: set[str] = set()
        for exemplo in exemplos:
            dimensoes = exemplo.dimensoes
            if dimensao not in dimensoes:
                _falhar(CodigoValidacaoCatalogo.POLITICA_DE_AMOSTRAS)
            valores.add(dimensoes[dimensao])
        if len(valores) < politica.minimo_distintos_por_dimensao:
            _falhar(CodigoValidacaoCatalogo.POLITICA_DE_AMOSTRAS)


def _exemplo_aplicavel(
    exemplo: ExemploRotuladoCatalogo,
    regra: RegraValidada,
) -> bool:
    referencia = ReferenciaVersaoRegra(regra.rule_id, regra.versao)
    if exemplo.regras_aplicaveis:
        return referencia in exemplo.regras_aplicaveis
    return set(regra.aplicacoes).issubset(exemplo.aplicacoes_efetivas)


def _validar_cobertura(
    regra: RegraValidada,
    manifesto: ManifestoAtivacaoRegra,
    resultados_dsl: dict[str, object],
) -> None:
    condicoes_regra = {item.condition_id for item in regra.condicoes}
    cobertura = {
        item.condicao_id: item.fixture_ids
        for item in manifesto.cobertura_condicoes
    }
    if set(cobertura) != condicoes_regra:
        _falhar(CodigoValidacaoCatalogo.COBERTURA_INCOMPLETA)
    for condicao_id, fixture_ids in cobertura.items():
        for fixture_id in fixture_ids:
            resultado = resultados_dsl.get(fixture_id)
            if (
                resultado is None
                or condicao_id not in resultado.condicoes_satisfeitas
            ):
                _falhar(CodigoValidacaoCatalogo.COBERTURA_INCOMPLETA)


def _validar_regra_de_erro_ou_causal(
    catalogo: CatalogoDeRegras,
    regra: RegraValidada,
    manifesto: ManifestoAtivacaoRegra,
    exemplos: tuple[ExemploRotuladoCatalogo, ...],
    resultados_dsl: dict[str, object],
) -> None:
    causal = bool(getattr(regra, "causa_raiz", None)) or (
        manifesto.produz_causa_raiz
    )
    exige_erro = regra.categoria is Categoria.ERRO or causal
    if not exige_erro:
        return
    exemplos_de_erro = tuple(
        item
        for item in exemplos
        if item.rotulo is Categoria.ERRO
        and getattr(resultados_dsl.get(item.fixture_id), "satisfeita", False)
    )
    if catalogo.cobertura.erros_rotulados < 1 or not exemplos_de_erro:
        _falhar(
            CodigoValidacaoCatalogo.CAUSA_RAIZ_SEM_EXEMPLO
            if causal
            else CodigoValidacaoCatalogo.ERRO_SEM_EXEMPLO
        )
    if causal and regra.categoria is not Categoria.ERRO:
        _falhar(CodigoValidacaoCatalogo.CAUSA_RAIZ_SEM_EXEMPLO)


def _validar_id(valor: object, nome: str) -> None:
    if not isinstance(valor, str) or _ID_RE.fullmatch(valor) is None:
        raise ValueError(f"{nome} inválido.")


def _validar_digest(valor: object) -> None:
    if not isinstance(valor, str) or _DIGEST_RE.fullmatch(valor) is None:
        raise ValueError("Digest SHA-256 inválido.")


def _validar_inteiro_positivo(valor: object, nome: str) -> None:
    if isinstance(valor, bool) or not isinstance(valor, int) or valor < 1:
        raise ValueError(f"{nome} deve ser inteiro positivo.")


__all__ = [
    "AvaliacaoExemploRegra",
    "CodigoValidacaoCatalogo",
    "CoberturaDeCondicao",
    "EvidenciasValidacaoCatalogo",
    "ExemploRotuladoCatalogo",
    "ExemploRotuladoParaValidacao",
    "GerenciadorValidacaoCatalogo",
    "ManifestoAtivacaoRegra",
    "PacoteValidacaoCatalogo",
    "PoliticaAmostras",
    "PoliticaDeAmostras",
    "ReferenciaVersaoRegra",
    "ResultadoValidacaoCatalogo",
    "ValidadorCatalogo",
    "validar_catalogo_para_publicacao",
    "validar_historico_append_only",
]
