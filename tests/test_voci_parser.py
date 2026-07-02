"""Testes unitários para o VociParser (aplicação VOCI — transcritor de áudio).

Valida os contratos do parser:
- Interpretação de linhas válidas (Req 4.1, 6.4)
- Marcação como não interpretada quando formato inválido (Req 4.2, 6.7)
- Preservação do texto original (Req 4.3)
- Impressão reconstrói o formato canônico (Req 4.4)
- Propriedade de round-trip (Req 4.5)
"""

from datetime import datetime

import pytest

from log_analyzer.apps.voci import VociParser
from log_analyzer.core.interfaces import Parser_de_Aplicacao
from log_analyzer.core.modelos import EntradaDeLog


@pytest.fixture
def parser() -> VociParser:
    """Fixture que retorna uma instância do VociParser."""
    return VociParser()


class TestVociParserInterface:
    """Verifica que VociParser implementa corretamente a interface Parser_de_Aplicacao."""

    def test_is_instance_of_parser_de_aplicacao(self, parser: VociParser):
        """VociParser é uma subclasse de Parser_de_Aplicacao."""
        assert isinstance(parser, Parser_de_Aplicacao)

    def test_niveis_de_severidade_returns_frozenset(self, parser: VociParser):
        """niveis_de_severidade retorna um frozenset."""
        niveis = parser.niveis_de_severidade
        assert isinstance(niveis, frozenset)

    def test_niveis_de_severidade_contains_expected_levels(self, parser: VociParser):
        """niveis_de_severidade contém DEBUG, INFO, WARNING, ERROR, CRITICAL."""
        esperados = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        assert parser.niveis_de_severidade == esperados


class TestVociParserInterpretarEntrada:
    """Testes para interpretar_entrada com linhas válidas e inválidas."""

    def test_linha_valida_info(self, parser: VociParser):
        """Interpreta corretamente uma linha INFO válida."""
        texto = "2024-01-15 10:30:45\tINFO\tTranscription started for session abc-123"
        entrada = parser.interpretar_entrada(texto)

        assert entrada.interpretada is True
        assert entrada.aplicacao == "VOCI"
        assert entrada.ordem_de_leitura == 0
        assert entrada.carimbo_de_tempo == datetime(2024, 1, 15, 10, 30, 45)
        assert entrada.nivel_de_severidade == "INFO"
        assert entrada.mensagem == "Transcription started for session abc-123"
        assert entrada.texto_original == texto

    def test_linha_valida_debug(self, parser: VociParser):
        """Interpreta corretamente uma linha DEBUG válida."""
        texto = "2023-06-01 00:00:00\tDEBUG\tInitializing audio pipeline"
        entrada = parser.interpretar_entrada(texto)

        assert entrada.interpretada is True
        assert entrada.nivel_de_severidade == "DEBUG"
        assert entrada.mensagem == "Initializing audio pipeline"

    def test_linha_valida_warning(self, parser: VociParser):
        """Interpreta corretamente uma linha WARNING válida."""
        texto = "2024-12-31 23:59:59\tWARNING\tAudio buffer low"
        entrada = parser.interpretar_entrada(texto)

        assert entrada.interpretada is True
        assert entrada.nivel_de_severidade == "WARNING"

    def test_linha_valida_error(self, parser: VociParser):
        """Interpreta corretamente uma linha ERROR válida."""
        texto = "2024-03-20 15:45:00\tERROR\tTranscription failed: timeout"
        entrada = parser.interpretar_entrada(texto)

        assert entrada.interpretada is True
        assert entrada.nivel_de_severidade == "ERROR"
        assert entrada.mensagem == "Transcription failed: timeout"

    def test_linha_valida_critical(self, parser: VociParser):
        """Interpreta corretamente uma linha CRITICAL válida."""
        texto = "2024-07-04 12:00:00\tCRITICAL\tService crashed unexpectedly"
        entrada = parser.interpretar_entrada(texto)

        assert entrada.interpretada is True
        assert entrada.nivel_de_severidade == "CRITICAL"

    def test_nivel_case_insensitive(self, parser: VociParser):
        """Aceita nível de severidade em qualquer casing."""
        texto = "2024-01-01 00:00:00\tinfo\tTest message"
        entrada = parser.interpretar_entrada(texto)

        assert entrada.interpretada is True
        assert entrada.nivel_de_severidade == "INFO"

    def test_linha_sem_tab_nao_interpretada(self, parser: VociParser):
        """Linha sem tabulação é marcada como não interpretada."""
        texto = "2024-01-15 10:30:45 INFO Transcription started"
        entrada = parser.interpretar_entrada(texto)

        assert entrada.interpretada is False
        assert entrada.texto_original == texto

    def test_linha_apenas_um_tab_nao_interpretada(self, parser: VociParser):
        """Linha com apenas uma tabulação (faltando campo) é não interpretada."""
        texto = "2024-01-15 10:30:45\tINFO"
        entrada = parser.interpretar_entrada(texto)

        assert entrada.interpretada is False
        assert entrada.texto_original == texto

    def test_timestamp_invalido_nao_interpretada(self, parser: VociParser):
        """Linha com timestamp inválido é marcada como não interpretada."""
        texto = "not-a-date\tINFO\tSome message"
        entrada = parser.interpretar_entrada(texto)

        assert entrada.interpretada is False
        assert entrada.texto_original == texto

    def test_nivel_invalido_nao_interpretada(self, parser: VociParser):
        """Linha com nível de severidade inválido é marcada como não interpretada."""
        texto = "2024-01-15 10:30:45\tTRACE\tSome message"
        entrada = parser.interpretar_entrada(texto)

        assert entrada.interpretada is False
        assert entrada.texto_original == texto

    def test_mensagem_vazia_nao_interpretada(self, parser: VociParser):
        """Linha com mensagem vazia é marcada como não interpretada."""
        texto = "2024-01-15 10:30:45\tINFO\t"
        entrada = parser.interpretar_entrada(texto)

        assert entrada.interpretada is False
        assert entrada.texto_original == texto

    def test_mensagem_apenas_espacos_nao_interpretada(self, parser: VociParser):
        """Linha com mensagem composta apenas de espaços é não interpretada."""
        texto = "2024-01-15 10:30:45\tINFO\t   "
        entrada = parser.interpretar_entrada(texto)

        assert entrada.interpretada is False
        assert entrada.texto_original == texto

    def test_linha_vazia_nao_interpretada(self, parser: VociParser):
        """Linha vazia é marcada como não interpretada."""
        entrada = parser.interpretar_entrada("")

        assert entrada.interpretada is False
        assert entrada.texto_original == ""

    def test_texto_original_sempre_preservado(self, parser: VociParser):
        """texto_original é preservado inalterado (Req 4.3)."""
        texto = "2024-01-15 10:30:45\tINFO\tHello world"
        entrada = parser.interpretar_entrada(texto)
        assert entrada.texto_original == texto

    def test_mensagem_com_tabs_preservada(self, parser: VociParser):
        """Mensagem que contém tabs adicionais é preservada integralmente."""
        texto = "2024-01-15 10:30:45\tINFO\tPart1\tPart2\tPart3"
        entrada = parser.interpretar_entrada(texto)

        assert entrada.interpretada is True
        # split com maxsplit=2 garante que tabs na mensagem são preservados
        assert entrada.mensagem == "Part1\tPart2\tPart3"


