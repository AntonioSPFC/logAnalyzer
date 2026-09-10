"""Regressão dedicada do fluxo VOCI.

Compara parsing, impressão, filtragem, classificação por entrada,
agrupamento, contagens e CLI aos resultados caracterizados da Fase 1.
Não utiliza catálogo, vínculos ou regras novas. Todos os textos são
sintéticos gerados em tempo de teste.

Requirements: 1.2, 1.4, 17.5
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from log_analyzer.apps.padroes import VociPadrao
from log_analyzer.apps.voci import VociParser
from log_analyzer.core.agrupamento import agrupar_por_aplicacao
from log_analyzer.core.analisador import Analisador_de_Logs
from log_analyzer.core.bootstrap import criar_registro_padrao
from log_analyzer.core.contagens import calcular_contagens
from log_analyzer.core.filtro import filtrar_por_identificador
from log_analyzer.core.modelos import ArquivoSelecionado, Categoria, EntradaDeLog
from log_analyzer.core.ordenacao import ordenar_linha_do_tempo


_ID_SINTETICO = "regressao-voci-id-789"
_RAIZ_PROJETO = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Dados sintéticos de teste
# ---------------------------------------------------------------------------

_LINHAS_VALIDAS = [
    ("2031-06-15 10:20:30\tINFO\tmensagem alfa regressao-voci-id-789", {
        "carimbo": datetime(2031, 6, 15, 10, 20, 30),
        "nivel": "INFO",
        "mensagem": "mensagem alfa regressao-voci-id-789",
    }),
    ("2031-06-15 10:20:31\tERROR\tfalha beta regressao-voci-id-789 detalhes", {
        "carimbo": datetime(2031, 6, 15, 10, 20, 31),
        "nivel": "ERROR",
        "mensagem": "falha beta regressao-voci-id-789 detalhes",
    }),
    ("2031-06-15 10:20:32\tWARNING\talerta gama", {
        "carimbo": datetime(2031, 6, 15, 10, 20, 32),
        "nivel": "WARNING",
        "mensagem": "alerta gama",
    }),
    ("2031-06-15 10:20:33\tDEBUG\tdiagnostico delta regressao-voci-id-789", {
        "carimbo": datetime(2031, 6, 15, 10, 20, 33),
        "nivel": "DEBUG",
        "mensagem": "diagnostico delta regressao-voci-id-789",
    }),
    ("2031-06-15 10:20:34\tCRITICAL\tcritico epsilon", {
        "carimbo": datetime(2031, 6, 15, 10, 20, 34),
        "nivel": "CRITICAL",
        "mensagem": "critico epsilon",
    }),
]

_LINHAS_INVALIDAS = [
    "texto livre sem tabulacoes",
    "2031-06-15 10:20:30 | INFO | formato pipe",
    "2031-06-15 10:20:30\tINVALIDO\tmensagem com nivel invalido",
    "2031-06-15 10:20:30\tINFO\t",       # mensagem vazia
    "2031-99-99 10:20:30\tINFO\tdata invalida",
    "\tINFO\ttimestamp ausente",
]


# ---------------------------------------------------------------------------
# Testes de parsing
# ---------------------------------------------------------------------------


class TestVociParsing:
    """Verifica que o parsing VOCI produz os mesmos resultados caracterizados."""

    @pytest.fixture()
    def parser(self) -> VociParser:
        return VociParser()

    @pytest.mark.parametrize(
        ("texto", "esperado"),
        _LINHAS_VALIDAS,
        ids=[f"valida-{i}" for i in range(len(_LINHAS_VALIDAS))],
    )
    def test_entrada_valida_parsing(
        self, parser: VociParser, texto: str, esperado: dict
    ) -> None:
        entrada = parser.interpretar_entrada(texto)

        assert entrada.interpretada is True
        assert entrada.aplicacao == "VOCI"
        assert entrada.texto_original == texto
        assert entrada.carimbo_de_tempo == esperado["carimbo"]
        assert entrada.nivel_de_severidade == esperado["nivel"]
        assert entrada.mensagem == esperado["mensagem"]
        assert entrada.categoria is Categoria.NAO_CLASSIFICADA
        assert entrada.correlacionada is False
        assert entrada.ordem_de_leitura == 0

    @pytest.mark.parametrize(
        "texto",
        _LINHAS_INVALIDAS,
        ids=[f"invalida-{i}" for i in range(len(_LINHAS_INVALIDAS))],
    )
    def test_entrada_invalida_preserva_texto(
        self, parser: VociParser, texto: str
    ) -> None:
        entrada = parser.interpretar_entrada(texto)

        assert entrada.interpretada is False
        assert entrada.aplicacao == "VOCI"
        assert entrada.texto_original == texto
        assert entrada.carimbo_de_tempo is None
        assert entrada.nivel_de_severidade is None
        assert entrada.mensagem is None
        assert entrada.categoria is Categoria.NAO_CLASSIFICADA

    def test_niveis_de_severidade(self, parser: VociParser) -> None:
        assert parser.niveis_de_severidade == frozenset(
            {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        )

    def test_interpretar_arquivo_preserva_sequencia(
        self, parser: VociParser
    ) -> None:
        linhas = (texto for texto, _ in _LINHAS_VALIDAS)
        entradas = list(parser.interpretar_arquivo(linhas))

        assert len(entradas) == len(_LINHAS_VALIDAS)
        for i, entrada in enumerate(entradas):
            assert entrada.interpretada is True
            assert entrada.mensagem == _LINHAS_VALIDAS[i][1]["mensagem"]


# ---------------------------------------------------------------------------
# Testes de impressão (round-trip)
# ---------------------------------------------------------------------------


class TestVociImpressao:
    """Verifica que imprimir_entrada produz texto canônico estável."""

    @pytest.fixture()
    def parser(self) -> VociParser:
        return VociParser()

    @pytest.mark.parametrize(
        ("texto", "_"),
        _LINHAS_VALIDAS,
        ids=[f"roundtrip-{i}" for i in range(len(_LINHAS_VALIDAS))],
    )
    def test_round_trip_entrada_valida(
        self, parser: VociParser, texto: str, _: dict
    ) -> None:
        entrada = parser.interpretar_entrada(texto)
        impresso = parser.imprimir_entrada(entrada)

        assert impresso == texto

        # Round-trip: re-interpretar o impresso devolve os mesmos campos
        reinterpretada = parser.interpretar_entrada(impresso)
        assert reinterpretada.interpretada is True
        assert reinterpretada.carimbo_de_tempo == entrada.carimbo_de_tempo
        assert reinterpretada.nivel_de_severidade == entrada.nivel_de_severidade
        assert reinterpretada.mensagem == entrada.mensagem

    @pytest.mark.parametrize(
        "texto",
        _LINHAS_INVALIDAS,
        ids=[f"impressao-inv-{i}" for i in range(len(_LINHAS_INVALIDAS))],
    )
    def test_impressao_entrada_invalida_preserva_texto_original(
        self, parser: VociParser, texto: str
    ) -> None:
        entrada = parser.interpretar_entrada(texto)
        assert parser.imprimir_entrada(entrada) == texto


# ---------------------------------------------------------------------------
# Testes de filtragem
# ---------------------------------------------------------------------------


class TestVociFiltragem:
    """Verifica filtragem case-insensitive por identificador no fluxo VOCI."""

    @pytest.fixture()
    def entradas(self) -> list[EntradaDeLog]:
        parser = VociParser()
        resultado: list[EntradaDeLog] = []
        for i, (texto, _) in enumerate(_LINHAS_VALIDAS):
            entrada = parser.interpretar_entrada(texto)
            resultado.append(replace(entrada, ordem_de_leitura=i))
        return resultado

    def test_filtra_somente_entradas_com_identificador(
        self, entradas: list[EntradaDeLog]
    ) -> None:
        filtradas = filtrar_por_identificador(entradas, _ID_SINTETICO)

        # Linhas 0, 1 e 3 contêm o identificador
        assert len(filtradas) == 3
        for entrada in filtradas:
            assert _ID_SINTETICO.lower() in entrada.texto_original.lower()

    def test_filtragem_case_insensitive(
        self, entradas: list[EntradaDeLog]
    ) -> None:
        filtradas_upper = filtrar_por_identificador(
            entradas, _ID_SINTETICO.upper()
        )
        filtradas_lower = filtrar_por_identificador(
            entradas, _ID_SINTETICO.lower()
        )
        assert len(filtradas_upper) == len(filtradas_lower)

    def test_filtragem_sem_correspondencia(
        self, entradas: list[EntradaDeLog]
    ) -> None:
        filtradas = filtrar_por_identificador(
            entradas, "identificador-inexistente-zzz"
        )
        assert filtradas == []


# ---------------------------------------------------------------------------
# Testes de classificação por entrada
# ---------------------------------------------------------------------------


class TestVociClassificacaoPorEntrada:
    """Verifica que VociPadrao sempre retorna NAO_CLASSIFICADA."""

    @pytest.fixture()
    def padrao(self) -> VociPadrao:
        return VociPadrao()

    def test_categorias_disponiveis(self, padrao: VociPadrao) -> None:
        assert padrao.categorias == (
            Categoria.SUCESSO,
            Categoria.ERRO,
            Categoria.NAO_CLASSIFICADA,
        )

    @pytest.mark.parametrize(
        ("texto", "_"),
        _LINHAS_VALIDAS,
        ids=[f"classif-{i}" for i in range(len(_LINHAS_VALIDAS))],
    )
    def test_classificacao_sempre_nao_classificada(
        self, padrao: VociPadrao, texto: str, _: dict
    ) -> None:
        parser = VociParser()
        entrada = parser.interpretar_entrada(texto)
        assert padrao.classificar(entrada) is Categoria.NAO_CLASSIFICADA

    def test_classificacao_entrada_nao_interpretada(
        self, padrao: VociPadrao
    ) -> None:
        parser = VociParser()
        entrada = parser.interpretar_entrada("texto sem formato voci")
        assert padrao.classificar(entrada) is Categoria.NAO_CLASSIFICADA


# ---------------------------------------------------------------------------
# Testes de agrupamento
# ---------------------------------------------------------------------------


class TestVociAgrupamento:
    """Verifica agrupamento por aplicação com entradas VOCI."""

    def test_agrupamento_somente_voci(self) -> None:
        parser = VociParser()
        entradas = [
            parser.interpretar_entrada(texto)
            for texto, _ in _LINHAS_VALIDAS
        ]

        grupos = agrupar_por_aplicacao(entradas)

        assert list(grupos.keys()) == ["VOCI"]
        assert len(grupos["VOCI"]) == len(_LINHAS_VALIDAS)

    def test_agrupamento_preserva_ordem(self) -> None:
        parser = VociParser()
        entradas = [
            replace(parser.interpretar_entrada(texto), ordem_de_leitura=i)
            for i, (texto, _) in enumerate(_LINHAS_VALIDAS)
        ]

        grupos = agrupar_por_aplicacao(entradas)
        for i, entrada in enumerate(grupos["VOCI"]):
            assert entrada.ordem_de_leitura == i


# ---------------------------------------------------------------------------
# Testes de contagens
# ---------------------------------------------------------------------------


class TestVociContagens:
    """Verifica cálculo de contagens com entradas VOCI."""

    def test_contagens_todas_nao_classificadas(self) -> None:
        parser = VociParser()
        entradas = [
            parser.interpretar_entrada(texto)
            for texto, _ in _LINHAS_VALIDAS
        ]

        contagem_cat, contagem_app = calcular_contagens(entradas)

        assert contagem_cat == {Categoria.NAO_CLASSIFICADA: len(_LINHAS_VALIDAS)}
        assert contagem_app == {"VOCI": len(_LINHAS_VALIDAS)}

    def test_contagens_lista_vazia(self) -> None:
        contagem_cat, contagem_app = calcular_contagens([])
        assert contagem_cat == {}
        assert contagem_app == {}

    def test_soma_contagens_igual_total(self) -> None:
        parser = VociParser()
        entradas = [
            parser.interpretar_entrada(texto)
            for texto, _ in _LINHAS_VALIDAS
        ]
        contagem_cat, contagem_app = calcular_contagens(entradas)

        assert sum(contagem_cat.values()) == len(entradas)
        assert sum(contagem_app.values()) == len(entradas)


# ---------------------------------------------------------------------------
# Testes de ordenação (linha do tempo)
# ---------------------------------------------------------------------------


class TestVociOrdenacao:
    """Verifica ordenação cronológica de entradas VOCI."""

    def test_ordenacao_por_carimbo(self) -> None:
        parser = VociParser()
        # Criar entradas fora de ordem cronológica
        textos_desordenados = [
            _LINHAS_VALIDAS[3][0],
            _LINHAS_VALIDAS[0][0],
            _LINHAS_VALIDAS[4][0],
            _LINHAS_VALIDAS[1][0],
            _LINHAS_VALIDAS[2][0],
        ]
        entradas = [
            replace(parser.interpretar_entrada(texto), ordem_de_leitura=i)
            for i, texto in enumerate(textos_desordenados)
        ]

        ordenadas = ordenar_linha_do_tempo(entradas)

        carimbos = [e.carimbo_de_tempo for e in ordenadas]
        assert carimbos == sorted(carimbos)

    def test_ordenacao_nao_muta_original(self) -> None:
        parser = VociParser()
        entradas = [
            replace(parser.interpretar_entrada(texto), ordem_de_leitura=i)
            for i, (texto, _) in enumerate(_LINHAS_VALIDAS)
        ]
        copia = list(entradas)

        ordenar_linha_do_tempo(entradas)

        assert entradas == copia


# ---------------------------------------------------------------------------
# Testes de integração via Analisador (fluxo legado VOCI)
# ---------------------------------------------------------------------------


class TestVociFluxoLegadoIntegrado:
    """Verifica o pipeline completo VOCI pelo Analisador sem catálogo/vínculos."""

    def test_analise_voci_com_correspondencia(self, tmp_path: Path) -> None:
        conteudo = (
            f"2031-06-15 10:20:30\tINFO\tevento {_ID_SINTETICO}\n"
            f"2031-06-15 10:20:31\tERROR\tfalha {_ID_SINTETICO}\n"
            "2031-06-15 10:20:32\tWARNING\tsem correspondencia\n"
        )
        arquivo = tmp_path / "voci_regressao.log"
        arquivo.write_text(conteudo, encoding="utf-8")

        analisador = Analisador_de_Logs(criar_registro_padrao())
        resultado = analisador.analisar(
            [ArquivoSelecionado(caminho=str(arquivo), app_id="VOCI")],
            _ID_SINTETICO,
        )

        # Somente 2 entradas contêm o identificador
        assert "VOCI" in resultado.entradas_por_aplicacao
        entradas = resultado.entradas_por_aplicacao["VOCI"]
        assert len(entradas) == 2

        # Todas NAO_CLASSIFICADA
        for entrada in entradas:
            assert entrada.categoria is Categoria.NAO_CLASSIFICADA

        # Contagens
        assert resultado.contagem_por_categoria == {
            Categoria.NAO_CLASSIFICADA: 2
        }
        assert resultado.contagem_por_aplicacao == {"VOCI": 2}

        # Sem correlação
        assert resultado.correlacao_encontrada is False

        # Sem extensões da Fase 2 ativas
        assert (
            getattr(resultado, "categoria_de_cenario", Categoria.NAO_CLASSIFICADA)
            is Categoria.NAO_CLASSIFICADA
        )
        assert getattr(resultado, "regra_aplicada", None) is None
        assert getattr(resultado, "identificadores_extraidos", []) == []
        assert getattr(resultado, "vinculos", []) == []

    def test_analise_voci_sem_correspondencia(self, tmp_path: Path) -> None:
        conteudo = "2031-06-15 10:20:30\tINFO\tmensagem sem id\n"
        arquivo = tmp_path / "voci_vazio.log"
        arquivo.write_text(conteudo, encoding="utf-8")

        analisador = Analisador_de_Logs(criar_registro_padrao())
        resultado = analisador.analisar(
            [ArquivoSelecionado(caminho=str(arquivo), app_id="VOCI")],
            _ID_SINTETICO,
        )

        assert resultado.entradas_por_aplicacao == {}
        assert resultado.contagem_por_categoria == {}
        assert resultado.contagem_por_aplicacao == {}

    def test_analise_voci_linha_do_tempo_ordenada(
        self, tmp_path: Path
    ) -> None:
        conteudo = (
            f"2031-06-15 10:20:35\tINFO\tultimo {_ID_SINTETICO}\n"
            f"2031-06-15 10:20:30\tINFO\tprimeiro {_ID_SINTETICO}\n"
            f"2031-06-15 10:20:33\tINFO\tmeio {_ID_SINTETICO}\n"
        )
        arquivo = tmp_path / "voci_ordem.log"
        arquivo.write_text(conteudo, encoding="utf-8")

        analisador = Analisador_de_Logs(criar_registro_padrao())
        resultado = analisador.analisar(
            [ArquivoSelecionado(caminho=str(arquivo), app_id="VOCI")],
            _ID_SINTETICO,
        )

        carimbos = [e.carimbo_de_tempo for e in resultado.linha_do_tempo]
        assert carimbos == sorted(carimbos)
        assert len(resultado.linha_do_tempo) == 3


# ---------------------------------------------------------------------------
# Testes de CLI
# ---------------------------------------------------------------------------


class TestVociCLI:
    """Verifica a saída da CLI para VOCI preserva formato caracterizado."""

    def _executar_cli(
        self, tmp_path: Path, conteudo: str, identificador: str
    ) -> subprocess.CompletedProcess:
        arquivo = tmp_path / "voci_cli.log"
        arquivo.write_text(conteudo, encoding="utf-8")

        ambiente = os.environ.copy()
        ambiente["PYTHONUTF8"] = "1"
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "log_analyzer",
                identificador,
                f"VOCI:{arquivo}",
            ],
            cwd=_RAIZ_PROJETO,
            env=ambiente,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=30,
        )

    def test_cli_voci_saida_basica(self, tmp_path: Path) -> None:
        conteudo = (
            f"2031-06-15 10:20:30\tINFO\tevento {_ID_SINTETICO}\n"
            f"2031-06-15 10:20:31\tERROR\tfalha {_ID_SINTETICO}\n"
        )
        resultado = self._executar_cli(tmp_path, conteudo, _ID_SINTETICO)

        assert resultado.returncode == 0
        assert "[VOCI] (2 entradas)" in resultado.stdout
        assert resultado.stderr == ""
        assert "Traceback" not in resultado.stdout + resultado.stderr

    def test_cli_voci_sem_correspondencia(self, tmp_path: Path) -> None:
        conteudo = "2031-06-15 10:20:30\tINFO\tsem match\n"
        resultado = self._executar_cli(tmp_path, conteudo, _ID_SINTETICO)

        assert resultado.returncode == 0
        assert "[VOCI]" not in resultado.stdout or "(0 entradas)" in resultado.stdout
        assert resultado.stderr == ""

    def test_cli_voci_contagens_na_saida(self, tmp_path: Path) -> None:
        conteudo = (
            f"2031-06-15 10:20:30\tINFO\tmsg {_ID_SINTETICO}\n"
            f"2031-06-15 10:20:31\tWARNING\talerta {_ID_SINTETICO}\n"
            f"2031-06-15 10:20:32\tERROR\terro {_ID_SINTETICO}\n"
        )
        resultado = self._executar_cli(tmp_path, conteudo, _ID_SINTETICO)

        assert resultado.returncode == 0
        assert "não classificada: 3" in resultado.stdout
        assert "VOCI: 3" in resultado.stdout

    def test_cli_voci_sem_regras_ativas_ou_catalogo_ativo(
        self, tmp_path: Path
    ) -> None:
        conteudo = f"2031-06-15 10:20:30\tINFO\tmsg {_ID_SINTETICO}\n"
        resultado = self._executar_cli(tmp_path, conteudo, _ID_SINTETICO)

        assert resultado.returncode == 0
        # VOCI nunca recebe regra ativa ou catálogo classificador
        assert "Regra aplicada: nenhuma" in resultado.stdout
        # Sem vínculos detectados
        saida = resultado.stdout
        assert "nenhum" in saida  # vínculos: nenhum

    def test_cli_voci_identificador_sanitizado_na_saida(
        self, tmp_path: Path
    ) -> None:
        conteudo = f"2031-06-15 10:20:30\tINFO\tevento {_ID_SINTETICO}\n"
        resultado = self._executar_cli(tmp_path, conteudo, _ID_SINTETICO)

        assert resultado.returncode == 0
        # A sanitização substitui o identificador por placeholder na saída
        assert "<CALL_ID_1>" in resultado.stdout
        # O identificador original não deve vazar na saída sanitizada
        assert _ID_SINTETICO not in resultado.stdout

    def test_cli_voci_erro_de_uso_nao_aparece(self, tmp_path: Path) -> None:
        conteudo = f"2031-06-15 10:20:30\tINFO\tevento {_ID_SINTETICO}\n"
        resultado = self._executar_cli(tmp_path, conteudo, _ID_SINTETICO)

        assert "Uso: python -m log_analyzer" not in resultado.stdout
