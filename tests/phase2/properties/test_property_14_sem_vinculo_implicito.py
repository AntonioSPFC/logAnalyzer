"""Property 14: ausência de vínculo implícito entre identificadores.

Os casos são integralmente sintéticos e não leem arquivos nem serviços externos.
Tempo, ordem, agrupamento em entradas, adjacência e semelhança textual variam
sem que um esquema ou uma declaração semântica seja registrado no grafo.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from hypothesis import event, given, settings, strategies as st

from log_analyzer.core.modelos import (
    EntradaDeLog,
    IdentificadorTecnico,
    Proveniencia,
    TipoIdentificador,
)
from log_analyzer.core.vinculos import GrafoDeVinculos


_NAMESPACE_POR_TIPO = {
    TipoIdentificador.CHAMADA_EXTERNA: "chamada_externa",
    TipoIdentificador.SIP: "sip",
    TipoIdentificador.UUID_CANAL: "uuid_canal",
    TipoIdentificador.UUID_SESSAO: "uuid_sessao",
    TipoIdentificador.TELECOM_CALL_ID: "chamada_externa",
    TipoIdentificador.CALL_ID: "chamada_externa",
}


@dataclass(frozen=True)
class _EspecificacaoDeIdentificador:
    tipo: TipoIdentificador
    namespace: str
    nome_campo: str
    valor_original: str
    valor_normalizado: str


@dataclass(frozen=True)
class _CasoSemDeclaracao:
    entradas_com_coexistencia: tuple[EntradaDeLog, ...]
    entradas_isoladas: tuple[EntradaDeLog, ...]
    similaridade_alta: bool


def _criar_entrada(
    especificacoes: tuple[_EspecificacaoDeIdentificador, ...],
    *,
    arquivo_token: str,
    entrada_id: str,
    linha: int,
    ordem: int,
    instante: datetime,
) -> EntradaDeLog:
    identificadores = tuple(
        IdentificadorTecnico(
            tipo=especificacao.tipo,
            namespace_comparacao=especificacao.namespace,
            nome_campo=especificacao.nome_campo,
            valor_original=especificacao.valor_original,
            valor_normalizado=especificacao.valor_normalizado,
            proveniencia=Proveniencia(
                arquivo_token=arquivo_token,
                entrada_id=entrada_id,
                linha_inicial=linha,
                linha_final=linha,
                span_inicial=indice * 32,
                span_final=indice * 32 + len(especificacao.valor_original),
                nome_campo=especificacao.nome_campo,
                regra_extracao="extrator-sintetico-v1",
            ),
        )
        for indice, especificacao in enumerate(especificacoes)
    )
    texto = " | ".join(
        f"{item.nome_campo}={item.valor_original}"
        for item in especificacoes
    )
    return EntradaDeLog(
        texto_original=f"EVENTO_SINTETICO | {texto}",
        aplicacao="APP_SINTETICA",
        ordem_de_leitura=ordem,
        interpretada=True,
        carimbo_de_tempo=instante,
        nivel_de_severidade="INFO",
        mensagem="evento sintético sem declaração semântica",
        entrada_id=entrada_id,
        arquivo_token=arquivo_token,
        posicao_inicial=linha,
        posicao_final=linha,
        timestamp_original=instante.isoformat(),
        timestamp_normalizado=instante,
        precisao_fracionaria=0,
        formato_origem="sintetico-property-14",
        identificadores=identificadores,
    )


@st.composite
def _casos_sem_declaracao(draw: st.DrawFn) -> _CasoSemDeclaracao:
    quantidade = draw(st.integers(min_value=3, max_value=12))
    quantidade_grupos = draw(
        st.integers(min_value=2, max_value=min(6, quantidade - 1))
    )
    similaridade_alta = draw(st.booleans())
    sal = draw(st.binary(min_size=6, max_size=10)).hex().upper()
    partes_opacas = draw(
        st.lists(
            st.binary(min_size=4, max_size=8),
            min_size=quantidade,
            max_size=quantidade,
            unique=True,
        )
    )
    tipos = draw(
        st.lists(
            st.sampled_from(tuple(TipoIdentificador)),
            min_size=quantidade,
            max_size=quantidade,
        )
    )
    inverter_caixa = draw(
        st.lists(
            st.booleans(),
            min_size=quantidade,
            max_size=quantidade,
        )
    )

    especificacoes: list[_EspecificacaoDeIdentificador] = []
    for indice, (tipo, parte, deve_inverter) in enumerate(
        zip(tipos, partes_opacas, inverter_caixa, strict=True)
    ):
        if similaridade_alta:
            valor = f"SYN_SIM_{sal}_{indice:02X}_{parte.hex()[-4:]}"
        else:
            valor = f"SYN_DIST_{parte.hex()}_{indice:02X}"
        valor_original = valor.swapcase() if deve_inverter else valor
        especificacoes.append(
            _EspecificacaoDeIdentificador(
                tipo=tipo,
                namespace=_NAMESPACE_POR_TIPO[tipo],
                nome_campo=f"CampoSintetico{indice:02d}",
                valor_original=valor_original,
                valor_normalizado=valor_original.casefold(),
            )
        )

    atribuicoes = [0, 0]
    atribuicoes.extend(
        draw(
            st.lists(
                st.integers(min_value=0, max_value=quantidade_grupos - 1),
                min_size=quantidade - 2,
                max_size=quantidade - 2,
            )
        )
    )
    grupos = tuple(
        tuple(
            especificacao
            for especificacao, grupo in zip(
                especificacoes, atribuicoes, strict=True
            )
            if grupo == indice_grupo
        )
        for indice_grupo in range(quantidade_grupos)
    )
    grupos = tuple(grupo for grupo in grupos if grupo)

    linha_inicial = draw(st.integers(min_value=1, max_value=100_000))
    lacunas = draw(
        st.lists(
            st.sampled_from((1, 2, 7, 31)),
            min_size=max(0, len(grupos) - 1),
            max_size=max(0, len(grupos) - 1),
        )
    )
    linhas = [linha_inicial]
    for lacuna in lacunas:
        linhas.append(linhas[-1] + lacuna)

    ordens = tuple(draw(st.permutations(tuple(range(len(grupos))))))
    deslocamentos = draw(
        st.lists(
            st.one_of(
                st.integers(min_value=-3, max_value=3),
                st.integers(min_value=-172_800, max_value=172_800),
            ),
            min_size=len(grupos),
            max_size=len(grupos),
        )
    )
    base = datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(
        seconds=draw(st.integers(min_value=0, max_value=31_536_000))
    )

    entradas_com_coexistencia = tuple(
        _criar_entrada(
            grupo,
            arquivo_token=f"<ARQUIVO_SINTETICO_A_{sal}>",
            entrada_id=f"entrada-agrupada-{sal}-{indice:02d}",
            linha=linhas[indice],
            ordem=ordens[indice],
            instante=base + timedelta(seconds=deslocamentos[indice]),
        )
        for indice, grupo in enumerate(grupos)
    )

    entradas_isoladas = tuple(
        _criar_entrada(
            (especificacao,),
            arquivo_token=f"<ARQUIVO_SINTETICO_B_{sal}>",
            entrada_id=f"entrada-isolada-{sal}-{indice:02d}",
            linha=linha_inicial + 1_000 + indice * 17,
            ordem=quantidade - indice - 1,
            instante=base + timedelta(days=400, seconds=indice * 13),
        )
        for indice, especificacao in enumerate(especificacoes)
    )
    return _CasoSemDeclaracao(
        entradas_com_coexistencia=entradas_com_coexistencia,
        entradas_isoladas=entradas_isoladas,
        similaridade_alta=similaridade_alta,
    )


def _chave(
    identificador: IdentificadorTecnico,
) -> tuple[str, str, str]:
    return (
        identificador.tipo.value,
        identificador.namespace_comparacao,
        identificador.valor_normalizado,
    )


def _identificadores(
    entradas: tuple[EntradaDeLog, ...],
) -> tuple[IdentificadorTecnico, ...]:
    return tuple(
        identificador
        for entrada in entradas
        for identificador in entrada.identificadores
    )


def _construir_grafo(
    entradas: tuple[EntradaDeLog, ...],
    *,
    ordem_invertida: bool,
) -> GrafoDeVinculos:
    grafo = GrafoDeVinculos()
    sequencia = tuple(reversed(entradas)) if ordem_invertida else entradas
    for entrada in sequencia:
        identificadores = (
            tuple(reversed(entrada.identificadores))
            if ordem_invertida
            else entrada.identificadores
        )
        grafo.adicionar_identificadores(identificadores)
    return grafo


def _assinatura_dos_fechamentos(
    grafo: GrafoDeVinculos,
    sementes: tuple[IdentificadorTecnico, ...],
) -> dict[tuple[str, str, str], tuple[tuple[str, str, str], ...]]:
    assinatura = {}
    for semente in sementes:
        fechamento = grafo.percorrer_bfs(semente)
        assinatura[_chave(semente)] = tuple(
            _chave(identificador)
            for identificador in fechamento.identificadores
        )
        assert fechamento.caminhos == ()
        assert fechamento.vinculos_percorridos == ()
        assert fechamento.evidencias == ()
        assert not fechamento.componente_ambiguo
        assert not fechamento.bloqueada_por_ambiguidade
        assert tuple(_chave(item) for item in grafo.componente_de(semente)) == (
            _chave(semente),
        )
    return assinatura


# Feature: log-analyzer-phase-2, Property 14: Ausência de declaração semântica implica ausência de vínculo
@given(caso=_casos_sem_declaracao())
@settings(max_examples=100)
def test_property_14_ausencia_de_declaracao_implica_ausencia_de_vinculo(
    caso: _CasoSemDeclaracao,
) -> None:
    """Metadados incidentais não criam arestas nem ampliam o fechamento.

    **Validates: Requirements 8.4, 8.5**
    """

    agrupadas = caso.entradas_com_coexistencia
    isoladas = caso.entradas_isoladas
    ids_agrupados = _identificadores(agrupadas)
    ids_isolados = _identificadores(isoladas)

    assert any(len(entrada.identificadores) > 1 for entrada in agrupadas)
    assert all(len(entrada.identificadores) == 1 for entrada in isoladas)
    assert min(
        entrada.timestamp_normalizado for entrada in isoladas
    ) - max(
        entrada.timestamp_normalizado for entrada in agrupadas
    ) > timedelta(days=300)

    linhas_agrupadas = sorted(
        entrada.posicao_inicial for entrada in agrupadas
    )
    possui_adjacencia = any(
        seguinte - anterior == 1
        for anterior, seguinte in zip(
            linhas_agrupadas, linhas_agrupadas[1:]
        )
    )
    event(
        "similaridade="
        + ("alta" if caso.similaridade_alta else "dispersa")
    )
    event("adjacencia=" + ("presente" if possui_adjacencia else "ausente"))
    event(
        "ordem="
        + (
            "permutada"
            if tuple(entrada.ordem_de_leitura for entrada in agrupadas)
            != tuple(range(len(agrupadas)))
            else "natural"
        )
    )
    event(
        "coexistencia_max="
        + str(max(len(entrada.identificadores) for entrada in agrupadas))
    )

    grafo_agrupado = _construir_grafo(
        agrupadas,
        ordem_invertida=False,
    )
    grafo_perturbado = _construir_grafo(
        isoladas,
        ordem_invertida=True,
    )

    chaves_esperadas = tuple(sorted({_chave(item) for item in ids_agrupados}))
    assert chaves_esperadas == tuple(
        sorted({_chave(item) for item in ids_isolados})
    )

    for grafo in (grafo_agrupado, grafo_perturbado):
        assert len(grafo.registro) == 0
        assert grafo.registro.esquemas() == ()
        assert grafo.arestas == ()
        assert grafo.vinculos == ()
        assert grafo.violacoes_cardinalidade == ()
        assert grafo.componentes_ambiguos == ()
        assert tuple(sorted(_chave(item) for item in grafo.nos)) == (
            chaves_esperadas
        )

    fechamento_agrupado = _assinatura_dos_fechamentos(
        grafo_agrupado,
        ids_agrupados,
    )
    fechamento_perturbado = _assinatura_dos_fechamentos(
        grafo_perturbado,
        ids_isolados,
    )
    fechamento_esperado = {
        chave: (chave,) for chave in chaves_esperadas
    }
    assert fechamento_agrupado == fechamento_esperado
    assert fechamento_perturbado == fechamento_esperado
