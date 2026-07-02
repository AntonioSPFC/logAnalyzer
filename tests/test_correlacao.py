"""Testes para a função correlacionar_vpl_ork.

Verifica a correlação entre entradas VPL e ORK:
- Entradas de ambos os lados são marcadas como correlacionada=True quando ambos
  possuem entradas para o mesmo identificador (Req 8.3)
- correlacao_encontrada é False quando nenhum identificador é compartilhado (Req 8.4)
- Entradas são preservadas e erros registrados quando um lado está indisponível (Req 8.5)
"""

from datetime import datetime

from log_analyzer.core.correlacao import correlacionar_vpl_ork
from log_analyzer.core.modelos import EntradaDeLog, MensagemDeErro


def _criar_entrada(
    aplicacao: str,
    ordem: int,
    texto: str = "log com identificador ABC-123",
    interpretada: bool = False,
) -> EntradaDeLog:
    """Helper para criar uma EntradaDeLog simples."""
    if interpretada:
        return EntradaDeLog(
            texto_original=texto,
            aplicacao=aplicacao,
            ordem_de_leitura=ordem,
            interpretada=True,
            carimbo_de_tempo=datetime(2024, 1, 1, 12, 0, ordem),
            nivel_de_severidade="INFO",
            mensagem="mensagem de teste",
        )
    return EntradaDeLog(
        texto_original=texto,
        aplicacao=aplicacao,
        ordem_de_leitura=ordem,
        interpretada=False,
    )


class TestCorrelacionarVplOrk:
    """Testes unitários para correlacionar_vpl_ork."""

    def test_ambos_lados_com_entradas_marca_correlacionada(self):
        """Req 8.3: Quando ambos possuem entradas, marca correlacionada=True."""
        entradas_vpl = [_criar_entrada("VPL", 0), _criar_entrada("VPL", 1)]
        entradas_ork = [_criar_entrada("ORK", 0)]

        vpl_out, ork_out, correlacao, erros = correlacionar_vpl_ork(
            entradas_vpl, entradas_ork, "ABC-123"
        )

        assert correlacao is True
        assert erros == []
        assert all(e.correlacionada for e in vpl_out)
        assert all(e.correlacionada for e in ork_out)
        assert len(vpl_out) == 2
        assert len(ork_out) == 1

    def test_ambos_vazios_sem_correlacao(self):
        """Req 8.4: Nenhuma entrada de nenhum lado, correlacao_encontrada=False."""
        vpl_out, ork_out, correlacao, erros = correlacionar_vpl_ork(
            [], [], "ABC-123"
        )

        assert correlacao is False
        assert erros == []
        assert vpl_out == []
        assert ork_out == []

    def test_apenas_vpl_disponivel_registra_erro_ork(self):
        """Req 8.5: ORK indisponível, registra erro e preserva VPL."""
        entradas_vpl = [_criar_entrada("VPL", 0), _criar_entrada("VPL", 1)]

        vpl_out, ork_out, correlacao, erros = correlacionar_vpl_ork(
            entradas_vpl, [], "ABC-123"
        )

        assert correlacao is False
        assert len(erros) == 1
        assert erros[0].arquivo_ou_app == "ORK"
        assert "ORK" in erros[0].descricao
        # Entradas VPL preservadas sem alteração (não marcadas como correlacionadas)
        assert vpl_out == entradas_vpl
        assert all(not e.correlacionada for e in vpl_out)
        assert ork_out == []

    def test_apenas_ork_disponivel_registra_erro_vpl(self):
        """Req 8.5: VPL indisponível, registra erro e preserva ORK."""
        entradas_ork = [_criar_entrada("ORK", 0)]

        vpl_out, ork_out, correlacao, erros = correlacionar_vpl_ork(
            [], entradas_ork, "ABC-123"
        )

        assert correlacao is False
        assert len(erros) == 1
        assert erros[0].arquivo_ou_app == "VPL"
        assert "VPL" in erros[0].descricao
        # Entradas ORK preservadas sem alteração
        assert ork_out == entradas_ork
        assert all(not e.correlacionada for e in ork_out)
        assert vpl_out == []

    def test_preserva_texto_original_apos_correlacao(self):
        """Req 8.4/INV-2: texto_original é preservado após marcação de correlação."""
        texto_vpl = "2024-01-01 INFO chamada VPL com id ABC-123"
        texto_ork = "2024-01-01 DEBUG ork processando ABC-123"
        entradas_vpl = [
            EntradaDeLog(
                texto_original=texto_vpl,
                aplicacao="VPL",
                ordem_de_leitura=0,
                interpretada=False,
            )
        ]
        entradas_ork = [
            EntradaDeLog(
                texto_original=texto_ork,
                aplicacao="ORK",
                ordem_de_leitura=0,
                interpretada=False,
            )
        ]

        vpl_out, ork_out, correlacao, erros = correlacionar_vpl_ork(
            entradas_vpl, entradas_ork, "ABC-123"
        )

        assert vpl_out[0].texto_original == texto_vpl
        assert ork_out[0].texto_original == texto_ork

    def test_preserva_todos_os_campos_exceto_correlacionada(self):
        """Verifica que replace() só altera correlacionada, mantendo demais campos."""
        entrada_vpl = EntradaDeLog(
            texto_original="2024-01-01 WARNING msg ABC-123",
            aplicacao="VPL",
            ordem_de_leitura=5,
            interpretada=True,
            carimbo_de_tempo=datetime(2024, 1, 1, 10, 30, 0),
            nivel_de_severidade="WARNING",
            mensagem="msg ABC-123",
        )
        entrada_ork = _criar_entrada("ORK", 0)

        vpl_out, ork_out, correlacao, erros = correlacionar_vpl_ork(
            [entrada_vpl], [entrada_ork], "ABC-123"
        )

        resultado = vpl_out[0]
        assert resultado.correlacionada is True
        assert resultado.texto_original == entrada_vpl.texto_original
        assert resultado.aplicacao == entrada_vpl.aplicacao
        assert resultado.ordem_de_leitura == entrada_vpl.ordem_de_leitura
        assert resultado.interpretada == entrada_vpl.interpretada
        assert resultado.carimbo_de_tempo == entrada_vpl.carimbo_de_tempo
        assert resultado.nivel_de_severidade == entrada_vpl.nivel_de_severidade
        assert resultado.mensagem == entrada_vpl.mensagem
        assert resultado.categoria == entrada_vpl.categoria

    def test_multiplas_entradas_de_ambos_lados(self):
        """Req 8.3: Todas as entradas de ambos os lados são marcadas."""
        entradas_vpl = [_criar_entrada("VPL", i) for i in range(5)]
        entradas_ork = [_criar_entrada("ORK", i) for i in range(3)]

        vpl_out, ork_out, correlacao, erros = correlacionar_vpl_ork(
            entradas_vpl, entradas_ork, "ABC-123"
        )

        assert correlacao is True
        assert len(vpl_out) == 5
        assert len(ork_out) == 3
        assert all(e.correlacionada for e in vpl_out)
        assert all(e.correlacionada for e in ork_out)

    def test_identificador_aparece_na_mensagem_de_erro(self):
        """O identificador buscado aparece na mensagem de erro para contexto."""
        identificador = "UUID-456-789"

        _, _, _, erros = correlacionar_vpl_ork(
            [_criar_entrada("VPL", 0)], [], identificador
        )

        assert identificador in erros[0].descricao
