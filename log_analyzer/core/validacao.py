"""Validação de entradas fornecidas pelo usuário.

Funções:
    validar_identificador — valida o Identificador de busca (Req 3.5, 10.2, 10.3).
"""

from __future__ import annotations

from log_analyzer.core.excecoes import ErroDeIdentificador


def validar_identificador(identificador: str) -> None:
    """Valida a string do Identificador fornecido pelo usuário.

    Raises:
        ErroDeIdentificador: se o identificador for vazio (len == 0),
            composto apenas por espaços em branco, ou tiver mais de 256 caracteres.

    Returns:
        None quando o identificador é válido.
    """
    if len(identificador) == 0:
        raise ErroDeIdentificador(
            "O Identificador não pode ser vazio.",
            identificador=identificador,
        )

    if identificador.isspace():
        raise ErroDeIdentificador(
            "O Identificador não pode ser composto apenas por espaços em branco.",
            identificador=identificador,
        )

    if len(identificador) > 256:
        raise ErroDeIdentificador(
            "O Identificador deve conter entre 1 e 256 caracteres.",
            identificador=identificador,
        )
