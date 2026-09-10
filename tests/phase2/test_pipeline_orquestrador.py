"""Integração sintética do orquestrador e dos adapters públicos da Fase 2.

Todos os cenários criam somente arquivos temporários pequenos. Limites de tamanho,
spill e alteração entre passes usam doubles locais e controlados.

Validates: Requirements 1.2, 1.3, 1.4, 1.6, 9.7, 15.1, 15.2,
15.3, 15.5, 15.6, 15.8, 16.1 e 17.1.
"""

from __future__ import annotations

import os
import stat
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

import log_analyzer.core as core
import log_analyzer.core.analisador as modulo_analisador
import log_analyzer.core.pipeline_fase2 as modulo_pipeline
from log_analyzer.core.analisador import Analisador_de_Logs
from log_analyzer.core.bootstrap import criar_registro_padrao
from log_analyzer.core.carregador import TAMANHO_MAXIMO_BYTES
from log_analyzer.core.excecoes import ErroDeIdentificador
from log_analyzer.core.indice import IndiceTemporario
from log_analyzer.core.interfaces import (
    Padrao_de_Analise,
    Parser_de_Aplicacao,
    Parser_de_Bloco,
)
from log_analyzer.core.materializacao import MaterializadorSeletivo
from log_analyzer.core.modelos import (
    ArquivoSelecionado,
    BaseCorrelacao,
    Categoria,
    EntradaDeLog,
    EstadoSanitizacao,
)
from log_analyzer.core.pipeline_fase2 import PipelineFase2
from log_analyzer.core.serializacao import serializar_resultado_de_analise
from log_analyzer.core.streaming import LeitorStreaming


CALL_ID = "CALL-SYN-ORQUESTRADOR-2042"
PLUGIN_ID = "LINE_SYN"


def _gravar(caminho: Path, conteudo: str) -> Path:
    caminho.write_text(conteudo, encoding="utf-8", newline="")
    return caminho


def _vpl(
    call_id: str = CALL_ID,
    *,
    valido: bool = True,
    identificador_tipado: bool = True,
    detalhe: str = "evento sintético VPL",
) -> str:
    nivel = "NOTICE" if valido else "INVALID"
    mensagem = (
        f"CallId={call_id} {detalhe}"
        if identificador_tipado
        else f"{detalhe} literal {call_id}"
    )
    return (
        "2035-06-07 08:09:10.123456 99.50% "
        f"[{nivel}] mod_sintetico.c:42 {mensagem}\n"
    )


def _ork(
    call_id: str = CALL_ID,
    *,
    valido: bool = True,
    identificador_tipado: bool = True,
    detalhe: str = "evento sintético ORK",
) -> str:
    nivel = "INFO" if valido else "INVALID"
    mensagem = (
        f"TelecomCallId={call_id} CallId={call_id} {detalhe}"
        if identificador_tipado
        else f"{detalhe} literal {call_id}"
    )
    return (
        "2035-06-07T11:09:10.123456+00:00 "
        "ork-node.synthetic.invalid ork-worker[4242]: "
        f"{nivel} - agent.synthetic - {mensagem}\n"
    )


def _voci(call_id: str = CALL_ID) -> str:
    return f"2035-06-07 08:09:11\tINFO\tevento sintético {call_id}\n"


class _ParserLineBasedSintetico(Parser_de_Aplicacao):
    """Plugin mínimo que implementa somente os ABCs da Fase 1."""

    def __init__(self) -> None:
        self.linhas_recebidas: list[str] = []

    @property
    def niveis_de_severidade(self) -> frozenset[str]:
        return frozenset({"INFO"})

    def interpretar_entrada(self, texto: str) -> EntradaDeLog:
        self.linhas_recebidas.append(texto)
        return EntradaDeLog(texto, PLUGIN_ID, 0, False)

    def imprimir_entrada(self, entrada: EntradaDeLog) -> str:
        return entrada.texto_original


class _PadraoLineBasedSintetico(Padrao_de_Analise):
    @property
    def categorias(self) -> tuple[Categoria, ...]:
        return tuple(Categoria)

    def classificar(self, entrada: EntradaDeLog) -> Categoria:
        return Categoria.ERRO


