"""Property 16: ambiguidade de vínculos é isolada e fail-closed.

Todos os identificadores, componentes e metadados são sintéticos e gerados em
memória. O teste não lê arquivos, fontes locais nem serviços externos.
"""

from __future__ import annotations

import string
from collections.abc import Sequence
from uuid import UUID

from hypothesis import given, settings, strategies as st

from log_analyzer.core.explicabilidade import (
    CodigoMensagemExplicabilidade,
    compor_diagnostico_sem_regra,
)
from log_analyzer.core.modelos import (
    Categoria,
    EntradaDeLog,
    EstadoCausaRaiz,
    IdentificadorTecnico,
    Proveniencia,
    ResultadoCausaRaiz,
    TipoIdentificador,
)
from log_analyzer.core.vinculos import (
    Cardinalidade,
    DeclaracaoSemanticaDeVinculo,
    EsquemaDeVinculo,
    GrafoDeVinculos,
    PapelCardinalidade,
    RegistroDeEsquemasDeVinculo,
)


_Identidade = tuple[TipoIdentificador, str, str]
_FATO_EXPLICITO = "DECLARACAO_EXPLICITA_SINTETICA"
_ALFABETO_CODIGO = string.ascii_uppercase + string.digits


def _identidade(identificador: IdentificadorTecnico) -> _Identidade:
    return (
        identificador.tipo,
        identificador.namespace_comparacao,
        identificador.valor_normalizado,
    )


def _proveniencia(
    componente: str,
    indice: int,
    linha: int,
    nome_campo: str,
) -> Proveniencia:
    return Proveniencia(
        arquivo_token="<ARQUIVO_PROPERTY_16>",
        entrada_id=f"property-16-{componente}-{indice}",
        linha_inicial=linha,
        linha_final=linha,
        nome_campo=nome_campo,
        regra_extracao="declaracao-explicita-sintetica-v1",
    )


def _identificador(
    tipo: TipoIdentificador,
    valor: UUID,
    proveniencia: Proveniencia,
) -> IdentificadorTecnico:
    if tipo is TipoIdentificador.CALL_ID:
        namespace = "chamada_externa"
        nome_campo = "CallId"
    else:
        namespace = "uuid_sessao"
        nome_campo = "SessionUuid"
    return IdentificadorTecnico(
        tipo=tipo,
        namespace_comparacao=namespace,
        nome_campo=nome_campo,
        valor_original=str(valor).upper(),
        valor_normalizado=str(valor),
        proveniencia=proveniencia,
    )


def _declaracao(
    valor_origem: UUID,
    valor_destino: UUID,
    componente: str,
    indice: int,
    linha: int,
    codigo_semantico: str,
) -> DeclaracaoSemanticaDeVinculo:
    origem = _identificador(
        TipoIdentificador.CALL_ID,
        valor_origem,
        _proveniencia(componente, indice, linha, "CallId"),
    )
    destino = _identificador(
        TipoIdentificador.UUID_SESSAO,
        valor_destino,
        _proveniencia(componente, indice, linha, "SessionUuid"),
    )
    evidencia = _proveniencia(
        componente,
        indice,
        linha,
        "declaracao_semantica",
    )
    return DeclaracaoSemanticaDeVinculo(
        origem=origem,
        destino=destino,
        evidencia=evidencia,
        codigo_semantico=codigo_semantico,
        fatos=frozenset({_FATO_EXPLICITO}),
    )


def _entrada_para_diagnostico(
    proveniencia: Proveniencia,
) -> EntradaDeLog:
    return EntradaDeLog(
        texto_original="EVENTO_SINTETICO_COM_VINCULO_AMBIGUO",
        aplicacao="VPL",
        ordem_de_leitura=0,
        interpretada=False,
        categoria=Categoria.NAO_CLASSIFICADA,
        entrada_id=proveniencia.entrada_id,
        arquivo_token=proveniencia.arquivo_token,
        posicao_inicial=proveniencia.linha_inicial,
        posicao_final=proveniencia.linha_final,
    )


