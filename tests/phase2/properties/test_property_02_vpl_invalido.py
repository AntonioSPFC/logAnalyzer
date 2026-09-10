"""Property 2: cabeÃ§alhos VPL invÃ¡lidos falham sem perda ou aborto."""

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

_TOKEN_VPL = "<ARQUIVO_1>"
_TOKEN_ORK = "<ARQUIVO_2>"
_CABECALHO_VPL_ANTERIOR = (
    "2030-01-01 01:02:03.1 1% [INFO] anterior.c:1 entrada anterior"
)
_FRAGMENTO_SINTETICO = st.text(
    alphabet=tuple("abcdefghijklmnopqrstuvwxyz0123456789Ã¡Ã§ÃµÎ©Î»æ—¥"),
    min_size=1,
    max_size=16,
)


@dataclass(frozen=True, slots=True)
class _CasoVplInvalido:
    campo_invalido: str
    timestamp_valido: str
    timestamp_invalido: str
    percentual: str
    severidade: str
    origem: str
    mensagem: str
    continuacoes: tuple[str, ...]
    terminador_cabecalho: str
    terminador_continuacao: str


@dataclass(frozen=True, slots=True)
class _FonteProcessada:
    parser: VplParser | OrkParser
    blocos: tuple[BlocoLog, ...]
    entradas: tuple[EntradaIndexada, ...]
    fonte: FonteMaterializacao


@st.composite
def _casos_vpl_invalidos(draw: st.DrawFn) -> _CasoVplInvalido:
    precisao = draw(st.integers(min_value=1, max_value=6))
    fracao = draw(st.integers(min_value=0, max_value=(10**precisao) - 1))
    dia = draw(st.integers(min_value=1, max_value=28))
    hora = draw(st.integers(min_value=0, max_value=23))
    minuto = draw(st.integers(min_value=0, max_value=59))
    segundo = draw(st.integers(min_value=0, max_value=58))
    sufixo = draw(_FRAGMENTO_SINTETICO)
    fragmentos_continuacao = draw(
        st.lists(_FRAGMENTO_SINTETICO, min_size=1, max_size=3)
    )

    parte_hora = f"{hora:02d}:{minuto:02d}:{segundo:02d}.{fracao:0{precisao}d}"
    return _CasoVplInvalido(
        campo_invalido=draw(
            st.sampled_from(("timestamp", "severidade", "mensagem"))
        ),
        timestamp_valido=f"2030-02-{dia:02d} {parte_hora}",
        timestamp_invalido=f"2030-13-{dia:02d} {parte_hora}",
        percentual=(
            f"{draw(st.integers(min_value=0, max_value=100))}."
            f"{draw(st.integers(min_value=0, max_value=99)):02d}%"
        ),
        severidade=draw(
            st.sampled_from(
                ("DEBUG", "INFO", "NOTICE", "WARNING", "ERR", "CRIT", "ALERT")
            )
        ),
        origem=(
            f"modulo_{draw(st.integers(min_value=1, max_value=99))}.c:"
            f"{draw(st.integers(min_value=1, max_value=999))}"
        ),
        mensagem=f"evento_vpl_sintetico_{sufixo}",
        continuacoes=tuple(
            f"continuaÃ§Ã£o_sintÃ©tica_{indice}_{fragmento}"
            for indice, fragmento in enumerate(fragmentos_continuacao, start=1)
        ),
        terminador_cabecalho=draw(st.sampled_from(("\n", "\r\n"))),
        terminador_continuacao=draw(st.sampled_from(("\n", "\r\n"))),
    )


def _formatar_cabecalho_vpl(
    campos: dict[str, str],
    percentual: str,
    origem: str,
) -> str:
    cabecalho = (
        f"{campos['timestamp']} {percentual} "
        f"[{campos['severidade']}] {origem}"
    )
    if campos["mensagem"]:
        cabecalho += f" {campos['mensagem']}"
    return cabecalho


