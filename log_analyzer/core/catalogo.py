"""Modelos imutáveis e carregamento atômico do catálogo de regras.

O catálogo é um documento JSON declarativo. Este módulo somente decodifica,
valida e congela seus dados; condições nunca são avaliadas aqui. A DSL, os
gates de ativação e a classificação pertencem a componentes posteriores.

A troca do catálogo ativo é transacional por instância de
:class:`CarregadorCatalogo`: qualquer falha de arquivo, JSON, schema,
integridade, referência ou histórico preserva a referência ativa anterior.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import stat
from threading import RLock
from typing import Any

from log_analyzer.core.excecoes import ErroDeCatalogo
from log_analyzer.core.modelos import Categoria


_SCHEMA_VERSION = 1
_MAX_CATALOG_BYTES = 5 * 1024 * 1024
_MAX_TEXT_LENGTH = 16_384
_MAX_DECLARATIVE_DEPTH = 16

_ID_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9._:-]{0,127}\Z")
_FIELD_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")
_DIGEST_PATTERN = re.compile(r"[0-9A-Fa-f]{64}\Z")
_APPLICATION_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{0,31}\Z")

_DEFAULT_GAP_ID = "ADDITIONAL_LABELED_SUCCESS_AND_ERROR_SAMPLES"
_DEFAULT_GAP_DESCRIPTION = (
    "Amostras adicionais rotuladas de sucesso e erro são necessárias para "
    "generalizar padrões além do cenário atualmente coberto."
)


class EstadoRegra(str, Enum):
    """Estados declarativos aceitos para uma versão de regra."""

    DRAFT = "DRAFT"
    CANDIDATE = "CANDIDATE"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


@dataclass(frozen=True)
class CondicaoRegra:
    """Condição declarativa ainda não compilada pela DSL.

    ``parametros`` contém somente escalares e tuplas produzidos a partir de
    JSON. Objetos são representados por tuplas ordenadas de pares; listas são
    representadas por tuplas. Assim, nenhum objeto mutável ou executável do
    documento atravessa a fronteira de carga.
    """

    condition_id: str
    operator: str
    parametros: tuple[tuple[str, object], ...] = ()

    @property
    def id_condicao(self) -> str:
        return self.condition_id

    @property
    def operador(self) -> str:
        return self.operator

    def obter_parametro(self, nome: str, padrao: object = None) -> object:
        for chave, valor in self.parametros:
            if chave == nome:
                return valor
        return padrao

    @property
    def field(self) -> object:
        return self.obter_parametro("field")

    @property
    def expected(self) -> object:
        return self.obter_parametro("expected")


@dataclass(frozen=True)
class ReferenciaFixture:
    """Referência imutável de uma regra a uma fixture e ao seu SHA-256."""

    fixture_id: str
    digest_sha256: str

    @property
    def digest(self) -> str:
        return self.digest_sha256


@dataclass(frozen=True)
class FixtureCatalogo:
    """Exemplo rotulado incorporado ou referência de suporte inline.

    Catálogos compactos podem declarar somente ``fixture_ids`` e
    ``fixture_digests`` nas regras. Nesse caso, ``incorporada`` é falso e os
    metadados de governança permanecem ``None``. Uma fixture declarada na
    coleção de topo é incorporada e exige todos os metadados de Requirement
    12.4.
    """

    fixture_id: str
    digest_sha256: str
    rotulo: Categoria | None = None
    origem_sanitizada: str | None = None
    validada_em: datetime | None = None
    responsavel_dominio: str | None = None
    versao_sanitizador: str | None = None
    incorporada: bool = False

    @property
    def digest(self) -> str:
        return self.digest_sha256

    @property
    def label(self) -> Categoria | None:
        return self.rotulo


# Nome alternativo útil para consumidores que tratam somente fixtures completas.
FixtureRotulada = FixtureCatalogo


@dataclass(frozen=True)
class LacunaCatalogo:
    """Lacuna declarada de cobertura ou governança."""

    gap_id: str
    descricao: str


@dataclass(frozen=True)
class CoberturaCatalogo:
    """Contagem e declaração determinística da cobertura rotulada."""

    sucessos_rotulados: int
    erros_rotulados: int
    declaracao: str
    lacunas: tuple[LacunaCatalogo, ...]

    @property
    def labeled_successes(self) -> int:
        return self.sucessos_rotulados

    @property
    def labeled_errors(self) -> int:
        return self.erros_rotulados


@dataclass(frozen=True)
class AprovacaoDeclarativa:
    """Registro declarativo da aprovação de uma versão de regra."""

    aprovado_por: str
    aprovado_em: datetime
    referencia_aprovacao: str

    @property
    def approved_by(self) -> str:
        return self.aprovado_por

    @property
    def approved_at(self) -> datetime:
        return self.aprovado_em

    @property
    def approval_reference(self) -> str:
        return self.referencia_aprovacao


AprovacaoRegra = AprovacaoDeclarativa


@dataclass(frozen=True)
class PrecedenciaRegra:
    """Posição versionada de uma regra na ordem de decisão."""

    rule_id: str
    versao: int
    ordem: int

    @property
    def version(self) -> int:
        return self.versao

    @property
    def precedence(self) -> int:
        return self.ordem


@dataclass(frozen=True)
class RegraValidada:
    """Versão imutável de regra declarada no catálogo.

    O nome do modelo não ativa a regra por si só. ``estado`` continua sendo um
    dado declarativo; os gates que autorizam ``ACTIVE`` são responsabilidade do
    validador de catálogo da tarefa subsequente.
    """

    rule_id: str
    versao: int
    categoria: Categoria
    aplicacoes: tuple[str, ...]
    condicoes: tuple[CondicaoRegra, ...]
    seletores_evidencia: tuple[str, ...]
    fixture_ids: tuple[str, ...]
    fixture_digests: tuple[str, ...]
    estado: EstadoRegra
    aprovado_por: str
    aprovado_em: datetime
    referencia_aprovacao: str
    precedencia: int
    digest_historico: str
    causa_raiz: str | None = None
    aprovacao: AprovacaoDeclarativa = field(init=False, repr=False)
    fixtures_suporte: tuple[ReferenciaFixture, ...] = field(
        init=False, repr=False
    )
    precedencia_declarada: PrecedenciaRegra = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "aprovacao",
            AprovacaoDeclarativa(
                aprovado_por=self.aprovado_por,
                aprovado_em=self.aprovado_em,
                referencia_aprovacao=self.referencia_aprovacao,
            ),
        )
        object.__setattr__(
            self,
            "fixtures_suporte",
            tuple(
                ReferenciaFixture(fixture_id, digest)
                for fixture_id, digest in zip(
                    self.fixture_ids, self.fixture_digests, strict=True
                )
            ),
        )
        object.__setattr__(
            self,
            "precedencia_declarada",
            PrecedenciaRegra(self.rule_id, self.versao, self.precedencia),
        )

    @property
    def version(self) -> int:
        return self.versao

    @property
    def category(self) -> Categoria:
        return self.categoria

    @property
    def applications(self) -> tuple[str, ...]:
        return self.aplicacoes

    @property
    def conditions(self) -> tuple[CondicaoRegra, ...]:
        return self.condicoes

    @property
    def evidence_selectors(self) -> tuple[str, ...]:
        return self.seletores_evidencia

    @property
    def state(self) -> EstadoRegra:
        return self.estado

    @property
    def ativa(self) -> bool:
        """Indica somente o estado declarado; gates ainda podem rejeitá-la."""

        return self.estado is EstadoRegra.ACTIVE

    @property
    def root_cause(self) -> str | None:
        return self.causa_raiz


@dataclass(frozen=True)
class CatalogoDeRegras:
    """Snapshot integral, profundamente imutável, de um catálogo validado."""

    versao: str
    schema_version: int
    regras: tuple[RegraValidada, ...]
    fixtures: tuple[FixtureCatalogo, ...]
    cobertura: CoberturaCatalogo
    precedencia: tuple[PrecedenciaRegra, ...]
    digest_sha256: str
    # Estado transitório de publicação: ``ACTIVE`` no JSON não basta. O
    # validador preenche estas identidades somente depois de todos os gates.
    regras_autorizadas: tuple[tuple[str, int], ...] = field(
        default=(), repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if not isinstance(self.regras_autorizadas, tuple):
            raise TypeError("regras_autorizadas deve ser uma tupla.")
        identidades = {(regra.rule_id, regra.versao) for regra in self.regras}
        if any(
            not isinstance(item, tuple)
            or len(item) != 2
            or not isinstance(item[0], str)
            or not _is_int(item[1])
            or item not in identidades
            for item in self.regras_autorizadas
        ):
            raise ValueError("Identidade de regra autorizada inválida.")
        if len(self.regras_autorizadas) != len(set(self.regras_autorizadas)):
            raise ValueError("Regras autorizadas devem ser únicas.")

    @property
    def catalog_version(self) -> str:
        return self.versao

    @property
    def rules(self) -> tuple[RegraValidada, ...]:
        return self.regras

    @property
    def coverage(self) -> CoberturaCatalogo:
        return self.cobertura

    @property
    def lacunas(self) -> tuple[LacunaCatalogo, ...]:
        return self.cobertura.lacunas

    @property
    def regras_declaradas_ativas(self) -> tuple[RegraValidada, ...]:
        """Regras cujo JSON declara ACTIVE, ainda sem autorizar execução."""

        return tuple(
            sorted(
                (regra for regra in self.regras if regra.ativa),
                key=lambda regra: (
                    regra.precedencia,
                    regra.rule_id,
                    regra.versao,
                ),
            )
        )

    @property
    def declared_active_rules(self) -> tuple[RegraValidada, ...]:
        return self.regras_declaradas_ativas

    @property
    def regras_ativas(self) -> tuple[RegraValidada, ...]:
        """Regras ACTIVE que também passaram pelos gates de publicação."""

        autorizadas = set(self.regras_autorizadas)
        return tuple(
            regra
            for regra in self.regras_declaradas_ativas
            if (regra.rule_id, regra.versao) in autorizadas
        )

    @property
    def active_rules(self) -> tuple[RegraValidada, ...]:
        return self.regras_ativas

    def obter_regra(self, rule_id: str, versao: int) -> RegraValidada | None:
        for regra in self.regras:
            if regra.rule_id == rule_id and regra.versao == versao:
                return regra
        return None

    def obter_fixture(self, fixture_id: str) -> FixtureCatalogo | None:
        for fixture in self.fixtures:
            if fixture.fixture_id == fixture_id:
                return fixture
        return None


class _FalhaDeValidacao(Exception):
    """Falha interna reduzida a código seguro na fronteira pública."""

    def __init__(self, codigo: str) -> None:
        super().__init__(codigo)
        self.codigo = codigo


def _falhar(codigo: str = "CATALOG_SCHEMA_ERROR") -> None:
    raise _FalhaDeValidacao(codigo)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _expect_object(value: object) -> dict[str, Any]:
    if type(value) is not dict:
        _falhar()
    return value


def _expect_array(value: object) -> list[Any]:
    if type(value) is not list:
        _falhar()
    return value


def _expect_keys(
    value: dict[str, Any],
    *,
    required: set[str],
    optional: set[str] = frozenset(),
) -> None:
    keys = set(value)
    if not required.issubset(keys) or not keys.issubset(required | optional):
        _falhar()


def _expect_text(
    value: object,
    *,
    identifier: bool = False,
    field_name: bool = False,
    max_length: int = _MAX_TEXT_LENGTH,
) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        _falhar()
    if identifier and _ID_PATTERN.fullmatch(value) is None:
        _falhar()
    if field_name and _FIELD_PATTERN.fullmatch(value) is None:
        _falhar()
    return value


def _expect_nonnegative_int(value: object) -> int:
    if not _is_int(value) or value < 0:
        _falhar()
    return value


def _expect_positive_int(value: object) -> int:
    if not _is_int(value) or value < 1:
        _falhar()
    return value


def _expect_digest(value: object) -> str:
    if not isinstance(value, str) or _DIGEST_PATTERN.fullmatch(value) is None:
        _falhar("CATALOG_DIGEST_ERROR")
    return value.lower()


def _expect_datetime(value: object) -> datetime:
    text = _expect_text(value, max_length=128)
    try:
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError, OverflowError):
        _falhar()
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _falhar()
    return parsed


def _parse_category(value: object) -> Categoria:
    if not isinstance(value, str):
        _falhar()
    if value in Categoria.__members__:
        return Categoria[value]
    for category in Categoria:
        if value == category.value:
            return category
    _falhar()


def _parse_state(value: object) -> EstadoRegra:
    if not isinstance(value, str):
        _falhar()
    try:
        return EstadoRegra(value)
    except ValueError:
        _falhar()


def _freeze_declarative(value: object, *, depth: int = 0) -> object:
    """Converte JSON em uma árvore imutável sem despachar conteúdo."""

    if depth > _MAX_DECLARATIVE_DEPTH:
        _falhar()
    if value is None or isinstance(value, (str, bool, int)):
        if isinstance(value, str) and len(value) > _MAX_TEXT_LENGTH:
            _falhar()
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            _falhar()
        return value
    if type(value) is list:
        if len(value) > 1024:
            _falhar()
        return tuple(
            _freeze_declarative(item, depth=depth + 1) for item in value
        )
    if type(value) is dict:
        if len(value) > 256:
            _falhar()
        frozen: list[tuple[str, object]] = []
        for key in sorted(value):
            _expect_text(key, field_name=True)
            frozen.append(
                (key, _freeze_declarative(value[key], depth=depth + 1))
            )
        return tuple(frozen)
    _falhar()


def _parse_condition(value: object) -> CondicaoRegra:
    data = _expect_object(value)
    if "condition_id" not in data or "operator" not in data:
        _falhar()
    condition_id = _expect_text(data["condition_id"], identifier=True)
    operator = _expect_text(data["operator"], identifier=True)
    parameters: list[tuple[str, object]] = []
    for key in sorted(set(data) - {"condition_id", "operator"}):
        _expect_text(key, field_name=True)
        parameters.append((key, _freeze_declarative(data[key])))
    return CondicaoRegra(condition_id, operator, tuple(parameters))


def _parse_gap(value: object) -> LacunaCatalogo:
    if isinstance(value, str):
        text = _expect_text(value)
        gap_id = (
            value
            if _ID_PATTERN.fullmatch(value) is not None
            else f"GAP_{sha256(value.encode('utf-8')).hexdigest()[:16]}"
        )
        return LacunaCatalogo(gap_id, text)

    data = _expect_object(value)
    _expect_keys(
        data,
        required={"gap_id", "description"},
    )
    return LacunaCatalogo(
        _expect_text(data["gap_id"], identifier=True),
        _expect_text(data["description"]),
    )


def _coverage_statement(successes: int, errors: int) -> str:
    success_noun = "cenário" if successes == 1 else "cenários"
    error_noun = "cenário" if errors == 1 else "cenários"
    return (
        f"{successes} {success_noun} de sucesso; "
        f"{errors} {error_noun} de erro"
    )


def _parse_coverage(
    value: object,
    top_level_gaps: object | None,
) -> CoberturaCatalogo:
    data = _expect_object(value)
    _expect_keys(
        data,
        required={"labeled_successes", "labeled_errors"},
        optional={"statement", "gaps"},
    )
    successes = _expect_nonnegative_int(data["labeled_successes"])
    errors = _expect_nonnegative_int(data["labeled_errors"])
    statement = _coverage_statement(successes, errors)
    if "statement" in data and _expect_text(data["statement"]) != statement:
        _falhar()

    gap_values: list[Any] = []
    if "gaps" in data:
        gap_values.extend(_expect_array(data["gaps"]))
    if top_level_gaps is not None:
        gap_values.extend(_expect_array(top_level_gaps))

    gaps_by_id: dict[str, LacunaCatalogo] = {}
    for raw_gap in gap_values:
        gap = _parse_gap(raw_gap)
        if gap.gap_id in gaps_by_id:
            _falhar("CATALOG_REFERENCE_ERROR")
        gaps_by_id[gap.gap_id] = gap

    # Requirement 12.1 é uma declaração permanente desta fase. Ela continua
    # explícita no snapshot mesmo quando o JSON compacto omite ``gaps``.
    gaps_by_id.setdefault(
        _DEFAULT_GAP_ID,
        LacunaCatalogo(_DEFAULT_GAP_ID, _DEFAULT_GAP_DESCRIPTION),
    )
    gaps = tuple(sorted(gaps_by_id.values(), key=lambda gap: gap.gap_id))
    return CoberturaCatalogo(successes, errors, statement, gaps)


def _parse_fixture(value: object) -> FixtureCatalogo:
    data = _expect_object(value)
    _expect_keys(
        data,
        required={
            "fixture_id",
            "label",
            "sanitized_origin",
            "validated_at",
            "validated_by",
        },
        optional={"digest", "sha256", "sanitizer_version"},
    )
    if ("digest" in data) == ("sha256" in data):
        _falhar("CATALOG_DIGEST_ERROR")
    digest = _expect_digest(data.get("digest", data.get("sha256")))
    return FixtureCatalogo(
        fixture_id=_expect_text(data["fixture_id"], identifier=True),
        digest_sha256=digest,
        rotulo=_parse_category(data["label"]),
        origem_sanitizada=_expect_text(data["sanitized_origin"]),
        validada_em=_expect_datetime(data["validated_at"]),
        responsavel_dominio=_expect_text(data["validated_by"]),
        versao_sanitizador=(
            _expect_text(data["sanitizer_version"], identifier=True)
            if "sanitizer_version" in data
            else None
        ),
        incorporada=True,
    )


def _parse_approval(data: dict[str, Any]) -> AprovacaoDeclarativa:
    flat_keys = {"approved_by", "approved_at", "approval_reference"}
    has_flat = bool(flat_keys & set(data))
    has_nested = "approval" in data
    if has_flat == has_nested:
        _falhar()

    if has_nested:
        approval = _expect_object(data["approval"])
        _expect_keys(approval, required=flat_keys)
    else:
        if not flat_keys.issubset(data):
            _falhar()
        approval = data

    return AprovacaoDeclarativa(
        aprovado_por=_expect_text(approval["approved_by"]),
        aprovado_em=_expect_datetime(approval["approved_at"]),
        referencia_aprovacao=_expect_text(
            approval["approval_reference"], max_length=1024
        ),
    )


def _canonical_digest(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError):
        _falhar()
    return sha256(encoded).hexdigest()


def _parse_rule(value: object) -> RegraValidada:
    data = _expect_object(value)
    required = {
        "rule_id",
        "version",
        "category",
        "applications",
        "conditions",
        "fixture_ids",
        "fixture_digests",
        "state",
        "precedence",
    }
    optional = {
        "approved_by",
        "approved_at",
        "approval_reference",
        "approval",
        "evidence_selectors",
        "digest",
        "root_cause",
        "causa_raiz",
    }
    _expect_keys(data, required=required, optional=optional)

    rule_id = _expect_text(data["rule_id"], identifier=True)
    version = _expect_positive_int(data["version"])
    category = _parse_category(data["category"])
    state = _parse_state(data["state"])
    precedence = _expect_nonnegative_int(data["precedence"])

    applications_raw = _expect_array(data["applications"])
    if not applications_raw:
        _falhar()
    applications: list[str] = []
    for application_raw in applications_raw:
        application = _expect_text(application_raw, max_length=32)
        if _APPLICATION_PATTERN.fullmatch(application) is None:
            _falhar()
        applications.append(application)
    if len(applications) != len(set(applications)):
        _falhar("CATALOG_REFERENCE_ERROR")
    applications_tuple = tuple(sorted(applications))

    conditions_raw = _expect_array(data["conditions"])
    conditions = tuple(_parse_condition(item) for item in conditions_raw)
    if not conditions:
        _falhar()
    condition_ids = tuple(condition.condition_id for condition in conditions)
    if len(condition_ids) != len(set(condition_ids)):
        _falhar("CATALOG_REFERENCE_ERROR")
    conditions = tuple(sorted(conditions, key=lambda item: item.condition_id))

    if "evidence_selectors" in data:
        selectors = tuple(
            _expect_text(item, identifier=True)
            for item in _expect_array(data["evidence_selectors"])
        )
        if not selectors or len(selectors) != len(set(selectors)):
            _falhar("CATALOG_REFERENCE_ERROR")
        if not set(selectors).issubset(condition_ids):
            _falhar("CATALOG_REFERENCE_ERROR")
        selectors = tuple(sorted(selectors))
    else:
        selectors = tuple(sorted(condition_ids))

    fixture_ids_raw = _expect_array(data["fixture_ids"])
    fixture_digests_raw = _expect_array(data["fixture_digests"])
    if len(fixture_ids_raw) != len(fixture_digests_raw):
        _falhar("CATALOG_REFERENCE_ERROR")
    if state is not EstadoRegra.DRAFT and not fixture_ids_raw:
        _falhar("CATALOG_REFERENCE_ERROR")

    fixture_pairs = tuple(
        sorted(
            (
                _expect_text(fixture_id, identifier=True),
                _expect_digest(digest),
            )
            for fixture_id, digest in zip(
                fixture_ids_raw, fixture_digests_raw, strict=True
            )
        )
    )
    if len({fixture_id for fixture_id, _ in fixture_pairs}) != len(
        fixture_pairs
    ):
        _falhar("CATALOG_REFERENCE_ERROR")
    fixture_ids = tuple(pair[0] for pair in fixture_pairs)
    fixture_digests = tuple(pair[1] for pair in fixture_pairs)

    approval = _parse_approval(data)

    root_keys = {"root_cause", "causa_raiz"} & set(data)
    if len(root_keys) > 1:
        _falhar()
    root_cause = (
        _expect_text(data[next(iter(root_keys))], identifier=True)
        if root_keys
        else None
    )

    canonical_rule = {
        key: item for key, item in data.items() if key != "digest"
    }
    computed_digest = _canonical_digest(canonical_rule)
    if "digest" in data and _expect_digest(data["digest"]) != computed_digest:
        _falhar("CATALOG_DIGEST_ERROR")

    return RegraValidada(
        rule_id=rule_id,
        versao=version,
        categoria=category,
        aplicacoes=applications_tuple,
        condicoes=conditions,
        seletores_evidencia=selectors,
        fixture_ids=fixture_ids,
        fixture_digests=fixture_digests,
        estado=state,
        aprovado_por=approval.aprovado_por,
        aprovado_em=approval.aprovado_em,
        referencia_aprovacao=approval.referencia_aprovacao,
        precedencia=precedence,
        digest_historico=computed_digest,
        causa_raiz=root_cause,
    )


def _resolve_fixtures(
    raw_fixtures: object | None,
    rules: tuple[RegraValidada, ...],
) -> tuple[FixtureCatalogo, ...]:
    explicit = raw_fixtures is not None
    fixtures_by_id: dict[str, FixtureCatalogo] = {}

    if explicit:
        for raw_fixture in _expect_array(raw_fixtures):
            fixture = _parse_fixture(raw_fixture)
            if fixture.fixture_id in fixtures_by_id:
                _falhar("CATALOG_REFERENCE_ERROR")
            fixtures_by_id[fixture.fixture_id] = fixture

    for rule in rules:
        for reference in rule.fixtures_suporte:
            fixture = fixtures_by_id.get(reference.fixture_id)
            if fixture is None:
                if explicit:
                    _falhar("CATALOG_REFERENCE_ERROR")
                fixtures_by_id[reference.fixture_id] = FixtureCatalogo(
                    fixture_id=reference.fixture_id,
                    digest_sha256=reference.digest_sha256,
                )
            elif fixture.digest_sha256 != reference.digest_sha256:
                _falhar("CATALOG_DIGEST_ERROR")

    return tuple(sorted(fixtures_by_id.values(), key=lambda item: item.fixture_id))


def _resolve_precedence(
    raw_precedence: object | None,
    rules: tuple[RegraValidada, ...],
) -> tuple[PrecedenciaRegra, ...]:
    expected = {
        (rule.rule_id, rule.versao): rule.precedencia_declarada for rule in rules
    }
    if raw_precedence is not None:
        declared: dict[tuple[str, int], PrecedenciaRegra] = {}
        for raw_item in _expect_array(raw_precedence):
            item = _expect_object(raw_item)
            _expect_keys(
                item,
                required={"rule_id", "version", "precedence"},
            )
            precedence = PrecedenciaRegra(
                rule_id=_expect_text(item["rule_id"], identifier=True),
                versao=_expect_positive_int(item["version"]),
                ordem=_expect_nonnegative_int(item["precedence"]),
            )
            key = (precedence.rule_id, precedence.versao)
            if key in declared:
                _falhar("CATALOG_REFERENCE_ERROR")
            declared[key] = precedence
        if declared != expected:
            _falhar("CATALOG_REFERENCE_ERROR")

    return tuple(
        sorted(
            expected.values(),
            key=lambda item: (item.ordem, item.rule_id, item.versao),
        )
    )


def _duplicate_rejecting_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _falhar("CATALOG_JSON_ERROR")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> object:
    _falhar("CATALOG_JSON_ERROR")


def _decode_json(text: str) -> dict[str, Any]:
    if not isinstance(text, str) or len(text.encode("utf-8")) > _MAX_CATALOG_BYTES:
        _falhar("CATALOG_SIZE_ERROR")
    try:
        document = json.loads(
            text,
            object_pairs_hook=_duplicate_rejecting_object,
            parse_constant=_reject_json_constant,
        )
    except _FalhaDeValidacao:
        raise
    except (json.JSONDecodeError, UnicodeError, TypeError, ValueError, OverflowError):
        _falhar("CATALOG_JSON_ERROR")
    return _expect_object(document)


def _build_catalog(document: object) -> CatalogoDeRegras:
    data = _expect_object(document)
    if "schema_version" not in data:
        _falhar("CATALOG_VERSION_ERROR")
    _expect_keys(
        data,
        required={"schema_version", "catalog_version", "coverage", "rules"},
        optional={
            "fixtures",
            "gaps",
            "precedence",
            "catalog_digest",
        },
    )

    schema_version = data["schema_version"]
    if not _is_int(schema_version) or schema_version != _SCHEMA_VERSION:
        _falhar("CATALOG_VERSION_ERROR")
    catalog_version = _expect_text(data["catalog_version"], identifier=True)
    coverage = _parse_coverage(data["coverage"], data.get("gaps"))

    rules = tuple(_parse_rule(item) for item in _expect_array(data["rules"]))
    identities = tuple((rule.rule_id, rule.versao) for rule in rules)
    if len(identities) != len(set(identities)):
        _falhar("CATALOG_REFERENCE_ERROR")
    rules = tuple(sorted(rules, key=lambda item: (item.rule_id, item.versao)))

    fixtures = _resolve_fixtures(data.get("fixtures"), rules)
    precedence = _resolve_precedence(data.get("precedence"), rules)

    canonical_catalog = {
        key: value for key, value in data.items() if key != "catalog_digest"
    }
    computed_digest = _canonical_digest(canonical_catalog)
    if "catalog_digest" in data:
        if _expect_digest(data["catalog_digest"]) != computed_digest:
            _falhar("CATALOG_DIGEST_ERROR")

    return CatalogoDeRegras(
        versao=catalog_version,
        schema_version=schema_version,
        regras=rules,
        fixtures=fixtures,
        cobertura=coverage,
        precedencia=precedence,
        digest_sha256=computed_digest,
    )


def construir_catalogo(documento: object) -> CatalogoDeRegras:
    """Valida um documento já decodificado e retorna um snapshot imutável.

    A exceção pública contém somente um código seguro; valores do catálogo não
    são interpolados na mensagem.
    """

    try:
        return _build_catalog(documento)
    except _FalhaDeValidacao as failure:
        raise ErroDeCatalogo(codigo=failure.codigo) from None
    except (TypeError, ValueError, OverflowError):
        raise ErroDeCatalogo(codigo="CATALOG_SCHEMA_ERROR") from None


def catalogo_de_json(texto: str) -> CatalogoDeRegras:
    """Decodifica JSON estrito e constrói um catálogo, sem manter estado."""

    try:
        document = _decode_json(texto)
        return _build_catalog(document)
    except _FalhaDeValidacao as failure:
        raise ErroDeCatalogo(codigo=failure.codigo) from None
    except (TypeError, ValueError, OverflowError):
        raise ErroDeCatalogo(codigo="CATALOG_SCHEMA_ERROR") from None


def _read_catalog_file(path: str | os.PathLike[str]) -> str:
    try:
        resolved = Path(path)
        status = resolved.stat()
        if not stat.S_ISREG(status.st_mode):
            _falhar("CATALOG_FILE_ERROR")
        if status.st_size > _MAX_CATALOG_BYTES:
            _falhar("CATALOG_SIZE_ERROR")
        payload = resolved.read_bytes()
    except _FalhaDeValidacao:
        raise
    except (OSError, TypeError, ValueError):
        _falhar("CATALOG_FILE_ERROR")

    if len(payload) > _MAX_CATALOG_BYTES:
        _falhar("CATALOG_SIZE_ERROR")
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        _falhar("CATALOG_ENCODING_ERROR")


def carregar_catalogo(path: str | os.PathLike[str]) -> CatalogoDeRegras:
    """Lê e valida um catálogo sem criar estado global."""

    try:
        text = _read_catalog_file(path)
        document = _decode_json(text)
        return _build_catalog(document)
    except _FalhaDeValidacao as failure:
        raise ErroDeCatalogo(codigo=failure.codigo) from None
    except (TypeError, ValueError, OverflowError):
        raise ErroDeCatalogo(codigo="CATALOG_SCHEMA_ERROR") from None


def _validate_append_only(
    current: CatalogoDeRegras | None,
    candidate: CatalogoDeRegras,
) -> None:
    if current is None:
        return

    current_rules = {
        (rule.rule_id, rule.versao): rule for rule in current.regras
    }
    candidate_rules = {
        (rule.rule_id, rule.versao): rule for rule in candidate.regras
    }

    # Versões históricas não podem desaparecer nem mudar de conteúdo/digest.
    for identity, old_rule in current_rules.items():
        if candidate_rules.get(identity) != old_rule:
            _falhar("CATALOG_HISTORY_ERROR")

    maximum_by_rule: dict[str, int] = {}
    for rule in current.regras:
        maximum_by_rule[rule.rule_id] = max(
            maximum_by_rule.get(rule.rule_id, 0), rule.versao
        )
    for identity, new_rule in candidate_rules.items():
        if identity in current_rules:
            continue
        previous_maximum = maximum_by_rule.get(new_rule.rule_id)
        if previous_maximum is not None and new_rule.versao <= previous_maximum:
            _falhar("CATALOG_HISTORY_ERROR")

    if candidate != current and candidate.versao == current.versao:
        _falhar("CATALOG_VERSION_ERROR")


class CarregadorCatalogo:
    """Mantém um catálogo ativo com publicação atômica e append-only.

    A carga estrutural ocorre antes do lock. Dentro do lock, o validador aplica
    histórico e gates de ativação contra o snapshot corrente; somente o retorno
    integralmente autorizado substitui a referência ativa.
    """

    def __init__(self, validador: object | None = None) -> None:
        from log_analyzer.core.validacao_catalogo import ValidadorCatalogo

        if validador is None:
            validador = ValidadorCatalogo()
        if not isinstance(validador, ValidadorCatalogo):
            raise TypeError("validador deve ser ValidadorCatalogo ou None.")
        self._lock = RLock()
        self._catalogo_ativo: CatalogoDeRegras | None = None
        self._validador = validador

    @property
    def catalogo_ativo(self) -> CatalogoDeRegras | None:
        with self._lock:
            return self._catalogo_ativo

    @property
    def active_catalog(self) -> CatalogoDeRegras | None:
        return self.catalogo_ativo

    @property
    def versao_ativa(self) -> str | None:
        active = self.catalogo_ativo
        return None if active is None else active.versao

    @property
    def validador(self) -> object:
        return self._validador

    def obter_catalogo_ativo(self) -> CatalogoDeRegras | None:
        return self.catalogo_ativo

    def _publish(
        self,
        candidate: CatalogoDeRegras,
        *,
        pacote_validacao: object | None = None,
    ) -> CatalogoDeRegras:
        with self._lock:
            validated = self._validador.validar(
                candidate,
                anterior=self._catalogo_ativo,
                pacote=pacote_validacao,
            )
            self._catalogo_ativo = validated
            return validated

    def carregar(
        self,
        path: str | os.PathLike[str],
        *,
        pacote_validacao: object | None = None,
    ) -> CatalogoDeRegras:
        """Carrega arquivo e publica somente depois de validação integral."""

        candidate = carregar_catalogo(path)
        return self._publish(
            candidate, pacote_validacao=pacote_validacao
        )

    def carregar_json(
        self,
        texto: str,
        *,
        pacote_validacao: object | None = None,
    ) -> CatalogoDeRegras:
        """Carrega texto JSON e publica somente depois de validação integral."""

        candidate = catalogo_de_json(texto)
        return self._publish(
            candidate, pacote_validacao=pacote_validacao
        )

    def carregar_documento(
        self,
        documento: object,
        *,
        pacote_validacao: object | None = None,
    ) -> CatalogoDeRegras:
        """Carrega árvore JSON sintética e publica de forma atômica."""

        candidate = construir_catalogo(documento)
        return self._publish(
            candidate, pacote_validacao=pacote_validacao
        )


# Alias descritivo mantido sem estado adicional.
GerenciadorCatalogo = CarregadorCatalogo


__all__ = [
    "AprovacaoDeclarativa",
    "AprovacaoRegra",
    "CarregadorCatalogo",
    "CatalogoDeRegras",
    "CoberturaCatalogo",
    "CondicaoRegra",
    "EstadoRegra",
    "FixtureCatalogo",
    "FixtureRotulada",
    "GerenciadorCatalogo",
    "LacunaCatalogo",
    "PrecedenciaRegra",
    "ReferenciaFixture",
    "RegraValidada",
    "carregar_catalogo",
    "catalogo_de_json",
    "construir_catalogo",
]
