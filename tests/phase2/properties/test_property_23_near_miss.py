"""Property 23 do comportamento fail-closed diante de near-misses.

A regra, as condições e o cenário deste teste são genéricos, integralmente
sintéticos e existem somente em memória. Eles não representam nem tentam
definir a regra real do Cenário_Dourado.
"""

from __future__ import annotations

from dataclasses import replace

from hypothesis import event, given, settings, strategies as st

from log_analyzer.core.catalogo import construir_catalogo
from log_analyzer.core.classificacao import ClassificadorDeCenario
from log_analyzer.core.dsl_regras import ContextoAvaliacaoDSL, FatoEstruturado
from log_analyzer.core.modelos import Categoria


# Feature: log-analyzer-phase-2, Property 23: Near-miss da regra dourada não generaliza
@given(
    sal=st.integers(min_value=0, max_value=2**64 - 1),
    quantidade_aplicacoes=st.integers(min_value=1, max_value=4),
    quantidade_fatos=st.integers(min_value=1, max_value=5),
)
@settings(max_examples=100)
def test_property_23_near_miss_da_regra_dourada_nao_generaliza(
    sal: int,
    quantidade_aplicacoes: int,
    quantidade_fatos: int,
) -> None:
    """Cada condição necessária ausente impede qualquer match parcial.

    **Validates: Requirements 11.5**
    """

    aplicacoes = tuple(
        f"P23_APP_{sal & 0xFFFFFFFF:08X}_{indice}"
        for indice in range(quantidade_aplicacoes)
    )
    codigos_fatos = tuple(
        f"SYN_P23_FACT_{sal:016X}_{indice}"
        for indice in range(quantidade_fatos)
    )
    condicoes_aplicacao = tuple(
        {
            "condition_id": f"SYN_P23_APP_CONDITION_{sal:016X}_{indice}",
            "operator": "APPLICATION_PRESENT",
            "application": aplicacao,
        }
        for indice, aplicacao in enumerate(aplicacoes)
    )
    condicoes_fato = tuple(
        {
            "condition_id": f"SYN_P23_FACT_CONDITION_{sal:016X}_{indice}",
            "operator": "FACT_PRESENT",
            "application": aplicacoes[indice % len(aplicacoes)],
            "fact": codigo,
        }
        for indice, codigo in enumerate(codigos_fatos)
    )
    condicoes = (*condicoes_aplicacao, *condicoes_fato)
    ids_condicoes = tuple(
        sorted(str(condicao["condition_id"]) for condicao in condicoes)
    )

    rule_id = f"SYN_P23_GENERIC_RULE_{sal:016X}"
    catalog_version = f"SYN_P23_CATALOG_{sal:016X}"
    documento = {
        "schema_version": 1,
        "catalog_version": catalog_version,
        "coverage": {
            "labeled_successes": 1,
            "labeled_errors": 0,
        },
        "rules": [
            {
                "rule_id": rule_id,
                "version": 1,
                "category": "SUCESSO",
                "applications": list(aplicacoes),
                "conditions": list(condicoes),
                "evidence_selectors": list(ids_condicoes),
                "fixture_ids": [f"SYN_P23_FIXTURE_{sal:016X}"],
                "fixture_digests": [f"{sal:064x}"],
                "state": "ACTIVE",
                "approved_by": "<DOMAIN_OWNER_SYNTHETIC>",
                "approved_at": "2035-01-02T03:04:05+00:00",
                "approval_reference": f"SYN_P23_APPROVAL_{sal:016X}",
                "precedence": 0,
            }
        ],
    }
    catalogo = replace(
        construir_catalogo(documento),
        regras_autorizadas=((rule_id, 1),),
    )
    fatos = tuple(
        FatoEstruturado(
            codigo=codigo,
            aplicacao=aplicacoes[indice % len(aplicacoes)],
        )
        for indice, codigo in enumerate(codigos_fatos)
    )
    contexto_integral = ContextoAvaliacaoDSL(
        aplicacoes=aplicacoes,
        fatos=fatos,
    )
    classificador = ClassificadorDeCenario(catalogo)

    resultado_integral = classificador.classificar(contexto_integral)

    assert len(catalogo.regras) == 1
    assert resultado_integral.categoria_de_cenario is Categoria.SUCESSO
    assert resultado_integral.classificada
    assert resultado_integral.correspondencia_integral
    assert resultado_integral.regra_aplicada is not None
    assert resultado_integral.regra_aplicada.rule_id == rule_id
    assert resultado_integral.regra_aplicada.versao == 1
    assert (
        resultado_integral.regra_aplicada.catalogo_versao
        == catalog_version
    )
    assert resultado_integral.condicoes_satisfeitas == ids_condicoes
    assert tuple(
        evidencia.condicao_id for evidencia in resultado_integral.evidencias
    ) == ids_condicoes
    assert all(
        evidencia.evidencias for evidencia in resultado_integral.evidencias
    )

    near_misses: list[tuple[str, str, ContextoAvaliacaoDSL]] = []
    for condicao, aplicacao in zip(
        condicoes_aplicacao,
        aplicacoes,
        strict=True,
    ):
        near_misses.append(
            (
                "aplicacao",
                str(condicao["condition_id"]),
                replace(
                    contexto_integral,
                    aplicacoes=tuple(
                        item for item in aplicacoes if item != aplicacao
                    ),
                ),
            )
        )
    for condicao, fato_removido in zip(
        condicoes_fato,
        fatos,
        strict=True,
    ):
        near_misses.append(
            (
                "fato",
                str(condicao["condition_id"]),
                replace(
                    contexto_integral,
                    fatos=tuple(
                        fato for fato in fatos if fato != fato_removido
                    ),
                ),
            )
        )

    assert len(near_misses) == len(condicoes)
    assert {condition_id for _, condition_id, _ in near_misses} == set(
        ids_condicoes
    )

    for tipo_remocao, _, contexto_near_miss in near_misses:
        resultado = classificador.classificar(contexto_near_miss)

        assert resultado.categoria_de_cenario is Categoria.NAO_CLASSIFICADA
        assert not resultado.classificada
        assert not resultado.correspondencia_integral
        assert resultado.regra_aplicada is None
        assert resultado.condicoes_satisfeitas == ()
        assert resultado.evidencias == ()
        assert resultado.referencias_evidencia == ()
        assert resultado.versao_catalogo == catalog_version
        event(f"suporte_removido={tipo_remocao}")

    event(f"quantidade_condicoes={len(condicoes)}")
    event(f"quantidade_aplicacoes={len(aplicacoes)}")
    event(f"quantidade_fatos={len(fatos)}")
