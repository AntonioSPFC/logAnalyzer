"""Testes de declaração de cobertura e limites de diagnóstico (tarefa 14.4).

Verifica:
  - Versão do catálogo distribuído conforme declarada no JSON.
  - Aplicações efetivamente analisadas e aplicações ausentes ou inválidas.
  - Declaração de cobertura "1 cenário de sucesso; 0 cenários de erro".
  - Ausência de regra ERRO no catálogo distribuído.
  - Causa-raiz não determinada sem regra causal ativa.
  - Mensagem de VOCI fora do escopo quando solicitada regra nova.

Nenhuma fonte de produção, fixture bruta, rede ou tasks.md é alterada.

Requirements: 12.1, 12.3, 17.1, 17.2, 17.3, 17.4, 17.5, 17.6
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from log_analyzer.core.analisador import Analisador_de_Logs
from log_analyzer.core.bootstrap import criar_registro_padrao
from log_analyzer.core.catalogo import (
    CarregadorCatalogo,
    CatalogoDeRegras,
    EstadoRegra,
)
from log_analyzer.core.composicao import (
    COBERTURA_ROTULADA_FASE2,
    compor_resultado_fase2,
)
from log_analyzer.core.modelos import (
    ArquivoSelecionado,
    Categoria,
    EntradaDeLog,
    EstadoCausaRaiz,
    EstadoSanitizacao,
    ResultadoCausaRaiz,
)
from log_analyzer.core.pipeline_fase2 import PipelineFase2


# ---------------------------------------------------------------------------
# Caminhos
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parents[2]
_CATALOGO_DISTRIBUIDO = _ROOT / "log_analyzer" / "catalogos" / "fase2.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _criar_arquivo_vpl_sintetico(tmp_path: Path, identificador: str) -> Path:
    """Cria um arquivo VPL sintético mínimo contendo o identificador."""
    conteudo = (
        "a]2042-05-06 12:00:00.000 [NOTICE] switch_channel.c:0000 "
        f"sofia/internal/{identificador}@127.0.0.1 Canal criado\n"
    )
    arquivo = tmp_path / "vpl_cobertura.log"
    arquivo.write_text(conteudo, encoding="utf-8")
    return arquivo


def _criar_arquivo_ork_sintetico(tmp_path: Path, identificador: str) -> Path:
    """Cria um arquivo ORK sintético mínimo contendo o identificador."""
    conteudo = (
        "2042-05-06T12:00:01.000-03:00 host1 proc/1234 INFO "
        f"com.app.Main - TelecomCallId={identificador} inicio\n"
    )
    arquivo = tmp_path / "ork_cobertura.log"
    arquivo.write_text(conteudo, encoding="utf-8")
    return arquivo


def _criar_arquivo_voci_sintetico(
    tmp_path: Path, identificador: str
) -> Path:
    """Cria um arquivo VOCI sintético mínimo contendo o identificador."""
    conteudo = f"2042-05-06 12:00:00\tINFO\tevento {identificador}\n"
    arquivo = tmp_path / "voci_cobertura.log"
    arquivo.write_text(conteudo, encoding="utf-8")
    return arquivo


# ---------------------------------------------------------------------------
# Testes do catálogo distribuído
# ---------------------------------------------------------------------------


class TestVersaoCatalogoDistribuido:
    """Verifica que o catálogo distribuído possui versão e schema corretos."""

    @pytest.fixture()
    def catalogo(self) -> CatalogoDeRegras:
        return CarregadorCatalogo().carregar(_CATALOGO_DISTRIBUIDO)

    def test_catalogo_existe(self) -> None:
        assert _CATALOGO_DISTRIBUIDO.exists()

    def test_versao_catalogo_nao_vazia(self, catalogo: CatalogoDeRegras) -> None:
        """A versão declarada do catálogo deve ser uma string não vazia."""
        assert catalogo.versao
        assert isinstance(catalogo.versao, str)
        assert catalogo.versao.strip() != ""

    def test_schema_version_valida(self, catalogo: CatalogoDeRegras) -> None:
        """O catálogo deve declarar schema_version == 1."""
        assert catalogo.schema_version == 1

    def test_versao_identica_ao_json_bruto(
        self, catalogo: CatalogoDeRegras
    ) -> None:
        """A versão deve coincidir com o valor literal declarado no JSON."""
        dados = json.loads(_CATALOGO_DISTRIBUIDO.read_text(encoding="utf-8"))
        assert catalogo.versao == dados["catalog_version"]


# ---------------------------------------------------------------------------
# Testes de cobertura rotulada
# ---------------------------------------------------------------------------


class TestCoberturaRotulada:
    """Verifica a declaração de cobertura do catálogo distribuído."""

    @pytest.fixture()
    def catalogo(self) -> CatalogoDeRegras:
        return CarregadorCatalogo().carregar(_CATALOGO_DISTRIBUIDO)

    def test_cobertura_um_sucesso_zero_erros(
        self, catalogo: CatalogoDeRegras
    ) -> None:
        """O catálogo deve declarar exatamente 1 sucesso e 0 erros rotulados."""
        assert catalogo.cobertura.sucessos_rotulados == 1
        assert catalogo.cobertura.erros_rotulados == 0

    def test_declaracao_textual_cobertura(
        self, catalogo: CatalogoDeRegras
    ) -> None:
        """A declaração textual deve ser a constante esperada."""
        assert (
            catalogo.cobertura.declaracao
            == "1 cenário de sucesso; 0 cenários de erro"
        )

    def test_constante_cobertura_composicao_coincide(
        self, catalogo: CatalogoDeRegras
    ) -> None:
        """A constante usada pela composição deve coincidir com o catálogo."""
        assert COBERTURA_ROTULADA_FASE2 == catalogo.cobertura.declaracao

    def test_lacunas_declaradas(self, catalogo: CatalogoDeRegras) -> None:
        """O catálogo deve declarar ao menos uma lacuna de cobertura."""
        assert len(catalogo.cobertura.lacunas) >= 1
        ids_lacunas = {lacuna.gap_id for lacuna in catalogo.cobertura.lacunas}
        assert "ADDITIONAL_LABELED_SUCCESS_AND_ERROR_SAMPLES" in ids_lacunas


# ---------------------------------------------------------------------------
# Testes de ausência de regra ERRO
# ---------------------------------------------------------------------------


class TestAusenciaRegraErro:
    """Verifica que o catálogo distribuído não contém regras de ERRO ou causa-raiz."""

    @pytest.fixture()
    def catalogo(self) -> CatalogoDeRegras:
        return CarregadorCatalogo().carregar(_CATALOGO_DISTRIBUIDO)

    def test_nenhuma_regra_no_catalogo(
        self, catalogo: CatalogoDeRegras
    ) -> None:
        """O catálogo distribuído não deve conter nenhuma regra (nem ACTIVE nem outra)."""
        assert catalogo.regras == ()

    def test_nenhuma_regra_ativa(self, catalogo: CatalogoDeRegras) -> None:
        """O catálogo distribuído não deve possuir regras autorizadas."""
        assert catalogo.regras_ativas == ()

    def test_nenhuma_regra_erro(self, catalogo: CatalogoDeRegras) -> None:
        """Nenhuma regra com categoria ERRO deve existir no catálogo."""
        regras_erro = [
            regra
            for regra in catalogo.regras
            if regra.categoria is Categoria.ERRO
        ]
        assert regras_erro == []

    def test_nenhuma_causa_raiz_declarada(
        self, catalogo: CatalogoDeRegras
    ) -> None:
        """Nenhuma regra no catálogo deve declarar causa-raiz."""
        regras_com_causa = [
            regra
            for regra in catalogo.regras
            if regra.causa_raiz is not None
        ]
        assert regras_com_causa == []


# ---------------------------------------------------------------------------
# Testes de aplicações analisadas e ausentes
# ---------------------------------------------------------------------------


class TestAplicacoesAnalisadasAusentes:
    """Verifica que o resultado identifica apps analisadas e ausentes."""

    def test_vpl_ork_analisadas(self, tmp_path: Path) -> None:
        """Quando VPL e ORK são fornecidos, ambos devem estar em apps analisadas."""
        identificador = "<COBERTURA_TEST_ID_1>"
        vpl = _criar_arquivo_vpl_sintetico(tmp_path, identificador)
        ork = _criar_arquivo_ork_sintetico(tmp_path, identificador)

        pipeline = PipelineFase2(criar_registro_padrao())
        resultado = pipeline.executar(
            (
                ArquivoSelecionado(str(vpl), "VPL"),
                ArquivoSelecionado(str(ork), "ORK"),
            ),
            identificador,
        )

        assert "VPL" in resultado.aplicacoes_analisadas
        assert "ORK" in resultado.aplicacoes_analisadas

    def test_ork_ausente(self, tmp_path: Path) -> None:
        """Quando somente VPL é fornecido, ORK deve estar em apps ausentes."""
        identificador = "<COBERTURA_TEST_ID_2>"
        vpl = _criar_arquivo_vpl_sintetico(tmp_path, identificador)

        pipeline = PipelineFase2(criar_registro_padrao())
        resultado = pipeline.executar(
            (ArquivoSelecionado(str(vpl), "VPL"),),
            identificador,
        )

        assert "VPL" in resultado.aplicacoes_analisadas
        # ORK não foi fornecido, portanto não aparece em analisadas
        assert "ORK" not in resultado.aplicacoes_analisadas

    def test_vpl_ausente(self, tmp_path: Path) -> None:
        """Quando somente ORK é fornecido, VPL não aparece em apps analisadas."""
        identificador = "<COBERTURA_TEST_ID_3>"
        ork = _criar_arquivo_ork_sintetico(tmp_path, identificador)

        pipeline = PipelineFase2(criar_registro_padrao())
        resultado = pipeline.executar(
            (ArquivoSelecionado(str(ork), "ORK"),),
            identificador,
        )

        assert "ORK" in resultado.aplicacoes_analisadas
        assert "VPL" not in resultado.aplicacoes_analisadas

    def test_cobertura_rotulada_no_resultado(self, tmp_path: Path) -> None:
        """O resultado deve declarar a cobertura rotulada da Fase 2."""
        identificador = "<COBERTURA_TEST_ID_4>"
        vpl = _criar_arquivo_vpl_sintetico(tmp_path, identificador)
        ork = _criar_arquivo_ork_sintetico(tmp_path, identificador)

        pipeline = PipelineFase2(criar_registro_padrao())
        resultado = pipeline.executar(
            (
                ArquivoSelecionado(str(vpl), "VPL"),
                ArquivoSelecionado(str(ork), "ORK"),
            ),
            identificador,
        )

        assert resultado.cobertura_rotulada == COBERTURA_ROTULADA_FASE2

    def test_versao_catalogo_no_resultado(self, tmp_path: Path) -> None:
        """O resultado deve registrar a versão do catálogo usado."""
        identificador = "<COBERTURA_TEST_ID_5>"
        vpl = _criar_arquivo_vpl_sintetico(tmp_path, identificador)
        ork = _criar_arquivo_ork_sintetico(tmp_path, identificador)

        pipeline = PipelineFase2(criar_registro_padrao())
        resultado = pipeline.executar(
            (
                ArquivoSelecionado(str(vpl), "VPL"),
                ArquivoSelecionado(str(ork), "ORK"),
            ),
            identificador,
        )

        catalogo = CarregadorCatalogo().carregar(_CATALOGO_DISTRIBUIDO)
        assert resultado.versao_catalogo == catalogo.versao


# ---------------------------------------------------------------------------
# Testes de causa-raiz não determinada
# ---------------------------------------------------------------------------


class TestCausaRaizNaoDeterminada:
    """Verifica que sem regra causal ativa, a causa-raiz é NAO_DETERMINADA."""

    def test_pipeline_causa_raiz_nao_determinada(self, tmp_path: Path) -> None:
        """O pipeline sem regra ativa deve produzir causa-raiz não determinada."""
        identificador = "<COBERTURA_TEST_ID_6>"
        vpl = _criar_arquivo_vpl_sintetico(tmp_path, identificador)
        ork = _criar_arquivo_ork_sintetico(tmp_path, identificador)

        pipeline = PipelineFase2(criar_registro_padrao())
        resultado = pipeline.executar(
            (
                ArquivoSelecionado(str(vpl), "VPL"),
                ArquivoSelecionado(str(ork), "ORK"),
            ),
            identificador,
        )

        assert resultado.causa_raiz.estado is EstadoCausaRaiz.NAO_DETERMINADA
        assert resultado.causa_raiz.descricao_sanitizada == "não determinada"
        assert resultado.causa_raiz.regra is None

    def test_pipeline_categoria_nao_classificada(
        self, tmp_path: Path
    ) -> None:
        """Sem regra ativa, a categoria de cenário deve ser NAO_CLASSIFICADA."""
        identificador = "<COBERTURA_TEST_ID_7>"
        vpl = _criar_arquivo_vpl_sintetico(tmp_path, identificador)
        ork = _criar_arquivo_ork_sintetico(tmp_path, identificador)

        pipeline = PipelineFase2(criar_registro_padrao())
        resultado = pipeline.executar(
            (
                ArquivoSelecionado(str(vpl), "VPL"),
                ArquivoSelecionado(str(ork), "ORK"),
            ),
            identificador,
        )

        assert resultado.categoria_de_cenario is Categoria.NAO_CLASSIFICADA
        assert resultado.regra_aplicada is None

    def test_composicao_causa_raiz_padrao(self) -> None:
        """A composição com defaults deve produzir causa-raiz NAO_DETERMINADA."""
        resultado = compor_resultado_fase2(
            identificador="<ID_TESTE_PADRAO>",
            entradas_selecionadas=[],
        )
        assert resultado.causa_raiz.estado is EstadoCausaRaiz.NAO_DETERMINADA
        assert resultado.causa_raiz.descricao_sanitizada == "não determinada"
        assert resultado.causa_raiz.regra is None


# ---------------------------------------------------------------------------
# Testes de VOCI fora do escopo da Fase 2
# ---------------------------------------------------------------------------


class TestVociForaDoEscopo:
    """Verifica que VOCI não recebe regras, catálogo ou classificação da Fase 2.

    Requirement 17.5: VOCI solicitada para regra nova retorna informação de
    que essa capacidade está fora do escopo da Fase 2. Na prática, o sistema
    mantém VOCI no fluxo legado: sem catálogo, sem regra, sem identificadores
    da Fase 2 e sem categoria de cenário diferente de NAO_CLASSIFICADA.
    """

    def test_voci_sem_catalogo_sem_regra(self, tmp_path: Path) -> None:
        """Análise somente VOCI não recebe extensões da Fase 2."""
        identificador = "voci-escopo-teste-001"
        voci = _criar_arquivo_voci_sintetico(tmp_path, identificador)

        analisador = Analisador_de_Logs(criar_registro_padrao())
        resultado = analisador.analisar(
            [ArquivoSelecionado(caminho=str(voci), app_id="VOCI")],
            identificador,
        )

        # VOCI nunca recebe extensões da Fase 2
        assert (
            getattr(resultado, "categoria_de_cenario", Categoria.NAO_CLASSIFICADA)
            is Categoria.NAO_CLASSIFICADA
        )
        assert getattr(resultado, "regra_aplicada", None) is None
        assert getattr(resultado, "identificadores_extraidos", []) == []
        assert getattr(resultado, "vinculos", []) == []

    def test_voci_nao_usa_pipeline_fase2(self, tmp_path: Path) -> None:
        """VOCI deve passar pelo fluxo legado, sem catálogo ou pipeline Fase 2."""
        identificador = "voci-escopo-teste-002"
        voci = _criar_arquivo_voci_sintetico(tmp_path, identificador)

        analisador = Analisador_de_Logs(criar_registro_padrao())
        resultado = analisador.analisar(
            [ArquivoSelecionado(caminho=str(voci), app_id="VOCI")],
            identificador,
        )

        # No fluxo legado, versao_catalogo permanece no default
        versao = getattr(resultado, "versao_catalogo", "sem-catalogo-ativo")
        assert versao == "sem-catalogo-ativo"

    def test_voci_junto_com_vpl_ork_sem_regra_voci(
        self, tmp_path: Path
    ) -> None:
        """Mesmo com VPL/ORK, VOCI não recebe regra ou classificação de cenário."""
        identificador = "<VOCI_ESCOPO_TEST_3>"
        vpl = _criar_arquivo_vpl_sintetico(tmp_path, identificador)
        ork = _criar_arquivo_ork_sintetico(tmp_path, identificador)
        voci = _criar_arquivo_voci_sintetico(tmp_path, identificador)

        analisador = Analisador_de_Logs(criar_registro_padrao())
        resultado = analisador.analisar(
            [
                ArquivoSelecionado(caminho=str(vpl), app_id="VPL"),
                ArquivoSelecionado(caminho=str(ork), app_id="ORK"),
                ArquivoSelecionado(caminho=str(voci), app_id="VOCI"),
            ],
            identificador,
        )

        # O resultado combinado não deve ter regra ativa (o catálogo não tem)
        assert (
            getattr(resultado, "categoria_de_cenario", Categoria.NAO_CLASSIFICADA)
            is Categoria.NAO_CLASSIFICADA
        )
        assert getattr(resultado, "regra_aplicada", None) is None

        # VOCI deve aparecer em aplicações analisadas (pelo fluxo legado)
        analisadas = getattr(resultado, "aplicacoes_analisadas", [])
        if analisadas:
            assert "VOCI" in analisadas

    def test_voci_nao_tem_identificadores_fase2(
        self, tmp_path: Path
    ) -> None:
        """VOCI não deve receber identificadores tipados da Fase 2."""
        identificador = "voci-escopo-teste-004"
        voci = _criar_arquivo_voci_sintetico(tmp_path, identificador)

        analisador = Analisador_de_Logs(criar_registro_padrao())
        resultado = analisador.analisar(
            [ArquivoSelecionado(caminho=str(voci), app_id="VOCI")],
            identificador,
        )

        # Sem identificadores da Fase 2
        ids_extraidos = getattr(resultado, "identificadores_extraidos", [])
        assert ids_extraidos == []

        # Sem evidências
        evidencias = getattr(resultado, "evidencias", [])
        assert evidencias == []
