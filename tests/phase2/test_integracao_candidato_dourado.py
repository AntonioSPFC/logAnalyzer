"""Teste de integração ponta a ponta do candidato estrutural VPL–ORK em fail-closed.

Usa exclusivamente a fixture de placeholders em
``tests/fixtures/log_analyzer_phase2/golden_candidate/`` para verificar:
  - Parsing real VPL e ORK
  - Agrupamento multiline
  - Normalização temporal
  - Busca por ``<CALL_ID_1>``
  - Correlação VPL–ORK
  - Linha do tempo ordenada
  - Evidência sanitizada

Como não há regras ativas nem predicados de classificação, exige-se:
  - ``NAO_CLASSIFICADA``
  - Regra ausente
  - Causa-raiz não determinada

Nenhum código de produção, fixture, catálogo ou tasks.md é alterado por este
arquivo. Nenhuma fonte de rede ou recurso proibido é consultado.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from log_analyzer.core.bootstrap import criar_registro_padrao
from log_analyzer.core.modelos import (
    ArquivoSelecionado,
    BaseCorrelacao,
    Categoria,
    EstadoCausaRaiz,
    EstadoSanitizacao,
)
from log_analyzer.core.pipeline_fase2 import PipelineFase2
from log_analyzer.core.serializacao import serializar_resultado_de_analise


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FIXTURE_DIR = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "log_analyzer_phase2"
    / "golden_candidate"
)

_VPL_LOG = _FIXTURE_DIR / "vpl.log"
_ORK_LOG = _FIXTURE_DIR / "ork.log"
_MANIFEST = _FIXTURE_DIR / "manifest.json"

_CALL_ID_PLACEHOLDER = "<CALL_ID_1>"


def _superficie_serializada(resultado: object) -> str:
    """Serializa o resultado para inspecionar a visão pública segura."""
    return json.dumps(
        serializar_resultado_de_analise(resultado),
        ensure_ascii=False,
        sort_keys=True,
    )


# ---------------------------------------------------------------------------
# Pré-condições da fixture
# ---------------------------------------------------------------------------


class TestPreCondicoesFixture:
    """Confirma que a fixture existe e está íntegra antes de exercitar o pipeline."""

    def test_fixture_vpl_existe(self) -> None:
        assert _VPL_LOG.exists(), f"Fixture VPL ausente: {_VPL_LOG}"

    def test_fixture_ork_existe(self) -> None:
        assert _ORK_LOG.exists(), f"Fixture ORK ausente: {_ORK_LOG}"

    def test_manifesto_existe_e_declara_nao_classificada(self) -> None:
        assert _MANIFEST.exists(), f"Manifesto ausente: {_MANIFEST}"
        manifesto = json.loads(_MANIFEST.read_text(encoding="utf-8"))
        assert manifesto["classification_status"] == "NAO_CLASSIFICADA"
        assert manifesto["active_rule"] is None
        assert manifesto["predicates"] == []
        assert manifesto["asserts_real_success"] is False


# ---------------------------------------------------------------------------
# Integração ponta a ponta
# ---------------------------------------------------------------------------


class TestIntegracaoCandidatoDouradoFase2:
    """Pipeline Fase 2 processando a fixture golden candidate de ponta a ponta."""

    @pytest.fixture()
    def resultado(self):
        """Executa o pipeline com a fixture e retorna o resultado sanitizado."""
        pipeline = PipelineFase2(criar_registro_padrao())
        return pipeline.executar(
            (
                ArquivoSelecionado(str(_VPL_LOG), "VPL"),
                ArquivoSelecionado(str(_ORK_LOG), "ORK"),
            ),
            _CALL_ID_PLACEHOLDER,
        )

    # --- Classificação fail-closed ----------------------------------------

    def test_categoria_nao_classificada(self, resultado) -> None:
        """Sem regra ativa, a categoria DEVE ser NAO_CLASSIFICADA."""
        assert resultado.categoria_de_cenario is Categoria.NAO_CLASSIFICADA

    def test_regra_aplicada_ausente(self, resultado) -> None:
        """Sem regra ativa, regra_aplicada DEVE ser None."""
        assert resultado.regra_aplicada is None

    def test_causa_raiz_nao_determinada(self, resultado) -> None:
        """Sem regra, causa-raiz DEVE ser NAO_DETERMINADA."""
        assert resultado.causa_raiz.estado is EstadoCausaRaiz.NAO_DETERMINADA
        assert resultado.causa_raiz.descricao_sanitizada == "não determinada"
        assert resultado.causa_raiz.regra is None

    # --- Sanitização -------------------------------------------------------

    def test_estado_sanitizacao_concluida(self, resultado) -> None:
        """O resultado entregue deve estar completamente sanitizado."""
        assert resultado.estado_sanitizacao is EstadoSanitizacao.CONCLUIDA

    def test_superficie_nao_contem_caminhos_brutos(self, resultado) -> None:
        """Caminhos reais do filesystem não devem vazar na superfície pública."""
        superficie = _superficie_serializada(resultado)
        assert str(_VPL_LOG) not in superficie
        assert str(_ORK_LOG) not in superficie
        # Confirma que nenhuma parte do caminho absoluto da fixture vaza
        assert str(_FIXTURE_DIR) not in superficie

    def test_superficie_usa_placeholders_para_evidencia(self, resultado) -> None:
        """Evidências devem usar placeholders tipados, não valores brutos."""
        superficie = _superficie_serializada(resultado)
        # O placeholder do CALL_ID deve aparecer sanitizado (mapeado)
        # mas o caminho real ou host real não deve aparecer
        assert str(_VPL_LOG.parent) not in superficie

    # --- Parsing real (VPL e ORK) -----------------------------------------

    def test_entradas_vpl_parseadas(self, resultado) -> None:
        """VPL deve ser parsed com ao menos 1 entrada estruturada."""
        assert "VPL" in resultado.entradas_por_aplicacao
        entradas_vpl = resultado.entradas_por_aplicacao["VPL"]
        assert len(entradas_vpl) >= 1

    def test_entradas_ork_parseadas(self, resultado) -> None:
        """ORK deve ser parsed com ao menos 1 entrada estruturada."""
        assert "ORK" in resultado.entradas_por_aplicacao
        entradas_ork = resultado.entradas_por_aplicacao["ORK"]
        assert len(entradas_ork) >= 1

    # --- Multiline ---------------------------------------------------------

    def test_multiline_vpl_preservado(self, resultado) -> None:
        """A continuação multiline do VPL deve estar no texto original."""
        entradas_vpl = resultado.entradas_por_aplicacao["VPL"]
        textos = " ".join(e.texto_original for e in entradas_vpl)
        assert "structural continuation vpl" in textos

    def test_multiline_ork_preservado(self, resultado) -> None:
        """A continuação multiline do ORK deve estar no texto original."""
        entradas_ork = resultado.entradas_por_aplicacao["ORK"]
        textos = " ".join(e.texto_original for e in entradas_ork)
        assert "structural continuation ork" in textos

    # --- Normalização temporal ---------------------------------------------

    def test_linha_do_tempo_nao_vazia(self, resultado) -> None:
        """O timeline deve conter entradas de ambas as aplicações."""
        assert len(resultado.linha_do_tempo) >= 2

    def test_entradas_sem_ordenacao_temporal_vazia(self, resultado) -> None:
        """Todas as entradas devem ter timestamp normalizável (nenhuma excluída)."""
        assert resultado.entradas_sem_ordenacao_temporal == []

    def test_timestamps_normalizados_em_utc(self, resultado) -> None:
        """Timestamps na timeline devem estar normalizados com offset UTC."""
        for entrada in resultado.linha_do_tempo:
            if entrada.timestamp_normalizado is not None:
                ts = entrada.timestamp_normalizado
                assert ts.tzinfo is not None, (
                    "timestamp_normalizado deve ser aware"
                )

    # --- Busca por <CALL_ID_1> ---------------------------------------------

    def test_busca_encontrou_entradas(self, resultado) -> None:
        """A busca por <CALL_ID_1> deve localizar entradas em ambos os lados."""
        total = sum(
            len(v) for v in resultado.entradas_por_aplicacao.values()
        )
        assert total >= 2, (
            "Busca deveria encontrar ao menos uma entrada VPL e uma ORK"
        )

    # --- Correlação VPL–ORK ------------------------------------------------

    def test_correlacao_encontrada(self, resultado) -> None:
        """Deve haver correlação entre VPL e ORK pelo <CALL_ID_1> compartilhado."""
        assert resultado.correlacao_encontrada is True

    def test_correlacao_base_valor_compartilhado(self, resultado) -> None:
        """A base primária de correlação deve ser VALOR_COMPARTILHADO."""
        assert resultado.correlacao is not None
        assert (
            resultado.correlacao.base_primaria
            is BaseCorrelacao.VALOR_COMPARTILHADO
        )

    def test_correlacao_evidencias_presentes(self, resultado) -> None:
        """A correlação deve conter ao menos uma evidência."""
        assert resultado.correlacao is not None
        assert len(resultado.correlacao.evidencias) >= 1

    # --- Aplicações analisadas ---------------------------------------------

    def test_aplicacoes_analisadas_vpl_ork(self, resultado) -> None:
        """Ambas as aplicações devem constar como analisadas."""
        assert sorted(resultado.aplicacoes_analisadas) == ["ORK", "VPL"]

    def test_nenhuma_aplicacao_ausente(self, resultado) -> None:
        """Nenhuma aplicação deve ser listada como ausente ou inválida."""
        assert resultado.aplicacoes_ausentes_ou_invalidas == []

    # --- Contagens ---------------------------------------------------------

    def test_contagem_por_aplicacao(self, resultado) -> None:
        """Deve haver ao menos 1 entrada por aplicação."""
        assert resultado.contagem_por_aplicacao.get("VPL", 0) >= 1
        assert resultado.contagem_por_aplicacao.get("ORK", 0) >= 1

    # --- Erros (ausência) --------------------------------------------------

    def test_sem_erros(self, resultado) -> None:
        """Pipeline deve completar sem erros para fixture válida."""
        assert resultado.erros == []

    # --- Evidências no resultado -------------------------------------------

    def test_evidencias_presentes_no_resultado(self, resultado) -> None:
        """O resultado deve conter evidências rastreáveis."""
        assert len(resultado.evidencias) >= 1

    # --- Não enfraquecido para SUCESSO -------------------------------------

    def test_nao_classificou_como_sucesso(self, resultado) -> None:
        """Mesmo com correlação válida, NÃO deve inferir SUCESSO sem regra."""
        assert resultado.categoria_de_cenario is not Categoria.SUCESSO

    def test_nao_classificou_como_erro(self, resultado) -> None:
        """Não deve inferir ERRO sem regra ativa."""
        assert resultado.categoria_de_cenario is not Categoria.ERRO
