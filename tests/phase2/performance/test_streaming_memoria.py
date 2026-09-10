"""Testes slow de streaming e pico de memória.

Comprova que o pico de RAM do pipeline streaming acompanha
estado/índice/resultado, não os bytes totais dos arquivos de entrada.

Usa arquivos temporários reais para blocos pequenos/médios e doubles de stat
para simular o limite de 500 MB sem escrever todo o conteúdo em disco.
Nenhum dado gerado é versionado — tudo usa ``tmp_path``.

Validates: Requirements 15.8
"""

from __future__ import annotations

import gc
import os
import tracemalloc
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from log_analyzer.core.carregador import TAMANHO_MAXIMO_BYTES
from log_analyzer.core.streaming import LeitorStreaming


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _status_double(status_real: os.stat_result, tamanho: int) -> SimpleNamespace:
    """Double de stat que reporta ``st_size`` arbitrário sem alocar disco."""

    return SimpleNamespace(
        st_mode=status_real.st_mode,
        st_size=tamanho,
        st_dev=status_real.st_dev,
        st_ino=status_real.st_ino,
        st_mtime_ns=status_real.st_mtime_ns,
    )


def _gerar_bloco_grande(tmp_path: Path, tamanho_alvo: int = 1_048_576) -> Path:
    """Gera um arquivo com um único bloco de ~1 MB (cabeçalho + continuações)."""

    caminho = tmp_path / "bloco_grande.log"
    # Cabeçalho VPL sintético válido para o perfil legado
    cabecalho = "2024-01-15 10:00:00.000000 100% [DEBUG] origem Inicio do bloco\n"
    bytes_cabecalho = cabecalho.encode("utf-8")

    linhas_continuacao_necessarias = (tamanho_alvo - len(bytes_cabecalho)) // 80
    # Continuações sem cabeçalho (indented)
    continuacao = "    " + "X" * 75 + "\n"  # 80 bytes

    with open(caminho, "wb") as f:
        f.write(bytes_cabecalho)
        for _ in range(linhas_continuacao_necessarias):
            f.write(continuacao.encode("utf-8"))

    return caminho


def _gerar_muitos_blocos_pequenos(
    tmp_path: Path,
    quantidade: int = 10_000,
    tamanho_por_bloco: int = 50,
) -> Path:
    """Gera 10.000 blocos de ~50 bytes cada (entradas com cabeçalho)."""

    caminho = tmp_path / "blocos_pequenos.log"
    # Template: "2024-01-15 10:00:00.NNNNNN 100% [INFO] src MsgNN\n"
    # Variamos microsegundos para criar cabeçalhos distintos
    with open(caminho, "wb") as f:
        for i in range(quantidade):
            micro = f"{i:06d}"
            # Formato legado VPL com severidade delimitada
            linha = f"2024-01-15 10:00:00.{micro} 100% [INFO] src M{i:04d}\n"
            dados = linha.encode("utf-8")
            # Ajustar para ~50 bytes por bloco
            if len(dados) < tamanho_por_bloco:
                # Pad com espaço antes do \n
                pad = tamanho_por_bloco - len(dados)
                linha = linha[:-1] + " " * pad + "\n"
                dados = linha.encode("utf-8")
            f.write(dados[:tamanho_por_bloco])
            # Garantir newline no final
            if not dados[:tamanho_por_bloco].endswith(b"\n"):
                f.write(b"\n")

    return caminho


def _consumir_streaming(caminho: Path) -> tuple[int, int]:
    """Consome todas as linhas via LeitorStreaming e retorna (linhas, bytes).

    Não acumula o conteúdo — descarta cada LinhaFisica após contar.
    """

    leitor = LeitorStreaming(caminho, "<ARQUIVO_1>")
    total_linhas = 0
    total_bytes = 0
    for linha in leitor.iterar_linhas():
        total_linhas += 1
        total_bytes += linha.fim_byte - linha.inicio_byte
    return total_linhas, total_bytes


