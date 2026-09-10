"""Teste de integração de uma regra ativa exclusivamente sintética (tarefa 14.2).

Monta em diretório temporário uma regra e fixture 100% sintéticas que passem
todos os gates e verifica:
  - Categoria ``SUCESSO``
  - Regra e versão referenciadas no resultado
  - Evidência de ambas as aplicações (VPL e ORK)
  - Correlação VPL–ORK com base ``VALOR_COMPARTILHADO``

A regra criada é um artefato de teste genérico. Seus predicados NÃO são
persistidos no catálogo distribuído e NÃO se afirma equivalência com o
cenário dourado real.

Nenhum código de produção, fixture persistente, catálogo distribuído ou
tasks.md é alterado. Nenhuma fonte de rede ou recurso proibido é consultado.

Validates: Requirements 10.1, 10.2, 11.1, 11.2, 11.3, 11.4, 13.1, 13.2.
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from log_analyzer.core.bootstrap import criar_registro_padrao
from log_analyzer.core.catalogo import CarregadorCatalogo
from log_analyzer.core.governanca import GovernancaDeFixtures
from log_analyzer.core.modelos import (
    ArquivoSelecionado,
    BaseCorrelacao,
    Categoria,
    EstadoSanitizacao,
)
from log_analyzer.core.pipeline_fase2 import PipelineFase2
from log_analyzer.core.serializacao import serializar_resultado_de_analise
from log_analyzer.core.validacao_catalogo import (
    CoberturaDeCondicao,
    ExemploRotuladoCatalogo,
    ManifestoAtivacaoRegra,
    PacoteValidacaoCatalogo,
    PoliticaDeAmostras,
    ReferenciaVersaoRegra,
)
from log_analyzer.core.dsl_regras import (
    ContextoAvaliacaoDSL,
    FatoEstruturado,
)
from log_analyzer.core.modelos import (
    CampoEstruturado,
    EntradaDeLog,
    IdentificadorTecnico,
    Proveniencia,
    TipoIdentificador,
    VinculoIdentificadores,
)

from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Constantes sintéticas (100% geradas, não derivadas de amostras reais)
# ---------------------------------------------------------------------------

_SYNTH_CALL_ID = "SYNTH-INTEG-REGRA-2077"
_SYNTH_RULE_ID = "SYNTH_INTEGRATION_RULE_14_2"
_SYNTH_RULE_VERSION = 1
_SYNTH_CATALOG_VERSION = "SYNTH_CATALOG_INTEG_14_2"
_SYNTH_FIXTURE_ID = "SYNTH_FIXTURE_INTEG_14_2"

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Builders de conteúdo sintético
# ---------------------------------------------------------------------------


def _vpl_content(call_id: str) -> str:
    """Gera conteúdo VPL sintético com CallId tipado."""
    return (
        f"2077-03-15 10:20:30.123456 99.80% "
        f"[NOTICE] synth_module.c:100 CallId={call_id} "
        f"synthetic VPL integration event regra sintetica\n"
    )


def _ork_content(call_id: str) -> str:
    """Gera conteúdo ORK sintético com TelecomCallId e CallId tipados."""
    return (
        f"2077-03-15T13:20:30.123456+00:00 "
        f"synth-node.integration.test synth-worker[7777]: "
        f"INFO - agent.synth - "
        f"TelecomCallId={call_id} CallId={call_id} "
        f"synthetic ORK integration event regra sintetica\n"
    )


def _write_log_file(path: Path, content: str) -> Path:
    """Grava conteúdo UTF-8 sem conversão de newline."""
    path.write_text(content, encoding="utf-8", newline="")
    return path


def _write_governed_fixture(tmp_path: Path) -> tuple[Path, str]:
    """Cria uma fixture sintética que passa pela governança.

    Returns:
        Tupla (diretório_fixture, digest_sha256 do artefato).
    """
    fixture_dir = tmp_path / _SYNTH_FIXTURE_ID
    fixture_dir.mkdir()

    artifact = fixture_dir / "synthetic_event.log"
    artifact.write_text(
        "event=SYNTHETIC_INTEG_14_2\n",
        encoding="utf-8",
    )
    digest = sha256(artifact.read_bytes()).hexdigest()

    manifest = {
        "fixture_id": _SYNTH_FIXTURE_ID,
        "origin": "synthetic",
        "sanitizer_version": "SYNTH_SANITIZER_INTEG_V1",
        "label": "SUCESSO",
        "validation_date": "2077-03-15",
        "approved_by": "<DOMAIN_OWNER_1>",
        "artifacts": [
            {"path": artifact.name, "sha256": digest},
        ],
    }
    (fixture_dir / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True),
        encoding="utf-8",
    )

    governance = GovernancaDeFixtures(fixture_dir).validar()
    assert governance.aprovada, (
        f"A fixture sintética deve passar pela governança: {governance}"
    )

    return fixture_dir, digest


def _synthetic_conditions() -> list[dict[str, object]]:
    """Condições DSL fechadas que serão satisfeitas pelo cenário."""
    return [
        {
            "condition_id": "SYNTH_COND_APP_VPL",
            "operator": "APPLICATION_PRESENT",
            "application": "VPL",
        },
        {
            "condition_id": "SYNTH_COND_APP_ORK",
            "operator": "APPLICATION_PRESENT",
            "application": "ORK",
        },
        {
            "condition_id": "SYNTH_COND_CARDINALITY",
            "operator": "CARDINALITY",
            "target": "ENTRY",
            "comparison": "GTE",
            "value": 2,
        },
    ]


def _build_catalog_document(digest: str) -> dict[str, object]:
    """Constrói o documento JSON do catálogo com regra ACTIVE sintética."""
    conditions = _synthetic_conditions()
    rule: dict[str, object] = {
        "rule_id": _SYNTH_RULE_ID,
        "version": _SYNTH_RULE_VERSION,
        "category": "SUCESSO",
        "applications": ["VPL", "ORK"],
        "conditions": conditions,
        "fixture_ids": [_SYNTH_FIXTURE_ID],
        "fixture_digests": [digest],
        "state": "ACTIVE",
        "approved_by": "<DOMAIN_OWNER_INTEG>",
        "approved_at": "2077-03-15T10:00:00+00:00",
        "approval_reference": "SYNTH_APPROVAL_INTEG_14_2",
        "precedence": 0,
    }
    fixture_doc: dict[str, object] = {
        "fixture_id": _SYNTH_FIXTURE_ID,
        "sha256": digest,
        "label": "SUCESSO",
        "sanitized_origin": "SYNTHETIC_GENERATED_INTEG",
        "validated_at": "2077-03-15T10:00:00+00:00",
        "validated_by": "<DOMAIN_OWNER_INTEG>",
        "sanitizer_version": "SYNTH_SANITIZER_INTEG_V1",
    }
    return {
        "schema_version": 1,
        "catalog_version": _SYNTH_CATALOG_VERSION,
        "coverage": {
            "labeled_successes": 1,
            "labeled_errors": 0,
        },
        "fixtures": [fixture_doc],
        "precedence": [
            {
                "rule_id": _SYNTH_RULE_ID,
                "version": _SYNTH_RULE_VERSION,
                "precedence": 0,
            },
        ],
        "rules": [rule],
    }


def _build_validation_package(
    digest: str,
    fixture_dir: Path,
) -> PacoteValidacaoCatalogo:
    """Constrói o pacote de validação para ativar a regra sintética."""
    reference = ReferenciaVersaoRegra(_SYNTH_RULE_ID, _SYNTH_RULE_VERSION)

    # Contexto mínimo que o exemplo rotulado precisa.
    entry_vpl = EntradaDeLog(
        texto_original="<SYNTHETIC_ENTRY>",
        aplicacao="VPL",
        ordem_de_leitura=0,
        interpretada=False,
        nivel_de_severidade="NOTICE",
        mensagem="<SYNTHETIC_ENTRY>",
        entrada_id="SYNTH_ENTRY_VPL_INTEG",
        arquivo_token="<ARQUIVO_1>",
        posicao_inicial=1,
        posicao_final=1,
        timestamp_original="2077-03-15T10:20:30.123456",
        timestamp_normalizado=datetime(2077, 3, 15, 13, 20, 30, 123456, tzinfo=UTC),
    )
    entry_ork = EntradaDeLog(
        texto_original="<SYNTHETIC_ENTRY>",
        aplicacao="ORK",
        ordem_de_leitura=1,
        interpretada=False,
        nivel_de_severidade="INFO",
        mensagem="<SYNTHETIC_ENTRY>",
        entrada_id="SYNTH_ENTRY_ORK_INTEG",
        arquivo_token="<ARQUIVO_2>",
        posicao_inicial=1,
        posicao_final=1,
        timestamp_original="2077-03-15T13:20:30.123456+00:00",
        timestamp_normalizado=datetime(2077, 3, 15, 13, 20, 30, 123456, tzinfo=UTC),
    )

    context = ContextoAvaliacaoDSL(
        entradas=(entry_vpl, entry_ork),
        aplicacoes=("VPL", "ORK"),
    )

    governance = GovernancaDeFixtures(fixture_dir).validar()
    assert governance.aprovada

    conditions = _synthetic_conditions()
    condition_ids = tuple(str(c["condition_id"]) for c in conditions)

    example = ExemploRotuladoCatalogo(
        fixture_id=_SYNTH_FIXTURE_ID,
        digest_sha256=digest,
        rotulo=Categoria.SUCESSO,
        contexto=context,
        governanca=governance,
        diversidade=(("origem", "SYNTHETIC_GENERATED_INTEG"),),
        aplicacoes=("ORK", "VPL"),
        regras_aplicaveis=(reference,),
    )

    manifesto = ManifestoAtivacaoRegra(
        rule_id=_SYNTH_RULE_ID,
        versao=_SYNTH_RULE_VERSION,
        politica_amostras=PoliticaDeAmostras(
            quantidade_minima=1,
            dimensoes_diversidade=("origem",),
            minimo_distintos_por_dimensao=1,
        ),
        cobertura_condicoes=tuple(
            CoberturaDeCondicao(
                condicao_id=cid,
                fixture_ids=(_SYNTH_FIXTURE_ID,),
            )
            for cid in condition_ids
        ),
        exemplos_aplicaveis=(_SYNTH_FIXTURE_ID,),
        produz_causa_raiz=False,
    )

    return PacoteValidacaoCatalogo(
        manifestos=(manifesto,),
        exemplos=(example,),
    )


# ---------------------------------------------------------------------------
# Testes de integração
# ---------------------------------------------------------------------------


class TestIntegracaoRegraSintetica:
    """Pipeline Fase 2 com regra sintética ACTIVE classificando SUCESSO."""

    @pytest.fixture()
    def artefatos(self, tmp_path: Path):
        """Monta fixture, catálogo e pacote de validação em tmp_path."""
        # 1. Fixture governada
        fixture_dir, digest = _write_governed_fixture(tmp_path)

        # 2. Catálogo JSON temporário
        catalog_doc = _build_catalog_document(digest)
        catalog_path = tmp_path / "catalog_synth_integ.json"
        catalog_path.write_text(
            json.dumps(catalog_doc, sort_keys=True, indent=2),
            encoding="utf-8",
        )

        # 3. Pacote de validação
        package = _build_validation_package(digest, fixture_dir)

        # 4. Carregar catálogo com ativação validada
        loader = CarregadorCatalogo()
        catalog = loader.carregar(catalog_path, pacote_validacao=package)

        # 5. Logs sintéticos
        vpl_file = _write_log_file(
            tmp_path / "vpl_synth.log", _vpl_content(_SYNTH_CALL_ID)
        )
        ork_file = _write_log_file(
            tmp_path / "ork_synth.log", _ork_content(_SYNTH_CALL_ID)
        )

        return catalog, vpl_file, ork_file

    @pytest.fixture()
    def resultado(self, artefatos):
        """Executa o pipeline com catálogo sintético e retorna o resultado."""
        catalog, vpl_file, ork_file = artefatos
        pipeline = PipelineFase2(
            criar_registro_padrao(),
            catalogo=catalog,
        )
        return pipeline.executar(
            (
                ArquivoSelecionado(str(vpl_file), "VPL"),
                ArquivoSelecionado(str(ork_file), "ORK"),
            ),
            _SYNTH_CALL_ID,
        )

    # --- Categoria SUCESSO --------------------------------------------------

    def test_categoria_sucesso(self, resultado) -> None:
        """A regra sintética satisfeita integralmente classifica SUCESSO."""
        assert resultado.categoria_de_cenario is Categoria.SUCESSO

    # --- Regra e versão -----------------------------------------------------

    def test_regra_aplicada_referencia_regra_sintetica(self, resultado) -> None:
        """O resultado deve referenciar a regra sintética ativada."""
        assert resultado.regra_aplicada is not None
        assert resultado.regra_aplicada.rule_id == _SYNTH_RULE_ID
        assert resultado.regra_aplicada.versao == _SYNTH_RULE_VERSION

    def test_versao_catalogo_no_resultado(self, resultado) -> None:
        """A versão do catálogo no resultado deve corresponder ao temporário."""
        assert resultado.versao_catalogo == _SYNTH_CATALOG_VERSION
        assert resultado.regra_aplicada.catalogo_versao == _SYNTH_CATALOG_VERSION

    # --- Evidência de ambas as apps ----------------------------------------

    def test_evidencias_presentes(self, resultado) -> None:
        """O resultado classificado deve conter evidências rastreáveis."""
        assert len(resultado.evidencias) >= 1

    def test_evidencia_cobre_vpl(self, resultado) -> None:
        """Deve haver ao menos uma evidência referenciando VPL."""
        apps_nas_evidencias = {ev.aplicacao for ev in resultado.evidencias}
        assert "VPL" in apps_nas_evidencias

    def test_evidencia_cobre_ork(self, resultado) -> None:
        """Deve haver ao menos uma evidência referenciando ORK."""
        apps_nas_evidencias = {ev.aplicacao for ev in resultado.evidencias}
        assert "ORK" in apps_nas_evidencias

    # --- Correlação VPL–ORK ------------------------------------------------

    def test_correlacao_encontrada(self, resultado) -> None:
        """Deve haver correlação entre VPL e ORK pelo CallId compartilhado."""
        assert resultado.correlacao_encontrada is True

    def test_correlacao_base_valor_compartilhado(self, resultado) -> None:
        """A base primária de correlação deve ser VALOR_COMPARTILHADO."""
        assert resultado.correlacao is not None
        assert (
            resultado.correlacao.base_primaria
            is BaseCorrelacao.VALOR_COMPARTILHADO
        )

    # --- Aplicações analisadas ---------------------------------------------

    def test_ambas_aplicacoes_analisadas(self, resultado) -> None:
        """VPL e ORK devem constar como analisadas."""
        assert sorted(resultado.aplicacoes_analisadas) == ["ORK", "VPL"]

    def test_nenhuma_aplicacao_ausente(self, resultado) -> None:
        """Nenhuma aplicação deve ser listada como ausente."""
        assert resultado.aplicacoes_ausentes_ou_invalidas == []

    # --- Contagens ----------------------------------------------------------

    def test_contagem_por_aplicacao(self, resultado) -> None:
        """Deve haver ao menos 1 entrada VPL e 1 ORK."""
        assert resultado.contagem_por_aplicacao.get("VPL", 0) >= 1
        assert resultado.contagem_por_aplicacao.get("ORK", 0) >= 1

    # --- Sanitização --------------------------------------------------------

    def test_estado_sanitizacao_concluida(self, resultado) -> None:
        """O resultado deve ter sanitização completamente aplicada."""
        assert resultado.estado_sanitizacao is EstadoSanitizacao.CONCLUIDA

    def test_superficie_nao_contem_call_id_bruto(self, resultado) -> None:
        """O CallId sintético não deve vazar na superfície pública."""
        superficie = json.dumps(
            serializar_resultado_de_analise(resultado),
            ensure_ascii=False,
            sort_keys=True,
        )
        assert _SYNTH_CALL_ID not in superficie

    # --- Sem erros ----------------------------------------------------------

    def test_sem_erros_de_pipeline(self, resultado) -> None:
        """O pipeline deve completar sem erros para entradas válidas."""
        assert resultado.erros == []

    # --- Não é o catálogo distribuído ---------------------------------------

    def test_regra_nao_e_do_catalogo_distribuido(self, resultado) -> None:
        """A regra é um artefato de teste; não equivale ao cenário real."""
        assert resultado.regra_aplicada.rule_id == _SYNTH_RULE_ID
        assert resultado.regra_aplicada.rule_id.startswith("SYNTH_")

    # --- Linha do tempo -----------------------------------------------------

    def test_linha_do_tempo_com_entradas(self, resultado) -> None:
        """A timeline deve conter entradas de ambas as aplicações."""
        assert len(resultado.linha_do_tempo) >= 2
        apps_timeline = {e.aplicacao for e in resultado.linha_do_tempo}
        assert "VPL" in apps_timeline
        assert "ORK" in apps_timeline
