"""Property 17: correlação VPL–ORK sustentada somente por evidência válida.

Todos os valores, grafos e metadados são sintéticos e construídos em memória.
O oráculo opera sobre especificações primitivas próprias; ele não consulta o
grafo nem o correlacionador para decidir igualdade, alcançabilidade ou
ambiguidade.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from hypothesis import event, given, settings, strategies as st

from log_analyzer.core.correlacao import (
    CorrelacionadorVplOrk,
    LacunaCorrelacao,
)
from log_analyzer.core.modelos import (
    BaseCorrelacao,
    EntradaDeLog,
    IdentificadorTecnico,
    Proveniencia,
    TipoIdentificador,
)
from log_analyzer.core.vinculos import (
    Cardinalidade,
    DeclaracaoSemanticaDeVinculo,
    EsquemaDeVinculo,
    GrafoDeVinculos,
    RegistroDeEsquemasDeVinculo,
)


_ESTADOS_DA_CADEIA = (
    "sem_declaracao",
    "valida",
    "esquema_nao_aprovado",
    "nao_correlacionavel",
    "evidencia_ausente",
    "ambigua",
)
_ESQUEMA_ID = "property-17-esquema-sintetico"
_ESQUEMA_VERSAO = 1
_TIPO_RELACAO = "property-17-relacao-explicita"
_CODIGO_SEMANTICO = "PROPERTY_17_DECLARACAO_EXPLICITA"
_FATO_APROVADO = "PROPERTY_17_FATO_ESTRUTURADO"
_REGRA_EXTRACAO = "property-17-extrator-sintetico-v1"


# Feature: log-analyzer-phase-2, Property 17: Correlação VPL–ORK existe se e somente se há evidência válida
@given(dados=st.data(), sal=st.integers(min_value=0, max_value=2**64 - 1))
@settings(max_examples=100)
def test_property_17_correlacao_existe_se_e_somente_se_ha_evidencia_valida(
    dados,
    sal: int,
) -> None:
    """Resultado coincide com o modelo formal de igualdade ou cadeia válida.

    **Validates: Requirements 9.1, 9.2, 9.4, 9.5, 9.6**
    """

    estado_cadeia = dados.draw(
        st.sampled_from(_ESTADOS_DA_CADEIA), label="estado_cadeia"
    )
    possui_valor_compartilhado = dados.draw(
        st.booleans(), label="possui_valor_compartilhado"
    )
    quantidade_arestas_do_caminho = dados.draw(
        st.integers(min_value=1, max_value=3),
        label="quantidade_arestas_do_caminho",
    )
    sal_textual = f"{sal:016x}"
    tokens = {
        "VPL": f"<ARQUIVO_SINTETICO_P17_VPL_{sal:016X}>",
        "ORK": f"<ARQUIVO_SINTETICO_P17_ORK_{sal:016X}>",
    }

    tipos_dos_nos = dados.draw(
        st.lists(
            st.sampled_from(tuple(TipoIdentificador)),
            min_size=quantidade_arestas_do_caminho + 1,
            max_size=quantidade_arestas_do_caminho + 1,
        ),
        label="tipos_dos_nos",
    )
    nos: list[dict[str, object]] = []
    for indice, tipo in enumerate(tipos_dos_nos):
        valor = f"syn-p17-{sal_textual}-no-{indice:02d}"
        nos.append(
            {
                "indice": indice,
                "tipo": tipo,
                "namespace": f"property_17_cadeia_{indice:02d}",
                "nome_campo": f"CampoCadeia{indice:02d}",
                "valor": valor,
                "original": valor.upper(),
            }
        )

    if estado_cadeia == "ambigua":
        indice = len(nos)
        valor = f"syn-p17-{sal_textual}-ramo-ambiguo"
        nos.append(
            {
                "indice": indice,
                "tipo": dados.draw(
                    st.sampled_from(tuple(TipoIdentificador)),
                    label="tipo_no_ambiguo",
                ),
                "namespace": "property_17_ramo_ambiguo",
                "nome_campo": "CampoRamoAmbiguo",
                "valor": valor,
                "original": valor.upper(),
            }
        )

    indice_evidencia_ausente = None
    if estado_cadeia == "evidencia_ausente":
        indice_evidencia_ausente = dados.draw(
            st.integers(
                min_value=0,
                max_value=quantidade_arestas_do_caminho - 1,
            ),
            label="indice_evidencia_ausente",
        )

    arestas: list[dict[str, object]] = []
    for indice in range(quantidade_arestas_do_caminho):
        aplicacao_evidencia = dados.draw(
            st.sampled_from(("VPL", "ORK")),
            label=f"aplicacao_evidencia_{indice}",
        )
        arestas.append(
            {
                "indice": indice,
                "origem": indice,
                "destino": indice + 1,
                "entrada_id": f"p17-{sal_textual}-evidencia-{indice:02d}",
                "aplicacao": aplicacao_evidencia,
                "arquivo_token": tokens[aplicacao_evidencia],
                "linha": 200 + indice,
                "presente": indice != indice_evidencia_ausente,
                "pertence_ao_caminho": True,
            }
        )

    if estado_cadeia == "ambigua":
        indice = len(arestas)
        aplicacao_evidencia = dados.draw(
            st.sampled_from(("VPL", "ORK")),
            label="aplicacao_evidencia_ambigua",
        )
        arestas.append(
            {
                "indice": indice,
                "origem": 0,
                "destino": len(nos) - 1,
                "entrada_id": f"p17-{sal_textual}-evidencia-ambigua",
                "aplicacao": aplicacao_evidencia,
                "arquivo_token": tokens[aplicacao_evidencia],
                "linha": 299,
                "presente": True,
                "pertence_ao_caminho": False,
            }
        )

    especificacoes_de_entrada: list[dict[str, object]] = [
        {
            "aplicacao": "VPL",
            "entrada_id": f"p17-{sal_textual}-extremo-vpl",
            "linha": 10,
            "papel": "extremo-vpl",
            "identificadores": (nos[0],),
        },
        {
            "aplicacao": "ORK",
            "entrada_id": f"p17-{sal_textual}-extremo-ork",
            "linha": 20,
            "papel": "extremo-ork",
            "identificadores": (
                nos[quantidade_arestas_do_caminho],
            ),
        },
    ]

    if possui_valor_compartilhado:
        quantidade_vpl = dados.draw(
            st.integers(min_value=1, max_value=3),
            label="quantidade_compartilhada_vpl",
        )
        quantidade_ork = dados.draw(
            st.integers(min_value=1, max_value=3),
            label="quantidade_compartilhada_ork",
        )
        valor_compartilhado = f"syn-p17-{sal_textual}-compartilhado"
        for indice in range(quantidade_vpl):
            especificacoes_de_entrada.append(
                {
                    "aplicacao": "VPL",
                    "entrada_id": (
                        f"p17-{sal_textual}-compartilhado-vpl-{indice:02d}"
                    ),
                    "linha": 30 + indice,
                    "papel": "valor-compartilhado-vpl",
                    "identificadores": (
                        {
                            "tipo": TipoIdentificador.CHAMADA_EXTERNA,
                            "namespace": "property_17_chamada_compativel",
                            "nome_campo": "CallExternalId",
                            "valor": valor_compartilhado,
                            "original": valor_compartilhado.upper(),
                        },
                    ),
                }
            )
        for indice in range(quantidade_ork):
            especificacoes_de_entrada.append(
                {
                    "aplicacao": "ORK",
                    "entrada_id": (
                        f"p17-{sal_textual}-compartilhado-ork-{indice:02d}"
                    ),
                    "linha": 40 + indice,
                    "papel": "valor-compartilhado-ork",
                    "identificadores": (
                        {
                            "tipo": TipoIdentificador.CALL_ID,
                            "namespace": "property_17_chamada_compativel",
                            "nome_campo": "CallId",
                            "valor": valor_compartilhado,
                            "original": valor_compartilhado.swapcase(),
                        },
                    ),
                }
            )

    valor_apenas_semelhante = f"syn-p17-{sal_textual}-semelhante"
    valor_igual_namespace_incompativel = f"syn-p17-{sal_textual}-colisao"
    especificacoes_de_entrada.extend(
        (
            {
                "aplicacao": "VPL",
                "entrada_id": f"p17-{sal_textual}-ruido-vpl",
                "linha": 70,
                "papel": "coexistencia-sem-vinculo-vpl",
                "identificadores": (
                    {
                        "tipo": TipoIdentificador.SIP,
                        "namespace": "property_17_mesmo_namespace_semelhante",
                        "nome_campo": "SimilarVpl",
                        "valor": f"{valor_apenas_semelhante}-a",
                        "original": f"{valor_apenas_semelhante}-A",
                    },
                    {
                        "tipo": TipoIdentificador.TELECOM_CALL_ID,
                        "namespace": "property_17_namespace_incompativel_vpl",
                        "nome_campo": "CollisionVpl",
                        "valor": valor_igual_namespace_incompativel,
                        "original": valor_igual_namespace_incompativel.upper(),
                    },
                ),
            },
            {
                "aplicacao": "ORK",
                "entrada_id": f"p17-{sal_textual}-ruido-ork",
                "linha": 80,
                "papel": "coexistencia-sem-vinculo-ork",
                "identificadores": (
                    {
                        "tipo": TipoIdentificador.SIP,
                        "namespace": "property_17_mesmo_namespace_semelhante",
                        "nome_campo": "SimilarOrk",
                        "valor": f"{valor_apenas_semelhante}-b",
                        "original": f"{valor_apenas_semelhante}-B",
                    },
                    {
                        "tipo": TipoIdentificador.TELECOM_CALL_ID,
                        "namespace": "property_17_namespace_incompativel_ork",
                        "nome_campo": "CollisionOrk",
                        "valor": valor_igual_namespace_incompativel,
                        "original": valor_igual_namespace_incompativel.lower(),
                    },
                ),
            },
        )
    )

    for aresta in arestas:
        if aresta["presente"]:
            especificacoes_de_entrada.append(
                {
                    "aplicacao": aresta["aplicacao"],
                    "entrada_id": aresta["entrada_id"],
                    "linha": aresta["linha"],
                    "papel": "evidencia-de-vinculo",
                    # A declaração carrega os dois papéis tipados. A entrada de
                    # evidência não duplica esses nós como ocorrências, evitando
                    # transformar uma cadeia em igualdade direta artificial.
                    "identificadores": (),
                }
            )

    especificacoes_vpl = [
        item
        for item in especificacoes_de_entrada
        if item["aplicacao"] == "VPL"
    ]
    especificacoes_ork = [
        item
        for item in especificacoes_de_entrada
        if item["aplicacao"] == "ORK"
    ]
    ordem_vpl = dados.draw(
        st.permutations(tuple(range(len(especificacoes_vpl)))),
        label="ordem_colecao_vpl",
    )
    ordem_ork = dados.draw(
        st.permutations(tuple(range(len(especificacoes_ork)))),
        label="ordem_colecao_ork",
    )
    especificacoes_ordenadas = [
        especificacoes_vpl[indice] for indice in ordem_vpl
    ] + [especificacoes_ork[indice] for indice in ordem_ork]

    quantidade_entradas = len(especificacoes_ordenadas)
    ordens_de_leitura = dados.draw(
        st.permutations(tuple(range(quantidade_entradas))),
        label="ordens_de_leitura",
    )
    perfil_temporal = dados.draw(
        st.sampled_from(("mesmo_instante", "proximo", "distante")),
        label="perfil_temporal",
    )
    if perfil_temporal == "mesmo_instante":
        deslocamentos = [0] * quantidade_entradas
    elif perfil_temporal == "proximo":
        deslocamentos = dados.draw(
            st.lists(
                st.integers(min_value=-2, max_value=2),
                min_size=quantidade_entradas,
                max_size=quantidade_entradas,
            ),
            label="deslocamentos_proximos",
        )
    else:
        deslocamentos = dados.draw(
            st.lists(
                st.integers(min_value=-172_800, max_value=172_800),
                min_size=quantidade_entradas,
                max_size=quantidade_entradas,
            ),
            label="deslocamentos_distantes",
        )
    estados_iniciais = dados.draw(
        st.lists(
            st.booleans(),
            min_size=quantidade_entradas,
            max_size=quantidade_entradas,
        ),
        label="marcacoes_iniciais",
    )
    instante_base = datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(
        seconds=sal % 31_536_000
    )

    entradas_vpl: list[EntradaDeLog] = []
    entradas_ork: list[EntradaDeLog] = []
    entradas_por_id: dict[str, EntradaDeLog] = {}
    for indice_entrada, especificacao in enumerate(especificacoes_ordenadas):
        aplicacao = str(especificacao["aplicacao"])
        entrada_id = str(especificacao["entrada_id"])
        linha = int(especificacao["linha"])
        identificadores: list[IdentificadorTecnico] = []
        for indice_identificador, especificacao_id in enumerate(
            especificacao["identificadores"]
        ):
            nome_campo = str(especificacao_id["nome_campo"])
            valor_original = str(especificacao_id["original"])
            proveniencia = Proveniencia(
                arquivo_token=tokens[aplicacao],
                entrada_id=entrada_id,
                linha_inicial=linha,
                linha_final=linha,
                span_inicial=indice_identificador * 64,
                span_final=(
                    indice_identificador * 64 + len(valor_original)
                ),
                nome_campo=nome_campo,
                regra_extracao=_REGRA_EXTRACAO,
            )
            identificadores.append(
                IdentificadorTecnico(
                    tipo=especificacao_id["tipo"],
                    namespace_comparacao=str(
                        especificacao_id["namespace"]
                    ),
                    nome_campo=nome_campo,
                    valor_original=valor_original,
                    valor_normalizado=str(especificacao_id["valor"]),
                    proveniencia=proveniencia,
                )
            )

        instante = instante_base + timedelta(
            seconds=deslocamentos[indice_entrada]
        )
        entrada = EntradaDeLog(
            texto_original=(
                "EVENTO_SINTETICO_PROPERTY_17 | "
                f"papel={especificacao['papel']}"
            ),
            aplicacao=aplicacao,
            ordem_de_leitura=ordens_de_leitura[indice_entrada],
            interpretada=True,
            carimbo_de_tempo=instante,
            nivel_de_severidade="INFO",
            mensagem="evento sintético da Property 17",
            correlacionada=estados_iniciais[indice_entrada],
            entrada_id=entrada_id,
            arquivo_token=tokens[aplicacao],
            posicao_inicial=linha,
            posicao_final=linha,
            timestamp_original=instante.isoformat(),
            timestamp_normalizado=instante,
            precisao_fracionaria=0,
            formato_origem="sintetico-property-17",
            identificadores=tuple(identificadores),
        )
        entradas_por_id[entrada_id] = entrada
        if aplicacao == "VPL":
            entradas_vpl.append(entrada)
        else:
            entradas_ork.append(entrada)

    esquema_aprovado = estado_cadeia != "esquema_nao_aprovado"
    permite_correlacao = estado_cadeia != "nao_correlacionavel"
    cardinalidade = (
        Cardinalidade.UM_PARA_UM
        if estado_cadeia == "ambigua"
        else Cardinalidade.MUITOS_PARA_MUITOS
    )
    registro = RegistroDeEsquemasDeVinculo()
    registro.registrar(
        EsquemaDeVinculo(
            esquema_id=_ESQUEMA_ID,
            versao=_ESQUEMA_VERSAO,
            tipo_relacao=_TIPO_RELACAO,
            tipos_origem=tuple(TipoIdentificador),
            tipos_destino=tuple(TipoIdentificador),
            cardinalidade=cardinalidade,
            permite_expansao_de_cenario=permite_correlacao,
            aprovado=esquema_aprovado,
            reconhecedor=lambda declaracao: (
                declaracao.codigo_semantico == _CODIGO_SEMANTICO
                and _FATO_APROVADO in declaracao.fatos
            ),
        )
    )
    grafo = GrafoDeVinculos(registro)
    for entrada in (*entradas_vpl, *entradas_ork):
        grafo.adicionar_identificadores(entrada.identificadores)

    possui_declaracao = estado_cadeia != "sem_declaracao"
    declaracoes_por_aresta: dict[int, DeclaracaoSemanticaDeVinculo] = {}
    for aresta in arestas:
        proveniencia_evidencia = Proveniencia(
            arquivo_token=str(aresta["arquivo_token"]),
            entrada_id=str(aresta["entrada_id"]),
            linha_inicial=int(aresta["linha"]),
            linha_final=int(aresta["linha"]),
            nome_campo="DeclaracaoSemanticaSintetica",
            regra_extracao="property-17-declaracao-sintetica-v1",
        )
        no_origem = nos[int(aresta["origem"])]
        no_destino = nos[int(aresta["destino"])]
        proveniencia_origem = replace(
            proveniencia_evidencia,
            nome_campo=str(no_origem["nome_campo"]),
        )
        proveniencia_destino = replace(
            proveniencia_evidencia,
            nome_campo=str(no_destino["nome_campo"]),
        )
        declaracoes_por_aresta[int(aresta["indice"])] = (
            DeclaracaoSemanticaDeVinculo(
                origem=IdentificadorTecnico(
                    tipo=no_origem["tipo"],
                    namespace_comparacao=str(no_origem["namespace"]),
                    nome_campo=str(no_origem["nome_campo"]),
                    valor_original=str(no_origem["original"]),
                    valor_normalizado=str(no_origem["valor"]),
                    proveniencia=proveniencia_origem,
                ),
                destino=IdentificadorTecnico(
                    tipo=no_destino["tipo"],
                    namespace_comparacao=str(no_destino["namespace"]),
                    nome_campo=str(no_destino["nome_campo"]),
                    valor_original=str(no_destino["original"]),
                    valor_normalizado=str(no_destino["valor"]),
                    proveniencia=proveniencia_destino,
                ),
                evidencia=proveniencia_evidencia,
                codigo_semantico=_CODIGO_SEMANTICO,
                fatos=frozenset({_FATO_APROVADO}),
            )
        )

    if possui_declaracao:
        ordem_declaracoes = dados.draw(
            st.permutations(tuple(range(len(arestas)))),
            label="ordem_declaracoes",
        )
        for indice_aresta in ordem_declaracoes:
            grafo.adicionar_declaracao(
                declaracoes_por_aresta[indice_aresta]
            )

    # Modelo independente: somente flags primitivas de aprovação, permissão,
    # cardinalidade, presença da evidência e adjacência explícita participam.
    arestas_criadas = (
        set(range(len(arestas)))
        if possui_declaracao and esquema_aprovado
        else set()
    )
    destinos_por_origem: dict[int, set[int]] = defaultdict(set)
    origens_por_destino: dict[int, set[int]] = defaultdict(set)
    for indice_aresta in arestas_criadas:
        aresta = arestas[indice_aresta]
        origem = int(aresta["origem"])
        destino = int(aresta["destino"])
        destinos_por_origem[origem].add(destino)
        origens_por_destino[destino].add(origem)

    nos_em_violacao: set[int] = set()
    if cardinalidade is Cardinalidade.UM_PARA_UM:
        nos_em_violacao.update(
            origem
            for origem, destinos in destinos_por_origem.items()
            if len(destinos) > 1
        )
        nos_em_violacao.update(
            destino
            for destino, origens in origens_por_destino.items()
            if len(origens) > 1
        )

    adjacencia_criada: dict[int, set[int]] = {
        indice: set() for indice in range(len(nos))
    }
    for indice_aresta in arestas_criadas:
        aresta = arestas[indice_aresta]
        origem = int(aresta["origem"])
        destino = int(aresta["destino"])
        adjacencia_criada[origem].add(destino)
        adjacencia_criada[destino].add(origem)

    nos_ambiguos: set[int] = set()
    pendentes = set(range(len(nos)))
    while pendentes:
        inicial = min(pendentes)
        componente = {inicial}
        fila_componente = deque((inicial,))
        while fila_componente:
            atual = fila_componente.popleft()
            for vizinho in sorted(adjacencia_criada[atual]):
                if vizinho not in componente:
                    componente.add(vizinho)
                    fila_componente.append(vizinho)
        if componente.intersection(nos_em_violacao):
            nos_ambiguos.update(componente)
        pendentes.difference_update(componente)

    identidades_dos_nos = {
        (
            no["tipo"],
            str(no["namespace"]),
            str(no["valor"]),
        ): int(no["indice"])
        for no in nos
    }
    identidades_ambiguas = {
        identidade
        for identidade, indice in identidades_dos_nos.items()
        if indice in nos_ambiguos
    }

    ocorrencias: dict[
        str, list[tuple[EntradaDeLog, IdentificadorTecnico, tuple[object, str, str]]]
    ] = {"VPL": [], "ORK": []}
    for entrada in (*entradas_vpl, *entradas_ork):
        for identificador in entrada.identificadores:
            identidade = (
                identificador.tipo,
                identificador.namespace_comparacao,
                identificador.valor_normalizado,
            )
            ocorrencias[entrada.aplicacao].append(
                (entrada, identificador, identidade)
            )

    por_comparacao: dict[
        str,
        dict[
            tuple[str, str],
            list[
                tuple[
                    EntradaDeLog,
                    IdentificadorTecnico,
                    tuple[object, str, str],
                ]
            ],
        ],
    ] = {"VPL": defaultdict(list), "ORK": defaultdict(list)}
    for aplicacao in ("VPL", "ORK"):
        for ocorrencia in ocorrencias[aplicacao]:
            identificador = ocorrencia[1]
            por_comparacao[aplicacao][
                (
                    identificador.namespace_comparacao,
                    identificador.valor_normalizado,
                )
            ].append(ocorrencia)

    entradas_cobertas_esperadas: set[str] = set()
    evidencias_esperadas: set[tuple[object, ...]] = set()
    encontrou_valor_compartilhado = False
    detectou_ambiguidade = False
    chaves_compartilhadas = sorted(
        set(por_comparacao["VPL"]).intersection(
            por_comparacao["ORK"]
        )
    )
    for chave_comparacao in chaves_compartilhadas:
        candidatas_vpl = por_comparacao["VPL"][chave_comparacao]
        candidatas_ork = por_comparacao["ORK"][chave_comparacao]
        validas_vpl = [
            item
            for item in candidatas_vpl
            if item[2] not in identidades_ambiguas
        ]
        validas_ork = [
            item
            for item in candidatas_ork
            if item[2] not in identidades_ambiguas
        ]
        if len(validas_vpl) != len(candidatas_vpl) or len(
            validas_ork
        ) != len(candidatas_ork):
            detectou_ambiguidade = True
        if not validas_vpl or not validas_ork:
            continue

        encontrou_valor_compartilhado = True
        for entrada, identificador, _ in (*validas_vpl, *validas_ork):
            entradas_cobertas_esperadas.add(str(entrada.entrada_id))
            proveniencia = identificador.proveniencia
            evidencias_esperadas.add(
                (
                    "identificador_compartilhado",
                    entrada.aplicacao,
                    proveniencia.arquivo_token,
                    proveniencia.entrada_id,
                    proveniencia.linha_inicial,
                    proveniencia.linha_final,
                    proveniencia.span_inicial,
                    proveniencia.span_final,
                    proveniencia.nome_campo,
                    proveniencia.regra_extracao,
                    entrada.timestamp_original,
                    entrada.timestamp_normalizado,
                    (
                        "valor_compartilhado:"
                        f"{identificador.namespace_comparacao}"
                    ),
                    identificador.valor_original,
                )
            )

    arestas_validas = {
        indice_aresta
        for indice_aresta in arestas_criadas
        if permite_correlacao
        and int(arestas[indice_aresta]["origem"]) not in nos_ambiguos
        and int(arestas[indice_aresta]["destino"]) not in nos_ambiguos
        and str(arestas[indice_aresta]["entrada_id"]) in entradas_por_id
    }
    adjacencia_valida: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for indice_aresta in arestas_validas:
        aresta = arestas[indice_aresta]
        origem = int(aresta["origem"])
        destino = int(aresta["destino"])
        adjacencia_valida[origem].append((destino, indice_aresta))
        adjacencia_valida[destino].append((origem, indice_aresta))

    primeiros_nos: dict[str, dict[tuple[object, str, str], int]] = {
        "VPL": {},
        "ORK": {},
    }
    for aplicacao in ("VPL", "ORK"):
        for _, _, identidade in ocorrencias[aplicacao]:
            if identidade in identidades_dos_nos:
                primeiros_nos[aplicacao].setdefault(
                    identidade, identidades_dos_nos[identidade]
                )

    caminhos_validos: list[
        tuple[int, int, tuple[int, ...], tuple[int, ...]]
    ] = []
    assinaturas_de_caminho: set[tuple[int, int, tuple[int, ...]]] = set()
    for origem in primeiros_nos["VPL"].values():
        for destino in primeiros_nos["ORK"].values():
            if origem == destino:
                continue
            fila = deque((origem,))
            pais: dict[int, tuple[int, int] | None] = {origem: None}
            while fila and destino not in pais:
                atual = fila.popleft()
                for vizinho, indice_aresta in sorted(
                    adjacencia_valida.get(atual, ()),
                    key=lambda item: (item[0], item[1]),
                ):
                    if vizinho not in pais:
                        pais[vizinho] = (atual, indice_aresta)
                        fila.append(vizinho)
            if destino not in pais:
                continue

            arestas_do_caminho: list[int] = []
            nos_do_caminho = [destino]
            atual = destino
            while atual != origem:
                anterior, indice_aresta = pais[atual]  # type: ignore[misc]
                arestas_do_caminho.append(indice_aresta)
                nos_do_caminho.append(anterior)
                atual = anterior
            arestas_do_caminho.reverse()
            nos_do_caminho.reverse()
            assinatura = (
                origem,
                destino,
                tuple(arestas_do_caminho),
            )
            if assinatura not in assinaturas_de_caminho:
                assinaturas_de_caminho.add(assinatura)
                caminhos_validos.append(
                    (
                        origem,
                        destino,
                        tuple(arestas_do_caminho),
                        tuple(nos_do_caminho),
                    )
                )

    # A travessia diagnóstica pode enxergar componentes ambíguos, mas nunca os
    # converte em correlação. Ela também não usa arestas sem permissão.
    arestas_diagnosticas = {
        indice_aresta
        for indice_aresta in arestas_criadas
        if permite_correlacao
    }
    adjacencia_diagnostica: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for indice_aresta in arestas_diagnosticas:
        aresta = arestas[indice_aresta]
        origem = int(aresta["origem"])
        destino = int(aresta["destino"])
        adjacencia_diagnostica[origem].append((destino, indice_aresta))
        adjacencia_diagnostica[destino].append((origem, indice_aresta))

    detectou_caminho_ambiguo = False
    for origem in primeiros_nos["VPL"].values():
        for destino in primeiros_nos["ORK"].values():
            if origem == destino:
                continue
            fila = deque((origem,))
            pais_diagnosticos: dict[int, tuple[int, int] | None] = {
                origem: None
            }
            while fila and destino not in pais_diagnosticos:
                atual = fila.popleft()
                for vizinho, indice_aresta in sorted(
                    adjacencia_diagnostica.get(atual, ()),
                    key=lambda item: (item[0], item[1]),
                ):
                    if vizinho not in pais_diagnosticos:
                        pais_diagnosticos[vizinho] = (
                            atual,
                            indice_aresta,
                        )
                        fila.append(vizinho)
            if destino not in pais_diagnosticos:
                continue
            atual = destino
            indices_diagnosticos: list[int] = []
            while atual != origem:
                anterior, indice_aresta = pais_diagnosticos[atual]  # type: ignore[misc]
                indices_diagnosticos.append(indice_aresta)
                atual = anterior
            if any(
                int(arestas[indice]["origem"]) in nos_ambiguos
                for indice in indices_diagnosticos
            ):
                detectou_caminho_ambiguo = True
    detectou_ambiguidade = (
        detectou_ambiguidade or detectou_caminho_ambiguo
    )

    indices_de_vinculos_esperados: list[int] = []
    sequencias_de_caminhos_esperadas: list[tuple[str, ...]] = []
    for _, _, indices_arestas, indices_nos in caminhos_validos:
        identidades_no_caminho = {
            (
                nos[indice_no]["tipo"],
                str(nos[indice_no]["namespace"]),
                str(nos[indice_no]["valor"]),
            )
            for indice_no in indices_nos
        }
        for entrada, identificador, identidade in (
            *ocorrencias["VPL"],
            *ocorrencias["ORK"],
        ):
            if identidade not in identidades_no_caminho:
                continue
            entradas_cobertas_esperadas.add(str(entrada.entrada_id))
            proveniencia = identificador.proveniencia
            evidencias_esperadas.add(
                (
                    "identificador_de_cadeia",
                    entrada.aplicacao,
                    proveniencia.arquivo_token,
                    proveniencia.entrada_id,
                    proveniencia.linha_inicial,
                    proveniencia.linha_final,
                    proveniencia.span_inicial,
                    proveniencia.span_final,
                    proveniencia.nome_campo,
                    proveniencia.regra_extracao,
                    entrada.timestamp_original,
                    entrada.timestamp_normalizado,
                    "extremo_ou_no_de_cadeia",
                    identificador.valor_original,
                )
            )

        sequencia_ids: list[str] = []
        for indice_aresta in indices_arestas:
            aresta = arestas[indice_aresta]
            entrada_evidencia = entradas_por_id[str(aresta["entrada_id"])]
            entrada_id_evidencia = str(aresta["entrada_id"])
            entradas_cobertas_esperadas.add(entrada_id_evidencia)
            if indice_aresta not in indices_de_vinculos_esperados:
                indices_de_vinculos_esperados.append(indice_aresta)
            sequencia_ids.append(entrada_id_evidencia)

            no_origem = nos[int(aresta["origem"])]
            no_destino = nos[int(aresta["destino"])]
            evidencias_esperadas.add(
                (
                    "vinculo",
                    entrada_evidencia.aplicacao,
                    str(aresta["arquivo_token"]),
                    entrada_id_evidencia,
                    int(aresta["linha"]),
                    int(aresta["linha"]),
                    None,
                    None,
                    "DeclaracaoSemanticaSintetica",
                    f"vinculo:{_ESQUEMA_ID}:v{_ESQUEMA_VERSAO}",
                    entrada_evidencia.timestamp_original,
                    entrada_evidencia.timestamp_normalizado,
                    _TIPO_RELACAO,
                    (
                        f"{no_origem['original']} -> "
                        f"{no_destino['original']}"
                    ),
                )
            )
        sequencias_de_caminhos_esperadas.append(tuple(sequencia_ids))

    encontrou_cadeia = bool(caminhos_validos)
    bases_positivas: list[BaseCorrelacao] = []
    if encontrou_valor_compartilhado:
        bases_positivas.append(BaseCorrelacao.VALOR_COMPARTILHADO)
    if encontrou_cadeia:
        bases_positivas.append(BaseCorrelacao.CADEIA_DE_VINCULOS)
    correlacao_esperada = bool(bases_positivas)
    if not correlacao_esperada:
        entradas_cobertas_esperadas.clear()

    resultado = CorrelacionadorVplOrk(grafo).correlacionar(
        entradas_vpl,
        entradas_ork,
    )

    assert resultado.encontrada is correlacao_esperada
    if correlacao_esperada:
        assert resultado.base_primaria is bases_positivas[0]
        assert resultado.bases == tuple(bases_positivas)
    else:
        base_negativa = (
            BaseCorrelacao.AMBIGUA
            if detectou_ambiguidade
            else BaseCorrelacao.NENHUMA
        )
        assert resultado.base_primaria is base_negativa
        assert resultado.bases == (base_negativa,)

    assert len(resultado.entradas_vpl) == len(entradas_vpl)
    assert len(resultado.entradas_ork) == len(entradas_ork)
    for original, observado in zip(
        (*entradas_vpl, *entradas_ork),
        (*resultado.entradas_vpl, *resultado.entradas_ork),
        strict=True,
    ):
        assert replace(
            observado, correlacionada=original.correlacionada
        ) == original

    ids_marcadas = {
        str(entrada.entrada_id)
        for entrada in (*resultado.entradas_vpl, *resultado.entradas_ork)
        if entrada.correlacionada
    }
    assert ids_marcadas == entradas_cobertas_esperadas
    assert resultado.entrada_ids_cobertas == tuple(
        str(entrada.entrada_id)
        for entrada in (*resultado.entradas_vpl, *resultado.entradas_ork)
        if str(entrada.entrada_id) in entradas_cobertas_esperadas
    )

    if correlacao_esperada and detectou_ambiguidade:
        assert resultado.lacunas == (
            LacunaCorrelacao.AMBIGUIDADE_ISOLADA,
        )
    elif correlacao_esperada:
        assert resultado.lacunas == ()
    elif detectou_ambiguidade:
        assert resultado.lacunas == (
            LacunaCorrelacao.ASSOCIACAO_AMBIGUA,
        )
    else:
        assert resultado.lacunas == (LacunaCorrelacao.SEM_EVIDENCIA,)

    vinculos_observados = resultado.vinculos_percorridos
    assert tuple(
        vinculo.evidencia.entrada_id for vinculo in vinculos_observados
    ) == tuple(
        str(arestas[indice]["entrada_id"])
        for indice in indices_de_vinculos_esperados
    )
    assert len(vinculos_observados) == len(indices_de_vinculos_esperados)
    for vinculo, indice_aresta in zip(
        vinculos_observados,
        indices_de_vinculos_esperados,
        strict=True,
    ):
        aresta = arestas[indice_aresta]
        no_origem = nos[int(aresta["origem"])]
        no_destino = nos[int(aresta["destino"])]
        assert (
            vinculo.origem.tipo,
            vinculo.origem.namespace_comparacao,
            vinculo.origem.valor_normalizado,
        ) == (
            no_origem["tipo"],
            no_origem["namespace"],
            no_origem["valor"],
        )
        assert (
            vinculo.destino.tipo,
            vinculo.destino.namespace_comparacao,
            vinculo.destino.valor_normalizado,
        ) == (
            no_destino["tipo"],
            no_destino["namespace"],
            no_destino["valor"],
        )
        assert vinculo.tipo_relacao == _TIPO_RELACAO
        assert vinculo.esquema_id == _ESQUEMA_ID
        assert vinculo.esquema_versao == _ESQUEMA_VERSAO
        assert vinculo.permite_correlacao
        assert not vinculo.ambiguo

    assert tuple(
        tuple(
            vinculo.evidencia.entrada_id
            for vinculo in caminho.vinculos
        )
        for caminho in resultado.caminhos_evidenciados
    ) == tuple(sequencias_de_caminhos_esperadas)

    evidencias_observadas = {
        (
            evidencia.tipo,
            evidencia.aplicacao,
            evidencia.proveniencia.arquivo_token,
            evidencia.proveniencia.entrada_id,
            evidencia.proveniencia.linha_inicial,
            evidencia.proveniencia.linha_final,
            evidencia.proveniencia.span_inicial,
            evidencia.proveniencia.span_final,
            evidencia.proveniencia.nome_campo,
            evidencia.proveniencia.regra_extracao,
            evidencia.timestamp_original,
            evidencia.timestamp_normalizado,
            evidencia.campo_ou_condicao,
            evidencia.representacao_sanitizada,
        )
        for evidencia in resultado.evidencias
    }
    assert evidencias_observadas == evidencias_esperadas
    assert len(resultado.evidencias) == len(evidencias_esperadas)
    assert {
        evidencia.tipo for evidencia in resultado.evidencias
    }.issubset(
        {
            "identificador_compartilhado",
            "identificador_de_cadeia",
            "vinculo",
        }
    )

    if detectou_caminho_ambiguo:
        assert resultado.caminhos_bloqueados_por_ambiguidade
        assert all(
            any(vinculo.ambiguo for vinculo in caminho.vinculos)
            for caminho in resultado.caminhos_bloqueados_por_ambiguidade
        )
    else:
        assert resultado.caminhos_bloqueados_por_ambiguidade == ()

    ids_de_ruido = {
        f"p17-{sal_textual}-ruido-vpl",
        f"p17-{sal_textual}-ruido-ork",
    }
    assert ids_de_ruido.isdisjoint(ids_marcadas)

    event(f"estado_cadeia={estado_cadeia}")
    event(
        "valor_compartilhado="
        + ("presente" if possui_valor_compartilhado else "ausente")
    )
    event(f"perfil_temporal={perfil_temporal}")
    event(f"arestas_do_caminho={quantidade_arestas_do_caminho}")
    event(
        "bases="
        + (
            "+".join(base.value for base in bases_positivas)
            if bases_positivas
            else resultado.base_primaria.value
        )
    )
