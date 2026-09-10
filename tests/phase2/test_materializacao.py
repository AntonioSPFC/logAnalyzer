"""Testes focados do segundo passe seletivo e íntegro.

Todos os arquivos são sintéticos e vivem em ``tmp_path``.

Validates: Requirements 5.1, 5.2, 5.3, 14.7, 15.1, 15.4, 15.6.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from log_analyzer.core.excecoes import (
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
from log_analyzer.core.streaming import FingerprintArquivo, LeitorStreaming


def _primeiro_passe(
    caminho: Path,
    token: str,
) -> tuple[FingerprintArquivo, bytes]:
    leitor = LeitorStreaming(caminho, token)
    list(leitor)
    return leitor.fingerprint, caminho.read_bytes()


def _entrada(
    *,
    entrada_id: str,
    token: str,
    payload: bytes,
    inicio: int,
    fim: int,
    linha_inicial: int,
    linha_final: int,
    ordem: int,
) -> EntradaIndexada:
    return EntradaIndexada(
        entrada_id=entrada_id,
        aplicacao="VPL",
        ordem_de_leitura=ordem,
        texto_ref=ReferenciaTextoOriginal(
            arquivo_token=token,
            inicio_byte=inicio,
            fim_byte=fim,
            linha_inicial=linha_inicial,
            linha_final=linha_final,
            sha256=hashlib.sha256(payload[inicio:fim]).hexdigest(),
        ),
        cabecalho=(),
        identificadores_digest=(),
        timestamp_original=None,
        timestamp_normalizado=None,
        falhas=(),
        interpretada=False,
    )


def _fonte(
    caminho: Path,
    token: str,
    fingerprint: FingerprintArquivo,
) -> FonteMaterializacao:
    return FonteMaterializacao(token, caminho, fingerprint)


def test_rele_apenas_selecionados_e_reconstroi_utf8_e_terminadores(
    tmp_path: Path,
) -> None:
    payload = "IGNORADA\nação α\r\nβ\nTAMBÉM IGNORADA".encode("utf-8")
    caminho = tmp_path / "fonte-sintetica.log"
    caminho.write_bytes(payload)
    fingerprint, original = _primeiro_passe(caminho, "<ARQUIVO_1>")

    inicio_primeira = original.index("ação".encode("utf-8"))
    fim_primeira = original.index("β".encode("utf-8")) + len("β\n".encode("utf-8"))
    inicio_segunda = 0
    fim_segunda = len("IGNORADA\n".encode("utf-8"))
    entrada_multiline = _entrada(
        entrada_id="entrada-sintetica-multiline",
        token="<ARQUIVO_1>",
        payload=original,
        inicio=inicio_primeira,
        fim=fim_primeira,
        linha_inicial=2,
        linha_final=3,
        ordem=1,
    )
    entrada_inicial = _entrada(
        entrada_id="entrada-sintetica-inicial",
        token="<ARQUIVO_1>",
        payload=original,
        inicio=inicio_segunda,
        fim=fim_segunda,
        linha_inicial=1,
        linha_final=1,
        ordem=0,
    )

    resultado = MaterializadorSeletivo(
        (_fonte(caminho, "<ARQUIVO_1>", fingerprint),)
    ).materializar((entrada_multiline, entrada_inicial))

    assert [entrada.entrada_id for entrada in resultado.entradas] == [
        "entrada-sintetica-multiline",
        "entrada-sintetica-inicial",
    ]
    assert [entrada.texto_original for entrada in resultado.entradas] == [
        "ação α\r\nβ\n",
        "IGNORADA\n",
    ]
    assert resultado.falhas == ()
    assert "TAMBÉM IGNORADA" not in repr(resultado)
    for materializada in resultado.entradas:
        referencia = materializada.entrada_indexada.texto_ref
        assert materializada.texto_original.encode("utf-8") == original[
            referencia.inicio_byte : referencia.fim_byte
        ]


@pytest.mark.parametrize("alteracao", ("identidade", "tamanho", "mtime", "hash"))
def test_identidade_tamanho_mtime_e_hash_invalidam_toda_a_fonte(
    tmp_path: Path,
    alteracao: str,
) -> None:
    payload = b"SYN_A\nSYN_B\n"
    caminho = tmp_path / f"fonte-{alteracao}.log"
    caminho.write_bytes(payload)
    fingerprint, original = _primeiro_passe(caminho, "<ARQUIVO_1>")
    primeira = _entrada(
        entrada_id="entrada-sintetica-a",
        token="<ARQUIVO_1>",
        payload=original,
        inicio=0,
        fim=6,
        linha_inicial=1,
        linha_final=1,
        ordem=0,
    )
    segunda = _entrada(
        entrada_id="entrada-sintetica-b",
        token="<ARQUIVO_1>",
        payload=original,
        inicio=6,
        fim=len(original),
        linha_inicial=2,
        linha_final=2,
        ordem=1,
    )

    status_anterior = caminho.stat()
    if alteracao == "identidade":
        substituta = tmp_path / "substituta.log"
        substituta.write_bytes(original)
        os.utime(
            substituta,
            ns=(status_anterior.st_atime_ns, fingerprint.mtime_ns),
        )
        os.replace(substituta, caminho)
        if caminho.stat().st_ino == fingerprint.inode:
            pytest.skip("Sistema de arquivos não expôs nova identidade.")
    elif alteracao == "tamanho":
        caminho.write_bytes(original + b"X")
    elif alteracao == "mtime":
        os.utime(
            caminho,
            ns=(status_anterior.st_atime_ns, fingerprint.mtime_ns + 1_000_000_000),
        )
    else:
        caminho.write_bytes(b"SYN_A\nMUT_B\n")
        os.utime(
            caminho,
            ns=(status_anterior.st_atime_ns, fingerprint.mtime_ns),
        )
        assert caminho.stat().st_size == fingerprint.tamanho_bytes
        assert caminho.stat().st_mtime_ns == fingerprint.mtime_ns

    resultado = MaterializadorSeletivo(
        (_fonte(caminho, "<ARQUIVO_1>", fingerprint),)
    ).materializar((primeira, segunda))

    assert resultado.entradas == ()
    assert len(resultado.falhas) == 1
    falha = resultado.falhas[0]
    assert isinstance(falha, ErroDeIntegridadeDaFonte)
    assert falha.contexto == {
        "codigo": "SOURCE_CHANGED",
        "arquivo_token": "<ARQUIVO_1>",
    }
    assert str(caminho) not in str(falha)
    assert "SYN_A" not in repr(resultado)
    assert "MUT_B" not in repr(resultado)


def test_source_changed_preserva_outras_fontes_sem_combinar_versoes(
    tmp_path: Path,
) -> None:
    caminho_alterado = tmp_path / "alterado.log"
    caminho_valido = tmp_path / "valido.log"
    caminho_alterado.write_bytes(b"OLD_A\nOLD_B\n")
    caminho_valido.write_bytes("válido\r\n".encode("utf-8"))
    fingerprint_alterado, payload_alterado = _primeiro_passe(
        caminho_alterado, "<ARQUIVO_1>"
    )
    fingerprint_valido, payload_valido = _primeiro_passe(
        caminho_valido, "<ARQUIVO_2>"
    )
    entradas = (
        _entrada(
            entrada_id="alterada-a",
            token="<ARQUIVO_1>",
            payload=payload_alterado,
            inicio=0,
            fim=6,
            linha_inicial=1,
            linha_final=1,
            ordem=0,
        ),
        _entrada(
            entrada_id="alterada-b",
            token="<ARQUIVO_1>",
            payload=payload_alterado,
            inicio=6,
            fim=len(payload_alterado),
            linha_inicial=2,
            linha_final=2,
            ordem=1,
        ),
        _entrada(
            entrada_id="valida",
            token="<ARQUIVO_2>",
            payload=payload_valido,
            inicio=0,
            fim=len(payload_valido),
            linha_inicial=1,
            linha_final=1,
            ordem=2,
        ),
    )

    status = caminho_alterado.stat()
    caminho_alterado.write_bytes(b"OLD_A\nNEW_B\n")
    os.utime(
        caminho_alterado,
        ns=(status.st_atime_ns, fingerprint_alterado.mtime_ns),
    )

    resultado = MaterializadorSeletivo(
        (
            _fonte(caminho_alterado, "<ARQUIVO_1>", fingerprint_alterado),
            _fonte(caminho_valido, "<ARQUIVO_2>", fingerprint_valido),
        )
    ).materializar(entradas)

    assert [(entrada.entrada_id, entrada.texto_original) for entrada in resultado.entradas] == [
        ("valida", "válido\r\n")
    ]
    assert len(resultado.falhas) == 1
    assert resultado.falhas[0].codigo == "SOURCE_CHANGED"
    assert resultado.falhas[0].arquivo_token == "<ARQUIVO_1>"


def test_utf8_invalido_e_suprimido_sem_eliminar_intervalo_valido(
    tmp_path: Path,
) -> None:
    payload = b"SYN_BAD\xff\nSYN_OK\r\n"
    caminho = tmp_path / "utf8-invalido.log"
    caminho.write_bytes(payload)
    fingerprint, original = _primeiro_passe(caminho, "<ARQUIVO_4>")
    limite = original.index(b"SYN_OK")
    invalida = _entrada(
        entrada_id="entrada-invalida",
        token="<ARQUIVO_4>",
        payload=original,
        inicio=0,
        fim=limite,
        linha_inicial=1,
        linha_final=1,
        ordem=0,
    )
    valida = _entrada(
        entrada_id="entrada-valida",
        token="<ARQUIVO_4>",
        payload=original,
        inicio=limite,
        fim=len(original),
        linha_inicial=2,
        linha_final=2,
        ordem=1,
    )

    resultado = MaterializadorSeletivo(
        (_fonte(caminho, "<ARQUIVO_4>", fingerprint),)
    ).materializar((invalida, valida))

    assert [(item.entrada_id, item.texto_original) for item in resultado.entradas] == [
        ("entrada-valida", "SYN_OK\r\n")
    ]
    assert len(resultado.falhas) == 1
    falha = resultado.falhas[0]
    assert isinstance(falha, ErroDeDecodificacao)
    assert falha.contexto == {
        "codigo": "INVALID_UTF8",
        "arquivo_token": "<ARQUIVO_4>",
        "posicao": payload.index(b"\xff"),
    }
    assert repr(b"SYN_BAD\xff") not in repr(resultado)


def _criar_indice_em_disco(tmp_path: Path) -> tuple[IndiceTemporario, Path]:
    indice = IndiceTemporario(
        limiar_memoria=0,
        tamanho_lote=2,
        diretorio_temporario=tmp_path,
    )
    indice.adicionar_entrada(
        entrada_id="entrada-indice",
        arquivo_token="<ARQUIVO_1>",
        aplicacao_codigo="VPL",
        ordem_de_leitura=0,
        inicio_byte=0,
        fim_byte=1,
        linha_inicial=1,
        linha_final=1,
    )
    caminho_indice = indice.caminho_temporario
    assert caminho_indice is not None and caminho_indice.exists()
    return indice, caminho_indice


def test_materializacao_fecha_indice_em_sucesso_e_excecao(tmp_path: Path) -> None:
    payload = b"SYN_OK\n"
    fonte_path = tmp_path / "fonte-limpeza.log"
    fonte_path.write_bytes(payload)
    fingerprint, original = _primeiro_passe(fonte_path, "<ARQUIVO_1>")
    entrada = _entrada(
        entrada_id="entrada-limpeza",
        token="<ARQUIVO_1>",
        payload=original,
        inicio=0,
        fim=len(original),
        linha_inicial=1,
        linha_final=1,
        ordem=0,
    )
    fonte = _fonte(fonte_path, "<ARQUIVO_1>", fingerprint)

    indice_sucesso, caminho_sucesso = _criar_indice_em_disco(tmp_path)
    resultado = materializar_selecao(
        (entrada,),
        (fonte,),
        indice_temporario=indice_sucesso,
    )
    assert [item.texto_original for item in resultado.entradas] == ["SYN_OK\n"]
    assert indice_sucesso.fechado
    assert not caminho_sucesso.exists()

    indice_excecao, caminho_excecao = _criar_indice_em_disco(tmp_path)

    def entradas_com_falha():
        yield entrada
        raise RuntimeError("falha sintética controlada")

    with pytest.raises(RuntimeError, match="falha sintética controlada"):
        materializar_selecao(
            entradas_com_falha(),
            (fonte,),
            indice_temporario=indice_excecao,
        )

    assert indice_excecao.fechado
    assert not caminho_excecao.exists()
    assert not tuple(tmp_path.glob(".log-analyzer-index-*"))
