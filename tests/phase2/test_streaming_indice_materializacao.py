"""Testes unitários integrados de streaming, índice e materialização.

Todos os arquivos e valores são sintéticos, criados exclusivamente em ``tmp_path``.

Validates: Requirements 4.3, 5.3, 14.7, 15.4, 15.6, 15.8.
"""

from __future__ import annotations

from contextlib import closing
import hashlib
import os
from pathlib import Path
import secrets
import sqlite3
import stat
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import log_analyzer.core.indice as modulo_indice
from log_analyzer.core.carregador import TAMANHO_MAXIMO_BYTES
from log_analyzer.core.excecoes import (
    ErroDeArquivo,
    ErroDeDecodificacao,
    ErroDeIntegridadeDaFonte,
)
from log_analyzer.core.indice import IndiceTemporario
from log_analyzer.core.materializacao import (
    FonteMaterializacao,
    MaterializadorSeletivo,
    materializar_selecao,
)
from log_analyzer.core.modelos import EntradaIndexada, ReferenciaTextoOriginal
from log_analyzer.core.streaming import (
    FingerprintArquivo,
    LeitorStreaming,
    LinhaFisica,
    validar_lote,
)


def _status_com_tamanho(status_real: os.stat_result, tamanho: int) -> SimpleNamespace:
    """Cria um double de ``stat`` sem alocar o tamanho anunciado."""

    return SimpleNamespace(
        st_mode=status_real.st_mode,
        st_size=tamanho,
        st_dev=status_real.st_dev,
        st_ino=status_real.st_ino,
        st_mtime_ns=status_real.st_mtime_ns,
    )


def _ler_primeiro_passe(
    caminho: Path,
    arquivo_token: str,
) -> tuple[LeitorStreaming, tuple[LinhaFisica, ...], bytes]:
    leitor = LeitorStreaming(caminho, arquivo_token)
    linhas = tuple(leitor.iterar_linhas())
    return leitor, linhas, caminho.read_bytes()


def _entrada_da_linha(
    linha: LinhaFisica,
    payload: bytes,
    *,
    arquivo_token: str,
    entrada_id: str,
    ordem: int,
) -> EntradaIndexada:
    intervalo = payload[linha.inicio_byte : linha.fim_byte]
    return EntradaIndexada(
        entrada_id=entrada_id,
        aplicacao="VPL",
        ordem_de_leitura=ordem,
        texto_ref=ReferenciaTextoOriginal(
            arquivo_token=arquivo_token,
            inicio_byte=linha.inicio_byte,
            fim_byte=linha.fim_byte,
            linha_inicial=linha.numero_1_based,
            linha_final=linha.numero_1_based,
            sha256=hashlib.sha256(intervalo).hexdigest(),
        ),
        cabecalho=(),
        identificadores_digest=(),
        timestamp_original=None,
        timestamp_normalizado=None,
        falhas=(),
        interpretada=False,
    )


@pytest.mark.parametrize(
    ("quantidade", "leitores_esperados", "falhas_esperadas"),
    ((0, 0, 0), (1, 1, 0), (100, 100, 0), (101, 100, 1)),
)
def test_preflight_respeita_limites_de_zero_um_cem_e_cento_e_um_arquivos(
    tmp_path: Path,
    quantidade: int,
    leitores_esperados: int,
    falhas_esperadas: int,
) -> None:
    fonte = tmp_path / "fonte-minima.log"
    fonte.write_bytes(b"X")

    resultado = validar_lote(tuple(fonte for _ in range(quantidade)))

    assert len(resultado.leitores) == leitores_esperados
    assert len(resultado.falhas) == falhas_esperadas
    assert [leitor.arquivo_token for leitor in resultado.leitores] == [
        f"<ARQUIVO_{indice}>" for indice in range(1, leitores_esperados + 1)
    ]
    if quantidade == 101:
        falha = resultado.falhas[0]
        assert falha.contexto == {
            "codigo": "BATCH_LIMIT_EXCEEDED",
            "arquivo_token": "<ARQUIVO_101>",
        }
        assert str(fonte) not in str(falha)


