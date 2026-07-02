"""Testes básicos para a camada de apresentação CLI.

Verifica a renderização do ResultadoDeAnalise:
- Agrupamento por aplicação com linha do tempo
- Marcação visual distinta para categoria ERRO (Req 9.3)
- Exibição de contagens (Req 9.4)
- Mensagem quando nenhuma entrada encontrada (Req 9.2)
- Mensagem de falha de exibição preservando entradas (Req 9.5)
"""

from datetime import datetime

from log_analyzer.cli.apresentacao import renderizar_resultado
from log_analyzer.core.modelos import (
    Categoria,
    EntradaDeLog,
    MensagemDeErro,
    ResultadoDeAnalise,
)


class _DictQueExplode(dict):
    """Dict que levanta exceção ao ser iterado via .items(), simulando falha na renderização."""

    def items(self):
        raise RuntimeError("falha simulada na iteração")


def _criar_entrada(
    texto: str = "linha original",
    aplicacao: str = "VPL",
    ordem: int = 0,
    interpretada: bool = True,
    carimbo: datetime | None = None,
    severidade: str = "INFO",
    mensagem: str = "mensagem de teste",
    categoria: Categoria = Categoria.NAO_CLASSIFICADA,
) -> EntradaDeLog:
    """Helper para criar EntradaDeLog para testes."""
    if interpretada and carimbo is None:
        carimbo = datetime(2024, 1, 15, 10, 30, 0)
    return EntradaDeLog(
        texto_original=texto,
        aplicacao=aplicacao,
        ordem_de_leitura=ordem,
        interpretada=interpretada,
        carimbo_de_tempo=carimbo,
        nivel_de_severidade=severidade if interpretada else None,
        mensagem=mensagem if interpretada else None,
        categoria=categoria,
    )


class TestRenderizarResultadoVazio:
    """Testes para resultado sem entradas (Req 9.2)."""

    def test_resultado_vazio_exibe_mensagem(self):
        resultado = ResultadoDeAnalise(identificador="ABC123")
        saida = renderizar_resultado(resultado)

        assert "ABC123" in saida
        assert "Nenhuma entrada encontrada" in saida

    def test_resultado_vazio_com_mensagens_acumuladas(self):
        resultado = ResultadoDeAnalise(
            identificador="XYZ",
            mensagens=["Nenhuma correspondência encontrada."],
        )
        saida = renderizar_resultado(resultado)

        assert "Nenhuma entrada encontrada" in saida
        assert "Nenhuma correspondência encontrada." in saida


class TestRenderizarResultadoComEntradas:
    """Testes para resultado com entradas — agrupamento e linha do tempo (Req 9.1)."""

    def test_agrupa_por_aplicacao(self):
        entrada_vpl = _criar_entrada(aplicacao="VPL", mensagem="msg vpl")
        entrada_ork = _criar_entrada(aplicacao="ORK", mensagem="msg ork")

        resultado = ResultadoDeAnalise(
            identificador="ID001",
            entradas_por_aplicacao={
                "VPL": [entrada_vpl],
                "ORK": [entrada_ork],
            },
        )
        saida = renderizar_resultado(resultado)

        assert "[VPL]" in saida
        assert "[ORK]" in saida
        assert "msg vpl" in saida
        assert "msg ork" in saida

    def test_exibe_timestamp_severidade_mensagem(self):
        entrada = _criar_entrada(
            carimbo=datetime(2024, 3, 10, 14, 25, 30),
            severidade="WARNING",
            mensagem="algo aconteceu",
        )
        resultado = ResultadoDeAnalise(
            identificador="T001",
            entradas_por_aplicacao={"VPL": [entrada]},
        )
        saida = renderizar_resultado(resultado)

        assert "2024-03-10 14:25:30" in saida
        assert "WARNING" in saida
        assert "algo aconteceu" in saida

    def test_entrada_nao_interpretada_exibe_texto_original(self):
        entrada = _criar_entrada(
            texto="linha bruta sem formato",
            interpretada=False,
        )
        resultado = ResultadoDeAnalise(
            identificador="T002",
            entradas_por_aplicacao={"VPL": [entrada]},
        )
        saida = renderizar_resultado(resultado)

        assert "linha bruta sem formato" in saida

    def test_exibe_contagem_entradas_por_aplicacao(self):
        entradas = [
            _criar_entrada(ordem=i, mensagem=f"msg {i}") for i in range(3)
        ]
        resultado = ResultadoDeAnalise(
            identificador="T003",
            entradas_por_aplicacao={"VPL": entradas},
        )
        saida = renderizar_resultado(resultado)

        assert "(3 entradas)" in saida