def test_orquestrador_preserva_blocos_invalidos_e_isola_fontes_invalidas(
    tmp_path: Path,
) -> None:
    vpl = _gravar(
        tmp_path / "vpl-misto.log",
        _vpl(valido=False) + _vpl(detalhe="evento VPL válido Ω"),
    )
    ork = _gravar(
        tmp_path / "ork-misto.log",
        _ork(valido=False) + _ork(detalhe="evento ORK válido Ω"),
    )
    ausente = tmp_path / "fonte-ausente.log"
    vazio = tmp_path / "fonte-vazia.log"
    vazio.write_bytes(b"")

    resultado = Analisador_de_Logs(criar_registro_padrao()).analisar(
        [
            ArquivoSelecionado(str(vpl), "VPL"),
            ArquivoSelecionado(str(ork), "ORK"),
            ArquivoSelecionado(str(ausente), "VPL"),
            ArquivoSelecionado(str(vazio), "ORK"),
        ],
        CALL_ID,
    )

    assert resultado.estado_sanitizacao is EstadoSanitizacao.CONCLUIDA
    assert resultado.aplicacoes_analisadas == ["VPL", "ORK"]
    assert resultado.aplicacoes_ausentes_ou_invalidas == []
    assert resultado.contagem_por_aplicacao == {"VPL": 2, "ORK": 2}
    assert [
        entrada.interpretada
        for entrada in resultado.entradas_por_aplicacao["VPL"]
    ] == [False, True]
    assert [
        entrada.interpretada
        for entrada in resultado.entradas_por_aplicacao["ORK"]
    ] == [False, True]

    assert len(resultado.linha_do_tempo) == 2
    assert {entrada.aplicacao for entrada in resultado.linha_do_tempo} == {
        "VPL",
        "ORK",
    }
    assert len(resultado.entradas_sem_ordenacao_temporal) == 2
    assert all(
        not entrada.interpretada
        for entrada in resultado.entradas_sem_ordenacao_temporal
    )
    assert resultado.correlacao_encontrada
    assert resultado.correlacao is not None
    assert resultado.correlacao.base_primaria is BaseCorrelacao.VALOR_COMPARTILHADO

    assert [
        (erro.arquivo_ou_app, erro.descricao) for erro in resultado.erros
    ] == [
        ("<ARQUIVO_3>", "FILE_UNAVAILABLE"),
        ("<ARQUIVO_4>", "EMPTY_FILE"),
    ]
    superficie = str(serializar_resultado_de_analise(resultado))
    assert CALL_ID not in superficie
    assert str(ausente) not in superficie
    assert str(vazio) not in superficie


@pytest.mark.parametrize("app_disponivel", ["VPL", "ORK"])
def test_lado_ausente_preserva_resultado_parcial_sem_correlacao(
    tmp_path: Path,
    app_disponivel: str,
) -> None:
    conteudo = _vpl() if app_disponivel == "VPL" else _ork()
    fonte = _gravar(
        tmp_path / f"{app_disponivel.lower()}-unico.log",
        conteudo,
    )
    app_ausente = "ORK" if app_disponivel == "VPL" else "VPL"

    resultado = Analisador_de_Logs(criar_registro_padrao()).analisar(
        [ArquivoSelecionado(str(fonte), app_disponivel)],
        CALL_ID,
    )

    assert resultado.contagem_por_aplicacao == {app_disponivel: 1}
    assert resultado.aplicacoes_analisadas == [app_disponivel]
    assert resultado.aplicacoes_ausentes_ou_invalidas == [app_ausente]
    assert resultado.erros == []
    assert not resultado.correlacao_encontrada
    assert resultado.correlacao is not None
    assert resultado.correlacao.base_primaria is BaseCorrelacao.NENHUMA
    assert len(resultado.linha_do_tempo) == 1