@pytest.mark.parametrize(
    ("tamanho", "aceito"),
    ((TAMANHO_MAXIMO_BYTES, True), (TAMANHO_MAXIMO_BYTES + 1, False)),
)
def test_preflight_valida_500_mb_sem_criar_arquivo_grande(
    tmp_path: Path,
    tamanho: int,
    aceito: bool,
) -> None:
    fonte = tmp_path / "double-de-tamanho.log"
    fonte.write_bytes(b"double seguro")
    status = _status_com_tamanho(fonte.stat(), tamanho)

    with (
        patch("log_analyzer.core.streaming.os.stat", return_value=status),
        patch("log_analyzer.core.streaming.os.fstat", return_value=status),
    ):
        if aceito:
            leitor = LeitorStreaming(fonte, "<ARQUIVO_1>")
            assert leitor.fingerprint.tamanho_bytes == TAMANHO_MAXIMO_BYTES
        else:
            with pytest.raises(ErroDeArquivo) as exc_info:
                LeitorStreaming(fonte, "<ARQUIVO_1>")

    if not aceito:
        erro = exc_info.value
        assert erro.contexto == {
            "codigo": "FILE_TOO_LARGE",
            "arquivo_token": "<ARQUIVO_1>",
        }
        assert str(fonte) not in str(erro)


def test_offsets_multibyte_terminadores_e_utf8_invalido_sao_lossless_e_seguros(
    tmp_path: Path,
) -> None:
    partes = (
        "ação α\r\n".encode("utf-8"),
        "β\n".encode("utf-8"),
        b"invalido-\xff\r\n",
        "fim".encode("utf-8"),
    )
    payload = b"".join(partes)
    fonte = tmp_path / "unicode-e-terminadores.log"
    fonte.write_bytes(payload)

    leitor, linhas, original = _ler_primeiro_passe(fonte, "<ARQUIVO_1>")
    limites: list[tuple[int, int]] = []
    inicio = 0
    for parte in partes:
        fim = inicio + len(parte)
        limites.append((inicio, fim))
        inicio = fim

    assert [(linha.inicio_byte, linha.fim_byte) for linha in linhas] == limites
    assert [linha.terminador for linha in linhas] == ["\r\n", "\n", "\r\n", ""]
    assert [linha.texto for linha in linhas] == ["ação α", "β", None, "fim"]
    assert leitor.fingerprint.sha256 == hashlib.sha256(payload).hexdigest()

    linha_invalida = linhas[2]
    assert isinstance(linha_invalida.falha, ErroDeDecodificacao)
    assert linha_invalida.falha.contexto == {
        "codigo": "INVALID_UTF8",
        "arquivo_token": "<ARQUIVO_1>",
        "posicao": payload.index(b"\xff"),
    }
    assert str(fonte) not in str(linha_invalida.falha)
    assert repr(partes[2]) not in str(linha_invalida.falha)

    entradas = tuple(
        _entrada_da_linha(
            linha,
            original,
            arquivo_token="<ARQUIVO_1>",
            entrada_id=f"entrada-{indice}",
            ordem=indice,
        )
        for indice, linha in enumerate(linhas, start=1)
    )
    resultado = MaterializadorSeletivo(
        (
            FonteMaterializacao(
                "<ARQUIVO_1>",
                fonte,
                leitor.fingerprint,
            ),
        )
    ).materializar(entradas)

    assert [entrada.texto_original for entrada in resultado.entradas] == [
        "ação α\r\n",
        "β\n",
        "fim",
    ]
    assert len(resultado.falhas) == 1
    falha_materializacao = resultado.falhas[0]
    assert isinstance(falha_materializacao, ErroDeDecodificacao)
    assert falha_materializacao.contexto == linha_invalida.falha.contexto
    assert str(fonte) not in repr(resultado)
    assert repr(partes[2]) not in repr(resultado)


