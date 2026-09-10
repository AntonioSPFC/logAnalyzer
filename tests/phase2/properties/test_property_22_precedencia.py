"""Property 22 da precedência versionada determinística da Fase 2.

Todos os catálogos, regras e contextos são sintéticos e construídos em
memória. Cada exemplo usa duas ordens físicas distintas para o mesmo conteúdo
semântico e um catálogo conflitante separado para verificar o fail-closed.
"""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json

from hypothesis import event, given, settings, strategies as st

from log_analyzer.core.catalogo import catalogo_de_json
from log_analyzer.core.classificacao import (
    SEM_CATALOGO_ATIVO,
    ClassificadorDeCenario,
)
from log_analyzer.core.dsl_regras import ContextoAvaliacaoDSL
from log_analyzer.core.modelos import Categoria, ReferenciaRegra


# Feature: log-analyzer-phase-2, Property 22: Precedência versionada é determinística
@given(
    dados=st.data(),
    quantidade_regras=st.integers(min_value=2, max_value=6),
    sal=st.integers(min_value=0, max_value=2**64 - 1),
)
@settings(max_examples=100)
def test_property_22_precedencia_versionada_e_deterministica(
    dados,
    quantidade_regras: int,
    sal: int,
) -> None:
    """A menor precedência vence em qualquer ordem; conflito falha fechado.

    **Validates: Requirements 10.6**
    """

    indices = tuple(range(quantidade_regras))
    versoes = tuple(
        dados.draw(
            st.lists(
                st.integers(min_value=1, max_value=10_000),
                min_size=quantidade_regras,
                max_size=quantidade_regras,
                unique=True,
            ),
            label="versoes",
        )
    )
    precedencias = tuple(
        dados.draw(
            st.permutations(indices),
            label="precedencias_por_regra",
        )
    )
    ordem_fisica_a = tuple(
        dados.draw(
            st.permutations(indices),
            label="ordem_fisica_a",
        )
    )
    deslocamento = dados.draw(
        st.integers(min_value=1, max_value=quantidade_regras - 1),
        label="deslocamento_ordem_fisica_b",
    )
    ordem_fisica_b = (
        ordem_fisica_a[deslocamento:]
        + ordem_fisica_a[:deslocamento]
    )

    regras_semanticas: list[dict[str, object]] = []
    precedencias_semanticas: list[dict[str, object]] = []
    categorias: list[Categoria] = []
    for indice in indices:
        versao = versoes[indice]
        categoria = (
            Categoria.SUCESSO
            if (indice + sal) % 2 == 0
            else Categoria.ERRO
        )
        categorias.append(categoria)
        rule_id = f"SYN_P22_RULE_{sal:016X}_{indice:02d}"
        condition_id = f"SYN_P22_CONDITION_{sal:016X}_{indice:02d}"
        fixture_id = f"SYN_P22_FIXTURE_{sal:016X}_{indice:02d}"
        fixture_digest = sha256(
            f"property-22:{sal}:{indice}:{versao}".encode("ascii")
        ).hexdigest()
        regra = {
            "rule_id": rule_id,
            "version": versao,
            "category": categoria.name,
            "applications": ["VPL"],
            "conditions": [
                {
                    "condition_id": condition_id,
                    "operator": "APPLICATION_PRESENT",
                    "application": "VPL",
                }
            ],
            "evidence_selectors": [condition_id],
            "fixture_ids": [fixture_id],
            "fixture_digests": [fixture_digest],
            "state": "ACTIVE",
            "approved_by": "<DOMAIN_OWNER_SYNTHETIC>",
            "approved_at": "2035-01-02T03:04:05+00:00",
            "approval_reference": (
                f"SYN_P22_APPROVAL_{sal:016X}_{indice:02d}"
            ),
            "precedence": precedencias[indice],
        }
        regras_semanticas.append(regra)
        precedencias_semanticas.append(
            {
                "rule_id": rule_id,
                "version": versao,
                "precedence": precedencias[indice],
            }
        )

    cobertura = {
        "labeled_successes": sum(
            categoria is Categoria.SUCESSO for categoria in categorias
        ),
        "labeled_errors": sum(
            categoria is Categoria.ERRO for categoria in categorias
        ),
    }
    versao_catalogo = f"SYN_P22_CATALOG_{sal:016X}"
    documento_a = {
        "schema_version": 1,
        "catalog_version": versao_catalogo,
        "coverage": cobertura,
        "rules": [regras_semanticas[indice] for indice in ordem_fisica_a],
        "precedence": [
            precedencias_semanticas[indice]
            for indice in reversed(ordem_fisica_a)
        ],
    }
    documento_b = {
        "schema_version": 1,
        "catalog_version": versao_catalogo,
        "coverage": cobertura,
        "rules": [regras_semanticas[indice] for indice in ordem_fisica_b],
        "precedence": [
            precedencias_semanticas[indice]
            for indice in reversed(ordem_fisica_b)
        ],
    }
    assert documento_a["rules"] != documento_b["rules"]
    assert documento_a["precedence"] != documento_b["precedence"]

    catalogo_a_carregado = catalogo_de_json(
        json.dumps(documento_a, separators=(",", ":"))
    )
    catalogo_b_carregado = catalogo_de_json(
        json.dumps(documento_b, separators=(",", ":"))
    )
    autorizadas_a = tuple(
        (
            str(regras_semanticas[indice]["rule_id"]),
            int(regras_semanticas[indice]["version"]),
        )
        for indice in ordem_fisica_a
    )
    autorizadas_b = tuple(
        (
            str(regras_semanticas[indice]["rule_id"]),
            int(regras_semanticas[indice]["version"]),
        )
        for indice in ordem_fisica_b
    )
    catalogo_a = replace(
        catalogo_a_carregado,
        regras_autorizadas=autorizadas_a,
    )
    catalogo_b = replace(
        catalogo_b_carregado,
        regras_autorizadas=autorizadas_b,
    )

    contexto = ContextoAvaliacaoDSL(aplicacoes=("VPL",))
    resultado_a = ClassificadorDeCenario(catalogo_a).classificar(contexto)
    resultado_b = ClassificadorDeCenario(catalogo_b).classificar(contexto)

    indice_esperado = precedencias.index(0)
    regra_esperada = regras_semanticas[indice_esperado]
    referencia_esperada = ReferenciaRegra(
        rule_id=str(regra_esperada["rule_id"]),
        versao=int(regra_esperada["version"]),
        catalogo_versao=versao_catalogo,
    )
    condicao_esperada = str(
        regra_esperada["conditions"][0]["condition_id"]  # type: ignore[index]
    )

    assert resultado_a.regra_aplicada == referencia_esperada
    assert resultado_b.regra_aplicada == referencia_esperada
    assert resultado_a.categoria_de_cenario is categorias[indice_esperado]
    assert resultado_b.categoria_de_cenario is categorias[indice_esperado]
    assert resultado_a.condicoes_satisfeitas == (condicao_esperada,)
    assert resultado_b.condicoes_satisfeitas == (condicao_esperada,)
    assert resultado_a.evidencias == resultado_b.evidencias
    assert resultado_a.referencias_evidencia == (
        resultado_b.referencias_evidencia
    )
    assert resultado_a.evidencias
    assert tuple(
        evidencia.condicao_id for evidencia in resultado_a.evidencias
    ) == (condicao_esperada,)
    assert resultado_a.referencias_evidencia

    regras_conflitantes: list[dict[str, object]] = []
    precedencias_conflitantes: list[dict[str, object]] = []
    for indice, regra in enumerate(regras_semanticas):
        precedencia_conflitante = (
            0 if indice in (0, 1) else int(regra["precedence"])
        )
        regra_conflitante = {
            **regra,
            "precedence": precedencia_conflitante,
        }
        regras_conflitantes.append(regra_conflitante)
        precedencias_conflitantes.append(
            {
                "rule_id": regra_conflitante["rule_id"],
                "version": regra_conflitante["version"],
                "precedence": precedencia_conflitante,
            }
        )

    documento_conflitante = {
        "schema_version": 1,
        "catalog_version": versao_catalogo,
        "coverage": cobertura,
        "rules": [
            regras_conflitantes[indice] for indice in ordem_fisica_a
        ],
        "precedence": [
            precedencias_conflitantes[indice]
            for indice in reversed(ordem_fisica_a)
        ],
    }
    catalogo_conflitante_carregado = catalogo_de_json(
        json.dumps(documento_conflitante, separators=(",", ":"))
    )
    catalogo_conflitante = replace(
        catalogo_conflitante_carregado,
        regras_autorizadas=autorizadas_a,
    )
    resultado_conflitante = ClassificadorDeCenario(
        catalogo_conflitante
    ).classificar(contexto)

    assert resultado_conflitante.categoria_de_cenario is (
        Categoria.NAO_CLASSIFICADA
    )
    assert resultado_conflitante.regra_aplicada is None
    assert resultado_conflitante.condicoes_satisfeitas == ()
    assert resultado_conflitante.evidencias == ()
    assert resultado_conflitante.referencias_evidencia == ()
    assert resultado_conflitante.versao_catalogo == SEM_CATALOGO_ATIVO

    event(f"quantidade_regras={quantidade_regras}")
    event(f"categoria_vencedora={categorias[indice_esperado].name}")
    event(
        "posicao_fisica_vencedora_a="
        f"{ordem_fisica_a.index(indice_esperado)}"
    )
    event(
        "posicao_fisica_vencedora_b="
        f"{ordem_fisica_b.index(indice_esperado)}"
    )
    event("conflito_precedencia=fail_closed")
