"""Testes unitários para o OrkParser.

Verifica os contratos do Parser_de_Aplicacao para o formato ORK:
- Interpretação correta de linhas válidas (timestamp | level | message)
- Marcação como não interpretada quando campos são inválidos
- Preservação do texto original em todos os casos
- Propriedade de round-trip (interpretar → imprimir → interpretar)
- Níveis de severidade válidos
"""

from datetime import datetime, timezone

import pytest

from log_analyzer.apps.ork import OrkParser
from log_analyzer.core.interfaces import Parser_de_Aplicacao
from log_analyzer.core.modelos import EntradaDeLog


@pytest.fixture
def parser() -> OrkParser:
    """Fornece uma instância do OrkParser."""
    return OrkParser()


class TestOrkParserInterface:
    """Verifica que OrkParser implementa a interface Parser_de_Aplicacao."""

    def test_is_instance_of_parser_de_aplicacao(self, parser: OrkParser):
        """OrkParser é uma subclasse concreta de Parser_de_Aplicacao."""
        assert isinstance(parser, Parser_de_Aplicacao)

    def test_niveis_de_severidade_returns_frozenset(self, parser: OrkParser):
        """niveis_de_severidade retorna um frozenset."""
        niveis = parser.niveis_de_severidade
        assert isinstance(niveis, frozenset)

    def test_niveis_de_severidade_contem_niveis_esperados(self, parser: OrkParser):
        """Contém os 5 níveis de severidade do ORK."""
        esperados = {"DEBUG", "INFO", "WARN", "ERROR", "FATAL"}
        assert parser.niveis_de_severidade == esperados


class TestOrkParserInterpretacao:
    """Testa interpretar_entrada com diversas entradas."""

    def test_linha_valida_info(self, parser: OrkParser):
        """Interpreta corretamente uma linha INFO válida."""
        texto = "2024-01-15T10:30:45.123000+00:00 | INFO | Call initiated for session abc-123"
        entrada = parser.interpretar_entrada(texto)

        assert entrada.interpretada is True
        assert entrada.aplicacao == "ORK"
        assert entrada.nivel_de_severidade == "INFO"
        assert entrada.mensagem == "Call initiated for session abc-123"
        assert entrada.carimbo_de_tempo is not None
        assert entrada.carimbo_de_tempo.year == 2024
        assert entrada.carimbo_de_tempo.month == 1
        assert entrada.carimbo_de_tempo.day == 15

    def test_linha_valida_error(self, parser: OrkParser):
        """Interpreta corretamente uma linha ERROR válida."""
        texto = "2024-06-20T08:00:00+00:00 | ERROR | Connection timeout"
        entrada = parser.interpretar_entrada(texto)

        assert entrada.interpretada is True
        assert entrada.nivel_de_severidade == "ERROR"
        assert entrada.mensagem == "Connection timeout"

    def test_linha_valida_debug(self, parser: OrkParser):
        """Interpreta corretamente uma linha DEBUG válida."""
        texto = "2024-03-10T12:00:00 | DEBUG | Entering function process_call"
        entrada = parser.interpretar_entrada(texto)

        assert entrada.interpretada is True
        assert entrada.nivel_de_severidade == "DEBUG"
        assert entrada.mensagem == "Entering function process_call"

    def test_linha_valida_warn(self, parser: OrkParser):
        """Interpreta corretamente uma linha WARN válida."""
        texto = "2024-05-01T15:45:30.500000+00:00 | WARN | High latency detected"
        entrada = parser.interpretar_entrada(texto)

        assert entrada.interpretada is True
        assert entrada.nivel_de_severidade == "WARN"
        assert entrada.mensagem == "High latency detected"

    def test_linha_valida_fatal(self, parser: OrkParser):
        """Interpreta corretamente uma linha FATAL válida."""
        texto = "2024-12-31T23:59:59+00:00 | FATAL | System shutdown imminent"
        entrada = parser.interpretar_entrada(texto)

        assert entrada.interpretada is True
        assert entrada.nivel_de_severidade == "FATAL"
        assert entrada.mensagem == "System shutdown imminent"

    def test_nivel_case_insensitive(self, parser: OrkParser):
        """Aceita nível de severidade em qualquer casing."""
        texto = "2024-01-15T10:30:45+00:00 | info | Test message"
        entrada = parser.interpretar_entrada(texto)

        assert entrada.interpretada is True
        assert entrada.nivel_de_severidade == "INFO"

    def test_mensagem_com_pipes(self, parser: OrkParser):
        """Mensagem pode conter pipes sem quebrar a interpretação."""
        texto = "2024-01-15T10:30:45+00:00 | INFO | Data | more | content here"
        entrada = parser.interpretar_entrada(texto)

        assert entrada.interpretada is True
        assert entrada.mensagem == "Data | more | content here"

    def test_ordem_de_leitura_default_zero(self, parser: OrkParser):
        """ordem_de_leitura é sempre 0 (chamadores gerenciam)."""
        texto = "2024-01-15T10:30:45+00:00 | INFO | Test"
        entrada = parser.interpretar_entrada(texto)
        assert entrada.ordem_de_leitura == 0


