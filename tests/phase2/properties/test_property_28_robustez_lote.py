"""Property 28: robustez de lotes sintéticos mistos.

O sistema sob teste processa arquivos temporários VPL/ORK, enquanto o oráculo
percorre somente descrições virtuais primitivas. Nenhuma fixture, fonte local,
base de dados, relatório ou serviço externo é consultado.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from hypothesis import event, given, note, settings
from hypothesis import strategies as st

from log_analyzer.core.bootstrap import criar_registro_padrao
from log_analyzer.core.modelos import ArquivoSelecionado
from log_analyzer.core.pipeline_fase2 import PipelineFase2


_MARCADOR = re.compile(r"P28MARK[0-9A-F]{8}(?:VPL|ORK)[0-9]{2}")
_CODIGOS_DE_FONTE_INVALIDA = {
    "ausente": "FILE_UNAVAILABLE",
    "vazia": "EMPTY_FILE",
    "diretorio": "NOT_REGULAR_FILE",
}


@dataclass(frozen=True, slots=True)
class _EntradaVirtual:
    marcador: str
    interpretada: bool
    texto: str


@dataclass(frozen=True, slots=True)
class _FonteVirtual:
    app_id: str
    caminho: Path
    entradas: tuple[_EntradaVirtual, ...]
    codigo_falha: str | None = None


@dataclass(frozen=True, slots=True)
class _EntradaEsperada:
    app_id: str
    arquivo_token: str
    ordem_de_leitura: int
    marcador: str
    interpretada: bool
    quantidade_falhas: int


def _texto_de_entrada(
    app_id: str,
    marcador: str,
    consulta: str,
    segundo: int,
    *,
    interpretada: bool,
) -> str:
    severidade = "INFO" if interpretada else "INVALID"
    if app_id == "VPL":
        severidade = "NOTICE" if interpretada else "INVALID"
        return (
            f"2035-06-15 10:20:{segundo:02d}.123456 98.75% "
            f"[{severidade}] p28_sintetico.py:{segundo} "
            f"marcador={marcador} CallId={consulta}"
        )
    return (
        f"2035-06-15T13:20:{segundo:02d}.123456+00:00 "
        "node-p28.synthetic.invalid p28-worker[2800]: "
        f"{severidade} - property.p28 - "
        f"marcador={marcador} CallId={consulta}"
    )


def _criar_fonte_valida(
    raiz: Path,
    app_id: str,
    consulta: str,
    semente: int,
    estados_extras: list[bool],
    indice_repetido: int,
    terminador: str,
) -> _FonteVirtual:
    estados = [False, True, *estados_extras]
    entradas_distintas = tuple(
        _EntradaVirtual(
            marcador=(
                f"P28MARK{semente:08X}{app_id}{indice:02d}"
            ),
            interpretada=interpretada,
            texto=_texto_de_entrada(
                app_id,
                f"P28MARK{semente:08X}{app_id}{indice:02d}",
                consulta,
                segundo=indice,
                interpretada=interpretada,
            ),
        )
        for indice, interpretada in enumerate(estados)
    )
    # A última linha repete byte a byte uma ocorrência anterior. O modelo não
    # colapsa essa igualdade: ela permanece uma nova posição de leitura.
    entradas = (*entradas_distintas, entradas_distintas[indice_repetido])
    caminho = raiz / f"fonte-sintetica-{app_id.casefold()}.log"
    caminho.write_bytes(
        terminador.encode("ascii").join(
            entrada.texto.encode("ascii") for entrada in entradas
        )
        + terminador.encode("ascii")
    )
    return _FonteVirtual(app_id, caminho, entradas)


def _criar_fonte_invalida(
    raiz: Path,
    app_id: str,
    tipo: str,
) -> _FonteVirtual:
    caminho = raiz / f"fonte-sintetica-invalida-{tipo}"
    if tipo == "vazia":
        caminho.write_bytes(b"")
    elif tipo == "diretorio":
        caminho.mkdir()
    return _FonteVirtual(
        app_id=app_id,
        caminho=caminho,
        entradas=(),
        codigo_falha=_CODIGOS_DE_FONTE_INVALIDA[tipo],
    )


def _modelo_sequencial(
    lote: tuple[_FonteVirtual, ...],
) -> tuple[list[_EntradaEsperada], list[tuple[str, str]]]:
    """Oráculo independente que percorre as descrições na ordem recebida."""

    entradas: list[_EntradaEsperada] = []
    falhas: list[tuple[str, str]] = []
    for posicao, fonte in enumerate(lote, start=1):
        token = f"<ARQUIVO_{posicao}>"
        if fonte.codigo_falha is not None:
            falhas.append((token, fonte.codigo_falha))
            continue
        for ordem, entrada in enumerate(fonte.entradas):
            entradas.append(
                _EntradaEsperada(
                    app_id=fonte.app_id,
                    arquivo_token=token,
                    ordem_de_leitura=ordem,
                    marcador=entrada.marcador,
                    interpretada=entrada.interpretada,
                    quantidade_falhas=0 if entrada.interpretada else 1,
                )
            )
    return entradas, falhas


# Feature: log-analyzer-phase-2, Property 28: Robustez do lote preserva válidos, falhas e repetições
@given(
    dados=st.data(),
    semente=st.integers(min_value=0, max_value=2**32 - 1),
    app_repetida=st.sampled_from(("VPL", "ORK")),
    app_invalida=st.sampled_from(("VPL", "ORK")),
    tipo_fonte_invalida=st.sampled_from(tuple(_CODIGOS_DE_FONTE_INVALIDA)),
    ordem_do_lote=st.permutations((0, 1, 2, 3)),
    terminador_vpl=st.sampled_from(("\n", "\r\n")),
    terminador_ork=st.sampled_from(("\n", "\r\n")),
)
@settings(max_examples=100, deadline=500)
def test_property_28_robustez_do_lote_preserva_validos_falhas_e_repeticoes(
    dados,
    semente: int,
    app_repetida: str,
    app_invalida: str,
    tipo_fonte_invalida: str,
    ordem_do_lote: tuple[int, ...],
    terminador_vpl: str,
    terminador_ork: str,
) -> None:
    """Pipeline coincide com o modelo para itens válidos e inválidos.

    **Validates: Requirements 15.1, 15.2, 15.3, 15.6, 15.7**
    """

    estados_extras_vpl = dados.draw(
        st.lists(st.booleans(), min_size=0, max_size=2),
        label="estados_extras_vpl",
    )
    estados_extras_ork = dados.draw(
        st.lists(st.booleans(), min_size=0, max_size=2),
        label="estados_extras_ork",
    )
    indice_repetido_vpl = dados.draw(
        st.integers(min_value=0, max_value=1 + len(estados_extras_vpl)),
        label="indice_repetido_vpl",
    )
    indice_repetido_ork = dados.draw(
        st.integers(min_value=0, max_value=1 + len(estados_extras_ork)),
        label="indice_repetido_ork",
    )
    consulta = f"CALL-P28-{semente:08X}"

    with TemporaryDirectory(prefix="phase2-property28-synthetic-") as diretorio:
        raiz = Path(diretorio)
        fonte_vpl = _criar_fonte_valida(
            raiz,
            "VPL",
            consulta,
            semente,
            estados_extras_vpl,
            indice_repetido_vpl,
            terminador_vpl,
        )
        fonte_ork = _criar_fonte_valida(
            raiz,
            "ORK",
            consulta,
            semente,
            estados_extras_ork,
            indice_repetido_ork,
            terminador_ork,
        )
        fontes_validas = {"VPL": fonte_vpl, "ORK": fonte_ork}
        fonte_invalida = _criar_fonte_invalida(
            raiz,
            app_invalida,
            tipo_fonte_invalida,
        )
        itens = (
            fonte_vpl,
            fonte_ork,
            fontes_validas[app_repetida],
            fonte_invalida,
        )
        lote = tuple(itens[indice] for indice in ordem_do_lote)
        entradas_esperadas, falhas_esperadas = _modelo_sequencial(lote)

        note(
            "lote_virtual="
            f"ordem={ordem_do_lote}, repetida={app_repetida}, "
            f"invalida={app_invalida}/{tipo_fonte_invalida}, "
            f"entradas_vpl={len(fonte_vpl.entradas)}, "
            f"entradas_ork={len(fonte_ork.entradas)}"
        )

        resultado = PipelineFase2(criar_registro_padrao()).executar(
            tuple(
                ArquivoSelecionado(
                    caminho=str(fonte.caminho),
                    app_id=fonte.app_id,
                )
                for fonte in lote
            ),
            consulta,
        )

    falhas_observadas = [
        (erro.arquivo_ou_app, erro.descricao) for erro in resultado.erros
    ]
    assert falhas_observadas == falhas_esperadas

    esperadas_por_app = {
        app_id: [
            entrada
            for entrada in entradas_esperadas
            if entrada.app_id == app_id
        ]
        for app_id in ("VPL", "ORK")
    }
    assert set(resultado.entradas_por_aplicacao) == {"VPL", "ORK"}

    observadas_por_app: dict[str, list[tuple[object, ...]]] = {}
    for app_id in ("VPL", "ORK"):
        observadas: list[tuple[object, ...]] = []
        for entrada in resultado.entradas_por_aplicacao[app_id]:
            marcadores = _MARCADOR.findall(entrada.texto_original)
            assert len(marcadores) == 1
            observadas.append(
                (
                    entrada.arquivo_token,
                    entrada.ordem_de_leitura,
                    marcadores[0],
                    entrada.interpretada,
                    len(entrada.falhas),
                )
            )
        observadas_por_app[app_id] = observadas

        assert observadas == [
            (
                entrada.arquivo_token,
                entrada.ordem_de_leitura,
                entrada.marcador,
                entrada.interpretada,
                entrada.quantidade_falhas,
            )
            for entrada in esperadas_por_app[app_id]
        ]

    multiplicidade_esperada = Counter(
        (entrada.app_id, entrada.marcador)
        for entrada in entradas_esperadas
    )
    multiplicidade_observada = Counter(
        (app_id, observada[2])
        for app_id, observadas in observadas_por_app.items()
        for observada in observadas
    )
    assert multiplicidade_observada == multiplicidade_esperada
    assert any(
        quantidade > 1 for quantidade in multiplicidade_esperada.values()
    )

    assert resultado.contagem_por_aplicacao == {
        app_id: len(entradas)
        for app_id, entradas in esperadas_por_app.items()
    }
    assert sum(resultado.contagem_por_aplicacao.values()) == len(
        entradas_esperadas
    )
    assert sum(
        len(entrada.falhas)
        for entradas in resultado.entradas_por_aplicacao.values()
        for entrada in entradas
    ) == sum(
        entrada.quantidade_falhas for entrada in entradas_esperadas
    )

    event(f"fonte_repetida={app_repetida}")
    event(f"fonte_invalida={tipo_fonte_invalida}")
    event(f"app_invalida={app_invalida}")
    event(f"posicao_fonte_invalida={ordem_do_lote.index(3) + 1}")
    event(f"terminador_vpl={'CRLF' if terminador_vpl == chr(13) + chr(10) else 'LF'}")
    event(f"terminador_ork={'CRLF' if terminador_ork == chr(13) + chr(10) else 'LF'}")
