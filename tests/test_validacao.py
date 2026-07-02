"""Testes para log_analyzer.core.validacao — validação do Identificador."""

import pytest

from log_analyzer.core.excecoes import ErroDeIdentificador
from log_analyzer.core.validacao import validar_identificador


# ─── Testes unitários ────────────────────────────────────────────────────────


class TestValidarIdentificadorValido:
    """Testes para identificadores válidos — validar_identificador retorna None."""

    def test_identificador_simples(self) -> None:
        assert validar_identificador("abc123") is None

    def test_identificador_com_espacos_internos(self) -> None:
        assert validar_identificador("call id 42") is None

    def test_identificador_com_um_caractere(self) -> None:
        assert validar_identificador("x") is None

    def test_identificador_com_256_caracteres(self) -> None:
        assert validar_identificador("a" * 256) is None

    def test_identificador_com_espacos_nas_bordas(self) -> None:
        # Tem espaços nas bordas, mas não é SOMENTE espaços
        assert validar_identificador("  abc  ") is None

    def test_identificador_unicode(self) -> None:
        assert validar_identificador("sessão-12345") is None


class TestValidarIdentificadorInvalido:
    """Testes para identificadores inválidos — levanta ErroDeIdentificador."""

    def test_identificador_vazio(self) -> None:
        with pytest.raises(ErroDeIdentificador) as exc_info:
            validar_identificador("")
        assert "vazio" in exc_info.value.mensagem.lower()
        assert exc_info.value.identificador == ""

    def test_identificador_somente_espacos(self) -> None:
        with pytest.raises(ErroDeIdentificador) as exc_info:
            validar_identificador("   ")
        assert "espaços" in exc_info.value.mensagem.lower()
        assert exc_info.value.identificador == "   "

    def test_identificador_somente_tabs(self) -> None:
        with pytest.raises(ErroDeIdentificador) as exc_info:
            validar_identificador("\t\t")
        assert exc_info.value.identificador == "\t\t"

    def test_identificador_somente_newlines(self) -> None:
        with pytest.raises(ErroDeIdentificador) as exc_info:
            validar_identificador("\n\n")
        assert exc_info.value.identificador == "\n\n"

    def test_identificador_com_257_caracteres(self) -> None:
        longo = "x" * 257
        with pytest.raises(ErroDeIdentificador) as exc_info:
            validar_identificador(longo)
        assert "256" in exc_info.value.mensagem
        assert exc_info.value.identificador == longo

    def test_identificador_muito_longo(self) -> None:
        longo = "a" * 1000
        with pytest.raises(ErroDeIdentificador) as exc_info:
            validar_identificador(longo)
        assert exc_info.value.identificador == longo
