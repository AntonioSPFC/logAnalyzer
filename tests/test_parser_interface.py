"""Testes unitários para a interface abstrata Parser_de_Aplicacao."""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from log_analyzer.core import EntradaDeLog, Parser_de_Aplicacao


class TestParserDeAplicacaoInterface:
    """Testa a interface abstrata e comportamentos esperados."""

    def test_cannot_instantiate_abstract(self):
        """Não é possível instanciar a classe abstrata diretamente."""
        with pytest.raises(TypeError):
            Parser_de_Aplicacao()  # type: ignore[abstract]

    def test_valid_subclass_must_implement_all_abstract_methods(self):
        """Subclasse que implementa todos os métodos abstratos pode ser instanciada."""

        class ParserValido(Parser_de_Aplicacao):
            @property
            def niveis_de_severidade(self) -> frozenset[str]:
                return frozenset({"INFO", "WARN", "ERROR"})

            def interpretar_entrada(self, texto: str) -> EntradaDeLog:
                return EntradaDeLog(
                    texto_original=texto,
                    aplicacao="TEST",
                    ordem_de_leitura=0,
                    interpretada=False,
                )

            def imprimir_entrada(self, entrada: EntradaDeLog) -> str:
                return entrada.texto_original

        parser = ParserValido()
        assert isinstance(parser, Parser_de_Aplicacao)
        assert "INFO" in parser.niveis_de_severidade

    def test_subclass_missing_niveis_de_severidade_raises(self):
        """Subclasse sem implementar niveis_de_severidade não pode ser instanciada."""

        class ParserSemNiveis(Parser_de_Aplicacao):
            def interpretar_entrada(self, texto: str) -> EntradaDeLog:
                return EntradaDeLog(
                    texto_original=texto,
                    aplicacao="TEST",
                    ordem_de_leitura=0,
                    interpretada=False,
                )

            def imprimir_entrada(self, entrada: EntradaDeLog) -> str:
                return texto

        with pytest.raises(TypeError):
            ParserSemNiveis()  # type: ignore[abstract]

    def test_subclass_missing_interpretar_entrada_raises(self):
        """Subclasse sem implementar interpretar_entrada não pode ser instanciada."""

        class ParserSemInterpretar(Parser_de_Aplicacao):
            @property
            def niveis_de_severidade(self) -> frozenset[str]:
                return frozenset({"INFO"})

            def imprimir_entrada(self, entrada: EntradaDeLog) -> str:
                return ""

        with pytest.raises(TypeError):
            ParserSemInterpretar()  # type: ignore[abstract]

    def test_subclass_missing_imprimir_entrada_raises(self):
        """Subclasse sem implementar imprimir_entrada não pode ser instanciada."""

        class ParserSemImprimir(Parser_de_Aplicacao):
            @property
            def niveis_de_severidade(self) -> frozenset[str]:
                return frozenset({"INFO"})

            def interpretar_entrada(self, texto: str) -> EntradaDeLog:
                return EntradaDeLog(
                    texto_original=texto,
                    aplicacao="TEST",
                    ordem_de_leitura=0,
                    interpretada=False,
                )

        with pytest.raises(TypeError):
            ParserSemImprimir()  # type: ignore[abstract]

    def test_interpretar_arquivo_default_implementation(self):
        """O método interpretar_arquivo (default) itera e chama interpretar_entrada."""

        class ParserComDefault(Parser_de_Aplicacao):
            @property
            def niveis_de_severidade(self) -> frozenset[str]:
                return frozenset({"INFO", "ERROR"})

            def interpretar_entrada(self, texto: str) -> EntradaDeLog:
                return EntradaDeLog(
                    texto_original=texto,
                    aplicacao="TEST",
                    ordem_de_leitura=0,
                    interpretada=False,
                )

            def imprimir_entrada(self, entrada: EntradaDeLog) -> str:
                return entrada.texto_original

        parser = ParserComDefault()
        linhas = ["linha 1", "linha 2", "linha 3"]
        resultado = parser.interpretar_arquivo(linhas)

        assert len(resultado) == 3
        assert all(isinstance(e, EntradaDeLog) for e in resultado)
        assert resultado[0].texto_original == "linha 1"
        assert resultado[1].texto_original == "linha 2"
        assert resultado[2].texto_original == "linha 3"

    def test_interpretar_arquivo_calls_interpretar_entrada_for_each_line(self):
        """interpretar_arquivo chama interpretar_entrada uma vez por linha."""

        class ParserContador(Parser_de_Aplicacao):
            def __init__(self):
                self.chamadas: list[str] = []

            @property
            def niveis_de_severidade(self) -> frozenset[str]:
                return frozenset({"INFO"})

            def interpretar_entrada(self, texto: str) -> EntradaDeLog:
                self.chamadas.append(texto)
                return EntradaDeLog(
                    texto_original=texto,
                    aplicacao="TEST",
                    ordem_de_leitura=len(self.chamadas) - 1,
                    interpretada=False,
                )

            def imprimir_entrada(self, entrada: EntradaDeLog) -> str:
                return entrada.texto_original

        parser = ParserContador()
        linhas = ["a", "b", "c", "d"]
        parser.interpretar_arquivo(linhas)

        assert parser.chamadas == ["a", "b", "c", "d"]

    def test_interpretar_arquivo_with_empty_iterable(self):
        """interpretar_arquivo com iterável vazio retorna lista vazia."""

        class ParserSimples(Parser_de_Aplicacao):
            @property
            def niveis_de_severidade(self) -> frozenset[str]:
                return frozenset({"INFO"})

            def interpretar_entrada(self, texto: str) -> EntradaDeLog:
                return EntradaDeLog(
                    texto_original=texto,
                    aplicacao="TEST",
                    ordem_de_leitura=0,
                    interpretada=False,
                )

            def imprimir_entrada(self, entrada: EntradaDeLog) -> str:
                return entrada.texto_original

        parser = ParserSimples()
        resultado = parser.interpretar_arquivo([])
        assert resultado == []

    def test_interpretar_arquivo_works_with_generator(self):
        """interpretar_arquivo funciona com um generator (streaming)."""

        class ParserStreaming(Parser_de_Aplicacao):
            @property
            def niveis_de_severidade(self) -> frozenset[str]:
                return frozenset({"DEBUG", "INFO"})

            def interpretar_entrada(self, texto: str) -> EntradaDeLog:
                return EntradaDeLog(
                    texto_original=texto,
                    aplicacao="TEST",
                    ordem_de_leitura=0,
                    interpretada=False,
                )

            def imprimir_entrada(self, entrada: EntradaDeLog) -> str:
                return entrada.texto_original

        parser = ParserStreaming()

        def gerador():
            yield "linha gen 1"
            yield "linha gen 2"

        resultado = parser.interpretar_arquivo(gerador())
        assert len(resultado) == 2
        assert resultado[0].texto_original == "linha gen 1"
        assert resultado[1].texto_original == "linha gen 2"

    def test_tipo_inicio_declara_exatamente_os_tres_estados(self):
        """A detecção por bloco usa somente os três estados especificados."""
        from log_analyzer.core.interfaces import TipoInicio

        assert tuple((estado.name, estado.value) for estado in TipoInicio) == (
            ("CABECALHO_VALIDO", "cabecalho_valido"),
            ("CABECALHO_APARENTE_INVALIDO", "cabecalho_aparente_invalido"),
            ("CONTINUACAO", "continuacao"),
        )

    def test_parser_de_bloco_e_runtime_checkable_e_opcional(self):
        """Só objetos com a capacidade adicional satisfazem o protocolo estrutural."""
        from log_analyzer.core.interfaces import Parser_de_Bloco, TipoInicio

        class ParserSomenteLinha(Parser_de_Aplicacao):
            @property
            def niveis_de_severidade(self) -> frozenset[str]:
                return frozenset({"INFO"})

            def interpretar_entrada(self, texto: str) -> EntradaDeLog:
                return EntradaDeLog(
                    texto_original=texto,
                    aplicacao="TEST",
                    ordem_de_leitura=0,
                    interpretada=False,
                )

            def imprimir_entrada(self, entrada: EntradaDeLog) -> str:
                return entrada.texto_original

        class ParserEstruturalDeBloco:
            def detectar_inicio(self, linha: object) -> TipoInicio:
                return TipoInicio.CABECALHO_VALIDO

            def interpretar_bloco(self, bloco: object) -> object:
                return bloco

        parser_line_based = ParserSomenteLinha()

        assert not isinstance(parser_line_based, Parser_de_Bloco)
        assert isinstance(ParserEstruturalDeBloco(), Parser_de_Bloco)
        assert [
            entrada.texto_original
            for entrada in parser_line_based.interpretar_arquivo(iter(("a", "b")))
        ] == ["a", "b"]

    def test_abstract_methods_set(self):
        """A interface declara exatamente os métodos abstratos esperados."""
        esperados = {"niveis_de_severidade", "interpretar_entrada", "imprimir_entrada"}
        assert esperados == Parser_de_Aplicacao.__abstractmethods__
