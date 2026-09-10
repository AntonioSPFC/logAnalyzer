"""Testes focados do índice temporário seguro da Fase 2.

Todos os valores são sintéticos e os arquivos SQLite vivem apenas em ``tmp_path``.

Validates: Requirements 5.1, 7.1, 7.6, 14.1, 15.8.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import stat

import pytest

from log_analyzer.core.indice import IndiceTemporario


_INSTANTE = datetime(2032, 4, 5, 6, 7, 8, 9000, tzinfo=timezone.utc)
_VALOR_CHAMADA = "identificador-sintético-α-001"
_VALOR_SESSAO = "sessão-sintética-β-002"


def _adicionar_entrada(
    indice: IndiceTemporario,
    *,
    entrada_id: str = "entrada-sintetica-1",
    arquivo_token: str = "<ARQUIVO_1>",
    ordem: int = 0,
    codigos: tuple[str, ...] = (),
) -> None:
    indice.adicionar_entrada(
        entrada_id=entrada_id,
        arquivo_token=arquivo_token,
        aplicacao_codigo="VPL",
        ordem_de_leitura=ordem,
        inicio_byte=10 * ordem,
        fim_byte=10 * ordem + 9,
        linha_inicial=ordem + 1,
        linha_final=ordem + 1,
        timestamp_normalizado=_INSTANTE,
        codigos=codigos,
    )


def test_backend_em_memoria_usa_hmac_efemero_separado_por_namespace() -> None:
    with IndiceTemporario(limiar_memoria=20) as primeiro:
        _adicionar_entrada(primeiro, codigos=("PARSE_OK",))
        _adicionar_entrada(
            primeiro,
            entrada_id="entrada-sintetica-2",
            arquivo_token="<ARQUIVO_2>",
            ordem=1,
        )

        chamada = primeiro.indexar_identificador(
            entrada_id="entrada-sintetica-1",
            namespace="chamada_externa",
            valor_normalizado=_VALOR_CHAMADA,
        )
        sessao = primeiro.indexar_identificador(
            entrada_id="entrada-sintetica-1",
            namespace="sessao",
            valor_normalizado=_VALOR_CHAMADA,
        )
        primeiro.indexar_identificador(
            entrada_id="entrada-sintetica-2",
            namespace="chamada_externa",
            valor_normalizado=_VALOR_CHAMADA,
        )

        assert not primeiro.em_disco
        assert primeiro.caminho_temporario is None
        assert len(chamada.hmac_sha256) == 64
        assert chamada.hmac_sha256 != sessao.hmac_sha256
        assert chamada.hmac_sha256 == primeiro.calcular_hmac(
            "chamada_externa", _VALOR_CHAMADA
        )
        assert primeiro.buscar_identificador(
            "chamada_externa", _VALOR_CHAMADA
        ) == ("entrada-sintetica-1", "entrada-sintetica-2")
        assert primeiro.buscar_identificador("sessao", _VALOR_CHAMADA) == (
            "entrada-sintetica-1",
        )
        assert primeiro.codigos_da_entrada("entrada-sintetica-1") == (
            "PARSE_OK",
        )
        assert _VALOR_CHAMADA not in repr(tuple(primeiro.iterar_identificadores()))
        digest_primeira_analise = chamada.hmac_sha256

    with IndiceTemporario() as segunda:
        digest_segunda_analise = segunda.calcular_hmac(
            "chamada_externa", _VALOR_CHAMADA
        )

    assert digest_primeira_analise != digest_segunda_analise


def test_spill_sqlite_usa_lotes_e_nao_persiste_conteudo_reversivel(
    tmp_path: Path,
) -> None:
    texto_que_nao_deve_existir = "mensagem sintética confidencial de teste"
    caminho_de_origem_que_nao_deve_existir = (
        "C:/fontes-sinteticas/arquivo-confidencial.txt"
    )

    with IndiceTemporario(
        limiar_memoria=1,
        tamanho_lote=3,
        diretorio_temporario=tmp_path,
    ) as indice:
        _adicionar_entrada(indice)
        assert not indice.em_disco

        identificador = indice.indexar_identificador(
            entrada_id="entrada-sintetica-1",
            namespace="chamada_externa",
            valor_normalizado=_VALOR_CHAMADA,
        )
        indice.adicionar_codigo(
            entrada_id="entrada-sintetica-1", codigo="IDENTIFIER_FOUND"
        )

        assert indice.em_disco
        caminho_sqlite = indice.caminho_temporario
        assert caminho_sqlite is not None and caminho_sqlite.exists()

        # Os dois registros posteriores ao spill ainda estão no lote pendente.
        with closing(sqlite3.connect(caminho_sqlite)) as leitura_antes_do_lote:
            assert leitura_antes_do_lote.execute(
                "SELECT COUNT(*) FROM entradas"
            ).fetchone() == (1,)
            assert leitura_antes_do_lote.execute(
                "SELECT COUNT(*) FROM identificadores"
            ).fetchone() == (0,)
            assert leitura_antes_do_lote.execute(
                "SELECT COUNT(*) FROM codigos"
            ).fetchone() == (0,)

        aresta = indice.adicionar_aresta(
            origem_namespace="chamada_externa",
            origem_valor_normalizado=_VALOR_CHAMADA,
            destino_namespace="sessao",
            destino_valor_normalizado=_VALOR_SESSAO,
            relacao_codigo="mapeia_sessao",
            evidencia_entrada_id="entrada-sintetica-1",
        )
        # O terceiro registro confirma os três em uma única transação de lote.
        with closing(sqlite3.connect(caminho_sqlite)) as leitura_depois_do_lote:
            assert leitura_depois_do_lote.execute(
                "SELECT COUNT(*) FROM identificadores"
            ).fetchone() == (1,)
            assert leitura_depois_do_lote.execute(
                "SELECT COUNT(*) FROM codigos"
            ).fetchone() == (1,)
            assert leitura_depois_do_lote.execute(
                "SELECT COUNT(*) FROM arestas"
            ).fetchone() == (1,)
            digest_persistido = leitura_depois_do_lote.execute(
                "SELECT hex(hmac_sha256) FROM identificadores"
            ).fetchone()
            assert digest_persistido == (identificador.hmac_sha256.upper(),)

            tabelas = ("entradas", "identificadores", "codigos", "arestas")
            nomes_colunas = {
                str(coluna[1]).casefold()
                for tabela in tabelas
                for coluna in leitura_depois_do_lote.execute(
                    f"PRAGMA table_info({tabela})"
                )
            }
            assert not any(
                fragmento in nome
                for nome in nomes_colunas
                for fragmento in ("texto", "caminho", "path", "valor_original")
            )
            dump = "\n".join(leitura_depois_do_lote.iterdump())

        assert indice.buscar_identificador(
            "chamada_externa", _VALOR_CHAMADA
        ) == ("entrada-sintetica-1",)
        assert tuple(indice.iterar_arestas()) == (aresta,)
        assert _VALOR_CHAMADA not in dump
        assert _VALOR_SESSAO not in dump
        assert texto_que_nao_deve_existir not in dump
        assert caminho_de_origem_que_nao_deve_existir not in dump

        bytes_sqlite = caminho_sqlite.read_bytes()
        assert _VALOR_CHAMADA.encode("utf-8") not in bytes_sqlite
        assert _VALOR_SESSAO.encode("utf-8") not in bytes_sqlite
        assert texto_que_nao_deve_existir.encode("utf-8") not in bytes_sqlite
        assert caminho_de_origem_que_nao_deve_existir.encode("utf-8") not in bytes_sqlite

        if os.name == "posix":
            assert stat.S_IMODE(caminho_sqlite.stat().st_mode) == 0o600

    assert not caminho_sqlite.exists()
    assert not tuple(tmp_path.iterdir())


def test_close_e_context_manager_removem_spill_mesmo_em_excecao(
    tmp_path: Path,
) -> None:
    caminho_criado: Path | None = None

    with pytest.raises(RuntimeError, match="falha sintética controlada"):
        with IndiceTemporario(
            limiar_memoria=0,
            tamanho_lote=8,
            diretorio_temporario=tmp_path,
        ) as indice:
            _adicionar_entrada(indice)
            caminho_criado = indice.caminho_temporario
            assert caminho_criado is not None and caminho_criado.exists()
            raise RuntimeError("falha sintética controlada")

    assert caminho_criado is not None and not caminho_criado.exists()
    assert not tuple(tmp_path.iterdir())

    indice_fechado = IndiceTemporario()
    indice_fechado.close()
    indice_fechado.close()
    assert indice_fechado.fechado
    assert indice_fechado.caminho_temporario is None
    with pytest.raises(RuntimeError, match="fechado"):
        indice_fechado.calcular_hmac("chamada_externa", _VALOR_CHAMADA)


def test_metadado_com_aparencia_de_caminho_e_rejeitado_sem_eco() -> None:
    caminho_sintetico = "C:/fontes-sinteticas/segredo-de-teste.txt"

    with IndiceTemporario() as indice:
        with pytest.raises(ValueError) as exc_info:
            indice.adicionar_entrada(
                entrada_id="entrada-sintetica-1",
                arquivo_token=caminho_sintetico,
                aplicacao_codigo="VPL",
                ordem_de_leitura=0,
                inicio_byte=0,
                fim_byte=1,
                linha_inicial=1,
                linha_final=1,
            )

    assert caminho_sintetico not in str(exc_info.value)
