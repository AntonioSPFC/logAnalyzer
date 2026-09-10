"""Testes sintéticos dos gates atômicos do catálogo (tarefa 11.3)."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
from uuid import uuid4

import pytest

from log_analyzer.core.catalogo import CarregadorCatalogo, construir_catalogo
from log_analyzer.core.dsl_regras import ContextoAvaliacaoDSL
from log_analyzer.core.excecoes import ErroDeCatalogo
from log_analyzer.core.governanca import GovernancaDeFixtures
from log_analyzer.core.modelos import Categoria
from log_analyzer.core.validacao_catalogo import (
    CodigoValidacaoCatalogo,
    CoberturaDeCondicao,
    ExemploRotuladoCatalogo,
    ManifestoAtivacaoRegra,
    PacoteValidacaoCatalogo,
    PoliticaDeAmostras,
    ReferenciaVersaoRegra,
    ValidadorCatalogo,
)


def _criar_exemplo(
    tmp_path,
    *,
    fixture_id: str = "SYN_FIXTURE_01",
    rotulo: Categoria = Categoria.SUCESSO,
    aplicacao_contexto: str = "VPL",
    aplicacoes_declaradas: tuple[str, ...] = ("VPL",),
    governada: bool = True,
    regra: ReferenciaVersaoRegra | None = None,
    diversidade: tuple[tuple[str, str], ...] = (("origem", "sintetica"),),
) -> ExemploRotuladoCatalogo:
    diretorio = tmp_path / fixture_id
    diretorio.mkdir()
    artefato = diretorio / "evento.log"
    conteudo = (
        "evento=sintetico\n"
        if governada
        else f"uuid={uuid4()}\n"
    )
    artefato.write_text(conteudo, encoding="utf-8")
    digest = sha256(artefato.read_bytes()).hexdigest()
    manifesto = {
        "fixture_id": fixture_id,
        "origin": "synthetic",
        "sanitizer_version": "SYN_SANITIZER_1",
        "label": rotulo.name,
        "validation_date": "2025-01-02",
        "approved_by": "<DOMAIN_OWNER_1>",
        "artifacts": [{"path": "evento.log", "sha256": digest}],
    }
    (diretorio / "manifest.json").write_text(
        json.dumps(manifesto), encoding="utf-8"
    )
    governanca = GovernancaDeFixtures(diretorio).validar()
    assert governanca.aprovada is governada
    return ExemploRotuladoCatalogo(
        fixture_id=fixture_id,
        digest_sha256=digest,
        rotulo=rotulo,
        contexto=ContextoAvaliacaoDSL(
            aplicacoes=(aplicacao_contexto,)
        ),
        governanca=governanca,
        diversidade=diversidade,
        aplicacoes=aplicacoes_declaradas,
        regras_aplicaveis=() if regra is None else (regra,),
    )


def _regra(
    exemplo: ExemploRotuladoCatalogo,
    *,
    rule_id: str = "SYN_RULE_01",
    version: int = 1,
    category: str = "SUCESSO",
    state: str = "ACTIVE",
    precedence: int = 0,
    application: str = "VPL",
    root_cause: str | None = None,
    expected_application: str | None = None,
) -> dict[str, object]:
    regra: dict[str, object] = {
        "rule_id": rule_id,
        "version": version,
        "category": category,
        "applications": [application],
        "conditions": [
            {
                "condition_id": f"SYN_CONDITION_{rule_id}",
                "operator": "APPLICATION_PRESENT",
                "application": expected_application or application,
            }
        ],
        "fixture_ids": [exemplo.fixture_id],
        "fixture_digests": [exemplo.digest_sha256],
        "state": state,
        "approved_by": "<DOMAIN_OWNER_1>",
        "approved_at": "2025-01-02T03:04:05+00:00",
        "approval_reference": f"SYN_APPROVAL_{rule_id}",
        "precedence": precedence,
    }
    if root_cause is not None:
        regra["root_cause"] = root_cause
    return regra


def _fixture(exemplo: ExemploRotuladoCatalogo) -> dict[str, object]:
    return {
        "fixture_id": exemplo.fixture_id,
        "sha256": exemplo.digest_sha256,
        "label": exemplo.rotulo.name,
        "sanitized_origin": "SYNTHETIC_GENERATED_SOURCE",
        "validated_at": "2025-01-02T03:04:05+00:00",
        "validated_by": "<DOMAIN_OWNER_1>",
        "sanitizer_version": "SYN_SANITIZER_1",
    }


def _catalogo(
    regras: list[dict[str, object]],
    exemplos: list[ExemploRotuladoCatalogo],
    *,
    version: str = "SYN_CATALOG_1",
    labeled_errors: int = 0,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "catalog_version": version,
        "coverage": {
            "labeled_successes": sum(
                item.rotulo is Categoria.SUCESSO for item in exemplos
            ),
            "labeled_errors": labeled_errors,
        },
        "fixtures": [_fixture(item) for item in exemplos],
        "rules": regras,
    }


def _manifesto(
    regra: dict[str, object],
    exemplo: ExemploRotuladoCatalogo,
    *,
    quantidade_minima: int = 1,
    minimo_diversidade: int = 1,
    condition_id: str | None = None,
    produz_causa_raiz: bool = False,
) -> ManifestoAtivacaoRegra:
    regra_id = str(regra["rule_id"])
    versao = int(regra["version"])
    condicao = regra["conditions"][0]
    return ManifestoAtivacaoRegra(
        rule_id=regra_id,
        versao=versao,
        politica_amostras=PoliticaDeAmostras(
            quantidade_minima=quantidade_minima,
            dimensoes_diversidade=("origem",),
            minimo_distintos_por_dimensao=minimo_diversidade,
        ),
        cobertura_condicoes=(
            CoberturaDeCondicao(
                condicao_id=condition_id or str(condicao["condition_id"]),
                fixture_ids=(exemplo.fixture_id,),
            ),
        ),
        exemplos_aplicaveis=(exemplo.fixture_id,),
        produz_causa_raiz=produz_causa_raiz,
    )


def _pacote(
    regra: dict[str, object],
    exemplo: ExemploRotuladoCatalogo,
    **manifesto_kwargs,
) -> PacoteValidacaoCatalogo:
    return PacoteValidacaoCatalogo(
        manifestos=(_manifesto(regra, exemplo, **manifesto_kwargs),),
        exemplos=(exemplo,),
    )


def test_active_declarado_so_e_exposto_depois_de_todos_os_gates(
    tmp_path,
) -> None:
    exemplo = _criar_exemplo(tmp_path)
    regra = _regra(exemplo)
    documento = _catalogo([regra], [exemplo])

    apenas_carregado = construir_catalogo(documento)
    assert len(apenas_carregado.regras_declaradas_ativas) == 1
    assert apenas_carregado.regras_ativas == ()

    loader = CarregadorCatalogo()
    publicado = loader.carregar_documento(
        documento, pacote_validacao=_pacote(regra, exemplo)
    )
    relatorio = ValidadorCatalogo(_pacote(regra, exemplo)).validar_com_relatorio(
        apenas_carregado
    )

    assert publicado is loader.catalogo_ativo
    assert publicado.regras_ativas == publicado.regras_declaradas_ativas
    assert publicado.regras_autorizadas == (("SYN_RULE_01", 1),)
    assert relatorio.avaliacoes[0].correspondencia_integral
    assert relatorio.avaliacoes[0].condicoes_satisfeitas == (
        "SYN_CONDITION_SYN_RULE_01",
    )


def test_active_sem_pacote_falha_e_nao_publica_snapshot() -> None:
    documento = {
        "schema_version": 1,
        "catalog_version": "SYN_CATALOG_EMPTY",
        "coverage": {"labeled_successes": 0, "labeled_errors": 0},
        "rules": [],
    }
    loader = CarregadorCatalogo()
    anterior = loader.carregar_documento(documento)
    ativo = deepcopy(documento)
    ativo["catalog_version"] = "SYN_CATALOG_2"
    ativo["rules"] = [
        {
            "rule_id": "SYN_RULE_UNSUPPORTED",
            "version": 1,
            "category": "SUCESSO",
            "applications": ["VPL"],
            "conditions": [
                {
                    "condition_id": "SYN_CONDITION_UNSUPPORTED",
                    "operator": "APPLICATION_PRESENT",
                    "application": "VPL",
                }
            ],
            "fixture_ids": ["SYN_FIXTURE_UNSUPPORTED"],
            "fixture_digests": [sha256(b"synthetic").hexdigest()],
            "state": "ACTIVE",
            "approved_by": "<DOMAIN_OWNER_1>",
            "approved_at": "2025-01-02T03:04:05+00:00",
            "approval_reference": "SYN_APPROVAL_UNSUPPORTED",
            "precedence": 0,
        }
    ]

    with pytest.raises(ErroDeCatalogo) as failure:
        loader.carregar_documento(ativo)

    assert failure.value.codigo == (
        CodigoValidacaoCatalogo.ATIVACAO_SEM_EVIDENCIA.value
    )
    assert loader.catalogo_ativo is anterior


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (
            lambda regra, exemplo, pacote: replace(
                pacote,
                exemplos=(
                    replace(exemplo, digest_sha256="0" * 64),
                ),
            ),
            CodigoValidacaoCatalogo.DIGEST_INVALIDO,
        ),
        (
            lambda regra, exemplo, pacote: replace(
                pacote,
                manifestos=(
                    _manifesto(
                        regra,
                        exemplo,
                        quantidade_minima=2,
                    ),
                ),
            ),
            CodigoValidacaoCatalogo.POLITICA_DE_AMOSTRAS,
        ),
        (
            lambda regra, exemplo, pacote: replace(
                pacote,
                manifestos=(
                    _manifesto(
                        regra,
                        exemplo,
                        condition_id="SYN_CONDITION_MISSING",
                    ),
                ),
            ),
            CodigoValidacaoCatalogo.COBERTURA_INCOMPLETA,
        ),
    ],
)
def test_digest_politica_e_cobertura_falham_atomicamente(
    tmp_path, mutation, expected_code: CodigoValidacaoCatalogo
) -> None:
    exemplo = _criar_exemplo(tmp_path)
    regra = _regra(exemplo)
    documento = _catalogo([regra], [exemplo])
    pacote = mutation(regra, exemplo, _pacote(regra, exemplo))
    loader = CarregadorCatalogo()

    with pytest.raises(ErroDeCatalogo) as failure:
        loader.carregar_documento(documento, pacote_validacao=pacote)

    assert failure.value.codigo == expected_code.value
    assert failure.value.mensagem == "Falha no catálogo de regras."
    assert loader.catalogo_ativo is None


def test_fixture_rejeitada_pela_governanca_nao_pode_ativar(tmp_path) -> None:
    exemplo = _criar_exemplo(tmp_path, governada=False)
    regra = _regra(exemplo)
    documento = _catalogo([regra], [exemplo])

    with pytest.raises(ErroDeCatalogo) as failure:
        CarregadorCatalogo().carregar_documento(
            documento, pacote_validacao=_pacote(regra, exemplo)
        )

    assert failure.value.codigo == (
        CodigoValidacaoCatalogo.FIXTURE_NAO_GOVERNADA.value
    )


def test_avaliacao_dsl_de_todo_exemplo_aplicavel_e_obrigatoria(
    tmp_path,
) -> None:
    referencia = ReferenciaVersaoRegra("SYN_RULE_01", 1)
    exemplo = _criar_exemplo(
        tmp_path,
        aplicacao_contexto="ORK",
        aplicacoes_declaradas=("ORK",),
        regra=referencia,
    )
    regra = _regra(exemplo, application="VPL")
    documento = _catalogo([regra], [exemplo])

    with pytest.raises(ErroDeCatalogo) as failure:
        CarregadorCatalogo().carregar_documento(
            documento, pacote_validacao=_pacote(regra, exemplo)
        )

    assert failure.value.codigo == (
        CodigoValidacaoCatalogo.AVALIACAO_DE_EXEMPLO.value
    )


def test_precedencia_versionada_duplicada_rejeita_catalogo(tmp_path) -> None:
    primeiro = _criar_exemplo(tmp_path, fixture_id="SYN_FIXTURE_01")
    segundo = _criar_exemplo(tmp_path, fixture_id="SYN_FIXTURE_02")
    regra_a = _regra(primeiro, rule_id="SYN_RULE_A", precedence=0)
    regra_b = _regra(segundo, rule_id="SYN_RULE_B", precedence=0)
    documento = _catalogo([regra_a, regra_b], [primeiro, segundo])
    pacote = PacoteValidacaoCatalogo(
        manifestos=(
            _manifesto(regra_a, primeiro),
            _manifesto(regra_b, segundo),
        ),
        exemplos=(
            replace(
                primeiro,
                regras_aplicaveis=(ReferenciaVersaoRegra("SYN_RULE_A", 1),),
            ),
            replace(
                segundo,
                regras_aplicaveis=(ReferenciaVersaoRegra("SYN_RULE_B", 1),),
            ),
        ),
    )

    with pytest.raises(ErroDeCatalogo) as failure:
        CarregadorCatalogo().carregar_documento(
            documento, pacote_validacao=pacote
        )

    assert failure.value.codigo == (
        CodigoValidacaoCatalogo.PRECEDENCIA_CONFLITANTE.value
    )


@pytest.mark.parametrize(
    ("category", "root_cause", "causal", "expected_code"),
    [
        (
            "ERRO",
            None,
            False,
            CodigoValidacaoCatalogo.ERRO_SEM_EXEMPLO,
        ),
        (
            "SUCESSO",
            "SYN_ROOT_CAUSE",
            True,
            CodigoValidacaoCatalogo.CAUSA_RAIZ_SEM_EXEMPLO,
        ),
    ],
)
def test_regra_de_erro_ou_causa_raiz_exige_exemplo_rotulado_de_erro(
    tmp_path,
    category: str,
    root_cause: str | None,
    causal: bool,
    expected_code: CodigoValidacaoCatalogo,
) -> None:
    rotulo = Categoria.ERRO if category == "ERRO" else Categoria.SUCESSO
    exemplo = _criar_exemplo(tmp_path, rotulo=rotulo)
    regra = _regra(
        exemplo,
        category=category,
        root_cause=root_cause,
    )
    documento = _catalogo(
        [regra], [exemplo], labeled_errors=0
    )

    with pytest.raises(ErroDeCatalogo) as failure:
        CarregadorCatalogo().carregar_documento(
            documento,
            pacote_validacao=_pacote(
                regra, exemplo, produz_causa_raiz=causal
            ),
        )

    assert failure.value.codigo == expected_code.value


def test_alteracao_sem_nova_versao_preserva_historico_e_snapshot(
    tmp_path,
) -> None:
    exemplo = _criar_exemplo(tmp_path)
    regra = _regra(exemplo, state="CANDIDATE")
    original = _catalogo([regra], [exemplo])
    loader = CarregadorCatalogo()
    anterior = loader.carregar_documento(original)

    alterado = deepcopy(original)
    alterado["catalog_version"] = "SYN_CATALOG_2"
    alterado["rules"][0]["conditions"][0]["application"] = "ORK"

    with pytest.raises(ErroDeCatalogo) as failure:
        loader.carregar_documento(alterado)

    assert failure.value.codigo == (
        CodigoValidacaoCatalogo.HISTORICO_INVALIDO.value
    )
    assert loader.catalogo_ativo is anterior
    assert anterior.regras[0].digest_historico == (
        construir_catalogo(original).regras[0].digest_historico
    )
