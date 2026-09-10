"""Property 4: cabeçalhos ORK inválidos falham sem perda ou aborto."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from hypothesis import event, given, settings
from hypothesis import strategies as st

from log_analyzer.apps.ork import OrkParser
from log_analyzer.apps.vpl import VplParser
from log_analyzer.core.interfaces import TipoInicio
from log_analyzer.core.materializacao import (
    FonteMaterializacao,
    MaterializadorSeletivo,
)
from log_analyzer.core.modelos import EntradaIndexada
from log_analyzer.core.multiline import AgrupadorMultiline, BlocoLog
from log_analyzer.core.streaming import LeitorStreaming

_TOKEN_ORK = "<ARQUIVO_1>"
_TOKEN_VPL = "<ARQUIVO_2>"
_CABECALHO_ORK_ANTERIOR = (
    "2030-01-01T01:02:03.1+00:00 host-anterior.synthetic.invalid "
    "worker-anterior[1]: INFO - property.synthetic - entrada anterior"
)
_FRAGMENTO_SINTETICO = st.text(
    alphabet=tuple("abcdefghijklmnopqrstuvwxyz0123456789áçõΩλ日"),
    min_size=1,
    max_size=16,
)


@dataclass(frozen=True, slots=True)
class _CasoOrkInvalido:
    campo_invalido: str
    timestamp_valido: str
    timestamp_invalido: str
    host: str
    processo: str
    pid: str
    severidade: str
    logger: str
    mensagem: str
    continuacoes: tuple[str, ...]
    terminador_cabecalho: str
    terminador_continuacao: str


@dataclass(frozen=True, slots=True)
class _FonteProcessada:
    parser: OrkParser | VplParser
    blocos: tuple[BlocoLog, ...]
    entradas: tuple[EntradaIndexada, ...]
    fonte: FonteMaterializacao


@st.composite
def _casos_ork_invalidos(draw: st.DrawFn) -> _CasoOrkInvalido:
    precisao = draw(st.integers(min_value=0, max_value=6))
    if precisao:
        fracao = draw(st.integers(min_value=0, max_value=(10**precisao) - 1))
        sufixo_fracao = f".{fracao:0{precisao}d}"
    else:
        sufixo_fracao = ""

    dia = draw(st.integers(min_value=1, max_value=28))
    hora = draw(st.integers(min_value=0, max_value=23))
    minuto = draw(st.integers(min_value=0, max_value=59))
    segundo = draw(st.integers(min_value=0, max_value=58))
    offset = draw(st.sampled_from(("Z", "+00:00", "-03:00", "+05:30")))
    sufixo = draw(_FRAGMENTO_SINTETICO)
    fragmentos_continuacao = draw(
        st.lists(_FRAGMENTO_SINTETICO, min_size=1, max_size=3)
    )
    parte_tempo = (
        f"T{hora:02d}:{minuto:02d}:{segundo:02d}{sufixo_fracao}{offset}"
    )

    return _CasoOrkInvalido(
        campo_invalido=draw(
            st.sampled_from(("timestamp", "severidade", "logger", "mensagem"))
        ),
        timestamp_valido=f"2030-02-{dia:02d}{parte_tempo}",
        timestamp_invalido=f"2030-13-{dia:02d}{parte_tempo}",
        host=(
            "host-"
            f"{draw(st.integers(min_value=1, max_value=99))}.synthetic.invalid"
        ),
        processo=f"worker_{draw(st.integers(min_value=1, max_value=99))}",
        pid=str(draw(st.integers(min_value=1, max_value=999_999))),
        severidade=draw(st.sampled_from(("DEBUG", "INFO", "WARN", "ERROR", "FATAL"))),
        logger=f"property.synthetic.{sufixo}",
        mensagem=f"evento_ork_sintetico_{sufixo}",
        continuacoes=tuple(
            f"continuação_sintética_{indice}_{fragmento}"
            for indice, fragmento in enumerate(fragmentos_continuacao, start=1)
        ),
        terminador_cabecalho=draw(st.sampled_from(("\n", "\r\n"))),
        terminador_continuacao=draw(st.sampled_from(("\n", "\r\n"))),
    )


def _formatar_cabecalho_ork(
    campos: dict[str, str],
    host: str,
    processo: str,
    pid: str,
) -> str:
    return (
        f"{campos['timestamp']} {host} {processo}[{pid}]: "
        f"{campos['severidade']} - {campos['logger']} - "
        f"{campos['mensagem']}"
    )


def _processar_fonte(
    parser: OrkParser | VplParser,
    caminho: Path,
    arquivo_token: str,
) -> _FonteProcessada:
    leitor = LeitorStreaming(caminho, arquivo_token)
    blocos = tuple(
        AgrupadorMultiline.para_parser(parser, arquivo_token).agrupar(leitor)
    )
    entradas = tuple(parser.interpretar_bloco(bloco) for bloco in blocos)
    return _FonteProcessada(
        parser=parser,
        blocos=blocos,
        entradas=entradas,
        fonte=FonteMaterializacao(
            arquivo_token=arquivo_token,
            caminho=caminho,
            fingerprint=leitor.fingerprint,
        ),
    )


# Feature: log-analyzer-phase-2, Property 4: Parsing ORK inválido falha sem perda
@given(caso=_casos_ork_invalidos())
@settings(max_examples=100)
def test_property_04_parsing_ork_invalido_falha_sem_perda(
    caso: _CasoOrkInvalido,
    tmp_path_factory,
) -> None:
    """Uma falha ORK isolada preserva sua origem e não interrompe ORK/VPL.

    **Validates: Requirements 3.4, 5.1, 5.2, 5.3, 15.1, 15.3**
    """

    tmp_path = tmp_path_factory.mktemp("property-04-ork-invalido")
    campos_validos = {
        "timestamp": caso.timestamp_valido,
        "severidade": caso.severidade,
        "logger": caso.logger,
        "mensagem": caso.mensagem,
    }
    campos_mutados = dict(campos_validos)
    if caso.campo_invalido == "timestamp":
        campos_mutados["timestamp"] = caso.timestamp_invalido
    elif caso.campo_invalido == "severidade":
        campos_mutados["severidade"] = "NOTICE"
    elif caso.campo_invalido == "logger":
        campos_mutados["logger"] = ""
    else:
        campos_mutados["mensagem"] = ""

    assert tuple(
        nome
        for nome in campos_validos
        if campos_mutados[nome] != campos_validos[nome]
    ) == (caso.campo_invalido,)
    event(f"campo obrigatório invalidado: {caso.campo_invalido}")
    event(f"terminador do cabeçalho inválido: {caso.terminador_cabecalho!r}")

    cabecalho_invalido = _formatar_cabecalho_ork(
        campos_mutados,
        caso.host,
        caso.processo,
        caso.pid,
    )
    partes_bloco_invalido = [
        cabecalho_invalido + caso.terminador_cabecalho
    ]
    partes_bloco_invalido.extend(
        continuacao
        + (
            caso.terminador_continuacao
            if indice % 2
            else caso.terminador_cabecalho
        )
        for indice, continuacao in enumerate(caso.continuacoes, start=1)
    )
    texto_bloco_invalido = "".join(partes_bloco_invalido)

    cabecalho_ork_subsequente = _formatar_cabecalho_ork(
        campos_validos | {"mensagem": f"{caso.mensagem}_subsequente"},
        caso.host,
        caso.processo,
        caso.pid,
    )
    prefixo_ork = _CABECALHO_ORK_ANTERIOR + caso.terminador_continuacao
    conteudo_ork = (
        prefixo_ork + texto_bloco_invalido + cabecalho_ork_subsequente
    )
    caminho_ork = tmp_path / "ork-property-04-sintetico.txt"
    caminho_ork.write_bytes(conteudo_ork.encode("utf-8"))

    mensagem_vpl = f"evento_vpl_sintetico_{caso.mensagem}_subsequente"
    conteudo_vpl = (
        "2030-02-03 07:05:07.123 12.50% [INFO] property.c:17 "
        f"{mensagem_vpl}"
    )
    caminho_vpl = tmp_path / "vpl-property-04-sintetico.txt"
    caminho_vpl.write_bytes(conteudo_vpl.encode("utf-8"))

    parser_ork = OrkParser()
    fonte_ork = _processar_fonte(parser_ork, caminho_ork, _TOKEN_ORK)
    parser_vpl = VplParser()
    fonte_vpl = _processar_fonte(parser_vpl, caminho_vpl, _TOKEN_VPL)

    assert _TOKEN_ORK != _TOKEN_VPL
    assert tuple(bloco.tipo_inicio for bloco in fonte_ork.blocos) == (
        TipoInicio.CABECALHO_VALIDO,
        TipoInicio.CABECALHO_APARENTE_INVALIDO,
        TipoInicio.CABECALHO_VALIDO,
    )
    assert len(fonte_ork.entradas) == 3
    assert tuple(entrada.interpretada for entrada in fonte_ork.entradas) == (
        True,
        False,
        True,
    )
    bloco_invalido = fonte_ork.blocos[1]
    entrada_invalida = fonte_ork.entradas[1]
    linha_inicial = 2
    linha_final = linha_inicial + len(caso.continuacoes)
    inicio_byte = len(prefixo_ork.encode("utf-8"))
    fim_byte = inicio_byte + len(texto_bloco_invalido.encode("utf-8"))

    assert bloco_invalido.intervalo_linhas == (linha_inicial, linha_final)
    assert bloco_invalido.intervalo_bytes == (inicio_byte, fim_byte)
    assert bloco_invalido.texto_original == texto_bloco_invalido
    assert bloco_invalido.sha256 == hashlib.sha256(
        texto_bloco_invalido.encode("utf-8")
    ).hexdigest()
    assert entrada_invalida.interpretada is False
    assert entrada_invalida.ordem_de_leitura == 1
    assert entrada_invalida.texto_ref == bloco_invalido.texto_ref
    assert entrada_invalida.texto_ref.arquivo_token == _TOKEN_ORK
    assert entrada_invalida.texto_ref.linha_inicial == linha_inicial
    assert entrada_invalida.texto_ref.linha_final == linha_final
    assert entrada_invalida.texto_ref.inicio_byte == inicio_byte
    assert entrada_invalida.texto_ref.fim_byte == fim_byte
    assert entrada_invalida.cabecalho == ()
    assert entrada_invalida.identificadores_digest == ()
    assert entrada_invalida.timestamp_original is None
    assert entrada_invalida.timestamp_normalizado is None
    assert len(entrada_invalida.falhas) == 1
    falha = entrada_invalida.falhas[0]
    assert falha.codigo == "ORK_CABECALHO_APARENTE_INVALIDO"
    assert falha.proveniencia.arquivo_token == _TOKEN_ORK
    assert falha.proveniencia.entrada_id == entrada_invalida.entrada_id
    assert falha.proveniencia.linha_inicial == linha_inicial
    assert falha.proveniencia.linha_final == linha_final

    assert fonte_ork.blocos[2].linha_inicial == linha_final + 1
    assert len(fonte_vpl.blocos) == len(fonte_vpl.entradas) == 1
    assert fonte_vpl.blocos[0].tipo_inicio is TipoInicio.CABECALHO_VALIDO
    assert fonte_vpl.entradas[0].interpretada is True
    assert fonte_vpl.entradas[0].texto_ref.arquivo_token == _TOKEN_VPL

    materializacao = MaterializadorSeletivo(
        (fonte_ork.fonte, fonte_vpl.fonte)
    ).materializar(fonte_ork.entradas + fonte_vpl.entradas)
    assert materializacao.falhas == ()
    assert len(materializacao.entradas) == 4
    textos = materializacao.texto_por_entrada_id()
    assert textos[fonte_ork.entradas[0].entrada_id] == prefixo_ork
    assert textos[entrada_invalida.entrada_id] == texto_bloco_invalido
    assert textos[fonte_ork.entradas[2].entrada_id] == (
        cabecalho_ork_subsequente
    )
    assert textos[fonte_vpl.entradas[0].entrada_id] == conteudo_vpl

    cabecalho_nao_interpretado = parser_ork.interpretar_entrada(
        cabecalho_invalido
    )
    assert cabecalho_nao_interpretado.interpretada is False
    assert cabecalho_nao_interpretado.texto_original == cabecalho_invalido
    assert cabecalho_nao_interpretado.posicao_inicial == 1
    assert cabecalho_nao_interpretado.posicao_final == 1
    assert parser_ork.imprimir_entrada(cabecalho_nao_interpretado) == (
        cabecalho_invalido
    )

    ork_anterior = parser_ork.interpretar_entrada(
        textos[fonte_ork.entradas[0].entrada_id]
    )
    ork_subsequente = parser_ork.interpretar_entrada(
        textos[fonte_ork.entradas[2].entrada_id]
    )
    vpl_subsequente = parser_vpl.interpretar_entrada(
        textos[fonte_vpl.entradas[0].entrada_id]
    )
    assert ork_anterior.interpretada is True
    assert ork_subsequente.interpretada is True
    assert ork_subsequente.aplicacao == "ORK"
    assert ork_subsequente.mensagem == f"{caso.mensagem}_subsequente"
    assert vpl_subsequente.interpretada is True
    assert vpl_subsequente.aplicacao == "VPL"
    assert vpl_subsequente.mensagem == mensagem_vpl
