"""Property 5: partição determinística de linhas físicas em blocos."""

from __future__ import annotations

import hashlib

from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.strategies import SearchStrategy

from log_analyzer.core.interfaces import TipoInicio
from log_analyzer.core.multiline import AgrupadorMultiline
from log_analyzer.core.streaming import LinhaFisica

_ModeloBloco = tuple[TipoInicio, tuple[int, ...]]
_CasoTrivalente = tuple[tuple[TipoInicio, ...], tuple[LinhaFisica, ...]]


def _modelo_de_particao(tipos: tuple[TipoInicio, ...]) -> tuple[_ModeloBloco, ...]:
    """Modelo sequencial mínimo, independente da máquina de produção."""

    blocos: list[_ModeloBloco] = []
    tipo_aberto: TipoInicio | None = None
    indices_abertos: list[int] = []

    for indice, tipo in enumerate(tipos):
        if tipo is TipoInicio.CONTINUACAO:
            if indices_abertos:
                indices_abertos.append(indice)
            else:
                blocos.append((TipoInicio.CONTINUACAO, (indice,)))
            continue

        if indices_abertos:
            assert tipo_aberto is not None
            blocos.append((tipo_aberto, tuple(indices_abertos)))

        tipo_aberto = tipo
        indices_abertos = [indice]

    if indices_abertos:
        assert tipo_aberto is not None
        blocos.append((tipo_aberto, tuple(indices_abertos)))

    return tuple(blocos)


@st.composite
def _sequencias_trivalentes(draw: st.DrawFn) -> _CasoTrivalente:
    """Gera linhas contíguas sintéticas classificadas nos três estados."""

    tipos = tuple(
        draw(
            st.lists(
                st.sampled_from(tuple(TipoInicio)),
                min_size=0,
                max_size=40,
            )
        )
    )
    terminadores = list(
        draw(
            st.lists(
                st.sampled_from(("\n", "\r\n")),
                min_size=len(tipos),
                max_size=len(tipos),
            )
        )
    )
    if terminadores and draw(st.booleans()):
        terminadores[-1] = ""

    linhas: list[LinhaFisica] = []
    inicio_byte = 0
    for numero, (tipo, terminador) in enumerate(
        zip(tipos, terminadores),
        start=1,
    ):
        texto = f"{tipo.value}|LINHA_SINTETICA_{numero}|Unicode-ação-Ω"
        payload = (texto + terminador).encode("utf-8")
        fim_byte = inicio_byte + len(payload)
        linhas.append(
            LinhaFisica(
                numero_1_based=numero,
                inicio_byte=inicio_byte,
                fim_byte=fim_byte,
                texto=texto,
                terminador=terminador,
                sha256=hashlib.sha256(payload).hexdigest(),
            )
        )
        inicio_byte = fim_byte

    return tipos, tuple(linhas)


_CASOS_TRIVALENTES: SearchStrategy[_CasoTrivalente] = _sequencias_trivalentes()


# Feature: log-analyzer-phase-2, Property 5: Partição determinística de linhas em blocos
@given(caso=_CASOS_TRIVALENTES)
@settings(max_examples=100)
def test_property_05_particao_deterministica_de_linhas_em_blocos(
    caso: _CasoTrivalente,
) -> None:
    """A máquina produz exatamente a partição definida pelo modelo simples.

    **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6**
    """

    tipos, linhas = caso
    tipo_por_numero = dict(enumerate(tipos, start=1))

    def detectar_inicio(linha: LinhaFisica) -> TipoInicio:
        return tipo_por_numero[linha.numero_1_based]

    blocos = tuple(
        AgrupadorMultiline(detectar_inicio, "<ARQUIVO_PBT_5>").agrupar(linhas)
    )
    blocos_repetidos = tuple(
        AgrupadorMultiline(detectar_inicio, "<ARQUIVO_PBT_5>").agrupar(linhas)
    )
    esperado = _modelo_de_particao(tipos)
    observado = tuple(
        (
            bloco.tipo_inicio,
            tuple(linha.numero_1_based - 1 for linha in bloco.linhas),
        )
        for bloco in blocos
    )

    assert observado == esperado
    assert blocos_repetidos == blocos
    assert tuple(bloco.ordem_de_leitura for bloco in blocos) == tuple(
        range(len(blocos))
    )

    linhas_emitidas = tuple(
        linha for bloco in blocos for linha in bloco.linhas
    )
    assert linhas_emitidas == linhas
    assert sum(len(bloco.linhas) for bloco in blocos) == len(linhas)

    for bloco in blocos:
        assert bloco.texto_original == "".join(
            linha.texto_com_terminador or "" for linha in bloco.linhas
        )
