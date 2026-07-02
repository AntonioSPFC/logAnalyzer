"""Testes para a filtragem por Identificador (Req 3.1, 3.2)."""

from datetime import datetime

import pytest

from log_analyzer.core.modelos import EntradaDeLog, Categoria
from log_analyzer.core.filtro import filtrar_por_identificador


def _entrada(texto: str, ordem: int = 0, app: str = "VPL") -> EntradaDeLog:
    """Helper para criar EntradaDeLog não interpretada com texto_original dado."""
    return EntradaDeLog(
        texto_original=texto,
        aplicacao=app,
        ordem_de_leitura=ordem,
        interpretada=False,
    )


class TestFiltrarPorIdentificador:
    """Testes unitários para filtrar_por_identificador."""

    def test_seleciona_entrada_com_identificador_exato(self):
        entradas = [_entrada("session-id-abc123")]
        resultado = filtrar_por_identificador(entradas, "session-id-abc123")
        assert resultado == entradas

    def test_case_insensitive_match(self):
        entradas = [_entrada("Chamada UUID-ABC iniciada")]
        resultado = filtrar_por_identificador(entradas, "uuid-abc")
        assert resultado == entradas

    def test_case_insensitive_identificador_uppercase(self):
        entradas = [_entrada("log com uuid-abc no meio")]
        resultado = filtrar_por_identificador(entradas, "UUID-ABC")
        assert resultado == entradas

    def test_nao_seleciona_entrada_sem_identificador(self):
        entradas = [_entrada("outra coisa qualquer")]
        resultado = filtrar_por_identificador(entradas, "uuid-abc")
        assert resultado == []

    def test_filtra_corretamente_mistura(self):
        e1 = _entrada("log com ID-123 aqui", ordem=0)
        e2 = _entrada("log sem nada relevante", ordem=1)
        e3 = _entrada("outro log com id-123 ali", ordem=2)
        entradas = [e1, e2, e3]
        resultado = filtrar_por_identificador(entradas, "id-123")
        assert resultado == [e1, e3]

    def test_lista_vazia_retorna_lista_vazia(self):
        resultado = filtrar_por_identificador([], "qualquer")
        assert resultado == []

    def test_identificador_substring_match(self):
        entradas = [_entrada("2024-01-01 INFO session=abc-def-ghi started")]
        resultado = filtrar_por_identificador(entradas, "abc-def-ghi")
        assert resultado == entradas

    def test_nenhuma_correspondencia_retorna_vazio(self):
        entradas = [
            _entrada("log A", ordem=0),
            _entrada("log B", ordem=1),
            _entrada("log C", ordem=2),
        ]
        resultado = filtrar_por_identificador(entradas, "xyz-nao-existe")
        assert resultado == []

    def test_todas_correspondem(self):
        entradas = [
            _entrada("abc linha 1", ordem=0),
            _entrada("ABC linha 2", ordem=1),
            _entrada("AbC linha 3", ordem=2),
        ]
        resultado = filtrar_por_identificador(entradas, "abc")
        assert resultado == entradas

    def test_preserva_ordem_original(self):
        e1 = _entrada("match-id primeiro", ordem=0)
        e2 = _entrada("sem match", ordem=1)
        e3 = _entrada("match-id terceiro", ordem=2)
        resultado = filtrar_por_identificador([e1, e2, e3], "match-id")
        assert resultado == [e1, e3]

    def test_entradas_interpretadas_tambem_filtradas(self):
        entrada = EntradaDeLog(
            texto_original="2024-01-15 10:00:00 INFO call-id-XYZ started",
            aplicacao="ORK",
            ordem_de_leitura=0,
            interpretada=True,
            carimbo_de_tempo=datetime(2024, 1, 15, 10, 0, 0),
            nivel_de_severidade="INFO",
            mensagem="call-id-XYZ started",
        )
        resultado = filtrar_por_identificador([entrada], "CALL-ID-XYZ")
        assert resultado == [entrada]
