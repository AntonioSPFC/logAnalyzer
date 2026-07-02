"""Testes unitários para os Padrões de Análise da Fase 1 (VplPadrao, OrkPadrao, VociPadrao).

Verifica:
- Cada classe pode ser instanciada sem erro.
- `categorias` contém SUCESSO e ERRO.
- `classificar` sempre retorna NAO_CLASSIFICADA para qualquer entrada.
"""

import pytest
from datetime import datetime

from log_analyzer.apps.padroes import OrkPadrao, VociPadrao, VplPadrao
from log_analyzer.core.modelos import Categoria, EntradaDeLog


# --- Fixtures ---


@pytest.fixture
def entrada_interpretada() -> EntradaDeLog:
    """Entrada de log interpretada para uso nos testes."""
    return EntradaDeLog(
        texto_original="2024-01-01 10:00:00 INFO Teste de mensagem",
        aplicacao="vpl",
        ordem_de_leitura=0,
        interpretada=True,
        carimbo_de_tempo=datetime(2024, 1, 1, 10, 0, 0),
        nivel_de_severidade="INFO",
        mensagem="Teste de mensagem",
    )


@pytest.fixture
def entrada_nao_interpretada() -> EntradaDeLog:
    """Entrada de log não interpretada para uso nos testes."""
    return EntradaDeLog(
        texto_original="linha sem formato reconhecido",
        aplicacao="ork",
        ordem_de_leitura=1,
        interpretada=False,
    )


# --- Testes de instanciação ---


class TestInstanciacao:
    """Verifica que cada Padrão pode ser instanciado corretamente."""

    def test_vpl_padrao_instancia(self) -> None:
        padrao = VplPadrao()
        assert padrao is not None

    def test_ork_padrao_instancia(self) -> None:
        padrao = OrkPadrao()
        assert padrao is not None

    def test_voci_padrao_instancia(self) -> None:
        padrao = VociPadrao()
        assert padrao is not None


# --- Testes de categorias ---


class TestCategorias:
    """Verifica que categorias contém SUCESSO e ERRO (Req 5.3)."""

    @pytest.mark.parametrize("cls", [VplPadrao, OrkPadrao, VociPadrao])
    def test_categorias_contem_sucesso(self, cls: type) -> None:
        padrao = cls()
        assert Categoria.SUCESSO in padrao.categorias

    @pytest.mark.parametrize("cls", [VplPadrao, OrkPadrao, VociPadrao])
    def test_categorias_contem_erro(self, cls: type) -> None:
        padrao = cls()
        assert Categoria.ERRO in padrao.categorias

    @pytest.mark.parametrize("cls", [VplPadrao, OrkPadrao, VociPadrao])
    def test_categorias_contem_nao_classificada(self, cls: type) -> None:
        padrao = cls()
        assert Categoria.NAO_CLASSIFICADA in padrao.categorias


# --- Testes de classificação ---


class TestClassificacao:
    """Verifica que classificar sempre retorna NAO_CLASSIFICADA na Fase 1 (Req 5.4, 6.6)."""

    @pytest.mark.parametrize("cls", [VplPadrao, OrkPadrao, VociPadrao])
    def test_classificar_entrada_interpretada_retorna_nao_classificada(
        self, cls: type, entrada_interpretada: EntradaDeLog
    ) -> None:
        padrao = cls()
        resultado = padrao.classificar(entrada_interpretada)
        assert resultado == Categoria.NAO_CLASSIFICADA

    @pytest.mark.parametrize("cls", [VplPadrao, OrkPadrao, VociPadrao])
    def test_classificar_entrada_nao_interpretada_retorna_nao_classificada(
        self, cls: type, entrada_nao_interpretada: EntradaDeLog
    ) -> None:
        padrao = cls()
        resultado = padrao.classificar(entrada_nao_interpretada)
        assert resultado == Categoria.NAO_CLASSIFICADA

    @pytest.mark.parametrize("cls", [VplPadrao, OrkPadrao, VociPadrao])
    def test_classificar_retorna_categoria_valida(
        self, cls: type, entrada_interpretada: EntradaDeLog
    ) -> None:
        padrao = cls()
        resultado = padrao.classificar(entrada_interpretada)
        assert resultado in padrao.categorias