class TestVociParserImprimirEntrada:
    """Testes para imprimir_entrada."""

    def test_imprimir_entrada_interpretada(self, parser: VociParser):
        """Imprime uma entrada interpretada no formato canônico."""
        entrada = EntradaDeLog(
            texto_original="original",
            aplicacao="VOCI",
            ordem_de_leitura=0,
            interpretada=True,
            carimbo_de_tempo=datetime(2024, 1, 15, 10, 30, 45),
            nivel_de_severidade="INFO",
            mensagem="Transcription started",
        )
        resultado = parser.imprimir_entrada(entrada)
        assert resultado == "2024-01-15 10:30:45\tINFO\tTranscription started"

    def test_imprimir_entrada_nao_interpretada_retorna_texto_original(
        self, parser: VociParser
    ):
        """Imprime entrada não interpretada retornando o texto_original."""
        texto = "linha malformada sem formato"
        entrada = EntradaDeLog(
            texto_original=texto,
            aplicacao="VOCI",
            ordem_de_leitura=0,
            interpretada=False,
        )
        resultado = parser.imprimir_entrada(entrada)
        assert resultado == texto


class TestVociParserRoundTrip:
    """Testes de round-trip: interpretar → imprimir → interpretar (Req 4.5)."""

    def test_round_trip_preserva_campos(self, parser: VociParser):
        """O ciclo interpretar → imprimir → interpretar preserva os campos."""
        texto = "2024-01-15 10:30:45\tINFO\tTranscription started for session abc-123"

        # Primeira interpretação
        entrada1 = parser.interpretar_entrada(texto)
        assert entrada1.interpretada is True

        # Imprimir
        impresso = parser.imprimir_entrada(entrada1)

        # Segunda interpretação
        entrada2 = parser.interpretar_entrada(impresso)
        assert entrada2.interpretada is True

        # Campos devem ser idênticos
        assert entrada1.carimbo_de_tempo == entrada2.carimbo_de_tempo
        assert entrada1.nivel_de_severidade == entrada2.nivel_de_severidade
        assert entrada1.mensagem == entrada2.mensagem

    def test_round_trip_todos_niveis(self, parser: VociParser):
        """Round-trip funciona para todos os níveis de severidade."""
        for nivel in parser.niveis_de_severidade:
            texto = f"2024-06-15 08:00:00\t{nivel}\tTest message for {nivel}"
            entrada1 = parser.interpretar_entrada(texto)
            impresso = parser.imprimir_entrada(entrada1)
            entrada2 = parser.interpretar_entrada(impresso)

            assert entrada1.carimbo_de_tempo == entrada2.carimbo_de_tempo
            assert entrada1.nivel_de_severidade == entrada2.nivel_de_severidade
            assert entrada1.mensagem == entrada2.mensagem


class TestVociParserInterpretarArquivo:
    """Testes para interpretar_arquivo (streaming)."""

    def test_interpreta_multiplas_linhas(self, parser: VociParser):
        """interpretar_arquivo processa múltiplas linhas."""
        linhas = [
            "2024-01-15 10:30:45\tINFO\tLine 1",
            "invalid line",
            "2024-01-15 10:30:46\tERROR\tLine 3",
        ]
        resultado = parser.interpretar_arquivo(linhas)

        assert len(resultado) == 3
        assert resultado[0].interpretada is True
        assert resultado[1].interpretada is False
        assert resultado[2].interpretada is True

    def test_interpreta_arquivo_vazio(self, parser: VociParser):
        """interpretar_arquivo com lista vazia retorna lista vazia."""
        resultado = parser.interpretar_arquivo([])
        assert resultado == []
