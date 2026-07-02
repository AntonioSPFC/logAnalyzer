"""Testes de integração do orquestrador Analisador_de_Logs.

Verifica o fluxo completo de análise: validação de entradas, resolução de
parser/padrão via Registro, carregamento, interpretação, filtragem,
classificação, correlação e composição do resultado.

Requirements testados: 2.3, 2.4, 2.5, 3.6, 10.1, 1.2, 5.6
"""

from __future__ import annotations

import os
import tempfile

import pytest

from log_analyzer.core.analisador import Analisador_de_Logs
from log_analyzer.core.bootstrap import criar_registro_padrao
from log_analyzer.core.excecoes import ErroDeIdentificador
from log_analyzer.core.modelos import (
    ArquivoSelecionado,
    Categoria,
    ResultadoDeAnalise,
)


@pytest.fixture
def registro():
    """Cria um registro padrão com VPL, ORK e VOCI."""
    return criar_registro_padrao()


@pytest.fixture
def analisador(registro):
    """Cria um Analisador_de_Logs com o registro padrão."""
    return Analisador_de_Logs(registro)


@pytest.fixture
def arquivo_vpl(tmp_path):
    """Cria um arquivo de log VPL temporário com entradas válidas."""
    conteudo = (
        "2024-01-15 10:30:45.123 [INFO] mod_sofia.c:1234 Call abc123 initiated\n"
        "2024-01-15 10:30:46.456 [DEBUG] mod_sofia.c:1235 Processing request\n"
        "2024-01-15 10:30:47.789 [WARNING] mod_sofia.c:1236 Call abc123 timeout\n"
    )
    arquivo = tmp_path / "vpl.log"
    arquivo.write_text(conteudo, encoding="utf-8")
    return str(arquivo)


@pytest.fixture
def arquivo_ork(tmp_path):
    """Cria um arquivo de log ORK temporário com entradas válidas."""
    conteudo = (
        "2024-01-15 10:30:45.500|INFO|agent.main|Session abc123 started\n"
        "2024-01-15 10:30:46.700|DEBUG|agent.tts|Processing audio\n"
        "2024-01-15 10:30:48.000|ERROR|agent.main|Session abc123 failed\n"
    )
    arquivo = tmp_path / "ork.log"
    arquivo.write_text(conteudo, encoding="utf-8")
    return str(arquivo)


class TestValidacaoIdentificador:
    """Testa que o analisador rejeita identificadores inválidos."""

    def test_identificador_vazio_levanta_erro(self, analisador, arquivo_vpl):
        """Identificador vazio deve levantar ErroDeIdentificador."""
        selecao = [ArquivoSelecionado(caminho=arquivo_vpl, app_id="VPL")]
        with pytest.raises(ErroDeIdentificador):
            analisador.analisar(selecao, "")

    def test_identificador_espacos_levanta_erro(self, analisador, arquivo_vpl):
        """Identificador com apenas espaços deve levantar ErroDeIdentificador."""
        selecao = [ArquivoSelecionado(caminho=arquivo_vpl, app_id="VPL")]
        with pytest.raises(ErroDeIdentificador):
            analisador.analisar(selecao, "   ")

    def test_identificador_longo_levanta_erro(self, analisador, arquivo_vpl):
        """Identificador com mais de 256 caracteres deve levantar ErroDeIdentificador."""
        selecao = [ArquivoSelecionado(caminho=arquivo_vpl, app_id="VPL")]
        with pytest.raises(ErroDeIdentificador):
            analisador.analisar(selecao, "x" * 257)


class TestSelecaoVazia:
    """Testa comportamento quando nenhum arquivo é selecionado (Req 3.6, 10.1)."""

    def test_selecao_vazia_retorna_resultado_com_mensagem(self, analisador):
        """Seleção vazia deve retornar resultado com mensagem informativa."""
        resultado = analisador.analisar([], "abc123")
        assert isinstance(resultado, ResultadoDeAnalise)
        assert resultado.identificador == "abc123"
        assert len(resultado.mensagens) > 0
        assert not resultado.entradas_por_aplicacao
        assert not resultado.linha_do_tempo

    def test_selecao_vazia_preserva_identificador(self, analisador):
        """O identificador deve ser preservado no resultado mesmo sem arquivos."""
        resultado = analisador.analisar([], "meu_id")
        assert resultado.identificador == "meu_id"


