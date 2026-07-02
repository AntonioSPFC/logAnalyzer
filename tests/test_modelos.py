"""Testes para os modelos de dados do domínio (log_analyzer.core.modelos).

Verifica:
- INV-1: EntradaDeLog interpretada requer carimbo_de_tempo, nivel_de_severidade e mensagem.
- INV-2: texto_original é sempre preservado (imutabilidade do dataclass frozen).
- Construção correta dos demais modelos.
"""

from datetime import datetime

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from log_analyzer.core.modelos import (
    ArquivoSelecionado,
    Categoria,
    EntradaDeLog,
    MensagemDeErro,
    ResultadoDeAnalise,
)


# ─── Testes de Categoria ───────────────────────────────────────────────────────


class TestCategoria:
    def test_valores_esperados(self):
        assert Categoria.SUCESSO.value == "sucesso"
        assert Categoria.ERRO.value == "erro"
        assert Categoria.NAO_CLASSIFICADA.value == "não classificada"

    def test_total_de_membros(self):
        assert len(Categoria) == 3


# ─── Testes de EntradaDeLog ────────────────────────────────────────────────────


class TestEntradaDeLog:
    """Testes unitários para EntradaDeLog e seus invariantes."""

    def test_criacao_interpretada_valida(self):
        entrada = EntradaDeLog(
            texto_original="2024-01-01 INFO Mensagem de teste",
            aplicacao="vpl",
            ordem_de_leitura=0,
            interpretada=True,
            carimbo_de_tempo=datetime(2024, 1, 1),
            nivel_de_severidade="INFO",
            mensagem="Mensagem de teste",
        )
        assert entrada.interpretada is True
        assert entrada.carimbo_de_tempo == datetime(2024, 1, 1)
        assert entrada.nivel_de_severidade == "INFO"
        assert entrada.mensagem == "Mensagem de teste"
        assert entrada.categoria == Categoria.NAO_CLASSIFICADA
        assert entrada.correlacionada is False

    def test_criacao_nao_interpretada(self):
        entrada = EntradaDeLog(
            texto_original="linha qualquer sem formato",
            aplicacao="ork",
            ordem_de_leitura=5,
            interpretada=False,
        )
        assert entrada.interpretada is False
        assert entrada.carimbo_de_tempo is None
        assert entrada.nivel_de_severidade is None
        assert entrada.mensagem is None

    def test_inv1_falha_sem_carimbo_de_tempo(self):
        with pytest.raises(ValueError, match="carimbo_de_tempo"):
            EntradaDeLog(
                texto_original="texto",
                aplicacao="vpl",
                ordem_de_leitura=0,
                interpretada=True,
                carimbo_de_tempo=None,
                nivel_de_severidade="INFO",
                mensagem="msg",
            )

    def test_inv1_falha_sem_nivel_de_severidade(self):
        with pytest.raises(ValueError, match="nivel_de_severidade"):
            EntradaDeLog(
                texto_original="texto",
                aplicacao="vpl",
                ordem_de_leitura=0,
                interpretada=True,
                carimbo_de_tempo=datetime(2024, 1, 1),
                nivel_de_severidade=None,
                mensagem="msg",
            )

    def test_inv1_falha_nivel_de_severidade_vazio(self):
        with pytest.raises(ValueError, match="nivel_de_severidade"):
            EntradaDeLog(
                texto_original="texto",
                aplicacao="vpl",
                ordem_de_leitura=0,
                interpretada=True,
                carimbo_de_tempo=datetime(2024, 1, 1),
                nivel_de_severidade="",
                mensagem="msg",
            )

    def test_inv1_falha_sem_mensagem(self):
        with pytest.raises(ValueError, match="mensagem"):
            EntradaDeLog(
                texto_original="texto",
                aplicacao="vpl",
                ordem_de_leitura=0,
                interpretada=True,
                carimbo_de_tempo=datetime(2024, 1, 1),
                nivel_de_severidade="INFO",
                mensagem=None,
            )

    def test_inv1_falha_mensagem_vazia(self):
        with pytest.raises(ValueError, match="mensagem"):
            EntradaDeLog(
                texto_original="texto",
                aplicacao="vpl",
                ordem_de_leitura=0,
                interpretada=True,
                carimbo_de_tempo=datetime(2024, 1, 1),
                nivel_de_severidade="INFO",
                mensagem="",
            )

    def test_inv2_texto_original_preservado(self):
        texto = "  linha com espaços e\tcaracteres especiais!  "
        entrada = EntradaDeLog(
            texto_original=texto,
            aplicacao="voci",
            ordem_de_leitura=0,
            interpretada=False,
        )
        assert entrada.texto_original == texto

    def test_imutabilidade_frozen(self):
        entrada = EntradaDeLog(
            texto_original="texto",
            aplicacao="vpl",
            ordem_de_leitura=0,
            interpretada=False,
        )
        with pytest.raises(AttributeError):
            entrada.texto_original = "outro texto"  # type: ignore[misc]


# ─── Testes de ArquivoSelecionado ─────────────────────────────────────────────


