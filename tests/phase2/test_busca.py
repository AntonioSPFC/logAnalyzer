"""Testes unitários da busca estruturada, literal e por vínculos.

Todos os valores, textos, identificadores e esquemas deste módulo são
sintéticos. Os testes exercitam o índice HMAC real e somente relações
explicitamente reconhecidas por esquemas locais aprovados.

Validates: Requirements 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 8.3.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import pytest

from log_analyzer.core.busca import BuscadorDeCenario, MotivoInclusaoBusca
from log_analyzer.core.excecoes import ErroDeIdentificador
from log_analyzer.core.indice import IndiceTemporario
from log_analyzer.core.modelos import (
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
)

_ARQUIVO_TOKEN = "<ARQUIVO_BUSCA_SINTETICO>"
_NAMESPACE_CHAMADA = "cenario_sintetico"
_NAMESPACE_SESSAO = "sessao_sintetica"
_CODIGO_RELACAO = "declaracao_sintetica_explicita"


@pytest.fixture
def indice() -> Iterator[IndiceTemporario]:
    with IndiceTemporario(limiar_memoria=1_000) as indice_temporario:
        yield indice_temporario


def _proveniencia(
    entrada_id: str,
    linha: int,
    *,
    nome_campo: str,
    regra: str = "extrator-busca-sintetico-v1",
) -> Proveniencia:
    return Proveniencia(
        arquivo_token=_ARQUIVO_TOKEN,
        entrada_id=entrada_id,
        linha_inicial=linha,
        linha_final=linha,
        span_inicial=0,
        span_final=24,
        nome_campo=nome_campo,
        regra_extracao=regra,
    )


def _identificador(
    valor: str,
    *,
    entrada_id: str,
    linha: int,
    namespace: str = _NAMESPACE_CHAMADA,
    tipo: TipoIdentificador = TipoIdentificador.CALL_ID,
    nome_campo: str = "CallIdSintetico",
) -> IdentificadorTecnico:
    return IdentificadorTecnico(
        tipo=tipo,
        namespace_comparacao=namespace,
        nome_campo=nome_campo,
        valor_original=f"<{valor.upper()}>",
        valor_normalizado=valor.casefold(),
        proveniencia=_proveniencia(
            entrada_id,
            linha,
            nome_campo=nome_campo,
        ),
    )


def _entrada(
    entrada_id: str,
    texto: str,
    *,
    ordem: int,
    linha: int,
    linha_final: int | None = None,
    identificadores: tuple[IdentificadorTecnico, ...] = (),
) -> EntradaDeLog:
    return EntradaDeLog(
        texto_original=texto,
        aplicacao="VPL" if ordem % 2 == 0 else "ORK",
        ordem_de_leitura=ordem,
        interpretada=False,
        entrada_id=entrada_id,
        arquivo_token=_ARQUIVO_TOKEN,
        posicao_inicial=linha,
        posicao_final=linha if linha_final is None else linha_final,
        identificadores=identificadores,
    )


def _indexar_entradas(
    indice: IndiceTemporario,
    entradas: tuple[EntradaDeLog, ...],
) -> None:
    for entrada in entradas:
        assert entrada.entrada_id is not None
        assert entrada.arquivo_token is not None
        assert entrada.posicao_inicial is not None
        assert entrada.posicao_final is not None
        inicio_byte = entrada.ordem_de_leitura * 1_000
        indice.adicionar_entrada(
            entrada_id=entrada.entrada_id,
            arquivo_token=entrada.arquivo_token,
            aplicacao_codigo=entrada.aplicacao,
            ordem_de_leitura=entrada.ordem_de_leitura,
            inicio_byte=inicio_byte,
            fim_byte=inicio_byte + len(entrada.texto_original.encode("utf-8")),
            linha_inicial=entrada.posicao_inicial,
            linha_final=entrada.posicao_final,
        )
        for identificador in entrada.identificadores:
            indice.indexar_identificador(
                entrada_id=entrada.entrada_id,
                namespace=identificador.namespace_comparacao,
                valor_normalizado=identificador.valor_normalizado,
            )


def _esquema(
    *,
    permite_expansao: bool,
    cardinalidade: Cardinalidade = Cardinalidade.MUITOS_PARA_MUITOS,
) -> EsquemaDeVinculo:
    return EsquemaDeVinculo(
        esquema_id="esquema-busca-sintetico",
        versao=1,
        tipo_relacao="mapeamento_sintetico_explicito",
        tipo_origem=TipoIdentificador.CALL_ID,
        tipo_destino=TipoIdentificador.UUID_SESSAO,
        cardinalidade=cardinalidade,
        permite_expansao_de_cenario=permite_expansao,
        aprovado=True,
        reconhecedor=lambda declaracao: (
            declaracao.codigo_semantico == _CODIGO_RELACAO
        ),
    )


def _declaracao(
    origem: str,
    destino: str,
    *,
    entrada_id: str,
    linha: int,
) -> DeclaracaoSemanticaDeVinculo:
    return DeclaracaoSemanticaDeVinculo(
        origem=_identificador(
            origem,
            entrada_id=entrada_id,
            linha=linha,
            nome_campo="PapelChamada",
        ),
        destino=_identificador(
            destino,
            entrada_id=entrada_id,
            linha=linha,
            namespace=_NAMESPACE_SESSAO,
            tipo=TipoIdentificador.UUID_SESSAO,
            nome_campo="PapelSessao",
        ),
        evidencia=_proveniencia(
            entrada_id,
            linha,
            nome_campo="DeclaracaoDeRelacao",
            regra="detector-de-vinculo-sintetico-v1",
        ),
        codigo_semantico=_CODIGO_RELACAO,
    )


def _snapshot_indice(indice: IndiceTemporario) -> tuple[object, ...]:
    return (
        len(indice),
        tuple(indice.iterar_entradas()),
        tuple(indice.iterar_identificadores()),
        tuple(indice.iterar_arestas()),
    )


def test_igualdade_estruturada_usa_hmac_e_respeita_namespace(
    indice: IndiceTemporario,
) -> None:
    valor = "identificador-sintetico-42"
    identificador_chamada = _identificador(
        valor,
        entrada_id="entrada-chamada",
        linha=1,
    )
    identificador_sessao = _identificador(
        valor,
        entrada_id="entrada-sessao",
        linha=2,
        namespace=_NAMESPACE_SESSAO,
        tipo=TipoIdentificador.UUID_SESSAO,
        nome_campo="SessaoSintetica",
    )
    entradas = (
        _entrada(
            "entrada-chamada",
            "evento estruturado de chamada",
            ordem=0,
            linha=1,
            identificadores=(identificador_chamada,),
        ),
        _entrada(
            "entrada-sessao",
            "evento estruturado de sessao",
            ordem=1,
            linha=2,
            identificadores=(identificador_sessao,),
        ),
    )
    _indexar_entradas(indice, entradas)

    resultado = BuscadorDeCenario(indice).buscar(
        entradas,
        valor.upper(),
        namespaces=(_NAMESPACE_CHAMADA,),
    )

    assert resultado.entrada_ids == ("entrada-chamada",)
    assert resultado.inclusoes[0].motivos == (
        MotivoInclusaoBusca.IGUALDADE_ESTRUTURADA,
    )
    assert resultado.inclusoes[0].namespaces_correspondentes == (
        _NAMESPACE_CHAMADA,
    )

    indexados = tuple(indice.iterar_identificadores())
    digests = {item.namespace: item.hmac_sha256 for item in indexados}
    assert set(digests) == {_NAMESPACE_CHAMADA, _NAMESPACE_SESSAO}
    assert all(len(digest) == 64 for digest in digests.values())
    assert digests[_NAMESPACE_CHAMADA] != digests[_NAMESPACE_SESSAO]
    assert all(not hasattr(item, "valor_normalizado") for item in indexados)


def test_fallback_so_ocorre_sem_igualdade_e_match_duplo_nao_duplica(
    indice: IndiceTemporario,
) -> None:
    consulta = "chamada-sintetica-42"
    identificador_igual = _identificador(
        consulta,
        entrada_id="entrada-estruturada",
        linha=1,
    )
    identificador_diferente = _identificador(
        "outro-identificador",
        entrada_id="entrada-fallback",
        linha=2,
    )
    entradas = (
        _entrada(
            "entrada-estruturada",
            "texto tambem contem CHAMADA-SINTETICA-42",
            ordem=0,
            linha=1,
            identificadores=(identificador_igual,),
        ),
        _entrada(
            "entrada-fallback",
            "prefixo ChAmAdA-SiNtEtIcA-42 sufixo",
            ordem=1,
            linha=2,
            identificadores=(identificador_diferente,),
        ),
    )
    _indexar_entradas(indice, entradas)

    resultado = BuscadorDeCenario(indice).buscar(
        entradas,
        consulta,
        namespaces=(_NAMESPACE_CHAMADA,),
    )

    assert resultado.entrada_ids == (
        "entrada-estruturada",
        "entrada-fallback",
    )
    assert resultado.entrada_ids.count("entrada-estruturada") == 1
    assert resultado.inclusao_de("entrada-estruturada").motivos == (
        MotivoInclusaoBusca.IGUALDADE_ESTRUTURADA,
    )
    assert resultado.inclusao_de("entrada-fallback").motivos == (
        MotivoInclusaoBusca.FALLBACK_LITERAL,
    )


def test_fallback_encontra_continuacao_com_casing_e_substring_parcial(
    indice: IndiceTemporario,
) -> None:
    entrada = _entrada(
        "entrada-multiline",
        "cabecalho sintetico\ncontinuacao com PREFIXO-call-PARTE-sufixo\n",
        ordem=0,
        linha=1,
        linha_final=2,
    )
    _indexar_entradas(indice, (entrada,))

    resultado = BuscadorDeCenario(indice).buscar(
        (entrada,),
        "CALL-parte",
    )

    assert resultado.entrada_ids == ("entrada-multiline",)
    assert resultado.inclusoes[0].motivos == (
        MotivoInclusaoBusca.FALLBACK_LITERAL,
    )


def test_expansao_autorizada_inclui_destino_com_caminho_e_evidencia(
    indice: IndiceTemporario,
) -> None:
    valor_semente = "chamada-raiz-sintetica"
    valor_destino = "sessao-destino-sintetica"
    identificador_semente = _identificador(
        valor_semente,
        entrada_id="entrada-semente",
        linha=1,
    )
    identificador_destino = _identificador(
        valor_destino,
        entrada_id="entrada-destino",
        linha=3,
        namespace=_NAMESPACE_SESSAO,
        tipo=TipoIdentificador.UUID_SESSAO,
        nome_campo="SessaoSintetica",
    )
    declaracao = _declaracao(
        valor_semente,
        valor_destino,
        entrada_id="entrada-evidencia",
        linha=2,
    )
    entradas = (
        _entrada(
            "entrada-semente",
            "evento semente estruturado",
            ordem=0,
            linha=1,
            identificadores=(identificador_semente,),
        ),
        _entrada(
            "entrada-evidencia",
            "declaracao sintetica entre dois papeis",
            ordem=1,
            linha=2,
            identificadores=(declaracao.origem, declaracao.destino),
        ),
        _entrada(
            "entrada-destino",
            "evento alcançavel somente pelo vinculo",
            ordem=2,
            linha=3,
            identificadores=(identificador_destino,),
        ),
    )
    _indexar_entradas(indice, entradas)

    grafo = GrafoDeVinculos()
    grafo.registrar_esquema(_esquema(permite_expansao=True))
    grafo.adicionar_identificador(identificador_semente)
    grafo.adicionar_identificador(identificador_destino)
    vinculos = grafo.adicionar_declaracao(declaracao)

    resultado = BuscadorDeCenario(indice, grafo).buscar(
        entradas,
        valor_semente.upper(),
        namespaces=(_NAMESPACE_CHAMADA,),
    )

    assert set(resultado.entrada_ids) == {
        "entrada-semente",
        "entrada-evidencia",
        "entrada-destino",
    }
    inclusao_destino = resultado.inclusao_de("entrada-destino")
    assert inclusao_destino is not None
    assert inclusao_destino.motivos == (
        MotivoInclusaoBusca.EXPANSAO_POR_VINCULO,
    )
    assert len(inclusao_destino.caminhos_evidenciados) == 1
    caminho = inclusao_destino.caminhos_evidenciados[0]
    assert caminho.destino.valor_normalizado == valor_destino
    assert tuple(
        passo.evidencia.entrada_id for passo in caminho.passos
    ) == ("entrada-evidencia",)

    inclusao_evidencia = resultado.inclusao_de("entrada-evidencia")
    assert inclusao_evidencia is not None
    assert MotivoInclusaoBusca.EVIDENCIA_DE_VINCULO in (
        inclusao_evidencia.motivos
    )
    assert resultado.vinculos_percorridos == vinculos


def test_vinculo_nao_autorizado_nao_expande_nem_inclui_evidencia(
    indice: IndiceTemporario,
) -> None:
    valor_semente = "chamada-sem-autorizacao"
    valor_destino = "sessao-bloqueada"
    identificador_semente = _identificador(
        valor_semente,
        entrada_id="entrada-semente",
        linha=1,
    )
    identificador_destino = _identificador(
        valor_destino,
        entrada_id="entrada-destino",
        linha=3,
        namespace=_NAMESPACE_SESSAO,
        tipo=TipoIdentificador.UUID_SESSAO,
        nome_campo="SessaoSintetica",
    )
    declaracao = _declaracao(
        valor_semente,
        valor_destino,
        entrada_id="entrada-evidencia",
        linha=2,
    )
    entradas = (
        _entrada(
            "entrada-semente",
            "evento semente",
            ordem=0,
            linha=1,
            identificadores=(identificador_semente,),
        ),
        _entrada(
            "entrada-evidencia",
            "declaracao sem permissao de expansao",
            ordem=1,
            linha=2,
            identificadores=(declaracao.origem, declaracao.destino),
        ),
        _entrada(
            "entrada-destino",
            "evento que nao deve ser alcançado",
            ordem=2,
            linha=3,
            identificadores=(identificador_destino,),
        ),
    )
    _indexar_entradas(indice, entradas)

    grafo = GrafoDeVinculos()
    grafo.registrar_esquema(_esquema(permite_expansao=False))
    grafo.adicionar_identificador(identificador_semente)
    grafo.adicionar_identificador(identificador_destino)
    grafo.adicionar_declaracao(declaracao)

    resultado = BuscadorDeCenario(indice, grafo).buscar(
        entradas,
        valor_semente,
        namespaces=(_NAMESPACE_CHAMADA,),
    )

    assert set(resultado.entrada_ids) == {
        "entrada-semente",
        "entrada-evidencia",
    }
    assert "entrada-destino" not in resultado.entrada_ids
    assert resultado.caminhos_evidenciados == ()
    assert all(
        MotivoInclusaoBusca.EXPANSAO_POR_VINCULO not in inclusao.motivos
        and MotivoInclusaoBusca.EVIDENCIA_DE_VINCULO not in inclusao.motivos
        for inclusao in resultado.inclusoes
    )


def test_componente_ambiguo_nao_expande_nem_inclui_evidencias(
    indice: IndiceTemporario,
) -> None:
    valor_semente = "chamada-ambigua"
    identificador_semente = _identificador(
        valor_semente,
        entrada_id="entrada-semente",
        linha=1,
    )
    declaracoes = (
        _declaracao(
            valor_semente,
            "sessao-ambigua-a",
            entrada_id="entrada-evidencia-a",
            linha=2,
        ),
        _declaracao(
            valor_semente,
            "sessao-ambigua-b",
            entrada_id="entrada-evidencia-b",
            linha=3,
        ),
    )
    identificadores_destino = tuple(
        _identificador(
            f"sessao-ambigua-{sufixo}",
            entrada_id=f"entrada-destino-{sufixo}",
            linha=linha,
            namespace=_NAMESPACE_SESSAO,
            tipo=TipoIdentificador.UUID_SESSAO,
            nome_campo="SessaoSintetica",
        )
        for sufixo, linha in (("a", 4), ("b", 5))
    )
    entradas = (
        _entrada(
            "entrada-semente",
            "evento semente ambiguo",
            ordem=0,
            linha=1,
            identificadores=(identificador_semente,),
        ),
        *(
            _entrada(
                declaracao.evidencia.entrada_id,
                "declaracao que viola cardinalidade",
                ordem=indice_declaracao,
                linha=declaracao.evidencia.linha_inicial,
                identificadores=(declaracao.origem, declaracao.destino),
            )
            for indice_declaracao, declaracao in enumerate(
                declaracoes,
                start=1,
            )
        ),
        *(
            _entrada(
                identificador.proveniencia.entrada_id,
                "evento destino de componente ambiguo",
                ordem=ordem,
                linha=identificador.proveniencia.linha_inicial,
                identificadores=(identificador,),
            )
            for ordem, identificador in enumerate(
                identificadores_destino,
                start=3,
            )
        ),
    )
    _indexar_entradas(indice, entradas)

    grafo = GrafoDeVinculos()
    grafo.registrar_esquema(
        _esquema(
            permite_expansao=True,
            cardinalidade=Cardinalidade.UM_PARA_UM,
        )
    )
    grafo.adicionar_identificador(identificador_semente)
    grafo.adicionar_identificadores(identificadores_destino)
    grafo.adicionar_declaracoes(declaracoes)
    assert grafo.arestas and all(vinculo.ambiguo for vinculo in grafo.arestas)

    resultado = BuscadorDeCenario(indice, grafo).buscar(
        entradas,
        valor_semente,
        namespaces=(_NAMESPACE_CHAMADA,),
    )

    assert {
        "entrada-destino-a",
        "entrada-destino-b",
    }.isdisjoint(resultado.entrada_ids)
    assert resultado.caminhos_evidenciados == ()
    assert all(
        MotivoInclusaoBusca.EXPANSAO_POR_VINCULO not in inclusao.motivos
        and MotivoInclusaoBusca.EVIDENCIA_DE_VINCULO not in inclusao.motivos
        for inclusao in resultado.inclusoes
    )


def test_resultado_deduplica_entrada_id_repetido_na_fonte_e_no_indice(
    indice: IndiceTemporario,
) -> None:
    consulta = "identificador-repetido"
    identificador = _identificador(
        consulta,
        entrada_id="entrada-repetida",
        linha=1,
    )
    entrada = _entrada(
        "entrada-repetida",
        "evento estruturado repetido",
        ordem=0,
        linha=1,
        identificadores=(identificador,),
    )
    _indexar_entradas(indice, (entrada,))
    indice.indexar_identificador(
        entrada_id="entrada-repetida",
        namespace=_NAMESPACE_CHAMADA,
        valor_normalizado=consulta,
    )

    resultado = BuscadorDeCenario(indice).buscar(
        (entrada, entrada),
        consulta,
        namespaces=(_NAMESPACE_CHAMADA,),
    )

    assert resultado.entrada_ids == ("entrada-repetida",)
    assert resultado.entradas_selecionadas == (entrada,)
    assert len(resultado.inclusoes) == 1


@dataclass
class _IndiceObservavel:
    delegado: IndiceTemporario
    acessos_de_busca: int = 0

    def zerar_acessos(self) -> None:
        self.acessos_de_busca = 0

    def iterar_identificadores(self):
        self.acessos_de_busca += 1
        return self.delegado.iterar_identificadores()

    def buscar_identificador(self, namespace: str, valor_normalizado: str):
        self.acessos_de_busca += 1
        return self.delegado.buscar_identificador(namespace, valor_normalizado)

    def calcular_hmac(self, namespace: str, valor_normalizado: str) -> str:
        self.acessos_de_busca += 1
        return self.delegado.calcular_hmac(namespace, valor_normalizado)


class _EntradasSentinela:
    def __init__(self) -> None:
        self.foi_iterada = False

    def __iter__(self):
        self.foi_iterada = True
        raise AssertionError("consulta invalida nao pode enumerar entradas")


@pytest.mark.parametrize(
    "consulta_invalida",
    ("", " \t\r\n", "x" * 257),
    ids=("vazia", "whitespace", "maior-que-256"),
)
def test_consulta_invalida_preserva_resultado_selecao_e_indice_atomicamente(
    indice: IndiceTemporario,
    consulta_invalida: str,
) -> None:
    consulta_valida = "consulta-valida-sintetica"
    identificador = _identificador(
        consulta_valida,
        entrada_id="entrada-valida",
        linha=1,
    )
    entrada = _entrada(
        "entrada-valida",
        "evento de estado previamente confirmado",
        ordem=0,
        linha=1,
        identificadores=(identificador,),
    )
    _indexar_entradas(indice, (entrada,))
    indice_observavel = _IndiceObservavel(indice)
    buscador = BuscadorDeCenario(indice_observavel)
    resultado_anterior = buscador.buscar(
        (entrada,),
        consulta_valida,
        namespaces=(_NAMESPACE_CHAMADA,),
    )
    selecao_anterior = buscador.selecao_atual
    estado_indice_anterior = _snapshot_indice(indice)
    indice_observavel.zerar_acessos()
    entradas_sentinela = _EntradasSentinela()

    with pytest.raises(ErroDeIdentificador):
        buscador.buscar(entradas_sentinela, consulta_invalida)

    assert entradas_sentinela.foi_iterada is False
    assert indice_observavel.acessos_de_busca == 0
    assert buscador.resultado_atual is resultado_anterior
    assert buscador.selecao_atual == selecao_anterior
    assert _snapshot_indice(indice) == estado_indice_anterior
