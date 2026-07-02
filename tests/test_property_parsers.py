"""Teste de propriedade: Round-trip de interpretação preserva os campos.

Feature: log-analyzer, Property 1: Round-trip de interpretação preserva os campos

**Validates: Requirements 4.4, 4.5**

Para toda EntradaDeLog que um Parser_de_Aplicacao interpreta com sucesso (interpretada=True),
executar a sequência interpretar → imprimir → interpretar novamente produz uma EntradaDeLog
cujos campos carimbo_de_tempo, nivel_de_severidade e mensagem são idênticos, campo a campo,
aos da primeira interpretação.
"""

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from log_analyzer.apps.vpl import VplParser
from log_analyzer.apps.ork import OrkParser
from log_analyzer.apps.voci import VociParser


# --- Strategies para gerar linhas de log válidas ---

# Componentes de timestamp reutilizáveis
_anos = st.integers(min_value=2000, max_value=2099)
_meses = st.integers(min_value=1, max_value=12)
_dias = st.integers(min_value=1, max_value=28)  # Limitar a 28 para evitar meses inválidos
_horas = st.integers(min_value=0, max_value=23)
_minutos = st.integers(min_value=0, max_value=59)
_segundos = st.integers(min_value=0, max_value=59)
_milissegundos = st.integers(min_value=0, max_value=999)

# Mensagens: texto não vazio sem caracteres que quebram o parsing
# Evitamos newlines, tabs e pipes conforme o formato de cada parser
_mensagem_base = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S", "Z"),
        blacklist_characters="\t\n\r\x00",
    ),
    min_size=1,
    max_size=100,
).filter(lambda s: s.strip() != "")


def _mensagem_sem_pipe():
    """Mensagem que não começa/termina com espaço e não contém ' | ' no início."""
    return st.text(
        alphabet=st.characters(
            whitelist_categories=("L", "N", "P", "S"),
            blacklist_characters="\t\n\r\x00|",
        ),
        min_size=1,
        max_size=80,
    ).filter(lambda s: s.strip() != "")


def _mensagem_para_ork():
    """Mensagem para ORK: pode conter pipes (o split usa maxsplit=2)."""
    return _mensagem_base.filter(lambda s: s.strip() != "")


def _mensagem_para_voci():
    """Mensagem para VOCI: não pode conter tabs (separador é \\t)."""
    return st.text(
        alphabet=st.characters(
            whitelist_categories=("L", "N", "P", "S", "Z"),
            blacklist_characters="\t\n\r\x00",
        ),
        min_size=1,
        max_size=100,
    ).filter(lambda s: s.strip() != "")


# VPL: "YYYY-MM-DD HH:MM:SS.mmm [LEVEL] source Message"
_niveis_vpl = st.sampled_from(["DEBUG", "INFO", "NOTICE", "WARNING", "ERR", "CRIT", "ALERT"])

_source_vpl = st.from_regex(r"[a-z_]+\.[a-z]:\d{1,5}", fullmatch=True)


@st.composite
def vpl_log_line(draw):
    """Gera uma linha de log VPL válida."""
    ano = draw(_anos)
    mes = draw(_meses)
    dia = draw(_dias)
    hora = draw(_horas)
    minuto = draw(_minutos)
    segundo = draw(_segundos)
    ms = draw(_milissegundos)
    nivel = draw(_niveis_vpl)
    source = draw(_source_vpl)
    # Mensagem VPL: não pode ser vazia, não deve conter newlines
    mensagem = draw(st.text(
        alphabet=st.characters(
            whitelist_categories=("L", "N", "P", "S", "Z"),
            blacklist_characters="\n\r\x00",
        ),
        min_size=1,
        max_size=80,
    ).filter(lambda s: s.strip() != ""))

    timestamp = f"{ano:04d}-{mes:02d}-{dia:02d} {hora:02d}:{minuto:02d}:{segundo:02d}.{ms:03d}"
    return f"{timestamp} [{nivel}] {source} {mensagem}"


# ORK: "ISO_TIMESTAMP | LEVEL | message"
_niveis_ork = st.sampled_from(["DEBUG", "INFO", "WARN", "ERROR", "FATAL"])