# Feature: log-analyzer-phase-2, Property 16: Ambiguidade é isolada e não classifica
@given(
    valores=st.lists(
        st.uuids(version=4),
        min_size=12,
        max_size=12,
        unique=True,
    ),
    quantidade_contradicoes=st.integers(min_value=2, max_value=4),
    quantidade_componentes_saudaveis=st.integers(min_value=1, max_value=3),
    papel_violado=st.sampled_from(
        (PapelCardinalidade.ORIGEM, PapelCardinalidade.DESTINO)
    ),
    versao_esquema=st.integers(min_value=1, max_value=100),
    sufixo_codigo=st.text(
        alphabet=_ALFABETO_CODIGO,
        min_size=1,
        max_size=12,
    ),
    linha_base=st.integers(min_value=1, max_value=100_000),
    ordem_insercao=st.permutations(tuple(range(7))),
)
@settings(max_examples=100)
def test_property_16_ambiguidade_e_isolada_e_nao_classifica(
    valores: list[UUID],
    quantidade_contradicoes: int,
    quantidade_componentes_saudaveis: int,
    papel_violado: PapelCardinalidade,
    versao_esquema: int,
    sufixo_codigo: str,
    linha_base: int,
    ordem_insercao: Sequence[int],
) -> None:
    """Só o componente contraditório é bloqueado e permanece sem conclusão.

    **Validates: Requirements 8.6**
    """

    codigo_semantico = f"MAPEIA_SESSAO_{sufixo_codigo}"
    registro = RegistroDeEsquemasDeVinculo()
    registro.registrar(
        EsquemaDeVinculo(
            esquema_id=f"esquema-property-16-{sufixo_codigo}",
            versao=versao_esquema,
            tipo_relacao="mapeia_sessao_sintetica",
            tipo_origem=TipoIdentificador.CALL_ID,
            tipo_destino=TipoIdentificador.UUID_SESSAO,
            cardinalidade=Cardinalidade.UM_PARA_UM,
            permite_expansao_de_cenario=True,
            aprovado=True,
            reconhecedor=lambda declaracao: (
                declaracao.codigo_semantico == codigo_semantico
                and _FATO_EXPLICITO in declaracao.fatos
            ),
        )
    )
    grafo = GrafoDeVinculos(registro)

    declaracoes_por_slot: dict[int, DeclaracaoSemanticaDeVinculo] = {}
    nos_afetados: dict[_Identidade, IdentificadorTecnico] = {}
    identificador_compartilhado: IdentificadorTecnico | None = None

    for indice in range(quantidade_contradicoes):
        if papel_violado is PapelCardinalidade.ORIGEM:
            valor_origem = valores[0]
            valor_destino = valores[indice + 1]
        else:
            valor_origem = valores[indice + 1]
            valor_destino = valores[0]
        declaracao = _declaracao(
            valor_origem,
            valor_destino,
            "ambiguo",
            indice,
            linha_base + indice,
            codigo_semantico,
        )
        declaracoes_por_slot[indice] = declaracao
        for identificador in (declaracao.origem, declaracao.destino):
            nos_afetados.setdefault(_identidade(identificador), identificador)
        identificador_compartilhado = (
            declaracao.origem
            if papel_violado is PapelCardinalidade.ORIGEM
            else declaracao.destino
        )

    componentes_saudaveis: list[
        tuple[IdentificadorTecnico, IdentificadorTecnico]
    ] = []
    for indice in range(quantidade_componentes_saudaveis):
        declaracao = _declaracao(
            valores[5 + (indice * 2)],
            valores[6 + (indice * 2)],
            f"saudavel-{indice}",
            indice,
            linha_base + 10 + indice,
            codigo_semantico,
        )
        declaracoes_por_slot[4 + indice] = declaracao
        componentes_saudaveis.append(
            (declaracao.origem, declaracao.destino)
        )

    for slot in ordem_insercao:
        declaracao = declaracoes_por_slot.get(slot)
        if declaracao is not None:
            criados = grafo.adicionar_declaracao(declaracao)
            assert len(criados) == 1

    assert identificador_compartilhado is not None
    identidades_afetadas = frozenset(nos_afetados)
    componentes_ambiguos = {
        frozenset(_identidade(no) for no in componente)
        for componente in grafo.componentes_ambiguos
    }
    assert componentes_ambiguos == {identidades_afetadas}

    violacoes = grafo.violacoes_cardinalidade
    assert len(violacoes) == 1
    assert violacoes[0].papel is papel_violado
    assert violacoes[0].quantidade == quantidade_contradicoes
    assert violacoes[0].limite == 1
    assert (
        _identidade(violacoes[0].identificador)
        == _identidade(identificador_compartilhado)
    )

    for identificador in nos_afetados.values():
        assert grafo.eh_ambiguo(identificador)
        assert not grafo.pode_sustentar_classificacao(identificador)
        travessia = grafo.percorrer_bfs(identificador)
        assert tuple(map(_identidade, travessia.identificadores)) == (
            _identidade(identificador),
        )
        assert travessia.caminhos == ()
        assert travessia.vinculos_percorridos == ()
        assert travessia.componente_ambiguo
        assert travessia.bloqueada_por_ambiguidade

    outros_afetados = [
        identificador
        for identificador in nos_afetados.values()
        if _identidade(identificador)
        != _identidade(identificador_compartilhado)
    ]
    assert outros_afetados
    assert (
        grafo.encontrar_caminho(
            identificador_compartilhado,
            outros_afetados[0],
        )
        is None
    )
    assert not grafo.pode_sustentar_classificacao()

    for origem, destino in componentes_saudaveis:
        identidades_saudaveis = {
            _identidade(origem),
            _identidade(destino),
        }
        assert not grafo.eh_ambiguo(origem)
        assert not grafo.eh_ambiguo(destino)
        assert grafo.pode_sustentar_classificacao(origem)
        assert grafo.pode_sustentar_classificacao(destino)

        travessia = grafo.percorrer_bfs(origem)
        assert set(map(_identidade, travessia.identificadores)) == (
            identidades_saudaveis
        )
        assert not travessia.componente_ambiguo
        assert not travessia.bloqueada_por_ambiguidade
        assert len(travessia.caminhos) == 1
        assert len(travessia.vinculos_percorridos) == 1
        assert not travessia.vinculos_percorridos[0].ambiguo

        caminho = grafo.encontrar_caminho(origem, destino)
        assert caminho is not None
        assert len(caminho.passos) == 1
        assert caminho.evidencias == (
            travessia.vinculos_percorridos[0].evidencia,
        )

    for vinculo in grafo.arestas:
        pertence_ao_afetado = (
            _identidade(vinculo.origem) in identidades_afetadas
            and _identidade(vinculo.destino) in identidades_afetadas
        )
        assert vinculo.ambiguo is pertence_ao_afetado

    entrada = _entrada_para_diagnostico(
        identificador_compartilhado.proveniencia
    )
    explicacao = compor_diagnostico_sem_regra((entrada,))
    assert explicacao.categoria_de_cenario is Categoria.NAO_CLASSIFICADA
    assert explicacao.regra_aplicada is None
    assert explicacao.condicoes_satisfeitas == ()
    assert explicacao.evidencias == ()
    assert explicacao.vinculos_percorridos == ()
    assert explicacao.causa_raiz == ResultadoCausaRaiz()
    assert explicacao.causa_raiz.estado is EstadoCausaRaiz.NAO_DETERMINADA
    assert [mensagem.codigo for mensagem in explicacao.mensagens] == [
        CodigoMensagemExplicabilidade.NENHUMA_REGRA_VALIDADA_CORRESPONDEU,
        CodigoMensagemExplicabilidade.CAUSA_RAIZ_NAO_DETERMINADA,
    ]
    assert all(
        mensagem.hipotese_causal is None
        for mensagem in explicacao.mensagens
    )

    mensagem_segura = " ".join(
        mensagem.descricao_segura for mensagem in explicacao.mensagens
    ).casefold()
    assert entrada.texto_original.casefold() not in mensagem_segura
    assert codigo_semantico.casefold() not in mensagem_segura
    assert all(str(valor).casefold() not in mensagem_segura for valor in valores)
