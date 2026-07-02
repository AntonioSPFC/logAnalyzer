"""Parser de Aplicação para VPL (PBX FreeSWITCH).

Formato de log esperado:
    YYYY-MM-DD HH:MM:SS.mmm [LEVEL] source Message text

Onde:
- YYYY-MM-DD HH:MM:SS.mmm é o carimbo de tempo com milissegundos
- LEVEL é um dos níveis de severidade do FreeSWITCH
- source é o identificador do módulo/fonte (ex: mod_sofia.c:1234)
- Message text é o conteúdo da mensagem

Níveis de severidade válidos (FreeSWITCH):
    DEBUG, INFO, NOTICE, WARNING, ERR, CRIT, ALERT
"""

import re
from datetime import datetime

from log_analyzer.core.interfaces import Parser_de_Aplicacao
from log_analyzer.core.modelos import EntradaDeLog

# Níveis de severidade do FreeSWITCH
_NIVEIS_VPL: frozenset[str] = frozenset(
    {"DEBUG", "INFO", "NOTICE", "WARNING", "ERR", "CRIT", "ALERT"}
)

# Regex para o formato de log VPL:
# 2024-01-15 10:30:45.123 [INFO] mod_sofia.c:1234 Some message here
_PATTERN = re.compile(
    r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d{3})"  # grupo 1: timestamp
    r"\s+\[([A-Z]+)\]"  # grupo 2: nível de severidade
    r"\s+\S+"  # source (não capturado)
    r"\s+(.*)"  # grupo 3: mensagem
)

_TIMESTAMP_FMT = "%Y-%m-%d %H:%M:%S.%f"


class VplParser(Parser_de_Aplicacao):
    """Parser de logs do VPL (FreeSWITCH).

    Implementa a interface Parser_de_Aplicacao para interpretar e imprimir
    entradas de log no formato FreeSWITCH.
    """

    @property
    def niveis_de_severidade(self) -> frozenset[str]:
        """Conjunto de níveis de severidade válidos para VPL."""
        return _NIVEIS_VPL

    def interpretar_entrada(self, texto: str) -> EntradaDeLog:
        """Converte uma linha bruta de log VPL em EntradaDeLog estruturada.

        Marca como não interpretada quando:
        - Não há carimbo de tempo válido
        - A severidade não pertence a niveis_de_severidade
        - Não há mensagem (vazia)

        O campo aplicacao é "VPL" e ordem_de_leitura é 0 (callers set this).
        """
        match = _PATTERN.match(texto)
        if not match:
            return EntradaDeLog(
                texto_original=texto,
                aplicacao="VPL",
                ordem_de_leitura=0,
                interpretada=False,
            )

        ts_str, nivel, mensagem = match.group(1), match.group(2), match.group(3)

        # Validar severidade
        if nivel not in _NIVEIS_VPL:
            return EntradaDeLog(
                texto_original=texto,
                aplicacao="VPL",
                ordem_de_leitura=0,
                interpretada=False,
            )

        # Validar mensagem não vazia
        if not mensagem or not mensagem.strip():
            return EntradaDeLog(
                texto_original=texto,
                aplicacao="VPL",
                ordem_de_leitura=0,
                interpretada=False,
            )

        # Validar carimbo de tempo
        try:
            carimbo = datetime.strptime(ts_str, _TIMESTAMP_FMT)
        except ValueError:
            return EntradaDeLog(
                texto_original=texto,
                aplicacao="VPL",
                ordem_de_leitura=0,
                interpretada=False,
            )

        return EntradaDeLog(
            texto_original=texto,
            aplicacao="VPL",
            ordem_de_leitura=0,
            interpretada=True,
            carimbo_de_tempo=carimbo,
            nivel_de_severidade=nivel,
            mensagem=mensagem,
        )

    def imprimir_entrada(self, entrada: EntradaDeLog) -> str:
        """Produz representação textual de uma EntradaDeLog.

        Para entradas interpretadas, formata com timestamp, severidade e mensagem.
        Para entradas não interpretadas, retorna o texto original.

        Satisfaz a propriedade de round-trip:
            interpretar(imprimir(interpretar(x))) == interpretar(x)
        """
        if not entrada.interpretada:
            return entrada.texto_original

        # Formatar timestamp com exatamente 3 dígitos de milissegundos para round-trip
        ts = entrada.carimbo_de_tempo  # type: ignore[union-attr]
        millis = ts.microsecond // 1000
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S") + f".{millis:03d}"
        # Usar "vpl_source" como source placeholder para round-trip
        return (
            f"{ts_str} [{entrada.nivel_de_severidade}] vpl_source {entrada.mensagem}"
        )