class TestArquivoSelecionado:
    def test_criacao_com_app_id(self):
        arq = ArquivoSelecionado(caminho="/var/log/app.log", app_id="vpl")
        assert arq.caminho == "/var/log/app.log"
        assert arq.app_id == "vpl"

    def test_criacao_sem_app_id(self):
        arq = ArquivoSelecionado(caminho="/var/log/app.log", app_id=None)
        assert arq.app_id is None


# ─── Testes de MensagemDeErro ──────────────────────────────────────────────────


class TestMensagemDeErro:
    def test_criacao(self):
        msg = MensagemDeErro(
            arquivo_ou_app="/var/log/app.log",
            descricao="Arquivo ilegível",
        )
        assert msg.arquivo_ou_app == "/var/log/app.log"
        assert msg.descricao == "Arquivo ilegível"


# ─── Testes de ResultadoDeAnalise ──────────────────────────────────────────────


class TestResultadoDeAnalise:
    def test_criacao_padrao(self):
        resultado = ResultadoDeAnalise(identificador="abc123")
        assert resultado.identificador == "abc123"
        assert resultado.entradas_por_aplicacao == {}
        assert resultado.linha_do_tempo == []
        assert resultado.contagem_por_categoria == {}
        assert resultado.contagem_por_aplicacao == {}
        assert resultado.correlacao_encontrada is False
        assert resultado.erros == []
        assert resultado.mensagens == []

    def test_independencia_de_instancias(self):
        r1 = ResultadoDeAnalise(identificador="id1")
        r2 = ResultadoDeAnalise(identificador="id2")
        r1.mensagens.append("msg")
        assert r2.mensagens == []


# ─── Testes baseados em propriedade ───────────────────────────────────────────


class TestEntradaDeLogPBT:
    """Feature: log-analyzer — Validação de INV-1 e INV-2 via propriedades."""

    @given(
        texto=st.text(min_size=1),
        app=st.sampled_from(["vpl", "ork", "voci"]),
        ordem=st.integers(min_value=0),
    )
    @settings(max_examples=100)
    def test_inv2_texto_original_nunca_alterado(self, texto: str, app: str, ordem: int):
        """INV-2: texto_original é sempre preservado independentemente do estado.

        Validates: Requirements 4.3, 5.4
        """
        entrada = EntradaDeLog(
            texto_original=texto,
            aplicacao=app,
            ordem_de_leitura=ordem,
            interpretada=False,
        )
        assert entrada.texto_original == texto

    @given(
        texto=st.text(min_size=1),
        app=st.sampled_from(["vpl", "ork", "voci"]),
        ordem=st.integers(min_value=0),
        ts=st.datetimes(
            min_value=datetime(2000, 1, 1), max_value=datetime(2030, 12, 31)
        ),
        nivel=st.text(min_size=1, max_size=20).filter(lambda s: s.strip() != ""),
        msg=st.text(min_size=1, max_size=200).filter(lambda s: s.strip() != ""),
    )
    @settings(max_examples=100)
    def test_inv1_interpretada_com_campos_validos(
        self,
        texto: str,
        app: str,
        ordem: int,
        ts: datetime,
        nivel: str,
        msg: str,
    ):
        """INV-1: EntradaDeLog interpretada com todos os campos válidos não levanta erro.

        Validates: Requirements 4.1
        """
        entrada = EntradaDeLog(
            texto_original=texto,
            aplicacao=app,
            ordem_de_leitura=ordem,
            interpretada=True,
            carimbo_de_tempo=ts,
            nivel_de_severidade=nivel,
            mensagem=msg,
        )
        assert entrada.carimbo_de_tempo is not None
        assert entrada.nivel_de_severidade
        assert entrada.mensagem

    @given(
        texto=st.text(min_size=1),
        app=st.sampled_from(["vpl", "ork", "voci"]),
        ordem=st.integers(min_value=0),
        ts=st.one_of(st.none(), st.datetimes()),
        nivel=st.one_of(st.none(), st.just(""), st.text(min_size=1, max_size=10)),
        msg=st.one_of(st.none(), st.just(""), st.text(min_size=1, max_size=50)),
    )
    @settings(max_examples=100)
    def test_inv1_interpretada_requer_todos_os_campos(
        self,
        texto: str,
        app: str,
        ordem: int,
        ts: datetime | None,
        nivel: str | None,
        msg: str | None,
    ):
        """INV-1: se interpretada=True e algum campo é None/vazio, deve levantar ValueError.

        Validates: Requirements 4.1, 4.3
        """
        campos_validos = (
            ts is not None
            and nivel is not None
            and nivel != ""
            and msg is not None
            and msg != ""
        )
        if campos_validos:
            # Deve criar sem erro
            entrada = EntradaDeLog(
                texto_original=texto,
                aplicacao=app,
                ordem_de_leitura=ordem,
                interpretada=True,
                carimbo_de_tempo=ts,
                nivel_de_severidade=nivel,
                mensagem=msg,
            )
            assert entrada.interpretada is True
        else:
            # Deve levantar ValueError
            with pytest.raises(ValueError):
                EntradaDeLog(
                    texto_original=texto,
                    aplicacao=app,
                    ordem_de_leitura=ordem,
                    interpretada=True,
                    carimbo_de_tempo=ts,
                    nivel_de_severidade=nivel,
                    mensagem=msg,
                )
