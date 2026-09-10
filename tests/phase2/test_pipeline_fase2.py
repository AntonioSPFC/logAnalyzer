"""Smokes sintéticos do pipeline streaming VPL/ORK da tarefa 12.1.

Os testes usam exclusivamente arquivos temporários e dados gerados em memória.
Nenhuma fonte local, banco, dashboard, relatório, rede ou serviço externo é
consultado.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from log_analyzer.core.bootstrap import criar_registro_padrao
from log_analyzer.core.excecoes import ErroDeIdentificador, ErroDeSanitizacao
from log_analyzer.core.indice import IndiceTemporario
from log_analyzer.core.materializacao import MaterializadorSeletivo
from log_analyzer.core.modelos import (
    ArquivoSelecionado,
    BaseCorrelacao,
    Categoria,
    EstadoSanitizacao,
)
from log_analyzer.core.pipeline_fase2 import PipelineFase2
from log_analyzer.core.serializacao import serializar_resultado_de_analise


def _call_id_sintetico() -> str:
    return f"CALL-SYN-{uuid4().hex}"


def _vpl(call_id: str, *, multiline: bool = True) -> str:
    cabecalho = (
        "2030-02-03 04:05:06.123456 98.75% [NOTICE] "
        "mod_sintetico.c:42 "
        f"canal sofia/external/{call_id}@sip.invalid"
    )
    if not multiline:
        return cabecalho + "\n"
    return cabecalho + "\ndetalhe multiline sintético Ω\n"


def _ork(call_id: str) -> str:
    return (
        "2030-02-03T07:05:07.123456+00:00 "
        "ork-node.synthetic.invalid ork-worker[04242]: "
        "INFO - agent.synthetic - "
        f"TelecomCallId={call_id} CallId={call_id}\n"
    )


def _gravar(caminho: Path, texto: str) -> Path:
    caminho.write_text(texto, encoding="utf-8", newline="")
    return caminho


def _superficie_serializada(resultado: object) -> str:
    return json.dumps(
        serializar_resultado_de_analise(resultado),
        ensure_ascii=False,
        sort_keys=True,
    )


def test_pipeline_conecta_streaming_busca_correlacao_catalogo_e_sanitizacao(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_id = _call_id_sintetico()
    vpl = _gravar(tmp_path / "vpl-sintetico.log", _vpl(call_id))
    ork = _gravar(tmp_path / "ork-sintetico.log", _ork(call_id))
    indices: list[IndiceTemporario] = []
    temporarios_criados: list[Path] = []

    class IndiceRastreado(IndiceTemporario):
        def close(self) -> None:
            caminho = self.caminho_temporario
            if caminho is not None:
                temporarios_criados.append(caminho)
            super().close()

    def fabrica_indice() -> IndiceTemporario:
        indice = IndiceRastreado(
            limiar_memoria=0,
            tamanho_lote=1,
            diretorio_temporario=tmp_path,
        )
        indices.append(indice)
        return indice

    def carregador_legado_proibido(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("o pipeline Fase 2 não pode usar carregar_arquivo")

    monkeypatch.setattr(
        "log_analyzer.core.carregador.carregar_arquivo",
        carregador_legado_proibido,
    )

    resultado = PipelineFase2(
        criar_registro_padrao(),
        fabrica_indice=fabrica_indice,
    ).executar(
        (
            ArquivoSelecionado(str(vpl), "VPL"),
            ArquivoSelecionado(str(ork), "ORK"),
        ),
        call_id,
    )

    assert resultado.estado_sanitizacao is EstadoSanitizacao.CONCLUIDA
    assert resultado.categoria_de_cenario is Categoria.NAO_CLASSIFICADA
    assert resultado.regra_aplicada is None
    assert resultado.versao_catalogo == "FASE2_INITIAL_1"
    assert resultado.causa_raiz.descricao_sanitizada == "não determinada"
    assert resultado.cobertura_rotulada == (
        "1 cenário de sucesso; 0 cenários de erro"
    )

    assert resultado.aplicacoes_analisadas == ["VPL", "ORK"]
    assert resultado.aplicacoes_ausentes_ou_invalidas == []
    assert resultado.contagem_por_aplicacao == {"VPL": 1, "ORK": 1}
    assert len(resultado.linha_do_tempo) == 2
    assert resultado.entradas_sem_ordenacao_temporal == []
    assert resultado.correlacao_encontrada
    assert resultado.correlacao is not None
    assert resultado.correlacao.base_primaria is BaseCorrelacao.VALOR_COMPARTILHADO
    assert "detalhe multiline sintético Ω" in (
        resultado.entradas_por_aplicacao["VPL"][0].texto_original
    )

    superficie = _superficie_serializada(resultado)
    assert call_id not in superficie
    assert str(vpl) not in superficie
    assert str(ork) not in superficie
    assert resultado.erros == []

    assert len(indices) == 1
    assert indices[0].fechado
    assert temporarios_criados
    assert all(not caminho.exists() for caminho in temporarios_criados)


def test_fonte_invalida_gera_uma_falha_e_preserva_lado_valido(
    tmp_path: Path,
) -> None:
    call_id = _call_id_sintetico()
    ausente = tmp_path / "vpl-ausente.log"
    ork = _gravar(tmp_path / "ork-valido.log", _ork(call_id))

    resultado = PipelineFase2(criar_registro_padrao()).executar(
        (
            ArquivoSelecionado(str(ausente), "VPL"),
            ArquivoSelecionado(str(ork), "ORK"),
        ),
        call_id,
    )

    assert resultado.estado_sanitizacao is EstadoSanitizacao.CONCLUIDA
    assert resultado.contagem_por_aplicacao == {"ORK": 1}
    assert resultado.aplicacoes_analisadas == ["ORK"]
    assert resultado.aplicacoes_ausentes_ou_invalidas == ["VPL"]
    assert not resultado.correlacao_encontrada
    assert len(resultado.erros) == 1
    assert resultado.erros[0].arquivo_ou_app == "<ARQUIVO_1>"
    assert resultado.erros[0].descricao == "FILE_UNAVAILABLE"
    assert str(ausente) not in _superficie_serializada(resultado)


def test_mudanca_entre_passes_invalida_so_a_fonte_com_source_changed(
    tmp_path: Path,
) -> None:
    call_id = _call_id_sintetico()
    vpl = _gravar(tmp_path / "vpl-mutavel.log", _vpl(call_id, multiline=False))

    class MaterializadorComMudanca(MaterializadorSeletivo):
        alterou = False

        def materializar(self, *args: object, **kwargs: object):
            if not self.alterou:
                self.alterou = True
                vpl.write_text(
                    _vpl(call_id, multiline=False) + "mudança sintética\n",
                    encoding="utf-8",
                    newline="",
                )
            return super().materializar(*args, **kwargs)

    resultado = PipelineFase2(
        criar_registro_padrao(),
        fabrica_materializador=MaterializadorComMudanca,
    ).executar(
        (ArquivoSelecionado(str(vpl), "VPL"),),
        call_id,
    )

    assert resultado.estado_sanitizacao is EstadoSanitizacao.CONCLUIDA
    assert resultado.entradas_por_aplicacao == {}
    assert resultado.aplicacoes_analisadas == []
    assert resultado.aplicacoes_ausentes_ou_invalidas == ["VPL", "ORK"]
    assert len(resultado.erros) == 1
    assert resultado.erros[0].arquivo_ou_app == "<ARQUIVO_1>"
    assert resultado.erros[0].descricao == "SOURCE_CHANGED"
    assert str(vpl) not in _superficie_serializada(resultado)


def test_falha_de_entrada_e_isolada_e_evento_seguinte_continua(
    tmp_path: Path,
) -> None:
    call_id = _call_id_sintetico()
    cabecalho_invalido = (
        "2030-02-03 04:05:05.123456 98.75% [INVALID] "
        f"mod_sintetico.c:41 CallId={call_id}\n"
    )
    fonte = _gravar(
        tmp_path / "vpl-misto.log",
        cabecalho_invalido + _vpl(call_id, multiline=False),
    )

    resultado = PipelineFase2(criar_registro_padrao()).executar(
        (ArquivoSelecionado(str(fonte), "VPL"),),
        call_id,
    )

    entradas = resultado.entradas_por_aplicacao["VPL"]
    assert len(entradas) == 2
    assert entradas[0].interpretada is False
    assert entradas[0].falhas
    assert entradas[1].interpretada is True
    assert resultado.erros == []
    assert resultado.contagem_por_aplicacao == {"VPL": 2}


def test_consulta_invalida_nao_enumera_fontes_nem_cria_indice() -> None:
    enumerou = False
    criou_indice = False

    def selecao_armadilha():
        nonlocal enumerou
        enumerou = True
        raise AssertionError("a seleção não deveria ser enumerada")
        yield  # pragma: no cover

    def fabrica_indice() -> IndiceTemporario:
        nonlocal criou_indice
        criou_indice = True
        return IndiceTemporario()

    pipeline = PipelineFase2(
        criar_registro_padrao(),
        fabrica_indice=fabrica_indice,
    )

    with pytest.raises(ErroDeIdentificador):
        pipeline.executar(selecao_armadilha(), "   ")

    assert not enumerou
    assert not criou_indice


def test_temporario_e_removido_mesmo_quando_sanitizacao_falha(
    tmp_path: Path,
) -> None:
    call_id = _call_id_sintetico()
    vpl = _gravar(tmp_path / "vpl-sanitizacao.log", _vpl(call_id))
    indices: list[IndiceTemporario] = []
    caminhos: list[Path] = []

    class IndiceRastreado(IndiceTemporario):
        def close(self) -> None:
            caminho = self.caminho_temporario
            if caminho is not None:
                caminhos.append(caminho)
            super().close()

    class SanitizadorFalho:
        def criar_visao_segura(self, _resultado: object) -> object:
            raise ErroDeSanitizacao()

    def fabrica_indice() -> IndiceTemporario:
        indice = IndiceRastreado(
            limiar_memoria=0,
            tamanho_lote=1,
            diretorio_temporario=tmp_path,
        )
        indices.append(indice)
        return indice

    pipeline = PipelineFase2(
        criar_registro_padrao(),
        fabrica_indice=fabrica_indice,
        sanitizador=SanitizadorFalho(),  # type: ignore[arg-type]
    )

    with pytest.raises(ErroDeSanitizacao):
        pipeline.executar(
            (ArquivoSelecionado(str(vpl), "VPL"),),
            call_id,
        )

    assert indices[0].fechado
    assert caminhos
    assert all(not caminho.exists() for caminho in caminhos)
