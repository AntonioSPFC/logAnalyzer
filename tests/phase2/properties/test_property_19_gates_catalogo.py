"""Property 19 dos gates de ativação do catálogo da Fase 2.

Os documentos, manifestos, exemplos e digests deste módulo são exclusivamente
sintéticos e construídos em memória. Cada tentativa parte de um catálogo já
publicado para também verificar a atomicidade de qualquer rejeição.
"""

from __future__ import annotations

from hashlib import sha256

from hypothesis import event, given, settings, strategies as st
import pytest

from log_analyzer.core.catalogo import CarregadorCatalogo
from log_analyzer.core.dsl_regras import ContextoAvaliacaoDSL
from log_analyzer.core.excecoes import ErroDeCatalogo
from log_analyzer.core.governanca import (
    DiagnosticoGovernanca,
    ResultadoGovernanca,
)
from log_analyzer.core.modelos import Categoria
from log_analyzer.core.validacao_catalogo import (
    CodigoValidacaoCatalogo,
    CoberturaDeCondicao,
    ExemploRotuladoCatalogo,
    ManifestoAtivacaoRegra,
    PacoteValidacaoCatalogo,
    PoliticaDeAmostras,
    ReferenciaVersaoRegra,
)


_GATE_OMITIDO = (
    "nenhum",
    "metadado_obrigatorio",
    "manifesto_ausente",
    "apoio_inconsistente",
    "fixture_nao_sanitizada",
    "cobertura_incompleta",
    "politica_amostras",
    "avaliacao_incompleta",
    "aprovacao_ausente",
    "precedencia_conflitante",
)

_TIPO_REGRA = (
    "SUCESSO",
    "ERRO_COM_EXEMPLO",
    "ERRO_SEM_EXEMPLO",
    "CAUSA_RAIZ_COM_EXEMPLO",
    "CAUSA_RAIZ_SEM_EXEMPLO",
)

_CAMPOS_OBRIGATORIOS = (
    "rule_id",
    "version",
    "category",
    "applications",
    "conditions",
    "fixture_ids",
    "fixture_digests",
    "state",
)

_CAMPOS_APROVACAO = (
    "approved_by",
    "approved_at",
    "approval_reference",
)

_CODIGO_POR_GATE = {
    "metadado_obrigatorio": "CATALOG_SCHEMA_ERROR",
    "manifesto_ausente": (
        CodigoValidacaoCatalogo.ATIVACAO_SEM_EVIDENCIA.value
    ),
    "apoio_inconsistente": CodigoValidacaoCatalogo.DIGEST_INVALIDO.value,
    "fixture_nao_sanitizada": (
        CodigoValidacaoCatalogo.FIXTURE_NAO_GOVERNADA.value
    ),
    "cobertura_incompleta": (
        CodigoValidacaoCatalogo.COBERTURA_INCOMPLETA.value
    ),
    "politica_amostras": (
        CodigoValidacaoCatalogo.POLITICA_DE_AMOSTRAS.value
    ),
    "avaliacao_incompleta": (
        CodigoValidacaoCatalogo.AVALIACAO_DE_EXEMPLO.value
    ),
    "aprovacao_ausente": "CATALOG_SCHEMA_ERROR",
    "precedencia_conflitante": (
        CodigoValidacaoCatalogo.PRECEDENCIA_CONFLITANTE.value
    ),
}


def _digest(token: str) -> str:
    return sha256(token.encode("ascii")).hexdigest()


def _documento_fixture(
    *,
    fixture_id: str,
    digest: str,
    categoria: Categoria,
    origem_sanitizada: str = "SYNTHETIC_GENERATED_SOURCE",
) -> dict[str, object]:
    return {
        "fixture_id": fixture_id,
        "sha256": digest,
        "label": categoria.name,
        "sanitized_origin": origem_sanitizada,
        "validated_at": "2035-01-02T03:04:05+00:00",
        "validated_by": "<DOMAIN_OWNER_SYNTHETIC>",
        "sanitizer_version": "SYN_SANITIZER_1",
    }


