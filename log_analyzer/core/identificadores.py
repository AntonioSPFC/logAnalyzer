"""Normalização auditável de identificadores técnicos da Fase 2.

Este módulo é deliberadamente puro: recebe um valor já extraído de um contexto
conhecido e produz exatamente um :class:`IdentificadorTecnico`. Ele não procura
identificadores em texto, não infere tipos, não concatena fragmentos e não cria
vínculos entre valores.
"""

from __future__ import annotations

from types import MappingProxyType
from uuid import UUID

from log_analyzer.core.modelos import (
    IdentificadorTecnico,
    Proveniencia,
    TipoIdentificador,
)


_PARES_DELIMITADORES_EXTERNOS_APROVADOS = MappingProxyType(
    {
        '"': '"',
        "'": "'",
        "<": ">",
        "[": "]",
        "(": ")",
        "{": "}",
    }
)

_NAMESPACE_POR_TIPO = MappingProxyType(
    {
        TipoIdentificador.CHAMADA_EXTERNA: "chamada_externa",
        TipoIdentificador.TELECOM_CALL_ID: "chamada_externa",
        TipoIdentificador.CALL_ID: "chamada_externa",
        TipoIdentificador.SIP: "sip",
        TipoIdentificador.UUID_CANAL: "uuid_canal",
        TipoIdentificador.UUID_SESSAO: "uuid_sessao",
    }
)

_TIPOS_UUID = frozenset(
    {
        TipoIdentificador.UUID_CANAL,
        TipoIdentificador.UUID_SESSAO,
    }
)


class NormalizadorDeIdentificador:
    """Cria identificadores normalizados sem perder tipo ou proveniência.

    A equivalência textual é limitada a ``casefold`` e à remoção de whitespace
    periférico e pares de delimitadores externos aprovados. Caracteres internos,
    inclusive hífens e whitespace, permanecem inalterados.
    """

    def normalizar(
        self,
        tipo: TipoIdentificador,
        nome_campo: str,
        valor: str,
        proveniencia: Proveniencia,
    ) -> IdentificadorTecnico:
        """Normaliza um único valor extraído de um contexto explicitamente tipado.

        ``proveniencia`` deve identificar o mesmo campo e uma regra de extração
        versionada. O objeto é reutilizado sem alterar arquivo, entrada, linhas ou
        span.

        Raises:
            TypeError: quando tipo, campo, valor ou proveniência têm tipo inválido.
            ValueError: quando faltam metadados auditáveis, o valor normalizado é
                vazio ou um contexto UUID contém valor que ``uuid.UUID`` rejeita.
        """

        self._validar_contexto(tipo, nome_campo, valor, proveniencia)

        valor_normalizado = self._remover_sintaxe_externa(valor).casefold()
        if not valor_normalizado:
            raise ValueError(
                "valor deve conter um identificador após remover sintaxe externa."
            )

        if tipo in _TIPOS_UUID:
            self._validar_uuid(valor_normalizado)

        return IdentificadorTecnico(
            tipo=tipo,
            namespace_comparacao=_NAMESPACE_POR_TIPO[tipo],
            nome_campo=nome_campo,
            valor_original=valor,
            valor_normalizado=valor_normalizado,
            proveniencia=proveniencia,
        )

    @staticmethod
    def _validar_contexto(
        tipo: TipoIdentificador,
        nome_campo: str,
        valor: str,
        proveniencia: Proveniencia,
    ) -> None:
        if not isinstance(tipo, TipoIdentificador):
            raise TypeError("tipo deve ser TipoIdentificador.")
        if tipo not in _NAMESPACE_POR_TIPO:
            raise ValueError("tipo não possui namespace de comparação aprovado.")

        if not isinstance(nome_campo, str):
            raise TypeError("nome_campo deve ser string.")
        if not nome_campo.strip():
            raise ValueError("nome_campo deve ser uma string não vazia.")

        if not isinstance(valor, str):
            raise TypeError("valor deve ser string.")
        if not valor.strip():
            raise ValueError("valor deve ser uma string não vazia.")

        if not isinstance(proveniencia, Proveniencia):
            raise TypeError("proveniencia deve ser Proveniencia.")
        if proveniencia.nome_campo is None:
            raise ValueError("proveniencia deve registrar nome_campo.")
        if proveniencia.nome_campo != nome_campo:
            raise ValueError(
                "nome_campo deve corresponder ao registrado na proveniencia."
            )
        if proveniencia.regra_extracao is None:
            raise ValueError(
                "proveniencia deve registrar regra_extracao versionada."
            )

    @staticmethod
    def _remover_sintaxe_externa(valor: str) -> str:
        resultado = valor.strip()

        while len(resultado) >= 2:
            fechamento = _PARES_DELIMITADORES_EXTERNOS_APROVADOS.get(
                resultado[0]
            )
            if fechamento is None or resultado[-1] != fechamento:
                break
            resultado = resultado[1:-1].strip()

        return resultado

    @staticmethod
    def _validar_uuid(valor_normalizado: str) -> None:
        try:
            UUID(valor_normalizado)
        except (AttributeError, ValueError) as erro:
            raise ValueError(
                "valor deve ser um UUID válido no contexto tipado."
            ) from None