def test_spill_sqlite_tem_permissao_restrita_e_nao_armazena_conteudo_reversivel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    texto_original = f"texto-original-{secrets.token_hex(24)}-ç"
    valor_original_a = f"chamada-original-{secrets.token_hex(24)}-α"
    valor_original_b = f"sessao-original-{secrets.token_hex(24)}-β"
    fonte = tmp_path / f"fonte-{secrets.token_hex(16)}.log"
    fonte.write_text(texto_original, encoding="utf-8")

    chamadas_chmod: list[int] = []
    chmod_real = os.chmod

    def registrar_chmod(caminho: str | os.PathLike[str], modo: int) -> None:
        chamadas_chmod.append(modo)
        chmod_real(caminho, modo)

    monkeypatch.setattr(modulo_indice.os, "chmod", registrar_chmod)

    with IndiceTemporario(
        limiar_memoria=0,
        tamanho_lote=1,
        diretorio_temporario=tmp_path,
    ) as indice:
        indice.adicionar_entrada(
            entrada_id="entrada-segura-1",
            arquivo_token="<ARQUIVO_1>",
            aplicacao_codigo="VPL",
            ordem_de_leitura=0,
            inicio_byte=0,
            fim_byte=len(texto_original.encode("utf-8")),
            linha_inicial=1,
            linha_final=1,
            codigos=("PARSE_OK",),
        )
        identificador = indice.indexar_identificador(
            entrada_id="entrada-segura-1",
            namespace="chamada_externa",
            valor_normalizado=valor_original_a,
        )
        indice.adicionar_aresta(
            origem_namespace="chamada_externa",
            origem_valor_normalizado=valor_original_a,
            destino_namespace="sessao",
            destino_valor_normalizado=valor_original_b,
            relacao_codigo="mapeia_sessao",
            evidencia_entrada_id="entrada-segura-1",
        )
        indice.flush()

        caminho_sqlite = indice.caminho_temporario
        assert indice.em_disco
        assert caminho_sqlite is not None and caminho_sqlite.exists()
        modo_restrito = stat.S_IRUSR | stat.S_IWUSR
        assert modo_restrito in chamadas_chmod
        if os.name == "posix":
            assert stat.S_IMODE(caminho_sqlite.stat().st_mode) == modo_restrito

        with closing(sqlite3.connect(caminho_sqlite)) as conexao:
            tabelas = tuple(
                str(linha[0])
                for linha in conexao.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
                )
            )
            colunas = {
                str(coluna[1]).casefold()
                for tabela in tabelas
                for coluna in conexao.execute(f"PRAGMA table_info({tabela})")
            }
            dump = "\n".join(conexao.iterdump())
            digest_persistido = conexao.execute(
                "SELECT hex(hmac_sha256) FROM identificadores"
            ).fetchone()

        assert digest_persistido == (identificador.hmac_sha256.upper(),)
        assert indice.buscar_identificador(
            "chamada_externa", valor_original_a
        ) == ("entrada-segura-1",)
        assert not any(
            fragmento in coluna
            for coluna in colunas
            for fragmento in ("texto", "caminho", "path", "valor_original")
        )

        bytes_sqlite = caminho_sqlite.read_bytes()
        valores_proibidos = (
            texto_original,
            str(fonte),
            valor_original_a,
            valor_original_b,
        )
        for valor in valores_proibidos:
            assert valor not in dump
            assert valor.encode("utf-8") not in bytes_sqlite

    assert not caminho_sqlite.exists()
    assert not tuple(tmp_path.glob(".log-analyzer-index-*"))


