"""Testes unitários da máquina de agrupamento multiline da Fase 2.

Todos os conteúdos e detectores deste módulo são sintéticos. Os testes exercitam
as seis transições da máquina, EOF e preservação lossless sem consultar fontes
locais reais.

Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 15.7.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from log_analyzer.core.interfaces import TipoInicio
from log_analyzer.core.multiline import (
    AgrupadorMultiline,
    BlocoLog,
    EstadoAgrupamento,
)
from log_analyzer.core.streaming import LeitorStreaming, LinhaFisica

_ARQUIVO_TOKEN = "<ARQUIVO_42>"
_TIPOS_POR_MARCADOR = {
    "H": TipoInicio.CABECALHO_VALIDO,
    "I": TipoInicio.CABECALHO_APARENTE_INVALIDO,
    "C": TipoInicio.CONTINUACAO,
}


class _DetectorPorMarcador:
    """Detector trivalente sintético que não recebe linhas indecodificáveis."""

    def __init__(self) -> None:
        self.linhas_inspecionadas: list[int] = []

    def detectar_inicio(self, linha: LinhaFisica) -> TipoInicio:
        assert linha.texto is not None, "o agrupador deve reter UTF-8 inválido"
        self.linhas_inspecionadas.append(linha.numero_1_based)
        marcador, separador, _ = linha.texto.partition("|")
        if not separador or marcador not in _TIPOS_POR_MARCADOR:
            raise AssertionError("linha sintética sem marcador trivalente")
        return _TIPOS_POR_MARCADOR[marcador]


class _DetectorProgramado:
    """Classifica por posição para tornar tempo e conteúdo irrelevantes."""

    def __init__(self, *tipos: TipoInicio) -> None:
        self._tipos = tipos
        self.linhas_inspecionadas: list[int] = []

    def detectar_inicio(self, linha: LinhaFisica) -> TipoInicio:
        self.linhas_inspecionadas.append(linha.numero_1_based)
        return self._tipos[linha.numero_1_based - 1]


def _ler_linhas(
    tmp_path: Path,
    payload: bytes,
    *,
    nome: str,
) -> tuple[LinhaFisica, ...]:
    caminho = tmp_path / nome
    caminho.write_bytes(payload)
    return tuple(LeitorStreaming(caminho, _ARQUIVO_TOKEN))


def _limites(partes: tuple[bytes, ...]) -> list[tuple[int, int]]:
    resultado: list[tuple[int, int]] = []
    inicio = 0
    for parte in partes:
        fim = inicio + len(parte)
        resultado.append((inicio, fim))
        inicio = fim
    return resultado


def _assert_particao_exata(
    blocos: tuple[BlocoLog, ...],
    quantidade_linhas: int,
) -> None:
    numeros = [
        linha.numero_1_based
        for bloco in blocos
        for linha in bloco.linhas
    ]
    assert numeros == list(range(1, quantidade_linhas + 1))
    assert len(numeros) == len(set(numeros))


def test_continuacao_inicial_vira_entrada_nao_interpretada_autonoma(
    tmp_path: Path,
) -> None:
    partes = (
        "C|continuação órfã\r\n".encode(),
        b"H|evento seguinte\n",
    )
    detector = _DetectorPorMarcador()
    agrupador = AgrupadorMultiline(detector, _ARQUIVO_TOKEN)
    linhas = _ler_linhas(
        tmp_path,
        b"".join(partes),
        nome="continuacao-inicial.log",
    )

    primeiro_emitido = agrupador.processar_linha(linhas[0])

    assert len(primeiro_emitido) == 1
    orfa = primeiro_emitido[0]
    assert agrupador.estado is EstadoAgrupamento.SEM_BLOCO
    assert orfa.tipo_inicio is TipoInicio.CONTINUACAO
    assert orfa.entrada_nao_interpretada
    assert orfa.intervalo_linhas == (1, 1)
    assert orfa.intervalo_bytes == (0, len(partes[0]))
    assert orfa.texto_original == partes[0].decode()

    assert agrupador.processar_linha(linhas[1]) == ()
    assert agrupador.estado is EstadoAgrupamento.BLOCO_ABERTO
    segundo_emitido = agrupador.finalizar()
    assert [bloco.tipo_inicio for bloco in segundo_emitido] == [
        TipoInicio.CABECALHO_VALIDO
    ]
    assert segundo_emitido[0].intervalo_linhas == (2, 2)
    assert detector.linhas_inspecionadas == [1, 2]
    _assert_particao_exata((*primeiro_emitido, *segundo_emitido), 2)


def test_cabecalho_aparente_invalido_sem_bloco_abre_bloco_nao_interpretado(
    tmp_path: Path,
) -> None:
    partes = (
        b"I|timestamp-sintetico-invalido\n",
        b"C|detalhe preservado",
    )
    detector = _DetectorPorMarcador()
    agrupador = AgrupadorMultiline(detector, _ARQUIVO_TOKEN)
    linhas = _ler_linhas(
        tmp_path,
        b"".join(partes),
        nome="aparente-invalido-inicial.log",
    )

    assert agrupador.processar_linha(linhas[0]) == ()
    assert agrupador.estado is EstadoAgrupamento.BLOCO_ABERTO
    assert agrupador.processar_linha(linhas[1]) == ()
    (bloco,) = agrupador.finalizar()

    assert bloco.tipo_inicio is TipoInicio.CABECALHO_APARENTE_INVALIDO
    assert bloco.entrada_nao_interpretada
    assert not bloco.interpretavel
    assert bloco.intervalo_linhas == (1, 2)
    assert bloco.texto_original == b"".join(partes).decode()
    assert bloco.terminadores == ("\n", "")
    assert agrupador.estado is EstadoAgrupamento.SEM_BLOCO


def test_continuacoes_em_bloco_aberto_preservam_posicoes_hashes_e_terminadores(
    tmp_path: Path,
) -> None:
    partes = (
        b"H|evento sintetico\n",
        "C|ação α\r\n".encode(),
        b"C|fim-sem-newline",
    )
    payload = b"".join(partes)
    detector = _DetectorPorMarcador()
    agrupador = AgrupadorMultiline(detector, _ARQUIVO_TOKEN)
    linhas = _ler_linhas(
        tmp_path,
        payload,
        nome="preservacao-multiline.log",
    )

    blocos = tuple(agrupador.agrupar(linhas))

    assert len(blocos) == 1
    (bloco,) = blocos
    assert bloco.tipo_inicio is TipoInicio.CABECALHO_VALIDO
    assert bloco.interpretavel
    assert bloco.intervalo_linhas == (1, 3)
    assert bloco.intervalo_bytes == (0, len(payload))
    assert [
        (linha.inicio_byte, linha.fim_byte) for linha in bloco.linhas
    ] == _limites(partes)
    assert bloco.terminadores == ("\n", "\r\n", "")
    assert bloco.texto_original == payload.decode("utf-8")
    assert bloco.hashes_linhas == tuple(
        sha256(parte).hexdigest() for parte in partes
    )
    assert bloco.sha256 == sha256(payload).hexdigest()
    assert bloco.ordem_de_leitura == 0
    assert detector.linhas_inspecionadas == [1, 2, 3]

    referencia = bloco.texto_ref
    assert referencia is not None
    assert (
        referencia.arquivo_token,
        referencia.inicio_byte,
        referencia.fim_byte,
        referencia.linha_inicial,
        referencia.linha_final,
        referencia.sha256,
    ) == (
        _ARQUIVO_TOKEN,
        0,
        len(payload),
        1,
        3,
        sha256(payload).hexdigest(),
    )
    assert agrupador.eof_finalizado
    assert agrupador.finalizar() == ()
    _assert_particao_exata(blocos, 3)


@pytest.mark.parametrize(
    ("marcador_novo", "tipo_novo", "interpretavel"),
    (
        ("H", TipoInicio.CABECALHO_VALIDO, True),
        ("I", TipoInicio.CABECALHO_APARENTE_INVALIDO, False),
    ),
)
def test_novo_cabecalho_fecha_bloco_anterior_e_abre_o_novo(
    tmp_path: Path,
    marcador_novo: str,
    tipo_novo: TipoInicio,
    interpretavel: bool,
) -> None:
    partes = (
        b"H|cabecalho anterior\n",
        b"C|contexto anterior\r\n",
        f"{marcador_novo}|novo inicio".encode(),
    )
    detector = _DetectorPorMarcador()
    agrupador = AgrupadorMultiline(detector, _ARQUIVO_TOKEN)
    linhas = _ler_linhas(
        tmp_path,
        b"".join(partes),
        nome=f"novo-{marcador_novo}.log",
    )

    assert agrupador.processar_linha(linhas[0]) == ()
    assert agrupador.processar_linha(linhas[1]) == ()
    (anterior,) = agrupador.processar_linha(linhas[2])

    assert agrupador.estado is EstadoAgrupamento.BLOCO_ABERTO
    assert anterior.tipo_inicio is TipoInicio.CABECALHO_VALIDO
    assert anterior.intervalo_linhas == (1, 2)
    assert anterior.texto_original == b"".join(partes[:2]).decode()

    (novo,) = agrupador.finalizar()
    assert novo.tipo_inicio is tipo_novo
    assert novo.interpretavel is interpretavel
    assert novo.entrada_nao_interpretada is (not interpretavel)
    assert novo.intervalo_linhas == (3, 3)
    assert novo.inicio_byte == len(b"".join(partes[:2]))
    assert [anterior.ordem_de_leitura, novo.ordem_de_leitura] == [0, 1]
    assert anterior.entrada_id != novo.entrada_id
    _assert_particao_exata((anterior, novo), 3)


def test_linha_indecodificavel_e_autonoma_ou_continuacao_conforme_o_estado(
    tmp_path: Path,
) -> None:
    partes = (
        b"\xff\r\n",
        b"H|bloco aberto\n",
        b"\xfe\n",
        b"H|bloco seguinte",
    )
    detector = _DetectorPorMarcador()
    linhas = _ler_linhas(
        tmp_path,
        b"".join(partes),
        nome="utf8-invalido-multiline.log",
    )

    blocos = tuple(
        AgrupadorMultiline(detector, _ARQUIVO_TOKEN).agrupar(linhas)
    )

    assert [bloco.intervalo_linhas for bloco in blocos] == [
        (1, 1),
        (2, 3),
        (4, 4),
    ]
    assert [bloco.tipo_inicio for bloco in blocos] == [
        TipoInicio.CONTINUACAO,
        TipoInicio.CABECALHO_VALIDO,
        TipoInicio.CABECALHO_VALIDO,
    ]

    orfa, misto, seguinte = blocos
    assert orfa.entrada_nao_interpretada
    assert orfa.possui_falha_decodificacao
    assert orfa.texto_original is None
    assert orfa.hashes_linhas == (sha256(partes[0]).hexdigest(),)
    assert orfa.sha256 == sha256(partes[0]).hexdigest()
    assert orfa.texto_ref is not None

    assert misto.possui_falha_decodificacao
    assert misto.texto_original is None
    assert misto.sha256 is None
    assert misto.texto_ref is None
    assert misto.hashes_linhas == tuple(
        sha256(parte).hexdigest() for parte in partes[1:3]
    )
    assert [
        falha.contexto["codigo"] for falha in misto.falhas_decodificacao
    ] == ["INVALID_UTF8"]
    assert seguinte.texto_original == partes[3].decode()

    # As linhas sem texto jamais são entregues ao detector da aplicação.
    assert detector.linhas_inspecionadas == [2, 4]
    _assert_particao_exata(blocos, 4)


def test_repeticoes_sao_preservadas_sem_agrupar_por_tempo_ou_semantica(
    tmp_path: Path,
) -> None:
    cabecalho_repetido = (
        b"2099-12-31T23:59:59Z SYN_APP SYN_CALL_A\n"
    )
    continuacao_repetida = (
        b"1900-01-01T00:00:00Z SYN_APP SYN_CALL_B\r\n"
    )
    partes = (
        cabecalho_repetido,
        continuacao_repetida,
        cabecalho_repetido,
        continuacao_repetida,
    )
    payload = b"".join(partes)
    detector = _DetectorProgramado(
        TipoInicio.CABECALHO_VALIDO,
        TipoInicio.CONTINUACAO,
        TipoInicio.CABECALHO_VALIDO,
        TipoInicio.CONTINUACAO,
    )
    linhas = _ler_linhas(
        tmp_path,
        payload,
        nome="repeticoes-e-semantica.log",
    )

    blocos = tuple(
        AgrupadorMultiline(detector, _ARQUIVO_TOKEN).agrupar(linhas)
    )

    assert len(blocos) == 2
    primeiro, segundo = blocos
    tamanho_bloco = len(cabecalho_repetido + continuacao_repetida)
    assert [bloco.intervalo_linhas for bloco in blocos] == [(1, 2), (3, 4)]
    assert [bloco.intervalo_bytes for bloco in blocos] == [
        (0, tamanho_bloco),
        (tamanho_bloco, len(payload)),
    ]
    assert [bloco.ordem_de_leitura for bloco in blocos] == [0, 1]
    assert primeiro.entrada_id != segundo.entrada_id

    # Mesmo conteúdo, timestamp e identificadores continuam duas ocorrências.
    assert primeiro.texto_original == segundo.texto_original
    assert primeiro.sha256 == segundo.sha256
    assert primeiro.hashes_linhas == segundo.hashes_linhas
    assert [linha.numero_1_based for linha in primeiro.linhas] == [1, 2]
    assert [linha.numero_1_based for linha in segundo.linhas] == [3, 4]

    # A continuação tem tempo muito anterior e outro valor semântico, mas segue
    # o bloco aberto; somente a decisão trivalente do detector cria fronteiras.
    assert detector.linhas_inspecionadas == [1, 2, 3, 4]
    _assert_particao_exata(blocos, 4)


def test_eof_sem_linhas_nao_emite_bloco_vazio_e_e_idempotente() -> None:
    detector = _DetectorPorMarcador()
    agrupador = AgrupadorMultiline(detector, _ARQUIVO_TOKEN)

    assert tuple(agrupador.agrupar(())) == ()
    assert agrupador.estado is EstadoAgrupamento.SEM_BLOCO
    assert agrupador.eof_finalizado
    assert agrupador.finalizar() == ()
    assert detector.linhas_inspecionadas == []
