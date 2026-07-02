"""Testes unitários para a interface abstrata Padrao_de_Analise."""

import pytest

from log_analyzer.core import Categoria, EntradaDeLog, Padrao_de_Analise


class TestPadraoDeAnaliseInterface:
    """Testa a interface abstrata e a validação de subclasses."""

    def test_cannot_instantiate_abstract(self):
        """Não é possível instanciar a classe abstrata diretamente."""
        with pytest.raises(TypeError):
            Padrao_de_Analise()  # type: ignore[abstract]

    def test_valid_subclass_instantiation(self):
        """Subclasse concreta com SUCESSO e ERRO é aceita."""

        class PadraoValido(Padrao_de_Analise):
            @property
            def categorias(self) -> tuple[Categoria, ...]:
                return (Categoria.SUCESSO, Categoria.ERRO, Categoria.NAO_CLASSIFICADA)

            def classificar(self, entrada: EntradaDeLog) -> Categoria:
                return Categoria.NAO_CLASSIFICADA

        p = PadraoValido()
        assert Categoria.SUCESSO in p.categorias
        assert Categoria.ERRO in p.categorias

    def test_classificar_returns_categoria(self):
        """O método classificar retorna uma Categoria válida."""

        class PadraoValido(Padrao_de_Analise):
            @property
            def categorias(self) -> tuple[Categoria, ...]:
                return (Categoria.SUCESSO, Categoria.ERRO, Categoria.NAO_CLASSIFICADA)

            def classificar(self, entrada: EntradaDeLog) -> Categoria:
                return Categoria.NAO_CLASSIFICADA

        p = PadraoValido()
        entrada = EntradaDeLog(
            texto_original="test line",
            aplicacao="VPL",
            ordem_de_leitura=0,
            interpretada=False,
        )
        result = p.classificar(entrada)
        assert result == Categoria.NAO_CLASSIFICADA
        assert result in p.categorias

    def test_subclass_missing_sucesso_raises(self):
        """Subclasse sem SUCESSO nas categorias é rejeitada ao instanciar."""

        class PadraoSemSucesso(Padrao_de_Analise):
            @property
            def categorias(self) -> tuple[Categoria, ...]:
                return (Categoria.ERRO, Categoria.NAO_CLASSIFICADA)

            def classificar(self, entrada: EntradaDeLog) -> Categoria:
                return Categoria.NAO_CLASSIFICADA

        with pytest.raises(TypeError, match="SUCESSO"):
            PadraoSemSucesso()

    def test_subclass_missing_erro_raises(self):
        """Subclasse sem ERRO nas categorias é rejeitada ao instanciar."""

        class PadraoSemErro(Padrao_de_Analise):
            @property
            def categorias(self) -> tuple[Categoria, ...]:
                return (Categoria.SUCESSO, Categoria.NAO_CLASSIFICADA)

            def classificar(self, entrada: EntradaDeLog) -> Categoria:
                return Categoria.NAO_CLASSIFICADA

        with pytest.raises(TypeError, match="ERRO"):
            PadraoSemErro()

    def test_abstract_methods_required(self):
        """Subclasse sem implementar os métodos abstratos não pode ser instanciada."""

        class PadraoIncompleto(Padrao_de_Analise):
            pass

        with pytest.raises(TypeError):
            PadraoIncompleto()  # type: ignore[abstract]

    def test_abstract_methods_set(self):
        """A interface declara exatamente 'categorias' e 'classificar' como abstratos."""
        assert "categorias" in Padrao_de_Analise.__abstractmethods__
        assert "classificar" in Padrao_de_Analise.__abstractmethods__
