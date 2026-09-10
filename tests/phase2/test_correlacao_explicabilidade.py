"""Testes unitários da correlação evidenciada e da explicabilidade.

Todos os valores, textos, identificadores, vínculos e instantes deste módulo são
sintéticos. Correlação nova exige igualdade estruturada em namespace compatível
ou cadeia explícita não ambígua; tempo, ordem, coexistência, proximidade, texto
livre e similaridade nunca são aceitos como evidência.

Validates: Requirements 9.1, 9.2, 9.4, 9.5, 9.6, 9.7, 13.3, 13.4.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from log_analyzer.core.correlacao import (
    MOTIVO_AMBIGUIDADE,
    MOTIVO_ORK_AUSENTE,
    MOTIVO_SEM_EVIDENCIA,
    MOTIVO_VPL_AUSENTE,
    CorrelacionadorVplOrk,
    LacunaCorrelacao,
    correlacionar_vpl_ork,
)
from log_analyzer.core.explicabilidade import (
    CodigoMensagemExplicabilidade,
    CompositorDeExplicabilidade,
    compor_diagnostico_sem_regra,
    referencia_regra_de_vinculo,
)
from log_analyzer.core.modelos import (
    BaseCorrelacao,
    Categoria,
    EntradaDeLog,
    EstadoCausaRaiz,
    Evidencia,
    IdentificadorTecnico,
    Proveniencia,
    ReferenciaRegra,
    ResultadoCausaRaiz,
    TipoIdentificador,
)
from log_analyzer.core.vinculos import (
    Cardinalidade,
    DeclaracaoSemanticaDeVinculo,
    EsquemaDeVinculo,
    GrafoDeVinculos,
    RegistroDeEsquemasDeVinculo,
)

_INSTANTE = datetime(2042, 6, 7, 12, 30, 45, 123000, tzinfo=timezone.utc)
_CODIGO_VINCULO = "declaracao-sintetica-explicita"
_FATO_VINCULO = "papeis-sinteticos-explicitamente-relacionados"
_ESQUEMA_ID = "esquema-correlacao-sintetica"


def _arquivo_token(aplicacao: str) -> str:
    return f"<ARQUIVO_SINTETICO_{aplicacao}>"


def _proveniencia(
    aplicacao: str,
    entrada_id: str,
    linha: int,
    *,
    nome_campo: str,
    regra: str = "extrator-sintetico-v1",
) -> Proveniencia:
    return Proveniencia(
        arquivo_token=_arquivo_token(aplicacao),
        entrada_id=entrada_id,
        linha_inicial=linha,
        linha_final=linha,
        span_inicial=2,
        span_final=24,
        nome_campo=nome_campo,
        regra_extracao=regra,
    )


def _identificador(
    aplicacao: str,
    entrada_id: str,
    linha: int,
    *,
    tipo: TipoIdentificador,
    namespace: str,
    nome_campo: str,
    valor_original: str,
    valor_normalizado: str | None = None,
) -> IdentificadorTecnico:
    return IdentificadorTecnico(
        tipo=tipo,
        namespace_comparacao=namespace,
        nome_campo=nome_campo,
        valor_original=valor_original,
        valor_normalizado=valor_normalizado or valor_original.casefold(),
        proveniencia=_proveniencia(
            aplicacao,
            entrada_id,
            linha,
            nome_campo=nome_campo,
        ),
    )


def _entrada(
    aplicacao: str,
    entrada_id: str,
    linha: int,
    ordem: int,
    *,
    identificadores: tuple[IdentificadorTecnico, ...] = (),
    instante: datetime = _INSTANTE,
    texto: str | None = None,
    severidade: str = "INFO",
    categoria: Categoria = Categoria.NAO_CLASSIFICADA,
) -> EntradaDeLog:
    conteudo = texto or f"evento inteiramente sintético {entrada_id}"
    return EntradaDeLog(
        texto_original=conteudo,
        aplicacao=aplicacao,
        ordem_de_leitura=ordem,
        interpretada=True,
        carimbo_de_tempo=instante,
        nivel_de_severidade=severidade,
        mensagem=conteudo,
        categoria=categoria,
        entrada_id=entrada_id,
        arquivo_token=_arquivo_token(aplicacao),
        posicao_inicial=linha,
        posicao_final=linha,
        timestamp_original=instante.isoformat(),
        timestamp_normalizado=instante,
        identificadores=identificadores,
    )


def _declaracao(
    entrada_evidencia: EntradaDeLog,
    *,
    tipo_origem: TipoIdentificador,
    namespace_origem: str,
    valor_origem: str,
    tipo_destino: TipoIdentificador,
    namespace_destino: str,
    valor_destino: str,
) -> DeclaracaoSemanticaDeVinculo:
    assert entrada_evidencia.entrada_id is not None
    assert entrada_evidencia.posicao_inicial is not None
    aplicacao = entrada_evidencia.aplicacao
    entrada_id = entrada_evidencia.entrada_id
    linha = entrada_evidencia.posicao_inicial
    evidencia = _proveniencia(
        aplicacao,
        entrada_id,
        linha,
        nome_campo="RelacaoExplicita",
        regra="detector-de-vinculo-sintetico-v1",
    )
    origem = _identificador(
        aplicacao,
        entrada_id,
        linha,
        tipo=tipo_origem,
        namespace=namespace_origem,
        nome_campo="PapelOrigem",
        valor_original=valor_origem,
    )
    destino = _identificador(
        aplicacao,
        entrada_id,
        linha,
        tipo=tipo_destino,
        namespace=namespace_destino,
        nome_campo="PapelDestino",
        valor_original=valor_destino,
    )
    return DeclaracaoSemanticaDeVinculo(
        origem=origem,
        destino=destino,
        evidencia=evidencia,
        codigo_semantico=_CODIGO_VINCULO,
        fatos=frozenset({_FATO_VINCULO}),
    )


def _grafo_explicito(
    *declaracoes: DeclaracaoSemanticaDeVinculo,
    cardinalidade: Cardinalidade = Cardinalidade.MUITOS_PARA_MUITOS,
) -> GrafoDeVinculos:
    esquema = EsquemaDeVinculo(
        esquema_id=_ESQUEMA_ID,
        versao=1,
        tipo_relacao="mapeamento_sintetico_explicito",
        tipos_origem=frozenset(TipoIdentificador),
        tipos_destino=frozenset(TipoIdentificador),
        cardinalidade=cardinalidade,
        permite_expansao_de_cenario=True,
        aprovado=True,
        reconhecedor=lambda declaracao: (
            declaracao.codigo_semantico == _CODIGO_VINCULO
            and _FATO_VINCULO in declaracao.fatos
        ),
    )
    registro = RegistroDeEsquemasDeVinculo()
    registro.registrar(esquema)
    grafo = GrafoDeVinculos(registro)
    grafo.adicionar_declaracoes(declaracoes)
    return grafo


def _assert_evidencia_completa(
    evidencia: Evidencia,
    entrada: EntradaDeLog,
) -> None:
    """Confere todos os campos obrigatórios dos Requirements 13.3/13.4."""

    assert evidencia.tipo.strip()
    assert evidencia.aplicacao == entrada.aplicacao
    assert evidencia.proveniencia.arquivo_token == entrada.arquivo_token
    assert evidencia.proveniencia.entrada_id == entrada.entrada_id
    assert entrada.posicao_inicial is not None
    assert entrada.posicao_final is not None
    assert (
        entrada.posicao_inicial
        <= evidencia.proveniencia.linha_inicial
        <= evidencia.proveniencia.linha_final
        <= entrada.posicao_final
    )
    assert evidencia.proveniencia.span_inicial is not None
    assert evidencia.proveniencia.span_final is not None
    assert evidencia.proveniencia.nome_campo is not None
    assert evidencia.proveniencia.regra_extracao is not None
    assert evidencia.proveniencia.regra_extracao.strip()
    assert evidencia.timestamp_original == entrada.timestamp_original
    assert evidencia.timestamp_normalizado == entrada.timestamp_normalizado
    assert evidencia.campo_ou_condicao.strip()
    assert evidencia.representacao_sanitizada.strip()
    assert evidencia.representacao_sanitizada != entrada.texto_original


def _entrada_legada(aplicacao: str, ordem: int) -> EntradaDeLog:
    return EntradaDeLog(
        texto_original=f"evento legado sintético {aplicacao}-{ordem}",
        aplicacao=aplicacao,
        ordem_de_leitura=ordem,
        interpretada=False,
    )


def test_valor_compartilhado_marca_somente_entradas_cobertas_e_evidencia() -> None:
    namespace = "chamada_externa_sintetica"
    valor_normalizado = "<call_id_sintetico_compartilhado>"
    id_vpl = _identificador(
        "VPL",
        "vpl-compartilhada",
        10,
        tipo=TipoIdentificador.CHAMADA_EXTERNA,
        namespace=namespace,
        nome_campo="CallIdCanal",
        valor_original="<CALL_ID_SINTETICO_COMPARTILHADO>",
        valor_normalizado=valor_normalizado,
    )
    id_ork = _identificador(
        "ORK",
        "ork-compartilhada",
        30,
        tipo=TipoIdentificador.TELECOM_CALL_ID,
        namespace=namespace,
        nome_campo="TelecomCallId",
        valor_original="<call_id_sintetico_compartilhado>",
        valor_normalizado=valor_normalizado,
    )
    vpl_coberta = _entrada(
        "VPL", "vpl-compartilhada", 10, 0, identificadores=(id_vpl,)
    )
    ork_coberta = _entrada(
        "ORK", "ork-compartilhada", 30, 0, identificadores=(id_ork,)
    )
    vpl_isolada = _entrada("VPL", "vpl-isolada", 20, 1)
    ork_isolada = _entrada("ORK", "ork-isolada", 40, 1)

    resultado = CorrelacionadorVplOrk().correlacionar(
        [vpl_coberta, vpl_isolada],
        [ork_coberta, ork_isolada],
    )

    assert resultado.encontrada is True
    assert resultado.base_primaria is BaseCorrelacao.VALOR_COMPARTILHADO
    assert resultado.bases == (BaseCorrelacao.VALOR_COMPARTILHADO,)
    assert [entrada.correlacionada for entrada in resultado.entradas_vpl] == [
        True,
        False,
    ]
    assert [entrada.correlacionada for entrada in resultado.entradas_ork] == [
        True,
        False,
    ]
    assert resultado.entrada_ids_cobertas == (
        "vpl-compartilhada",
        "ork-compartilhada",
    )
    assert resultado.caminhos_evidenciados == ()
    assert resultado.vinculos_percorridos == ()
    assert resultado.lacunas == ()

    entradas_por_id = {
        entrada.entrada_id: entrada for entrada in (vpl_coberta, ork_coberta)
    }
    assert len(resultado.evidencias) == 2
    for evidencia in resultado.evidencias:
        assert evidencia.tipo == "identificador_compartilhado"
        assert evidencia.proveniencia.entrada_id in entradas_por_id
        entrada = entradas_por_id[evidencia.proveniencia.entrada_id]
        _assert_evidencia_completa(evidencia, entrada)
        assert evidencia.campo_ou_condicao == (
            f"valor_compartilhado:{namespace}"
        )
    assert {evidencia.representacao_sanitizada for evidencia in resultado.evidencias} == {
        id_vpl.valor_original,
        id_ork.valor_original,
    }


def test_cadeia_explicita_multietapa_registra_caminho_e_cada_vinculo() -> None:
    valor_raiz = "<CALL_ID_SINTETICO_CADEIA>"
    valor_intermediario = "<UUID_CANAL_SINTETICO_CADEIA>"
    valor_destino = "<UUID_SESSAO_SINTETICO_CADEIA>"
    id_vpl = _identificador(
        "VPL",
        "vpl-cadeia",
        50,
        tipo=TipoIdentificador.CALL_ID,
        namespace="chamada_sintetica",
        nome_campo="CallId",
        valor_original=valor_raiz,
    )
    id_ork = _identificador(
        "ORK",
        "ork-cadeia",
        70,
        tipo=TipoIdentificador.UUID_SESSAO,
        namespace="sessao_sintetica",
        nome_campo="SessionId",
        valor_original=valor_destino,
    )
    entrada_vpl = _entrada(
        "VPL", "vpl-cadeia", 50, 0, identificadores=(id_vpl,)
    )
    entrada_ork = _entrada(
        "ORK", "ork-cadeia", 70, 0, identificadores=(id_ork,)
    )
    primeiro_passo = _declaracao(
        entrada_vpl,
        tipo_origem=TipoIdentificador.CALL_ID,
        namespace_origem="chamada_sintetica",
        valor_origem=valor_raiz,
        tipo_destino=TipoIdentificador.UUID_CANAL,
        namespace_destino="canal_sintetico",
        valor_destino=valor_intermediario,
    )
    segundo_passo = _declaracao(
        entrada_ork,
        tipo_origem=TipoIdentificador.UUID_CANAL,
        namespace_origem="canal_sintetico",
        valor_origem=valor_intermediario,
        tipo_destino=TipoIdentificador.UUID_SESSAO,
        namespace_destino="sessao_sintetica",
        valor_destino=valor_destino,
    )
    grafo = _grafo_explicito(primeiro_passo, segundo_passo)

    resultado = CorrelacionadorVplOrk(grafo).correlacionar(
        [entrada_vpl], [entrada_ork]
    )

    assert resultado.encontrada is True
    assert resultado.base_primaria is BaseCorrelacao.CADEIA_DE_VINCULOS
    assert resultado.bases == (BaseCorrelacao.CADEIA_DE_VINCULOS,)
    assert resultado.entrada_ids_cobertas == ("vpl-cadeia", "ork-cadeia")
    assert resultado.entradas_vpl[0].correlacionada is True
    assert resultado.entradas_ork[0].correlacionada is True
    assert len(resultado.caminhos_evidenciados) == 1

    caminho = resultado.caminhos_evidenciados[0]
    assert len(caminho.passos) == 2
    assert [caminho.semente.valor_normalizado] + [
        passo.destino.valor_normalizado for passo in caminho.passos
    ] == [
        valor_raiz.casefold(),
        valor_intermediario.casefold(),
        valor_destino.casefold(),
    ]
    assert caminho.vinculos == resultado.vinculos_percorridos
    assert caminho.evidencias == tuple(
        vinculo.evidencia for vinculo in resultado.vinculos_percorridos
    )
    assert all(not vinculo.ambiguo for vinculo in caminho.vinculos)
    assert all(vinculo.permite_correlacao for vinculo in caminho.vinculos)

    entradas_por_id = {
        entrada_vpl.entrada_id: entrada_vpl,
        entrada_ork.entrada_id: entrada_ork,
    }
    for evidencia in resultado.evidencias:
        entrada = entradas_por_id[evidencia.proveniencia.entrada_id]
        _assert_evidencia_completa(evidencia, entrada)
    assert [evidencia.tipo for evidencia in resultado.evidencias].count(
        "identificador_de_cadeia"
    ) == 2
    evidencias_de_vinculo = tuple(
        evidencia
        for evidencia in resultado.evidencias
        if evidencia.tipo == "vinculo"
    )
    assert len(evidencias_de_vinculo) == 2
    for vinculo in resultado.vinculos_percorridos:
        evidencia = next(
            item
            for item in evidencias_de_vinculo
            if item.proveniencia.entrada_id == vinculo.evidencia.entrada_id
        )
        assert evidencia.proveniencia.regra_extracao == (
            referencia_regra_de_vinculo(vinculo)
        )
        assert evidencia.campo_ou_condicao == vinculo.tipo_relacao


def test_valor_compartilhado_e_cadeia_registram_ambas_as_bases() -> None:
    valor_compartilhado = "<CALL_ID_SINTETICO_DUPLA_BASE>"
    valor_raiz = "<CALL_ID_SINTETICO_RAIZ_DUPLA_BASE>"
    valor_destino = "<UUID_SESSAO_SINTETICO_DUPLA_BASE>"
    namespace_compartilhado = "chamada_compartilhada_sintetica"
    id_compartilhado_vpl = _identificador(
        "VPL",
        "vpl-dupla-base",
        80,
        tipo=TipoIdentificador.CHAMADA_EXTERNA,
        namespace=namespace_compartilhado,
        nome_campo="CallIdCanal",
        valor_original=valor_compartilhado,
    )
    id_raiz = _identificador(
        "VPL",
        "vpl-dupla-base",
        80,
        tipo=TipoIdentificador.CALL_ID,
        namespace="raiz_dupla_base_sintetica",
        nome_campo="CallIdInterno",
        valor_original=valor_raiz,
    )
    id_compartilhado_ork = _identificador(
        "ORK",
        "ork-dupla-base",
        90,
        tipo=TipoIdentificador.TELECOM_CALL_ID,
        namespace=namespace_compartilhado,
        nome_campo="TelecomCallId",
        valor_original=valor_compartilhado.lower(),
        valor_normalizado=valor_compartilhado.casefold(),
    )
    id_destino = _identificador(
        "ORK",
        "ork-dupla-base",
        90,
        tipo=TipoIdentificador.UUID_SESSAO,
        namespace="destino_dupla_base_sintetica",
        nome_campo="SessionId",
        valor_original=valor_destino,
    )
    entrada_vpl = _entrada(
        "VPL",
        "vpl-dupla-base",
        80,
        0,
        identificadores=(id_compartilhado_vpl, id_raiz),
    )
    entrada_ork = _entrada(
        "ORK",
        "ork-dupla-base",
        90,
        0,
        identificadores=(id_compartilhado_ork, id_destino),
    )
    declaracao = _declaracao(
        entrada_vpl,
        tipo_origem=TipoIdentificador.CALL_ID,
        namespace_origem="raiz_dupla_base_sintetica",
        valor_origem=valor_raiz,
        tipo_destino=TipoIdentificador.UUID_SESSAO,
        namespace_destino="destino_dupla_base_sintetica",
        valor_destino=valor_destino,
    )

    resultado = CorrelacionadorVplOrk(
        _grafo_explicito(declaracao)
    ).correlacionar([entrada_vpl], [entrada_ork])

    assert resultado.encontrada is True
    assert resultado.base_primaria is BaseCorrelacao.VALOR_COMPARTILHADO
    assert resultado.bases == (
        BaseCorrelacao.VALOR_COMPARTILHADO,
        BaseCorrelacao.CADEIA_DE_VINCULOS,
    )
    assert len(resultado.caminhos_evidenciados) == 1
    assert len(resultado.vinculos_percorridos) == 1
    assert {evidencia.tipo for evidencia in resultado.evidencias} == {
        "identificador_compartilhado",
        "identificador_de_cadeia",
        "vinculo",
    }
    assert resultado.entradas_vpl[0].correlacionada is True
    assert resultado.entradas_ork[0].correlacionada is True


def test_sem_evidencia_ignora_sinais_heuristicos_e_preserva_os_lados() -> None:
    texto_compartilhado = (
        "literal sintético idêntico e contexto quase igual sem declaração"
    )
    id_vpl_similar = _identificador(
        "VPL",
        "vpl-sem-evidencia",
        100,
        tipo=TipoIdentificador.CALL_ID,
        namespace="chamada_sintetica",
        nome_campo="CallId",
        valor_original="chamada-sintetica-0001",
    )
    id_vpl_coexistente = _identificador(
        "VPL",
        "vpl-sem-evidencia",
        100,
        tipo=TipoIdentificador.UUID_CANAL,
        namespace="ponte_privada_vpl",
        nome_campo="ChannelId",
        valor_original="ponte-sintetica-igual",
    )
    id_ork_similar = _identificador(
        "ORK",
        "ork-sem-evidencia",
        101,
        tipo=TipoIdentificador.TELECOM_CALL_ID,
        namespace="chamada_sintetica",
        nome_campo="TelecomCallId",
        valor_original="chamada-sintetica-000l",
    )
    id_ork_coexistente = _identificador(
        "ORK",
        "ork-sem-evidencia",
        101,
        tipo=TipoIdentificador.UUID_SESSAO,
        namespace="ponte_privada_ork",
        nome_campo="SessionId",
        valor_original="ponte-sintetica-igual",
    )
    entrada_vpl = _entrada(
        "VPL",
        "vpl-sem-evidencia",
        100,
        40,
        identificadores=(id_vpl_similar, id_vpl_coexistente),
        instante=_INSTANTE,
        texto=texto_compartilhado,
    )
    entrada_ork = _entrada(
        "ORK",
        "ork-sem-evidencia",
        101,
        41,
        identificadores=(id_ork_similar, id_ork_coexistente),
        instante=_INSTANTE,
        texto=texto_compartilhado,
    )

    # Precondições: todos os sinais proibidos estão deliberadamente presentes.
    assert entrada_vpl.timestamp_normalizado == entrada_ork.timestamp_normalizado
    assert entrada_ork.ordem_de_leitura == entrada_vpl.ordem_de_leitura + 1
    assert len(entrada_vpl.identificadores) == 2
    assert len(entrada_ork.identificadores) == 2
    assert entrada_vpl.texto_original == entrada_ork.texto_original
    assert id_vpl_similar.valor_normalizado[:-1] == (
        id_ork_similar.valor_normalizado[:-1]
    )
    assert id_vpl_coexistente.valor_normalizado == (
        id_ork_coexistente.valor_normalizado
    )
    assert id_vpl_coexistente.namespace_comparacao != (
        id_ork_coexistente.namespace_comparacao
    )

    resultado = CorrelacionadorVplOrk().correlacionar(
        [entrada_vpl], [entrada_ork]
    )

    assert resultado.encontrada is False
    assert resultado.base_primaria is BaseCorrelacao.NENHUMA
    assert resultado.bases == (BaseCorrelacao.NENHUMA,)
    assert resultado.evidencias == ()
    assert resultado.vinculos_percorridos == ()
    assert resultado.caminhos_evidenciados == ()
    assert resultado.caminhos_bloqueados_por_ambiguidade == ()
    assert resultado.lacunas == (LacunaCorrelacao.SEM_EVIDENCIA,)
    assert resultado.correlacao.motivo_seguro == MOTIVO_SEM_EVIDENCIA
    assert resultado.entrada_ids_cobertas == ()
    assert not resultado.entradas_vpl[0].correlacionada
    assert not resultado.entradas_ork[0].correlacionada
    assert resultado.entradas_vpl[0].texto_original == texto_compartilhado
    assert resultado.entradas_ork[0].texto_original == texto_compartilhado


def test_ambiguidade_bloqueia_caminho_e_nao_marca_entradas() -> None:
    valor_raiz = "<CALL_ID_SINTETICO_AMBIGUO>"
    valor_destino = "<UUID_SESSAO_SINTETICO_AMBIGUO_1>"
    id_vpl = _identificador(
        "VPL",
        "vpl-ambigua",
        110,
        tipo=TipoIdentificador.CALL_ID,
        namespace="chamada_ambigua_sintetica",
        nome_campo="CallId",
        valor_original=valor_raiz,
    )
    id_ork = _identificador(
        "ORK",
        "ork-ambigua",
        120,
        tipo=TipoIdentificador.UUID_SESSAO,
        namespace="sessao_ambigua_sintetica",
        nome_campo="SessionId",
        valor_original=valor_destino,
    )
    entrada_vpl = _entrada(
        "VPL", "vpl-ambigua", 110, 0, identificadores=(id_vpl,)
    )
    entrada_ork = _entrada(
        "ORK", "ork-ambigua", 120, 0, identificadores=(id_ork,)
    )
    declaracao_1 = _declaracao(
        entrada_vpl,
        tipo_origem=TipoIdentificador.CALL_ID,
        namespace_origem="chamada_ambigua_sintetica",
        valor_origem=valor_raiz,
        tipo_destino=TipoIdentificador.UUID_SESSAO,
        namespace_destino="sessao_ambigua_sintetica",
        valor_destino=valor_destino,
    )
    declaracao_2 = _declaracao(
        entrada_vpl,
        tipo_origem=TipoIdentificador.CALL_ID,
        namespace_origem="chamada_ambigua_sintetica",
        valor_origem=valor_raiz,
        tipo_destino=TipoIdentificador.UUID_SESSAO,
        namespace_destino="sessao_ambigua_sintetica",
        valor_destino="<UUID_SESSAO_SINTETICO_AMBIGUO_2>",
    )
    grafo = _grafo_explicito(
        declaracao_1,
        declaracao_2,
        cardinalidade=Cardinalidade.UM_PARA_UM,
    )

    assert grafo.eh_ambiguo(id_vpl)
    assert grafo.eh_ambiguo(id_ork)

    resultado = CorrelacionadorVplOrk(grafo).correlacionar(
        [entrada_vpl], [entrada_ork]
    )

    assert resultado.encontrada is False
    assert resultado.base_primaria is BaseCorrelacao.AMBIGUA
    assert resultado.bases == (BaseCorrelacao.AMBIGUA,)
    assert resultado.correlacao.motivo_seguro == MOTIVO_AMBIGUIDADE
    assert resultado.lacunas == (LacunaCorrelacao.ASSOCIACAO_AMBIGUA,)
    assert resultado.caminhos_evidenciados == ()
    assert len(resultado.caminhos_bloqueados_por_ambiguidade) == 1
    assert all(
        vinculo.ambiguo
        for caminho in resultado.caminhos_bloqueados_por_ambiguidade
        for vinculo in caminho.vinculos
    )
    assert resultado.vinculos_percorridos == ()
    assert resultado.evidencias == ()
    assert resultado.entrada_ids_cobertas == ()
    assert not resultado.entradas_vpl[0].correlacionada
    assert not resultado.entradas_ork[0].correlacionada


@pytest.mark.parametrize(
    ("aplicacao_presente", "lacuna_esperada", "motivo_esperado"),
    (
        ("VPL", LacunaCorrelacao.ORK_AUSENTE, MOTIVO_ORK_AUSENTE),
        ("ORK", LacunaCorrelacao.VPL_AUSENTE, MOTIVO_VPL_AUSENTE),
    ),
)
def test_lado_ausente_preserva_resultado_parcial_e_identifica_lacuna(
    aplicacao_presente: str,
    lacuna_esperada: LacunaCorrelacao,
    motivo_esperado: str,
) -> None:
    entrada = _entrada(
        aplicacao_presente,
        f"{aplicacao_presente.lower()}-parcial",
        130,
        0,
    )
    entradas_vpl = [entrada] if aplicacao_presente == "VPL" else []
    entradas_ork = [entrada] if aplicacao_presente == "ORK" else []

    resultado = CorrelacionadorVplOrk().correlacionar(
        entradas_vpl, entradas_ork
    )

    assert resultado.encontrada is False
    assert resultado.base_primaria is BaseCorrelacao.NENHUMA
    assert resultado.bases == (BaseCorrelacao.NENHUMA,)
    assert resultado.lacunas == (lacuna_esperada,)
    assert resultado.correlacao.motivo_seguro == motivo_esperado
    assert resultado.aplicacoes_ausentes == (
        "ORK" if aplicacao_presente == "VPL" else "VPL",
    )
    assert resultado.evidencias == ()
    assert resultado.entrada_ids_cobertas == ()
    lado_presente = (
        resultado.entradas_vpl
        if aplicacao_presente == "VPL"
        else resultado.entradas_ork
    )
    assert lado_presente == (entrada,)
    assert lado_presente[0].correlacionada is False


def test_explicacao_completa_mantem_dimensoes_semanticas_separadas() -> None:
    identificador = _identificador(
        "ORK",
        "ork-explicacao",
        140,
        tipo=TipoIdentificador.CALL_ID,
        namespace="chamada_explicacao_sintetica",
        nome_campo="CallId",
        valor_original="<CALL_ID_SINTETICO_EXPLICACAO>",
    )
    entrada = _entrada(
        "ORK",
        "ork-explicacao",
        140,
        0,
        identificadores=(identificador,),
        severidade="WARNING",
        categoria=Categoria.SUCESSO,
    )
    declaracao = _declaracao(
        entrada,
        tipo_origem=TipoIdentificador.CALL_ID,
        namespace_origem="chamada_explicacao_sintetica",
        valor_origem="<CALL_ID_SINTETICO_EXPLICACAO>",
        tipo_destino=TipoIdentificador.UUID_SESSAO,
        namespace_destino="sessao_explicacao_sintetica",
        valor_destino="<UUID_SESSAO_SINTETICO_EXPLICACAO>",
    )
    vinculo = _grafo_explicito(declaracao).arestas[0]
    compositor = CompositorDeExplicabilidade()
    condicao = "campo_sintetico_presente"
    evidencia_de_campo = compositor.construir_evidencia_de_campo(
        entrada,
        identificador,
        condicao,
        "CallId=<CALL_ID_SINTETICO_EXPLICACAO>",
    )
    evidencia_de_vinculo = compositor.construir_evidencia_de_vinculo(
        entrada,
        vinculo,
        (
            "CallId=<CALL_ID_SINTETICO_EXPLICACAO> -> "
            "SessionId=<UUID_SESSAO_SINTETICO_EXPLICACAO>"
        ),
    )
    regra_de_cenario = ReferenciaRegra(
        "regra-cenario-sintetica", 3, "catalogo-sintetico-v3"
    )
    regra_causal = ReferenciaRegra(
        "regra-causal-sintetica", 2, "catalogo-sintetico-v3"
    )
    causa_raiz = ResultadoCausaRaiz(
        estado=EstadoCausaRaiz.DETERMINADA,
        descricao_sanitizada="causa sintética determinada por regra",
        regra=regra_causal,
    )

    explicacao = compositor.compor(
        [entrada],
        Categoria.ERRO,
        regra_aplicada=regra_de_cenario,
        condicoes_satisfeitas=(condicao,),
        evidencias=(evidencia_de_campo, evidencia_de_vinculo),
        vinculos_percorridos=(vinculo,),
        causa_raiz=causa_raiz,
    )

    # Todos os campos obrigatórios da explicação são exercitados diretamente.
    assert explicacao.categoria_de_cenario is Categoria.ERRO
    assert explicacao.regra_aplicada == regra_de_cenario
    assert explicacao.condicoes_satisfeitas == (condicao,)
    assert explicacao.evidencias == (
        evidencia_de_campo,
        evidencia_de_vinculo,
    )
    assert explicacao.vinculos_percorridos == (vinculo,)
    assert explicacao.mensagens == ()
    assert explicacao.dimensoes.categoria_de_cenario is Categoria.ERRO
    assert explicacao.dimensoes.causa_raiz == causa_raiz
    assert explicacao.causa_raiz.estado is EstadoCausaRaiz.DETERMINADA
    assert explicacao.causa_raiz.descricao_sanitizada == (
        "causa sintética determinada por regra"
    )
    assert explicacao.causa_raiz.regra == regra_causal
    assert explicacao.causa_raiz.regra != explicacao.regra_aplicada

    aspecto = explicacao.dimensoes.entradas[0]
    assert aspecto.aplicacao == "ORK"
    assert aspecto.entrada_id == "ork-explicacao"
    assert aspecto.posicao_inicial == 140
    assert aspecto.posicao_final == 140
    assert aspecto.severidade_de_log == "WARNING"
    assert aspecto.categoria_da_entrada is Categoria.SUCESSO
    assert aspecto.categoria_da_entrada is not explicacao.categoria_de_cenario
    assert aspecto.severidade_de_log not in {
        aspecto.categoria_da_entrada.name,
        explicacao.categoria_de_cenario.name,
    }

    _assert_evidencia_completa(evidencia_de_campo, entrada)
    _assert_evidencia_completa(evidencia_de_vinculo, entrada)
    assert evidencia_de_vinculo.proveniencia.regra_extracao == (
        referencia_regra_de_vinculo(vinculo)
    )


def test_explicacao_sem_regra_informa_lacunas_sem_inventar_causa() -> None:
    entrada = _entrada(
        "VPL",
        "vpl-sem-regra",
        150,
        0,
        severidade="ERROR",
        categoria=Categoria.ERRO,
    )

    explicacao = compor_diagnostico_sem_regra([entrada])

    assert explicacao.categoria_de_cenario is Categoria.NAO_CLASSIFICADA
    assert explicacao.regra_aplicada is None
    assert explicacao.condicoes_satisfeitas == ()
    assert explicacao.evidencias == ()
    assert explicacao.vinculos_percorridos == ()
    assert explicacao.dimensoes.categoria_de_cenario is (
        Categoria.NAO_CLASSIFICADA
    )
    assert explicacao.dimensoes.entradas[0].severidade_de_log == "ERROR"
    assert explicacao.dimensoes.entradas[0].categoria_da_entrada is Categoria.ERRO
    assert explicacao.causa_raiz == ResultadoCausaRaiz()
    assert [mensagem.codigo for mensagem in explicacao.mensagens] == [
        CodigoMensagemExplicabilidade.NENHUMA_REGRA_VALIDADA_CORRESPONDEU,
        CodigoMensagemExplicabilidade.CAUSA_RAIZ_NAO_DETERMINADA,
    ]
    assert all(
        mensagem.descricao_segura.strip()
        and mensagem.categoria_de_cenario
        is Categoria.NAO_CLASSIFICADA
        and mensagem.estado_causa_raiz is EstadoCausaRaiz.NAO_DETERMINADA
        and mensagem.hipotese_causal is None
        for mensagem in explicacao.mensagens
    )


def test_wrapper_legado_mantem_semantica_de_listas_pre_filtradas() -> None:
    entrada_vpl = _entrada_legada("VPL", 0)
    entrada_ork = _entrada_legada("ORK", 0)
    entradas_vpl = [entrada_vpl]
    entradas_ork = [entrada_ork]
    consulta_ausente = "CONSULTA-SINTETICA-AUSENTE-DOS-TEXTOS"
    assert consulta_ausente not in entrada_vpl.texto_original
    assert consulta_ausente not in entrada_ork.texto_original

    primeiro = correlacionar_vpl_ork(
        entradas_vpl, entradas_ork, consulta_ausente
    )
    segundo = correlacionar_vpl_ork(
        entradas_vpl, entradas_ork, consulta_ausente
    )
    vpl_saida, ork_saida, encontrada, erros = primeiro

    assert primeiro == segundo
    assert encontrada is True
    assert erros == []
    assert all(entrada.correlacionada for entrada in vpl_saida + ork_saida)
    assert vpl_saida[0] is not entrada_vpl
    assert ork_saida[0] is not entrada_ork
    assert replace(vpl_saida[0], correlacionada=False) == entrada_vpl
    assert replace(ork_saida[0], correlacionada=False) == entrada_ork
    assert entradas_vpl == [entrada_vpl]
    assert entradas_ork == [entrada_ork]
    assert entrada_vpl.correlacionada is False
    assert entrada_ork.correlacionada is False


@pytest.mark.parametrize("lado_ausente", ("VPL", "ORK"))
def test_wrapper_legado_preserva_lado_disponivel_e_reporta_ausente(
    lado_ausente: str,
) -> None:
    aplicacao_disponivel = "ORK" if lado_ausente == "VPL" else "VPL"
    disponivel = _entrada_legada(aplicacao_disponivel, 0)
    entradas_vpl = [] if lado_ausente == "VPL" else [disponivel]
    entradas_ork = [disponivel] if lado_ausente == "VPL" else []
    identificador = "ID-SINTETICO-ERRO-LEGADO"

    vpl_saida, ork_saida, encontrada, erros = correlacionar_vpl_ork(
        entradas_vpl, entradas_ork, identificador
    )

    assert encontrada is False
    assert len(erros) == 1
    assert erros[0].arquivo_ou_app == lado_ausente
    assert lado_ausente in erros[0].descricao
    assert identificador in erros[0].descricao
    saida_disponivel = ork_saida if lado_ausente == "VPL" else vpl_saida
    assert saida_disponivel == [disponivel]
    assert saida_disponivel[0] is disponivel
    assert disponivel.correlacionada is False


def test_wrapper_legado_com_ambos_os_lados_vazios_mantem_caso_fase_1() -> None:
    assert correlacionar_vpl_ork([], [], "ID-SINTETICO") == (
        [],
        [],
        False,
        [],
    )
