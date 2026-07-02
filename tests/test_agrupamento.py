"""Testes para a função agrupar_por_aplicacao.

Verifica que a partição por aplicação é correta: cada grupo contém apenas
entradas da aplicação correspondente, a ordem é preservada e a união dos
grupos é igual ao conjunto total de entradas fornecidas (Req 3.3).
"""

from datetime import datetime

from log_analyzer.core.agrupamento import agrupar_por_aplicacao
from log_analyzer.core.modelos import Categoria, EntradaDeLog


def _criar_entrada(
    aplicacao: str, ordem: int, texto: str = "linha"
) -> EntradaDeLog:
    """Helper para criar uma EntradaDeLog simples não interpretada."""
    return EntradaDeLog(
        texto_original=texto,
        aplicacao=aplicacao,
        ordem_de_leitura=ordem,
        interpretada=False,
    )


class TestAgruparPorAplicacao:
    """Testes unitários para agrupar_por_aplicacao."""

    def test_lista_vazia_retorna_dicionario_vazio(self):
        resultado = agrupar_por_aplicacao([])
        assert resultado == {}

    def test_entradas_de_uma_unica_aplicacao(self):
        entradas = [
            _criar_entrada("VPL", 0),
            _criar_entrada("VPL", 1),
            _criar_entrada("VPL", 2),
        ]
        resultado = agrupar_por_aplicacao(entradas)
        assert list(resultado.keys()) == ["VPL"]
        assert resultado["VPL"] == entradas

    def test_entradas_de_multiplas_aplicacoes(self):
        e_vpl = _criar_entrada("VPL", 0, "log vpl")
        e_ork = _criar_entrada("ORK", 1, "log ork")
        e_voci = _criar_entrada("VOCI", 2, "log voci")
        entradas = [e_vpl, e_ork, e_voci]

        resultado = agrupar_por_aplicacao(entradas)

        assert set(resultado.keys()) == {"VPL", "ORK", "VOCI"}
        assert resultado["VPL"] == [e_vpl]
        assert resultado["ORK"] == [e_ork]
        assert resultado["VOCI"] == [e_voci]

    def test_preserva_ordem_dentro_do_grupo(self):
        e1 = _criar_entrada("ORK", 0, "primeiro")
        e2 = _criar_entrada("VPL", 1, "meio")
        e3 = _criar_entrada("ORK", 2, "segundo")
        e4 = _criar_entrada("ORK", 3, "terceiro")

        resultado = agrupar_por_aplicacao([e1, e2, e3, e4])

        assert resultado["ORK"] == [e1, e3, e4]
        assert resultado["VPL"] == [e2]

    def test_uniao_dos_grupos_igual_ao_total(self):
        entradas = [
            _criar_entrada("VPL", 0),
            _criar_entrada("ORK", 1),
            _criar_entrada("VOCI", 2),
            _criar_entrada("VPL", 3),
            _criar_entrada("ORK", 4),
        ]

        resultado = agrupar_por_aplicacao(entradas)

        todas_agrupadas = []
        for grupo in resultado.values():
            todas_agrupadas.extend(grupo)

        assert len(todas_agrupadas) == len(entradas)
        # Cada entrada original aparece exatamente uma vez
        for entrada in entradas:
            assert entrada in todas_agrupadas

    def test_cada_grupo_contem_apenas_entradas_da_aplicacao(self):
        entradas = [
            _criar_entrada("VPL", i) for i in range(3)
        ] + [
            _criar_entrada("ORK", i) for i in range(3, 6)
        ]

        resultado = agrupar_por_aplicacao(entradas)

        for app_id, grupo in resultado.items():
            for entrada in grupo:
                assert entrada.aplicacao == app_id

    def test_funciona_com_entradas_interpretadas(self):
        entrada = EntradaDeLog(
            texto_original="2024-01-01 INFO mensagem",
            aplicacao="VPL",
            ordem_de_leitura=0,
            interpretada=True,
            carimbo_de_tempo=datetime(2024, 1, 1),
            nivel_de_severidade="INFO",
            mensagem="mensagem",
        )

        resultado = agrupar_por_aplicacao([entrada])

        assert resultado == {"VPL": [entrada]}

    def test_funciona_com_entradas_com_categoria(self):
        entrada = EntradaDeLog(
            texto_original="erro no sistema",
            aplicacao="ORK",
            ordem_de_leitura=0,
            interpretada=False,
            categoria=Categoria.ERRO,
        )

        resultado = agrupar_por_aplicacao([entrada])

        assert resultado == {"ORK": [entrada]}
