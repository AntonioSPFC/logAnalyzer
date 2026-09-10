"""Integração segura da CLI com o renderer iterável da Fase 2.

Os dados deste módulo são exclusivamente sintéticos e temporários.
"""

from __future__ import annotations

from copy import deepcopy
import importlib
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from log_analyzer.core.analisador import Analisador_de_Logs
from log_analyzer.core.modelos import ResultadoDeAnalise
from log_analyzer.core.visao_segura import criar_visao_segura


cli_main = importlib.import_module("log_analyzer.cli.main")

CONSULTA_SINTETICA = "chamada-sintetica-9001"
CREDENCIAL_SINTETICA = "token-sintetico-confidencial"


def test_voci_mantem_sintaxe_e_app_id_com_saida_sanitizada(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    arquivo = tmp_path / "cliente-sintetico-voci.log"
    arquivo.write_text(
        "2042-05-06 09:30:00\tINFO\t"
        f"CallId={CONSULTA_SINTETICA} "
        f"Authorization: Bearer {CREDENCIAL_SINTETICA}\n",
        encoding="utf-8",
    )

    sanitizador_real = cli_main.criar_visao_segura
    with (
        patch.object(
            sys,
            "argv",
            ["log_analyzer", CONSULTA_SINTETICA, f"VOCI:{arquivo}"],
        ),
        patch.object(
            cli_main,
            "criar_visao_segura",
            wraps=sanitizador_real,
        ) as sanitizar,
    ):
        cli_main.main()

    capturado = capsys.readouterr()
    sanitizar.assert_called_once()
    assert "[VOCI] (1 entradas)" in capturado.out
    assert capturado.err == ""
    for bruto in (CONSULTA_SINTETICA, str(arquivo), CREDENCIAL_SINTETICA):
        assert bruto not in capturado.out + capturado.err


def test_fase2_concluida_usa_iterador_sem_resanitizar_e_preserva_argumentos(
    capsys: pytest.CaptureFixture[str],
) -> None:
    resultado = criar_visao_segura(
        ResultadoDeAnalise(identificador=CONSULTA_SINTETICA)
    )
    capturado: dict[str, object] = {}
    caminhos = (
        r"C:\fontes\vpl-sintetico.log",
        r"C:\fontes\ork-sintetico.log",
        r"C:\fontes\voci-sintetico.log",
    )

    def analisar(
        _self: Analisador_de_Logs,
        selecao: object,
        identificador: str,
    ) -> ResultadoDeAnalise:
        capturado["selecao"] = selecao
        capturado["identificador"] = identificador
        return resultado

    iterador_real = cli_main.iterar_linhas_resultado
    with (
        patch.object(
            sys,
            "argv",
            [
                "log_analyzer",
                CONSULTA_SINTETICA,
                f"VPL:{caminhos[0]}",
                f"ORK:{caminhos[1]}",
                f"VOCI:{caminhos[2]}",
            ],
        ),
        patch.object(Analisador_de_Logs, "analisar", new=analisar),
        patch.object(
            cli_main,
            "iterar_linhas_resultado",
            wraps=iterador_real,
        ) as iterador,
        patch.object(cli_main, "criar_visao_segura") as sanitizar,
    ):
        cli_main.main()

    saida = capsys.readouterr()
    selecao = capturado["selecao"]
    assert capturado["identificador"] == CONSULTA_SINTETICA
    assert [(item.app_id, item.caminho) for item in selecao] == [
        ("VPL", caminhos[0]),
        ("ORK", caminhos[1]),
        ("VOCI", caminhos[2]),
    ]
    iterador.assert_called_once_with(resultado)
    sanitizar.assert_not_called()
    assert CONSULTA_SINTETICA not in saida.out + saida.err
    assert all(caminho not in saida.out + saida.err for caminho in caminhos)
    assert saida.err == ""


def test_falha_do_writer_preserva_resultado_e_emite_somente_constante(
    capsys: pytest.CaptureFixture[str],
) -> None:
    resultado = ResultadoDeAnalise(
        identificador=CONSULTA_SINTETICA,
        mensagens=[
            f"Authorization: Bearer {CREDENCIAL_SINTETICA}"
        ],
    )
    snapshot = deepcopy(resultado)
    detalhe_bruto = f"writer falhou para {CONSULTA_SINTETICA}"

    with (
        patch.object(
            sys,
            "argv",
            ["log_analyzer", CONSULTA_SINTETICA, "VOCI:fonte.log"],
        ),
        patch.object(
            Analisador_de_Logs,
            "analisar",
            return_value=resultado,
        ),
        patch.object(
            cli_main,
            "_escrever_uma_vez",
            side_effect=RuntimeError(detalhe_bruto),
        ),
        pytest.raises(SystemExit) as exc_info,
    ):
        cli_main.main()

    saida = capsys.readouterr()
    assert exc_info.value.code == cli_main.CODIGO_SAIDA_ERRO
    assert resultado == snapshot
    assert saida.out == ""
    assert saida.err == f"{cli_main.MENSAGEM_FALHA_APRESENTACAO}\n"
    for bruto in (
        CONSULTA_SINTETICA,
        CREDENCIAL_SINTETICA,
        detalhe_bruto,
        "fonte.log",
    ):
        assert bruto not in saida.out + saida.err


def test_excecao_bruta_da_analise_nunca_cruza_stdout_ou_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    caminho = r"C:\cliente\fonte-confidencial.log"
    detalhe = f"falha em {caminho} para {CONSULTA_SINTETICA}"

    with (
        patch.object(
            sys,
            "argv",
            ["log_analyzer", CONSULTA_SINTETICA, f"VPL:{caminho}"],
        ),
        patch.object(
            Analisador_de_Logs,
            "analisar",
            side_effect=RuntimeError(detalhe),
        ),
        pytest.raises(SystemExit) as exc_info,
    ):
        cli_main.main()

    saida = capsys.readouterr()
    assert exc_info.value.code == cli_main.CODIGO_SAIDA_ERRO
    assert saida.out == ""
    assert saida.err == f"{cli_main.MENSAGEM_FALHA_ANALISE}\n"
    assert CONSULTA_SINTETICA not in saida.err
    assert caminho not in saida.err
    assert detalhe not in saida.err


def test_writer_seekable_reverte_prefixo_parcial() -> None:
    class WriterParcial:
        def __init__(self) -> None:
            self.conteudo = "prefixo-existente"
            self.posicao = len(self.conteudo)

        def seekable(self) -> bool:
            return True

        def tell(self) -> int:
            return self.posicao

        def write(self, texto: str) -> int:
            parcial = texto[: max(1, len(texto) // 2)]
            self.conteudo += parcial
            self.posicao = len(self.conteudo)
            raise OSError(f"falha bruta {CONSULTA_SINTETICA}")

        def seek(self, posicao: int) -> None:
            self.posicao = posicao

        def truncate(self) -> None:
            self.conteudo = self.conteudo[: self.posicao]

    writer = WriterParcial()

    with pytest.raises(cli_main._FalhaDeWriter):
        cli_main._escrever_uma_vez(writer, "conteúdo sanitizado completo\n")

    assert writer.conteudo == "prefixo-existente"
