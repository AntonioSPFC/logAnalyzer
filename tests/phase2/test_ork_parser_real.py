"""Testes unitários sintéticos dos perfis ORK real e legado.

A cobertura desta tarefa usa apenas valores marcados como sintéticos,
placeholders tipados e arquivos criados pela factory segura da Fase 2.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from log_analyzer.apps.ork import OrkParser
from log_analyzer.core.interfaces import Parser_de_Bloco, TipoInicio
from log_analyzer.core.modelos import EntradaDeLog, TipoIdentificador
from log_analyzer.core.multiline import AgrupadorMultiline
from log_analyzer.core.streaming import LeitorStreaming, LinhaFisica
from tests.phase2.strategies import (
    TemporaryLogFactory,
    assert_no_raw_source_reference,
)

_TIMESTAMP_REAL = "2030-02-03T04:05:06.123456-03:00"
_HOST = "ork-node.synthetic.invalid"
_PROCESSO = "ork-worker"
_PID = "04242"
_LOGGER = "agent.synthetic"


def _cabecalho_real(
    *,
    timestamp: str = _TIMESTAMP_REAL,
    host: str = _HOST,
    processo: str = _PROCESSO,
    pid: str = _PID,
    severidade: str = "INFO",
    logger: str = _LOGGER,
    mensagem: str = "evento sintético",
) -> str:
    """Monta exclusivamente a gramática ORK real com dados sintéticos."""

    texto = (
        f"{timestamp} {host} {processo}[{pid}]: "
        f"{severidade} - {logger} - {mensagem}"
    )
    assert_no_raw_source_reference(texto)
    return texto


def _linha(texto: str) -> LinhaFisica:
    tamanho = len((texto + "\n").encode("utf-8"))
    return LinhaFisica(
        numero_1_based=1,
        inicio_byte=0,
        fim_byte=tamanho,
        texto=texto,
        terminador="\n",
    )


def _campos(entrada: EntradaDeLog) -> dict[str, str]:
    return {
        campo.nome: campo.valor_original
        for campo in entrada.campos_estruturados
    }


def _assinatura_identificadores(
    entrada: EntradaDeLog,
) -> set[tuple[TipoIdentificador, str, str]]:
    return {
        (
            identificador.tipo,
            identificador.nome_campo,
            identificador.valor_normalizado,
        )
        for identificador in entrada.identificadores
    }


def test_detector_trivalente_prioriza_real_e_preserva_legado() -> None:
    parser = OrkParser()
    real = _cabecalho_real()
    legado = (
        "2030-02-03T04:05:06.123456+00:00 | INFO | "
        "evento sintético"
    )
    aparente_invalido = _cabecalho_real(
        timestamp="2030-02-03T04:05:06.123456"
    )

    assert isinstance(parser, Parser_de_Bloco)
    assert parser.detectar_inicio(_linha(real)) is TipoInicio.CABECALHO_VALIDO
    assert (
        parser.detectar_inicio(_linha(legado))
        is TipoInicio.CABECALHO_VALIDO
    )
    assert (
        parser.detectar_inicio(_linha(aparente_invalido))
        is TipoInicio.CABECALHO_APARENTE_INVALIDO
    )
    assert (
        parser.detectar_inicio(_linha("continuação sintética"))
        is TipoInicio.CONTINUACAO
    )


def test_perfil_real_exige_offset_e_legado_sem_offset_permanece_aceito() -> None:
    parser = OrkParser()
    real_sem_offset = _cabecalho_real(
        timestamp="2030-02-03T04:05:06.123456"
    )

    entrada_real = parser.interpretar_entrada(real_sem_offset)

    assert entrada_real.interpretada is False
    assert entrada_real.texto_original == real_sem_offset
    assert entrada_real.falhas[0].codigo == (
        "ORK_CABECALHO_APARENTE_INVALIDO"
    )
    assert parser.imprimir_entrada(entrada_real) == real_sem_offset

    legado_sem_offset = (
        "2030-02-03T04:05:06.123456 | DEBUG | "
        "evento legado sintético"
    )
    entrada_legada = parser.interpretar_entrada(legado_sem_offset)

    assert entrada_legada.interpretada is True
    assert entrada_legada.formato_origem == "ork-legado"
    assert entrada_legada.timestamp_original == (
        "2030-02-03T04:05:06.123456"
    )
    assert entrada_legada.timestamp_normalizado is None


def test_perfil_real_estrutura_cabecalho_unicode_e_ids_aprovados() -> None:
    parser = OrkParser()
    uuid_sessao = str(uuid4())
    uuid_incidental = str(uuid4())
    logger = f"agent.synthetic;session_uuid={uuid_sessao}"
    mensagem = (
        "Início da ação çã Ω "
        'TelecomCallId="<CALL_ID_1>" '
        "CallId={<CALL_ID_2>} "
        f"incidental={uuid_incidental}"
    )
    texto = _cabecalho_real(logger=logger, mensagem=mensagem)

    entrada = parser.interpretar_entrada(texto)

    assert entrada.interpretada is True
    assert entrada.texto_original == texto
    assert entrada.carimbo_de_tempo == datetime(
        2030,
        2,
        3,
        4,
        5,
        6,
        123456,
        tzinfo=timezone(timedelta(hours=-3)),
    )
    assert entrada.timestamp_original == _TIMESTAMP_REAL
    assert entrada.timestamp_normalizado == datetime(
        2030, 2, 3, 7, 5, 6, 123456, tzinfo=timezone.utc
    )
    assert entrada.precisao_fracionaria == 6
    assert entrada.nivel_de_severidade == "INFO"
    assert entrada.origem_evento == logger
    assert entrada.formato_origem == "ork-real"
    assert entrada.mensagem == mensagem

    campos = _campos(entrada)
    assert campos["timestamp"] == _TIMESTAMP_REAL
    assert campos["host"] == _HOST
    assert campos["processo"] == _PROCESSO
    assert campos["pid"] == _PID
    assert campos["severidade"] == "INFO"
    assert campos["logger"] == logger
    assert campos["mensagem"] == mensagem
    assert campos["TelecomCallId"] == '"<CALL_ID_1>"'
    assert campos["CallId"] == "{<CALL_ID_2>}"
    assert campos["session_uuid"] == uuid_sessao

    assinaturas = _assinatura_identificadores(entrada)
    assert (
        TipoIdentificador.TELECOM_CALL_ID,
        "TelecomCallId",
        "call_id_1",
    ) in assinaturas
    assert (
        TipoIdentificador.CALL_ID,
        "CallId",
        "call_id_2",
    ) in assinaturas
    assert (
        TipoIdentificador.UUID_SESSAO,
        "session_uuid",
        uuid_sessao.casefold(),
    ) in assinaturas
    assert all(
        identificador.valor_normalizado != uuid_incidental.casefold()
        for identificador in entrada.identificadores
    )
    assert all(
        identificador.valor_normalizado not in {_HOST.casefold(), _PID}
        for identificador in entrada.identificadores
    )

    for identificador in entrada.identificadores:
        proveniencia = identificador.proveniencia
        assert proveniencia.nome_campo == identificador.nome_campo
        assert proveniencia.regra_extracao
        assert proveniencia.span_inicial is not None
        assert proveniencia.span_final is not None
        assert (
            texto[proveniencia.span_inicial : proveniencia.span_final]
            == identificador.valor_original
        )


@pytest.mark.parametrize(
    "mutacao",
    [
        {"timestamp": "2030-13-03T04:05:06.123456-03:00"},
        {"host": ""},
        {"processo": ""},
        {"pid": "PID"},
        {"severidade": "NOTICE"},
        {"logger": ""},
        {"mensagem": "   "},
    ],
    ids=[
        "timestamp-invalido",
        "host-ausente",
        "processo-ausente",
        "pid-invalido",
        "severidade-invalida",
        "logger-ausente",
        "mensagem-vazia",
    ],
)
def test_mutacoes_de_campos_obrigatorios_falham_sem_perda(
    mutacao: dict[str, str],
) -> None:
    parser = OrkParser()
    texto = _cabecalho_real(**mutacao)

    entrada = parser.interpretar_entrada(texto)

    assert (
        parser.detectar_inicio(_linha(texto))
        is TipoInicio.CABECALHO_APARENTE_INVALIDO
    )
    assert entrada.interpretada is False
    assert entrada.texto_original == texto
    assert entrada.posicao_inicial == 1
    assert entrada.posicao_final == 1
    assert entrada.falhas[0].codigo == (
        "ORK_CABECALHO_APARENTE_INVALIDO"
    )
    assert parser.imprimir_entrada(entrada) == texto


def test_multiline_preserva_texto_limites_e_ids_em_continuacao(
    synthetic_log_factory: TemporaryLogFactory,
) -> None:
    parser = OrkParser()
    cabecalho = _cabecalho_real(mensagem="mensagem Unicode á")
    continuacao_um = "continuação sintética um"
    continuacao_dois = "detalhe Ω CallId=<CALL_ID_3>"
    invalido = _cabecalho_real(
        severidade="DESCONHECIDO",
        mensagem="mensagem inválida sintética",
    )
    arquivo = synthetic_log_factory.write_lines(
        [
            cabecalho,
            continuacao_um,
            continuacao_dois,
            invalido,
            "continuação do inválido",
        ],
        newline="\r\n",
        final_newline=False,
        filename="ork-synthetic.log",
    )

    leitor = LeitorStreaming(arquivo.path, "<ARQUIVO_1>")
    agrupador = AgrupadorMultiline.para_parser(parser, "<ARQUIVO_1>")
    blocos = tuple(agrupador.agrupar(leitor))

    assert len(blocos) == 2
    assert blocos[0].intervalo_linhas == (1, 3)
    assert blocos[0].texto_original == (
        f"{cabecalho}\r\n{continuacao_um}\r\n{continuacao_dois}\r\n"
    )
    assert blocos[1].intervalo_linhas == (4, 5)
    assert blocos[1].tipo_inicio is TipoInicio.CABECALHO_APARENTE_INVALIDO
    assert blocos[1].texto_original == (
        f"{invalido}\r\ncontinuação do inválido"
    )

    indexada_valida = parser.interpretar_bloco(blocos[0])
    indexada_invalida = parser.interpretar_bloco(blocos[1])
    assert indexada_valida.interpretada is True
    assert indexada_valida.texto_ref.linha_inicial == 1
    assert indexada_valida.texto_ref.linha_final == 3
    assert {campo.nome for campo in indexada_valida.cabecalho} == {
        "timestamp",
        "host",
        "processo",
        "pid",
        "severidade",
        "logger",
    }
    assert indexada_valida.identificadores_digest == ()
    assert indexada_invalida.interpretada is False
    assert indexada_invalida.falhas[0].codigo == (
        "ORK_CABECALHO_APARENTE_INVALIDO"
    )

    materializada = parser.interpretar_entrada(
        blocos[0].texto_original or ""
    )
    assert materializada.mensagem == (
        f"mensagem Unicode á\r\n{continuacao_um}\r\n"
        f"{continuacao_dois}\r\n"
    )
    call_id = next(
        identificador
        for identificador in materializada.identificadores
        if identificador.nome_campo == "CallId"
    )
    assert call_id.valor_normalizado == "call_id_3"
    assert call_id.proveniencia.linha_inicial == 3
    assert call_id.proveniencia.linha_final == 3


def test_pretty_printer_real_faz_round_trip_com_multiline() -> None:
    parser = OrkParser()
    uuid_sessao = str(uuid4())
    texto = _cabecalho_real(
        timestamp="2031-04-05T06:07:08.12Z",
        host="roundtrip-node.synthetic.invalid",
        processo="roundtrip-worker",
        pid="7001",
        severidade="WARN",
        logger=f"session_uuid={uuid_sessao}",
        mensagem=(
            "ação sintética TelecomCallId=<CALL_ID_RT>\n"
            "detalhe Unicode 漢字 CallId='<CALL_ID_RT>'"
        ),
    )

    primeira = parser.interpretar_entrada(texto)
    impresso = parser.imprimir_entrada(primeira)
    segunda = parser.interpretar_entrada(impresso)

    assert primeira.interpretada is True
    assert segunda.interpretada is True
    assert segunda.formato_origem == primeira.formato_origem == "ork-real"
    assert segunda.carimbo_de_tempo == primeira.carimbo_de_tempo
    assert segunda.timestamp_original == primeira.timestamp_original
    assert segunda.timestamp_normalizado == primeira.timestamp_normalizado
    assert segunda.precisao_fracionaria == primeira.precisao_fracionaria
    assert segunda.nivel_de_severidade == primeira.nivel_de_severidade
    assert segunda.origem_evento == primeira.origem_evento
    assert segunda.mensagem == primeira.mensagem
    assert [
        (campo.nome, campo.valor_original)
        for campo in segunda.campos_estruturados
    ] == [
        (campo.nome, campo.valor_original)
        for campo in primeira.campos_estruturados
    ]
    assert _assinatura_identificadores(
        segunda
    ) == _assinatura_identificadores(primeira)


def test_fallback_legado_mantem_contrato_pipe_e_round_trip() -> None:
    parser = OrkParser()
    texto = (
        "2032-05-06T07:08:09.123000+00:00 | info | "
        "evento sintético | detalhe adicional"
    )

    primeira = parser.interpretar_entrada(texto)
    impresso = parser.imprimir_entrada(primeira)
    segunda = parser.interpretar_entrada(impresso)

    assert primeira.interpretada is True
    assert primeira.formato_origem == "ork-legado"
    assert primeira.nivel_de_severidade == "INFO"
    assert primeira.mensagem == "evento sintético | detalhe adicional"
    assert impresso == (
        "2032-05-06T07:08:09.123000+00:00 | info | "
        "evento sintético | detalhe adicional"
    )
    assert segunda.interpretada is True
    assert segunda.formato_origem == "ork-legado"
    assert segunda.carimbo_de_tempo == primeira.carimbo_de_tempo
    assert segunda.timestamp_original == primeira.timestamp_original
    assert segunda.timestamp_normalizado == primeira.timestamp_normalizado
    assert segunda.precisao_fracionaria == primeira.precisao_fracionaria
    assert segunda.nivel_de_severidade == primeira.nivel_de_severidade
    assert segunda.mensagem == primeira.mensagem

    construida_sem_campos = EntradaDeLog(
        texto_original="entrada construída sintética",
        aplicacao="ORK",
        ordem_de_leitura=0,
        interpretada=True,
        carimbo_de_tempo=datetime(
            2032,
            5,
            6,
            7,
            8,
            9,
            tzinfo=timezone.utc,
        ),
        nivel_de_severidade="WARN",
        mensagem="fallback sintético",
    )
    assert parser.imprimir_entrada(construida_sem_campos) == (
        "2032-05-06T07:08:09+00:00 | WARN | fallback sintético"
    )
