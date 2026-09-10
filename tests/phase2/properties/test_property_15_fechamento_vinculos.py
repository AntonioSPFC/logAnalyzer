"""Property 15 do fechamento determinístico por vínculos explícitos.

Os grafos, identificadores e metadados deste módulo são totalmente sintéticos e
produzidos em memória. O modelo de referência implementa sua própria BFS e não
consulta a implementação do grafo para calcular resultados esperados.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

from hypothesis import event, given, settings, strategies as st

from log_analyzer.core.modelos import (
    IdentificadorTecnico,
    Proveniencia,
    TipoIdentificador,
    VinculoIdentificadores,
)
from log_analyzer.core.vinculos import (
    Cardinalidade,
    DeclaracaoSemanticaDeVinculo,
    EsquemaDeVinculo,
    GrafoDeVinculos,
    RegistroDeEsquemasDeVinculo,
    ResultadoTravessia,
)


_ESQUEMA_ID = "property-15-esquema-sintetico"
_ESQUEMA_VERSAO = 1
_TIPO_RELACAO = "property-15-relacao-explicita"
_CODIGO_SEMANTICO = "PROPERTY_15_VINCULO_EXPLICITO"
_FATO_SEMANTICO = "PROPERTY_15_FATO_APROVADO"
_TIPOS_IDENTIFICADOR = tuple(TipoIdentificador)
_TOPOLOGIAS = (
    "isolado",
    "caminho",
    "ciclo",
    "desconectado",
    "diamante",
    "aleatorio",
)
_NAMESPACE_POR_TIPO = {
    TipoIdentificador.CHAMADA_EXTERNA: "chamada_sintetica",
    TipoIdentificador.SIP: "sip_sintetico",
    TipoIdentificador.UUID_CANAL: "uuid_canal_sintetico",
    TipoIdentificador.UUID_SESSAO: "uuid_sessao_sintetico",
    TipoIdentificador.TELECOM_CALL_ID: "telecom_sintetico",
    TipoIdentificador.CALL_ID: "call_id_sintetico",
}


@dataclass(frozen=True)
class _NoSintetico:
    indice: int
    tipo: TipoIdentificador
    namespace: str
    valor_normalizado: str


@dataclass(frozen=True)
class _ArestaSintetica:
    indice: int
    origem: int
    destino: int
    evidencia_id: str
    linha: int


@dataclass(frozen=True)
class _PassoEsperado:
    origem: int
    destino: int
    aresta: int
    sentido_original: bool


@dataclass(frozen=True)
class _CaminhoEsperado:
    semente: int
    destino: int
    passos: tuple[_PassoEsperado, ...]


@dataclass(frozen=True)
class _FechamentoEsperado:
    sementes: tuple[int, ...]
    nos: tuple[int, ...]
    caminhos: tuple[_CaminhoEsperado, ...]
    arestas_percorridas: tuple[int, ...]
    distancias: tuple[tuple[int, int], ...]


def _identidade_no(no: _NoSintetico) -> tuple[TipoIdentificador, str, str]:
    return (no.tipo, no.namespace, no.valor_normalizado)


def _identidade_identificador(
    identificador: IdentificadorTecnico,
) -> tuple[TipoIdentificador, str, str]:
    return (
        identificador.tipo,
        identificador.namespace_comparacao,
        identificador.valor_normalizado,
    )


def _digest_no(no: _NoSintetico) -> str:
    material = f"{no.namespace}\0{no.valor_normalizado}".encode("utf-8")
    return sha256(material).hexdigest()


def _ordem_no(no: _NoSintetico) -> tuple[str, str, str, str]:
    return (
        no.tipo.value,
        _digest_no(no),
        no.namespace,
        no.valor_normalizado,
    )


def _ordem_aresta(
    aresta: _ArestaSintetica,
    nos: tuple[_NoSintetico, ...],
) -> tuple[object, ...]:
    return (
        _ordem_no(nos[aresta.origem]),
        _ordem_no(nos[aresta.destino]),
        aresta.evidencia_id,
        _ESQUEMA_ID,
        _ESQUEMA_VERSAO,
        _TIPO_RELACAO,
    )


def _valor_sintetico(
    sal: int,
    indice: int,
    tipo: TipoIdentificador,
) -> str:
    if tipo in (
        TipoIdentificador.UUID_CANAL,
        TipoIdentificador.UUID_SESSAO,
    ):
        return str(UUID(int=(sal << 16) | (indice + 1)))
    return f"syn-p15-{sal:016x}-{indice:02d}"


def _proveniencia_no(sal: int, indice: int) -> Proveniencia:
    return Proveniencia(
        arquivo_token=f"<ARQUIVO_SINTETICO_P15_{sal:016X}>",
        entrada_id=f"000-P15-NO-{indice:02d}",
        linha_inicial=indice + 1,
        linha_final=indice + 1,
        nome_campo=f"campo_sintetico_{indice:02d}",
        regra_extracao="property-15-no-sintetico-v1",
    )


def _proveniencia_aresta(sal: int, aresta: _ArestaSintetica) -> Proveniencia:
    return Proveniencia(
        arquivo_token=f"<ARQUIVO_SINTETICO_P15_{sal:016X}>",
        entrada_id=aresta.evidencia_id,
        linha_inicial=aresta.linha,
        linha_final=aresta.linha,
        nome_campo="declaracao_de_vinculo_sintetica",
        regra_extracao="property-15-vinculo-sintetico-v1",
    )


def _criar_identificador(
    no: _NoSintetico,
    proveniencia: Proveniencia,
) -> IdentificadorTecnico:
    return IdentificadorTecnico(
        tipo=no.tipo,
        namespace_comparacao=no.namespace,
        nome_campo=f"campo_sintetico_{no.indice:02d}",
        valor_original=no.valor_normalizado.upper(),
        valor_normalizado=no.valor_normalizado,
        proveniencia=proveniencia,
    )


def _reconhecer_declaracao(
    declaracao: DeclaracaoSemanticaDeVinculo,
) -> bool:
    return (
        declaracao.codigo_semantico == _CODIGO_SEMANTICO
        and _FATO_SEMANTICO in declaracao.fatos
    )


def _novo_grafo() -> GrafoDeVinculos:
    registro = RegistroDeEsquemasDeVinculo()
    registro.registrar(
        EsquemaDeVinculo(
            esquema_id=_ESQUEMA_ID,
            versao=_ESQUEMA_VERSAO,
            tipo_relacao=_TIPO_RELACAO,
            tipos_origem=_TIPOS_IDENTIFICADOR,
            tipos_destino=_TIPOS_IDENTIFICADOR,
            cardinalidade=Cardinalidade.MUITOS_PARA_MUITOS,
            permite_expansao_de_cenario=True,
            aprovado=True,
            reconhecedor=_reconhecer_declaracao,
        )
    )
    return GrafoDeVinculos(registro)


def _construir_grafo(
    identificadores: tuple[IdentificadorTecnico, ...],
    declaracoes: tuple[DeclaracaoSemanticaDeVinculo, ...],
    ordem_nos: tuple[int, ...],
    ordem_arestas: tuple[int, ...],
) -> GrafoDeVinculos:
    grafo = _novo_grafo()
    for indice in ordem_nos:
        grafo.adicionar_identificador(identificadores[indice])
    for indice in ordem_arestas:
        criados = grafo.adicionar_declaracao(declaracoes[indice])
        assert len(criados) == 1
        assert criados[0].evidencia == declaracoes[indice].evidencia
    return grafo


def _modelo_de_referencia(
    nos: tuple[_NoSintetico, ...],
    arestas: tuple[_ArestaSintetica, ...],
    sementes: tuple[int, ...],
) -> _FechamentoEsperado:
    """Calcula o fechamento por uma BFS multiorigem independente."""

    adjacencia: dict[int, list[tuple[int, int]]] = {
        no.indice: [] for no in nos
    }
    for aresta in arestas:
        adjacencia[aresta.origem].append((aresta.destino, aresta.indice))
        adjacencia[aresta.destino].append((aresta.origem, aresta.indice))

    sementes_ordenadas = tuple(
        sorted(set(sementes), key=lambda indice: _ordem_no(nos[indice]))
    )
    conjunto_sementes = set(sementes_ordenadas)
    visitados = set(sementes_ordenadas)
    ordem_descoberta = list(sementes_ordenadas)
    fila = deque(sementes_ordenadas)
    pais: dict[int, tuple[int, int]] = {}
    raizes = {indice: indice for indice in sementes_ordenadas}
    distancias = {indice: 0 for indice in sementes_ordenadas}

    while fila:
        atual = fila.popleft()
        vizinhos = sorted(
            adjacencia[atual],
            key=lambda item: (
                nos[item[0]].tipo.value,
                _digest_no(nos[item[0]]),
                arestas[item[1]].evidencia_id,
                nos[item[0]].namespace,
                nos[item[0]].valor_normalizado,
            ),
        )
        for vizinho, indice_aresta in vizinhos:
            if vizinho in visitados:
                continue
            visitados.add(vizinho)
            ordem_descoberta.append(vizinho)
            pais[vizinho] = (atual, indice_aresta)
            raizes[vizinho] = raizes[atual]
            distancias[vizinho] = distancias[atual] + 1
            fila.append(vizinho)

    caminhos: list[_CaminhoEsperado] = []
    for destino in ordem_descoberta:
        if destino in conjunto_sementes:
            continue
        segmentos: list[_PassoEsperado] = []
        atual = destino
        while atual not in conjunto_sementes:
            anterior, indice_aresta = pais[atual]
            aresta = arestas[indice_aresta]
            segmentos.append(
                _PassoEsperado(
                    origem=anterior,
                    destino=atual,
                    aresta=indice_aresta,
                    sentido_original=(
                        aresta.origem == anterior
                        and aresta.destino == atual
                    ),
                )
            )
            atual = anterior
        segmentos.reverse()
        caminhos.append(
            _CaminhoEsperado(
                semente=raizes[destino],
                destino=destino,
                passos=tuple(segmentos),
            )
        )

    arestas_percorridas: list[int] = []
    arestas_vistas: set[int] = set()
    for caminho in caminhos:
        for passo in caminho.passos:
            if passo.aresta not in arestas_vistas:
                arestas_vistas.add(passo.aresta)
                arestas_percorridas.append(passo.aresta)

    return _FechamentoEsperado(
        sementes=sementes_ordenadas,
        nos=tuple(ordem_descoberta),
        caminhos=tuple(caminhos),
        arestas_percorridas=tuple(arestas_percorridas),
        distancias=tuple(sorted(distancias.items())),
    )


def _indice_do_identificador(
    identificador: IdentificadorTecnico,
    indices_por_identidade: dict[tuple[TipoIdentificador, str, str], int],
) -> int:
    return indices_por_identidade[_identidade_identificador(identificador)]


def _indice_do_vinculo(
    vinculo: VinculoIdentificadores,
    indices_por_evidencia: dict[str, int],
) -> int:
    return indices_por_evidencia[vinculo.evidencia.entrada_id]


def _validar_grafo(
    grafo: GrafoDeVinculos,
    nos: tuple[_NoSintetico, ...],
    arestas: tuple[_ArestaSintetica, ...],
    identificadores: tuple[IdentificadorTecnico, ...],
    indices_por_identidade: dict[tuple[TipoIdentificador, str, str], int],
    indices_por_evidencia: dict[str, int],
) -> None:
    nos_esperados = tuple(
        no.indice for no in sorted(nos, key=_ordem_no)
    )
    assert tuple(
        _indice_do_identificador(item, indices_por_identidade)
        for item in grafo.nos
    ) == nos_esperados
    assert grafo.nos == tuple(
        identificadores[indice] for indice in nos_esperados
    )

    arestas_esperadas = tuple(
        aresta.indice
        for aresta in sorted(
            arestas,
            key=lambda item: _ordem_aresta(item, nos),
        )
    )
    assert tuple(
        _indice_do_vinculo(item, indices_por_evidencia)
        for item in grafo.arestas
    ) == arestas_esperadas
    assert all(
        vinculo.esquema_id == _ESQUEMA_ID
        and vinculo.esquema_versao == _ESQUEMA_VERSAO
        and vinculo.tipo_relacao == _TIPO_RELACAO
        and vinculo.permite_correlacao
        and not vinculo.ambiguo
        for vinculo in grafo.arestas
    )
    assert grafo.violacoes_cardinalidade == ()
    assert grafo.componentes_ambiguos == ()
    assert grafo.pode_sustentar_classificacao()
    assert all(
        grafo.pode_sustentar_classificacao(identificador)
        for identificador in identificadores
    )


def _validar_fechamento(
    resultado: ResultadoTravessia,
    esperado: _FechamentoEsperado,
    identificadores: tuple[IdentificadorTecnico, ...],
    indices_por_identidade: dict[tuple[TipoIdentificador, str, str], int],
    indices_por_evidencia: dict[str, int],
) -> None:
    indices_sementes = tuple(
        _indice_do_identificador(item, indices_por_identidade)
        for item in resultado.sementes
    )
    indices_nos = tuple(
        _indice_do_identificador(item, indices_por_identidade)
        for item in resultado.nos
    )
    assert indices_sementes == esperado.sementes
    assert indices_nos == esperado.nos
    assert len(resultado) == len(esperado.nos)
    assert tuple(resultado) == resultado.nos
    assert not resultado.componente_ambiguo
    assert not resultado.bloqueada_por_ambiguidade

    assert len(resultado.caminhos) == len(esperado.caminhos)
    distancias = dict(esperado.distancias)
    for caminho, caminho_esperado in zip(
        resultado.caminhos,
        esperado.caminhos,
        strict=True,
    ):
        assert _indice_do_identificador(
            caminho.semente, indices_por_identidade
        ) == caminho_esperado.semente
        assert _indice_do_identificador(
            caminho.destino, indices_por_identidade
        ) == caminho_esperado.destino

        passos_observados = tuple(
            _PassoEsperado(
                origem=_indice_do_identificador(
                    passo.origem, indices_por_identidade
                ),
                destino=_indice_do_identificador(
                    passo.destino, indices_por_identidade
                ),
                aresta=_indice_do_vinculo(
                    passo.vinculo, indices_por_evidencia
                ),
                sentido_original=passo.sentido_original,
            )
            for passo in caminho.passos
        )
        assert passos_observados == caminho_esperado.passos
        assert len(caminho.passos) == distancias[caminho_esperado.destino]
        assert caminho.vinculos == tuple(
            passo.vinculo for passo in caminho.passos
        )
        assert caminho.evidencias == tuple(
            passo.vinculo.evidencia for passo in caminho.passos
        )
        assert all(
            passo.evidencia == passo.vinculo.evidencia
            for passo in caminho.passos
        )
        assert resultado.caminho_para(
            identificadores[caminho_esperado.destino]
        ) == caminho

    for semente in esperado.sementes:
        caminho_semente = resultado.caminho_para(identificadores[semente])
        assert caminho_semente is not None
        assert caminho_semente.semente == identificadores[semente]
        assert caminho_semente.destino == identificadores[semente]
        assert caminho_semente.passos == ()

    inalcançaveis = set(range(len(identificadores))).difference(esperado.nos)
    assert all(
        resultado.caminho_para(identificadores[indice]) is None
        for indice in inalcançaveis
    )

    arestas_observadas = tuple(
        _indice_do_vinculo(vinculo, indices_por_evidencia)
        for vinculo in resultado.vinculos_percorridos
    )
    evidencias_observadas = tuple(
        indices_por_evidencia[evidencia.entrada_id]
        for evidencia in resultado.evidencias
    )
    assert arestas_observadas == esperado.arestas_percorridas
    assert evidencias_observadas == esperado.arestas_percorridas
    assert resultado.evidencias == tuple(
        vinculo.evidencia for vinculo in resultado.vinculos_percorridos
    )


def _assinatura_fechamento(
    resultado: ResultadoTravessia,
    indices_por_identidade: dict[tuple[TipoIdentificador, str, str], int],
    indices_por_evidencia: dict[str, int],
) -> tuple[object, ...]:
    return (
        tuple(
            _indice_do_identificador(item, indices_por_identidade)
            for item in resultado.sementes
        ),
        tuple(
            _indice_do_identificador(item, indices_por_identidade)
            for item in resultado.nos
        ),
        tuple(
            (
                _indice_do_identificador(
                    caminho.semente, indices_por_identidade
                ),
                _indice_do_identificador(
                    caminho.destino, indices_por_identidade
                ),
                tuple(
                    (
                        _indice_do_identificador(
                            passo.origem, indices_por_identidade
                        ),
                        _indice_do_identificador(
                            passo.destino, indices_por_identidade
                        ),
                        _indice_do_vinculo(
                            passo.vinculo, indices_por_evidencia
                        ),
                        passo.sentido_original,
                    )
                    for passo in caminho.passos
                ),
            )
            for caminho in resultado.caminhos
        ),
        tuple(
            _indice_do_vinculo(vinculo, indices_por_evidencia)
            for vinculo in resultado.vinculos_percorridos
        ),
        tuple(
            indices_por_evidencia[evidencia.entrada_id]
            for evidencia in resultado.evidencias
        ),
    )


def _duas_permutacoes_distintas(
    dados,
    valores: tuple[int, ...],
    rotulo: str,
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    if len(valores) < 2:
        return valores, valores
    primeira = tuple(
        dados.draw(st.permutations(valores), label=f"{rotulo}_primeira")
    )
    segunda = tuple(
        dados.draw(st.permutations(valores), label=f"{rotulo}_segunda")
    )
    if segunda == primeira:
        segunda = primeira[1:] + primeira[:1]
    return primeira, segunda


# Feature: log-analyzer-phase-2, Property 15: Fechamento por vínculos equivale à alcançabilidade evidenciada
@given(dados=st.data(), sal=st.integers(min_value=0, max_value=2**64 - 1))
@settings(max_examples=100)
def test_property_15_fechamento_equivale_a_alcancabilidade_evidenciada(
    dados,
    sal: int,
) -> None:
    """BFS coincide com o modelo e independe da ordem de inserção.

    **Validates: Requirements 8.1, 8.2, 8.3, 13.4**
    """

    topologia = dados.draw(st.sampled_from(_TOPOLOGIAS), label="topologia")
    minimo_nos = {
        "isolado": 2,
        "caminho": 2,
        "ciclo": 3,
        "desconectado": 4,
        "diamante": 4,
        "aleatorio": 2,
    }[topologia]
    quantidade_nos = dados.draw(
        st.integers(min_value=minimo_nos, max_value=8),
        label="quantidade_nos",
    )
    tipos = tuple(
        dados.draw(
            st.lists(
                st.sampled_from(_TIPOS_IDENTIFICADOR),
                min_size=quantidade_nos,
                max_size=quantidade_nos,
            ),
            label="tipos_dos_nos",
        )
    )
    nos = tuple(
        _NoSintetico(
            indice=indice,
            tipo=tipo,
            namespace=_NAMESPACE_POR_TIPO[tipo],
            valor_normalizado=_valor_sintetico(sal, indice, tipo),
        )
        for indice, tipo in enumerate(tipos)
    )

    pares_possiveis = tuple(
        (origem, destino)
        for origem in range(quantidade_nos)
        for destino in range(origem + 1, quantidade_nos)
    )
    if topologia == "isolado":
        pares_selecionados: set[tuple[int, int]] = set()
    elif topologia == "caminho":
        pares_selecionados = {
            (indice, indice + 1) for indice in range(quantidade_nos - 1)
        }
    elif topologia == "ciclo":
        pares_selecionados = {
            (indice, indice + 1) for indice in range(quantidade_nos - 1)
        }
        pares_selecionados.add((0, quantidade_nos - 1))
    elif topologia == "desconectado":
        corte = quantidade_nos // 2
        pares_selecionados = {
            (indice, indice + 1)
            for inicio, fim in ((0, corte), (corte, quantidade_nos))
            for indice in range(inicio, fim - 1)
        }
    elif topologia == "diamante":
        pares_selecionados = {(0, 1), (0, 2), (1, 3), (2, 3)}
    else:
        pares_selecionados = set(
            dados.draw(
                st.sets(
                    st.sampled_from(pares_possiveis),
                    min_size=0,
                    max_size=min(len(pares_possiveis), quantidade_nos + 3),
                ),
                label="arestas_aleatorias",
            )
        )

    pares_ordenados = tuple(sorted(pares_selecionados))
    arestas = tuple(
        _ArestaSintetica(
            indice=indice,
            origem=origem,
            destino=destino,
            evidencia_id=f"100-P15-ARESTA-{indice:02d}",
            linha=100 + indice,
        )
        for indice, (origem, destino) in enumerate(pares_ordenados)
    )

    identificadores = tuple(
        _criar_identificador(no, _proveniencia_no(sal, no.indice))
        for no in nos
    )
    declaracoes = tuple(
        DeclaracaoSemanticaDeVinculo(
            origem=_criar_identificador(
                nos[aresta.origem],
                _proveniencia_aresta(sal, aresta),
            ),
            destino=_criar_identificador(
                nos[aresta.destino],
                _proveniencia_aresta(sal, aresta),
            ),
            evidencia=_proveniencia_aresta(sal, aresta),
            codigo_semantico=_CODIGO_SEMANTICO,
            fatos=frozenset({_FATO_SEMANTICO}),
        )
        for aresta in arestas
    )

    indices_nos = tuple(range(quantidade_nos))
    indices_arestas = tuple(range(len(arestas)))
    ordem_nos_a, ordem_nos_b = _duas_permutacoes_distintas(
        dados, indices_nos, "ordem_nos"
    )
    ordem_arestas_a, ordem_arestas_b = _duas_permutacoes_distintas(
        dados, indices_arestas, "ordem_arestas"
    )

    quantidade_sementes = dados.draw(
        st.integers(min_value=1, max_value=min(3, quantidade_nos)),
        label="quantidade_sementes",
    )
    conjunto_sementes = dados.draw(
        st.sets(
            st.integers(min_value=0, max_value=quantidade_nos - 1),
            min_size=quantidade_sementes,
            max_size=quantidade_sementes,
        ),
        label="sementes",
    )
    sementes_base = tuple(sorted(conjunto_sementes))
    ordem_sementes_a, ordem_sementes_b = _duas_permutacoes_distintas(
        dados, sementes_base, "ordem_sementes"
    )

    grafo_a = _construir_grafo(
        identificadores,
        declaracoes,
        ordem_nos_a,
        ordem_arestas_a,
    )
    grafo_b = _construir_grafo(
        identificadores,
        declaracoes,
        ordem_nos_b,
        ordem_arestas_b,
    )
    resultado_a = grafo_a.percorrer_bfs(
        tuple(identificadores[indice] for indice in ordem_sementes_a)
    )
    resultado_b = grafo_b.percorrer_bfs(
        tuple(identificadores[indice] for indice in ordem_sementes_b)
    )
    esperado = _modelo_de_referencia(nos, arestas, sementes_base)

    indices_por_identidade = {
        _identidade_no(no): no.indice for no in nos
    }
    indices_por_evidencia = {
        aresta.evidencia_id: aresta.indice for aresta in arestas
    }
    _validar_grafo(
        grafo_a,
        nos,
        arestas,
        identificadores,
        indices_por_identidade,
        indices_por_evidencia,
    )
    _validar_grafo(
        grafo_b,
        nos,
        arestas,
        identificadores,
        indices_por_identidade,
        indices_por_evidencia,
    )
    _validar_fechamento(
        resultado_a,
        esperado,
        identificadores,
        indices_por_identidade,
        indices_por_evidencia,
    )
    _validar_fechamento(
        resultado_b,
        esperado,
        identificadores,
        indices_por_identidade,
        indices_por_evidencia,
    )

    assert _assinatura_fechamento(
        resultado_a,
        indices_por_identidade,
        indices_por_evidencia,
    ) == _assinatura_fechamento(
        resultado_b,
        indices_por_identidade,
        indices_por_evidencia,
    )
    assert grafo_a.nos == grafo_b.nos
    assert grafo_a.arestas == grafo_b.arestas

    event(f"topologia={topologia}")
    event(f"quantidade_nos={quantidade_nos}")
    event(f"quantidade_arestas={len(arestas)}")
    event(f"quantidade_sementes={quantidade_sementes}")
    event(
        "permutacao_arestas="
        + ("distinta" if ordem_arestas_a != ordem_arestas_b else "trivial")
    )