def _documento_regra(
    *,
    rule_id: str,
    categoria: Categoria,
    condicoes: tuple[str, ...],
    fixture_ids: tuple[str, ...],
    fixture_digests: tuple[str, ...],
    precedencia: int = 0,
    causa_raiz: bool = False,
) -> dict[str, object]:
    documento: dict[str, object] = {
        "rule_id": rule_id,
        "version": 1,
        "category": categoria.name,
        "applications": ["VPL"],
        "conditions": [
            {
                "condition_id": condicao_id,
                "operator": "APPLICATION_PRESENT",
                "application": "VPL",
            }
            for condicao_id in condicoes
        ],
        "evidence_selectors": list(condicoes),
        "fixture_ids": list(fixture_ids),
        "fixture_digests": list(fixture_digests),
        "state": "ACTIVE",
        "approved_by": "<DOMAIN_OWNER_SYNTHETIC>",
        "approved_at": "2035-01-02T03:04:05+00:00",
        "approval_reference": f"SYN_APPROVAL_{rule_id}",
        "precedence": precedencia,
    }
    if causa_raiz:
        documento["root_cause"] = "SYN_ROOT_CAUSE"
    return documento


def _resultado_governanca(aprovada: bool) -> ResultadoGovernanca:
    if aprovada:
        return ResultadoGovernanca(aprovada=True)
    return ResultadoGovernanca(
        aprovada=False,
        diagnosticos=(
            DiagnosticoGovernanca(
                arquivo="fixture.log",
                linha=1,
                tipo="DADO_CLIENTE",
            ),
        ),
    )


def _exemplo(
    *,
    fixture_id: str,
    digest: str,
    categoria: Categoria,
    referencia: ReferenciaVersaoRegra,
    indice: int,
    aplicacao_no_contexto: str = "VPL",
    governada: bool = True,
) -> ExemploRotuladoCatalogo:
    return ExemploRotuladoCatalogo(
        fixture_id=fixture_id,
        digest_sha256=digest,
        rotulo=categoria,
        contexto=ContextoAvaliacaoDSL(
            aplicacoes=(aplicacao_no_contexto,)
        ),
        governanca=_resultado_governanca(governada),
        diversidade=(("origem", f"SYN_SOURCE_{indice:02d}"),),
        aplicacoes=("VPL",),
        regras_aplicaveis=(referencia,),
    )


def _manifesto(
    *,
    referencia: ReferenciaVersaoRegra,
    condicoes: tuple[str, ...],
    fixture_ids: tuple[str, ...],
    quantidade_minima: int,
    minimo_diversidade: int,
    produz_causa_raiz: bool,
) -> ManifestoAtivacaoRegra:
    return ManifestoAtivacaoRegra(
        rule_id=referencia.rule_id,
        versao=referencia.versao,
        politica_amostras=PoliticaDeAmostras(
            quantidade_minima=quantidade_minima,
            dimensoes_diversidade=("origem",),
            minimo_distintos_por_dimensao=minimo_diversidade,
        ),
        cobertura_condicoes=tuple(
            CoberturaDeCondicao(
                condicao_id=condicao_id,
                fixture_ids=fixture_ids,
            )
            for condicao_id in condicoes
        ),
        exemplos_aplicaveis=fixture_ids,
        produz_causa_raiz=produz_causa_raiz,
    )


