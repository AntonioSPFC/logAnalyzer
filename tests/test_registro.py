"""Testes unitários para o Registro_de_Aplicacoes.

Verifica:
- Registro bem-sucedido de aplicações válidas
- Rejeição de app_id duplicado preservando o existente
- Rejeição de parser que não implementa Parser_de_Aplicacao
- Rejeição de padrão que não implementa Padrao_de_Analise
- obter levanta ErroDeRegistro para app_id ausente
- aplicacoes_suportadas retorna a lista correta
- esta_registrada retorna True/False corretamente
- Em qualquer falha, o catálogo não é alterado
"""

import pytest

from log_analyzer.core.excecoes import ErroDeRegistro
from log_analyzer.core.interfaces import Padrao_de_Analise, Parser_de_Aplicacao
from log_analyzer.core.modelos import Categoria, EntradaDeLog
from log_analyzer.core.registro import Registro_de_Aplicacoes


# -- Fixtures: implementações concretas válidas para os testes --


class ParserFake(Parser_de_Aplicacao):
    """Parser concreto mínimo para testes."""

    @property
    def niveis_de_severidade(self) -> frozenset[str]:
        return frozenset({"INFO", "ERROR"})

    def interpretar_entrada(self, texto: str) -> EntradaDeLog:
        return EntradaDeLog(
            texto_original=texto,
            aplicacao="fake",
            ordem_de_leitura=0,
            interpretada=False,
        )

    def imprimir_entrada(self, entrada: EntradaDeLog) -> str:
        return entrada.texto_original


class PadraoFake(Padrao_de_Analise):
    """Padrão concreto mínimo para testes."""

    @property
    def categorias(self) -> tuple[Categoria, ...]:
        return (Categoria.SUCESSO, Categoria.ERRO, Categoria.NAO_CLASSIFICADA)

    def classificar(self, entrada: EntradaDeLog) -> Categoria:
        return Categoria.NAO_CLASSIFICADA


class ParserFake2(Parser_de_Aplicacao):
    """Segundo parser concreto para diferenciar instâncias."""

    @property
    def niveis_de_severidade(self) -> frozenset[str]:
        return frozenset({"DEBUG", "WARN"})

    def interpretar_entrada(self, texto: str) -> EntradaDeLog:
        return EntradaDeLog(
            texto_original=texto,
            aplicacao="fake2",
            ordem_de_leitura=0,
            interpretada=False,
        )

    def imprimir_entrada(self, entrada: EntradaDeLog) -> str:
        return entrada.texto_original


class PadraoFake2(Padrao_de_Analise):
    """Segundo padrão concreto para diferenciar instâncias."""

    @property
    def categorias(self) -> tuple[Categoria, ...]:
        return (Categoria.SUCESSO, Categoria.ERRO, Categoria.NAO_CLASSIFICADA)

    def classificar(self, entrada: EntradaDeLog) -> Categoria:
        return Categoria.NAO_CLASSIFICADA


@pytest.fixture
def registro() -> Registro_de_Aplicacoes:
    """Registro vazio."""
    return Registro_de_Aplicacoes()


@pytest.fixture
def parser() -> ParserFake:
    return ParserFake()


@pytest.fixture
def padrao() -> PadraoFake:
    return PadraoFake()


# -- Testes de registro bem-sucedido --


class TestRegistrarSucesso:
    """Testes de registro bem-sucedido."""

    def test_registrar_aplicacao_valida(
        self,
        registro: Registro_de_Aplicacoes,
        parser: ParserFake,
        padrao: PadraoFake,
    ) -> None:
        """Registro de uma aplicação válida não levanta exceção."""
        registro.registrar("APP1", parser, padrao)
        assert registro.esta_registrada("APP1")

    def test_registrar_multiplas_aplicacoes(
        self, registro: Registro_de_Aplicacoes
    ) -> None:
        """Múltiplas aplicações com app_ids distintos são registradas."""
        registro.registrar("APP1", ParserFake(), PadraoFake())
        registro.registrar("APP2", ParserFake2(), PadraoFake2())
        assert registro.aplicacoes_suportadas() == ("APP1", "APP2")


# -- Testes de rejeição: app_id duplicado (Req 7.6) --


class TestRejeicaoDuplicado:
    """app_id duplicado é rejeitado; o existente é preservado."""

    def test_duplicado_levanta_erro(
        self,
        registro: Registro_de_Aplicacoes,
        parser: ParserFake,
        padrao: PadraoFake,
    ) -> None:
        registro.registrar("VPL", parser, padrao)
        with pytest.raises(ErroDeRegistro) as exc_info:
            registro.registrar("VPL", ParserFake2(), PadraoFake2())
        assert "duplicado" in exc_info.value.mensagem.lower() or "duplicado" in str(
            exc_info.value.contexto.get("causa", "")
        )

    def test_duplicado_preserva_existente(
        self,
        registro: Registro_de_Aplicacoes,
        parser: ParserFake,
        padrao: PadraoFake,
    ) -> None:
        registro.registrar("VPL", parser, padrao)
        with pytest.raises(ErroDeRegistro):
            registro.registrar("VPL", ParserFake2(), PadraoFake2())
        # O existente permanece inalterado
        obtido_parser, obtido_padrao = registro.obter("VPL")
        assert obtido_parser is parser
        assert obtido_padrao is padrao