def test_limpeza_do_indice_ocorre_quando_materializacao_lanca_excecao(
    tmp_path: Path,
) -> None:
    fonte = tmp_path / "fonte-limpeza.log"
    fonte.write_bytes(b"CONTEUDO\n")
    leitor, linhas, payload = _ler_primeiro_passe(fonte, "<ARQUIVO_1>")
    entrada = _entrada_da_linha(
        linhas[0],
        payload,
        arquivo_token="<ARQUIVO_1>",
        entrada_id="entrada-limpeza",
        ordem=0,
    )
    origem = FonteMaterializacao("<ARQUIVO_1>", fonte, leitor.fingerprint)

    indice = IndiceTemporario(
        limiar_memoria=0,
        diretorio_temporario=tmp_path,
    )
    indice.adicionar_entrada(
        entrada_id="entrada-indice-limpeza",
        arquivo_token="<ARQUIVO_1>",
        aplicacao_codigo="VPL",
        ordem_de_leitura=0,
        inicio_byte=0,
        fim_byte=1,
        linha_inicial=1,
        linha_final=1,
    )
    caminho_sqlite = indice.caminho_temporario
    assert caminho_sqlite is not None and caminho_sqlite.exists()

    def selecao_com_falha():
        yield entrada
        raise RuntimeError("falha sintética controlada")

    with pytest.raises(RuntimeError, match="falha sintética controlada"):
        materializar_selecao(
            selecao_com_falha(),
            (origem,),
            indice_temporario=indice,
        )

    assert indice.fechado
    assert not caminho_sqlite.exists()
    assert not tuple(tmp_path.glob(".log-analyzer-index-*"))


def test_alteracao_entre_passes_invalida_toda_a_fonte_e_preserva_outra(
    tmp_path: Path,
) -> None:
    fonte_alterada = tmp_path / "fonte-alterada.log"
    fonte_estavel = tmp_path / "fonte-estavel.log"
    fonte_alterada.write_bytes(b"FIRST\nSECOND\n")
    fonte_estavel.write_bytes("estável\r\n".encode("utf-8"))

    leitor_alterado, linhas_alteradas, payload_alterado = _ler_primeiro_passe(
        fonte_alterada,
        "<ARQUIVO_1>",
    )
    leitor_estavel, linhas_estaveis, payload_estavel = _ler_primeiro_passe(
        fonte_estavel,
        "<ARQUIVO_2>",
    )
    entradas_alteradas = tuple(
        _entrada_da_linha(
            linha,
            payload_alterado,
            arquivo_token="<ARQUIVO_1>",
            entrada_id=f"entrada-alterada-{indice}",
            ordem=indice,
        )
        for indice, linha in enumerate(linhas_alteradas)
    )
    entrada_estavel = _entrada_da_linha(
        linhas_estaveis[0],
        payload_estavel,
        arquivo_token="<ARQUIVO_2>",
        entrada_id="entrada-estavel",
        ordem=2,
    )

    status_anterior = fonte_alterada.stat()
    fonte_alterada.write_bytes(b"FIRST\nMUTATE\n")
    os.utime(
        fonte_alterada,
        ns=(status_anterior.st_atime_ns, leitor_alterado.fingerprint.mtime_ns),
    )
    assert fonte_alterada.stat().st_size == leitor_alterado.fingerprint.tamanho_bytes

    resultado = MaterializadorSeletivo(
        (
            FonteMaterializacao(
                "<ARQUIVO_1>",
                fonte_alterada,
                leitor_alterado.fingerprint,
            ),
            FonteMaterializacao(
                "<ARQUIVO_2>",
                fonte_estavel,
                leitor_estavel.fingerprint,
            ),
        )
    ).materializar(
        (entradas_alteradas[0], entrada_estavel, entradas_alteradas[1])
    )

    assert [entrada.entrada_id for entrada in resultado.entradas] == [
        "entrada-estavel"
    ]
    assert resultado.entradas[0].texto_original == "estável\r\n"
    assert len(resultado.falhas) == 1
    falha = resultado.falhas[0]
    assert isinstance(falha, ErroDeIntegridadeDaFonte)
    assert falha.contexto == {
        "codigo": "SOURCE_CHANGED",
        "arquivo_token": "<ARQUIVO_1>",
    }
    assert str(fonte_alterada) not in str(falha)
    assert "FIRST" not in repr(resultado)
    assert "MUTATE" not in repr(resultado)
