"""Testes unitários para a hierarquia de exceções do Analisador de Logs."""

import pytest

from log_analyzer.core.excecoes import (
    ErroDeArquivo,
    ErroDeCatalogo,
    ErroDeDecodificacao,
    ErroDeIdentificador,
    ErroDeIntegridadeDaFonte,
    ErroDeRegistro,
    ErroDeSanitizacao,
    ErroDoAnalisador,
    ErroTemporal,
)
from log_analyzer.core import (
    ErroDoAnalisador as ErroDoAnalisadorExported,
    ErroDeArquivo as ErroDeArquivoExported,
    ErroDeIdentificador as ErroDeIdentificadorExported,
    ErroDeRegistro as ErroDeRegistroExported,
)


NOVOS_ERROS = (
    ErroDeDecodificacao,
    ErroTemporal,
    ErroDeCatalogo,
    ErroDeSanitizacao,
    ErroDeIntegridadeDaFonte,
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

    @pytest.mark.parametrize("classe_erro", NOVOS_ERROS)
    def test_novos_erros_herdam_de_erro_do_analisador(self, classe_erro):
        assert issubclass(classe_erro, ErroDoAnalisador)

    def test_captura_generica_com_erro_do_analisador(self):
        """Todas as exceções do analisador podem ser capturadas pela base."""
        for exc_class in (ErroDeRegistro, ErroDeArquivo, ErroDeIdentificador):
            with pytest.raises(ErroDoAnalisador):
                raise exc_class("teste")

    @pytest.mark.parametrize("classe_erro", NOVOS_ERROS)
    def test_captura_generica_dos_novos_erros(self, classe_erro):
        with pytest.raises(ErroDoAnalisador):
            raise classe_erro()


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


class TestErrosComContextoSeguro:
    """Testes dos contratos seguros adicionados na Fase 2."""

    @pytest.mark.parametrize(
        ("classe_erro", "codigo_padrao", "mensagem_segura"),
        (
            (ErroDeDecodificacao, "DECODE_ERROR", "Falha de decodificação da fonte."),
            (ErroTemporal, "TEMPORAL_ERROR", "Falha na resolução temporal da entrada."),
            (ErroDeCatalogo, "CATALOG_ERROR", "Falha no catálogo de regras."),
            (
                ErroDeSanitizacao,
                "SANITIZATION_ERROR",
                "Falha de sanitização; conteúdo suprimido.",
            ),
            (
                ErroDeIntegridadeDaFonte,
                "SOURCE_CHANGED",
                "A integridade da fonte não pôde ser confirmada.",
            ),
        ),
    )
    def test_codigo_e_mensagem_padrao_constante(
        self, classe_erro, codigo_padrao, mensagem_segura
    ):
        erro = classe_erro()

        assert erro.codigo == codigo_padrao
        assert erro.contexto == {"codigo": codigo_padrao}
        assert erro.mensagem == mensagem_segura
        assert str(erro) == mensagem_segura

    @pytest.mark.parametrize("classe_erro", NOVOS_ERROS)
    def test_contexto_contem_somente_codigo_token_e_posicao(self, classe_erro):
        erro = classe_erro(
            codigo="SAFE_FAILURE",
            arquivo_token="<ARQUIVO_7>",
            posicao=42,
        )

        assert erro.codigo == "SAFE_FAILURE"
        assert erro.arquivo_token == "<ARQUIVO_7>"
        assert erro.posicao == 42
        assert erro.contexto == {
            "codigo": "SAFE_FAILURE",
            "arquivo_token": "<ARQUIVO_7>",
            "posicao": 42,
        }

    @pytest.mark.parametrize("classe_erro", NOVOS_ERROS)
    def test_contexto_opcional_nao_cria_chaves_vazias(self, classe_erro):
        erro = classe_erro(codigo="SAFE_FAILURE")

        assert erro.arquivo_token is None
        assert erro.posicao is None
        assert "arquivo_token" not in erro.contexto
        assert "posicao" not in erro.contexto

    @pytest.mark.parametrize("classe_erro", NOVOS_ERROS)
    def test_mensagem_nao_interpola_contexto(self, classe_erro):
        erro_padrao = classe_erro()
        erro_contextualizado = classe_erro(
            codigo="SAFE_FAILURE",
            arquivo_token="<ARQUIVO_9>",
            posicao=999,
        )

        assert str(erro_contextualizado) == str(erro_padrao)
        assert "<ARQUIVO_9>" not in str(erro_contextualizado)
        assert "999" not in str(erro_contextualizado)

    @pytest.mark.parametrize(
        ("argumento", "valor_sensivel"),
        (
            ("caminho", r"C:\dados\fonte.log"),
            ("bytes_brutos", b"segredo-binario"),
            ("identificador", "identificador-bruto-secreto"),
            ("texto_bruto", "conteudo bruto secreto"),
        ),
    )
    def test_campos_brutos_nao_sao_aceitos_nem_ecoados(
        self, argumento, valor_sensivel
    ):
        with pytest.raises(TypeError) as exc_info:
            ErroDeSanitizacao(**{argumento: valor_sensivel})

        assert str(valor_sensivel) not in str(exc_info.value)

    @pytest.mark.parametrize(
        ("argumentos", "valor_sensivel"),
        (
            ({"codigo": r"C:\dados\fonte.log"}, r"C:\dados\fonte.log"),
            ({"arquivo_token": r"C:\dados\fonte.log"}, r"C:\dados\fonte.log"),
            ({"posicao": "conteudo bruto secreto"}, "conteudo bruto secreto"),
        ),
    )
    def test_contexto_invalido_e_rejeitado_sem_eco(self, argumentos, valor_sensivel):
        with pytest.raises(ValueError) as exc_info:
            ErroDeDecodificacao(**argumentos)

        assert valor_sensivel not in str(exc_info.value)

    @pytest.mark.parametrize("posicao", (-1, True, 1.5))
    def test_posicao_deve_ser_inteiro_nao_negativo(self, posicao):
        with pytest.raises(ValueError, match="Posição segura inválida"):
            ErroTemporal(posicao=posicao)


class TestExportacao:
    """Verifica que as exceções legadas continuam exportadas por log_analyzer.core."""

    def test_exporta_erro_do_analisador(self):
        assert ErroDoAnalisadorExported is ErroDoAnalisador

    def test_exporta_erro_de_arquivo(self):
        assert ErroDeArquivoExported is ErroDeArquivo

    def test_exporta_erro_de_identificador(self):
        assert ErroDeIdentificadorExported is ErroDeIdentificador

    def test_exporta_erro_de_registro(self):
        assert ErroDeRegistroExported is ErroDeRegistro