def _medir_pico_streaming(caminho: Path) -> tuple[int, int]:
    """Mede o pico de memória (tracemalloc) durante streaming completo.

    Retorna (pico_bytes, tamanho_arquivo_bytes).
    """

    gc.collect()
    tracemalloc.start()
    tracemalloc.reset_peak()

    leitor = LeitorStreaming(caminho, "<ARQUIVO_1>")
    for _ in leitor.iterar_linhas():
        pass  # Descarta cada linha — simula pipeline streaming

    _, pico = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    tamanho_arquivo = caminho.stat().st_size
    return pico, tamanho_arquivo


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestPreflightDouble500MB:
    """Preflight aceita arquivo com st_size=500 MB usando double de stat."""

    def test_preflight_aceita_500mb_via_double(self, tmp_path: Path) -> None:
        """O preflight valida st_size sem precisar de um arquivo real de 500 MB."""

        fonte = tmp_path / "double-500mb.log"
        fonte.write_bytes(b"conteudo minimo para double\n")

        status_real = fonte.stat()
        status_500mb = _status_double(status_real, TAMANHO_MAXIMO_BYTES)

        with (
            patch("log_analyzer.core.streaming.os.stat", return_value=status_500mb),
            patch("log_analyzer.core.streaming.os.fstat", return_value=status_500mb),
        ):
            leitor = LeitorStreaming(fonte, "<ARQUIVO_1>")
            assert leitor.fingerprint.tamanho_bytes == TAMANHO_MAXIMO_BYTES

    def test_preflight_rejeita_acima_500mb_via_double(self, tmp_path: Path) -> None:
        """O preflight rejeita st_size > 500 MB sem criar o arquivo."""

        from log_analyzer.core.excecoes import ErroDeArquivo

        fonte = tmp_path / "double-500mb-plus.log"
        fonte.write_bytes(b"conteudo minimo para double\n")

        status_real = fonte.stat()
        status_acima = _status_double(status_real, TAMANHO_MAXIMO_BYTES + 1)

        with (
            patch("log_analyzer.core.streaming.os.stat", return_value=status_acima),
            patch("log_analyzer.core.streaming.os.fstat", return_value=status_acima),
        ):
            with pytest.raises(ErroDeArquivo) as exc_info:
                LeitorStreaming(fonte, "<ARQUIVO_1>")
            assert exc_info.value.contexto["codigo"] == "FILE_TOO_LARGE"


@pytest.mark.slow
class TestStreamingBlocoGrandeMemoria:
    """O pico de RAM ao processar um bloco de ~1 MB é muito menor que 1 MB."""

    def test_pico_memoria_bloco_grande_proporcional_ao_estado(
        self, tmp_path: Path
    ) -> None:
        """Streaming de um bloco de 1 MB não retém 1 MB em RAM.

        O leitor processa linha a linha; o pico deve ser proporcional ao
        estado do iterador (buffers internos do Python), não ao total do
        arquivo.
        """

        caminho = _gerar_bloco_grande(tmp_path, tamanho_alvo=1_048_576)
        tamanho_real = caminho.stat().st_size
        assert tamanho_real >= 900_000, "Bloco grande deve ter ~1 MB"

        pico, tamanho_arquivo = _medir_pico_streaming(caminho)

        # O pico deve ser muito menor que o tamanho do arquivo.
        # Tolerância generosa: pico < 50% do tamanho do arquivo demonstra que
        # o streaming não materializa tudo de uma vez.
        # Na prática espera-se algo próximo de ~100-200 KB de overhead.
        fracao = pico / tamanho_arquivo
        assert fracao < 0.50, (
            f"Pico de RAM ({pico:,} bytes) é {fracao:.1%} do arquivo "
            f"({tamanho_arquivo:,} bytes) — deveria ser < 50%"
        )


