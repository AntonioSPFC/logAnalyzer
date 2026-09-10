"""Serialização aditiva dos contratos públicos do Analisador de Logs.

Os helpers convertem modelos legados e da Fase 2 em estruturas compostas
somente por primitivas JSON. Nomes, ordem e valores dos campos existentes são
preservados; campos aditivos aparecem depois do prefixo legado definido pelos
dataclasses.

A serialização é deliberadamente explícita: tipos desconhecidos não são
convertidos por ``str`` e, portanto, não podem ter sua semântica reinterpretada
silenciosamente.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum
from typing import TypeAlias, cast

from log_analyzer.core.modelos import EntradaDeLog, ResultadoDeAnalise


ValorSerializado: TypeAlias = (
    None
    | bool
    | int
    | float
    | str
    | list["ValorSerializado"]
    | dict[str, "ValorSerializado"]
)


def _serializar_chave(chave: object) -> str:
    """Converte somente chaves textuais ou enums textuais sem coerção livre."""

    if isinstance(chave, str):
        return chave
    if isinstance(chave, Enum) and isinstance(chave.value, str):
        return chave.value
    raise TypeError(
        "Chave de mapeamento não suportada para serialização: "
        f"{type(chave).__name__}."
    )


def serializar_modelo(objeto: object) -> ValorSerializado:
    """Converte recursivamente um modelo em primitivas compatíveis com JSON.

    Regras estáveis do contrato:

    - dataclasses mantêm a ordem declarada e os nomes exatos dos campos;
    - enums usam ``value``, preservando inclusive os valores de ``Categoria``;
    - ``datetime`` usa ISO 8601 sem alterar timezone ou precisão;
    - tuplas e listas tornam-se arrays JSON na ordem original;
    - mapeamentos mantêm chaves textuais; enums textuais usam seu valor público.

    Objetos legados construídos apenas com os campos da Fase 1 são aceitos
    porque os campos novos possuem defaults. Dataclasses de versões anteriores,
    caso ainda estejam em memória, também são percorridos somente pelos campos
    que efetivamente possuem.
    """

    if objeto is None or isinstance(objeto, (bool, int, float, str)):
        return objeto

    if isinstance(objeto, Enum):
        return serializar_modelo(objeto.value)

    if isinstance(objeto, datetime):
        return objeto.isoformat()

    if is_dataclass(objeto) and not isinstance(objeto, type):
        return {
            campo.name: serializar_modelo(getattr(objeto, campo.name))
            for campo in fields(objeto)
        }

    if isinstance(objeto, Mapping):
        resultado: dict[str, ValorSerializado] = {}
        for chave, valor in objeto.items():
            chave_serializada = _serializar_chave(chave)
            if chave_serializada in resultado:
                raise ValueError(
                    "Chaves distintas colidem após serialização do mapeamento."
                )
            resultado[chave_serializada] = serializar_modelo(valor)
        return resultado

    if isinstance(objeto, (list, tuple)):
        return [serializar_modelo(item) for item in objeto]

    raise TypeError(
        "Tipo não suportado para serialização: " f"{type(objeto).__name__}."
    )


def serializar_entrada_de_log(
    entrada: EntradaDeLog,
) -> dict[str, ValorSerializado]:
    """Serializa uma entrada legada ou aditiva sem mudar campos existentes."""

    if not isinstance(entrada, EntradaDeLog):
        raise TypeError("entrada deve ser EntradaDeLog.")
    return cast(dict[str, ValorSerializado], serializar_modelo(entrada))


def serializar_resultado_de_analise(
    resultado: ResultadoDeAnalise,
) -> dict[str, ValorSerializado]:
    """Serializa um resultado legado ou aditivo sem omitir seus defaults."""

    if not isinstance(resultado, ResultadoDeAnalise):
        raise TypeError("resultado deve ser ResultadoDeAnalise.")
    return cast(dict[str, ValorSerializado], serializar_modelo(resultado))


__all__ = [
    "ValorSerializado",
    "serializar_entrada_de_log",
    "serializar_modelo",
    "serializar_resultado_de_analise",
]
