"""Caracterização dos plugins, formatos legados e CLI da Fase 1.

Todos os textos e arquivos usados aqui são sintéticos. O módulo não consulta
amostras locais nem qualquer diretório de logs.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from log_analyzer.apps.ork import OrkParser
from log_analyzer.apps.padroes import OrkPadrao, VociPadrao, VplPadrao
from log_analyzer.apps.voci import VociParser
from log_analyzer.apps.vpl import VplParser
from log_analyzer.core.analisador import Analisador_de_Logs
from log_analyzer.core.bootstrap import criar_registro_padrao
from log_analyzer.core.interfaces import Padrao_de_Analise, Parser_de_Aplicacao
from log_analyzer.core.modelos import ArquivoSelecionado, Categoria, EntradaDeLog
from log_analyzer.core.registro import Registro_de_Aplicacoes


IDENTIFICADOR_SINTETICO = "cenario-sintetico-42"


class ParserLegadoMinimo(Parser_de_Aplicacao):
    """Plugin line-based que implementa somente o contrato da Fase 1."""

    @property
    def niveis_de_severidade(self) -> frozenset[str]:
        return frozenset({"INFO"})

    def interpretar_entrada(self, texto: str) -> EntradaDeLog:
        return EntradaDeLog(
            texto_original=texto,
            aplicacao="SINTETICO",
            ordem_de_leitura=0,
            interpretada=False,
        )

    def imprimir_entrada(self, entrada: EntradaDeLog) -> str:
        return entrada.texto_original


class PadraoLegadoMinimo(Padrao_de_Analise):
    """Padrão que implementa somente o contrato por entrada da Fase 1."""

    @property
    def categorias(self) -> tuple[Categoria, ...]:
        return (Categoria.SUCESSO, Categoria.ERRO, Categoria.NAO_CLASSIFICADA)

    def classificar(self, entrada: EntradaDeLog) -> Categoria:
        return Categoria.NAO_CLASSIFICADA


@pytest.mark.parametrize(
    (
        "parser",
        "texto",
        "aplicacao",
        "carimbo",
        "nivel",
        "mensagem",
        "texto_canonico",
    ),
    [
        (
            VplParser(),
            "2030-02-03 04:05:06.007 [NOTICE] modulo_sintetico.c:42 "
            f"evento {IDENTIFICADOR_SINTETICO}",
            "VPL",
            datetime(2030, 2, 3, 4, 5, 6, 7000),
            "NOTICE",
            f"evento {IDENTIFICADOR_SINTETICO}",
            "2030-02-03 04:05:06.007 [NOTICE] modulo_sintetico.c:42 "
            f"evento {IDENTIFICADOR_SINTETICO}",
        ),
        (
            OrkParser(),
            "2030-02-03T04:05:06.007000+00:00 | WARN | "
            f"evento {IDENTIFICADOR_SINTETICO}",
            "ORK",
            datetime(2030, 2, 3, 4, 5, 6, 7000, tzinfo=timezone.utc),
            "WARN",
            f"evento {IDENTIFICADOR_SINTETICO}",
            "2030-02-03T04:05:06.007000+00:00 | WARN | "
            f"evento {IDENTIFICADOR_SINTETICO}",
        ),
        (
            VociParser(),
            "2030-02-03 04:05:06\tWARNING\t"
            f"evento {IDENTIFICADOR_SINTETICO}",
            "VOCI",
            datetime(2030, 2, 3, 4, 5, 6),
            "WARNING",
            f"evento {IDENTIFICADOR_SINTETICO}",
            "2030-02-03 04:05:06\tWARNING\t"
            f"evento {IDENTIFICADOR_SINTETICO}",
        ),
    ],
    ids=("vpl-legado", "ork-legado", "voci-legado"),
)
def test_formatos_legados_preservam_parsing_e_round_trip(
    parser: Parser_de_Aplicacao,
    texto: str,
    aplicacao: str,
    carimbo: datetime,
    nivel: str,
    mensagem: str,
    texto_canonico: str,
) -> None:
    entrada = parser.interpretar_entrada(texto)

    assert entrada.texto_original == texto
    assert entrada.aplicacao == aplicacao
    assert entrada.ordem_de_leitura == 0
    assert entrada.interpretada is True
    assert entrada.carimbo_de_tempo == carimbo
    assert entrada.nivel_de_severidade == nivel
    assert entrada.mensagem == mensagem
    assert entrada.categoria is Categoria.NAO_CLASSIFICADA
    assert entrada.correlacionada is False

    impresso = parser.imprimir_entrada(entrada)
    assert impresso == texto_canonico

    reinterpretada = parser.interpretar_entrada(impresso)
    assert reinterpretada.interpretada is True
    assert reinterpretada.carimbo_de_tempo == entrada.carimbo_de_tempo
    assert reinterpretada.nivel_de_severidade == entrada.nivel_de_severidade
    assert reinterpretada.mensagem == entrada.mensagem


@pytest.mark.parametrize(
    ("parser", "texto"),
    [
        (
            VplParser(),
            "2030-02-03 04:05:06.007 NOTICE modulo.c:42 linha sintetica",
        ),
        (
            OrkParser(),
            "2030-02-03T04:05:06+00:00 - INFO - linha sintetica",
        ),
        (
            VociParser(),
            "2030-02-03 04:05:06 | INFO | linha sintetica",
        ),
    ],
    ids=("vpl-invalido", "ork-invalido", "voci-invalido"),
)
def test_formatos_fora_da_gramatica_legada_preservam_texto(
    parser: Parser_de_Aplicacao,
    texto: str,
) -> None:
    entrada = parser.interpretar_entrada(texto)

    assert entrada.interpretada is False
    assert entrada.texto_original == texto
    assert parser.imprimir_entrada(entrada) == texto


def test_abcs_e_registro_aceitam_plugin_exclusivamente_legado() -> None:
    assert Parser_de_Aplicacao.__abstractmethods__ == frozenset(
        {"niveis_de_severidade", "interpretar_entrada", "imprimir_entrada"}
    )
    assert Padrao_de_Analise.__abstractmethods__ == frozenset(
        {"categorias", "classificar"}
    )

    parser = ParserLegadoMinimo()
    padrao = PadraoLegadoMinimo()
    registro = Registro_de_Aplicacoes()
    registro.registrar("SINTETICO", parser, padrao)

    assert registro.aplicacoes_suportadas() == ("SINTETICO",)
    assert registro.esta_registrada("SINTETICO") is True
    parser_resolvido, padrao_resolvido = registro.obter("SINTETICO")
    assert parser_resolvido is parser
    assert padrao_resolvido is padrao

    textos = (f"linha {indice}" for indice in range(3))
    assert [entrada.texto_original for entrada in parser.interpretar_arquivo(textos)] == [
        "linha 0",
        "linha 1",
        "linha 2",
    ]


def test_bootstrap_preserva_vpl_ork_e_voci_com_plugins_corretos() -> None:
    registro = criar_registro_padrao()

    assert registro.aplicacoes_suportadas() == ("VPL", "ORK", "VOCI")
    tipos_esperados = {
        "VPL": (VplParser, VplPadrao),
        "ORK": (OrkParser, OrkPadrao),
        "VOCI": (VociParser, VociPadrao),
    }
    for app_id, (tipo_parser, tipo_padrao) in tipos_esperados.items():
        parser, padrao = registro.obter(app_id)
        assert type(parser) is tipo_parser
        assert type(padrao) is tipo_padrao


@pytest.mark.parametrize(
    "texto",
    [
        "2030-02-03 04:05:06.007 42.00% [INFO] modulo.c:42 "
        f"evento {IDENTIFICADOR_SINTETICO}",
        "2030-02-03T04:05:06+00:00 host-sintetico processo[42]: "
        f"INFO - logger.sintetico - evento {IDENTIFICADOR_SINTETICO}",
    ],
    ids=("formato-vpl-fase2", "formato-ork-fase2"),
)
def test_voci_nao_adota_formatos_especificos_de_vpl_ou_ork(texto: str) -> None:
    entrada = VociParser().interpretar_entrada(texto)

    assert entrada.aplicacao == "VOCI"
    assert entrada.interpretada is False
    assert entrada.texto_original == texto


def test_voci_permanece_sem_regra_ou_categoria_de_cenario_fase2(
    tmp_path: Path,
) -> None:
    arquivo = tmp_path / "voci-sintetico.log"
    arquivo.write_text(
        "2030-02-03 04:05:06\tERROR\t"
        f"SUCESSO ERRO CallId={IDENTIFICADOR_SINTETICO}\n",
        encoding="utf-8",
    )

    resultado = Analisador_de_Logs(criar_registro_padrao()).analisar(
        [ArquivoSelecionado(caminho=str(arquivo), app_id="VOCI")],
        IDENTIFICADOR_SINTETICO,
    )

    entradas = resultado.entradas_por_aplicacao["VOCI"]
    assert len(entradas) == 1
    assert entradas[0].interpretada is True
    assert entradas[0].nivel_de_severidade == "ERROR"
    assert entradas[0].categoria is Categoria.NAO_CLASSIFICADA
    assert resultado.contagem_por_categoria == {Categoria.NAO_CLASSIFICADA: 1}
    assert resultado.correlacao_encontrada is False

    # Os fallbacks tornam a caracterização compatível tanto antes quanto depois
    # da extensão aditiva dos modelos: VOCI nunca recebe conclusão da Fase 2.
    assert (
        getattr(resultado, "categoria_de_cenario", Categoria.NAO_CLASSIFICADA)
        is Categoria.NAO_CLASSIFICADA
    )
    assert getattr(resultado, "regra_aplicada", None) is None
    assert getattr(resultado, "identificadores_extraidos", []) == []
    assert getattr(resultado, "vinculos", []) == []


@pytest.mark.parametrize(
    ("app_id", "conteudo"),
    [
        (
            "VPL",
            "2030-02-03 04:05:06.007 [INFO] modulo.c:42 "
            f"evento {IDENTIFICADOR_SINTETICO}\n",
        ),
        (
            "ORK",
            "2030-02-03T04:05:06+00:00 | INFO | "
            f"evento {IDENTIFICADOR_SINTETICO}\n",
        ),
        (
            "VOCI",
            "2030-02-03 04:05:06\tINFO\t"
            f"evento {IDENTIFICADOR_SINTETICO}\n",
        ),
    ],
    ids=("cli-vpl", "cli-ork", "cli-voci"),
)
def test_python_m_log_analyzer_preserva_sintaxe_e_associacao(
    tmp_path: Path,
    app_id: str,
    conteudo: str,
) -> None:
    arquivo = tmp_path / f"{app_id.lower()}-sintetico.log"
    arquivo.write_text(conteudo, encoding="utf-8")

    ambiente = os.environ.copy()
    ambiente["PYTHONUTF8"] = "1"
    raiz_projeto = Path(__file__).resolve().parents[2]
    processo = subprocess.run(
        [
            sys.executable,
            "-m",
            "log_analyzer",
            IDENTIFICADOR_SINTETICO,
            f"{app_id}:{arquivo}",
        ],
        cwd=raiz_projeto,
        env=ambiente,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )

    assert processo.returncode == 0, processo.stderr
    assert f"[{app_id}] (1 entradas)" in processo.stdout
    assert "Uso: python -m log_analyzer" not in processo.stdout
    assert "Traceback" not in processo.stdout + processo.stderr
    assert processo.stderr == ""