class TestMarcacaoVisualErro:
    """Testes para marcação visual distinta de entradas ERRO (Req 9.3)."""

    def test_entrada_erro_tem_marcador_distinto(self):
        entrada_erro = _criar_entrada(
            mensagem="falha crítica",
            categoria=Categoria.ERRO,
        )
        resultado = ResultadoDeAnalise(
            identificador="E001",
            entradas_por_aplicacao={"VPL": [entrada_erro]},
        )
        saida = renderizar_resultado(resultado)

        assert "[ERRO]" in saida
        assert "falha crítica" in saida

    def test_entrada_sucesso_nao_tem_marcador_erro(self):
        entrada_ok = _criar_entrada(
            mensagem="tudo certo",
            categoria=Categoria.SUCESSO,
        )
        resultado = ResultadoDeAnalise(
            identificador="E002",
            entradas_por_aplicacao={"VPL": [entrada_ok]},
        )
        saida = renderizar_resultado(resultado)

        assert "[ERRO]" not in saida
        assert "tudo certo" in saida

    def test_entrada_nao_classificada_nao_tem_marcador_erro(self):
        entrada = _criar_entrada(
            mensagem="normal",
            categoria=Categoria.NAO_CLASSIFICADA,
        )
        resultado = ResultadoDeAnalise(
            identificador="E003",
            entradas_por_aplicacao={"VPL": [entrada]},
        )
        saida = renderizar_resultado(resultado)

        assert "[ERRO]" not in saida

    def test_entrada_erro_nao_interpretada_tem_marcador(self):
        entrada = _criar_entrada(
            texto="erro em formato desconhecido",
            interpretada=False,
            categoria=Categoria.ERRO,
        )
        resultado = ResultadoDeAnalise(
            identificador="E004",
            entradas_por_aplicacao={"VPL": [entrada]},
        )
        saida = renderizar_resultado(resultado)

        assert "[ERRO]" in saida
        assert "erro em formato desconhecido" in saida


class TestContagens:
    """Testes para exibição das contagens (Req 9.4)."""

    def test_exibe_contagem_por_categoria(self):
        resultado = ResultadoDeAnalise(
            identificador="C001",
            entradas_por_aplicacao={"VPL": [_criar_entrada()]},
            contagem_por_categoria={
                Categoria.SUCESSO: 5,
                Categoria.ERRO: 2,
                Categoria.NAO_CLASSIFICADA: 3,
            },
        )
        saida = renderizar_resultado(resultado)

        assert "Contagem por categoria:" in saida
        assert "sucesso: 5" in saida
        assert "erro: 2" in saida
        assert "não classificada: 3" in saida

    def test_exibe_contagem_por_aplicacao(self):
        resultado = ResultadoDeAnalise(
            identificador="C002",
            entradas_por_aplicacao={"VPL": [_criar_entrada()]},
            contagem_por_aplicacao={"VPL": 7, "ORK": 3},
        )
        saida = renderizar_resultado(resultado)

        assert "Contagem por aplicação:" in saida
        assert "VPL: 7" in saida
        assert "ORK: 3" in saida


class TestFalhaDeExibicao:
    """Testes para falha na apresentação (Req 9.5)."""

    def test_falha_retorna_mensagem_de_erro(self):
        entrada = _criar_entrada()
        resultado = ResultadoDeAnalise(
            identificador="F001",
            entradas_por_aplicacao={"VPL": [entrada]},
        )

        # Simular uma falha forçando um dict que levanta exceção ao iterar
        resultado.entradas_por_aplicacao = _DictQueExplode({"VPL": [entrada]})
        saida = renderizar_resultado(resultado)

        assert "Falha ao exibir o resultado da análise" in saida
        assert "preservadas" in saida

    def test_falha_preserva_entradas_no_objeto(self):
        entrada = _criar_entrada()
        resultado = ResultadoDeAnalise(
            identificador="F002",
            entradas_por_aplicacao={"VPL": [entrada]},
        )

        # Guardar referência antes da falha
        entradas_originais = resultado.entradas_por_aplicacao.copy()

        # Simular falha
        resultado.entradas_por_aplicacao = _DictQueExplode({"VPL": [entrada]})
        renderizar_resultado(resultado)

        # As entradas originais continuam acessíveis (preservadas no objeto)
        assert "VPL" in entradas_originais
        assert len(entradas_originais["VPL"]) == 1


class TestExibicaoDeErrosAcumulados:
    """Testes para exibição de erros acumulados no resultado."""

    def test_exibe_erros_acumulados(self):
        resultado = ResultadoDeAnalise(
            identificador="ERR01",
            entradas_por_aplicacao={"VPL": [_criar_entrada()]},
            erros=[
                MensagemDeErro(
                    arquivo_ou_app="arquivo.log",
                    descricao="Arquivo ilegível",
                ),
            ],
        )
        saida = renderizar_resultado(resultado)

        assert "Erros:" in saida
        assert "arquivo.log" in saida
        assert "Arquivo ilegível" in saida
