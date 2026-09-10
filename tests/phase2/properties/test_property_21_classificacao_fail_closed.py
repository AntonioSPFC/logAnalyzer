"""Property 21 da classificação de cenário sound e fail-closed.

Todos os catálogos, regras, contextos, fatos e vínculos são sintéticos e
construídos em memória. O teste não lê fixtures, fontes locais ou serviços
externos.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from hypothesis import event, given, settings, strategies as st

from log_analyzer.core.catalogo import EstadoRegra, construir_catalogo
from log_analyzer.core.classificacao import ClassificadorDeCenario
from log_analyzer.core.dsl_regras import ContextoAvaliacaoDSL, FatoEstruturado
from log_analyzer.core.modelos import (
    Categoria,
    EntradaDeLog,
    EstadoCausaRaiz,
    IdentificadorTecnico,
    Proveniencia,
    ResultadoCausaRaiz,
    TipoIdentificador,
    VinculoIdentificadores,
)


# Feature: log-analyzer-phase-2, Property 21: Classificação é sound e fail-closed
@given(
    sal=st.integers(min_value=0, max_value=2**32 - 1),
    sufixos_fatos=st.lists(
        st.integers(min_value=0, max_value=999_999),
        min_size=1,
        max_size=5,
        unique=True,
    ),
    categoria_da_entrada=st.sampled_from(tuple(Categoria)),
)
@settings(max_examples=100)
def test_property_21_classificacao_e_sound_e_fail_closed(
    sal: int,
    sufixos_fatos: list[int],
    categoria_da_entrada: Categoria,
) -> None:
    """Só match integral de regra ACTIVE autorizada produz conclusão.

    **Validates: Requirements 10.3, 10.4, 10.5, 13.1, 17.4, 17.6**
    """

    rule_id = f"SYN_RULE_P21_{sal}"
    fixture_id = f"SYN_FIXTURE_P21_{sal}"
    digest_fixture = f"{sal:064x}"
    catalog_version = f"SYN_CATALOG_P21_ACTIVE_{sal}"
    instante = datetime(2035, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

    condicoes_aplicacao = [
        {
            "condition_id": f"SYN_APP_VPL_{sal}",
            "operator": "APPLICATION_PRESENT",
            "application": "VPL",
        },
        {
            "condition_id": f"SYN_APP_ORK_{sal}",
            "operator": "APPLICATION_PRESENT",
            "application": "ORK",
        },
    ]
    codigos_fato = tuple(
        f"SYN_FACT_P21_{sal}_{sufixo}" for sufixo in sufixos_fatos
    )
    condicoes_fato = [
        {
            "condition_id": f"SYN_FACT_CONDITION_P21_{sal}_{sufixo}",
            "operator": "FACT_PRESENT",
            "application": "ORK",
            "fact": codigo,
        }
        for sufixo, codigo in zip(
            sufixos_fatos,
            codigos_fato,
            strict=True,
        )
    ]
    condicoes_ativas = [*condicoes_aplicacao, *condicoes_fato]
    ids_condicoes = tuple(
        sorted(str(condicao["condition_id"]) for condicao in condicoes_ativas)
    )

    regra_ativa = {
        "rule_id": rule_id,
        "version": 1,
        "category": "SUCESSO",
        "applications": ["VPL", "ORK"],
        "conditions": condicoes_ativas,
        "evidence_selectors": list(ids_condicoes),
        "fixture_ids": [fixture_id],
        "fixture_digests": [digest_fixture],
        "state": "ACTIVE",
        "approved_by": "<DOMAIN_OWNER_SYNTHETIC>",
        "approved_at": "2035-01-02T03:04:05+00:00",
        "approval_reference": f"SYN_APPROVAL_P21_{sal}",
        "precedence": 0,
    }
    documento_ativo = {
        "schema_version": 1,
        "catalog_version": catalog_version,
        "coverage": {
            "labeled_successes": 1,
            "labeled_errors": 0,
        },
        "rules": [regra_ativa],
    }
    catalogo_ativo_nao_autorizado = construir_catalogo(documento_ativo)
    catalogo_autorizado = replace(
        catalogo_ativo_nao_autorizado,
        regras_autorizadas=((rule_id, 1),),
    )

    entrada = EntradaDeLog(
        texto_original=f"EVENTO_SINTETICO_PROPERTY_21_{sal}",
        aplicacao="VPL",
        ordem_de_leitura=0,
        interpretada=True,
        carimbo_de_tempo=instante,
        nivel_de_severidade="INFO",
        mensagem=f"MENSAGEM_SINTETICA_PROPERTY_21_{sal}",
        categoria=categoria_da_entrada,
        entrada_id=f"SYN_ENTRY_P21_{sal}",
        arquivo_token=f"<ARQUIVO_SINTETICO_P21_{sal}>",
        posicao_inicial=1,
        posicao_final=1,
        timestamp_original=instante.isoformat(),
        timestamp_normalizado=instante,
    )
    fatos_integrais = tuple(
        FatoEstruturado(codigo=codigo, aplicacao="ORK")
        for codigo in codigos_fato
    )
    contexto_integral = ContextoAvaliacaoDSL(
        entradas=(entrada,),
        aplicacoes=("ORK", "VPL"),
        fatos=fatos_integrais,
    )

    classificador = ClassificadorDeCenario(catalogo_autorizado)
    resultados_por_severidade = tuple(
        classificador.classificar(
            replace(
                contexto_integral,
                entradas=(
                    replace(entrada, nivel_de_severidade=severidade),
                ),
            )
        )
        for severidade in ("DEBUG", "INFO", "NOTICE", "WARNING", "ERROR")
    )
    resultado_integral = resultados_por_severidade[0]

    assert all(
        resultado == resultado_integral
        for resultado in resultados_por_severidade
    )
    assert catalogo_autorizado.regras_ativas
    assert catalogo_autorizado.regras_ativas[0].estado is EstadoRegra.ACTIVE
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
    assert {
        cobertura.condicao_id for cobertura in resultado_integral.evidencias
    } == set(ids_condicoes)
    assert len(resultado_integral.evidencias) == len(ids_condicoes)
    assert all(
        cobertura.evidencias for cobertura in resultado_integral.evidencias
    )
    assert resultado_integral.referencias_evidencia
    assert resultado_integral.causa_raiz == ResultadoCausaRaiz()
    assert (
        resultado_integral.causa_raiz.estado
        is EstadoCausaRaiz.NAO_DETERMINADA
    )

    proveniencia_vinculo = Proveniencia(
        arquivo_token=entrada.arquivo_token or "<ARQUIVO_SINTETICO_P21>",
        entrada_id=entrada.entrada_id or "SYN_ENTRY_P21",
        linha_inicial=1,
        linha_final=1,
        nome_campo="SYN_LINK_DECLARATION",
        regra_extracao="SYN_LINK_EXTRACTOR_P21_V1",
    )
    origem = IdentificadorTecnico(
        tipo=TipoIdentificador.CALL_ID,
        namespace_comparacao="SYN_CALL_P21",
        nome_campo="CallId",
        valor_original=f"SYN_CALL_P21_{sal}",
        valor_normalizado=f"syn_call_p21_{sal}",
        proveniencia=proveniencia_vinculo,
    )
    destino = IdentificadorTecnico(
        tipo=TipoIdentificador.UUID_SESSAO,
        namespace_comparacao="SYN_SESSION_P21",
        nome_campo="SessionId",
        valor_original=f"SYN_SESSION_P21_{sal}",
        valor_normalizado=f"syn_session_p21_{sal}",
        proveniencia=proveniencia_vinculo,
    )
    vinculo_ambiguo = VinculoIdentificadores(
        origem=origem,
        destino=destino,
        tipo_relacao="SYN_CALL_TO_SESSION_P21",
        evidencia=proveniencia_vinculo,
        esquema_id="SYN_LINK_SCHEMA_P21",
        esquema_versao=1,
        permite_correlacao=True,
        ambiguo=True,
    )

    documento_candidato = {
        **documento_ativo,
        "catalog_version": f"SYN_CATALOG_P21_CANDIDATE_{sal}",
        "rules": [{**regra_ativa, "state": "CANDIDATE"}],
    }
    documento_inativo = {
        **documento_ativo,
        "catalog_version": f"SYN_CATALOG_P21_RETIRED_{sal}",
        "rules": [{**regra_ativa, "state": "RETIRED"}],
    }
    condicao_com_erro = {
        "condition_id": f"SYN_DSL_ERROR_P21_{sal}",
        "operator": "SYNTHETIC_UNSUPPORTED_OPERATOR",
        "payload": "SYNTHETIC_INERT_VALUE",
    }
    regra_com_erro_dsl = {
        **regra_ativa,
        "conditions": [*condicoes_ativas, condicao_com_erro],
        "evidence_selectors": [*ids_condicoes, condicao_com_erro["condition_id"]],
    }
    documento_erro_dsl = {
        **documento_ativo,
        "catalog_version": f"SYN_CATALOG_P21_DSL_ERROR_{sal}",
        "rules": [regra_com_erro_dsl],
    }
    catalogo_erro_dsl_nao_autorizado = construir_catalogo(
        documento_erro_dsl
    )
    catalogo_erro_dsl = replace(
        catalogo_erro_dsl_nao_autorizado,
        regras_autorizadas=((rule_id, 1),),
    )
    catalogo_invalido = replace(
        catalogo_autorizado,
        digest_sha256="INVALID",
    )

    contexto_severidade_isolada = ContextoAvaliacaoDSL(
        entradas=(replace(entrada, nivel_de_severidade="ERROR"),),
    )
    contexto_parcial = replace(
        contexto_integral,
        fatos=fatos_integrais[:-1],
    )
    contexto_ambiguo = replace(
        contexto_integral,
        vinculos=(vinculo_ambiguo,),
    )
    resultados_fail_closed = (
        (
            "severidade_isolada",
            classificador.classificar(contexto_severidade_isolada),
        ),
        (
            "candidato_estrutural",
            ClassificadorDeCenario(
                construir_catalogo(documento_candidato)
            ).classificar(contexto_integral),
        ),
        (
            "regra_inativa",
            ClassificadorDeCenario(
                construir_catalogo(documento_inativo)
            ).classificar(contexto_integral),
        ),
        (
            "active_nao_autorizada",
            ClassificadorDeCenario(
                catalogo_ativo_nao_autorizado
            ).classificar(contexto_integral),
        ),
        ("partial_match", classificador.classificar(contexto_parcial)),
        ("ambiguidade", classificador.classificar(contexto_ambiguo)),
        (
            "erro_dsl",
            ClassificadorDeCenario(catalogo_erro_dsl).classificar(
                contexto_integral
            ),
        ),
        (
            "catalogo_invalido",
            ClassificadorDeCenario(catalogo_invalido).classificar(
                contexto_integral
            ),
        ),
    )

    for motivo, resultado in resultados_fail_closed:
        assert resultado.categoria_de_cenario is Categoria.NAO_CLASSIFICADA
        assert not resultado.classificada
        assert not resultado.correspondencia_integral
        assert resultado.regra_aplicada is None
        assert resultado.condicoes_satisfeitas == ()
        assert resultado.evidencias == ()
        assert resultado.referencias_evidencia == ()
        assert resultado.causa_raiz == ResultadoCausaRaiz()
        assert resultado.causa_raiz.estado is EstadoCausaRaiz.NAO_DETERMINADA
        event(f"fail_closed={motivo}")

    event(f"quantidade_predicados={len(ids_condicoes)}")
    event(f"categoria_da_entrada={categoria_da_entrada.name}")
    event("severidades_testadas=DEBUG|INFO|NOTICE|WARNING|ERROR")
