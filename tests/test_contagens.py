"""Testes para a função calcular_contagens.

Verifica que as contagens por categoria e por aplicação são consistentes com
as entradas fornecidas: cada soma é igual ao total de entradas, e cada contagem
corresponde exatamente ao número real de entradas daquela categoria/aplicação
(Req 9.4, Property 15).
"""

from datetime import datetime

from log_analyzer.core.contagens import calcular_contagens
from log_analyzer.core.modelos import Categoria, EntradaDeLog


def _criar_entrada(
    aplicacao: str,
    ordem: int,
    categoria: Categoria = Categoria.NAO_CLASSIFICADA,
    texto: str = "linha",
) -> EntradaDeLog:
    """Helper para criar uma EntradaDeLog simples não interpretada."""
    return EntradaDeLog(
        texto_original=texto,
        aplicacao=aplicacao,
        ordem_de_leitura=ordem,
        interpretada=False,
        categoria=categoria,
    )


class TestCalcularContagens:
    """Testes unitários para calcular_contagens."""

    def test_lista_vazia_retorna_dicionarios_vazios(self):
        por_categoria, por_aplicacao = calcular_contagens([])
        assert por_categoria == {}
        assert por_aplicacao == {}

    def test_uma_entrada_nao_classificada(self):
        entradas = [_criar_entrada("VPL", 0)]
        por_categoria, por_aplicacao = calcular_contagens(entradas)

        assert por_categoria == {Categoria.NAO_CLASSIFICADA: 1}
        assert por_aplicacao == {"VPL": 1}

    def test_multiplas_categorias(self):
        entradas = [
            _criar_entrada("VPL", 0, Categoria.SUCESSO),
            _criar_entrada("VPL", 1, Categoria.ERRO),
            _criar_entrada("VPL", 2, Categoria.NAO_CLASSIFICADA),
            _criar_entrada("VPL", 3, Categoria.ERRO),
        ]
        por_categoria, por_aplicacao = calcular_contagens(entradas)

        assert por_categoria[Categoria.SUCESSO] == 1
        assert por_categoria[Categoria.ERRO] == 2
        assert por_categoria[Categoria.NAO_CLASSIFICADA] == 1
        assert por_aplicacao == {"VPL": 4}

    def test_multiplas_aplicacoes(self):
        entradas = [
            _criar_entrada("VPL", 0),
            _criar_entrada("ORK", 1),
            _criar_entrada("ORK", 2),
            _criar_entrada("VOCI", 3),
        ]
        por_categoria, por_aplicacao = calcular_contagens(entradas)

        assert por_aplicacao == {"VPL": 1, "ORK": 2, "VOCI": 1}
        assert por_categoria == {Categoria.NAO_CLASSIFICADA: 4}

    def test_soma_por_categoria_igual_total(self):
        entradas = [
            _criar_entrada("VPL", 0, Categoria.SUCESSO),
            _criar_entrada("ORK", 1, Categoria.ERRO),
            _criar_entrada("VOCI", 2, Categoria.NAO_CLASSIFICADA),
            _criar_entrada("VPL", 3, Categoria.ERRO),
            _criar_entrada("ORK", 4, Categoria.SUCESSO),
        ]
        por_categoria, por_aplicacao = calcular_contagens(entradas)

        assert sum(por_categoria.values()) == len(entradas)
        assert sum(por_aplicacao.values()) == len(entradas)

    def test_cada_contagem_corresponde_ao_real(self):
        entradas = [
            _criar_entrada("VPL", 0, Categoria.SUCESSO),
            _criar_entrada("VPL", 1, Categoria.SUCESSO),
            _criar_entrada("ORK", 2, Categoria.ERRO),
            _criar_entrada("VOCI", 3, Categoria.NAO_CLASSIFICADA),
        ]
        por_categoria, por_aplicacao = calcular_contagens(entradas)

        # Contagens por categoria correspondem ao número real
        assert por_categoria[Categoria.SUCESSO] == 2
        assert por_categoria[Categoria.ERRO] == 1
        assert por_categoria[Categoria.NAO_CLASSIFICADA] == 1

        # Contagens por aplicação correspondem ao número real
        assert por_aplicacao["VPL"] == 2
        assert por_aplicacao["ORK"] == 1
        assert por_aplicacao["VOCI"] == 1

    def test_funciona_com_entradas_interpretadas(self):
        entrada = EntradaDeLog(
            texto_original="2024-01-01 INFO mensagem",
            aplicacao="VPL",
            ordem_de_leitura=0,
            interpretada=True,
            carimbo_de_tempo=datetime(2024, 1, 1),
            nivel_de_severidade="INFO",
            mensagem="mensagem",
            categoria=Categoria.SUCESSO,
        )
        por_categoria, por_aplicacao = calcular_contagens([entrada])

        assert por_categoria == {Categoria.SUCESSO: 1}
        assert por_aplicacao == {"VPL": 1}

    def test_aplicacao_unica_com_varias_categorias(self):
        entradas = [
            _criar_entrada("ORK", 0, Categoria.SUCESSO),
            _criar_entrada("ORK", 1, Categoria.ERRO),
            _criar_entrada("ORK", 2, Categoria.SUCESSO),
        ]
        por_categoria, por_aplicacao = calcular_contagens(entradas)

        assert por_aplicacao == {"ORK": 3}
        assert por_categoria == {Categoria.SUCESSO: 2, Categoria.ERRO: 1}
