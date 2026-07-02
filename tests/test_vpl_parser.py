"""Testes unitários para o VplParser (log_analyzer.apps.vpl).

Verifica:
- niveis_de_severidade retorna o frozenset correto
- interpretar_entrada para linhas válidas (interpretada=True)
- interpretar_entrada para linhas inválidas (interpretada=False, texto_original preservado)
- imprimir_entrada produz representação textual com timestamp, severidade e mensagem
- Propriedade de round-trip: interpretar(imprimir(interpretar(x))) == interpretar(x)
"""

from datetime import datetime

import pytest

from log_analyzer.apps.vpl import VplParser
from log_analyzer.core.modelos import Categoria, EntradaDeLog


@pytest.fixture
def parser() -> VplParser:
    return VplParser()


# ─── Testes de niveis_de_severidade ────────────────────────────────────────────


class TestNiveisDeSeveridade:
    def test_retorna_frozenset(self, parser: VplParser):
        niveis = parser.niveis_de_severidade
        assert isinstance(niveis, frozenset)

    def test_contem_todos_os_niveis_freeswitch(self, parser: VplParser):
        esperados = {"DEBUG", "INFO", "NOTICE", "WARNING", "ERR", "CRIT", "ALERT"}
        assert parser.niveis_de_severidade == esperados

    def test_total_de_niveis(self, parser: VplParser):
        assert len(parser.niveis_de_severidade) == 7


# ─── Testes de interpretar_entrada — linhas válidas ────────────────────────────


class TestInterpretarEntradaValida:
    def test_linha_info(self, parser: VplParser):
        texto = "2024-01-15 10:30:45.123 [INFO] mod_sofia.c:1234 Session started"
        entrada = parser.interpretar_entrada(texto)
        assert entrada.interpretada is True
        assert entrada.aplicacao == "VPL"
        assert entrada.ordem_de_leitura == 0
        assert entrada.carimbo_de_tempo == datetime(2024, 1, 15, 10, 30, 45, 123000)
        assert entrada.nivel_de_severidade == "INFO"
        assert entrada.mensagem == "Session started"
        assert entrada.texto_original == texto

    def test_linha_warning(self, parser: VplParser):
        texto = "2023-12-31 23:59:59.999 [WARNING] switch_core.c:100 High load detected"
        entrada = parser.interpretar_entrada(texto)
        assert entrada.interpretada is True
        assert entrada.nivel_de_severidade == "WARNING"
        assert entrada.mensagem == "High load detected"

    def test_linha_err(self, parser: VplParser):
        texto = "2024-06-01 00:00:00.000 [ERR] mod_dptools.c:42 Connection refused"
        entrada = parser.interpretar_entrada(texto)
        assert entrada.interpretada is True
        assert entrada.nivel_de_severidade == "ERR"
        assert entrada.mensagem == "Connection refused"

    def test_linha_debug(self, parser: VplParser):
        texto = "2024-03-10 08:15:30.500 [DEBUG] mod_event.c:99 Event fired"
        entrada = parser.interpretar_entrada(texto)
        assert entrada.interpretada is True
        assert entrada.nivel_de_severidade == "DEBUG"

    def test_linha_crit(self, parser: VplParser):
        texto = "2024-01-01 12:00:00.001 [CRIT] core.c:1 System failure"
        entrada = parser.interpretar_entrada(texto)
        assert entrada.interpretada is True
        assert entrada.nivel_de_severidade == "CRIT"

    def test_linha_alert(self, parser: VplParser):
        texto = "2024-01-01 12:00:00.001 [ALERT] core.c:1 Immediate action required"
        entrada = parser.interpretar_entrada(texto)
        assert entrada.interpretada is True
        assert entrada.nivel_de_severidade == "ALERT"

    def test_linha_notice(self, parser: VplParser):
        texto = "2024-01-01 12:00:00.001 [NOTICE] mod_sofia.c:55 Registration complete"
        entrada = parser.interpretar_entrada(texto)
        assert entrada.interpretada is True
        assert entrada.nivel_de_severidade == "NOTICE"

    def test_mensagem_com_espacos(self, parser: VplParser):
        texto = "2024-01-15 10:30:45.123 [INFO] mod.c:1 Message with  multiple   spaces"
        entrada = parser.interpretar_entrada(texto)
        assert entrada.interpretada is True
        assert entrada.mensagem == "Message with  multiple   spaces"

    def test_categoria_padrao_nao_classificada(self, parser: VplParser):
        texto = "2024-01-15 10:30:45.123 [INFO] mod.c:1 Some log"
        entrada = parser.interpretar_entrada(texto)
        assert entrada.categoria == Categoria.NAO_CLASSIFICADA

    def test_correlacionada_padrao_false(self, parser: VplParser):
        texto = "2024-01-15 10:30:45.123 [INFO] mod.c:1 Some log"
        entrada = parser.interpretar_entrada(texto)
        assert entrada.correlacionada is False


