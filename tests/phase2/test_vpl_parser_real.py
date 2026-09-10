"""Testes unitários dos perfis VPL real e legado da Fase 2.

Todos os cabeçalhos são construídos localmente com valores sintéticos. UUIDs são
criados em tempo de teste e arquivos existem somente sob ``tmp_path`` por meio
dos builders compartilhados da Fase 2.
"""

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from log_analyzer.apps.vpl import VplParser
from log_analyzer.core.interfaces import Parser_de_Bloco, TipoInicio
from log_analyzer.core.modelos import (
    CampoEstruturado,
    EntradaDeLog,
    IdentificadorTecnico,
    TipoIdentificador,
)
from log_analyzer.core.multiline import AgrupadorMultiline
from log_analyzer.core.streaming import LeitorStreaming, LinhaFisica
from tests.phase2.strategies import (
    BlockSpec,
    LineKind,
    PhysicalLineSpec,
    TemporaryLogFactory,
    assert_no_raw_source_reference,
)

_NIVEIS_VPL = frozenset(
    {"DEBUG", "INFO", "NOTICE", "WARNING", "ERR", "CRIT", "ALERT"}
)


def _cabecalho_real(
    *,
    timestamp: str = "2030-02-03 04:05:06.123456",
    percentual: str = "98.75%",
    severidade: str = "NOTICE",
    origem: str = "mod_sintetico.c:42",
    mensagem: str = "evento sintético",
    uuid_canal: str | None = None,
) -> str:
    """Monta somente a gramática VPL real com dados sintéticos explícitos."""

    prefixo_uuid = f"{uuid_canal} " if uuid_canal is not None else ""
    texto = (
        f"{prefixo_uuid}{timestamp} {percentual} "
        f"[{severidade}] {origem} {mensagem}"
    )
    assert_no_raw_source_reference(texto)
    return texto


def _cabecalho_legado(
    *,
    timestamp: str = "2030-02-03 04:05:06.007",
    severidade: str = "NOTICE",
    origem: str = "modulo_sintetico.c:42",
    mensagem: str = "evento sintético",
) -> str:
    """Monta o perfil sintético da Fase 1 sem consultar qualquer fixture."""

    texto = f"{timestamp} [{severidade}] {origem} {mensagem}"
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


def _campo(entrada: EntradaDeLog, nome: str) -> CampoEstruturado:
    encontrados = tuple(
        campo for campo in entrada.campos_estruturados if campo.nome == nome
    )
    assert len(encontrados) == 1, f"campo sintético inesperado: {nome}"
    return encontrados[0]


def _identificador(
    entrada: EntradaDeLog,
    tipo: TipoIdentificador,
    nome: str,
) -> IdentificadorTecnico:
    encontrados = tuple(
        identificador
        for identificador in entrada.identificadores
        if identificador.tipo is tipo and identificador.nome_campo == nome
    )
    assert len(encontrados) == 1, (
        f"identificador sintético inesperado: {tipo.value}/{nome}"
    )
    return encontrados[0]


def _assert_campo_posicionado(
    entrada: EntradaDeLog,
    campo: CampoEstruturado,
) -> None:
    """Confere que valor, span e linhas apontam para o texto preservado."""

    proveniencia = campo.proveniencia
    inicio = proveniencia.span_inicial
    fim = proveniencia.span_final
    assert inicio is not None
    assert fim is not None
    assert entrada.texto_original[inicio:fim] == campo.valor_original
    assert proveniencia.arquivo_token == entrada.arquivo_token
    assert proveniencia.entrada_id == entrada.entrada_id
    assert proveniencia.nome_campo == campo.nome
    assert proveniencia.regra_extracao

    linha_base = entrada.posicao_inicial or 1
    linha_inicial = linha_base + entrada.texto_original.count("\n", 0, inicio)
    ultimo_indice = inicio if fim <= inicio else fim - 1
    linha_final = linha_base + entrada.texto_original.count(
        "\n", 0, ultimo_indice + 1
    )
    if fim > inicio and entrada.texto_original[fim - 1] == "\n":
        linha_final -= 1
    assert proveniencia.linha_inicial == linha_inicial
    assert proveniencia.linha_final == linha_final


