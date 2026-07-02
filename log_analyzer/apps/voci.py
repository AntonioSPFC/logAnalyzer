"""Parser de Aplicação para VOCI (transcritor de áudio).

Formato de log VOCI: tab-separated
    YYYY-MM-DD HH:MM:SS\tLEVEL\tMessage

Níveis de severidade: DEBUG, INFO, WARNING, ERROR, CRITICAL
"""

from datetime import datetime

from log_analyzer.core.interfaces import Parser_de_Aplicacao
from log_analyzer.core.modelos import EntradaDeLog

# Formato esperado do carimbo de tempo VOCI
_FORMATO_TIMESTAMP = "%Y-%m-%d %H:%M:%S"

# Níveis de severidade válidos para VOCI
_NIVEIS_VOCI = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


class VociParser(Parser_de_Aplicacao):
    """Parser para logs da aplicação VOCI (transcritor de áudio).

    Formato: YYYY-MM-DD HH:MM:SS\\tLEVEL\\tMessage
    Separador: tabulação (\\t)
    Níveis: DEBUG, INFO, WARNING, ERROR, CRITICAL

    Requisitos: 6.4, 6.7, 4.1, 4.2, 4.3, 4.4
    """

    @property
    def niveis_de_severidade(self) -> frozenset[str]:
        """Conjunto de níveis de severidade válidos para VOCI."""
        return _NIVEIS_VOCI

    def interpretar_entrada(self, texto: str) -> EntradaDeLog:
        """Converte uma linha bruta de log VOCI em EntradaDeLog estruturada.

        Formato esperado: YYYY-MM-DD HH:MM:SS\\tLEVEL\\tMessage

        Se a linha não segue o formato esperado (falta carimbo de tempo válido,
        severidade válida ou mensagem), retorna EntradaDeLog com interpretada=False,
        preservando o texto_original. (Req 4.1, 4.2, 4.3, 6.7)
        """
        try:
            # Separar por tabulação — espera exatamente 3 partes
            partes = texto.split("\t", 2)
            if len(partes) != 3:
                return self._entrada_nao_interpretada(texto)

            texto_timestamp, nivel, mensagem = partes

            # Validar e parsear o carimbo de tempo
            carimbo = datetime.strptime(texto_timestamp.strip(), _FORMATO_TIMESTAMP)

            # Validar o nível de severidade
            nivel_normalizado = nivel.strip().upper()
            if nivel_normalizado not in _NIVEIS_VOCI:
                return self._entrada_nao_interpretada(texto)

            # Validar a mensagem (não pode ser vazia)
            mensagem_limpa = mensagem.strip()
            if not mensagem_limpa:
                return self._entrada_nao_interpretada(texto)

            return EntradaDeLog(
                texto_original=texto,
                aplicacao="VOCI",
                ordem_de_leitura=0,
                interpretada=True,
                carimbo_de_tempo=carimbo,
                nivel_de_severidade=nivel_normalizado,
                mensagem=mensagem_limpa,
            )

        except (ValueError, IndexError):
            return self._entrada_nao_interpretada(texto)

    def imprimir_entrada(self, entrada: EntradaDeLog) -> str:
        """Produz a representação textual de uma EntradaDeLog de VOCI.

        Formato: YYYY-MM-DD HH:MM:SS\\tLEVEL\\tMessage

        Para entradas interpretadas, reconstrói a linha no formato canônico.
        Para entradas não interpretadas, retorna o texto_original.
        Deve satisfazer a propriedade de round-trip (Req 4.4, 4.5).
        """
        if not entrada.interpretada:
            return entrada.texto_original

        timestamp_str = entrada.carimbo_de_tempo.strftime(_FORMATO_TIMESTAMP)  # type: ignore[union-attr]
        return f"{timestamp_str}\t{entrada.nivel_de_severidade}\t{entrada.mensagem}"

    def _entrada_nao_interpretada(self, texto: str) -> EntradaDeLog:
        """Cria uma EntradaDeLog marcada como não interpretada, preservando o texto original."""
        return EntradaDeLog(
            texto_original=texto,
            aplicacao="VOCI",
            ordem_de_leitura=0,
            interpretada=False,
        )
