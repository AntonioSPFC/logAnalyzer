"""Testes sintéticos focados da DSL fechada de regras (tarefa 11.2)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from log_analyzer.core.catalogo import CondicaoRegra
from log_analyzer.core.dsl_regras import (
    CodigoErroDSL,
    ContextoAvaliacaoDSL,
    EstadoAvaliacaoDSL,
    FatoEstruturado,
    OPERADORES_SUPORTADOS,
    OperadorDSL,
    TipoReferenciaDSL,
    avaliar_condicao,
    avaliar_condicoes,
)
from log_analyzer.core.modelos import (
    CampoEstruturado,
    EntradaDeLog,
    IdentificadorTecnico,
    Proveniencia,
    TipoIdentificador,
    VinculoIdentificadores,
)


UTC = timezone.utc


def _freeze(value: object) -> object:
    if type(value) is dict:
        return tuple(
            (key, _freeze(item))
            for key, item in sorted(value.items())
        )
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value


def _condition(
    condition_id: str,
    operator: str,
    **parameters: object,
) -> CondicaoRegra:
    return CondicaoRegra(
        condition_id=condition_id,
        operator=operator,
        parametros=tuple(
            (key, _freeze(value))
            for key, value in sorted(parameters.items())
        ),
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
    minute: int | None,
    fields: tuple[tuple[str, str], ...] = (),
    free_text: str = "<SYNTHETIC_ENTRY>",
) -> EntradaDeLog:
    provenance_by_field = tuple(
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
    timestamp = (
        None
        if minute is None
        else datetime(2025, 1, 2, 3, minute, tzinfo=UTC)
    )
    return EntradaDeLog(
        texto_original=free_text,
        aplicacao=application,
        ordem_de_leitura=line - 1,
        interpretada=False,
        mensagem=free_text,
        entrada_id=entry_id,
        arquivo_token=token,
        posicao_inicial=line,
        posicao_final=line,
        timestamp_original=(
            None if timestamp is None else timestamp.isoformat()
        ),
        timestamp_normalizado=timestamp,
        campos_estruturados=provenance_by_field,
    )


def _identifier(
    kind: TipoIdentificador,
    value: str,
    field: str,
    provenance: Proveniencia,
) -> IdentificadorTecnico:
    return IdentificadorTecnico(
        tipo=kind,
        namespace_comparacao=f"SYN_{kind.name}",
        nome_campo=field,
        valor_original=value,
        valor_normalizado=value.casefold(),
        proveniencia=provenance,
    )


def _link(
    evidence: Proveniencia,
    *,
    ambiguous: bool = False,
) -> VinculoIdentificadores:
    source = _identifier(
        TipoIdentificador.CALL_ID,
        "SYN_CALL_A",
        "CallId",
        evidence,
    )
    target = _identifier(
        TipoIdentificador.UUID_SESSAO,
        "SYN_SESSION_A",
        "SessionId",
        evidence,
    )
    return VinculoIdentificadores(
        origem=source,
        destino=target,
        tipo_relacao="SYN_CALL_TO_SESSION",
        evidencia=evidence,
        esquema_id="SYN_LINK_SCHEMA",
        esquema_versao=1,
        permite_correlacao=True,
        ambiguo=ambiguous,
    )


@pytest.fixture
def structured_context() -> ContextoAvaliacaoDSL:
    vpl = _entry(
        "VPL",
        "SYN_ENTRY_VPL",
        token="<ARQUIVO_1>",
        line=1,
        minute=4,
        fields=(("SYN_FIELD", "SYN_VALUE"),),
    )
    ork = _entry(
        "ORK",
        "SYN_ENTRY_ORK",
        token="<ARQUIVO_2>",
        line=2,
        minute=5,
        fields=(("OTHER_FIELD", "OTHER_VALUE"),),
    )
    evidence = _provenance(
        ork.entrada_id or "",
        token=ork.arquivo_token or "",
        line=ork.posicao_inicial or 1,
        field="SYN_LINK_DECLARATION",
        rule="SYN_LINK_EXTRACTOR_V1",
    )
    return ContextoAvaliacaoDSL(
        entradas=(ork, vpl),
        aplicacoes=("VPL", "ORK"),
        vinculos=(_link(evidence),),
        fatos=(
            FatoEstruturado(
                codigo="SYN_FACT_READY",
                aplicacao="VPL",
                proveniencia=vpl.campos_estruturados[0].proveniencia,
            ),
        ),
    )


def test_conjunto_de_operadores_e_fechado_e_desconhecido_falha_seguro(
    structured_context: ContextoAvaliacaoDSL,
) -> None:
    assert OPERADORES_SUPORTADOS == {
        "APPLICATION_PRESENT",
        "FIELD_PRESENT",
        "FIELD_EQUALS",
        "EXPLICIT_LINK_PRESENT",
        "LINK_PRESENT",
        "FACT_PRESENT",
        "CARDINALITY",
        "TEMPORAL_ORDER",
    }

    result = avaliar_condicao(
        _condition("SYN_UNKNOWN", "PYTHON_EXPRESSION", expression="1 + 1"),
        structured_context,
    )

    assert result.estado is EstadoAvaliacaoDSL.ERRO_SEGURO
    assert result.codigo_erro == CodigoErroDSL.OPERADOR_NAO_SUPORTADO.value
    assert result.operador == "UNKNOWN"
    assert result.referencias == ()


@pytest.mark.parametrize(
    ("condition", "expected_type"),
    [
        (
            _condition(
                "SYN_APP",
                OperadorDSL.APLICACAO_PRESENTE.value,
                application="VPL",
            ),
            TipoReferenciaDSL.APLICACAO,
        ),
        (
            _condition(
                "SYN_FIELD_PRESENT",
                OperadorDSL.CAMPO_PRESENTE.value,
                application="VPL",
                field="SYN_FIELD",
            ),
            TipoReferenciaDSL.CAMPO,
        ),
        (
            _condition(
                "SYN_FIELD_EQUALS",
                OperadorDSL.CAMPO_IGUAL.value,
                application="VPL",
                field="SYN_FIELD",
                expected="SYN_VALUE",
            ),
            TipoReferenciaDSL.CAMPO,
        ),
        (
            _condition(
                "SYN_LINK",
                OperadorDSL.VINCULO_EXPLICITO_PRESENTE.value,
                relation="SYN_CALL_TO_SESSION",
                schema_id="SYN_LINK_SCHEMA",
                schema_version=1,
                source_type="CALL_ID",
                target_type="uuid_sessao",
                allows_correlation=True,
            ),
            TipoReferenciaDSL.VINCULO,
        ),
        (
            _condition(
                "SYN_FACT",
                OperadorDSL.FATO_PRESENTE.value,
                application="VPL",
                fact="SYN_FACT_READY",
            ),
            TipoReferenciaDSL.FATO,
        ),
    ],
)
def test_operadores_de_presenca_usam_somente_dados_estruturados(
    structured_context: ContextoAvaliacaoDSL,
    condition: CondicaoRegra,
    expected_type: TipoReferenciaDSL,
) -> None:
    result = avaliar_condicao(condition, structured_context)

    assert result.estado is EstadoAvaliacaoDSL.SATISFEITA
    assert result.codigo_erro is None
    assert result.referencias
    assert {reference.tipo for reference in result.referencias} == {
        expected_type
    }
    assert all("SYN_VALUE" not in reference.chave for reference in result.referencias)
    assert all("SYN_CALL_A" not in reference.chave for reference in result.referencias)


def test_cardinalidade_conta_colecoes_tipadas_com_comparadores_fechados(
    structured_context: ContextoAvaliacaoDSL,
) -> None:
    at_least = avaliar_condicao(
        _condition(
            "SYN_FIELD_COUNT",
            OperadorDSL.CARDINALIDADE.value,
            target="FIELD",
            comparison="AT_LEAST",
            value=2,
        ),
        structured_context,
    )
    no_fact = avaliar_condicao(
        _condition(
            "SYN_ABSENT_FACT_COUNT",
            OperadorDSL.CARDINALIDADE.value,
            target="FACT",
            comparison="EQ",
            value=0,
            fact="SYN_FACT_ABSENT",
        ),
        structured_context,
    )
    wrong_count = avaliar_condicao(
        _condition(
            "SYN_ENTRY_COUNT",
            OperadorDSL.CARDINALIDADE.value,
            target="ENTRY",
            comparison="EQ",
            value=3,
        ),
        structured_context,
    )

    assert at_least.satisfeita
    assert len(at_least.referencias) == 2
    assert no_fact.satisfeita
    assert no_fact.referencias == ()
    assert wrong_count.estado is EstadoAvaliacaoDSL.NAO_SATISFEITA
    assert wrong_count.referencias == ()


def test_ordem_temporal_usa_apenas_utc_normalizado_e_semantica_total(
    structured_context: ContextoAvaliacaoDSL,
) -> None:
    condition = _condition(
        "SYN_TEMPORAL_ORDER",
        OperadorDSL.ORDEM_TEMPORAL.value,
        before={"application": "VPL"},
        after={"application": "ORK"},
    )

    result = avaliar_condicao(condition, structured_context)
    reversed_context = ContextoAvaliacaoDSL(
        entradas=tuple(reversed(structured_context.entradas)),
        aplicacoes=tuple(reversed(structured_context.aplicacoes)),
        vinculos=tuple(reversed(structured_context.vinculos)),
        fatos=tuple(reversed(structured_context.fatos)),
    )
    repeated = avaliar_condicao(condition, reversed_context)

    assert result.satisfeita
    assert result == repeated
    assert len(result.referencias) == 2
    assert {reference.tipo for reference in result.referencias} == {
        TipoReferenciaDSL.ENTRADA
    }

    without_utc = _entry(
        "VPL",
        "SYN_NO_UTC",
        token="<ARQUIVO_3>",
        line=3,
        minute=None,
    )
    missing_time_context = ContextoAvaliacaoDSL(
        entradas=(without_utc, structured_context.entradas[0]),
    )
    missing = avaliar_condicao(condition, missing_time_context)
    assert missing.estado is EstadoAvaliacaoDSL.NAO_SATISFEITA
    assert missing.codigo_erro is None


def test_ordem_temporal_pode_selecionar_fatos_sem_ler_mensagens(
    structured_context: ContextoAvaliacaoDSL,
) -> None:
    ork = next(
        entry for entry in structured_context.entradas if entry.aplicacao == "ORK"
    )
    context = ContextoAvaliacaoDSL(
        entradas=structured_context.entradas,
        fatos=(
            *structured_context.fatos,
            FatoEstruturado(
                codigo="SYN_FACT_FINISHED",
                aplicacao="ORK",
                proveniencia=_provenance(
                    ork.entrada_id or "",
                    token=ork.arquivo_token or "",
                    line=ork.posicao_inicial or 1,
                ),
            ),
        ),
    )
    condition = _condition(
        "SYN_FACT_ORDER",
        OperadorDSL.ORDEM_TEMPORAL.value,
        before={"fact": "SYN_FACT_READY", "application": "VPL"},
        after={"fact": "SYN_FACT_FINISHED", "application": "ORK"},
    )

    assert avaliar_condicao(condition, context).satisfeita


def test_texto_livre_nao_cria_campo_fato_aplicacao_ou_vinculo() -> None:
    payload = (
        "FIELD=SYN_VALUE FACT=SYN_FACT_READY "
        "LINK=SYN_CALL_TO_SESSION APPLICATION=ORK"
    )
    entry = _entry(
        "VPL",
        "SYN_FREE_TEXT_ONLY",
        token="<ARQUIVO_4>",
        line=4,
        minute=6,
        free_text=payload,
    )
    context = ContextoAvaliacaoDSL(entradas=(entry,))
    conditions = (
        _condition(
            "SYN_NO_FIELD",
            OperadorDSL.CAMPO_PRESENTE.value,
            field="FIELD",
        ),
        _condition(
            "SYN_NO_FACT",
            OperadorDSL.FATO_PRESENTE.value,
            fact="SYN_FACT_READY",
        ),
        _condition(
            "SYN_NO_LINK",
            OperadorDSL.VINCULO_PRESENTE.value,
            relation="SYN_CALL_TO_SESSION",
        ),
        _condition(
            "SYN_NO_ORK",
            OperadorDSL.APLICACAO_PRESENTE.value,
            application="ORK",
        ),
    )

    results = tuple(avaliar_condicao(item, context) for item in conditions)
    assert all(
        result.estado is EstadoAvaliacaoDSL.NAO_SATISFEITA
        for result in results
    )


def test_vinculo_ambiguo_nunca_satisfaz_predicado_de_regra(
    structured_context: ContextoAvaliacaoDSL,
) -> None:
    ambiguous = ContextoAvaliacaoDSL(
        entradas=structured_context.entradas,
        vinculos=(_link(structured_context.vinculos[0].evidencia, ambiguous=True),),
    )
    condition = _condition(
        "SYN_AMBIGUOUS_LINK",
        OperadorDSL.VINCULO_PRESENTE.value,
        relation="SYN_CALL_TO_SESSION",
    )

    result = avaliar_condicao(condition, ambiguous)

    assert result.estado is EstadoAvaliacaoDSL.NAO_SATISFEITA
    assert result.referencias == ()


def test_parametros_malformados_e_objetos_executaveis_viram_erro_seguro(
    structured_context: ContextoAvaliacaoDSL,
) -> None:
    class Trap:
        def __call__(self) -> None:  # pragma: no cover - nunca deve executar
            raise AssertionError("callable executado")

        def __str__(self) -> str:  # pragma: no cover - nunca deve executar
            raise AssertionError("objeto convertido para texto")

        def __eq__(self, _other: object) -> bool:  # pragma: no cover
            raise AssertionError("objeto comparado")

    conditions = (
        CondicaoRegra(
            condition_id="SYN_CALLABLE",
            operator=OperadorDSL.CAMPO_IGUAL.value,
            parametros=(
                ("field", "SYN_FIELD"),
                ("expected", Trap()),
            ),
        ),
        _condition(
            "SYN_REGEX_PARAMETER",
            OperadorDSL.CAMPO_PRESENTE.value,
            field="SYN_FIELD",
            regex=".*",
        ),
        _condition(
            "SYN_SQL_PARAMETER",
            OperadorDSL.FATO_PRESENTE.value,
            fact="SYN_FACT_READY",
            sql="SELECT SYNTHETIC_COLUMN",
        ),
        _condition(
            "SYN_BAD_TEMPORAL_SELECTOR",
            OperadorDSL.ORDEM_TEMPORAL.value,
            before={"application": "VPL", "entry_id": "SYN_ENTRY_VPL"},
            after={"application": "ORK"},
        ),
    )

    for condition in conditions:
        result = avaliar_condicao(condition, structured_context)
        assert result.estado is EstadoAvaliacaoDSL.ERRO_SEGURO
        assert result.codigo_erro == CodigoErroDSL.PARAMETROS_INVALIDOS.value
        assert result.referencias == ()


def test_conjuncao_e_fail_closed_e_referencias_sao_deterministicas(
    structured_context: ContextoAvaliacaoDSL,
) -> None:
    satisfied = _condition(
        "SYN_A_SATISFIED",
        OperadorDSL.APLICACAO_PRESENTE.value,
        application="VPL",
    )
    also_satisfied = _condition(
        "SYN_B_SATISFIED",
        OperadorDSL.FATO_PRESENTE.value,
        fact="SYN_FACT_READY",
    )
    absent = _condition(
        "SYN_C_ABSENT",
        OperadorDSL.APLICACAO_PRESENTE.value,
        application="VOCI",
    )
    invalid = _condition("SYN_D_INVALID", "EVAL", source="synthetic")

    all_satisfied = avaliar_condicoes(
        (also_satisfied, satisfied), structured_context
    )
    partial = avaliar_condicoes(
        (absent, also_satisfied, satisfied), structured_context
    )
    error = avaliar_condicoes(
        (satisfied, invalid), structured_context
    )
    empty = avaliar_condicoes((), structured_context)
    duplicate = avaliar_condicoes(
        (satisfied, satisfied), structured_context
    )

    assert all_satisfied.estado is EstadoAvaliacaoDSL.SATISFEITA
    assert all_satisfied.condicoes_satisfeitas == (
        "SYN_A_SATISFIED",
        "SYN_B_SATISFIED",
    )
    assert tuple(
        reference.condicao_id
        for reference in all_satisfied.referencias_satisfeitas
    ) == all_satisfied.condicoes_satisfeitas

    assert partial.estado is EstadoAvaliacaoDSL.NAO_SATISFEITA
    assert partial.condicoes_satisfeitas == (
        "SYN_A_SATISFIED",
        "SYN_B_SATISFIED",
    )
    assert error.estado is EstadoAvaliacaoDSL.ERRO_SEGURO
    assert error.codigo_erro == CodigoErroDSL.OPERADOR_NAO_SUPORTADO.value
    assert empty.codigo_erro == CodigoErroDSL.SEM_CONDICOES.value
    assert duplicate.codigo_erro == CodigoErroDSL.CONDICAO_DUPLICADA.value


def test_field_equals_do_catalogo_permanece_dado_inerte_e_exato(
    structured_context: ContextoAvaliacaoDSL,
) -> None:
    inert_payload = "__import__('synthetic_module').run()"
    condition = _condition(
        "SYN_INERT_EXPECTED",
        "FIELD_EQUALS",
        field="SYN_FIELD",
        expected=inert_payload,
    )

    result = avaliar_condicao(condition, structured_context)

    assert result.estado is EstadoAvaliacaoDSL.NAO_SATISFEITA
    assert result.codigo_erro is None
    assert inert_payload not in repr(result)


def test_ordem_temporal_igual_exige_permissao_explicita() -> None:
    timestamp = datetime(2025, 1, 2, 3, 4, tzinfo=UTC)
    first = _entry(
        "VPL",
        "SYN_EQUAL_FIRST",
        token="<ARQUIVO_5>",
        line=5,
        minute=4,
    )
    second = _entry(
        "ORK",
        "SYN_EQUAL_SECOND",
        token="<ARQUIVO_6>",
        line=6,
        minute=4,
    )
    assert first.timestamp_normalizado == timestamp
    assert second.timestamp_normalizado == timestamp
    context = ContextoAvaliacaoDSL(entradas=(first, second))
    strict = _condition(
        "SYN_STRICT_TIME",
        OperadorDSL.ORDEM_TEMPORAL.value,
        before={"entry_id": "SYN_EQUAL_FIRST"},
        after={"entry_id": "SYN_EQUAL_SECOND"},
    )
    inclusive = _condition(
        "SYN_INCLUSIVE_TIME",
        OperadorDSL.ORDEM_TEMPORAL.value,
        before={"entry_id": "SYN_EQUAL_FIRST"},
        after={"entry_id": "SYN_EQUAL_SECOND"},
        allow_equal=True,
    )

    assert avaliar_condicao(strict, context).nao_satisfeita
    assert avaliar_condicao(inclusive, context).satisfeita


def test_contexto_e_resultados_nao_mutam_colecoes_de_entrada(
    structured_context: ContextoAvaliacaoDSL,
) -> None:
    original_entries = structured_context.entradas
    original_fields = tuple(
        entry.campos_estruturados for entry in original_entries
    )
    condition = _condition(
        "SYN_NO_MUTATION",
        OperadorDSL.CARDINALIDADE.value,
        target="ENTRY",
        comparison="GTE",
        value=1,
    )

    first = avaliar_condicao(condition, structured_context)
    second = avaliar_condicao(condition, structured_context)

    assert first == second
    assert structured_context.entradas is original_entries
    assert tuple(entry.campos_estruturados for entry in original_entries) == original_fields