# Feature: log-analyzer-phase-2, Property 19: Somente regras completas, apoiadas e aprovadas podem ser ativadas
@given(
    gate_omitido=st.sampled_from(_GATE_OMITIDO),
    tipo_regra=st.sampled_from(_TIPO_REGRA),
    quantidade_condicoes=st.integers(min_value=1, max_value=4),
    quantidade_exemplos=st.integers(min_value=1, max_value=3),
    salt=st.text(
        alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
        min_size=1,
        max_size=8,
    ),
    indice_metadado=st.integers(min_value=0, max_value=255),
    indice_aprovacao=st.integers(min_value=0, max_value=255),
    politica_falha_por_quantidade=st.booleans(),
    fixture_falha_pela_origem=st.booleans(),
)
@settings(max_examples=100)
def test_property_19_somente_regras_completas_apoiadas_e_aprovadas_ativam(
    gate_omitido: str,
    tipo_regra: str,
    quantidade_condicoes: int,
    quantidade_exemplos: int,
    salt: str,
    indice_metadado: int,
    indice_aprovacao: int,
    politica_falha_por_quantidade: bool,
    fixture_falha_pela_origem: bool,
) -> None:
    """Ativação equivale à passagem de todos os gates e é atômica.

    **Validates: Requirements 10.1, 10.2, 12.2, 12.4, 12.6, 12.7**
    """

    produz_causa_raiz = tipo_regra.startswith("CAUSA_RAIZ")
    regra_de_erro = tipo_regra != "SUCESSO"
    categoria = Categoria.ERRO if regra_de_erro else Categoria.SUCESSO
    possui_exemplo_erro_reconhecido = tipo_regra in {
        "ERRO_COM_EXEMPLO",
        "CAUSA_RAIZ_COM_EXEMPLO",
    }
    sem_exemplo_erro = tipo_regra in {
        "ERRO_SEM_EXEMPLO",
        "CAUSA_RAIZ_SEM_EXEMPLO",
    }

    rule_id = f"SYN_P19_RULE_{salt}"
    referencia = ReferenciaVersaoRegra(rule_id, 1)
    condicoes = tuple(
        f"SYN_P19_CONDITION_{salt}_{indice:02d}"
        for indice in range(quantidade_condicoes)
    )
    fixture_ids = tuple(
        f"SYN_P19_FIXTURE_{salt}_{indice:02d}"
        for indice in range(quantidade_exemplos)
    )
    fixture_digests = tuple(
        _digest(f"property-19:{salt}:{indice}")
        for indice in range(quantidade_exemplos)
    )

    exemplos: list[ExemploRotuladoCatalogo] = []
    fixtures_documento: list[dict[str, object]] = []
    for indice, (fixture_id, digest) in enumerate(
        zip(fixture_ids, fixture_digests, strict=True)
    ):
        digest_exemplo = digest
        if gate_omitido == "apoio_inconsistente" and indice == 0:
            digest_exemplo = _digest(
                f"property-19:mismatched:{salt}:{indice}"
            )

        governada = not (
            gate_omitido == "fixture_nao_sanitizada"
            and indice == 0
            and not fixture_falha_pela_origem
        )
        aplicacao_no_contexto = (
            "ORK"
            if gate_omitido == "avaliacao_incompleta" and indice == 0
            else "VPL"
        )
        exemplos.append(
            _exemplo(
                fixture_id=fixture_id,
                digest=digest_exemplo,
                categoria=categoria,
                referencia=referencia,
                indice=indice,
                aplicacao_no_contexto=aplicacao_no_contexto,
                governada=governada,
            )
        )
        origem = (
            "RAW_UNAPPROVED_SOURCE"
            if gate_omitido == "fixture_nao_sanitizada"
            and indice == 0
            and fixture_falha_pela_origem
            else "SYNTHETIC_GENERATED_SOURCE"
        )
        fixtures_documento.append(
            _documento_fixture(
                fixture_id=fixture_id,
                digest=digest,
                categoria=categoria,
                origem_sanitizada=origem,
            )
        )

    regra_documento = _documento_regra(
        rule_id=rule_id,
        categoria=categoria,
        condicoes=condicoes,
        fixture_ids=fixture_ids,
        fixture_digests=fixture_digests,
        causa_raiz=produz_causa_raiz,
    )

    condicoes_cobertas = condicoes
    if gate_omitido == "cobertura_incompleta":
        condicoes_cobertas = (
            condicoes[:-1]
            if len(condicoes) > 1
            else (f"SYN_P19_UNKNOWN_{salt}",)
        )

    minimo_exemplos = quantidade_exemplos
    minimo_diversidade = quantidade_exemplos
    if gate_omitido == "politica_amostras":
        if politica_falha_por_quantidade:
            minimo_exemplos += 1
        else:
            minimo_diversidade += 1

    manifesto_principal = _manifesto(
        referencia=referencia,
        condicoes=condicoes_cobertas,
        fixture_ids=fixture_ids,
        quantidade_minima=minimo_exemplos,
        minimo_diversidade=minimo_diversidade,
        produz_causa_raiz=produz_causa_raiz,
    )
    manifestos: list[ManifestoAtivacaoRegra] = []
    if gate_omitido != "manifesto_ausente":
        manifestos.append(manifesto_principal)

    regras_documento = [regra_documento]
    sucessos_rotulados = (
        quantidade_exemplos if categoria is Categoria.SUCESSO else 0
    )
    erros_rotulados = (
        quantidade_exemplos
        if categoria is Categoria.ERRO
        and possui_exemplo_erro_reconhecido
        else 0
    )

    if gate_omitido == "precedencia_conflitante":
        conflito_rule_id = f"SYN_P19_CONFLICT_{salt}"
        conflito_referencia = ReferenciaVersaoRegra(conflito_rule_id, 1)
        conflito_condicao = (f"SYN_P19_CONFLICT_CONDITION_{salt}",)
        conflito_fixture_id = f"SYN_P19_CONFLICT_FIXTURE_{salt}"
        conflito_digest = _digest(f"property-19:conflict:{salt}")
        conflito_exemplo = _exemplo(
            fixture_id=conflito_fixture_id,
            digest=conflito_digest,
            categoria=Categoria.SUCESSO,
            referencia=conflito_referencia,
            indice=quantidade_exemplos,
        )
        exemplos.append(conflito_exemplo)
        fixtures_documento.append(
            _documento_fixture(
                fixture_id=conflito_fixture_id,
                digest=conflito_digest,
                categoria=Categoria.SUCESSO,
            )
        )
        regras_documento.append(
            _documento_regra(
                rule_id=conflito_rule_id,
                categoria=Categoria.SUCESSO,
                condicoes=conflito_condicao,
                fixture_ids=(conflito_fixture_id,),
                fixture_digests=(conflito_digest,),
                precedencia=0,
            )
        )
        manifestos.append(
            _manifesto(
                referencia=conflito_referencia,
                condicoes=conflito_condicao,
                fixture_ids=(conflito_fixture_id,),
                quantidade_minima=1,
                minimo_diversidade=1,
                produz_causa_raiz=False,
            )
        )
        sucessos_rotulados += 1

    if gate_omitido == "metadado_obrigatorio":
        campo = _CAMPOS_OBRIGATORIOS[
            indice_metadado % len(_CAMPOS_OBRIGATORIOS)
        ]
        regra_documento.pop(campo)
    elif gate_omitido == "aprovacao_ausente":
        campo = _CAMPOS_APROVACAO[
            indice_aprovacao % len(_CAMPOS_APROVACAO)
        ]
        regra_documento.pop(campo)

    pacote = PacoteValidacaoCatalogo(
        manifestos=tuple(manifestos),
        exemplos=tuple(exemplos),
    )
    documento_anterior = {
        "schema_version": 1,
        "catalog_version": f"SYN_P19_BASE_{salt}",
        "coverage": {"labeled_successes": 0, "labeled_errors": 0},
        "rules": [],
    }
    documento_candidato = {
        "schema_version": 1,
        "catalog_version": f"SYN_P19_CANDIDATE_{salt}",
        "coverage": {
            "labeled_successes": sucessos_rotulados,
            "labeled_errors": erros_rotulados,
        },
        "fixtures": fixtures_documento,
        "rules": regras_documento,
    }

    carregador = CarregadorCatalogo()
    anterior = carregador.carregar_documento(documento_anterior)
    snapshot_anterior = (
        anterior.versao,
        anterior.digest_sha256,
        anterior.regras,
        anterior.fixtures,
        anterior.regras_autorizadas,
        anterior.regras_ativas,
    )

    todos_os_gates_passam = gate_omitido == "nenhum" and not sem_exemplo_erro
    if todos_os_gates_passam:
        publicado = carregador.carregar_documento(
            documento_candidato,
            pacote_validacao=pacote,
        )

        assert publicado is carregador.catalogo_ativo
        assert publicado is not anterior
        assert publicado.regras_autorizadas == ((rule_id, 1),)
        assert tuple(
            (regra.rule_id, regra.versao)
            for regra in publicado.regras_ativas
        ) == ((rule_id, 1),)
        assert publicado.regras_ativas == publicado.regras_declaradas_ativas
        assert snapshot_anterior == (
            anterior.versao,
            anterior.digest_sha256,
            anterior.regras,
            anterior.fixtures,
            anterior.regras_autorizadas,
            anterior.regras_ativas,
        )
        resultado = "ativada"
    else:
        with pytest.raises(ErroDeCatalogo) as falha:
            carregador.carregar_documento(
                documento_candidato,
                pacote_validacao=pacote,
            )

        codigo_esperado = _CODIGO_POR_GATE.get(gate_omitido)
        if gate_omitido == "nenhum":
            codigo_esperado = (
                CodigoValidacaoCatalogo.CAUSA_RAIZ_SEM_EXEMPLO.value
                if produz_causa_raiz
                else CodigoValidacaoCatalogo.ERRO_SEM_EXEMPLO.value
            )
        assert falha.value.codigo == codigo_esperado
        assert carregador.catalogo_ativo is anterior
        assert snapshot_anterior == (
            anterior.versao,
            anterior.digest_sha256,
            anterior.regras,
            anterior.fixtures,
            anterior.regras_autorizadas,
            anterior.regras_ativas,
        )
        assert anterior.regras_ativas == ()
        resultado = "catalogo_anterior_preservado"

    event(f"gate_omitido={gate_omitido}")
    event(f"tipo_regra={tipo_regra}")
    event(f"resultado={resultado}")