def _processar_fonte(
    parser: VplParser | OrkParser,
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


# Feature: log-analyzer-phase-2, Property 2: Parsing VPL invÃ¡lido falha sem perda
@given(caso=_casos_vpl_invalidos())
@settings(max_examples=100, deadline=500)
def test_property_02_parsing_vpl_invalido_falha_sem_perda(
    caso: _CasoVplInvalido,
    tmp_path_factory,
) -> None:
    """Uma falha VPL isolada preserva sua origem e nÃ£o interrompe VPL/ORK.

    **Validates: Requirements 2.5, 5.1, 5.2, 5.3, 15.1, 15.2**
    """

    tmp_path = tmp_path_factory.mktemp("property-02-vpl-invalido")
    campos_validos = {
        "timestamp": caso.timestamp_valido,
        "severidade": caso.severidade,
        "mensagem": caso.mensagem,
    }
    campos_mutados = dict(campos_validos)
    if caso.campo_invalido == "timestamp":
        campos_mutados["timestamp"] = caso.timestamp_invalido
    elif caso.campo_invalido == "severidade":
        campos_mutados["severidade"] = "NIVEL_INVALIDO"
    else:
        campos_mutados["mensagem"] = ""

    assert tuple(
        nome
        for nome in campos_validos
        if campos_mutados[nome] != campos_validos[nome]
    ) == (caso.campo_invalido,)
    event(f"campo obrigatÃ³rio invalidado: {caso.campo_invalido}")
    event(f"terminador do cabeÃ§alho invÃ¡lido: {caso.terminador_cabecalho!r}")

    cabecalho_invalido = _formatar_cabecalho_vpl(
        campos_mutados,
        caso.percentual,
        caso.origem,
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

    cabecalho_vpl_subsequente = _formatar_cabecalho_vpl(
        campos_validos | {"mensagem": f"{caso.mensagem}_subsequente"},
        caso.percentual,
        caso.origem,
    )
    prefixo_vpl = _CABECALHO_VPL_ANTERIOR + caso.terminador_continuacao
    conteudo_vpl = (
        prefixo_vpl + texto_bloco_invalido + cabecalho_vpl_subsequente
    )
    caminho_vpl = tmp_path / "vpl-property-02-sintetico.log"
    caminho_vpl.write_bytes(conteudo_vpl.encode("utf-8"))

    mensagem_ork = f"evento_ork_sintetico_{caso.mensagem}_subsequente"
    conteudo_ork = (
        "2030-02-03T07:05:07.123+00:00 host-sintetico.invalid "
        f"worker[17]: INFO - property.synthetic - {mensagem_ork}"
    )
    caminho_ork = tmp_path / "ork-property-02-sintetico.log"
    caminho_ork.write_bytes(conteudo_ork.encode("utf-8"))

    parser_vpl = VplParser()
    fonte_vpl = _processar_fonte(parser_vpl, caminho_vpl, _TOKEN_VPL)
    parser_ork = OrkParser()
    fonte_ork = _processar_fonte(parser_ork, caminho_ork, _TOKEN_ORK)

    assert tuple(bloco.tipo_inicio for bloco in fonte_vpl.blocos) == (
        TipoInicio.CABECALHO_VALIDO,
        TipoInicio.CABECALHO_APARENTE_INVALIDO,
        TipoInicio.CABECALHO_VALIDO,
    )
    assert len(fonte_vpl.entradas) == 3
    bloco_invalido = fonte_vpl.blocos[1]
    entrada_invalida = fonte_vpl.entradas[1]
    linha_inicial = 2
    linha_final = linha_inicial + len(caso.continuacoes)
    inicio_byte = len(prefixo_vpl.encode("utf-8"))
    fim_byte = inicio_byte + len(texto_bloco_invalido.encode("utf-8"))

    assert bloco_invalido.intervalo_linhas == (linha_inicial, linha_final)
    assert bloco_invalido.intervalo_bytes == (inicio_byte, fim_byte)
    assert bloco_invalido.texto_original == texto_bloco_invalido
    assert bloco_invalido.sha256 == hashlib.sha256(
        texto_bloco_invalido.encode("utf-8")
    ).hexdigest()
    assert entrada_invalida.interpretada is False
    assert entrada_invalida.texto_ref == bloco_invalido.texto_ref
    assert entrada_invalida.texto_ref.arquivo_token == _TOKEN_VPL
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
    assert falha.codigo == "VPL_CABECALHO_APARENTE_INVALIDO"
    assert falha.proveniencia.arquivo_token == _TOKEN_VPL
    assert falha.proveniencia.entrada_id == entrada_invalida.entrada_id
    assert falha.proveniencia.linha_inicial == linha_inicial
    assert falha.proveniencia.linha_final == linha_final

    assert fonte_vpl.blocos[2].linha_inicial == linha_final + 1
    assert fonte_vpl.entradas[2].interpretada is True
    assert len(fonte_ork.blocos) == len(fonte_ork.entradas) == 1
    assert fonte_ork.blocos[0].tipo_inicio is TipoInicio.CABECALHO_VALIDO
    assert fonte_ork.entradas[0].interpretada is True

    materializacao = MaterializadorSeletivo(
        (fonte_vpl.fonte, fonte_ork.fonte)
    ).materializar(fonte_vpl.entradas + fonte_ork.entradas)
    assert materializacao.falhas == ()
    assert len(materializacao.entradas) == 4
    textos = materializacao.texto_por_entrada_id()
    assert textos[entrada_invalida.entrada_id] == texto_bloco_invalido
    assert textos[fonte_vpl.entradas[2].entrada_id] == cabecalho_vpl_subsequente
    assert textos[fonte_ork.entradas[0].entrada_id] == conteudo_ork

    materializada_invalida = parser_vpl.interpretar_entrada(
        textos[entrada_invalida.entrada_id]
    )
    assert materializada_invalida.interpretada is False
    assert materializada_invalida.texto_original == texto_bloco_invalido
    assert materializada_invalida.posicao_inicial == 1
    assert materializada_invalida.posicao_final == 1 + len(caso.continuacoes)
    assert parser_vpl.imprimir_entrada(materializada_invalida) == (
        texto_bloco_invalido
    )

    vpl_subsequente = parser_vpl.interpretar_entrada(
        textos[fonte_vpl.entradas[2].entrada_id]
    )
    ork_subsequente = parser_ork.interpretar_entrada(
        textos[fonte_ork.entradas[0].entrada_id]
    )
    assert vpl_subsequente.interpretada is True
    assert vpl_subsequente.aplicacao == "VPL"
    assert vpl_subsequente.mensagem == f"{caso.mensagem}_subsequente"
    assert ork_subsequente.interpretada is True
    assert ork_subsequente.aplicacao == "ORK"
    assert ork_subsequente.mensagem == mensagem_ork
