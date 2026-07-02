"""Carregador de arquivos de log com validações.

Responsável por:
- Validar que o arquivo existe e é legível (Req 1.2)
- Validar que o arquivo não está vazio (Req 10.4)
- Validar que o arquivo não excede 500 MB (Req 1.4)
- Ler o arquivo linha a linha (streaming) para evitar carga total em memória (Req 1.1)
- Produzir MensagemDeErro em caso de falha, identificando o arquivo afetado (Req 1.2, 10.5)
"""

from __future__ import annotations

import os
from typing import Iterator

from log_analyzer.core.modelos import MensagemDeErro

#: Tamanho máximo permitido por arquivo: 500 MB em bytes.
TAMANHO_MAXIMO_BYTES: int = 500 * 1024 * 1024


def carregar_arquivo(caminho: str) -> list[str] | MensagemDeErro:
    """Carrega um arquivo de log linha a linha com validações.

    Validações realizadas (nesta ordem):
    1. Arquivo acessível para leitura (existe e tem permissão).
    2. Tamanho do arquivo ≤ 500 MB.
    3. Arquivo não está vazio.

    Em caso de sucesso, retorna a lista de linhas (sem newline final em cada
    linha). Em caso de falha, retorna uma ``MensagemDeErro`` identificando o
    arquivo afetado — sem lançar exceção, para que o orquestrador possa
    continuar o processamento dos demais arquivos.

    Parameters
    ----------
    caminho : str
        Caminho do arquivo de log a ser carregado.

    Returns
    -------
    list[str] | MensagemDeErro
        Lista de linhas (sucesso) ou mensagem de erro (falha).
    """
    # 1. Verificar se o arquivo é legível (existe + permissão de leitura)
    if not os.path.isfile(caminho):
        return MensagemDeErro(
            arquivo_ou_app=caminho,
            descricao="Arquivo não encontrado ou não é um arquivo regular.",
        )

    if not os.access(caminho, os.R_OK):
        return MensagemDeErro(
            arquivo_ou_app=caminho,
            descricao="Arquivo não pode ser lido (sem permissão de leitura).",
        )

    # 2. Verificar tamanho ≤ 500 MB
    try:
        tamanho = os.path.getsize(caminho)
    except OSError as e:
        return MensagemDeErro(
            arquivo_ou_app=caminho,
            descricao=f"Não foi possível obter o tamanho do arquivo: {e}",
        )

    if tamanho > TAMANHO_MAXIMO_BYTES:
        tamanho_mb = tamanho / (1024 * 1024)
        return MensagemDeErro(
            arquivo_ou_app=caminho,
            descricao=(
                f"Arquivo excede o limite de 500 MB "
                f"(tamanho: {tamanho_mb:.1f} MB)."
            ),
        )

    # 3. Verificar se o arquivo não está vazio
    if tamanho == 0:
        return MensagemDeErro(
            arquivo_ou_app=caminho,
            descricao="Arquivo está vazio.",
        )

    # 4. Leitura em streaming (linha a linha) e coleta das linhas
    try:
        linhas = list(_ler_linhas(caminho))
    except OSError as e:
        return MensagemDeErro(
            arquivo_ou_app=caminho,
            descricao=f"Erro ao ler o arquivo: {e}",
        )

    return linhas


def _ler_linhas(caminho: str) -> Iterator[str]:
    """Gera linhas de um arquivo em streaming (sem carregar tudo de uma vez).

    Cada linha é retornada sem o caractere de nova linha final.
    """
    with open(caminho, "r", encoding="utf-8", errors="replace") as f:
        for linha in f:
            yield linha.rstrip("\n").rstrip("\r")