def _assinatura_campos(
    entrada: EntradaDeLog,
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (campo.nome, campo.valor_original)
        for campo in entrada.campos_estruturados
    )


def _assinatura_identificadores(
    entrada: EntradaDeLog,
) -> tuple[tuple[object, str, str, str, str], ...]:
    return tuple(
        (
            identificador.tipo,
            identificador.namespace_comparacao,
            identificador.nome_campo,
            identificador.valor_original,
            identificador.valor_normalizado,
        )
        for identificador in entrada.identificadores
    )


def test_detector_trivalente_prioriza_real_e_preserva_legado() -> None:
    parser = VplParser()
    real = _cabecalho_real()
    legado = _cabecalho_legado()
    aparente_invalido = _cabecalho_real(
        percentual="percentual-invalido"
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


@pytest.mark.parametrize(
    ("fracao", "microssegundos"),
    (
        pytest.param("1", 100_000, id="precisao-1"),
        pytest.param("12", 120_000, id="precisao-2"),
        pytest.param("123", 123_000, id="precisao-3"),
        pytest.param("1234", 123_400, id="precisao-4"),
        pytest.param("12345", 123_450, id="precisao-5"),
        pytest.param("123456", 123_456, id="precisao-6"),
    ),
)
def test_perfil_real_estrutura_todos_os_campos_unicode_e_precisao(
    fracao: str,
    microssegundos: int,
) -> None:
    parser = VplParser()
    timestamp = f"2030-02-03 04:05:06.{fracao}"
    mensagem = "Ação Unicode: café, çã, Ω, 漢字 e emoji 😀"
    texto = _cabecalho_real(timestamp=timestamp, mensagem=mensagem)

    entrada = parser.interpretar_entrada(texto)

    assert entrada.interpretada is True
    assert entrada.aplicacao == "VPL"
    assert entrada.ordem_de_leitura == 0
    assert entrada.texto_original == texto
    assert entrada.carimbo_de_tempo == datetime(
        2030, 2, 3, 4, 5, 6, microssegundos
    )
    assert entrada.timestamp_original == timestamp
    assert entrada.timestamp_normalizado == datetime(
        2030,
        2,
        3,
        7,
        5,
        6,
        microssegundos,
        tzinfo=timezone.utc,
    )
    assert entrada.precisao_fracionaria == len(fracao)
    assert entrada.nivel_de_severidade == "NOTICE"
    assert entrada.origem_evento == "mod_sintetico.c:42"
    assert entrada.mensagem == mensagem
    assert entrada.formato_origem == "vpl-real"
    assert entrada.posicao_inicial == entrada.posicao_final == 1
    assert entrada.falhas == ()
    assert entrada.identificadores == ()

    assert {
        campo.nome: campo.valor_original
        for campo in entrada.campos_estruturados
    } == {
        "timestamp": timestamp,
        "percentual_operacional": "98.75%",
        "severidade": "NOTICE",
        "origem": "mod_sintetico.c:42",
        "mensagem": mensagem,
    }
    for campo in entrada.campos_estruturados:
        _assert_campo_posicionado(entrada, campo)


def test_identificadores_somente_em_campos_e_posicoes_aprovadas() -> None:
    parser = VplParser()
    uuid_prefixo = str(uuid4()).upper()
    uuid_canal_rotulado = str(uuid4())
    uuid_sessao = str(uuid4()).upper()
    uuid_incidental = str(uuid4())
    mensagem = (
        "Canal sofia/external/<CALL_ID_1>@sip.invalid "
        'CALLID="<CALL_ID_2>" '
        "CallId: '<CALL_ID_3>' "
        "call-id=(<CALL_ID_4>) "
        f"channel_uuid=<{uuid_canal_rotulado}> "
        f"session-id='{uuid_sessao}' "
        f"trace_uuid={uuid_incidental} incidental={uuid_incidental} "
        "callid=<CALL_ID_5> CALL-ID=<CALL_ID_6>"
    )
    texto = _cabecalho_real(
        uuid_canal=uuid_prefixo,
        mensagem=mensagem,
    )

    entrada = parser.interpretar_entrada(texto)

    assert entrada.interpretada is True
    esperados = {
        (TipoIdentificador.UUID_CANAL, "ChannelUuid"): (
            uuid_prefixo,
            uuid_prefixo.casefold(),
            "uuid_canal",
        ),
        (TipoIdentificador.CHAMADA_EXTERNA, "SipChannelUser"): (
            "<CALL_ID_1>",
            "call_id_1",
            "chamada_externa",
        ),
        (TipoIdentificador.CALL_ID, "CALLID"): (
            '"<CALL_ID_2>"',
            "call_id_2",
            "chamada_externa",
        ),
        (TipoIdentificador.CALL_ID, "CallId"): (
            "'<CALL_ID_3>'",
            "call_id_3",
            "chamada_externa",
        ),
        (TipoIdentificador.CALL_ID, "call-id"): (
            "(<CALL_ID_4>)",
            "call_id_4",
            "chamada_externa",
        ),
        (TipoIdentificador.UUID_CANAL, "channel_uuid"): (
            f"<{uuid_canal_rotulado}>",
            uuid_canal_rotulado.casefold(),
            "uuid_canal",
        ),
        (TipoIdentificador.UUID_SESSAO, "session-id"): (
            f"'{uuid_sessao}'",
            uuid_sessao.casefold(),
            "uuid_sessao",
        ),
    }
    assert {
        (identificador.tipo, identificador.nome_campo)
        for identificador in entrada.identificadores
    } == set(esperados)

    for (tipo, nome), (original, normalizado, namespace) in esperados.items():
        identificador = _identificador(entrada, tipo, nome)
        campo = _campo(entrada, nome)
        assert identificador.valor_original == original
        assert identificador.valor_normalizado == normalizado
        assert identificador.namespace_comparacao == namespace
        assert identificador.proveniencia == campo.proveniencia
        assert identificador.proveniencia.linha_inicial == 1
        assert identificador.proveniencia.linha_final == 1
        _assert_campo_posicionado(entrada, campo)

    assert all(
        identificador.valor_normalizado != uuid_incidental.casefold()
        for identificador in entrada.identificadores
    )
    assert {campo.nome for campo in entrada.campos_estruturados}.isdisjoint(
        {"trace_uuid", "incidental", "callid", "CALL-ID"}
    )


def test_campos_call_id_aprovados_possuem_casing_exato() -> None:
    parser = VplParser()
    texto = _cabecalho_real(
        timestamp="2030-02-03 04:05:06.1",
        percentual="1%",
        severidade="INFO",
        origem="origem.c:1",
        mensagem=(
            "CALLID=<CALL_ID_1> CallId=<CALL_ID_2> "
            "call-id=<CALL_ID_3> callid=<CALL_ID_4> "
            "CALL-ID=<CALL_ID_5> xCallId=<CALL_ID_6>"
        ),
    )

    entrada = parser.interpretar_entrada(texto)

    assert entrada.interpretada is True
    assert {
        identificador.nome_campo for identificador in entrada.identificadores
    } == {"CALLID", "CallId", "call-id"}
    assert {
        identificador.valor_normalizado
        for identificador in entrada.identificadores
    } == {"call_id_1", "call_id_2", "call_id_3"}


def test_multiline_preserva_unicode_terminadores_posicoes_e_isola_invalido(
    tmp_path: Path,
) -> None:
    parser = VplParser()
    uuid_sessao = str(uuid4())
    cabecalho = _cabecalho_real(
        timestamp="2030-02-03 04:05:06.123",
        percentual="75%",
        severidade="INFO",
        origem="origem.c:7",
        mensagem="mensagem Unicode á",
    )
    continuacao = f"continuação Ω session_uuid=<{uuid_sessao}>"
    invalido = _cabecalho_real(
        timestamp="2030-02-03 04:05:06.123",
        percentual="75%",
        severidade="DESCONHECIDO",
        origem="origem.c:8",
        mensagem="mensagem inválida",
    )
    blocos_sinteticos = (
        BlockSpec(
            (
                PhysicalLineSpec(LineKind.VALID_HEADER, cabecalho, "\r\n"),
                PhysicalLineSpec(LineKind.CONTINUATION, continuacao, "\n"),
            )
        ),
        BlockSpec(
            (
                PhysicalLineSpec(LineKind.INVALID_HEADER, invalido, "\n"),
                PhysicalLineSpec(
                    LineKind.CONTINUATION,
                    "continuação do inválido",
                    "",
                ),
            )
        ),
    )
    arquivo = TemporaryLogFactory(tmp_path).write_blocks(
        blocos_sinteticos,
        filename="vpl-sintetico.log",
    )

    leitor = LeitorStreaming(arquivo.path, "<ARQUIVO_1>")
    agrupador = AgrupadorMultiline.para_parser(parser, "<ARQUIVO_1>")
    blocos = tuple(agrupador.agrupar(leitor))

    assert len(blocos) == 2
    assert blocos[0].intervalo_linhas == (1, 2)
    assert blocos[0].texto_original == f"{cabecalho}\r\n{continuacao}\n"
    assert blocos[1].intervalo_linhas == (3, 4)
    assert blocos[1].texto_original == (
        f"{invalido}\ncontinuação do inválido"
    )
    assert blocos[1].tipo_inicio is TipoInicio.CABECALHO_APARENTE_INVALIDO

    indexada_valida = parser.interpretar_bloco(blocos[0])
    indexada_invalida = parser.interpretar_bloco(blocos[1])
    assert indexada_valida.interpretada is True
    assert indexada_valida.texto_ref.linha_inicial == 1
    assert indexada_valida.texto_ref.linha_final == 2
    assert {campo.nome for campo in indexada_valida.cabecalho} == {
        "timestamp",
        "percentual_operacional",
        "severidade",
        "origem",
    }
    assert indexada_valida.identificadores_digest == ()
    assert indexada_invalida.interpretada is False
    assert indexada_invalida.falhas[0].codigo == (
        "VPL_CABECALHO_APARENTE_INVALIDO"
    )
    assert indexada_invalida.falhas[0].proveniencia.linha_inicial == 3
    assert indexada_invalida.falhas[0].proveniencia.linha_final == 4

    materializada = parser.interpretar_entrada(
        blocos[0].texto_original or ""
    )
    assert materializada.texto_original == f"{cabecalho}\r\n{continuacao}\n"
    assert materializada.mensagem == (
        f"mensagem Unicode á\r\n{continuacao}\n"
    )
    assert materializada.posicao_inicial == 1
    assert materializada.posicao_final == 2
    identificador_sessao = _identificador(
        materializada,
        TipoIdentificador.UUID_SESSAO,
        "session_uuid",
    )
    assert identificador_sessao.valor_normalizado == uuid_sessao.casefold()
    assert identificador_sessao.proveniencia.linha_inicial == 2
    assert identificador_sessao.proveniencia.linha_final == 2
    _assert_campo_posicionado(
        materializada,
        _campo(materializada, "session_uuid"),
    )


@pytest.mark.parametrize(
    "texto",
    (
        pytest.param(
            _cabecalho_real(timestamp="2030-02-30 04:05:06.123"),
            id="timestamp-calendario-invalido",
        ),
        pytest.param(
            _cabecalho_real(timestamp="2030-02-03 04:05:06"),
            id="timestamp-sem-fracao",
        ),
        pytest.param(
            _cabecalho_real(timestamp="2030-02-03 04:05:06.1234567"),
            id="timestamp-precisao-maior-que-seis",
        ),
        pytest.param(
            _cabecalho_real(percentual="-1%"),
            id="percentual-invalido",
        ),
        pytest.param(
            _cabecalho_real(severidade="UNKNOWN"),
            id="severidade-desconhecida",
        ),
        pytest.param(
            _cabecalho_real(severidade="INFO").replace("[INFO]", "INFO", 1),
            id="severidade-sem-delimitadores",
        ),
        pytest.param(
            "2030-02-03 04:05:06.123 75% [INFO]",
            id="origem-ausente",
        ),
        pytest.param(
            _cabecalho_real(mensagem="").rstrip(),
            id="mensagem-ausente",
        ),
        pytest.param(
            _cabecalho_real(
                uuid_canal="00000000-0000-0000-0000-00000000000G"
            ),
            id="uuid-posicional-invalido",
        ),
    ),
)
def test_mutacoes_de_cabecalho_real_sao_nao_interpretadas_sem_perda(
    texto: str,
) -> None:
    parser = VplParser()

    assert (
        parser.detectar_inicio(_linha(texto))
        is TipoInicio.CABECALHO_APARENTE_INVALIDO
    )
    entrada = parser.interpretar_entrada(texto)

    assert entrada.interpretada is False
    assert entrada.texto_original == texto
    assert entrada.posicao_inicial == entrada.posicao_final == 1
    assert entrada.campos_estruturados == ()
    assert entrada.identificadores == ()
    assert len(entrada.falhas) == 1
    assert entrada.falhas[0].codigo == "VPL_CABECALHO_APARENTE_INVALIDO"
    assert entrada.falhas[0].proveniencia.linha_inicial == 1
    assert entrada.falhas[0].proveniencia.linha_final == 1
    assert parser.imprimir_entrada(entrada) == texto


def test_cabecalho_aparente_invalido_multiline_preserva_texto_e_posicoes() -> None:
    parser = VplParser()
    texto = (
        _cabecalho_real(timestamp="2030-13-03 04:05:06.123")
        + "\ncontinuação preservada"
    )

    entrada = parser.interpretar_entrada(texto)

    assert entrada.interpretada is False
    assert entrada.texto_original == texto
    assert entrada.posicao_inicial == 1
    assert entrada.posicao_final == 2
    assert entrada.falhas[0].codigo == "VPL_CABECALHO_APARENTE_INVALIDO"
    assert entrada.falhas[0].proveniencia.linha_inicial == 1
    assert entrada.falhas[0].proveniencia.linha_final == 2
    assert parser.imprimir_entrada(entrada) == texto


def test_pretty_printer_real_faz_round_trip_de_todos_os_campos_e_ids() -> None:
    parser = VplParser()
    uuid_canal = str(uuid4())
    uuid_sessao = str(uuid4())
    texto = _cabecalho_real(
        uuid_canal=uuid_canal,
        timestamp="2030-02-03 04:05:06.12",
        percentual="8.5%",
        severidade="DEBUG",
        origem="origem.c:9",
        mensagem=(
            "canal sofia/internal/<CALL_ID_1>@sip.invalid "
            "CallId=<CALL_ID_2>\n"
            f"detalhe Unicode Ω session_uuid=<{uuid_sessao}>"
        ),
    )

    primeira = parser.interpretar_entrada(texto)
    impresso = parser.imprimir_entrada(primeira)
    segunda = parser.interpretar_entrada(impresso)

    assert primeira.interpretada is True
    assert impresso == texto
    assert segunda.interpretada is True
    assert segunda.formato_origem == primeira.formato_origem == "vpl-real"
    assert segunda.carimbo_de_tempo == primeira.carimbo_de_tempo
    assert segunda.timestamp_original == primeira.timestamp_original
    assert segunda.timestamp_normalizado == primeira.timestamp_normalizado
    assert segunda.precisao_fracionaria == primeira.precisao_fracionaria
    assert segunda.nivel_de_severidade == primeira.nivel_de_severidade
    assert segunda.origem_evento == primeira.origem_evento
    assert segunda.mensagem == primeira.mensagem
    assert segunda.posicao_inicial == primeira.posicao_inicial
    assert segunda.posicao_final == primeira.posicao_final
    assert segunda.falhas == primeira.falhas
    assert _assinatura_campos(segunda) == _assinatura_campos(primeira)
    assert _assinatura_identificadores(segunda) == (
        _assinatura_identificadores(primeira)
    )


@pytest.mark.parametrize("nivel", sorted(_NIVEIS_VPL))
def test_fallback_legado_mantem_contrato_caracterizado_da_fase_1(
    nivel: str,
) -> None:
    parser = VplParser()
    mensagem = "evento Unicode ç Ω CallId=<CALL_ID_9>"
    texto = _cabecalho_legado(severidade=nivel, mensagem=mensagem)

    entrada = parser.interpretar_entrada(texto)

    assert parser.niveis_de_severidade == _NIVEIS_VPL
    assert entrada.interpretada is True
    assert entrada.texto_original == texto
    assert entrada.formato_origem == "vpl-legado"
    assert entrada.carimbo_de_tempo == datetime(2030, 2, 3, 4, 5, 6, 7_000)
    assert entrada.timestamp_original == "2030-02-03 04:05:06.007"
    assert entrada.timestamp_normalizado == datetime(
        2030, 2, 3, 7, 5, 6, 7_000, tzinfo=timezone.utc
    )
    assert entrada.precisao_fracionaria == 3
    assert entrada.nivel_de_severidade == nivel
    assert entrada.origem_evento == "modulo_sintetico.c:42"
    assert entrada.mensagem == mensagem
    assert {
        campo.nome: campo.valor_original
        for campo in entrada.campos_estruturados
    } == {
        "timestamp": "2030-02-03 04:05:06.007",
        "severidade": nivel,
        "origem": "modulo_sintetico.c:42",
        "mensagem": mensagem,
        "CallId": "<CALL_ID_9>",
    }
    assert _identificador(
        entrada,
        TipoIdentificador.CALL_ID,
        "CallId",
    ).valor_normalizado == "call_id_9"
    assert parser.imprimir_entrada(entrada) == _cabecalho_legado(
        severidade=nivel,
        origem="modulo_sintetico.c:42",
        mensagem=mensagem,
    )


def test_round_trip_legado_canonico_preserva_campos_e_identificadores() -> None:
    parser = VplParser()
    texto = _cabecalho_legado(
        origem="vpl_source",
        mensagem="evento sintético CallId=<CALL_ID_10>",
    )

    primeira = parser.interpretar_entrada(texto)
    segunda = parser.interpretar_entrada(parser.imprimir_entrada(primeira))

    assert primeira.interpretada is True
    assert segunda.interpretada is True
    assert segunda.formato_origem == primeira.formato_origem == "vpl-legado"
    assert segunda.carimbo_de_tempo == primeira.carimbo_de_tempo
    assert segunda.timestamp_original == primeira.timestamp_original
    assert segunda.timestamp_normalizado == primeira.timestamp_normalizado
    assert segunda.precisao_fracionaria == primeira.precisao_fracionaria
    assert segunda.nivel_de_severidade == primeira.nivel_de_severidade
    assert segunda.origem_evento == primeira.origem_evento
    assert segunda.mensagem == primeira.mensagem
    assert _assinatura_campos(segunda) == _assinatura_campos(primeira)
    assert _assinatura_identificadores(segunda) == (
        _assinatura_identificadores(primeira)
    )