# ─── Testes de interpretar_entrada — linhas inválidas ──────────────────────────


class TestInterpretarEntradaInvalida:
    def test_linha_vazia(self, parser: VplParser):
        entrada = parser.interpretar_entrada("")
        assert entrada.interpretada is False
        assert entrada.texto_original == ""

    def test_texto_sem_formato(self, parser: VplParser):
        texto = "isto nao e um log valido"
        entrada = parser.interpretar_entrada(texto)
        assert entrada.interpretada is False
        assert entrada.texto_original == texto

    def test_timestamp_invalido(self, parser: VplParser):
        texto = "2024-13-01 10:30:45.123 [INFO] mod.c:1 Message"
        entrada = parser.interpretar_entrada(texto)
        assert entrada.interpretada is False
        assert entrada.texto_original == texto

    def test_severidade_invalida(self, parser: VplParser):
        texto = "2024-01-15 10:30:45.123 [UNKNOWN] mod.c:1 Message"
        entrada = parser.interpretar_entrada(texto)
        assert entrada.interpretada is False
        assert entrada.texto_original == texto

    def test_mensagem_ausente(self, parser: VplParser):
        texto = "2024-01-15 10:30:45.123 [INFO] mod.c:1 "
        entrada = parser.interpretar_entrada(texto)
        assert entrada.interpretada is False
        assert entrada.texto_original == texto

    def test_sem_colchetes_no_nivel(self, parser: VplParser):
        texto = "2024-01-15 10:30:45.123 INFO mod.c:1 Message"
        entrada = parser.interpretar_entrada(texto)
        assert entrada.interpretada is False

    def test_timestamp_incompleto(self, parser: VplParser):
        texto = "2024-01-15 10:30:45 [INFO] mod.c:1 Message"
        entrada = parser.interpretar_entrada(texto)
        assert entrada.interpretada is False

    def test_aplicacao_e_vpl(self, parser: VplParser):
        texto = "texto invalido qualquer"
        entrada = parser.interpretar_entrada(texto)
        assert entrada.aplicacao == "VPL"

    def test_ordem_de_leitura_e_zero(self, parser: VplParser):
        texto = "texto invalido qualquer"
        entrada = parser.interpretar_entrada(texto)
        assert entrada.ordem_de_leitura == 0


# ─── Testes de imprimir_entrada ────────────────────────────────────────────────


class TestImprimirEntrada:
    def test_entrada_interpretada(self, parser: VplParser):
        entrada = EntradaDeLog(
            texto_original="original",
            aplicacao="VPL",
            ordem_de_leitura=0,
            interpretada=True,
            carimbo_de_tempo=datetime(2024, 1, 15, 10, 30, 45, 123000),
            nivel_de_severidade="INFO",
            mensagem="Session started",
        )
        resultado = parser.imprimir_entrada(entrada)
        assert "2024-01-15 10:30:45.123" in resultado
        assert "[INFO]" in resultado
        assert "Session started" in resultado

    def test_entrada_nao_interpretada_retorna_texto_original(self, parser: VplParser):
        texto = "linha sem formato"
        entrada = EntradaDeLog(
            texto_original=texto,
            aplicacao="VPL",
            ordem_de_leitura=0,
            interpretada=False,
        )
        resultado = parser.imprimir_entrada(entrada)
        assert resultado == texto


# ─── Teste de round-trip ───────────────────────────────────────────────────────


class TestRoundTrip:
    def test_roundtrip_basico(self, parser: VplParser):
        """interpretar(imprimir(interpretar(x))) == interpretar(x) para campos estruturados."""
        texto = "2024-01-15 10:30:45.123 [INFO] mod_sofia.c:1234 Call initiated"
        # Primeira interpretação
        e1 = parser.interpretar_entrada(texto)
        assert e1.interpretada is True
        # Imprimir
        impresso = parser.imprimir_entrada(e1)
        # Segunda interpretação
        e2 = parser.interpretar_entrada(impresso)
        assert e2.interpretada is True
        # Campos devem ser idênticos
        assert e2.carimbo_de_tempo == e1.carimbo_de_tempo
        assert e2.nivel_de_severidade == e1.nivel_de_severidade
        assert e2.mensagem == e1.mensagem

    def test_roundtrip_todos_os_niveis(self, parser: VplParser):
        """Round-trip funciona para todos os níveis de severidade."""
        for nivel in parser.niveis_de_severidade:
            texto = f"2024-06-15 12:00:00.000 [{nivel}] source.c:1 Test message"
            e1 = parser.interpretar_entrada(texto)
            assert e1.interpretada is True
            impresso = parser.imprimir_entrada(e1)
            e2 = parser.interpretar_entrada(impresso)
            assert e2.interpretada is True
            assert e2.carimbo_de_tempo == e1.carimbo_de_tempo
            assert e2.nivel_de_severidade == e1.nivel_de_severidade
            assert e2.mensagem == e1.mensagem
