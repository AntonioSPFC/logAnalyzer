"""Testes unitários dos esquemas explícitos e do grafo de vínculos.

Todos os identificadores, esquemas, timestamps e textos deste módulo são
sintéticos. Nenhuma aresta é inferida de coexistência, tempo, posição, ordem ou
similaridade: somente declarações estruturadas reconhecidas por esquemas
aprovados são apresentadas ao grafo.

Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 13.4.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

import pytest

from log_analyzer.core.modelos import (
    EntradaDeLog,
    IdentificadorTecnico,
    Proveniencia,
    TipoIdentificador,
)
from log_analyzer.core.vinculos import (
    Cardinalidade,
    ChaveDeIdentificador,
    DeclaracaoSemanticaDeVinculo,
    EsquemaDeVinculo,
    GrafoDeVinculos,
    PapelCardinalidade,
    RegistroDeEsquemasDeVinculo,
)

_CODIGO_EXPLICITO = "mapeamento-sintetico-explicito"
_FATO_EXPLICITO = "declaracao-sintetica-aprovavel"
_ARQUIVO_TOKEN = "<ARQUIVO_SINTETICO_VINCULOS>"
_INSTANTE_BASE = datetime(2035, 4, 5, 12, 30, tzinfo=timezone.utc)


def _proveniencia(
    entrada_id: str,
    linha: int,
    *,
    nome_campo: str,
    regra: str = "extrator-sintetico-v1",
) -> Proveniencia:
    return Proveniencia(
        arquivo_token=_ARQUIVO_TOKEN,
        entrada_id=entrada_id,
        linha_inicial=linha,
        linha_final=linha,
        span_inicial=0,
        span_final=16,
        nome_campo=nome_campo,
        regra_extracao=regra,
    )


def _identificador(
    valor: str,
    *,
    entrada_id: str,
    linha: int,
    tipo: TipoIdentificador = TipoIdentificador.CALL_ID,
    namespace: str | None = None,
    nome_campo: str | None = None,
) -> IdentificadorTecnico:
    nome = nome_campo or f"Campo_{tipo.value}"
    return IdentificadorTecnico(
        tipo=tipo,
        namespace_comparacao=namespace or f"namespace_{tipo.value}",
        nome_campo=nome,
        valor_original=f"<{valor.upper()}>",
        valor_normalizado=valor.casefold(),
        proveniencia=_proveniencia(
            entrada_id,
            linha,
            nome_campo=nome,
        ),
    )


def _declaracao(
    origem: str,
    destino: str,
    *,
    entrada_id: str,
    linha: int,
    tipo_origem: TipoIdentificador = TipoIdentificador.CALL_ID,
    tipo_destino: TipoIdentificador = TipoIdentificador.UUID_SESSAO,
    codigo_semantico: str = _CODIGO_EXPLICITO,
) -> DeclaracaoSemanticaDeVinculo:
    return DeclaracaoSemanticaDeVinculo(
        origem=_identificador(
            origem,
            entrada_id=entrada_id,
            linha=linha,
            tipo=tipo_origem,
            nome_campo="PapelOrigem",
        ),
        destino=_identificador(
            destino,
            entrada_id=entrada_id,
            linha=linha,
            tipo=tipo_destino,
            nome_campo="PapelDestino",
        ),
        evidencia=_proveniencia(
            entrada_id,
            linha,
            nome_campo="DeclaracaoDeRelacao",
            regra="detector-de-vinculo-sintetico-v1",
        ),
        codigo_semantico=codigo_semantico,
        fatos=frozenset({_FATO_EXPLICITO}),
    )


def _esquema(
    *,
    esquema_id: str = "esquema-sintetico",
    versao: int = 1,
    cardinalidade: Cardinalidade = Cardinalidade.MUITOS_PARA_MUITOS,
    tipos_origem: Iterable[TipoIdentificador] = (TipoIdentificador.CALL_ID,),
    tipos_destino: Iterable[TipoIdentificador] = (
        TipoIdentificador.UUID_SESSAO,
    ),
    aprovado: bool = True,
    permite_expansao: bool = True,
    codigo_reconhecido: str = _CODIGO_EXPLICITO,
) -> EsquemaDeVinculo:
    return EsquemaDeVinculo(
        esquema_id=esquema_id,
        versao=versao,
        tipo_relacao="relacao_sintetica_explicita",
        tipos_origem=frozenset(tipos_origem),
        tipos_destino=frozenset(tipos_destino),
        cardinalidade=cardinalidade,
        permite_expansao_de_cenario=permite_expansao,
        aprovado=aprovado,
        reconhecedor=lambda declaracao: (
            declaracao.codigo_semantico == codigo_reconhecido
            and _FATO_EXPLICITO in declaracao.fatos
        ),
    )


def _grafo_com_esquema(esquema: EsquemaDeVinculo) -> GrafoDeVinculos:
    registro = RegistroDeEsquemasDeVinculo()
    registro.registrar(esquema)
    return GrafoDeVinculos(registro)


def _assinatura(identificador: IdentificadorTecnico) -> tuple[str, str, str]:
    return (
        identificador.tipo.value,
        identificador.namespace_comparacao,
        identificador.valor_normalizado,
    )


def _valores(identificadores: Iterable[IdentificadorTecnico]) -> set[str]:
    return {item.valor_normalizado for item in identificadores}


def _entrada_sintetica(
    entrada_id: str,
    *,
    linha: int,
    ordem: int,
    instante: datetime,
    valores: tuple[str, ...],
) -> EntradaDeLog:
    identificadores = tuple(
        _identificador(
            valor,
            entrada_id=entrada_id,
            linha=linha,
            namespace="namespace_contexto_sintetico",
        )
        for valor in valores
    )
    return EntradaDeLog(
        texto_original=f"evento inteiramente sintético {entrada_id}",
        aplicacao="APP_SINTETICA",
        ordem_de_leitura=ordem,
        interpretada=True,
        carimbo_de_tempo=instante,
        nivel_de_severidade="INFO",
        mensagem="mensagem sintética",
        entrada_id=entrada_id,
        arquivo_token=_ARQUIVO_TOKEN,
        posicao_inicial=linha,
        posicao_final=linha,
        timestamp_original=instante.isoformat(),
        timestamp_normalizado=instante,
        identificadores=identificadores,
    )


def test_declaracao_reconhecida_cria_aresta_versionada_e_evidenciada() -> None:
    esquema = _esquema(versao=3)
    grafo = _grafo_com_esquema(esquema)
    declaracao = _declaracao(
        "chamada-sintetica-a",
        "sessao-sintetica-a",
        entrada_id="entrada-mapeamento-a",
        linha=7,
    )

    criados = grafo.adicionar_declaracao(declaracao)

    assert len(criados) == 1
    vinculo = criados[0]
    assert grafo.arestas == (vinculo,)
    assert _valores(grafo.nos) == {
        "chamada-sintetica-a",
        "sessao-sintetica-a",
    }
    assert vinculo.origem == declaracao.origem
    assert vinculo.destino == declaracao.destino
    assert vinculo.evidencia is declaracao.evidencia
    assert vinculo.esquema_id == "esquema-sintetico"
    assert vinculo.esquema_versao == 3
    assert vinculo.tipo_relacao == "relacao_sintetica_explicita"
    assert vinculo.permite_correlacao is True
    assert vinculo.ambiguo is False


def test_registro_preserva_historico_e_usa_ultima_versao_aprovada() -> None:
    registro = RegistroDeEsquemasDeVinculo()
    versao_1 = _esquema(versao=1, aprovado=True)
    versao_2 = _esquema(versao=2, aprovado=False)
    versao_3 = _esquema(versao=3, aprovado=True)
    registro.registrar(versao_1)
    registro.registrar(versao_2)
    registro.registrar(versao_3)

    assert registro.versoes("esquema-sintetico") == (1, 2, 3)
    assert registro.obter("esquema-sintetico", 1) is versao_1
    assert registro.obter("esquema-sintetico") is versao_3
    assert registro.obter_aprovado("esquema-sintetico") is versao_3
    assert registro.esquemas_aprovados() == (versao_3,)
    assert registro.esquemas_aprovados(todas_as_versoes=True) == (
        versao_1,
        versao_3,
    )

    declaracao = _declaracao(
        "chamada-versionada",
        "sessao-versionada",
        entrada_id="entrada-versionada",
        linha=9,
    )
    assert registro.reconhecer(declaracao) == (versao_3,)

    with pytest.raises(ValueError, match="já estão registrados"):
        registro.registrar(versao_3)


@pytest.mark.parametrize(
    ("cardinalidade", "iniciais", "gatilho", "papeis_esperados"),
    (
        (
            Cardinalidade.UM_PARA_UM,
            (("origem-1", "destino-1"), ("origem-2", "destino-2")),
            ("origem-1", "destino-2"),
            frozenset(
                {PapelCardinalidade.ORIGEM, PapelCardinalidade.DESTINO}
            ),
        ),
        (
            Cardinalidade.UM_PARA_MUITOS,
            (("origem-1", "destino-1"), ("origem-1", "destino-2")),
            ("origem-2", "destino-1"),
            frozenset({PapelCardinalidade.DESTINO}),
        ),
        (
            Cardinalidade.MUITOS_PARA_UM,
            (("origem-1", "destino-1"), ("origem-2", "destino-1")),
            ("origem-1", "destino-2"),
            frozenset({PapelCardinalidade.ORIGEM}),
        ),
        (
            Cardinalidade.MUITOS_PARA_MUITOS,
            (
                ("origem-1", "destino-1"),
                ("origem-1", "destino-2"),
                ("origem-2", "destino-1"),
            ),
            ("origem-2", "destino-2"),
            frozenset(),
        ),
    ),
)
def test_cardinalidades_direcionais_detectam_apenas_limites_excedidos(
    cardinalidade: Cardinalidade,
    iniciais: tuple[tuple[str, str], ...],
    gatilho: tuple[str, str],
    papeis_esperados: frozenset[PapelCardinalidade],
) -> None:
    grafo = _grafo_com_esquema(_esquema(cardinalidade=cardinalidade))
    for indice, (origem, destino) in enumerate(iniciais, start=1):
        grafo.adicionar_declaracao(
            _declaracao(
                origem,
                destino,
                entrada_id=f"entrada-cardinalidade-{indice}",
                linha=indice,
            )
        )

    assert grafo.violacoes_cardinalidade == ()
    assert all(not vinculo.ambiguo for vinculo in grafo.arestas)

    grafo.adicionar_declaracao(
        _declaracao(
            *gatilho,
            entrada_id="entrada-cardinalidade-gatilho",
            linha=20,
        )
    )

    assert {
        violacao.papel for violacao in grafo.violacoes_cardinalidade
    } == papeis_esperados
    if papeis_esperados:
        assert all(
            violacao.quantidade == 2 and violacao.limite == 1
            for violacao in grafo.violacoes_cardinalidade
        )
        assert len(grafo.componentes_ambiguos) == 1
        assert all(vinculo.ambiguo for vinculo in grafo.arestas)
    else:
        assert grafo.componentes_ambiguos == ()
        assert all(not vinculo.ambiguo for vinculo in grafo.arestas)


def test_ambiguidade_fica_isolada_e_nao_expande_para_componente_valido() -> None:
    esquema = _esquema(
        cardinalidade=Cardinalidade.UM_PARA_UM,
        tipos_destino=(TipoIdentificador.CALL_ID,),
    )
    grafo = _grafo_com_esquema(esquema)
    declaracoes = (
        _declaracao(
            "raiz-ambigua",
            "destino-ambiguo-1",
            entrada_id="entrada-ambigua-1",
            linha=1,
            tipo_destino=TipoIdentificador.CALL_ID,
        ),
        _declaracao(
            "raiz-ambigua",
            "destino-ambiguo-2",
            entrada_id="entrada-ambigua-2",
            linha=2,
            tipo_destino=TipoIdentificador.CALL_ID,
        ),
        _declaracao(
            "raiz-valida",
            "destino-valido",
            entrada_id="entrada-valida",
            linha=30,
            tipo_destino=TipoIdentificador.CALL_ID,
        ),
    )
    grafo.adicionar_declaracoes(declaracoes)

    ambiguos = {
        item.valor_normalizado for item in grafo.componentes_ambiguos[0]
    }
    assert ambiguos == {
        "raiz-ambigua",
        "destino-ambiguo-1",
        "destino-ambiguo-2",
    }
    for identificador in declaracoes[0].origem, declaracoes[0].destino, declaracoes[1].destino:
        assert grafo.eh_ambiguo(identificador)
        assert not grafo.pode_sustentar_classificacao(identificador)
    assert not grafo.eh_ambiguo(declaracoes[2].origem)
    assert grafo.pode_sustentar_classificacao(declaracoes[2].origem)

    travessia_bloqueada = grafo.percorrer_bfs(declaracoes[0].origem)
    assert _valores(travessia_bloqueada.identificadores) == {"raiz-ambigua"}
    assert travessia_bloqueada.componente_ambiguo is True
    assert travessia_bloqueada.bloqueada_por_ambiguidade is True
    assert travessia_bloqueada.vinculos_percorridos == ()

    travessia_valida = grafo.percorrer_bfs(declaracoes[2].origem)
    assert _valores(travessia_valida.identificadores) == {
        "raiz-valida",
        "destino-valido",
    }
    assert travessia_valida.componente_ambiguo is False
    assert travessia_valida.bloqueada_por_ambiguidade is False

    diagnostico = grafo.inspecionar_componente(declaracoes[0].origem)
    assert _valores(diagnostico.identificadores) == ambiguos
    assert len(diagnostico.vinculos_percorridos) == 2
    assert diagnostico.componente_ambiguo is True


def test_ciclo_e_fechado_uma_vez_sem_repetir_nos_ou_caminhos() -> None:
    esquema = _esquema(
        tipos_destino=(TipoIdentificador.CALL_ID,),
        cardinalidade=Cardinalidade.MUITOS_PARA_MUITOS,
    )
    grafo = _grafo_com_esquema(esquema)
    declaracoes = (
        _declaracao(
            "no-a",
            "no-b",
            entrada_id="aresta-a-b",
            linha=1,
            tipo_destino=TipoIdentificador.CALL_ID,
        ),
        _declaracao(
            "no-b",
            "no-c",
            entrada_id="aresta-b-c",
            linha=2,
            tipo_destino=TipoIdentificador.CALL_ID,
        ),
        _declaracao(
            "no-c",
            "no-a",
            entrada_id="aresta-c-a",
            linha=3,
            tipo_destino=TipoIdentificador.CALL_ID,
        ),
    )
    grafo.adicionar_declaracoes(declaracoes)

    travessia = grafo.percorrer_bfs(declaracoes[0].origem)

    assert len(grafo.arestas) == 3
    assert _valores(travessia.identificadores) == {"no-a", "no-b", "no-c"}
    assert len(travessia.identificadores) == 3
    assert len(travessia.caminhos) == 2
    assert all(len(caminho.passos) == 1 for caminho in travessia.caminhos)
    assert travessia.componente_ambiguo is False


def test_componentes_desconectados_permanecem_separados() -> None:
    esquema = _esquema(tipos_destino=(TipoIdentificador.CALL_ID,))
    grafo = _grafo_com_esquema(esquema)
    primeira = _declaracao(
        "componente-a-1",
        "componente-a-2",
        entrada_id="aresta-componente-a",
        linha=1,
        tipo_destino=TipoIdentificador.CALL_ID,
    )
    segunda = _declaracao(
        "componente-b-1",
        "componente-b-2",
        entrada_id="aresta-componente-b",
        linha=10,
        tipo_destino=TipoIdentificador.CALL_ID,
    )
    isolado = _identificador(
        "no-isolado",
        entrada_id="entrada-isolada",
        linha=20,
    )
    grafo.adicionar_declaracao(primeira)
    grafo.adicionar_declaracao(segunda)
    grafo.adicionar_identificador(isolado)

    assert _valores(grafo.componente_de(primeira.origem)) == {
        "componente-a-1",
        "componente-a-2",
    }
    assert _valores(grafo.componente_de(segunda.origem)) == {
        "componente-b-1",
        "componente-b-2",
    }
    assert _valores(grafo.componente_de(isolado)) == {"no-isolado"}
    assert _valores(grafo.percorrer_bfs(primeira.origem)) == {
        "componente-a-1",
        "componente-a-2",
    }
    assert grafo.encontrar_caminho(primeira.origem, segunda.origem) is None


def test_ordem_da_bfs_independe_da_ordem_de_insercao() -> None:
    alvos = (
        ("vizinho-sessao-z", TipoIdentificador.UUID_SESSAO, "aresta-z", 4),
        ("vizinho-sip", TipoIdentificador.SIP, "aresta-sip", 2),
        ("vizinho-canal", TipoIdentificador.UUID_CANAL, "aresta-canal", 3),
        ("vizinho-sessao-a", TipoIdentificador.UUID_SESSAO, "aresta-a", 1),
    )
    esquema = _esquema(
        tipos_destino=(
            TipoIdentificador.SIP,
            TipoIdentificador.UUID_CANAL,
            TipoIdentificador.UUID_SESSAO,
        )
    )
    semente = _identificador(
        "raiz-bfs",
        entrada_id="semente-bfs",
        linha=1,
    )

    ordens_observadas: list[tuple[tuple[str, str, str], ...]] = []
    destinos_observados: list[tuple[tuple[str, str, str], ...]] = []
    for ordem in ((0, 1, 2, 3), (3, 2, 1, 0), (1, 3, 0, 2)):
        grafo = _grafo_com_esquema(esquema)
        for indice in ordem:
            valor, tipo, entrada_id, linha = alvos[indice]
            grafo.adicionar_declaracao(
                _declaracao(
                    "raiz-bfs",
                    valor,
                    entrada_id=entrada_id,
                    linha=linha,
                    tipo_destino=tipo,
                )
            )
        travessia = grafo.percorrer_bfs(semente)
        ordens_observadas.append(
            tuple(_assinatura(item) for item in travessia.identificadores)
        )
        destinos_observados.append(
            tuple(_assinatura(caminho.destino) for caminho in travessia.caminhos)
        )

    alvos_esperados = sorted(
        (
            _identificador(
                valor,
                entrada_id=entrada_id,
                linha=linha,
                tipo=tipo,
                nome_campo="PapelDestino",
            )
            for valor, tipo, entrada_id, linha in alvos
        ),
        key=lambda item: (
            item.tipo.value,
            ChaveDeIdentificador.de_identificador(item).digest,
        ),
    )
    ordem_esperada = (
        _assinatura(semente),
        *(_assinatura(item) for item in alvos_esperados),
    )
    destinos_esperados = tuple(
        _assinatura(item) for item in alvos_esperados
    )

    assert ordens_observadas == [ordem_esperada] * 3
    assert destinos_observados == [destinos_esperados] * 3


def test_bfs_escolhe_caminho_minimo_com_evidencia_em_cada_passo() -> None:
    esquema = _esquema(tipos_destino=(TipoIdentificador.CALL_ID,))
    grafo = _grafo_com_esquema(esquema)
    definicoes = (
        ("raiz", "ramo-longo-1", "e-raiz-longo", 1),
        ("ramo-longo-1", "ramo-longo-2", "e-longo-1-2", 2),
        ("ramo-longo-2", "alvo", "e-longo-2-alvo", 3),
        ("raiz", "atalho", "e-raiz-atalho", 4),
        ("atalho", "alvo", "e-atalho-alvo", 5),
    )
    por_entrada: dict[str, DeclaracaoSemanticaDeVinculo] = {}
    for origem, destino, entrada_id, linha in definicoes:
        declaracao = _declaracao(
            origem,
            destino,
            entrada_id=entrada_id,
            linha=linha,
            tipo_destino=TipoIdentificador.CALL_ID,
        )
        por_entrada[entrada_id] = declaracao
        grafo.adicionar_declaracao(declaracao)

    semente = _identificador(
        "raiz",
        entrada_id="semente-caminho",
        linha=1,
    )
    alvo = _identificador(
        "alvo",
        entrada_id="consulta-alvo",
        linha=99,
    )
    caminho = grafo.encontrar_caminho(semente, alvo)

    assert caminho is not None
    assert len(caminho.passos) == 2
    assert [caminho.semente.valor_normalizado] + [
        passo.destino.valor_normalizado for passo in caminho.passos
    ] == ["raiz", "atalho", "alvo"]
    assert tuple(
        evidencia.entrada_id for evidencia in caminho.evidencias
    ) == ("e-raiz-atalho", "e-atalho-alvo")
    assert caminho.evidencias == tuple(
        passo.vinculo.evidencia for passo in caminho.passos
    )
    assert all(
        passo.evidencia is passo.vinculo.evidencia
        for passo in caminho.passos
    )
    assert all(passo.sentido_original for passo in caminho.passos)
    assert caminho.passos[0].vinculo.evidencia is por_entrada[
        "e-raiz-atalho"
    ].evidencia
    assert caminho.passos[1].vinculo.evidencia is por_entrada[
        "e-atalho-alvo"
    ].evidencia


def test_contexto_sem_declaracao_nao_cria_vinculo_implicito() -> None:
    coexistente = _entrada_sintetica(
        "entrada-coexistente",
        linha=10,
        ordem=0,
        instante=_INSTANTE_BASE,
        valores=("coexistente-a", "coexistente-b"),
    )
    proxima_1 = _entrada_sintetica(
        "entrada-proxima-1",
        linha=20,
        ordem=1,
        instante=_INSTANTE_BASE + timedelta(seconds=1),
        valores=("adjacente-similar-0001",),
    )
    proxima_2 = _entrada_sintetica(
        "entrada-proxima-2",
        linha=21,
        ordem=2,
        instante=_INSTANTE_BASE + timedelta(seconds=1, microseconds=1),
        valores=("adjacente-similar-000l",),
    )
    distante = _entrada_sintetica(
        "entrada-distante",
        linha=200,
        ordem=99,
        instante=_INSTANTE_BASE + timedelta(days=30),
        valores=("valor-distante",),
    )
    entradas = (coexistente, proxima_1, proxima_2, distante)

    # As precondições tornam explícitos todos os sinais proibidos de inferência.
    assert len(coexistente.identificadores) == 2
    assert proxima_2.timestamp_normalizado - proxima_1.timestamp_normalizado == timedelta(
        microseconds=1
    )
    assert proxima_2.posicao_inicial == proxima_1.posicao_final + 1
    assert proxima_2.ordem_de_leitura == proxima_1.ordem_de_leitura + 1
    assert proxima_1.identificadores[0].valor_normalizado.startswith(
        "adjacente-similar-000"
    )
    assert proxima_2.identificadores[0].valor_normalizado.startswith(
        "adjacente-similar-000"
    )

    assinaturas_por_ordem: list[set[tuple[str, str, str]]] = []
    for sequencia in (entradas, tuple(reversed(entradas))):
        grafo = GrafoDeVinculos()
        for entrada in sequencia:
            grafo.adicionar_identificadores(entrada.identificadores)

        assert grafo.arestas == ()
        assert grafo.vinculos == ()
        assert grafo.componentes_ambiguos == ()
        assert all(
            len(grafo.componente_de(identificador)) == 1
            for entrada in entradas
            for identificador in entrada.identificadores
        )
        assinaturas_por_ordem.append(
            {_assinatura(item) for item in grafo.nos}
        )

    assert assinaturas_por_ordem[0] == assinaturas_por_ordem[1]


@pytest.mark.parametrize(
    "modo",
    ("sem_esquema", "esquema_nao_aprovado", "codigo_nao_reconhecido"),
)
def test_declaracao_sem_reconhecimento_aprovado_nao_cria_aresta(
    modo: str,
) -> None:
    registro = RegistroDeEsquemasDeVinculo()
    if modo == "esquema_nao_aprovado":
        registro.registrar(_esquema(aprovado=False))
    elif modo == "codigo_nao_reconhecido":
        registro.registrar(
            _esquema(codigo_reconhecido="outro-codigo-sintetico")
        )
    grafo = GrafoDeVinculos(registro)
    declaracao = _declaracao(
        "origem-sem-aprovacao",
        "destino-sem-aprovacao",
        entrada_id=f"entrada-{modo}",
        linha=50,
    )

    assert grafo.adicionar_declaracao(declaracao) == ()
    assert grafo.arestas == ()
    assert _valores(grafo.nos) == {
        "origem-sem-aprovacao",
        "destino-sem-aprovacao",
    }
    assert grafo.componente_de(declaracao.origem) == (declaracao.origem,)
    assert grafo.componente_de(declaracao.destino) == (declaracao.destino,)
