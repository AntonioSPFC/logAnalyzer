"""Testes focados dos modelos e da carga atômica do catálogo (tarefa 11.1)."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
from hashlib import sha256
import json

import pytest

from log_analyzer.core.catalogo import (
    CarregadorCatalogo,
    EstadoRegra,
    catalogo_de_json,
    carregar_catalogo,
)
from log_analyzer.core.excecoes import ErroDeCatalogo
from log_analyzer.core.modelos import Categoria


def _digest(token: str) -> str:
    return sha256(token.encode("ascii")).hexdigest()


def _rule(
    *,
    rule_id: str = "SYN_RULE_01",
    version: int = 1,
    fixture_id: str = "SYN_FIXTURE_01",
    precedence: int = 0,
) -> dict[str, object]:
    return {
        "rule_id": rule_id,
        "version": version,
        "category": "SUCESSO",
        "applications": ["VPL", "ORK"],
        "conditions": [
            {
                "condition_id": f"SYN_CONDITION_{version:02d}",
                "operator": "FIELD_EQUALS",
                "field": "SYN_FIELD",
                "expected": "<CALL_ID_1>",
            }
        ],
        "fixture_ids": [fixture_id],
        "fixture_digests": [_digest(fixture_id)],
        "state": "CANDIDATE",
        "approved_by": "<DOMAIN_OWNER_1>",
        "approved_at": "2025-01-02T03:04:05+00:00",
        "approval_reference": "SYN_APPROVAL_01",
        "precedence": precedence,
    }


def _catalog(*, version: str = "SYN_CATALOG_1") -> dict[str, object]:
    return {
        "schema_version": 1,
        "catalog_version": version,
        "coverage": {
            "labeled_successes": 1,
            "labeled_errors": 0,
        },
        "rules": [_rule()],
    }


def test_carrega_json_compacto_em_modelos_profundamente_imutaveis(
    tmp_path,
) -> None:
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(_catalog()), encoding="utf-8")

    catalog = carregar_catalogo(path)

    assert catalog.versao == "SYN_CATALOG_1"
    assert catalog.schema_version == 1
    assert catalog.cobertura.declaracao == (
        "1 cenário de sucesso; 0 cenários de erro"
    )
    assert catalog.cobertura.sucessos_rotulados == 1
    assert catalog.cobertura.erros_rotulados == 0
    assert catalog.lacunas
    assert len(catalog.regras) == 1
    assert len(catalog.fixtures) == 1

    rule = catalog.regras[0]
    assert rule.categoria is Categoria.SUCESSO
    assert rule.estado is EstadoRegra.CANDIDATE
    assert rule.aplicacoes == ("ORK", "VPL")
    assert rule.fixture_ids == ("SYN_FIXTURE_01",)
    assert rule.fixtures_suporte[0].digest_sha256 == _digest(
        "SYN_FIXTURE_01"
    )
    assert rule.aprovacao.aprovado_por == "<DOMAIN_OWNER_1>"
    assert rule.condicoes[0].expected == "<CALL_ID_1>"
    assert catalog.fixtures[0].incorporada is False

    with pytest.raises(FrozenInstanceError):
        rule.precedencia = 7  # type: ignore[misc]
    with pytest.raises(TypeError):
        rule.condicoes[0].parametros[0] = ("field", "alterado")  # type: ignore[index]


def test_fixture_incorporada_e_precedencia_validam_referencias() -> None:
    document = _catalog()
    document["fixtures"] = [
        {
            "fixture_id": "SYN_FIXTURE_01",
            "sha256": _digest("SYN_FIXTURE_01"),
            "label": "SUCESSO",
            "sanitized_origin": "SYNTHETIC_GENERATED_SOURCE",
            "validated_at": "2025-01-02T03:04:05Z",
            "validated_by": "<DOMAIN_OWNER_1>",
            "sanitizer_version": "SYN_SANITIZER_1",
        }
    ]
    document["precedence"] = [
        {
            "rule_id": "SYN_RULE_01",
            "version": 1,
            "precedence": 0,
        }
    ]

    catalog = catalogo_de_json(json.dumps(document))

    fixture = catalog.fixtures[0]
    assert fixture.incorporada is True
    assert fixture.rotulo is Categoria.SUCESSO
    assert fixture.origem_sanitizada == "SYNTHETIC_GENERATED_SOURCE"
    assert fixture.responsavel_dominio == "<DOMAIN_OWNER_1>"
    assert catalog.precedencia[0].rule_id == "SYN_RULE_01"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda data: data.pop("coverage"), "CATALOG_SCHEMA_ERROR"),
        (
            lambda data: data.__setitem__("schema_version", True),
            "CATALOG_VERSION_ERROR",
        ),
        (
            lambda data: data["rules"][0].__setitem__("version", 0),
            "CATALOG_SCHEMA_ERROR",
        ),
        (
            lambda data: data["rules"][0].__setitem__(
                "fixture_digests", ["not-a-sha256"]
            ),
            "CATALOG_DIGEST_ERROR",
        ),
        (
            lambda data: data["rules"][0].__setitem__(
                "evidence_selectors", ["UNKNOWN_CONDITION"]
            ),
            "CATALOG_REFERENCE_ERROR",
        ),
    ],
)
def test_rejeita_schema_tipos_versoes_digests_e_referencias(
    mutation,
    code: str,
) -> None:
    document = _catalog()
    mutation(document)

    with pytest.raises(ErroDeCatalogo) as failure:
        catalogo_de_json(json.dumps(document))

    assert failure.value.codigo == code
    assert failure.value.mensagem == "Falha no catálogo de regras."


def test_condicao_permanece_dado_inerte_sem_execucao() -> None:
    document = _catalog()
    condition = document["rules"][0]["conditions"][0]
    condition["expected"] = "__import__('synthetic_module').run()"
    condition["metadata"] = {
        "template_like": "{{ synthetic_value }}",
        "sql_like": "SELECT synthetic_column FROM synthetic_table",
    }

    catalog = catalogo_de_json(json.dumps(document))
    loaded = catalog.regras[0].condicoes[0]

    assert loaded.expected == "__import__('synthetic_module').run()"
    assert isinstance(loaded.obter_parametro("metadata"), tuple)


def test_falha_preserva_catalogo_anterior_ou_nenhum_catalogo_ativo(
    tmp_path,
) -> None:
    loader = CarregadorCatalogo()
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text('{"catalog_version":', encoding="utf-8")

    with pytest.raises(ErroDeCatalogo):
        loader.carregar(invalid_path)
    assert loader.catalogo_ativo is None

    valid_path = tmp_path / "valid.json"
    valid_path.write_text(json.dumps(_catalog()), encoding="utf-8")
    previous = loader.carregar(valid_path)

    invalid_document = _catalog(version="SYN_CATALOG_2")
    invalid_document["rules"][0]["fixture_digests"] = ["not-a-sha256"]
    invalid_path.write_text(json.dumps(invalid_document), encoding="utf-8")

    with pytest.raises(ErroDeCatalogo) as failure:
        loader.carregar(invalid_path)

    assert failure.value.codigo == "CATALOG_DIGEST_ERROR"
    assert loader.catalogo_ativo is previous
    assert loader.versao_ativa == "SYN_CATALOG_1"


def test_historico_e_append_only_e_aceita_somente_nova_versao() -> None:
    loader = CarregadorCatalogo()
    original_document = _catalog()
    original = loader.carregar_documento(original_document)

    changed_history = deepcopy(original_document)
    changed_history["catalog_version"] = "SYN_CATALOG_2"
    changed_history["rules"][0]["conditions"][0]["expected"] = "CHANGED"
    with pytest.raises(ErroDeCatalogo) as failure:
        loader.carregar_documento(changed_history)
    assert failure.value.codigo == "CATALOG_HISTORY_ERROR"
    assert loader.catalogo_ativo is original

    appended = deepcopy(original_document)
    appended["catalog_version"] = "SYN_CATALOG_2"
    appended["rules"].append(
        _rule(version=2, fixture_id="SYN_FIXTURE_02", precedence=1)
    )
    current = loader.carregar_documento(appended)

    assert current.versao == "SYN_CATALOG_2"
    assert tuple(rule.versao for rule in current.regras) == (1, 2)
    assert loader.catalogo_ativo is current


def test_json_com_chave_duplicada_e_digest_de_catalogo_invalido_falha() -> None:
    with pytest.raises(ErroDeCatalogo) as duplicate_failure:
        catalogo_de_json(
            '{"catalog_version":"SYN_CATALOG_1",'
            '"catalog_version":"SYN_CATALOG_2",'
            '"coverage":{"labeled_successes":1,"labeled_errors":0},'
            '"rules":[]}'
        )
    assert duplicate_failure.value.codigo == "CATALOG_JSON_ERROR"

    document = _catalog()
    document["catalog_digest"] = "0" * 64
    with pytest.raises(ErroDeCatalogo) as digest_failure:
        catalogo_de_json(json.dumps(document))
    assert digest_failure.value.codigo == "CATALOG_DIGEST_ERROR"


def test_schema_version_e_obrigatoria_e_somente_a_versao_suportada() -> None:
    sem_versao = _catalog()
    sem_versao.pop("schema_version")

    with pytest.raises(ErroDeCatalogo) as ausente:
        catalogo_de_json(json.dumps(sem_versao))
    assert ausente.value.codigo == "CATALOG_VERSION_ERROR"

    versao_desconhecida = _catalog()
    versao_desconhecida["schema_version"] = 2
    with pytest.raises(ErroDeCatalogo) as desconhecida:
        catalogo_de_json(json.dumps(versao_desconhecida))
    assert desconhecida.value.codigo == "CATALOG_VERSION_ERROR"


def test_todos_os_modelos_do_catalogo_sao_profundamente_imutaveis() -> None:
    document = _catalog()
    document["fixtures"] = [
        {
            "fixture_id": "SYN_FIXTURE_01",
            "sha256": _digest("SYN_FIXTURE_01"),
            "label": "SUCESSO",
            "sanitized_origin": "SYNTHETIC_GENERATED_SOURCE",
            "validated_at": "2025-01-02T03:04:05Z",
            "validated_by": "<DOMAIN_OWNER_1>",
            "sanitizer_version": "SYN_SANITIZER_1",
        }
    ]
    document["precedence"] = [
        {"rule_id": "SYN_RULE_01", "version": 1, "precedence": 0}
    ]
    catalog = catalogo_de_json(json.dumps(document))
    rule = catalog.regras[0]

    mutations = (
        (catalog, "versao", "SYN_CATALOG_CHANGED"),
        (catalog.cobertura, "declaracao", "alterada"),
        (catalog.cobertura.lacunas[0], "descricao", "alterada"),
        (catalog.fixtures[0], "fixture_id", "SYN_FIXTURE_CHANGED"),
        (rule, "estado", EstadoRegra.ACTIVE),
        (rule.condicoes[0], "operator", "CHANGED"),
        (rule.aprovacao, "aprovado_por", "<DOMAIN_OWNER_2>"),
        (rule.precedencia_declarada, "ordem", 99),
        (rule.fixtures_suporte[0], "digest_sha256", "0" * 64),
    )
    for model, attribute, value in mutations:
        with pytest.raises(FrozenInstanceError):
            setattr(model, attribute, value)

    assert tuple(state.value for state in EstadoRegra) == (
        "DRAFT",
        "CANDIDATE",
        "APPROVED",
        "ACTIVE",
        "RETIRED",
    )


def _adicionar_fixture_com_digest_inconsistente(
    document: dict[str, object],
) -> None:
    document["fixtures"] = [
        {
            "fixture_id": "SYN_FIXTURE_01",
            "sha256": _digest("SYN_FIXTURE_DIFFERENT"),
            "label": "SUCESSO",
            "sanitized_origin": "SYNTHETIC_GENERATED_SOURCE",
            "validated_at": "2025-01-02T03:04:05Z",
            "validated_by": "<DOMAIN_OWNER_1>",
        }
    ]


def _adicionar_precedencia_inconsistente(
    document: dict[str, object],
) -> None:
    document["precedence"] = [
        {"rule_id": "SYN_RULE_UNKNOWN", "version": 1, "precedence": 0}
    ]


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda data: data["rules"][0].__setitem__("rule_id", "../INVALID"),
            "CATALOG_SCHEMA_ERROR",
        ),
        (
            lambda data: data["rules"][0]["conditions"][0].__setitem__(
                "condition_id", "INVALID/CONDITION"
            ),
            "CATALOG_SCHEMA_ERROR",
        ),
        (
            lambda data: data["rules"][0].__setitem__(
                "fixture_ids", ["INVALID/FIXTURE"]
            ),
            "CATALOG_SCHEMA_ERROR",
        ),
        (
            lambda data: data["rules"][0].__setitem__("version", True),
            "CATALOG_SCHEMA_ERROR",
        ),
        (
            lambda data: data["rules"][0].__setitem__("state", "EXECUTABLE"),
            "CATALOG_SCHEMA_ERROR",
        ),
        (
            lambda data: data["rules"][0].__setitem__(
                "applications", ["vpl", "ORK"]
            ),
            "CATALOG_SCHEMA_ERROR",
        ),
        (
            lambda data: data.__setitem__("unexpected", "inert"),
            "CATALOG_SCHEMA_ERROR",
        ),
        (_adicionar_fixture_com_digest_inconsistente, "CATALOG_DIGEST_ERROR"),
        (_adicionar_precedencia_inconsistente, "CATALOG_REFERENCE_ERROR"),
    ],
)
def test_validacao_estrita_preserva_snapshot_anterior_em_toda_falha(
    mutation,
    code: str,
) -> None:
    loader = CarregadorCatalogo()
    previous = loader.carregar_documento(_catalog())
    candidate = _catalog(version="SYN_CATALOG_2")
    mutation(candidate)

    with pytest.raises(ErroDeCatalogo) as failure:
        loader.carregar_documento(candidate)

    assert failure.value.codigo == code
    assert failure.value.mensagem == "Falha no catálogo de regras."
    assert loader.catalogo_ativo is previous


def test_catalogo_sem_regra_ativa_nao_introduz_classificacao() -> None:
    from log_analyzer.core.modelos import ResultadoDeAnalise

    document = _catalog()
    document["rules"] = []
    catalog = catalogo_de_json(json.dumps(document))

    assert catalog.regras == ()
    assert catalog.regras_ativas == ()
    assert catalog.active_rules == ()
    assert (
        ResultadoDeAnalise(identificador="<CALL_ID_1>").categoria_de_cenario
        is Categoria.NAO_CLASSIFICADA
    )
