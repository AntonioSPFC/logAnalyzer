"""Property 20: histórico append-only do catálogo de regras."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
from hashlib import sha256

from hypothesis import given, settings
from hypothesis import strategies as st
import pytest

from log_analyzer.core.catalogo import CarregadorCatalogo, construir_catalogo
from log_analyzer.core.excecoes import ErroDeCatalogo
from log_analyzer.core.validacao_catalogo import CodigoValidacaoCatalogo


_OPERACOES = (
    "append",
    "mutate_history",
    "remove_history",
    "same_catalog_version",
)


# Feature: log-analyzer-phase-2, Property 20: Histórico do catálogo é append-only
@given(
    salt=st.text(
        alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
        min_size=1,
        max_size=8,
    ),
    quantidade_condicoes=st.integers(min_value=1, max_value=4),
    versao_inicial=st.integers(min_value=1, max_value=8),
    operacoes_extras=st.lists(
        st.sampled_from(_OPERACOES), min_size=0, max_size=4
    ),
    posicoes_insercao=st.lists(
        st.integers(min_value=0, max_value=16), min_size=4, max_size=4
    ),
    alvos=st.lists(
        st.integers(min_value=0, max_value=255), min_size=8, max_size=8
    ),
)
@settings(max_examples=100)
def test_property_20_historico_do_catalogo_e_append_only(
    salt: str,
    quantidade_condicoes: int,
    versao_inicial: int,
    operacoes_extras: list[str],
    posicoes_insercao: list[int],
    alvos: list[int],
) -> None:
    """Versões aceitas só anexam histórico; falhas preservam o snapshot.

    **Validates: Requirements 12.5**
    """
    operacoes = list(operacoes_extras)
    for operacao, posicao in zip(
        _OPERACOES, posicoes_insercao, strict=True
    ):
        operacoes.insert(posicao % (len(operacoes) + 1), operacao)

    rule_id = f"SYN_RULE_HISTORY_{salt}"
    fixture_id = f"SYN_FIXTURE_HISTORY_{salt}_{versao_inicial:02d}"
    regra_inicial: dict[str, object] = {
        "rule_id": rule_id,
        "version": versao_inicial,
        "category": "SUCESSO",
        "applications": ["VPL"],
        "conditions": [
            {
                "condition_id": f"SYN_CONDITION_{salt}_{indice:02d}",
                "operator": "FIELD_EQUALS",
                "field": f"SYN_FIELD_{indice:02d}",
                "expected": f"SYN_INITIAL_{salt}_{indice:02d}",
            }
            for indice in range(quantidade_condicoes)
        ],
        "fixture_ids": [fixture_id],
        "fixture_digests": [
            sha256(fixture_id.encode("ascii")).hexdigest()
        ],
        "state": "CANDIDATE",
        "approved_by": "<DOMAIN_OWNER_SYNTHETIC>",
        "approved_at": "2025-01-02T03:04:05+00:00",
        "approval_reference": f"SYN_APPROVAL_{salt}_{versao_inicial:02d}",
        "precedence": versao_inicial,
    }
    documento_atual: dict[str, object] = {
        "schema_version": 1,
        "catalog_version": f"SYN_CATALOG_HISTORY_00_{salt}",
        "coverage": {"labeled_successes": 1, "labeled_errors": 0},
        "rules": [regra_inicial],
    }

    carregador = CarregadorCatalogo()
    snapshot_inicial = carregador.carregar_documento(
        deepcopy(documento_atual)
    )
    registros_historicos = [
        (
            snapshot_inicial,
            snapshot_inicial.versao,
            snapshot_inicial.digest_sha256,
            tuple(
                (
                    regra.rule_id,
                    regra.versao,
                    regra.digest_historico,
                    tuple(
                        (
                            condicao.condition_id,
                            condicao.operator,
                            condicao.parametros,
                        )
                        for condicao in regra.condicoes
                    ),
                )
                for regra in snapshot_inicial.regras
            ),
            tuple(
                (fixture.fixture_id, fixture.digest_sha256)
                for fixture in snapshot_inicial.fixtures
            ),
        )
    ]
    revisao_catalogo = 0
    alteracoes_aceitas = 0
    alteracoes_rejeitadas = 0

    for etapa, operacao in enumerate(operacoes):
        anterior = carregador.catalogo_ativo
        assert anterior is not None

        candidato = deepcopy(documento_atual)
        regras_candidatas = candidato["rules"]
        assert isinstance(regras_candidatas, list)
        ultima_regra = regras_candidatas[-1]
        assert isinstance(ultima_regra, dict)

        if operacao == "append":
            nova_regra = deepcopy(ultima_regra)
            nova_versao = int(nova_regra["version"]) + 1
            condicoes = nova_regra["conditions"]
            assert isinstance(condicoes, list)
            indice_condicao = alvos[etapa] % len(condicoes)
            condicao_alterada = condicoes[indice_condicao]
            assert isinstance(condicao_alterada, dict)
            condicao_alterada["expected"] = (
                f"SYN_ACCEPTED_{salt}_{etapa:02d}_{nova_versao:02d}"
            )
            novo_fixture_id = (
                f"SYN_FIXTURE_HISTORY_{salt}_{nova_versao:02d}"
            )
            nova_regra["version"] = nova_versao
            nova_regra["fixture_ids"] = [novo_fixture_id]
            nova_regra["fixture_digests"] = [
                sha256(novo_fixture_id.encode("ascii")).hexdigest()
            ]
            nova_regra["approval_reference"] = (
                f"SYN_APPROVAL_{salt}_{nova_versao:02d}"
            )
            nova_regra["precedence"] = nova_versao
            regras_candidatas.append(nova_regra)

            proxima_revisao = revisao_catalogo + 1
            candidato["catalog_version"] = (
                f"SYN_CATALOG_HISTORY_{proxima_revisao:02d}_{salt}"
            )
            publicado = carregador.carregar_documento(candidato)

            assert publicado is carregador.catalogo_ativo
            assert publicado is not anterior
            assert publicado.versao != anterior.versao
            assert len(publicado.regras) == len(anterior.regras) + 1
            assert publicado.regras[-1].versao == anterior.regras[-1].versao + 1
            assert publicado.regras[-1].condicoes != anterior.regras[-1].condicoes
            for regra_anterior in anterior.regras:
                regra_preservada = publicado.obter_regra(
                    regra_anterior.rule_id, regra_anterior.versao
                )
                assert regra_preservada == regra_anterior
                assert regra_preservada is not None
                assert (
                    regra_preservada.digest_historico
                    == regra_anterior.digest_historico
                )

            documento_atual = candidato
            revisao_catalogo = proxima_revisao
            alteracoes_aceitas += 1
            registros_historicos.append(
                (
                    publicado,
                    publicado.versao,
                    publicado.digest_sha256,
                    tuple(
                        (
                            regra.rule_id,
                            regra.versao,
                            regra.digest_historico,
                            tuple(
                                (
                                    condicao.condition_id,
                                    condicao.operator,
                                    condicao.parametros,
                                )
                                for condicao in regra.condicoes
                            ),
                        )
                        for regra in publicado.regras
                    ),
                    tuple(
                        (fixture.fixture_id, fixture.digest_sha256)
                        for fixture in publicado.fixtures
                    ),
                )
            )
        else:
            if operacao == "mutate_history":
                indice_regra = alvos[etapa] % len(regras_candidatas)
                regra_alterada = regras_candidatas[indice_regra]
                assert isinstance(regra_alterada, dict)
                condicoes = regra_alterada["conditions"]
                assert isinstance(condicoes, list)
                indice_condicao = alvos[-(etapa + 1)] % len(condicoes)
                condicao_alterada = condicoes[indice_condicao]
                assert isinstance(condicao_alterada, dict)
                condicao_alterada["expected"] = (
                    f"SYN_REJECTED_HISTORY_{salt}_{etapa:02d}"
                )
                candidato["catalog_version"] = (
                    f"SYN_CATALOG_REJECTED_MUTATION_{etapa:02d}_{salt}"
                )
                codigo_esperado = (
                    CodigoValidacaoCatalogo.HISTORICO_INVALIDO.value
                )
            elif operacao == "remove_history":
                indice_regra = alvos[etapa] % len(regras_candidatas)
                regras_candidatas.pop(indice_regra)
                candidato["catalog_version"] = (
                    f"SYN_CATALOG_REJECTED_REMOVAL_{etapa:02d}_{salt}"
                )
                codigo_esperado = (
                    CodigoValidacaoCatalogo.HISTORICO_INVALIDO.value
                )
            else:
                nova_regra = deepcopy(ultima_regra)
                nova_versao = int(nova_regra["version"]) + 1
                condicoes = nova_regra["conditions"]
                assert isinstance(condicoes, list)
                indice_condicao = alvos[etapa] % len(condicoes)
                condicao_alterada = condicoes[indice_condicao]
                assert isinstance(condicao_alterada, dict)
                condicao_alterada["expected"] = (
                    f"SYN_REJECTED_VERSION_{salt}_{etapa:02d}"
                )
                novo_fixture_id = (
                    f"SYN_FIXTURE_REJECTED_{salt}_{nova_versao:02d}"
                )
                nova_regra["version"] = nova_versao
                nova_regra["fixture_ids"] = [novo_fixture_id]
                nova_regra["fixture_digests"] = [
                    sha256(novo_fixture_id.encode("ascii")).hexdigest()
                ]
                nova_regra["approval_reference"] = (
                    f"SYN_APPROVAL_REJECTED_{salt}_{nova_versao:02d}"
                )
                nova_regra["precedence"] = nova_versao
                regras_candidatas.append(nova_regra)
                codigo_esperado = (
                    CodigoValidacaoCatalogo.VERSAO_INVALIDA.value
                )

            with pytest.raises(ErroDeCatalogo) as falha:
                carregador.carregar_documento(candidato)

            assert falha.value.codigo == codigo_esperado
            assert carregador.catalogo_ativo is anterior
            assert carregador.catalogo_ativo == anterior
            alteracoes_rejeitadas += 1

        ativo = carregador.catalogo_ativo
        assert ativo is not None

        documento_reordenado: dict[str, object] = {}
        for chave, valor in reversed(tuple(documento_atual.items())):
            if chave == "coverage":
                assert isinstance(valor, dict)
                documento_reordenado[chave] = {
                    item_chave: deepcopy(item_valor)
                    for item_chave, item_valor in reversed(tuple(valor.items()))
                }
            else:
                documento_reordenado[chave] = deepcopy(valor)

        regras_reordenadas: list[dict[str, object]] = []
        regras_atuais = documento_atual["rules"]
        assert isinstance(regras_atuais, list)
        for regra_documento in regras_atuais:
            assert isinstance(regra_documento, dict)
            regra_reordenada: dict[str, object] = {}
            for chave, valor in reversed(tuple(regra_documento.items())):
                if chave == "conditions":
                    assert isinstance(valor, list)
                    regra_reordenada[chave] = [
                        {
                            item_chave: deepcopy(item_valor)
                            for item_chave, item_valor in reversed(
                                tuple(condicao.items())
                            )
                        }
                        for condicao in valor
                    ]
                else:
                    regra_reordenada[chave] = deepcopy(valor)
            regras_reordenadas.append(regra_reordenada)
        documento_reordenado["rules"] = regras_reordenadas

        reconstruido = construir_catalogo(documento_reordenado)
        assert reconstruido.digest_sha256 == ativo.digest_sha256
        assert tuple(
            (regra.rule_id, regra.versao, regra.digest_historico)
            for regra in reconstruido.regras
        ) == tuple(
            (regra.rule_id, regra.versao, regra.digest_historico)
            for regra in ativo.regras
        )

        for (
            snapshot,
            versao_snapshot,
            digest_snapshot,
            estado_regras,
            estado_fixtures,
        ) in registros_historicos:
            assert snapshot.versao == versao_snapshot
            assert snapshot.digest_sha256 == digest_snapshot
            assert tuple(
                (
                    regra.rule_id,
                    regra.versao,
                    regra.digest_historico,
                    tuple(
                        (
                            condicao.condition_id,
                            condicao.operator,
                            condicao.parametros,
                        )
                        for condicao in regra.condicoes
                    ),
                )
                for regra in snapshot.regras
            ) == estado_regras
            assert tuple(
                (fixture.fixture_id, fixture.digest_sha256)
                for fixture in snapshot.fixtures
            ) == estado_fixtures

    assert alteracoes_aceitas >= 1
    assert alteracoes_rejeitadas >= 3
    assert tuple(regra.versao for regra in carregador.catalogo_ativo.regras) == tuple(
        range(
            versao_inicial,
            versao_inicial + alteracoes_aceitas + 1,
        )
    )

    with pytest.raises(FrozenInstanceError):
        snapshot_inicial.versao = "SYN_CATALOG_MUTATED"  # type: ignore[misc]
    with pytest.raises(TypeError):
        snapshot_inicial.regras[0].condicoes[0].parametros[0] = (  # type: ignore[index]
            "expected",
            "SYN_MUTATED",
        )

    assert snapshot_inicial is registros_historicos[0][0]
    assert snapshot_inicial.versao == registros_historicos[0][1]
    assert snapshot_inicial.digest_sha256 == registros_historicos[0][2]
