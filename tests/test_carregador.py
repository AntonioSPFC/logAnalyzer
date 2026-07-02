"""Testes para o carregador de arquivos (log_analyzer.core.carregador).

Cobre os requisitos 1.1, 1.2, 1.4, 10.4 e 10.5:
- Leitura linha a linha de um arquivo válido.
- Rejeição de arquivo ilegível (não existe ou sem permissão).
- Rejeição de arquivo vazio.
- Rejeição de arquivo acima de 500 MB.
- Produção de MensagemDeErro identificando o arquivo afetado.
"""

from __future__ import annotations

import os
import sys
import stat
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from log_analyzer.core.carregador import carregar_arquivo, TAMANHO_MAXIMO_BYTES
from log_analyzer.core.modelos import MensagemDeErro


class TestCarregarArquivoSucesso:
    """Testes de cenários de sucesso na leitura de arquivo."""

    def test_arquivo_com_varias_linhas(self, tmp_path: Path) -> None:
        """Arquivo com múltiplas linhas retorna lista de linhas sem newline."""
        conteudo = "linha 1\nlinha 2\nlinha 3\n"
        arquivo = tmp_path / "log.txt"
        arquivo.write_text(conteudo, encoding="utf-8")

        resultado = carregar_arquivo(str(arquivo))

        assert isinstance(resultado, list)
        assert resultado == ["linha 1", "linha 2", "linha 3"]

    def test_arquivo_com_uma_linha_sem_newline(self, tmp_path: Path) -> None:
        """Arquivo com uma única linha sem newline final."""
        arquivo = tmp_path / "log.txt"
        arquivo.write_text("unica linha", encoding="utf-8")

        resultado = carregar_arquivo(str(arquivo))

        assert isinstance(resultado, list)
        assert resultado == ["unica linha"]

    def test_arquivo_com_linhas_vazias_intercaladas(self, tmp_path: Path) -> None:
        """Arquivo com linhas vazias intercaladas preserva as linhas vazias."""
        conteudo = "a\n\nb\n\nc"
        arquivo = tmp_path / "log.txt"
        arquivo.write_text(conteudo, encoding="utf-8")

        resultado = carregar_arquivo(str(arquivo))

        assert isinstance(resultado, list)
        assert resultado == ["a", "", "b", "", "c"]

    def test_arquivo_com_caracteres_unicode(self, tmp_path: Path) -> None:
        """Arquivo com caracteres UTF-8 é lido corretamente."""
        conteudo = "ação\nmaçã\ncafé\n"
        arquivo = tmp_path / "log.txt"
        arquivo.write_text(conteudo, encoding="utf-8")

        resultado = carregar_arquivo(str(arquivo))

        assert isinstance(resultado, list)
        assert "ação" in resultado
        assert "maçã" in resultado
        assert "café" in resultado


class TestCarregarArquivoErroIlegivel:
    """Testes para arquivo ilegível (não existe ou sem permissão)."""

    def test_arquivo_nao_existe(self) -> None:
        """Arquivo inexistente retorna MensagemDeErro."""
        caminho = "/caminho/inexistente/arquivo.log"

        resultado = carregar_arquivo(caminho)

        assert isinstance(resultado, MensagemDeErro)
        assert resultado.arquivo_ou_app == caminho
        assert "não encontrado" in resultado.descricao.lower() or "não é um arquivo" in resultado.descricao.lower()

    def test_caminho_e_diretorio(self, tmp_path: Path) -> None:
        """Caminho que aponta para um diretório retorna MensagemDeErro."""
        resultado = carregar_arquivo(str(tmp_path))

        assert isinstance(resultado, MensagemDeErro)
        assert resultado.arquivo_ou_app == str(tmp_path)

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="Permissões de arquivo não funcionam da mesma forma no Windows",
    )
    def test_arquivo_sem_permissao_leitura(self, tmp_path: Path) -> None:
        """Arquivo sem permissão de leitura retorna MensagemDeErro."""
        arquivo = tmp_path / "protegido.log"
        arquivo.write_text("conteudo", encoding="utf-8")
        arquivo.chmod(0o000)

        try:
            resultado = carregar_arquivo(str(arquivo))
            assert isinstance(resultado, MensagemDeErro)
            assert resultado.arquivo_ou_app == str(arquivo)
            assert "permissão" in resultado.descricao.lower() or "lido" in resultado.descricao.lower()
        finally:
            arquivo.chmod(stat.S_IRUSR | stat.S_IWUSR)