class TestOrkParserNaoInterpretada:
    """Testa que linhas inválidas são marcadas como não interpretadas."""

    def test_linha_vazia(self, parser: OrkParser):
        """Linha vazia é não interpretada."""
        entrada = parser.interpretar_entrada("")
        assert entrada.interpretada is False
        assert entrada.texto_original == ""
        assert entrada.aplicacao == "ORK"

    def test_linha_sem_separador(self, parser: OrkParser):
        """Linha sem o separador pipe é não interpretada."""
        texto = "Isto é apenas texto sem formato"
        entrada = parser.interpretar_entrada(texto)
        assert entrada.interpretada is False
        assert entrada.texto_original == texto

    def test_linha_com_um_separador_apenas(self, parser: OrkParser):
        """Linha com apenas um separador é não interpretada."""
        texto = "2024-01-15T10:30:45 | INFO"
        entrada = parser.interpretar_entrada(texto)
        assert entrada.interpretada is False
        assert entrada.texto_original == texto

    def test_timestamp_invalido(self, parser: OrkParser):
        """Timestamp inválido resulta em não interpretada."""
        texto = "not-a-date | INFO | Some message"
        entrada = parser.interpretar_entrada(texto)
        assert entrada.interpretada is False
        assert entrada.texto_original == texto

    def test_nivel_invalido(self, parser: OrkParser):
        """Nível de severidade não reconhecido resulta em não interpretada."""
        texto = "2024-01-15T10:30:45+00:00 | CRITICAL | Some message"
        entrada = parser.interpretar_entrada(texto)
        assert entrada.interpretada is False
        assert entrada.texto_original == texto

    def test_mensagem_vazia(self, parser: OrkParser):
        """Mensagem vazia (apenas espaços) resulta em não interpretada."""
        texto = "2024-01-15T10:30:45+00:00 | INFO |    "
        entrada = parser.interpretar_entrada(texto)
        assert entrada.interpretada is False
        assert entrada.texto_original == texto

    def test_texto_original_preservado_sempre(self, parser: OrkParser):
        """O texto_original é sempre preservado, independente da interpretação."""
        texto = "garbage data \x00 \t lixo"
        entrada = parser.interpretar_entrada(texto)
        assert entrada.texto_original == texto


class TestOrkParserImprimir:
    """Testa imprimir_entrada."""

    def test_imprimir_entrada_interpretada(self, parser: OrkParser):
        """Imprime uma entrada interpretada no formato pipe-delimited."""
        texto = "2024-01-15T10:30:45+00:00 | INFO | Call initiated"
        entrada = parser.interpretar_entrada(texto)
        assert entrada.interpretada is True

        impressao = parser.imprimir_entrada(entrada)
        assert "2024-01-15" in impressao
        assert "INFO" in impressao
        assert "Call initiated" in impressao
        assert " | " in impressao

    def test_imprimir_entrada_nao_interpretada(self, parser: OrkParser):
        """Imprime o texto original para entrada não interpretada."""
        texto = "linha invalida qualquer"
        entrada = parser.interpretar_entrada(texto)
        assert entrada.interpretada is False

        impressao = parser.imprimir_entrada(entrada)
        assert impressao == texto


class TestOrkParserRoundTrip:
    """Testa a propriedade de round-trip: interpretar → imprimir → interpretar."""

    def test_round_trip_basico(self, parser: OrkParser):
        """Round-trip preserva campos para uma linha simples."""
        texto = "2024-01-15T10:30:45+00:00 | INFO | Call initiated for session abc-123"
        entrada1 = parser.interpretar_entrada(texto)
        assert entrada1.interpretada is True

        texto_impresso = parser.imprimir_entrada(entrada1)
        entrada2 = parser.interpretar_entrada(texto_impresso)

        assert entrada2.interpretada is True
        assert entrada2.carimbo_de_tempo == entrada1.carimbo_de_tempo
        assert entrada2.nivel_de_severidade == entrada1.nivel_de_severidade
        assert entrada2.mensagem == entrada1.mensagem

    def test_round_trip_com_todos_os_niveis(self, parser: OrkParser):
        """Round-trip funciona para todos os níveis de severidade."""
        for nivel in parser.niveis_de_severidade:
            texto = f"2024-06-15T12:00:00+00:00 | {nivel} | Msg for {nivel}"
            entrada1 = parser.interpretar_entrada(texto)
            assert entrada1.interpretada is True

            texto_impresso = parser.imprimir_entrada(entrada1)
            entrada2 = parser.interpretar_entrada(texto_impresso)

            assert entrada2.interpretada is True
            assert entrada2.carimbo_de_tempo == entrada1.carimbo_de_tempo
            assert entrada2.nivel_de_severidade == entrada1.nivel_de_severidade
            assert entrada2.mensagem == entrada1.mensagem

    def test_round_trip_mensagem_com_pipes(self, parser: OrkParser):
        """Round-trip preserva mensagens que contêm o separador pipe."""
        texto = "2024-01-15T10:30:45+00:00 | ERROR | Error in | module | data"
        entrada1 = parser.interpretar_entrada(texto)
        assert entrada1.interpretada is True

        texto_impresso = parser.imprimir_entrada(entrada1)
        entrada2 = parser.interpretar_entrada(texto_impresso)

        assert entrada2.interpretada is True
        assert entrada2.mensagem == entrada1.mensagem


class TestOrkParserInterpretar_arquivo:
    """Testa interpretar_arquivo (default da interface)."""

    def test_interpreta_multiplas_linhas(self, parser: OrkParser):
        """interpretar_arquivo processa várias linhas em sequência."""
        linhas = [
            "2024-01-15T10:30:45+00:00 | INFO | Line 1",
            "invalid line",
            "2024-01-15T10:30:46+00:00 | ERROR | Line 3",
        ]
        resultado = parser.interpretar_arquivo(linhas)

        assert len(resultado) == 3
        assert resultado[0].interpretada is True
        assert resultado[1].interpretada is False
        assert resultado[2].interpretada is True
