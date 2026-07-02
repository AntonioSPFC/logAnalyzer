"""Testes unitários para a hierarquia de exceções do Analisador de Logs."""

import pytest

from log_analyzer.core.excecoes import (
    ErroDoAnalisador,
    ErroDeArquivo,
    ErroDeIdentificador,
    ErroDeRegistro,
)
from log_analyzer.core import (
    ErroDoAnalisador as ErroDoAnalisadorExported,
    ErroDeArquivo as ErroDeArquivoExported,
    ErroDeIdentificador as ErroDeIdentificadorExported,
    ErroDeRegistro as ErroDeRegistroExported,
)


class TestHierarquiaDeHeranca:
    """Verifica que a hierarquia de herança está correta."""

    def test_erro_do_analisador_herda_de_exception(self):
        assert issubclass(ErroDoAnalisador, Exception)

    def test_erro_de_registro_herda_de_erro_do_analisador(self):
        assert issubclass(ErroDeRegistro, ErroDoAnalisador)

    def test_erro_de_arquivo_herda_de_erro_do_analisador(self):
        assert issubclass(ErroDeArquivo, ErroDoAnalisador)

    def test_erro_de_identificador_herda_de_erro_do_analisador(self):
        assert issubclass(ErroDeIdentificador, ErroDoAnalisador)

    def test_captura_generica_com_erro_do_analisador(self):
        """Todas as exceções do analisador podem ser capturadas pela base."""
        for exc_class in (ErroDeRegistro, ErroDeArquivo, ErroDeIdentificador):
            with pytest.raises(ErroDoAnalisador):
                raise exc_class("teste")


class TestErroDoAnalisador:
    """Testes para a exceção base."""

    def test_mensagem_descritiva(self):
        erro = ErroDoAnalisador("algo deu errado")
        assert erro.mensagem == "algo deu errado"
        assert str(erro) == "algo deu errado"

    def test_contexto_padrao_vazio(self):
        erro = ErroDoAnalisador("erro")
        assert erro.contexto == {}

    def test_contexto_opcional(self):
        ctx = {"chave": "valor"}
        erro = ErroDoAnalisador("erro", contexto=ctx)
        assert erro.contexto == {"chave": "valor"}


class TestErroDeRegistro:
    """Testes para ErroDeRegistro — interface não implementada, id duplicado, app não suportada."""

    def test_mensagem_e_app_id(self):
        erro = ErroDeRegistro("Aplicação não suportada", app_id="XYZ")
        assert erro.mensagem == "Aplicação não suportada"
        assert erro.app_id == "XYZ"
        assert erro.contexto["app_id"] == "XYZ"

    def test_sem_app_id(self):
        erro = ErroDeRegistro("Interface não implementada")
        assert erro.app_id is None
        assert "app_id" not in erro.contexto

    def test_contexto_extra(self):
        erro = ErroDeRegistro("Duplicado", app_id="VPL", interface="Parser_de_Aplicacao")
        assert erro.contexto["app_id"] == "VPL"
        assert erro.contexto["interface"] == "Parser_de_Aplicacao"


class TestErroDeArquivo:
    """Testes para ErroDeArquivo — ilegível, vazio, grande demais, formato inválido."""

    def test_mensagem_e_caminho(self):
        erro = ErroDeArquivo("Arquivo ilegível", caminho="/var/log/app.log")
        assert erro.mensagem == "Arquivo ilegível"
        assert erro.caminho == "/var/log/app.log"
        assert erro.contexto["caminho"] == "/var/log/app.log"

    def test_sem_caminho(self):
        erro = ErroDeArquivo("Arquivo vazio")
        assert erro.caminho is None
        assert "caminho" not in erro.contexto

    def test_contexto_extra(self):
        erro = ErroDeArquivo("Arquivo excede limite", caminho="big.log", tamanho_mb=600)
        assert erro.contexto["caminho"] == "big.log"
        assert erro.contexto["tamanho_mb"] == 600


class TestErroDeIdentificador:
    """Testes para ErroDeIdentificador — identificador inválido."""

    def test_mensagem_e_identificador(self):
        erro = ErroDeIdentificador("Identificador vazio", identificador="")
        assert erro.mensagem == "Identificador vazio"
        assert erro.identificador == ""
        assert erro.contexto["identificador"] == ""

    def test_sem_identificador(self):
        erro = ErroDeIdentificador("Identificador inválido")
        assert erro.identificador is None
        assert "identificador" not in erro.contexto

    def test_contexto_extra(self):
        erro = ErroDeIdentificador(
            "Identificador muito longo", identificador="x" * 300, comprimento=300
        )
        assert erro.contexto["identificador"] == "x" * 300
        assert erro.contexto["comprimento"] == 300


class TestExportacao:
    """Verifica que as exceções são corretamente exportadas de log_analyzer.core."""

    def test_exporta_erro_do_analisador(self):
        assert ErroDoAnalisadorExported is ErroDoAnalisador

    def test_exporta_erro_de_arquivo(self):
        assert ErroDeArquivoExported is ErroDeArquivo

    def test_exporta_erro_de_identificador(self):
        assert ErroDeIdentificadorExported is ErroDeIdentificador

    def test_exporta_erro_de_registro(self):
        assert ErroDeRegistroExported is ErroDeRegistro
