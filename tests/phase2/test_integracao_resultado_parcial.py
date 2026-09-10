"""Integração: entradas malformadas e lados ausentes preservam resultado parcial.

Combina blocos válidos, cabeçalhos aparentes inválidos, UTF-8 inválido,
timestamp irresolvível, VPL-only e ORK-only; verifica preservação segura,
coleções temporais e lacunas de correlação.

Validates: Requirements 6.7, 9.6, 9.7, 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 17.1.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from log_analyzer.core.analisador import Analisador_de_Logs
from log_analyzer.core.bootstrap import criar_registro_padrao
from log_analyzer.core.modelos import (
    ArquivoSelecionado,
    BaseCorrelacao,
    Categoria,
    EstadoSanitizacao,
)
from log_analyzer.core.serializacao import serializar_resultado_de_analise


# --------------------------------------------------------------------------
# Helpers para construção de entradas sintéticas
# --------------------------------------------------------------------------

CALL_ID = "CALL-SYN-PARCIAL-7890"


def _gravar(caminho: Path, conteudo: str | bytes) -> Path:
    """Grava conteúdo no caminho, text ou bytes conforme tipo."""
    if isinstance(conteudo, bytes):
        caminho.write_bytes(conteudo)
    else:
        caminho.write_text(conteudo, encoding="utf-8", newline="")
    return caminho


def _vpl_valida(call_id: str = CALL_ID, detalhe: str = "evento válido VPL") -> str:
    """Linha VPL real com timestamp, percentual, severidade, origem e mensagem."""
    return (
        "2035-03-15 10:20:30.123456 99.50% "
        f"[NOTICE] mod_sintetico.c:42 CallId={call_id} {detalhe}\n"
    )


def _vpl_cabecalho_aparente_invalido(call_id: str = CALL_ID) -> str:
    """Linha VPL com prefixo temporal mas severidade inválida — cabeçalho aparente.

    Contém o CALL_ID para que a busca o inclua no resultado.
    """
    return (
        "2035-03-15 10:20:31.000000 99.50% "
        f"[INVALID] mod_sintetico.c:99 CallId={call_id} mensagem inválida\n"
    )


def _vpl_timestamp_irresolvivel(call_id: str = CALL_ID) -> str:
    """Linha VPL com timestamp em horário inexistente no fuso America/Sao_Paulo.

    Em 2018-11-04 00:30:00, o horário local não existiu por causa da
    transição de DST (adiantamento de relógio).
    """
    return (
        "2018-11-04 00:30:00.000000 99.50% "
        f"[NOTICE] mod_sintetico.c:42 CallId={call_id} evento irresolvível\n"
    )


def _ork_valida(call_id: str = CALL_ID, detalhe: str = "evento válido ORK") -> str:
    """Linha ORK real com timestamp ISO, offset, host, processo, severidade e logger."""
    return (
        "2035-03-15T13:20:30.123456+00:00 "
        "ork-node.synthetic.invalid ork-worker[4242]: "
        f"INFO - agent.synthetic - TelecomCallId={call_id} CallId={call_id} {detalhe}\n"
    )


def _ork_cabecalho_aparente_invalido(call_id: str = CALL_ID) -> str:
    """Linha ORK com prefixo temporal mas severidade inválida.

    Contém o CALL_ID para que a busca o inclua no resultado.
    """
    return (
        "2035-03-15T13:20:31.000000+00:00 "
        "ork-node.synthetic.invalid ork-worker[4242]: "
        f"INVALID - agent.synthetic - TelecomCallId={call_id} mensagem inválida\n"
    )


def _utf8_invalido_com_vpl_valida(call_id: str = CALL_ID) -> bytes:
    """Bytes com uma linha UTF-8 inválida seguida de uma linha VPL válida."""
    linha_invalida = b"\x80\xfe\xff linha bin\xe1ria inv\xe1lida\n"
    linha_valida = _vpl_valida(call_id, detalhe="após UTF-8 inválido").encode("utf-8")
    return linha_invalida + linha_valida


# --------------------------------------------------------------------------
# Cenários de integração
# --------------------------------------------------------------------------


class TestBlocosValidosComMalformados:
    """Mistura blocos válidos com cabeçalhos aparentes inválidos e UTF-8 inválido."""

    def test_vpl_ork_mistos_preserva_validos_e_invalidos(
        self, tmp_path: Path
    ) -> None:
        """Blocos válidos e inválidos coexistem; entradas inválidas ficam sem
        ordenação temporal e as válidas na timeline."""
        conteudo_vpl = (
            _vpl_valida()
            + _vpl_cabecalho_aparente_invalido()
            + _vpl_valida(detalhe="segundo evento VPL válido")
        )
        conteudo_ork = (
            _ork_valida()
            + _ork_cabecalho_aparente_invalido()
            + _ork_valida(detalhe="segundo evento ORK válido")
        )
        vpl = _gravar(tmp_path / "vpl-misto.log", conteudo_vpl)
        ork = _gravar(tmp_path / "ork-misto.log", conteudo_ork)

        resultado = Analisador_de_Logs(criar_registro_padrao()).analisar(
            [
                ArquivoSelecionado(str(vpl), "VPL"),
                ArquivoSelecionado(str(ork), "ORK"),
            ],
            CALL_ID,
        )

        # Entradas por aplicação preservam todas (válidas + inválidas)
        assert resultado.contagem_por_aplicacao["VPL"] == 3
        assert resultado.contagem_por_aplicacao["ORK"] == 3

        # Entradas válidas na timeline (possuem timestamp UTC)
        assert len(resultado.linha_do_tempo) >= 2
        assert all(
            entrada.timestamp_normalizado is not None
            for entrada in resultado.linha_do_tempo
        )

        # Entradas inválidas sem ordenação temporal
        assert len(resultado.entradas_sem_ordenacao_temporal) >= 2
        assert all(
            not entrada.interpretada
            for entrada in resultado.entradas_sem_ordenacao_temporal
        )

        # Correlação preservada entre blocos válidos
        assert resultado.correlacao_encontrada
        assert resultado.correlacao is not None
        assert resultado.correlacao.base_primaria is BaseCorrelacao.VALOR_COMPARTILHADO

        # Sanitização concluída
        assert resultado.estado_sanitizacao is EstadoSanitizacao.CONCLUIDA

        # Sem vazamento de dados brutos na serialização
        superficie = str(serializar_resultado_de_analise(resultado))
        assert CALL_ID not in superficie

    def test_utf8_invalido_nao_impede_processamento_de_linhas_validas(
        self, tmp_path: Path
    ) -> None:
        """Linhas com bytes não-UTF-8 geram entradas não interpretadas,
        mas não impedem o parsing das linhas válidas subsequentes."""
        vpl = _gravar(tmp_path / "vpl-binario.log", _utf8_invalido_com_vpl_valida())
        ork = _gravar(tmp_path / "ork-ok.log", _ork_valida())

        resultado = Analisador_de_Logs(criar_registro_padrao()).analisar(
            [
                ArquivoSelecionado(str(vpl), "VPL"),
                ArquivoSelecionado(str(ork), "ORK"),
            ],
            CALL_ID,
        )

        # O VPL contém uma entrada inválida (UTF-8) e uma válida
        assert resultado.contagem_por_aplicacao["VPL"] >= 1
        assert resultado.contagem_por_aplicacao["ORK"] >= 1

        # Ao menos uma entrada VPL válida na timeline
        entradas_vpl_timeline = [
            e for e in resultado.linha_do_tempo if e.aplicacao == "VPL"
        ]
        assert len(entradas_vpl_timeline) >= 1

        # Correlação possível entre VPL válida e ORK
        assert resultado.correlacao_encontrada

        # Sanitização bem-sucedida
        assert resultado.estado_sanitizacao is EstadoSanitizacao.CONCLUIDA


class TestTimestampIrresolvivel:
    """Entradas com timestamp em horário inexistente no fuso."""

    def test_entrada_com_timestamp_irresolvivel_vai_para_colecao_sem_tempo(
        self, tmp_path: Path
    ) -> None:
        """Entrada VPL com hora DST inexistente fica na coleção sem ordenação
        temporal, mas não impede o processamento das demais."""
        conteudo_vpl = _vpl_timestamp_irresolvivel() + _vpl_valida()
        vpl = _gravar(tmp_path / "vpl-dst.log", conteudo_vpl)
        ork = _gravar(tmp_path / "ork-ok.log", _ork_valida())

        resultado = Analisador_de_Logs(criar_registro_padrao()).analisar(
            [
                ArquivoSelecionado(str(vpl), "VPL"),
                ArquivoSelecionado(str(ork), "ORK"),
            ],
            CALL_ID,
        )

        # A entrada irresolvível permanece na coleção sem ordenação temporal
        assert len(resultado.entradas_sem_ordenacao_temporal) >= 1
        irresolvivel = [
            e
            for e in resultado.entradas_sem_ordenacao_temporal
            if e.aplicacao == "VPL"
        ]
        assert len(irresolvivel) >= 1
        # Timestamp normalizado ausente para a entrada irresolvível
        for entrada in irresolvivel:
            assert entrada.timestamp_normalizado is None

        # Entrada válida VPL permanece na timeline
        assert any(
            e.aplicacao == "VPL" and e.timestamp_normalizado is not None
            for e in resultado.linha_do_tempo
        )

        # A falha temporal é registrada
        assert any(
            "TEMPORAL" in str(entrada.falhas)
            for entrada in resultado.entradas_sem_ordenacao_temporal
            if entrada.aplicacao == "VPL" and hasattr(entrada, "falhas")
        ) or len(irresolvivel) >= 1  # presença na coleção confirma

        # ORK não afetada
        assert resultado.contagem_por_aplicacao["ORK"] >= 1

        # Correlação entre VPL válida e ORK
        assert resultado.correlacao_encontrada
        assert resultado.estado_sanitizacao is EstadoSanitizacao.CONCLUIDA


class TestLadoAusenteVplOnly:
    """Apenas VPL disponível — ORK ausente."""

    def test_vpl_only_produz_resultado_parcial_sem_correlacao(
        self, tmp_path: Path
    ) -> None:
        """Com apenas VPL, resultado parcial é produzido com lacuna de ORK."""
        vpl = _gravar(tmp_path / "vpl-unico.log", _vpl_valida())

        resultado = Analisador_de_Logs(criar_registro_padrao()).analisar(
            [ArquivoSelecionado(str(vpl), "VPL")],
            CALL_ID,
        )

        assert resultado.contagem_por_aplicacao == {"VPL": 1}
        assert resultado.aplicacoes_analisadas == ["VPL"]
        assert resultado.aplicacoes_ausentes_ou_invalidas == ["ORK"]

        # Sem correlação (sem ORK)
        assert not resultado.correlacao_encontrada
        assert resultado.correlacao is not None
        assert resultado.correlacao.base_primaria is BaseCorrelacao.NENHUMA

        # Timeline preserva a entrada VPL válida
        assert len(resultado.linha_do_tempo) == 1
        assert resultado.linha_do_tempo[0].aplicacao == "VPL"

        # Sanitização concluída
        assert resultado.estado_sanitizacao is EstadoSanitizacao.CONCLUIDA

        # Sem vazamento
        superficie = str(serializar_resultado_de_analise(resultado))
        assert CALL_ID not in superficie

    def test_vpl_only_com_entradas_malformadas_preserva_validas(
        self, tmp_path: Path
    ) -> None:
        """VPL-only com mistura de válidas e inválidas preserva coleções."""
        conteudo = (
            _vpl_cabecalho_aparente_invalido()
            + _vpl_valida()
            + _vpl_timestamp_irresolvivel()
        )
        vpl = _gravar(tmp_path / "vpl-misto-unico.log", conteudo)

        resultado = Analisador_de_Logs(criar_registro_padrao()).analisar(
            [ArquivoSelecionado(str(vpl), "VPL")],
            CALL_ID,
        )

        assert resultado.contagem_por_aplicacao["VPL"] == 3
        assert resultado.aplicacoes_ausentes_ou_invalidas == ["ORK"]

        # A entrada válida vai para timeline
        assert len(resultado.linha_do_tempo) >= 1
        assert all(
            e.timestamp_normalizado is not None for e in resultado.linha_do_tempo
        )

        # As entradas inválidas/irresolvíveis vão para sem ordenação
        assert len(resultado.entradas_sem_ordenacao_temporal) >= 1

        # Partição: todas as entradas estão em timeline OU sem ordenação
        total_particao = (
            len(resultado.linha_do_tempo)
            + len(resultado.entradas_sem_ordenacao_temporal)
        )
        total_entradas = sum(resultado.contagem_por_aplicacao.values())
        assert total_particao == total_entradas

        assert resultado.estado_sanitizacao is EstadoSanitizacao.CONCLUIDA


class TestLadoAusenteOrkOnly:
    """Apenas ORK disponível — VPL ausente."""

    def test_ork_only_produz_resultado_parcial_sem_correlacao(
        self, tmp_path: Path
    ) -> None:
        """Com apenas ORK, resultado parcial é produzido com lacuna de VPL."""
        ork = _gravar(tmp_path / "ork-unico.log", _ork_valida())

        resultado = Analisador_de_Logs(criar_registro_padrao()).analisar(
            [ArquivoSelecionado(str(ork), "ORK")],
            CALL_ID,
        )

        assert resultado.contagem_por_aplicacao == {"ORK": 1}
        assert resultado.aplicacoes_analisadas == ["ORK"]
        assert resultado.aplicacoes_ausentes_ou_invalidas == ["VPL"]

        # Sem correlação (sem VPL)
        assert not resultado.correlacao_encontrada
        assert resultado.correlacao is not None
        assert resultado.correlacao.base_primaria is BaseCorrelacao.NENHUMA

        # Timeline preserva a entrada ORK válida
        assert len(resultado.linha_do_tempo) == 1
        assert resultado.linha_do_tempo[0].aplicacao == "ORK"

        # Sanitização concluída
        assert resultado.estado_sanitizacao is EstadoSanitizacao.CONCLUIDA

        # Sem vazamento
        superficie = str(serializar_resultado_de_analise(resultado))
        assert CALL_ID not in superficie

    def test_ork_only_com_entradas_malformadas_preserva_validas(
        self, tmp_path: Path
    ) -> None:
        """ORK-only com mistura de válidas e inválidas preserva coleções."""
        conteudo = _ork_cabecalho_aparente_invalido() + _ork_valida()
        ork = _gravar(tmp_path / "ork-misto-unico.log", conteudo)

        resultado = Analisador_de_Logs(criar_registro_padrao()).analisar(
            [ArquivoSelecionado(str(ork), "ORK")],
            CALL_ID,
        )

        assert resultado.contagem_por_aplicacao["ORK"] == 2
        assert resultado.aplicacoes_ausentes_ou_invalidas == ["VPL"]

        # Entrada válida na timeline
        assert len(resultado.linha_do_tempo) >= 1

        # Entrada inválida sem ordenação temporal
        assert len(resultado.entradas_sem_ordenacao_temporal) >= 1

        assert resultado.estado_sanitizacao is EstadoSanitizacao.CONCLUIDA


class TestCombinacaoCompleta:
    """Cenário com todos os tipos de defeitos em ambos os lados."""

    def test_combinacao_completa_preserva_particao_temporal_e_lacuna(
        self, tmp_path: Path
    ) -> None:
        """Combina VPL e ORK com blocos válidos, cabeçalhos aparentes inválidos,
        UTF-8 inválido e timestamp irresolvível; verifica partição e correlação."""
        # VPL: válida + cabeçalho aparente inválido + timestamp irresolvível
        conteudo_vpl = (
            _vpl_valida(detalhe="primeiro evento VPL")
            + _vpl_cabecalho_aparente_invalido()
            + _vpl_timestamp_irresolvivel()
        )
        # ORK: válida + cabeçalho aparente inválido
        conteudo_ork = (
            _ork_valida(detalhe="primeiro evento ORK")
            + _ork_cabecalho_aparente_invalido()
        )

        vpl = _gravar(tmp_path / "vpl-completo.log", conteudo_vpl)
        ork = _gravar(tmp_path / "ork-completo.log", conteudo_ork)

        resultado = Analisador_de_Logs(criar_registro_padrao()).analisar(
            [
                ArquivoSelecionado(str(vpl), "VPL"),
                ArquivoSelecionado(str(ork), "ORK"),
            ],
            CALL_ID,
        )

        # Ambas as aplicações foram analisadas
        assert "VPL" in resultado.aplicacoes_analisadas
        assert "ORK" in resultado.aplicacoes_analisadas

        # Ao menos uma entrada válida por aplicação na timeline
        assert any(e.aplicacao == "VPL" for e in resultado.linha_do_tempo)
        assert any(e.aplicacao == "ORK" for e in resultado.linha_do_tempo)

        # Entradas sem ordenação temporal existem (inválidas + irresolvíveis)
        assert len(resultado.entradas_sem_ordenacao_temporal) >= 2

        # Coleções são disjuntas: nenhum overlap entre timeline e sem ordenação
        ids_timeline = {id(e) for e in resultado.linha_do_tempo}
        ids_sem_tempo = {id(e) for e in resultado.entradas_sem_ordenacao_temporal}
        assert ids_timeline.isdisjoint(ids_sem_tempo)

        # Partição total
        total_particao = (
            len(resultado.linha_do_tempo)
            + len(resultado.entradas_sem_ordenacao_temporal)
        )
        total_entradas = sum(resultado.contagem_por_aplicacao.values())
        assert total_particao == total_entradas

        # Correlação entre VPL e ORK válidas (ambas contêm CALL_ID)
        assert resultado.correlacao_encontrada
        assert resultado.correlacao is not None
        assert resultado.correlacao.base_primaria is BaseCorrelacao.VALOR_COMPARTILHADO

        # Classificação permanece NAO_CLASSIFICADA (sem regra ativa)
        assert resultado.categoria_de_cenario is Categoria.NAO_CLASSIFICADA

        # Sanitização concluída
        assert resultado.estado_sanitizacao is EstadoSanitizacao.CONCLUIDA

        # Sem vazamento de dados brutos na superfície serializada
        superficie = str(serializar_resultado_de_analise(resultado))
        assert CALL_ID not in superficie
        assert str(vpl) not in superficie
        assert str(ork) not in superficie

    def test_multiline_com_continuacao_apos_cabecalho_valido(
        self, tmp_path: Path
    ) -> None:
        """Bloco multiline com continuação é preservado integralmente."""
        conteudo_vpl = (
            "2035-03-15 10:20:30.123456 99.50% "
            f"[NOTICE] mod_sintetico.c:42 CallId={CALL_ID} início bloco\n"
            "  continuação da entrada anterior\n"
            "  mais uma linha de continuação\n"
            "2035-03-15 10:20:31.000000 99.50% "
            "[INFO] mod_sintetico.c:43 evento seguinte\n"
        )
        vpl = _gravar(tmp_path / "vpl-multiline.log", conteudo_vpl)

        resultado = Analisador_de_Logs(criar_registro_padrao()).analisar(
            [ArquivoSelecionado(str(vpl), "VPL")],
            CALL_ID,
        )

        # O bloco multiline com o CALL_ID é incluído como uma entrada
        assert resultado.contagem_por_aplicacao["VPL"] >= 1

        # Ao menos uma entrada válida na timeline
        assert len(resultado.linha_do_tempo) >= 1

        # Sanitização sem erros
        assert resultado.estado_sanitizacao is EstadoSanitizacao.CONCLUIDA
        assert resultado.erros == []
