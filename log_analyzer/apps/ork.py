"""Parser de Aplicação para o ORK (orquestrador de agente IA para chamadas).

Formato de log (pipe-delimited):
    ISO_TIMESTAMP | LEVEL | message

Exemplo:
    2024-01-15T10:30:45.123Z | INFO | Call initiated for session abc-123

Níveis de severidade válidos: DEBUG, INFO, WARN, ERROR, FATAL
"""

from datetime import datetime, timezone

from log_analyzer.core.interfaces import Parser_de_Aplicacao
from log_analyzer.core.modelos import EntradaDeLog

_ORK_NIVEIS = frozenset({"DEBUG", "INFO", "WARN", "ERROR", "FATAL"})

_APLICACAO = "ORK"


class OrkParser(Parser_de_Aplicacao):
    """Parser concreto para logs do ORK no formato pipe-delimited.

    Formato esperado:
        ISO_TIMESTAMP | LEVEL | message

    Onde:
    - ISO_TIMESTAMP é um carimbo de tempo em formato ISO 8601
    - LEVEL é um dos níveis: DEBUG, INFO, WARN, ERROR, FATAL
    - message é o texto livre da entrada

    Satisfaz os requisitos 6.3, 6.7, 4.1, 4.2, 4.3, 4.4, 4.5.
    """

    @property
    def niveis_de_severidade(self) -> frozenset[str]:
        """Retorna os níveis de severidade válidos do ORK."""
        return _ORK_NIVEIS

    def interpretar_entrada(self, texto: str) -> EntradaDeLog:
        """Interpreta uma linha de log do ORK.

        Tenta extrair carimbo de tempo, nível de severidade e mensagem.
        Se qualquer campo estiver ausente ou inválido, retorna entrada não interpretada
        preservando o texto original.
        """
        try:
            partes = texto.split(" | ", maxsplit=2)
            if len(partes) != 3:
                return self._nao_interpretada(texto)

            timestamp_str, nivel_str, mensagem = partes
            timestamp_str = timestamp_str.strip()
            nivel_str = nivel_str.strip()
            mensagem = mensagem.strip()

            # Validar mensagem não vazia
            if not mensagem:
                return self._nao_interpretada(texto)

            # Validar nível de severidade
            nivel_upper = nivel_str.upper()
            if nivel_upper not in _ORK_NIVEIS:
                return self._nao_interpretada(texto)

            # Parsear carimbo de tempo ISO 8601
            carimbo = datetime.fromisoformat(timestamp_str)

            return EntradaDeLog(
                texto_original=texto,
                aplicacao=_APLICACAO,
                ordem_de_leitura=0,
                interpretada=True,
                carimbo_de_tempo=carimbo,
                nivel_de_severidade=nivel_upper,
                mensagem=mensagem,
            )
        except (ValueError, IndexError):
            return self._nao_interpretada(texto)

    def imprimir_entrada(self, entrada: EntradaDeLog) -> str:
        """Produz a representação textual pipe-delimited do ORK.

        Para entradas interpretadas: ISO_TIMESTAMP | LEVEL | message
        Para entradas não interpretadas: retorna o texto_original.

        Deve satisfazer a propriedade de round-trip (Req 4.5).
        """
        if not entrada.interpretada:
            return entrada.texto_original

        # Formatar o timestamp em ISO 8601
        assert entrada.carimbo_de_tempo is not None
        assert entrada.nivel_de_severidade is not None
        assert entrada.mensagem is not None

        ts = entrada.carimbo_de_tempo
        # Usar isoformat para preservar a representação
        timestamp_str = ts.isoformat()

        return f"{timestamp_str} | {entrada.nivel_de_severidade} | {entrada.mensagem}"

    def _nao_interpretada(self, texto: str) -> EntradaDeLog:
        """Cria uma EntradaDeLog não interpretada preservando o texto original."""
        return EntradaDeLog(
            texto_original=texto,
            aplicacao=_APLICACAO,
            ordem_de_leitura=0,
            interpretada=False,
        )