@st.composite
def ork_log_line(draw):
    """Gera uma linha de log ORK válida."""
    ano = draw(_anos)
    mes = draw(_meses)
    dia = draw(_dias)
    hora = draw(_horas)
    minuto = draw(_minutos)
    segundo = draw(_segundos)
    micro = draw(st.integers(min_value=0, max_value=999999))
    nivel = draw(_niveis_ork)
    # Mensagem ORK: não pode ser vazia após strip
    mensagem = draw(_mensagem_para_ork())

    # Formato ISO com timezone +00:00
    timestamp = f"{ano:04d}-{mes:02d}-{dia:02d}T{hora:02d}:{minuto:02d}:{segundo:02d}.{micro:06d}+00:00"
    return f"{timestamp} | {nivel} | {mensagem}"


# VOCI: "YYYY-MM-DD HH:MM:SS\tLEVEL\tMessage"
_niveis_voci = st.sampled_from(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])


@st.composite
def voci_log_line(draw):
    """Gera uma linha de log VOCI válida."""
    ano = draw(_anos)
    mes = draw(_meses)
    dia = draw(_dias)
    hora = draw(_horas)
    minuto = draw(_minutos)
    segundo = draw(_segundos)
    nivel = draw(_niveis_voci)
    mensagem = draw(_mensagem_para_voci())

    timestamp = f"{ano:04d}-{mes:02d}-{dia:02d} {hora:02d}:{minuto:02d}:{segundo:02d}"
    return f"{timestamp}\t{nivel}\t{mensagem}"


# --- Strategy composta: gera (parser, linha) casados ---

@st.composite
def parser_e_linha(draw):
    """Gera um par (parser_name, log_line) onde a linha é válida para o parser."""
    choice = draw(st.sampled_from(["VPL", "ORK", "VOCI"]))
    if choice == "VPL":
        line = draw(vpl_log_line())
    elif choice == "ORK":
        line = draw(ork_log_line())
    else:
        line = draw(voci_log_line())
    return (choice, line)


# --- Teste de propriedade ---

@settings(max_examples=100)
@given(data=parser_e_linha())
def test_round_trip_interpretacao_preserva_campos(data):
    """Property 1: Round-trip de interpretação preserva os campos.

    Feature: log-analyzer, Property 1: Round-trip de interpretação preserva os campos

    Para toda EntradaDeLog que um Parser_de_Aplicacao interpreta com sucesso (interpretada=True),
    executar a sequência interpretar → imprimir → interpretar novamente produz uma EntradaDeLog
    cujos campos carimbo_de_tempo, nivel_de_severidade e mensagem são idênticos, campo a campo,
    aos da primeira interpretação.

    **Validates: Requirements 4.4, 4.5**
    """
    parser_choice, log_line = data

    # Selecionar o parser correto
    parsers = {
        "VPL": VplParser(),
        "ORK": OrkParser(),
        "VOCI": VociParser(),
    }
    parser = parsers[parser_choice]

    # Passo 1: Interpretar a linha
    e1 = parser.interpretar_entrada(log_line)

    # Só exercitar o round-trip para entradas interpretadas com sucesso
    assume(e1.interpretada is True)

    # Passo 2: Imprimir a entrada interpretada
    texto_impresso = parser.imprimir_entrada(e1)

    # Passo 3: Interpretar novamente o texto impresso
    e2 = parser.interpretar_entrada(texto_impresso)

    # Asserções de round-trip: campos devem ser idênticos
    assert e2.interpretada is True, (
        f"Reinterpretação falhou para parser {parser_choice}.\n"
        f"Linha original: {log_line!r}\n"
        f"Texto impresso: {texto_impresso!r}"
    )
    assert e1.carimbo_de_tempo == e2.carimbo_de_tempo, (
        f"carimbo_de_tempo diverge no round-trip ({parser_choice}).\n"
        f"Original: {e1.carimbo_de_tempo}\n"
        f"Re-interpretado: {e2.carimbo_de_tempo}"
    )
    assert e1.nivel_de_severidade == e2.nivel_de_severidade, (
        f"nivel_de_severidade diverge no round-trip ({parser_choice}).\n"
        f"Original: {e1.nivel_de_severidade}\n"
        f"Re-interpretado: {e2.nivel_de_severidade}"
    )
    assert e1.mensagem == e2.mensagem, (
        f"mensagem diverge no round-trip ({parser_choice}).\n"
        f"Original: {e1.mensagem!r}\n"
        f"Re-interpretado: {e2.mensagem!r}"
    )