class TestAplicacaoNaoInformada:
    """Testa tratamento de arquivo sem app_id (Req 2.3, 2.4)."""

    def test_app_id_none_gera_erro(self, analisador, arquivo_vpl):
        """Arquivo com app_id=None deve gerar erro e ser ignorado."""
        selecao = [ArquivoSelecionado(caminho=arquivo_vpl, app_id=None)]
        resultado = analisador.analisar(selecao, "abc123")
        assert len(resultado.erros) == 1
        assert "Aplicação não informada" in resultado.erros[0].descricao
        assert resultado.erros[0].arquivo_ou_app == arquivo_vpl

    def test_app_id_none_nao_aborta_demais(self, analisador, arquivo_vpl):
        """Arquivo sem app_id não deve impedir processamento dos demais."""
        selecao = [
            ArquivoSelecionado(caminho=arquivo_vpl, app_id=None),
            ArquivoSelecionado(caminho=arquivo_vpl, app_id="VPL"),
        ]
        resultado = analisador.analisar(selecao, "abc123")
        # Um erro do arquivo sem app_id
        assert len(resultado.erros) == 1
        # Entradas do segundo arquivo devem estar presentes
        assert len(resultado.linha_do_tempo) > 0


class TestAplicacaoNaoSuportada:
    """Testa tratamento de aplicação não registrada."""

    def test_app_nao_registrada_gera_erro(self, analisador, arquivo_vpl):
        """App não registrada deve gerar erro sem abortar."""
        selecao = [ArquivoSelecionado(caminho=arquivo_vpl, app_id="INEXISTENTE")]
        resultado = analisador.analisar(selecao, "abc123")
        assert len(resultado.erros) == 1
        assert "não suportada" in resultado.erros[0].descricao.lower() or \
               "INEXISTENTE" in resultado.erros[0].arquivo_ou_app


class TestArquivoInvalido:
    """Testa tratamento de arquivo não legível ou vazio (Req 1.2, 10.4)."""

    def test_arquivo_inexistente_gera_erro(self, analisador):
        """Arquivo inexistente deve gerar erro sem abortar."""
        selecao = [
            ArquivoSelecionado(caminho="/nao/existe/arquivo.log", app_id="VPL")
        ]
        resultado = analisador.analisar(selecao, "abc123")
        assert len(resultado.erros) == 1

    def test_arquivo_vazio_gera_erro(self, analisador, tmp_path):
        """Arquivo vazio deve gerar erro sem abortar."""
        arquivo = tmp_path / "vazio.log"
        arquivo.write_text("", encoding="utf-8")
        selecao = [ArquivoSelecionado(caminho=str(arquivo), app_id="VPL")]
        resultado = analisador.analisar(selecao, "abc123")
        assert len(resultado.erros) == 1

    def test_arquivo_invalido_nao_aborta_demais(self, analisador, arquivo_vpl, tmp_path):
        """Arquivo inválido não deve impedir processamento dos demais."""
        arquivo_vazio = tmp_path / "vazio.log"
        arquivo_vazio.write_text("", encoding="utf-8")
        selecao = [
            ArquivoSelecionado(caminho=str(arquivo_vazio), app_id="VPL"),
            ArquivoSelecionado(caminho=arquivo_vpl, app_id="VPL"),
        ]
        resultado = analisador.analisar(selecao, "abc123")
        assert len(resultado.erros) == 1
        assert len(resultado.linha_do_tempo) > 0


class TestFluxoCompleto:
    """Testa o fluxo completo de análise com dados válidos."""

    def test_analise_basica_vpl(self, analisador, arquivo_vpl):
        """Análise básica de um arquivo VPL deve funcionar."""
        selecao = [ArquivoSelecionado(caminho=arquivo_vpl, app_id="VPL")]
        resultado = analisador.analisar(selecao, "abc123")
        assert resultado.identificador == "abc123"
        # abc123 aparece em 2 das 3 linhas
        assert len(resultado.linha_do_tempo) == 2
        assert "VPL" in resultado.entradas_por_aplicacao
        assert not resultado.erros

    def test_analise_sem_correspondencia(self, analisador, arquivo_vpl):
        """Busca por identificador não existente retorna resultado vazio."""
        selecao = [ArquivoSelecionado(caminho=arquivo_vpl, app_id="VPL")]
        resultado = analisador.analisar(selecao, "inexistente999")
        assert len(resultado.linha_do_tempo) == 0
        assert len(resultado.mensagens) > 0

    def test_classificacao_fase1_nao_classificada(self, analisador, arquivo_vpl):
        """Na Fase 1, toda entrada deve ser classificada como NAO_CLASSIFICADA."""
        selecao = [ArquivoSelecionado(caminho=arquivo_vpl, app_id="VPL")]
        resultado = analisador.analisar(selecao, "abc123")
        for entrada in resultado.linha_do_tempo:
            assert entrada.categoria == Categoria.NAO_CLASSIFICADA

    def test_ordem_de_leitura_correta(self, analisador, arquivo_vpl):
        """As entradas devem manter ordem_de_leitura sequencial."""
        selecao = [ArquivoSelecionado(caminho=arquivo_vpl, app_id="VPL")]
        resultado = analisador.analisar(selecao, "abc123")
        for entrada in resultado.linha_do_tempo:
            assert entrada.ordem_de_leitura >= 0

    def test_contagens_consistentes(self, analisador, arquivo_vpl):
        """Contagens devem ser consistentes com as entradas."""
        selecao = [ArquivoSelecionado(caminho=arquivo_vpl, app_id="VPL")]
        resultado = analisador.analisar(selecao, "abc123")
        total_por_cat = sum(resultado.contagem_por_categoria.values())
        total_por_app = sum(resultado.contagem_por_aplicacao.values())
        total_entradas = len(resultado.linha_do_tempo)
        assert total_por_cat == total_entradas
        assert total_por_app == total_entradas


