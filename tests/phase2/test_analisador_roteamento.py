"""Testes sintéticos focados do roteamento preservado da tarefa 12.2.

Validates: Requirements 1.1, 1.2, 1.3, 1.6, 7.7, 9.6, 9.7,
15.1 e 16.1.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import log_analyzer.core.analisador as modulo_analisador
from log_analyzer.core.analisador import Analisador_de_Logs
from log_analyzer.core.bootstrap import criar_registro_padrao
from log_analyzer.core.modelos import (
    ArquivoSelecionado,
    Categoria,
    EstadoSanitizacao,
)


IDENTIFICADOR = "CALL-SYN-ROTEAMENTO-001"


def _vpl(*, campo_conhecido: bool = True) -> str:
    mensagem = (
        f"CallId={IDENTIFICADOR} evento sintético"
        if campo_conhecido
        else f"evento literal {IDENTIFICADOR}"
    )
    return (
        "2032-04-05 06:07:08.123456 99.00% [NOTICE] "
        f"mod_sintetico.c:42 {mensagem}\n"
    )


def _ork(*, campo_conhecido: bool = True) -> str:
    mensagem = (
        f"TelecomCallId={IDENTIFICADOR} evento sintético"
        if campo_conhecido
        else f"evento literal {IDENTIFICADOR}"
    )
    return (
        "2032-04-05T09:07:09.123456+00:00 "
        "ork-node.synthetic.invalid ork-worker[4242]: "
        f"INFO - agent.synthetic - {mensagem}\n"
    )


def _voci() -> str:
    return f"2032-04-05 06:07:10\tINFO\tevento {IDENTIFICADOR}\n"


def _gravar(caminho: Path, conteudo: str) -> Path:
    caminho.write_text(conteudo, encoding="utf-8", newline="")
    return caminho


def test_selecao_mista_rota_cada_fonte_uma_vez_e_nao_usa_timeline_legada_para_fase2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vpl = _gravar(tmp_path / "vpl-sintetico.log", _vpl())
    voci = _gravar(tmp_path / "voci-sintetico.log", _voci())
    carregar_real = modulo_analisador.carregar_arquivo
    ordenar_real = modulo_analisador.ordenar_linha_do_tempo
    caminhos_materializados_no_legado: list[str] = []
    apps_entregues_a_timeline_legada: list[tuple[str, ...]] = []

    def carregar_rastreado(caminho: str):
        caminhos_materializados_no_legado.append(caminho)
        return carregar_real(caminho)

    def ordenar_rastreado(entradas):
        apps_entregues_a_timeline_legada.append(
            tuple(entrada.aplicacao for entrada in entradas)
        )
        return ordenar_real(entradas)

    monkeypatch.setattr(
        modulo_analisador,
        "carregar_arquivo",
        carregar_rastreado,
    )
    monkeypatch.setattr(
        modulo_analisador,
        "ordenar_linha_do_tempo",
        ordenar_rastreado,
    )

    resultado = Analisador_de_Logs(criar_registro_padrao()).analisar(
        [
            ArquivoSelecionado(str(vpl), "VPL"),
            ArquivoSelecionado(str(voci), "VOCI"),
        ],
        IDENTIFICADOR,
    )

    assert caminhos_materializados_no_legado == [str(voci)]
    assert apps_entregues_a_timeline_legada == [("VOCI",)]
    assert set(resultado.entradas_por_aplicacao) == {"VPL", "VOCI"}
    assert [entrada.aplicacao for entrada in resultado.linha_do_tempo] == [
        "VPL"
    ]
    assert [
        entrada.aplicacao
        for entrada in resultado.entradas_sem_ordenacao_temporal
    ] == ["VOCI"]
    assert resultado.entradas_por_aplicacao["VOCI"][0].texto_original == (
        _voci().rstrip("\n")
    )
    assert resultado.entradas_por_aplicacao["VOCI"][0].categoria is (
        Categoria.NAO_CLASSIFICADA
    )
    assert resultado.estado_sanitizacao is EstadoSanitizacao.INTERNA_BRUTA
    assert not resultado.correlacao_encontrada
    assert resultado.erros == []


def test_voci_permanece_integralmente_no_fluxo_legado(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    voci = _gravar(tmp_path / "voci-legado.log", _voci())

    class PipelineProibido:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("VOCI não pode instanciar PipelineFase2")

    monkeypatch.setattr(
        modulo_analisador,
        "PipelineFase2",
        PipelineProibido,
    )

    resultado = Analisador_de_Logs(criar_registro_padrao()).analisar(
        [ArquivoSelecionado(str(voci), "VOCI")],
        IDENTIFICADOR,
    )

    assert resultado.identificador == IDENTIFICADOR
    assert [entrada.aplicacao for entrada in resultado.linha_do_tempo] == [
        "VOCI"
    ]
    assert resultado.entradas_sem_ordenacao_temporal == []
    assert resultado.estado_sanitizacao is EstadoSanitizacao.INTERNA_BRUTA
    assert resultado.entradas_por_aplicacao["VOCI"][0].texto_original == (
        _voci().rstrip("\n")
    )


def test_reassociacao_e_aplicada_antes_do_roteamento_e_da_materializacao_legada(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fonte = _gravar(tmp_path / "fonte-reassociada.log", _vpl())

    def carregar_legado_proibido(_caminho: str):
        raise AssertionError(
            "a associação VOCI substituída não pode materializar a fonte"
        )

    monkeypatch.setattr(
        modulo_analisador,
        "carregar_arquivo",
        carregar_legado_proibido,
    )

    resultado = Analisador_de_Logs(criar_registro_padrao()).analisar(
        [
            ArquivoSelecionado(str(fonte), "VOCI"),
            ArquivoSelecionado(str(fonte), "VPL"),
        ],
        IDENTIFICADOR,
    )

    assert set(resultado.entradas_por_aplicacao) == {"VPL"}
    assert resultado.contagem_por_aplicacao == {"VPL": 1}
    assert resultado.erros == []


def test_mesmo_literal_sem_identificador_tipado_nao_cria_correlacao_fase2(
    tmp_path: Path,
) -> None:
    vpl = _gravar(
        tmp_path / "vpl-literal.log",
        _vpl(campo_conhecido=False),
    )
    ork = _gravar(
        tmp_path / "ork-literal.log",
        _ork(campo_conhecido=False),
    )

    resultado = Analisador_de_Logs(criar_registro_padrao()).analisar(
        [
            ArquivoSelecionado(str(vpl), "VPL"),
            ArquivoSelecionado(str(ork), "ORK"),
        ],
        IDENTIFICADOR,
    )

    assert resultado.contagem_por_aplicacao == {"VPL": 1, "ORK": 1}
    assert resultado.identificadores_extraidos == []
    assert not resultado.correlacao_encontrada
    assert resultado.correlacao is not None
    assert not resultado.correlacao.encontrada
    assert all(
        not entrada.correlacionada
        for entradas in resultado.entradas_por_aplicacao.values()
        for entrada in entradas
    )