@pytest.mark.slow
class TestStreamingMuitosBlocosPequenosMemoria:
    """O pico de RAM com 10.000 blocos pequenos (50 bytes) é sublinear."""

    def test_pico_memoria_muitos_blocos_pequenos_nao_acumula(
        self, tmp_path: Path
    ) -> None:
        """Streaming de 10.000 blocos de 50 bytes (~500 KB total) não retém
        todo o conteúdo em RAM.

        O pico deve ser proporcional ao estado do iterador, não ao total de
        bytes processados.
        """

        caminho = _gerar_muitos_blocos_pequenos(
            tmp_path, quantidade=10_000, tamanho_por_bloco=50
        )
        tamanho_real = caminho.stat().st_size
        assert tamanho_real >= 400_000, "Deve ter ~500 KB no total"

        pico, tamanho_arquivo = _medir_pico_streaming(caminho)

        # Com 10.000 blocos de 50 bytes, o total é ~500 KB.
        # O pico deve ser bem menor que os ~500 KB totais — streaming descarta
        # cada linha após processá-la.
        fracao = pico / tamanho_arquivo
        assert fracao < 0.50, (
            f"Pico de RAM ({pico:,} bytes) é {fracao:.1%} dos dados totais "
            f"({tamanho_arquivo:,} bytes) — deveria ser < 50%"
        )

    def test_pico_cresce_sublinearmente_com_volume(
        self, tmp_path: Path
    ) -> None:
        """Dobrar o volume de dados não dobra o pico de RAM.

        Isso demonstra que o crescimento de memória acompanha
        estado/estruturas internas e não bytes processados.
        """

        dir_base = tmp_path / "base"
        dir_base.mkdir()
        dir_dobro = tmp_path / "dobro"
        dir_dobro.mkdir()

        caminho_base = _gerar_muitos_blocos_pequenos(
            dir_base, quantidade=5_000, tamanho_por_bloco=50
        )
        caminho_dobro = _gerar_muitos_blocos_pequenos(
            dir_dobro, quantidade=10_000, tamanho_por_bloco=50
        )

        pico_base, tam_base = _medir_pico_streaming(caminho_base)
        pico_dobro, tam_dobro = _medir_pico_streaming(caminho_dobro)

        # O arquivo dobro tem ~2x os bytes; o pico não deve dobrar.
        # Tolerância: pico_dobro < 1.8 * pico_base (sublinear)
        assert pico_dobro < 1.8 * pico_base or pico_dobro < 262_144, (
            f"Pico não é sublinear: base={pico_base:,}, dobro={pico_dobro:,} "
            f"(ratio={pico_dobro / max(pico_base, 1):.2f})"
        )


@pytest.mark.slow
class TestStreamingDouble500MBNaoMaterializaConteudo:
    """Simula arquivo de 500 MB com double e confirma streaming com pouca RAM.

    Usa um arquivo real pequeno com st_size=500 MB no preflight e conteúdo
    real limitado na leitura — o que importa é que o leitor não tenta
    materializar os 500 MB anunciados.
    """

    def test_streaming_com_double_500mb_usa_ram_limitada(
        self, tmp_path: Path
    ) -> None:
        """Mesmo com preflight reportando 500 MB, o streaming do conteúdo
        real (pequeno) demonstra que não há alocação proporcional ao st_size.
        """

        # Gera conteúdo real modesto (~100 KB)
        fonte = tmp_path / "double-streaming-500mb.log"
        linhas_reais = 1000
        with open(fonte, "wb") as f:
            for i in range(linhas_reais):
                f.write(
                    f"2024-01-15 10:00:00.{i:06d} 100% [INFO] src L{i}\n"
                    .encode("utf-8")
                )

        tamanho_real = fonte.stat().st_size
        assert tamanho_real < 100_000, "Conteúdo real deve ser < 100 KB"

        status_real = fonte.stat()
        status_500mb = _status_double(status_real, TAMANHO_MAXIMO_BYTES)

        gc.collect()
        tracemalloc.start()
        tracemalloc.reset_peak()

        # Preflight com double de 500 MB
        with (
            patch("log_analyzer.core.streaming.os.stat", return_value=status_500mb),
            patch("log_analyzer.core.streaming.os.fstat", return_value=status_500mb),
        ):
            leitor = LeitorStreaming(fonte, "<ARQUIVO_1>")
            assert leitor.fingerprint.tamanho_bytes == TAMANHO_MAXIMO_BYTES

        # Leitura real do conteúdo — sem patches de stat na iteração para
        # usar o conteúdo real do arquivo
        contagem = 0
        for _ in leitor.iterar_linhas():
            contagem += 1

        _, pico = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        assert contagem == linhas_reais
        # O pico de RAM deve ser insignificante em relação aos 500 MB
        # anunciados. Mesmo com overhead do Python, não deve exceder 5 MB.
        assert pico < 5_242_880, (
            f"Pico de RAM ({pico:,} bytes) é excessivo para streaming de "
            f"{tamanho_real:,} bytes reais com double de 500 MB"
        )
        # E certamente deve ser menor que 1% dos 500 MB anunciados
        fracao_anunciado = pico / TAMANHO_MAXIMO_BYTES
        assert fracao_anunciado < 0.01, (
            f"Pico ({pico:,} bytes) é {fracao_anunciado:.4%} dos 500 MB "
            f"anunciados — deveria ser < 1%"
        )