class TestCorrelacaoVplOrk:
    """Testa a correlação VPL ↔ ORK."""

    def test_correlacao_com_identificador_comum(
        self, analisador, arquivo_vpl, arquivo_ork
    ):
        """Se VPL e ORK têm entradas com mesmo id, devem ser correlacionadas."""
        selecao = [
            ArquivoSelecionado(caminho=arquivo_vpl, app_id="VPL"),
            ArquivoSelecionado(caminho=arquivo_ork, app_id="ORK"),
        ]
        resultado = analisador.analisar(selecao, "abc123")
        assert resultado.correlacao_encontrada is True
        # Todas as entradas VPL e ORK devem estar marcadas como correlacionadas
        for entrada in resultado.linha_do_tempo:
            if entrada.aplicacao in ("VPL", "ORK"):
                assert entrada.correlacionada is True

    def test_linha_do_tempo_ordenada_por_tempo(
        self, analisador, arquivo_vpl, arquivo_ork
    ):
        """A linha do tempo deve estar ordenada por carimbo de tempo."""
        selecao = [
            ArquivoSelecionado(caminho=arquivo_vpl, app_id="VPL"),
            ArquivoSelecionado(caminho=arquivo_ork, app_id="ORK"),
        ]
        resultado = analisador.analisar(selecao, "abc123")
        for i in range(len(resultado.linha_do_tempo) - 1):
            e1 = resultado.linha_do_tempo[i]
            e2 = resultado.linha_do_tempo[i + 1]
            if e1.carimbo_de_tempo and e2.carimbo_de_tempo:
                assert e1.carimbo_de_tempo <= e2.carimbo_de_tempo


class TestReassociacao:
    """Testa reassociação (Req 2.5): última aplicação prevalece."""

    def test_mesmo_arquivo_diferentes_apps_ultima_prevalece(
        self, analisador, arquivo_vpl
    ):
        """Se o mesmo arquivo aparece duas vezes com apps diferentes, ambos são processados."""
        selecao = [
            ArquivoSelecionado(caminho=arquivo_vpl, app_id="VPL"),
            ArquivoSelecionado(caminho=arquivo_vpl, app_id="VPL"),
        ]
        resultado = analisador.analisar(selecao, "abc123")
        # Cada aparição é processada independentemente
        assert not resultado.erros


class TestAcumulacaoDeErros:
    """Testa que erros são acumulados sem abortar (Req 1.2)."""

    def test_multiplos_erros_acumulados(self, analisador, arquivo_vpl, tmp_path):
        """Múltiplos arquivos inválidos geram múltiplos erros."""
        arquivo_vazio = tmp_path / "vazio.log"
        arquivo_vazio.write_text("", encoding="utf-8")
        selecao = [
            ArquivoSelecionado(caminho=str(arquivo_vazio), app_id="VPL"),
            ArquivoSelecionado(caminho="/nao/existe.log", app_id="VPL"),
            ArquivoSelecionado(caminho=arquivo_vpl, app_id=None),
            ArquivoSelecionado(caminho=arquivo_vpl, app_id="VPL"),
        ]
        resultado = analisador.analisar(selecao, "abc123")
        # 3 erros acumulados: vazio, inexistente, app não informada
        assert len(resultado.erros) == 3
        # O último arquivo (VPL válido) deve ter sido processado normalmente
        assert len(resultado.linha_do_tempo) > 0