# -- Testes de rejeição: interface não implementada (Req 7.5) --


class TestRejeicaoInterface:
    """Parser ou padrão que não implementa a interface é rejeitado."""

    def test_parser_invalido_levanta_erro(
        self,
        registro: Registro_de_Aplicacoes,
        padrao: PadraoFake,
    ) -> None:
        with pytest.raises(ErroDeRegistro) as exc_info:
            registro.registrar("APP1", "nao_sou_parser", padrao)  # type: ignore[arg-type]
        assert "Parser_de_Aplicacao" in exc_info.value.mensagem

    def test_padrao_invalido_levanta_erro(
        self,
        registro: Registro_de_Aplicacoes,
        parser: ParserFake,
    ) -> None:
        with pytest.raises(ErroDeRegistro) as exc_info:
            registro.registrar("APP1", parser, 42)  # type: ignore[arg-type]
        assert "Padrao_de_Analise" in exc_info.value.mensagem

    def test_ambos_invalidos_reporta_parser_primeiro(
        self,
        registro: Registro_de_Aplicacoes,
    ) -> None:
        """Quando ambos são inválidos, o parser é validado primeiro."""
        with pytest.raises(ErroDeRegistro) as exc_info:
            registro.registrar("APP1", None, None)  # type: ignore[arg-type]
        assert "Parser_de_Aplicacao" in exc_info.value.mensagem

    def test_falha_nao_altera_catalogo(
        self,
        registro: Registro_de_Aplicacoes,
        parser: ParserFake,
        padrao: PadraoFake,
    ) -> None:
        """Após falha de registro, o catálogo permanece inalterado."""
        registro.registrar("EXISTENTE", parser, padrao)
        with pytest.raises(ErroDeRegistro):
            registro.registrar("NOVA", "invalido", padrao)  # type: ignore[arg-type]
        assert not registro.esta_registrada("NOVA")
        assert registro.aplicacoes_suportadas() == ("EXISTENTE",)


# -- Testes de obter (Req 1.5, 2.2, 6.8) --


class TestObter:
    """obter resolve ou levanta ErroDeRegistro."""

    def test_obter_existente(
        self,
        registro: Registro_de_Aplicacoes,
        parser: ParserFake,
        padrao: PadraoFake,
    ) -> None:
        registro.registrar("ORK", parser, padrao)
        resultado = registro.obter("ORK")
        assert resultado == (parser, padrao)

    def test_obter_ausente_levanta_erro(
        self, registro: Registro_de_Aplicacoes
    ) -> None:
        with pytest.raises(ErroDeRegistro) as exc_info:
            registro.obter("INEXISTENTE")
        assert exc_info.value.app_id == "INEXISTENTE"
        assert "não suportada" in exc_info.value.mensagem.lower() or "nao_suportada" in str(
            exc_info.value.contexto.get("causa", "")
        )


# -- Testes de aplicacoes_suportadas --


class TestAplicacoesSuportadas:
    """aplicacoes_suportadas retorna tupla dos app_ids."""

    def test_vazio(self, registro: Registro_de_Aplicacoes) -> None:
        assert registro.aplicacoes_suportadas() == ()

    def test_com_aplicacoes(
        self,
        registro: Registro_de_Aplicacoes,
    ) -> None:
        registro.registrar("VPL", ParserFake(), PadraoFake())
        registro.registrar("ORK", ParserFake2(), PadraoFake2())
        apps = registro.aplicacoes_suportadas()
        assert "VPL" in apps
        assert "ORK" in apps
        assert len(apps) == 2


# -- Testes de esta_registrada --


class TestEstaRegistrada:
    """esta_registrada retorna bool correto."""

    def test_registrada(
        self,
        registro: Registro_de_Aplicacoes,
        parser: ParserFake,
        padrao: PadraoFake,
    ) -> None:
        registro.registrar("VOCI", parser, padrao)
        assert registro.esta_registrada("VOCI") is True

    def test_nao_registrada(self, registro: Registro_de_Aplicacoes) -> None:
        assert registro.esta_registrada("XPTO") is False


# -- Teste de atomicidade: falha não altera catálogo --


class TestAtomicidade:
    """Qualquer falha de registro não altera o catálogo."""

    def test_duplicado_nao_altera(
        self,
        registro: Registro_de_Aplicacoes,
        parser: ParserFake,
        padrao: PadraoFake,
    ) -> None:
        registro.registrar("APP1", parser, padrao)
        snapshot = registro.aplicacoes_suportadas()
        with pytest.raises(ErroDeRegistro):
            registro.registrar("APP1", ParserFake2(), PadraoFake2())
        assert registro.aplicacoes_suportadas() == snapshot

    def test_interface_invalida_nao_altera(
        self,
        registro: Registro_de_Aplicacoes,
        parser: ParserFake,
        padrao: PadraoFake,
    ) -> None:
        registro.registrar("APP1", parser, padrao)
        snapshot = registro.aplicacoes_suportadas()
        with pytest.raises(ErroDeRegistro):
            registro.registrar("APP2", "nao_parser", padrao)  # type: ignore[arg-type]
        assert registro.aplicacoes_suportadas() == snapshot
