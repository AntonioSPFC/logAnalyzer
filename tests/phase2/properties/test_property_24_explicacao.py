"""Property 24 da explicação completa e rastreável da Fase 2.

Todos os resultados, campos e metadados são sintéticos e construídos em
memória. O teste não lê arquivos, fixtures, fontes locais nem serviços externos.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hypothesis import event, given, settings, strategies as st

from log_analyzer.core.explicabilidade import (
    CodigoMensagemExplicabilidade,
    CompositorDeExplicabilidade,
    MENSAGEM_CAUSA_RAIZ_NAO_DETERMINADA,
    MENSAGEM_SEM_REGRA_CORRESPONDENTE,
)
from log_analyzer.core.modelos import (
    CampoEstruturado,
    Categoria,
    EntradaDeLog,
    EstadoCausaRaiz,
    Proveniencia,
    ReferenciaRegra,
    ResultadoCausaRaiz,
)


# Feature: log-analyzer-phase-2, Property 24: Explicação é completa e vinculada à decisão
@given(
    dados=st.data(),
    classificada=st.booleans(),
    categoria_classificada=st.sampled_from(
        (Categoria.SUCESSO, Categoria.ERRO)
    ),
    entradas_geradas=st.lists(
        st.tuples(
            st.sampled_from(("VPL", "ORK")),
            st.sampled_from(
                ("DEBUG", "INFO", "NOTICE", "WARNING", "ERROR")
            ),
            st.sampled_from(tuple(Categoria)),
            st.integers(min_value=0, max_value=31_536_000),
            st.integers(min_value=0, max_value=3),
        ),
        min_size=1,
        max_size=5,
    ),
    identificador_condicao_base=st.integers(
        min_value=1,
        max_value=999_996,
    ),
    quantidade_condicoes=st.integers(min_value=1, max_value=5),
    linha_base=st.integers(min_value=1, max_value=100_000),
    versao_regra=st.integers(min_value=1, max_value=1_000),
    versao_catalogo=st.integers(min_value=1, max_value=1_000),
    versao_extrator=st.integers(min_value=1, max_value=1_000),
    sal=st.integers(min_value=0, max_value=2**64 - 1),
)
@settings(max_examples=100)
def test_property_24_explicacao_completa_e_vinculada_a_decisao(
    dados,
    classificada: bool,
    categoria_classificada: Categoria,
    entradas_geradas: list[tuple[str, str, Categoria, int, int]],
    identificador_condicao_base: int,
    quantidade_condicoes: int,
    linha_base: int,
    versao_regra: int,
    versao_catalogo: int,
    versao_extrator: int,
    sal: int,
) -> None:
    """A explicação preserva a decisão, sua evidência e suas dimensões.

    **Validates: Requirements 13.1, 13.2, 13.3, 13.5, 13.6, 13.7**
    """

    identificadores_condicao = tuple(
        range(
            identificador_condicao_base,
            identificador_condicao_base + quantidade_condicoes,
        )
    )
    categoria_de_cenario = (
        categoria_classificada
        if classificada
        else Categoria.NAO_CLASSIFICADA
    )
    categoria_contrastante = (
        Categoria.SUCESSO
        if categoria_de_cenario is Categoria.ERRO
        else Categoria.ERRO
    )
    severidade_contrastante = (
        "INFO" if categoria_de_cenario is Categoria.ERRO else "ERROR"
    )
    quantidade_entradas = len(entradas_geradas)
    quantidade_condicoes = len(identificadores_condicao)

    indices_entrada_por_condicao = tuple(
        dados.draw(
            st.lists(
                st.integers(
                    min_value=0,
                    max_value=quantidade_entradas - 1,
                ),
                min_size=quantidade_condicoes,
                max_size=quantidade_condicoes,
            ),
            label="indices_entrada_por_condicao",
        )
    )
    rotulos = tuple(
        (
            f"condicao_sintetica_{identificador}"
            if classificada
            else f"contexto_sintetico_{identificador}"
        )
        for identificador in identificadores_condicao
    )
    representacoes = tuple(
        f"<EVIDENCIA_SINTETICA_{identificador}>"
        for identificador in identificadores_condicao
    )
    regra_extracao = (
        f"property-24-extrator-sintetico-v{versao_extrator}"
    )

    ids_entrada = tuple(
        f"property-24-{sal:016x}-entrada-{indice}"
        for indice in range(quantidade_entradas)
    )
    tokens_arquivo = tuple(
        f"<ARQUIVO_SINTETICO_P24_{sal:016X}_{indice + 1}>"
        for indice in range(quantidade_entradas)
    )
    posicoes = tuple(
        (
            linha_base + (indice * 10),
            linha_base + (indice * 10) + dados_entrada[4],
        )
        for indice, dados_entrada in enumerate(entradas_geradas)
    )

    campos_por_entrada: list[list[CampoEstruturado]] = [
        [] for _ in range(quantidade_entradas)
    ]
    campos_por_condicao: list[CampoEstruturado] = []
    for indice_condicao, identificador in enumerate(
        identificadores_condicao
    ):
        indice_entrada = indices_entrada_por_condicao[indice_condicao]
        posicao_inicial, posicao_final = posicoes[indice_entrada]
        nome_campo = f"campo_sintetico_{identificador}"
        campo = CampoEstruturado(
            nome=nome_campo,
            valor_original=f"<DADO_SINTETICO_{identificador}>",
            proveniencia=Proveniencia(
                arquivo_token=tokens_arquivo[indice_entrada],
                entrada_id=ids_entrada[indice_entrada],
                linha_inicial=posicao_inicial,
                linha_final=posicao_final,
                nome_campo=nome_campo,
                regra_extracao=regra_extracao,
            ),
        )
        campos_por_entrada[indice_entrada].append(campo)
        campos_por_condicao.append(campo)

    instante_base = datetime(2035, 1, 1, tzinfo=timezone.utc)
    entradas: list[EntradaDeLog] = []
    for indice, dados_entrada in enumerate(entradas_geradas):
        (
            aplicacao,
            severidade_gerada,
            categoria_gerada,
            deslocamento_segundos,
            _,
        ) = dados_entrada
        severidade = (
            severidade_contrastante
            if indice == 0
            else severidade_gerada
        )
        categoria_da_entrada = (
            categoria_contrastante if indice == 0 else categoria_gerada
        )
        instante = instante_base + timedelta(
            seconds=deslocamento_segundos
        )
        texto_original = (
            f"EVENTO_SINTETICO_PROPERTY_24_{sal:016X}_{indice}"
        )
        mensagem = (
            f"MENSAGEM_SINTETICA_PROPERTY_24_{sal:016X}_{indice}"
        )
        posicao_inicial, posicao_final = posicoes[indice]
        entradas.append(
            EntradaDeLog(
                texto_original=texto_original,
                aplicacao=aplicacao,
                ordem_de_leitura=indice,
                interpretada=True,
                carimbo_de_tempo=instante,
                nivel_de_severidade=severidade,
                mensagem=mensagem,
                categoria=categoria_da_entrada,
                entrada_id=ids_entrada[indice],
                arquivo_token=tokens_arquivo[indice],
                posicao_inicial=posicao_inicial,
                posicao_final=posicao_final,
                timestamp_original=instante.isoformat(),
                timestamp_normalizado=instante,
                campos_estruturados=tuple(campos_por_entrada[indice]),
            )
        )

    compositor = CompositorDeExplicabilidade()
    evidencias_base = tuple(
        compositor.construir_evidencia_de_campo(
            entradas[indices_entrada_por_condicao[indice]],
            campos_por_condicao[indice],
            rotulos[indice],
            representacoes[indice],
        )
        for indice in range(quantidade_condicoes)
    )
    ordem_evidencias = tuple(
        dados.draw(
            st.permutations(tuple(range(quantidade_condicoes))),
            label="ordem_evidencias",
        )
    )
    evidencias = tuple(
        evidencias_base[indice] for indice in ordem_evidencias
    )

    regra_aplicada = (
        ReferenciaRegra(
            rule_id=f"regra-sintetica-property-24-{sal:016x}",
            versao=versao_regra,
            catalogo_versao=(
                f"catalogo-sintetico-property-24-v{versao_catalogo}"
            ),
        )
        if classificada
        else None
    )
    causa_raiz_sem_regra = ResultadoCausaRaiz()
    condicoes_satisfeitas = rotulos if classificada else ()

    explicacao = compositor.compor(
        entradas,
        categoria_de_cenario,
        regra_aplicada=regra_aplicada,
        condicoes_satisfeitas=condicoes_satisfeitas,
        evidencias=evidencias,
        causa_raiz=causa_raiz_sem_regra,
    )

    assert explicacao.categoria_de_cenario is categoria_de_cenario
    assert (
        explicacao.dimensoes.categoria_de_cenario
        is categoria_de_cenario
    )
    assert explicacao.causa_raiz is causa_raiz_sem_regra
    assert explicacao.dimensoes.causa_raiz is causa_raiz_sem_regra

    if classificada:
        assert explicacao.regra_aplicada is regra_aplicada
        assert explicacao.regra_aplicada is not None
        assert explicacao.regra_aplicada.rule_id == (
            f"regra-sintetica-property-24-{sal:016x}"
        )
        assert explicacao.regra_aplicada.versao == versao_regra
        assert explicacao.regra_aplicada.catalogo_versao == (
            f"catalogo-sintetico-property-24-v{versao_catalogo}"
        )
        assert explicacao.condicoes_satisfeitas == rotulos
        assert len(explicacao.condicoes_satisfeitas) == len(
            set(explicacao.condicoes_satisfeitas)
        )
        assert {
            evidencia.campo_ou_condicao
            for evidencia in explicacao.evidencias
        } == set(explicacao.condicoes_satisfeitas)
        assert len(explicacao.evidencias) == len(
            explicacao.condicoes_satisfeitas
        )
    else:
        assert explicacao.regra_aplicada is None
        assert explicacao.condicoes_satisfeitas == ()
        assert all(
            evidencia.campo_ou_condicao not in explicacao.condicoes_satisfeitas
            for evidencia in explicacao.evidencias
        )

    assert explicacao.evidencias == evidencias
    esperado_por_rotulo = {
        rotulos[indice]: (
            entradas[indices_entrada_por_condicao[indice]],
            campos_por_condicao[indice],
            representacoes[indice],
        )
        for indice in range(quantidade_condicoes)
    }
    for evidencia in explicacao.evidencias:
        entrada, campo, representacao = esperado_por_rotulo[
            evidencia.campo_ou_condicao
        ]
        assert evidencia.tipo == "campo_estruturado"
        assert evidencia.aplicacao == entrada.aplicacao
        assert evidencia.proveniencia.arquivo_token == entrada.arquivo_token
        assert evidencia.proveniencia.entrada_id == entrada.entrada_id
        assert (
            evidencia.proveniencia.linha_inicial
            == entrada.posicao_inicial
        )
        assert evidencia.proveniencia.linha_final == entrada.posicao_final
        assert evidencia.proveniencia.nome_campo == campo.nome
        assert evidencia.proveniencia.regra_extracao == regra_extracao
        assert evidencia.timestamp_original == entrada.timestamp_original
        assert (
            evidencia.timestamp_normalizado
            == entrada.timestamp_normalizado
        )
        assert evidencia.representacao_sanitizada == representacao
        assert entrada.texto_original not in representacao
        assert entrada.mensagem is not None
        assert entrada.mensagem not in representacao

    assert len(explicacao.dimensoes.entradas) == len(entradas)
    for entrada, aspecto in zip(
        entradas,
        explicacao.dimensoes.entradas,
        strict=True,
    ):
        assert aspecto.aplicacao == entrada.aplicacao
        assert aspecto.entrada_id == entrada.entrada_id
        assert aspecto.posicao_inicial == entrada.posicao_inicial
        assert aspecto.posicao_final == entrada.posicao_final
        assert aspecto.severidade_de_log == entrada.nivel_de_severidade
        assert aspecto.categoria_da_entrada is entrada.categoria

    primeiro_aspecto = explicacao.dimensoes.entradas[0]
    assert primeiro_aspecto.severidade_de_log == severidade_contrastante
    assert primeiro_aspecto.categoria_da_entrada is categoria_contrastante
    assert primeiro_aspecto.categoria_da_entrada is not categoria_de_cenario
    assert isinstance(primeiro_aspecto.severidade_de_log, str)
    assert isinstance(primeiro_aspecto.categoria_da_entrada, Categoria)
    assert isinstance(explicacao.categoria_de_cenario, Categoria)

    assert explicacao.causa_raiz.estado is EstadoCausaRaiz.NAO_DETERMINADA
    assert explicacao.causa_raiz.descricao_sanitizada == "não determinada"
    assert explicacao.causa_raiz.regra is None
    codigos_esperados = (
        (
            CodigoMensagemExplicabilidade.CAUSA_RAIZ_NAO_DETERMINADA,
        )
        if classificada
        else (
            CodigoMensagemExplicabilidade.NENHUMA_REGRA_VALIDADA_CORRESPONDEU,
            CodigoMensagemExplicabilidade.CAUSA_RAIZ_NAO_DETERMINADA,
        )
    )
    assert tuple(
        mensagem.codigo for mensagem in explicacao.mensagens
    ) == codigos_esperados
    assert all(
        mensagem.hipotese_causal is None
        and mensagem.estado_causa_raiz
        is EstadoCausaRaiz.NAO_DETERMINADA
        for mensagem in explicacao.mensagens
    )

    mensagens_por_codigo = {
        mensagem.codigo: mensagem for mensagem in explicacao.mensagens
    }
    mensagem_causal = mensagens_por_codigo[
        CodigoMensagemExplicabilidade.CAUSA_RAIZ_NAO_DETERMINADA
    ]
    assert (
        mensagem_causal.descricao_segura
        == MENSAGEM_CAUSA_RAIZ_NAO_DETERMINADA
    )
    assert mensagem_causal.categoria_de_cenario is categoria_de_cenario
    if classificada:
        assert (
            CodigoMensagemExplicabilidade.NENHUMA_REGRA_VALIDADA_CORRESPONDEU
            not in mensagens_por_codigo
        )
    else:
        mensagem_sem_regra = mensagens_por_codigo[
            CodigoMensagemExplicabilidade.NENHUMA_REGRA_VALIDADA_CORRESPONDEU
        ]
        assert (
            mensagem_sem_regra.descricao_segura
            == MENSAGEM_SEM_REGRA_CORRESPONDENTE
        )
        assert (
            mensagem_sem_regra.categoria_de_cenario
            is Categoria.NAO_CLASSIFICADA
        )

    texto_das_mensagens = " ".join(
        mensagem.descricao_segura for mensagem in explicacao.mensagens
    ).casefold()
    assert all(
        entrada.texto_original.casefold() not in texto_das_mensagens
        and entrada.mensagem is not None
        and entrada.mensagem.casefold() not in texto_das_mensagens
        for entrada in entradas
    )
    assert all(
        campo.valor_original.casefold() not in texto_das_mensagens
        for campo in campos_por_condicao
    )

    event(
        "resultado=" + ("classificado" if classificada else "nao_classificado")
    )
    event(f"categoria_de_cenario={categoria_de_cenario.name}")
    event(f"quantidade_entradas={quantidade_entradas}")
    event(f"quantidade_condicoes_ou_contextos={quantidade_condicoes}")
    event("causa_raiz=sem_regra_causal")
