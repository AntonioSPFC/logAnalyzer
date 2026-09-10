"""Testes sintéticos integrados de catálogo, DSL e classificação (tarefa 11.6).

As regras exercitadas neste arquivo existem somente em diretórios temporários e
não representam nem aproximam a regra real do cenário dourado. Os artefatos
distribuídos são lidos apenas para comprovar seu estado fail-closed.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

import pytest

from log_analyzer.core.catalogo import (
    CarregadorCatalogo,
    EstadoRegra,
)
from log_analyzer.core.classificacao import ClassificadorDeCenario
from log_analyzer.core.dsl_regras import (
    ContextoAvaliacaoDSL,
    FatoEstruturado,
    OPERADORES_SUPORTADOS,
)
from log_analyzer.core.excecoes import ErroDeCatalogo
from log_analyzer.core.governanca import GovernancaDeFixtures
from log_analyzer.core.modelos import (
    CampoEstruturado,
    Categoria,
    EntradaDeLog,
    EstadoCausaRaiz,
    IdentificadorTecnico,
    Proveniencia,
    ResultadoCausaRaiz,
    TipoIdentificador,
    VinculoIdentificadores,
)
from log_analyzer.core.validacao_catalogo import (
    CodigoValidacaoCatalogo,
    CoberturaDeCondicao,
    ExemploRotuladoCatalogo,
    ManifestoAtivacaoRegra,
    PacoteValidacaoCatalogo,
    PoliticaDeAmostras,
    ReferenciaVersaoRegra,
)


UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[2]
DISTRIBUTED_CATALOG = ROOT / "log_analyzer" / "catalogos" / "fase2.json"
CANDIDATE_FIXTURE = (
    ROOT / "tests" / "fixtures" / "log_analyzer_phase2" / "golden_candidate"
)


def _provenance(
    entry_id: str,
    *,
    token: str,
    line: int,
    field: str | None = None,
    rule: str = "SYN_EXTRACTOR_V1",
) -> Proveniencia:
    return Proveniencia(
        arquivo_token=token,
        entrada_id=entry_id,
        linha_inicial=line,
        linha_final=line,
        nome_campo=field,
        regra_extracao=rule,
    )


def _entry(
    application: str,
    entry_id: str,
    *,
    token: str,
    line: int,
    minute: int,
    fields: tuple[tuple[str, str], ...],
    severity: str,
) -> EntradaDeLog:
    timestamp = datetime(2025, 1, 2, 3, minute, tzinfo=UTC)
    structured_fields = tuple(
        CampoEstruturado(
            nome=name,
            valor_original=value,
            proveniencia=_provenance(
                entry_id,
                token=token,
                line=line,
                field=name,
            ),
        )
        for name, value in fields
    )
    return EntradaDeLog(
        texto_original="<SYNTHETIC_ENTRY>",
        aplicacao=application,
        ordem_de_leitura=line - 1,
        interpretada=False,
        nivel_de_severidade=severity,
        mensagem="<SYNTHETIC_ENTRY>",
        entrada_id=entry_id,
        arquivo_token=token,
        posicao_inicial=line,
        posicao_final=line,
        timestamp_original=timestamp.isoformat(),
        timestamp_normalizado=timestamp,
        campos_estruturados=structured_fields,
    )


def _structured_context() -> ContextoAvaliacaoDSL:
    vpl = _entry(
        "VPL",
        "SYN_ENTRY_VPL",
        token="<ARQUIVO_1>",
        line=1,
        minute=4,
        fields=(("SYN_STATE", "SYN_READY"),),
        severity="ERROR",
    )
    ork = _entry(
        "ORK",
        "SYN_ENTRY_ORK",
        token="<ARQUIVO_2>",
        line=2,
        minute=5,
        fields=(("SYN_RESULT", "SYN_DONE"),),
        severity="INFO",
    )
    link_evidence = _provenance(
        "SYN_ENTRY_ORK",
        token="<ARQUIVO_2>",
        line=2,
        field="SYN_LINK_DECLARATION",
        rule="SYN_LINK_EXTRACTOR_V1",
    )
    source = IdentificadorTecnico(
        tipo=TipoIdentificador.CALL_ID,
        namespace_comparacao="SYN_CALL_NAMESPACE",
        nome_campo="SYN_CALL_ID",
        valor_original="SYN_CALL_A",
        valor_normalizado="syn_call_a",
        proveniencia=link_evidence,
    )
    target = IdentificadorTecnico(
        tipo=TipoIdentificador.UUID_SESSAO,
        namespace_comparacao="SYN_SESSION_NAMESPACE",
        nome_campo="SYN_SESSION_ID",
        valor_original="SYN_SESSION_A",
        valor_normalizado="syn_session_a",
        proveniencia=link_evidence,
    )
    link = VinculoIdentificadores(
        origem=source,
        destino=target,
        tipo_relacao="SYN_CALL_TO_SESSION",
        evidencia=link_evidence,
        esquema_id="SYN_LINK_SCHEMA",
        esquema_versao=1,
        permite_correlacao=True,
    )
    fact = FatoEstruturado(
        codigo="SYN_FACT_READY",
        aplicacao="VPL",
        proveniencia=vpl.campos_estruturados[0].proveniencia,
    )
    return ContextoAvaliacaoDSL(
        entradas=(ork, vpl),
        aplicacoes=("ORK", "VPL"),
        vinculos=(link,),
        fatos=(fact,),
    )


def _application_conditions(
    *,
    condition_id: str = "SYN_CONDITION_APPLICATION",
    application: str = "VPL",
) -> list[dict[str, object]]:
    return [
        {
            "condition_id": condition_id,
            "operator": "APPLICATION_PRESENT",
            "application": application,
        }
    ]


def _all_operator_conditions() -> list[dict[str, object]]:
    return [
        {
            "condition_id": "SYN_CONDITION_APPLICATION",
            "operator": "APPLICATION_PRESENT",
            "application": "VPL",
        },
        {
            "condition_id": "SYN_CONDITION_FIELD_PRESENT",
            "operator": "FIELD_PRESENT",
            "application": "VPL",
            "field": "SYN_STATE",
        },
        {
            "condition_id": "SYN_CONDITION_FIELD_EQUALS",
            "operator": "FIELD_EQUALS",
            "application": "VPL",
            "field": "SYN_STATE",
            "expected": "SYN_READY",
        },
        {
            "condition_id": "SYN_CONDITION_EXPLICIT_LINK",
            "operator": "EXPLICIT_LINK_PRESENT",
            "relation": "SYN_CALL_TO_SESSION",
            "schema_id": "SYN_LINK_SCHEMA",
            "schema_version": 1,
            "source_type": "CALL_ID",
            "target_type": "UUID_SESSAO",
            "allows_correlation": True,
        },
        {
            "condition_id": "SYN_CONDITION_LINK",
            "operator": "LINK_PRESENT",
            "relation": "SYN_CALL_TO_SESSION",
        },
        {
            "condition_id": "SYN_CONDITION_FACT",
            "operator": "FACT_PRESENT",
            "application": "VPL",
            "fact": "SYN_FACT_READY",
        },
        {
            "condition_id": "SYN_CONDITION_CARDINALITY",
            "operator": "CARDINALITY",
            "target": "ENTRY",
            "comparison": "EQ",
            "value": 2,
        },
        {
            "condition_id": "SYN_CONDITION_TEMPORAL_ORDER",
            "operator": "TEMPORAL_ORDER",
            "before": {"application": "VPL"},
            "after": {"application": "ORK"},
        },
    ]


def _write_governed_example(
    tmp_path: Path,
    *,
    fixture_id: str,
    label: Categoria,
    context: ContextoAvaliacaoDSL,
    rule_reference: ReferenciaVersaoRegra,
) -> ExemploRotuladoCatalogo:
    directory = tmp_path / fixture_id
    directory.mkdir()
    artifact = directory / "synthetic_event.log"
    artifact.write_text("event=SYNTHETIC\n", encoding="utf-8")
    digest = sha256(artifact.read_bytes()).hexdigest()
    manifest = {
        "fixture_id": fixture_id,
        "origin": "synthetic",
        "sanitizer_version": "SYN_SANITIZER_1",
        "label": label.name,
        "validation_date": "2025-01-02",
        "approved_by": "<DOMAIN_OWNER_1>",
        "artifacts": [
            {"path": artifact.name, "sha256": digest},
        ],
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True),
        encoding="utf-8",
    )
    governance = GovernancaDeFixtures(directory).validar()
    assert governance.aprovada
    return ExemploRotuladoCatalogo(
        fixture_id=fixture_id,
        digest_sha256=digest,
        rotulo=label,
        contexto=context,
        governanca=governance,
        diversidade=(("origem", "SYNTHETIC"),),
        aplicacoes=tuple(sorted(context.aplicacoes_presentes)),
        regras_aplicaveis=(rule_reference,),
    )


def _rule_document(
    example: ExemploRotuladoCatalogo,
    *,
    rule_id: str,
    version: int = 1,
    state: str = "ACTIVE",
    category: Categoria = Categoria.SUCESSO,
    conditions: list[dict[str, object]] | None = None,
    precedence: int = 0,
    root_cause: str | None = None,
) -> dict[str, object]:
    document: dict[str, object] = {
        "rule_id": rule_id,
        "version": version,
        "category": category.name,
        "applications": ["VPL", "ORK"],
        "conditions": conditions or _application_conditions(),
        "fixture_ids": [example.fixture_id],
        "fixture_digests": [example.digest_sha256],
        "state": state,
        "approved_by": "<DOMAIN_OWNER_1>",
        "approved_at": "2025-01-02T03:04:05+00:00",
        "approval_reference": f"SYN_APPROVAL_{rule_id}_{version}",
        "precedence": precedence,
    }
    if root_cause is not None:
        document["root_cause"] = root_cause
    return document


def _fixture_document(example: ExemploRotuladoCatalogo) -> dict[str, object]:
    return {
        "fixture_id": example.fixture_id,
        "sha256": example.digest_sha256,
        "label": example.rotulo.name,
        "sanitized_origin": "SYNTHETIC_GENERATED_SOURCE",
        "validated_at": "2025-01-02T03:04:05+00:00",
        "validated_by": "<DOMAIN_OWNER_1>",
        "sanitizer_version": "SYN_SANITIZER_1",
    }


def _catalog_document(
    rules: list[dict[str, object]],
    examples: list[ExemploRotuladoCatalogo],
    *,
    version: str,
    labeled_errors: int | None = None,
) -> dict[str, object]:
    errors = (
        sum(example.rotulo is Categoria.ERRO for example in examples)
        if labeled_errors is None
        else labeled_errors
    )
    return {
        "schema_version": 1,
        "catalog_version": version,
        "coverage": {
            "labeled_successes": sum(
                example.rotulo is Categoria.SUCESSO for example in examples
            ),
            "labeled_errors": errors,
        },
        "fixtures": [_fixture_document(example) for example in examples],
        "precedence": [
            {
                "rule_id": rule["rule_id"],
                "version": rule["version"],
                "precedence": rule["precedence"],
            }
            for rule in rules
        ],
        "rules": rules,
    }


def _write_catalog(
    tmp_path: Path,
    name: str,
    document: dict[str, object],
) -> Path:
    path = tmp_path / name
    path.write_text(
        json.dumps(document, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    return path


def _manifest(
    rule: dict[str, object],
    example: ExemploRotuladoCatalogo,
    *,
    minimum_examples: int = 1,
    covered_condition_ids: tuple[str, ...] | None = None,
    produces_root_cause: bool = False,
) -> ManifestoAtivacaoRegra:
    conditions = rule["conditions"]
    assert isinstance(conditions, list)
    all_condition_ids = tuple(
        str(condition["condition_id"])
        for condition in conditions
        if isinstance(condition, dict)
    )
    selected_ids = covered_condition_ids or all_condition_ids
    return ManifestoAtivacaoRegra(
        rule_id=str(rule["rule_id"]),
        versao=int(rule["version"]),
        politica_amostras=PoliticaDeAmostras(
            quantidade_minima=minimum_examples,
            dimensoes_diversidade=("origem",),
            minimo_distintos_por_dimensao=1,
        ),
        cobertura_condicoes=tuple(
            CoberturaDeCondicao(
                condicao_id=condition_id,
                fixture_ids=(example.fixture_id,),
            )
            for condition_id in selected_ids
        ),
        exemplos_aplicaveis=(example.fixture_id,),
        produz_causa_raiz=produces_root_cause,
    )


def _package(
    pairs: tuple[
        tuple[dict[str, object], ExemploRotuladoCatalogo], ...
    ],
    *,
    produces_root_cause: bool = False,
) -> PacoteValidacaoCatalogo:
    return PacoteValidacaoCatalogo(
        manifestos=tuple(
            _manifest(
                rule,
                example,
                produces_root_cause=produces_root_cause,
            )
            for rule, example in pairs
        ),
        exemplos=tuple(example for _, example in pairs),
    )


def _assert_unclassified(result: object) -> None:
    assert result.categoria_de_cenario is Categoria.NAO_CLASSIFICADA
    assert result.regra_aplicada is None
    assert result.condicoes_satisfeitas == ()
    assert result.evidencias == ()
    assert result.causa_raiz == ResultadoCausaRaiz()
    assert result.causa_raiz.estado is EstadoCausaRaiz.NAO_DETERMINADA
    assert result.causa_raiz.regra is None


def test_catalogo_distribuido_e_fixture_candidata_permanecem_fail_closed() -> None:
    manifest = json.loads(
        (CANDIDATE_FIXTURE / "manifest.json").read_text(encoding="utf-8")
    )
    artifacts = {
        item["path"]: item["sha256"] for item in manifest["artifacts"]
    }
    assert set(artifacts) == {"ork.log", "vpl.log"}

    entries: list[EntradaDeLog] = []
    for order, (filename, application) in enumerate(
        (("vpl.log", "VPL"), ("ork.log", "ORK"))
    ):
        artifact = CANDIDATE_FIXTURE / filename
        content = artifact.read_text(encoding="utf-8")
        assert content
        assert sha256(artifact.read_bytes()).hexdigest() == artifacts[filename]
        entries.append(
            EntradaDeLog(
                texto_original=content,
                aplicacao=application,
                ordem_de_leitura=order,
                interpretada=False,
                mensagem=content,
                entrada_id=f"SYN_CANDIDATE_{application}",
                arquivo_token=f"<ARQUIVO_{order + 1}>",
                posicao_inicial=1,
                posicao_final=2,
            )
        )

    catalog = CarregadorCatalogo().carregar(DISTRIBUTED_CATALOG)
    fixture = catalog.obter_fixture(manifest["fixture_id"])

    assert manifest["candidate_kind"] == "structural"
    assert manifest["classification_status"] == "NAO_CLASSIFICADA"
    assert manifest["predicates"] == []
    assert manifest["active_rule"] is None
    assert manifest["asserts_real_success"] is False
    assert fixture is not None
    assert fixture.rotulo is Categoria.NAO_CLASSIFICADA
    assert catalog.cobertura.sucessos_rotulados == 1
    assert catalog.cobertura.erros_rotulados == 0
    assert catalog.regras == ()
    assert catalog.regras_ativas == ()
    assert not any(
        rule.categoria is Categoria.ERRO or rule.causa_raiz is not None
        for rule in catalog.regras
    )

    result = ClassificadorDeCenario(catalog).classificar(
        ContextoAvaliacaoDSL(entradas=tuple(entries))
    )

    _assert_unclassified(result)
    assert result.versao_catalogo == catalog.versao


@pytest.mark.parametrize(
    "state",
    ["DRAFT", "CANDIDATE", "APPROVED", "RETIRED"],
)
def test_estados_nao_ativos_incluindo_candidato_nunca_classificam(
    tmp_path: Path,
    state: str,
) -> None:
    context = _structured_context()
    rule_id = f"SYN_RULE_STATE_{state}"
    reference = ReferenciaVersaoRegra(rule_id, 1)
    example = _write_governed_example(
        tmp_path,
        fixture_id=f"SYN_FIXTURE_STATE_{state}",
        label=Categoria.SUCESSO,
        context=context,
        rule_reference=reference,
    )
    rule = _rule_document(
        example,
        rule_id=rule_id,
        state=state,
    )
    path = _write_catalog(
        tmp_path,
        f"catalog_{state.casefold()}.json",
        _catalog_document(
            [rule],
            [example],
            version=f"SYN_CATALOG_STATE_{state}",
        ),
    )

    catalog = CarregadorCatalogo().carregar(path)
    result = ClassificadorDeCenario(catalog).classificar(context)

    assert catalog.regras[0].estado is EstadoRegra(state)
    assert catalog.regras_declaradas_ativas == ()
    assert catalog.regras_ativas == ()
    _assert_unclassified(result)


def test_schema_e_digests_invalidos_preservam_carga_anterior_atomicamente(
    tmp_path: Path,
) -> None:
    loader = CarregadorCatalogo()
    baseline_path = _write_catalog(
        tmp_path,
        "catalog_baseline.json",
        _catalog_document([], [], version="SYN_CATALOG_BASELINE"),
    )
    baseline = loader.carregar(baseline_path)

    context = _structured_context()
    reference = ReferenciaVersaoRegra("SYN_RULE_INVALID", 1)
    example = _write_governed_example(
        tmp_path,
        fixture_id="SYN_FIXTURE_INVALID",
        label=Categoria.SUCESSO,
        context=context,
        rule_reference=reference,
    )
    rule = _rule_document(
        example,
        rule_id=reference.rule_id,
        state="CANDIDATE",
    )
    valid_candidate = _catalog_document(
        [rule],
        [example],
        version="SYN_CATALOG_INVALID_CANDIDATE",
    )

    invalid_documents: list[tuple[str, dict[str, object], str]] = []

    invalid_schema_version = deepcopy(valid_candidate)
    invalid_schema_version["schema_version"] = 2
    invalid_documents.append(
        (
            "invalid_schema_version.json",
            invalid_schema_version,
            "CATALOG_VERSION_ERROR",
        )
    )

    missing_schema_field = deepcopy(valid_candidate)
    missing_schema_field.pop("coverage")
    invalid_documents.append(
        (
            "missing_schema_field.json",
            missing_schema_field,
            "CATALOG_SCHEMA_ERROR",
        )
    )

    invalid_catalog_digest = deepcopy(valid_candidate)
    invalid_catalog_digest["catalog_digest"] = "0" * 64
    invalid_documents.append(
        (
            "invalid_catalog_digest.json",
            invalid_catalog_digest,
            "CATALOG_DIGEST_ERROR",
        )
    )

    inconsistent_fixture_digest = deepcopy(valid_candidate)
    fixtures = inconsistent_fixture_digest["fixtures"]
    assert isinstance(fixtures, list)
    assert isinstance(fixtures[0], dict)
    fixtures[0]["sha256"] = "f" * 64
    invalid_documents.append(
        (
            "inconsistent_fixture_digest.json",
            inconsistent_fixture_digest,
            "CATALOG_DIGEST_ERROR",
        )
    )

    for filename, document, expected_code in invalid_documents:
        path = _write_catalog(tmp_path, filename, document)
        with pytest.raises(ErroDeCatalogo) as failure:
            loader.carregar(path)
        assert failure.value.codigo == expected_code
        assert failure.value.mensagem == "Falha no catálogo de regras."
        assert loader.catalogo_ativo is baseline
        assert loader.versao_ativa == "SYN_CATALOG_BASELINE"


@pytest.mark.parametrize(
    ("gate", "expected_code"),
    [
        (
            "activation_evidence",
            CodigoValidacaoCatalogo.ATIVACAO_SEM_EVIDENCIA,
        ),
        ("condition_coverage", CodigoValidacaoCatalogo.COBERTURA_INCOMPLETA),
        ("sample_policy", CodigoValidacaoCatalogo.POLITICA_DE_AMOSTRAS),
        ("fixture_digest", CodigoValidacaoCatalogo.DIGEST_INVALIDO),
        ("closed_dsl", CodigoValidacaoCatalogo.AVALIACAO_DE_EXEMPLO),
    ],
)
def test_gate_incompleto_rejeita_active_e_preserva_catalogo_anterior(
    tmp_path: Path,
    gate: str,
    expected_code: CodigoValidacaoCatalogo,
) -> None:
    loader = CarregadorCatalogo()
    baseline = loader.carregar(
        _write_catalog(
            tmp_path,
            "baseline.json",
            _catalog_document([], [], version="SYN_GATE_BASELINE"),
        )
    )
    context = _structured_context()
    reference = ReferenciaVersaoRegra("SYN_RULE_GATED", 1)
    example = _write_governed_example(
        tmp_path,
        fixture_id="SYN_FIXTURE_GATED",
        label=Categoria.SUCESSO,
        context=context,
        rule_reference=reference,
    )
    conditions = [
        *_application_conditions(condition_id="SYN_GATE_APPLICATION"),
        {
            "condition_id": "SYN_GATE_FIELD",
            "operator": "FIELD_PRESENT",
            "application": "VPL",
            "field": "SYN_STATE",
        },
    ]
    if gate == "closed_dsl":
        conditions = [
            {
                "condition_id": "SYN_GATE_UNKNOWN_OPERATOR",
                "operator": "SYN_UNKNOWN_OPERATOR",
            }
        ]
    rule = _rule_document(
        example,
        rule_id=reference.rule_id,
        conditions=conditions,
    )
    candidate_path = _write_catalog(
        tmp_path,
        f"candidate_{gate}.json",
        _catalog_document(
            [rule],
            [example],
            version=f"SYN_GATE_CANDIDATE_{gate.upper()}",
        ),
    )

    package: PacoteValidacaoCatalogo | None
    if gate == "activation_evidence":
        package = None
    elif gate == "condition_coverage":
        package = PacoteValidacaoCatalogo(
            manifestos=(
                _manifest(
                    rule,
                    example,
                    covered_condition_ids=("SYN_GATE_APPLICATION",),
                ),
            ),
            exemplos=(example,),
        )
    elif gate == "sample_policy":
        package = PacoteValidacaoCatalogo(
            manifestos=(
                _manifest(rule, example, minimum_examples=2),
            ),
            exemplos=(example,),
        )
    elif gate == "fixture_digest":
        package = PacoteValidacaoCatalogo(
            manifestos=(_manifest(rule, example),),
            exemplos=(replace(example, digest_sha256="0" * 64),),
        )
    else:
        package = _package(((rule, example),))

    with pytest.raises(ErroDeCatalogo) as failure:
        loader.carregar(candidate_path, pacote_validacao=package)

    assert failure.value.codigo == expected_code.value
    assert loader.catalogo_ativo is baseline
    assert baseline.regras_ativas == ()


def test_regra_active_sintetica_aprovada_exercita_toda_a_dsl(
    tmp_path: Path,
) -> None:
    context = _structured_context()
    reference = ReferenciaVersaoRegra("SYN_RULE_ALL_OPERATORS", 1)
    example = _write_governed_example(
        tmp_path,
        fixture_id="SYN_FIXTURE_ALL_OPERATORS",
        label=Categoria.SUCESSO,
        context=context,
        rule_reference=reference,
    )
    conditions = _all_operator_conditions()
    rule = _rule_document(
        example,
        rule_id=reference.rule_id,
        conditions=conditions,
        precedence=7,
    )
    path = _write_catalog(
        tmp_path,
        "catalog_all_operators.json",
        _catalog_document(
            [rule],
            [example],
            version="SYN_CATALOG_ALL_OPERATORS",
        ),
    )

    catalog = CarregadorCatalogo().carregar(
        path,
        pacote_validacao=_package(((rule, example),)),
    )
    result = ClassificadorDeCenario(catalog).classificar(context)

    assert {condition["operator"] for condition in conditions} == set(
        OPERADORES_SUPORTADOS
    )
    assert catalog.regras_autorizadas == ((reference.rule_id, 1),)
    assert catalog.regras_ativas == catalog.regras_declaradas_ativas
    assert result.categoria_de_cenario is Categoria.SUCESSO
    assert result.regra_aplicada is not None
    assert result.regra_aplicada.rule_id == reference.rule_id
    assert result.regra_aplicada.versao == 1
    assert result.regra_aplicada.catalogo_versao == catalog.versao
    assert set(result.condicoes_satisfeitas) == {
        str(condition["condition_id"]) for condition in conditions
    }
    assert {evidence.condicao_id for evidence in result.evidencias} == set(
        result.condicoes_satisfeitas
    )
    assert result.causa_raiz == ResultadoCausaRaiz()
    assert any(
        entry.nivel_de_severidade == "ERROR" for entry in context.entradas
    )


def test_precedencia_versionada_escolhe_regra_sintetica_prioritaria(
    tmp_path: Path,
) -> None:
    context = _structured_context()
    later_reference = ReferenciaVersaoRegra("SYN_RULE_LATER", 1)
    first_reference = ReferenciaVersaoRegra("SYN_RULE_FIRST", 2)
    later_example = _write_governed_example(
        tmp_path,
        fixture_id="SYN_FIXTURE_LATER",
        label=Categoria.SUCESSO,
        context=context,
        rule_reference=later_reference,
    )
    first_example = _write_governed_example(
        tmp_path,
        fixture_id="SYN_FIXTURE_FIRST",
        label=Categoria.SUCESSO,
        context=context,
        rule_reference=first_reference,
    )
    later_rule = _rule_document(
        later_example,
        rule_id=later_reference.rule_id,
        version=later_reference.versao,
        conditions=_application_conditions(
            condition_id="SYN_CONDITION_LATER"
        ),
        precedence=20,
    )
    first_rule = _rule_document(
        first_example,
        rule_id=first_reference.rule_id,
        version=first_reference.versao,
        conditions=_application_conditions(
            condition_id="SYN_CONDITION_FIRST"
        ),
        precedence=3,
    )
    catalog_path = _write_catalog(
        tmp_path,
        "catalog_precedence.json",
        _catalog_document(
            [later_rule, first_rule],
            [later_example, first_example],
            version="SYN_CATALOG_PRECEDENCE",
        ),
    )

    catalog = CarregadorCatalogo().carregar(
        catalog_path,
        pacote_validacao=_package(
            (
                (later_rule, later_example),
                (first_rule, first_example),
            )
        ),
    )
    result = ClassificadorDeCenario(catalog).classificar(context)

    assert tuple(item.ordem for item in catalog.precedencia) == (3, 20)
    assert result.regra_aplicada is not None
    assert result.regra_aplicada.rule_id == first_reference.rule_id
    assert result.regra_aplicada.versao == first_reference.versao
    assert result.condicoes_satisfeitas == ("SYN_CONDITION_FIRST",)


def test_historico_append_only_rejeita_reescrita_e_preserva_digest(
    tmp_path: Path,
) -> None:
    context = _structured_context()
    reference_v1 = ReferenciaVersaoRegra("SYN_RULE_HISTORY", 1)
    example_v1 = _write_governed_example(
        tmp_path,
        fixture_id="SYN_FIXTURE_HISTORY_V1",
        label=Categoria.SUCESSO,
        context=context,
        rule_reference=reference_v1,
    )
    rule_v1 = _rule_document(
        example_v1,
        rule_id=reference_v1.rule_id,
        version=1,
        state="CANDIDATE",
        conditions=_application_conditions(
            condition_id="SYN_CONDITION_HISTORY_V1"
        ),
    )
    original_document = _catalog_document(
        [rule_v1],
        [example_v1],
        version="SYN_CATALOG_HISTORY_V1",
    )
    loader = CarregadorCatalogo()
    original = loader.carregar(
        _write_catalog(tmp_path, "history_v1.json", original_document)
    )
    original_digest = original.regras[0].digest_historico

    rewritten = deepcopy(original_document)
    rewritten["catalog_version"] = "SYN_CATALOG_HISTORY_REWRITTEN"
    rules = rewritten["rules"]
    assert isinstance(rules, list)
    assert isinstance(rules[0], dict)
    conditions = rules[0]["conditions"]
    assert isinstance(conditions, list)
    assert isinstance(conditions[0], dict)
    conditions[0]["application"] = "ORK"

    with pytest.raises(ErroDeCatalogo) as failure:
        loader.carregar(
            _write_catalog(tmp_path, "history_rewritten.json", rewritten)
        )

    assert failure.value.codigo == CodigoValidacaoCatalogo.HISTORICO_INVALIDO.value
    assert loader.catalogo_ativo is original
    assert original.regras[0].digest_historico == original_digest

    reference_v2 = ReferenciaVersaoRegra("SYN_RULE_HISTORY", 2)
    example_v2 = _write_governed_example(
        tmp_path,
        fixture_id="SYN_FIXTURE_HISTORY_V2",
        label=Categoria.SUCESSO,
        context=context,
        rule_reference=reference_v2,
    )
    rule_v2 = _rule_document(
        example_v2,
        rule_id=reference_v2.rule_id,
        version=2,
        state="CANDIDATE",
        conditions=_application_conditions(
            condition_id="SYN_CONDITION_HISTORY_V2"
        ),
        precedence=1,
    )
    appended_document = _catalog_document(
        [rule_v1, rule_v2],
        [example_v1, example_v2],
        version="SYN_CATALOG_HISTORY_V2",
    )
    current = loader.carregar(
        _write_catalog(tmp_path, "history_v2.json", appended_document)
    )

    assert tuple(rule.versao for rule in current.regras) == (1, 2)
    assert current.obter_regra("SYN_RULE_HISTORY", 1) is not None
    assert (
        current.obter_regra("SYN_RULE_HISTORY", 1).digest_historico
        == original_digest
    )
    assert loader.catalogo_ativo is current


@pytest.mark.parametrize(
    ("category", "root_cause", "produces_root_cause", "expected_code"),
    [
        (
            Categoria.ERRO,
            None,
            False,
            CodigoValidacaoCatalogo.ERRO_SEM_EXEMPLO,
        ),
        (
            Categoria.SUCESSO,
            "SYN_ROOT_CAUSE",
            True,
            CodigoValidacaoCatalogo.CAUSA_RAIZ_SEM_EXEMPLO,
        ),
    ],
)
def test_regra_de_erro_ou_causa_raiz_sem_amostra_de_erro_nao_e_publicada(
    tmp_path: Path,
    category: Categoria,
    root_cause: str | None,
    produces_root_cause: bool,
    expected_code: CodigoValidacaoCatalogo,
) -> None:
    loader = CarregadorCatalogo()
    baseline = loader.carregar(
        _write_catalog(
            tmp_path,
            "unsupported_baseline.json",
            _catalog_document([], [], version="SYN_UNSUPPORTED_BASELINE"),
        )
    )
    context = _structured_context()
    rule_id = (
        "SYN_RULE_ERROR_WITHOUT_SUPPORT"
        if category is Categoria.ERRO
        else "SYN_RULE_CAUSE_WITHOUT_SUPPORT"
    )
    reference = ReferenciaVersaoRegra(rule_id, 1)
    example = _write_governed_example(
        tmp_path,
        fixture_id=f"SYN_FIXTURE_{category.name}_WITHOUT_SUPPORT",
        label=category,
        context=context,
        rule_reference=reference,
    )
    rule = _rule_document(
        example,
        rule_id=rule_id,
        category=category,
        root_cause=root_cause,
    )
    path = _write_catalog(
        tmp_path,
        "unsupported_rule.json",
        _catalog_document(
            [rule],
            [example],
            version=f"SYN_CATALOG_{category.name}_WITHOUT_SUPPORT",
            labeled_errors=0,
        ),
    )
    package = PacoteValidacaoCatalogo(
        manifestos=(
            _manifest(
                rule,
                example,
                produces_root_cause=produces_root_cause,
            ),
        ),
        exemplos=(example,),
    )

    with pytest.raises(ErroDeCatalogo) as failure:
        loader.carregar(path, pacote_validacao=package)

    assert failure.value.codigo == expected_code.value
    assert loader.catalogo_ativo is baseline
    assert baseline.regras == ()
    _assert_unclassified(
        ClassificadorDeCenario(baseline).classificar(context)
    )