def test_consulta_invalida_nao_acessa_fontes_nem_altera_resultado_anterior(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fonte = _gravar(tmp_path / "vpl-consulta.log", _vpl())
    selecao = [ArquivoSelecionado(str(fonte), "VPL")]
    analisador = Analisador_de_Logs(criar_registro_padrao())
    resultado_anterior = analisador.analisar(selecao, CALL_ID)
    snapshot = deepcopy(serializar_resultado_de_analise(resultado_anterior))
    bytes_antes = fonte.read_bytes()

    class PipelineProibido:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("consulta inválida não pode criar pipeline")

    def carregador_proibido(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("consulta inválida não pode abrir fonte")

    monkeypatch.setattr(modulo_analisador, "PipelineFase2", PipelineProibido)
    monkeypatch.setattr(modulo_analisador, "carregar_arquivo", carregador_proibido)

    for consulta in ("", "   ", "X" * 257):
        with pytest.raises(ErroDeIdentificador):
            analisador.analisar(selecao, consulta)

    assert serializar_resultado_de_analise(resultado_anterior) == snapshot
    assert fonte.read_bytes() == bytes_antes


def test_mudanca_de_fonte_isola_lado_e_limpa_indice_apos_spill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vpl = _gravar(tmp_path / "vpl-mutavel.log", _vpl())
    ork = _gravar(tmp_path / "ork-estavel.log", _ork())
    indices: list[IndiceTemporario] = []
    fechamentos: list[tuple[bool, Path | None, bool]] = []

    class IndiceRastreado(IndiceTemporario):
        def close(self) -> None:
            if not self.fechado:
                caminho = self.caminho_temporario
                fechamentos.append(
                    (
                        self.em_disco,
                        caminho,
                        caminho is not None and caminho.exists(),
                    )
                )
            super().close()

    class MaterializadorComMudanca(MaterializadorSeletivo):
        alterou = False

        def materializar(self, *args: object, **kwargs: object):
            if not self.alterou:
                self.alterou = True
                vpl.write_text(
                    _vpl(detalhe="fonte alterada") + "continuação nova\n",
                    encoding="utf-8",
                    newline="",
                )
            return super().materializar(*args, **kwargs)

    def fabrica_indice() -> IndiceTemporario:
        indice = IndiceRastreado(
            limiar_memoria=0,
            tamanho_lote=1,
            diretorio_temporario=tmp_path,
        )
        indices.append(indice)
        return indice

    def fabrica_pipeline(registro: object) -> PipelineFase2:
        return PipelineFase2(
            registro,  # type: ignore[arg-type]
            fabrica_indice=fabrica_indice,
            fabrica_materializador=MaterializadorComMudanca,
        )

    monkeypatch.setattr(modulo_analisador, "PipelineFase2", fabrica_pipeline)

    resultado = Analisador_de_Logs(criar_registro_padrao()).analisar(
        [
            ArquivoSelecionado(str(vpl), "VPL"),
            ArquivoSelecionado(str(ork), "ORK"),
        ],
        CALL_ID,
    )

    assert resultado.contagem_por_aplicacao == {"ORK": 1}
    assert resultado.aplicacoes_analisadas == ["ORK"]
    assert resultado.aplicacoes_ausentes_ou_invalidas == ["VPL"]
    assert not resultado.correlacao_encontrada
    assert [
        (erro.arquivo_ou_app, erro.descricao) for erro in resultado.erros
    ] == [("<ARQUIVO_1>", "SOURCE_CHANGED")]

    assert len(indices) == 1
    assert indices[0].fechado
    assert len(fechamentos) == 1
    em_disco, caminho_indice, existia_antes_de_fechar = fechamentos[0]
    assert em_disco
    assert caminho_indice is not None
    assert existia_antes_de_fechar
    assert not caminho_indice.exists()


def test_voci_e_plugin_line_based_permanecem_no_fluxo_legado(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    voci = _gravar(tmp_path / "voci-legado.log", _voci())
    plugin = _gravar(
        tmp_path / "plugin-legado.log",
        f"linha selecionada {CALL_ID}\nlinha ignorada\n",
    )
    registro = criar_registro_padrao()
    parser_plugin = _ParserLineBasedSintetico()
    registro.registrar(PLUGIN_ID, parser_plugin, _PadraoLineBasedSintetico())
    caminhos_carregados: list[str] = []
    carregar_real = modulo_analisador.carregar_arquivo

    class PipelineProibido:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("fontes line-based não podem criar PipelineFase2")

    def carregar_rastreado(caminho: str):
        caminhos_carregados.append(caminho)
        return carregar_real(caminho)

    monkeypatch.setattr(modulo_analisador, "PipelineFase2", PipelineProibido)
    monkeypatch.setattr(modulo_analisador, "carregar_arquivo", carregar_rastreado)

    resultado = Analisador_de_Logs(registro).analisar(
        [
            ArquivoSelecionado(str(voci), "VOCI"),
            ArquivoSelecionado(str(plugin), PLUGIN_ID),
        ],
        CALL_ID,
    )

    assert not isinstance(parser_plugin, Parser_de_Bloco)
    assert caminhos_carregados == [str(voci), str(plugin)]
    assert parser_plugin.linhas_recebidas == [
        f"linha selecionada {CALL_ID}",
        "linha ignorada",
    ]
    assert set(resultado.entradas_por_aplicacao) == {"VOCI", PLUGIN_ID}
    assert resultado.entradas_por_aplicacao["VOCI"][0].interpretada
    assert resultado.entradas_por_aplicacao["VOCI"][0].categoria is (
        Categoria.NAO_CLASSIFICADA
    )
    assert resultado.entradas_por_aplicacao[PLUGIN_ID][0].categoria is Categoria.ERRO
    assert resultado.estado_sanitizacao is EstadoSanitizacao.INTERNA_BRUTA
    assert resultado.erros == []


def test_wrappers_publicos_preservam_semantica_legada_e_adapter_fase2(
    tmp_path: Path,
) -> None:
    arquivo = tmp_path / "wrapper-carga.log"
    arquivo.write_bytes(f"primeira\r\nsegunda {CALL_ID}".encode("utf-8"))
    assert core.carregar_arquivo(str(arquivo)) == [
        "primeira",
        f"segunda {CALL_ID}",
    ]

    sem_tempo = EntradaDeLog(f"prefixo {CALL_ID} sufixo", "VPL", 2, False)
    ignorada = EntradaDeLog("outro evento", "ORK", 1, False)
    com_tempo = EntradaDeLog(
        f"{CALL_ID} evento temporal",
        "ORK",
        0,
        True,
        datetime(2035, 6, 7, 11, 9, 10),
        "INFO",
        "evento temporal",
    )
    entradas = [sem_tempo, ignorada, com_tempo]

    assert core.filtrar_por_identificador(entradas, CALL_ID.lower()) == [
        sem_tempo,
        com_tempo,
    ]
    vpl_saida, ork_saida, encontrada, erros = core.correlacionar_vpl_ork(
        [sem_tempo],
        [ignorada],
        "consulta já filtrada",
    )
    assert encontrada
    assert erros == []
    assert vpl_saida[0].correlacionada
    assert ork_saida[0].correlacionada
    assert not sem_tempo.correlacionada
    assert not ignorada.correlacionada
    assert core.ordenar_linha_do_tempo([sem_tempo, com_tempo]) == [
        com_tempo,
        sem_tempo,
    ]

    fonte_fase2 = _gravar(tmp_path / "wrapper-pipeline.log", _vpl())
    resultado = core.executar_pipeline_fase2(
        [ArquivoSelecionado(str(fonte_fase2), "VPL")],
        CALL_ID,
        registro=criar_registro_padrao(),
    )
    assert resultado.contagem_por_aplicacao == {"VPL": 1}
    assert resultado.estado_sanitizacao is EstadoSanitizacao.CONCLUIDA
    assert core.PipelineStreamingFase2 is core.PipelineFase2


def test_limite_de_lote_aceita_100_e_rejeita_o_101_sem_abortar(
    tmp_path: Path,
) -> None:
    arquivos: list[Path] = []
    for numero in range(100):
        arquivos.append(
            _gravar(
                tmp_path / f"vpl-lote-{numero:03d}.log",
                _vpl(detalhe=f"item sintético {numero:03d}"),
            )
        )
    excedente = tmp_path / "vpl-lote-100.log"
    selecao = [ArquivoSelecionado(str(arquivo), "VPL") for arquivo in arquivos]
    selecao.append(ArquivoSelecionado(str(excedente), "VPL"))

    resultado = Analisador_de_Logs(criar_registro_padrao()).analisar(
        selecao,
        CALL_ID,
    )

    assert resultado.contagem_por_aplicacao == {"VPL": 100}
    assert len(resultado.entradas_por_aplicacao["VPL"]) == 100
    assert len(resultado.linha_do_tempo) == 100
    assert resultado.aplicacoes_analisadas == ["VPL"]
    assert [
        (erro.arquivo_ou_app, erro.descricao) for erro in resultado.erros
    ] == [("<ARQUIVO_101>", "BATCH_LIMIT_EXCEEDED")]


def test_limite_de_tamanho_aceita_500_mb_e_rejeita_um_byte_a_mais(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    no_limite = _gravar(tmp_path / "vpl-500mb.log", _vpl())
    acima = _gravar(tmp_path / "vpl-500mb-mais-um.log", _vpl())
    tamanhos = {
        os.fspath(no_limite): TAMANHO_MAXIMO_BYTES,
        os.fspath(acima): TAMANHO_MAXIMO_BYTES + 1,
    }
    tamanhos_validados: list[int] = []

    class LeitorComTamanhoDublado(LeitorStreaming):
        def _executar_preflight(self):
            tamanho = tamanhos[os.fspath(self._caminho)]
            tamanhos_validados.append(tamanho)
            status_dublado = SimpleNamespace(
                st_mode=stat.S_IFREG | stat.S_IRUSR | stat.S_IWUSR,
                st_size=tamanho,
            )
            self._validar_status(status_dublado)  # type: ignore[arg-type]
            return super()._executar_preflight()

    monkeypatch.setattr(modulo_pipeline, "LeitorStreaming", LeitorComTamanhoDublado)

    resultado = Analisador_de_Logs(criar_registro_padrao()).analisar(
        [
            ArquivoSelecionado(str(no_limite), "VPL"),
            ArquivoSelecionado(str(acima), "VPL"),
        ],
        CALL_ID,
    )

    assert tamanhos_validados == [
        TAMANHO_MAXIMO_BYTES,
        TAMANHO_MAXIMO_BYTES + 1,
    ]
    assert resultado.contagem_por_aplicacao == {"VPL": 1}
    assert [
        (erro.arquivo_ou_app, erro.descricao) for erro in resultado.erros
    ] == [("<ARQUIVO_2>", "FILE_TOO_LARGE")]


def test_reassociacao_usa_somente_a_ultima_aplicacao_valida(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fonte = _gravar(tmp_path / "fonte-reassociada.log", _vpl())

    def carregador_legado_proibido(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("a associação VOCI substituída não pode abrir a fonte")

    monkeypatch.setattr(
        modulo_analisador,
        "carregar_arquivo",
        carregador_legado_proibido,
    )

    resultado = Analisador_de_Logs(criar_registro_padrao()).analisar(
        [
            ArquivoSelecionado(str(fonte), "VOCI"),
            ArquivoSelecionado(str(fonte), "VPL"),
        ],
        CALL_ID,
    )

    assert resultado.contagem_por_aplicacao == {"VPL": 1}
    assert set(resultado.entradas_por_aplicacao) == {"VPL"}
    assert resultado.erros == []


def test_literal_compartilhado_e_mesmo_instante_nao_criam_correlacao_implicita(
    tmp_path: Path,
) -> None:
    vpl = _gravar(
        tmp_path / "vpl-literal.log",
        _vpl(identificador_tipado=False),
    )
    ork = _gravar(
        tmp_path / "ork-literal.log",
        _ork(identificador_tipado=False),
    )

    resultado = Analisador_de_Logs(criar_registro_padrao()).analisar(
        [
            ArquivoSelecionado(str(vpl), "VPL"),
            ArquivoSelecionado(str(ork), "ORK"),
        ],
        CALL_ID,
    )

    assert resultado.contagem_por_aplicacao == {"VPL": 1, "ORK": 1}
    assert len(resultado.linha_do_tempo) == 2
    assert resultado.identificadores_extraidos == []
    assert not resultado.correlacao_encontrada
    assert resultado.correlacao is not None
    assert resultado.correlacao.base_primaria is BaseCorrelacao.NENHUMA
    assert all(
        not entrada.correlacionada
        for entradas in resultado.entradas_por_aplicacao.values()
        for entrada in entradas
    )
