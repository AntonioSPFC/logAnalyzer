"""Testes técnicos de integridade e limpeza sob carga.

Cenários cobertos:
- Alteração concorrente da fonte entre primeiro e segundo passes (SOURCE_CHANGED).
- Falha simulada de disco/índice via monkeypatch.
- Permissões insuficientes no diretório de temporários.
- Remoção garantida de temporários em sucesso e exceção (sem fallback para RAM irrestrita).

Todos os arquivos e dados são sintéticos, criados em ``tmp_path``.

Validates: Requirements 14.7, 15.1, 15.6, 15.8.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
from unittest.mock import patch

import pytest

from log_analyzer.core.excecoes import ErroDeIntegridadeDaFonte
from log_analyzer.core.indice import IndiceTemporario
from log_analyzer.core.materializacao import (
    FonteMaterializacao,
    MaterializadorSeletivo,
    ResultadoMaterializacao,
    materializar_selecao,
)
from log_analyzer.core.modelos import EntradaIndexada, ReferenciaTextoOriginal
from log_analyzer.core.streaming import FingerprintArquivo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _criar_fonte_e_entrada(
    tmp_path: Path,
    conteudo: bytes,
    *,
    arquivo_token: str = "<ARQUIVO_1>",
    entrada_id: str = "entrada-001",
) -> tuple[Path, FonteMaterializacao, EntradaIndexada]:
    """Cria um arquivo sintético e os objetos associados para materialização."""

    caminho = tmp_path / "fonte.log"
    caminho.write_bytes(conteudo)
    st = os.stat(caminho)

    fingerprint = FingerprintArquivo(
        dispositivo=st.st_dev,
        inode=st.st_ino,
        tamanho_bytes=st.st_size,
        mtime_ns=st.st_mtime_ns,
        sha256=hashlib.sha256(conteudo).hexdigest(),
    )
    fonte = FonteMaterializacao(
        arquivo_token=arquivo_token,
        caminho=caminho,
        fingerprint=fingerprint,
    )
    entrada = EntradaIndexada(
        entrada_id=entrada_id,
        aplicacao="VPL",
        ordem_de_leitura=0,
        texto_ref=ReferenciaTextoOriginal(
            arquivo_token=arquivo_token,
            inicio_byte=0,
            fim_byte=len(conteudo),
            linha_inicial=1,
            linha_final=1,
            sha256=hashlib.sha256(conteudo).hexdigest(),
        ),
        cabecalho=(),
        identificadores_digest=(),
        timestamp_original=None,
        timestamp_normalizado=None,
        falhas=(),
        interpretada=False,
    )
    return caminho, fonte, entrada


# ---------------------------------------------------------------------------
# Testes de alteração concorrente da fonte (SOURCE_CHANGED)
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestAlteracaoConcorrenteDaFonte:
    """Verifica detecção de SOURCE_CHANGED quando a fonte muda entre passes."""

    def test_conteudo_alterado_entre_passes_produz_source_changed(
        self, tmp_path: Path
    ) -> None:
        """Altera o conteúdo do arquivo após criar o fingerprint."""

        conteudo_original = b"linha original do log\n" * 50
        caminho, fonte, entrada = _criar_fonte_e_entrada(
            tmp_path, conteudo_original
        )

        # Simula alteração concorrente: conteúdo diferente, mesmo tamanho
        conteudo_alterado = b"linha ALTERADA no log\n" * 50
        caminho.write_bytes(conteudo_alterado)

        mat = MaterializadorSeletivo([fonte])
        resultado = mat.materializar([entrada])

        assert len(resultado.falhas) == 1
        assert isinstance(resultado.falhas[0], ErroDeIntegridadeDaFonte)
        assert resultado.falhas[0].codigo == "SOURCE_CHANGED"
        assert len(resultado.entradas) == 0

    def test_tamanho_alterado_entre_passes_produz_source_changed(
        self, tmp_path: Path
    ) -> None:
        """Altera o tamanho do arquivo entre o primeiro e segundo passe."""

        conteudo_original = b"dados curtos\n"
        caminho, fonte, entrada = _criar_fonte_e_entrada(
            tmp_path, conteudo_original
        )

        # Altera para conteúdo maior
        caminho.write_bytes(b"dados muito maiores agora\n" * 100)

        mat = MaterializadorSeletivo([fonte])
        resultado = mat.materializar([entrada])

        assert len(resultado.falhas) == 1
        assert isinstance(resultado.falhas[0], ErroDeIntegridadeDaFonte)
        assert resultado.falhas[0].codigo == "SOURCE_CHANGED"

    def test_fonte_removida_entre_passes_produz_source_changed(
        self, tmp_path: Path
    ) -> None:
        """Remove a fonte fisicamente antes do segundo passe."""

        conteudo_original = b"conteudo efemero\n"
        caminho, fonte, entrada = _criar_fonte_e_entrada(
            tmp_path, conteudo_original
        )
        caminho.unlink()

        mat = MaterializadorSeletivo([fonte])
        resultado = mat.materializar([entrada])

        assert len(resultado.falhas) == 1
        assert isinstance(resultado.falhas[0], ErroDeIntegridadeDaFonte)

    def test_multiplas_fontes_isolam_falha_de_uma_sem_afetar_outras(
        self, tmp_path: Path
    ) -> None:
        """Se uma fonte foi alterada, as demais ainda materializam normalmente."""

        conteudo_a = b"fonte A intacta\n"
        conteudo_b = b"fonte B alterada\n"

        caminho_a = tmp_path / "fonte_a.log"
        caminho_a.write_bytes(conteudo_a)
        st_a = os.stat(caminho_a)

        caminho_b = tmp_path / "fonte_b.log"
        caminho_b.write_bytes(conteudo_b)
        st_b = os.stat(caminho_b)

        fp_a = FingerprintArquivo(
            dispositivo=st_a.st_dev,
            inode=st_a.st_ino,
            tamanho_bytes=st_a.st_size,
            mtime_ns=st_a.st_mtime_ns,
            sha256=hashlib.sha256(conteudo_a).hexdigest(),
        )
        fp_b = FingerprintArquivo(
            dispositivo=st_b.st_dev,
            inode=st_b.st_ino,
            tamanho_bytes=st_b.st_size,
            mtime_ns=st_b.st_mtime_ns,
            sha256=hashlib.sha256(conteudo_b).hexdigest(),
        )

        fonte_a = FonteMaterializacao(
            arquivo_token="<ARQUIVO_1>", caminho=caminho_a, fingerprint=fp_a
        )
        fonte_b = FonteMaterializacao(
            arquivo_token="<ARQUIVO_2>", caminho=caminho_b, fingerprint=fp_b
        )

        entrada_a = EntradaIndexada(
            entrada_id="ea-001",
            aplicacao="VPL",
            ordem_de_leitura=0,
            texto_ref=ReferenciaTextoOriginal(
                arquivo_token="<ARQUIVO_1>",
                inicio_byte=0,
                fim_byte=len(conteudo_a),
                linha_inicial=1,
                linha_final=1,
                sha256=hashlib.sha256(conteudo_a).hexdigest(),
            ),
            cabecalho=(),
            identificadores_digest=(),
            timestamp_original=None,
            timestamp_normalizado=None,
            falhas=(),
            interpretada=False,
        )
        entrada_b = EntradaIndexada(
            entrada_id="eb-001",
            aplicacao="ORK",
            ordem_de_leitura=1,
            texto_ref=ReferenciaTextoOriginal(
                arquivo_token="<ARQUIVO_2>",
                inicio_byte=0,
                fim_byte=len(conteudo_b),
                linha_inicial=1,
                linha_final=1,
                sha256=hashlib.sha256(conteudo_b).hexdigest(),
            ),
            cabecalho=(),
            identificadores_digest=(),
            timestamp_original=None,
            timestamp_normalizado=None,
            falhas=(),
            interpretada=False,
        )

        # Altera apenas fonte_b
        caminho_b.write_bytes(b"substituida totalmente\n")

        mat = MaterializadorSeletivo([fonte_a, fonte_b])
        resultado = mat.materializar([entrada_a, entrada_b])

        # Fonte A materializa com sucesso
        assert len(resultado.entradas) == 1
        assert resultado.entradas[0].entrada_id == "ea-001"
        # Fonte B falha com SOURCE_CHANGED
        assert len(resultado.falhas) == 1
        assert isinstance(resultado.falhas[0], ErroDeIntegridadeDaFonte)


# ---------------------------------------------------------------------------
# Testes de falha de disco/índice simulada
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestFalhaDeDisco:
    """Simula falhas de I/O no índice temporário via mock/monkeypatch."""

    def test_falha_ao_criar_sqlite_temporario_propaga_excecao(
        self, tmp_path: Path
    ) -> None:
        """Falha de disco ao criar o arquivo SQLite impede o spill."""

        def _mkstemp_falha(*args, **kwargs):
            raise OSError("Disco cheio simulado")

        with patch("tempfile.mkstemp", side_effect=_mkstemp_falha):
            indice = IndiceTemporario(
                limiar_memoria=1,
                diretorio_temporario=tmp_path,
            )
            with pytest.raises(OSError, match="Disco cheio simulado"):
                indice.adicionar_entrada(
                    entrada_id="e-001",
                    arquivo_token="<ARQUIVO_1>",
                    aplicacao_codigo="VPL",
                    ordem_de_leitura=0,
                    inicio_byte=0,
                    fim_byte=10,
                    linha_inicial=1,
                    linha_final=1,
                )
                # Adicionar segunda entrada para ultrapassar limiar e forçar spill
                indice.adicionar_entrada(
                    entrada_id="e-002",
                    arquivo_token="<ARQUIVO_1>",
                    aplicacao_codigo="VPL",
                    ordem_de_leitura=1,
                    inicio_byte=10,
                    fim_byte=20,
                    linha_inicial=2,
                    linha_final=2,
                )

    def test_falha_de_escrita_sqlite_limpa_arquivo_temporario(
        self, tmp_path: Path
    ) -> None:
        """Se o SQLite falha ao escrever, os temporários não ficam no disco."""

        indice = IndiceTemporario(
            limiar_memoria=1,
            diretorio_temporario=tmp_path,
        )
        # Primeira entrada fica em memória
        indice.adicionar_entrada(
            entrada_id="e-001",
            arquivo_token="<ARQUIVO_1>",
            aplicacao_codigo="VPL",
            ordem_de_leitura=0,
            inicio_byte=0,
            fim_byte=10,
            linha_inicial=1,
            linha_final=1,
        )

        # Simula falha na transação de escrita durante o spill.
        # Patching _executar_transacao no nível da instância não é viável
        # porque a conexão SQLite é read-only. Usamos patch no método da classe.
        original_executar = IndiceTemporario._executar_transacao

        def _executar_falha(self_indice, registros):
            raise sqlite3.OperationalError("Falha de I/O simulada")

        with patch.object(
            IndiceTemporario,
            "_executar_transacao",
            _executar_falha,
        ):
            with pytest.raises(sqlite3.OperationalError):
                indice.adicionar_entrada(
                    entrada_id="e-002",
                    arquivo_token="<ARQUIVO_1>",
                    aplicacao_codigo="VPL",
                    ordem_de_leitura=1,
                    inicio_byte=10,
                    fim_byte=20,
                    linha_inicial=2,
                    linha_final=2,
                )

        # Verifica que nenhum SQLite permanece no diretório temporário
        arquivos_restantes = list(tmp_path.glob("*.sqlite3*"))
        assert arquivos_restantes == []

    def test_indice_em_disco_permite_close_apos_falha(
        self, tmp_path: Path
    ) -> None:
        """O close() do índice não propaga exceção mesmo se operações falharam."""

        indice = IndiceTemporario(
            limiar_memoria=2,
            diretorio_temporario=tmp_path,
        )
        indice.adicionar_entrada(
            entrada_id="e-001",
            arquivo_token="<ARQUIVO_1>",
            aplicacao_codigo="VPL",
            ordem_de_leitura=0,
            inicio_byte=0,
            fim_byte=10,
            linha_inicial=1,
            linha_final=1,
        )
        indice.adicionar_entrada(
            entrada_id="e-002",
            arquivo_token="<ARQUIVO_1>",
            aplicacao_codigo="VPL",
            ordem_de_leitura=1,
            inicio_byte=10,
            fim_byte=20,
            linha_inicial=2,
            linha_final=2,
        )
        indice.adicionar_entrada(
            entrada_id="e-003",
            arquivo_token="<ARQUIVO_1>",
            aplicacao_codigo="VPL",
            ordem_de_leitura=2,
            inicio_byte=20,
            fim_byte=30,
            linha_inicial=3,
            linha_final=3,
        )

        assert indice.em_disco
        caminho_sqlite = indice.caminho_temporario
        assert caminho_sqlite is not None and caminho_sqlite.exists()

        # close() remove o arquivo e não propaga
        indice.close()
        assert indice.fechado
        assert not caminho_sqlite.exists()


# ---------------------------------------------------------------------------
# Testes de permissões insuficientes no diretório de temporários
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestPermissoesInsuficientes:
    """Verifica comportamento quando o diretório de temporários é inacessível."""

    @pytest.mark.skipif(
        os.name == "nt",
        reason="Restrição de permissão POSIX não aplicável ao Windows",
    )
    def test_diretorio_somente_leitura_impede_spill(
        self, tmp_path: Path
    ) -> None:
        """Sem escrita no diretório, o spill para SQLite falha adequadamente."""

        dir_restrito = tmp_path / "somente_leitura"
        dir_restrito.mkdir()
        dir_restrito.chmod(stat.S_IRUSR | stat.S_IXUSR)  # r-x------

        try:
            indice = IndiceTemporario(
                limiar_memoria=1,
                diretorio_temporario=dir_restrito,
            )
            indice.adicionar_entrada(
                entrada_id="e-001",
                arquivo_token="<ARQUIVO_1>",
                aplicacao_codigo="VPL",
                ordem_de_leitura=0,
                inicio_byte=0,
                fim_byte=10,
                linha_inicial=1,
                linha_final=1,
            )

            with pytest.raises((OSError, PermissionError)):
                indice.adicionar_entrada(
                    entrada_id="e-002",
                    arquivo_token="<ARQUIVO_1>",
                    aplicacao_codigo="VPL",
                    ordem_de_leitura=1,
                    inicio_byte=10,
                    fim_byte=20,
                    linha_inicial=2,
                    linha_final=2,
                )
        finally:
            dir_restrito.chmod(stat.S_IRWXU)

    def test_mkstemp_falha_por_permissao_no_monkeypatch(
        self, tmp_path: Path
    ) -> None:
        """Monkeypatch simula PermissionError no mkstemp em qualquer OS."""

        def _mkstemp_sem_permissao(*args, **kwargs):
            raise PermissionError("Permissão negada no diretório de temporários")

        indice = IndiceTemporario(
            limiar_memoria=1,
            diretorio_temporario=tmp_path,
        )
        indice.adicionar_entrada(
            entrada_id="e-001",
            arquivo_token="<ARQUIVO_1>",
            aplicacao_codigo="VPL",
            ordem_de_leitura=0,
            inicio_byte=0,
            fim_byte=10,
            linha_inicial=1,
            linha_final=1,
        )

        with patch("tempfile.mkstemp", side_effect=_mkstemp_sem_permissao):
            with pytest.raises(PermissionError, match="Permissão negada"):
                indice.adicionar_entrada(
                    entrada_id="e-002",
                    arquivo_token="<ARQUIVO_1>",
                    aplicacao_codigo="VPL",
                    ordem_de_leitura=1,
                    inicio_byte=10,
                    fim_byte=20,
                    linha_inicial=2,
                    linha_final=2,
                )


# ---------------------------------------------------------------------------
# Testes de remoção garantida de temporários (sucesso e exceção)
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestRemocaoGarantidaDeTemporarios:
    """Verifica que temporários são removidos em todos os caminhos de saída."""

    def test_indice_com_context_manager_remove_temporarios_em_sucesso(
        self, tmp_path: Path
    ) -> None:
        """O context manager garante remoção em fluxo normal."""

        with IndiceTemporario(
            limiar_memoria=1,
            diretorio_temporario=tmp_path,
        ) as indice:
            indice.adicionar_entrada(
                entrada_id="e-001",
                arquivo_token="<ARQUIVO_1>",
                aplicacao_codigo="VPL",
                ordem_de_leitura=0,
                inicio_byte=0,
                fim_byte=10,
                linha_inicial=1,
                linha_final=1,
            )
            indice.adicionar_entrada(
                entrada_id="e-002",
                arquivo_token="<ARQUIVO_1>",
                aplicacao_codigo="VPL",
                ordem_de_leitura=1,
                inicio_byte=10,
                fim_byte=20,
                linha_inicial=2,
                linha_final=2,
            )
            assert indice.em_disco
            caminho = indice.caminho_temporario
            assert caminho is not None and caminho.exists()

        # Após sair do with, temporários devem ter sido removidos
        assert not caminho.exists()
        assert indice.fechado

    def test_indice_com_context_manager_remove_temporarios_em_excecao(
        self, tmp_path: Path
    ) -> None:
        """O context manager garante remoção mesmo quando há exceção."""

        caminho_capturado: Path | None = None

        with pytest.raises(RuntimeError, match="Falha forçada"):
            with IndiceTemporario(
                limiar_memoria=1,
                diretorio_temporario=tmp_path,
            ) as indice:
                indice.adicionar_entrada(
                    entrada_id="e-001",
                    arquivo_token="<ARQUIVO_1>",
                    aplicacao_codigo="VPL",
                    ordem_de_leitura=0,
                    inicio_byte=0,
                    fim_byte=10,
                    linha_inicial=1,
                    linha_final=1,
                )
                indice.adicionar_entrada(
                    entrada_id="e-002",
                    arquivo_token="<ARQUIVO_1>",
                    aplicacao_codigo="VPL",
                    ordem_de_leitura=1,
                    inicio_byte=10,
                    fim_byte=20,
                    linha_inicial=2,
                    linha_final=2,
                )
                assert indice.em_disco
                caminho_capturado = indice.caminho_temporario
                assert caminho_capturado is not None
                raise RuntimeError("Falha forçada no processamento")

        assert caminho_capturado is not None
        assert not caminho_capturado.exists()

    def test_materializar_selecao_fecha_indice_em_sucesso(
        self, tmp_path: Path
    ) -> None:
        """``materializar_selecao`` chama close() do índice em finally."""

        conteudo = b"dados de teste\n"
        _, fonte, entrada = _criar_fonte_e_entrada(tmp_path, conteudo)

        indice = IndiceTemporario(
            limiar_memoria=1,
            diretorio_temporario=tmp_path,
        )
        indice.adicionar_entrada(
            entrada_id="entrada-001",
            arquivo_token="<ARQUIVO_1>",
            aplicacao_codigo="VPL",
            ordem_de_leitura=0,
            inicio_byte=0,
            fim_byte=len(conteudo),
            linha_inicial=1,
            linha_final=1,
        )
        indice.adicionar_entrada(
            entrada_id="entrada-002",
            arquivo_token="<ARQUIVO_1>",
            aplicacao_codigo="VPL",
            ordem_de_leitura=1,
            inicio_byte=0,
            fim_byte=len(conteudo),
            linha_inicial=1,
            linha_final=1,
        )
        assert indice.em_disco

        resultado = materializar_selecao(
            [entrada],
            [fonte],
            indice_temporario=indice,
        )

        assert indice.fechado
        assert len(resultado.entradas) == 1

    def test_materializar_selecao_fecha_indice_em_excecao(
        self, tmp_path: Path
    ) -> None:
        """``materializar_selecao`` chama close() mesmo diante de exceção."""

        conteudo = b"arquivo valido\n"
        _, fonte, entrada = _criar_fonte_e_entrada(tmp_path, conteudo)

        indice = IndiceTemporario(
            limiar_memoria=1,
            diretorio_temporario=tmp_path,
        )
        indice.adicionar_entrada(
            entrada_id="entrada-001",
            arquivo_token="<ARQUIVO_1>",
            aplicacao_codigo="VPL",
            ordem_de_leitura=0,
            inicio_byte=0,
            fim_byte=len(conteudo),
            linha_inicial=1,
            linha_final=1,
        )
        indice.adicionar_entrada(
            entrada_id="entrada-002",
            arquivo_token="<ARQUIVO_1>",
            aplicacao_codigo="VPL",
            ordem_de_leitura=1,
            inicio_byte=0,
            fim_byte=len(conteudo),
            linha_inicial=1,
            linha_final=1,
        )

        # Fornece fonte inválida (iterável que causa TypeError internamente)
        with pytest.raises(TypeError):
            materializar_selecao(
                [entrada],
                "fonte-invalida",  # type: ignore[arg-type]
                indice_temporario=indice,
            )

        # Índice foi fechado pelo finally
        assert indice.fechado

    def test_nenhum_fallback_para_ram_irrestrita_apos_falha_de_spill(
        self, tmp_path: Path
    ) -> None:
        """Quando o spill falha, NÃO há fallback para crescer em memória."""

        def _mkstemp_falha(*args, **kwargs):
            raise OSError("Disco indisponível")

        indice = IndiceTemporario(
            limiar_memoria=1,
            diretorio_temporario=tmp_path,
        )
        # Primeira entrada em memória (dentro do limiar)
        indice.adicionar_entrada(
            entrada_id="e-001",
            arquivo_token="<ARQUIVO_1>",
            aplicacao_codigo="VPL",
            ordem_de_leitura=0,
            inicio_byte=0,
            fim_byte=10,
            linha_inicial=1,
            linha_final=1,
        )

        with patch("tempfile.mkstemp", side_effect=_mkstemp_falha):
            # Ultrapassar limiar tenta spill -> falha -> exceção propagada
            with pytest.raises(OSError, match="Disco indisponível"):
                indice.adicionar_entrada(
                    entrada_id="e-002",
                    arquivo_token="<ARQUIVO_1>",
                    aplicacao_codigo="VPL",
                    ordem_de_leitura=1,
                    inicio_byte=10,
                    fim_byte=20,
                    linha_inicial=2,
                    linha_final=2,
                )

        # Confirma que não houve crescimento silencioso em memória
        # O índice não deve ter a entrada e-002
        assert indice.quantidade_registros == 1

    def test_diretorio_temporario_limpo_apos_multiplas_entradas(
        self, tmp_path: Path
    ) -> None:
        """Verificação de que nenhum arquivo permanece após close com carga."""

        dir_temp = tmp_path / "temp_dir"
        dir_temp.mkdir()

        indice = IndiceTemporario(
            limiar_memoria=5,
            diretorio_temporario=dir_temp,
        )

        # Força spill com muitas entradas
        for i in range(20):
            indice.adicionar_entrada(
                entrada_id=f"e-{i:04d}",
                arquivo_token="<ARQUIVO_1>",
                aplicacao_codigo="VPL",
                ordem_de_leitura=i,
                inicio_byte=i * 100,
                fim_byte=(i + 1) * 100,
                linha_inicial=i + 1,
                linha_final=i + 1,
            )

        assert indice.em_disco
        assert indice.quantidade_registros == 20

        indice.close()

        # Nenhum arquivo restante no diretório temporário
        arquivos_restantes = list(dir_temp.iterdir())
        assert arquivos_restantes == []
