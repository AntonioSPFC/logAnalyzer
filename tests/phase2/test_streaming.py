"""Testes focados do preflight e da leitura incremental da Fase 2."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from log_analyzer.core.carregador import TAMANHO_MAXIMO_BYTES
from log_analyzer.core.excecoes import ErroDeArquivo, ErroDeDecodificacao
from log_analyzer.core.streaming import (
    LeitorStreaming,
    validar_lote,
)
from tests.phase2.strategies.blocks import (
    BlockSpec,
    LineKind,
    PhysicalLineSpec,
)
from tests.phase2.strategies.files import TemporaryLogFactory


def _capturar_erro(caminho: Path, token: str) -> ErroDeArquivo:
    with pytest.raises(ErroDeArquivo) as exc_info:
        LeitorStreaming(caminho, token)
    erro = exc_info.value
    assert erro.caminho is None
    assert str(caminho) not in str(erro)
    assert erro.contexto["arquivo_token"] == token
    return erro


def test_preserva_offsets_utf8_terminadores_e_fingerprint(
    synthetic_log_factory: TemporaryLogFactory,
) -> None:
    linhas_sinteticas = (
        PhysicalLineSpec(LineKind.CONTINUATION, "ação", "\r\n"),
        PhysicalLineSpec(LineKind.CONTINUATION, "β", "\n"),
        PhysicalLineSpec(LineKind.CONTINUATION, "fim", ""),
    )
    arquivo = synthetic_log_factory.write_blocks(
        (BlockSpec(linhas_sinteticas),),
        filename="mixed-newlines.log",
    )

    leitor = LeitorStreaming(arquivo.path, "<ARQUIVO_7>")
    assert leitor.fingerprint.tamanho_bytes == len(arquivo.payload)
    assert leitor.sha256_arquivo is None

    linhas = list(leitor)
    partes = tuple(linha.serialized.encode("utf-8") for linha in linhas_sinteticas)
    limites = []
    inicio = 0
    for parte in partes:
        fim = inicio + len(parte)
        limites.append((inicio, fim))
        inicio = fim

    assert [linha.numero_1_based for linha in linhas] == [1, 2, 3]
    assert [(linha.inicio_byte, linha.fim_byte) for linha in linhas] == limites
    assert [linha.texto for linha in linhas] == ["ação", "β", "fim"]
    assert [linha.terminador for linha in linhas] == ["\r\n", "\n", ""]
    assert all(linha.decodificada for linha in linhas)
    assert b"".join(
        linha.texto_com_terminador.encode("utf-8")  # type: ignore[union-attr]
        for linha in linhas
    ) == arquivo.payload
    assert [linha.sha256 for linha in linhas] == [
        hashlib.sha256(parte).hexdigest() for parte in partes
    ]
    assert leitor.sha256_arquivo == arquivo.digest
    assert leitor.fingerprint.sha256 == arquivo.digest


def test_utf8_invalido_vira_item_seguro_e_nao_interrompe_linhas_seguintes(
    tmp_path: Path,
) -> None:
    payload = b"SYN_OK\nSYN_BAD\xff\r\nSYN_NEXT"
    caminho = tmp_path / "invalid-utf8.log"
    caminho.write_bytes(payload)

    leitor = LeitorStreaming(caminho, "<ARQUIVO_3>")
    linhas = list(leitor.iterar_linhas())

    assert len(linhas) == 3
    assert linhas[0].texto_com_terminador == "SYN_OK\n"
    assert linhas[2].texto_com_terminador == "SYN_NEXT"

    linha_invalida = linhas[1]
    assert linha_invalida.texto is None
    assert linha_invalida.terminador == "\r\n"
    assert not linha_invalida.decodificada
    assert linha_invalida.tamanho_bytes == len(b"SYN_BAD\xff\r\n")
    assert linha_invalida.sha256 == hashlib.sha256(b"SYN_BAD\xff\r\n").hexdigest()
    assert isinstance(linha_invalida.falha, ErroDeDecodificacao)
    assert linha_invalida.falha.contexto == {
        "codigo": "INVALID_UTF8",
        "arquivo_token": "<ARQUIVO_3>",
        "posicao": payload.index(b"\xff"),
    }
    assert str(caminho) not in str(linha_invalida.falha)
    assert "�" not in "".join(linha.texto or "" for linha in linhas)
    assert leitor.sha256_arquivo == hashlib.sha256(payload).hexdigest()


def test_preflight_rejeita_fontes_invalidas_sem_expor_caminhos(
    synthetic_log_factory: TemporaryLogFactory,
    tmp_path: Path,
) -> None:
    valido = synthetic_log_factory.write_lines(
        ("SYN_VALID",), filename="valid.log"
    )
    vazio = tmp_path / "empty.log"
    vazio.write_bytes(b"")
    diretorio = tmp_path / "directory"
    diretorio.mkdir()
    ausente = tmp_path / "missing.log"

    assert _capturar_erro(vazio, "<ARQUIVO_1>").contexto["codigo"] == "EMPTY_FILE"
    assert (
        _capturar_erro(diretorio, "<ARQUIVO_2>").contexto["codigo"]
        == "NOT_REGULAR_FILE"
    )
    assert (
        _capturar_erro(ausente, "<ARQUIVO_3>").contexto["codigo"]
        == "FILE_UNAVAILABLE"
    )

    with patch("log_analyzer.core.streaming.os.access", return_value=False):
        erro_ilegivel = _capturar_erro(valido.path, "<ARQUIVO_4>")
    assert erro_ilegivel.contexto["codigo"] == "FILE_NOT_READABLE"

    status_real = os.stat(valido.path)
    status_grande = SimpleNamespace(
        st_mode=status_real.st_mode,
        st_size=TAMANHO_MAXIMO_BYTES + 1,
    )
    with patch("log_analyzer.core.streaming.os.stat", return_value=status_grande):
        erro_grande = _capturar_erro(valido.path, "<ARQUIVO_5>")
    assert erro_grande.contexto["codigo"] == "FILE_TOO_LARGE"

    status_no_limite = SimpleNamespace(
        st_mode=status_real.st_mode,
        st_size=TAMANHO_MAXIMO_BYTES,
    )
    with patch("log_analyzer.core.streaming.os.stat", return_value=status_no_limite):
        leitor_no_limite = LeitorStreaming(valido.path, "<ARQUIVO_6>")
    assert leitor_no_limite.arquivo_token == "<ARQUIVO_6>"


def test_preflight_de_lote_preserva_validos_e_rejeita_cada_item_excedente(
    synthetic_log_factory: TemporaryLogFactory,
    tmp_path: Path,
) -> None:
    valido = synthetic_log_factory.write_lines(
        ("SYN_BATCH",), filename="batch.log"
    )
    ausente = tmp_path / "missing-in-batch.log"
    fontes = (valido.path, ausente, *([valido.path] * 99))

    resultado = validar_lote(fontes)

    assert len(resultado.leitores) == 99
    assert len(resultado.falhas) == 2
    assert [falha.contexto["arquivo_token"] for falha in resultado.falhas] == [
        "<ARQUIVO_2>",
        "<ARQUIVO_101>",
    ]
    assert [falha.contexto["codigo"] for falha in resultado.falhas] == [
        "FILE_UNAVAILABLE",
        "BATCH_LIMIT_EXCEEDED",
    ]
    assert resultado.leitores[0].arquivo_token == "<ARQUIVO_1>"
    assert resultado.leitores[-1].arquivo_token == "<ARQUIVO_100>"
    assert all(str(ausente) not in str(falha) for falha in resultado.falhas)