class TestCarregarArquivoVazio:
    """Testes para arquivo vazio (Req 10.4)."""

    def test_arquivo_vazio_retorna_mensagem_erro(self, tmp_path: Path) -> None:
        """Arquivo com 0 bytes retorna MensagemDeErro indicando que está vazio."""
        arquivo = tmp_path / "vazio.log"
        arquivo.write_text("", encoding="utf-8")

        resultado = carregar_arquivo(str(arquivo))

        assert isinstance(resultado, MensagemDeErro)
        assert resultado.arquivo_ou_app == str(arquivo)
        assert "vazio" in resultado.descricao.lower()


class TestCarregarArquivoExcedeTamanho:
    """Testes para arquivo acima de 500 MB (Req 1.4)."""

    def test_arquivo_acima_de_500mb_retorna_mensagem_erro(self, tmp_path: Path) -> None:
        """Arquivo que excede 500 MB retorna MensagemDeErro (simulado via mock)."""
        arquivo = tmp_path / "grande.log"
        arquivo.write_text("dados", encoding="utf-8")

        # Simular tamanho > 500 MB sem criar arquivo real de 500 MB
        tamanho_simulado = TAMANHO_MAXIMO_BYTES + 1
        with patch("log_analyzer.core.carregador.os.path.getsize", return_value=tamanho_simulado):
            resultado = carregar_arquivo(str(arquivo))

        assert isinstance(resultado, MensagemDeErro)
        assert resultado.arquivo_ou_app == str(arquivo)
        assert "500 MB" in resultado.descricao or "500" in resultado.descricao

    def test_arquivo_exatamente_500mb_e_aceito(self, tmp_path: Path) -> None:
        """Arquivo de exatamente 500 MB (limite) é aceito."""
        arquivo = tmp_path / "limite.log"
        arquivo.write_text("dados", encoding="utf-8")

        # Simular tamanho = exatamente 500 MB
        with patch("log_analyzer.core.carregador.os.path.getsize", return_value=TAMANHO_MAXIMO_BYTES):
            resultado = carregar_arquivo(str(arquivo))

        # Deve ser lido com sucesso (retorna lista)
        assert isinstance(resultado, list)


class TestCarregarArquivoIdentificacao:
    """Testa que MensagemDeErro sempre identifica o arquivo afetado."""

    def test_mensagem_erro_identifica_arquivo_inexistente(self) -> None:
        """MensagemDeErro.arquivo_ou_app contém o caminho do arquivo."""
        caminho = "/meu/arquivo/especifico.log"
        resultado = carregar_arquivo(caminho)

        assert isinstance(resultado, MensagemDeErro)
        assert resultado.arquivo_ou_app == caminho

    def test_mensagem_erro_identifica_arquivo_vazio(self, tmp_path: Path) -> None:
        """MensagemDeErro.arquivo_ou_app contém o caminho do arquivo vazio."""
        arquivo = tmp_path / "vazio_id.log"
        arquivo.write_text("", encoding="utf-8")

        resultado = carregar_arquivo(str(arquivo))

        assert isinstance(resultado, MensagemDeErro)
        assert resultado.arquivo_ou_app == str(arquivo)


class TestConstanteTamanhoMaximo:
    """Testa que a constante TAMANHO_MAXIMO_BYTES está correta."""

    def test_tamanho_maximo_e_500mb(self) -> None:
        """TAMANHO_MAXIMO_BYTES deve ser exatamente 500 * 1024 * 1024."""
        assert TAMANHO_MAXIMO_BYTES == 500 * 1024 * 1024
        assert TAMANHO_MAXIMO_BYTES == 524_288_000
