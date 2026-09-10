"""Property 25 da sanitização estrutural da Fase 2.

Todos os valores sensíveis e resultados são construídos em memória a partir de
estratégias Hypothesis. O teste não lê arquivos, fixtures ou serviços externos.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
import json
import re
from uuid import UUID

from hypothesis import given, settings, strategies as st

from log_analyzer.core.modelos import (
    BaseCorrelacao,
    CampoEstruturado,
    Categoria,
    EntradaDeLog,
    EstadoSanitizacao,
    Evidencia,
    IdentificadorTecnico,
    MensagemDeErro,
    Proveniencia,
    ResultadoCorrelacao,
    ResultadoDeAnalise,
    TipoIdentificador,
    VinculoIdentificadores,
)
from log_analyzer.core.serializacao import serializar_resultado_de_analise
from log_analyzer.core.visao_segura import SanitizadorDeResultado


_PREFIXOS_ESPERADOS = (
    "CALL_ID",
    "UUID",
    "UUID_CANAL",
    "UUID_SESSAO",
    "TELEFONE",
    "DOCUMENTO",
    "IP",
    "HOST_INTERNO",
    "URL_INTERNA",
    "CREDENCIAL",
    "DADO_CLIENTE",
)
_PADRAO_PLACEHOLDER = re.compile(
    r"<(?:CALL_ID|UUID|UUID_CANAL|UUID_SESSAO|TELEFONE|DOCUMENTO|IP|"
    r"HOST_INTERNO|URL_INTERNA|CREDENCIAL|DADO_CLIENTE)_[1-9][0-9]*>"
)


# Feature: log-analyzer-phase-2, Property 25: Sanitização é consistente, tipada e preserva estrutura
@given(
    sal=st.integers(min_value=0, max_value=2**64 - 1),
    uuid_compartilhado=st.uuids(version=4),
    partes_telefone=st.tuples(
        st.integers(min_value=0, max_value=9_999),
        st.integers(min_value=0, max_value=9_999),
    ),
    numero_documento=st.integers(min_value=0, max_value=99_999_999_999),
    octetos_ip=st.tuples(
        st.integers(min_value=1, max_value=254),
        st.integers(min_value=1, max_value=254),
        st.integers(min_value=1, max_value=254),
    ),
    ordem_campos=st.permutations(tuple(range(15))),
    ordem_identificadores=st.permutations((0, 1, 2)),
    ordem_vinculos=st.permutations((0, 1)),
    ordem_timeline=st.permutations((0, 1)),
    repeticoes=st.integers(min_value=2, max_value=5),
)
@settings(max_examples=100)
def test_property_25_sanitizacao_consistente_tipada_preserva_estrutura(
    sal: int,
    uuid_compartilhado: UUID,
    partes_telefone: tuple[int, int],
    numero_documento: int,
    octetos_ip: tuple[int, int, int],
    ordem_campos: Sequence[int],
    ordem_identificadores: Sequence[int],
    ordem_vinculos: Sequence[int],
    ordem_timeline: Sequence[int],
    repeticoes: int,
) -> None:
    """A visão segura remove originais e conserva toda a topologia.

    **Validates: Requirements 14.1, 14.2, 14.3, 14.4, 16.4**
    """

    token = f"{sal:016X}"
    call_id = f"SYN_CALL_{token}"
    call_id_equivalente = call_id.swapcase()
    uuid_canonico = str(uuid_compartilhado)
    uuid_canal_original = uuid_canonico.upper()
    uuid_sessao_original = f"{{{uuid_canonico}}}"

    parte_esquerda, parte_direita = partes_telefone
    digitos_telefone = f"55219{parte_esquerda:04d}{parte_direita:04d}"
    telefone_formatado = (
        f"+55 (21) 9{parte_esquerda:04d}-{parte_direita:04d}"
    )
    telefone_equivalente = (
        f"55 21 9{parte_esquerda:04d} {parte_direita:04d}"
    )

    digitos_documento = f"{numero_documento:011d}"
    documento_formatado = (
        f"{digitos_documento[:3]}.{digitos_documento[3:6]}."
        f"{digitos_documento[6:9]}-{digitos_documento[9:]}"
    )
    documento_equivalente = (
        f"{digitos_documento[:3]} {digitos_documento[3:6]} "
        f"{digitos_documento[6:9]} {digitos_documento[9:]}"
    )

    ip_interno = f"10.{octetos_ip[0]}.{octetos_ip[1]}.{octetos_ip[2]}"
    host_interno = f"syn-{token.lower()}.internal"
    url_interna = (
        f"https://{host_interno}/synthetic/{token.lower()}"
    )
    credencial = f"SYN_TEST_CREDENTIAL_{token}"
    dado_cliente = f"SYNTHETIC_CUSTOMER_{token}"

    entrada_vpl_id = "entrada-sintetica-vpl-1"
    entrada_ork_id = "entrada-sintetica-ork-2"
    arquivo_vpl = "<ARQUIVO_1>"
    arquivo_ork = "<ARQUIVO_2>"
    origem_vpl = f"C:/synthetic-input/{call_id}-vpl.txt"
    origem_ork = f"C:/synthetic-input/{call_id_equivalente}-ork.txt"

    especificacoes_base = (
        ("CallId", call_id, "CALL_ID", call_id.casefold()),
        (
            "TelecomCallId",
            call_id_equivalente,
            "CALL_ID",
            call_id.casefold(),
        ),
        ("uuid", uuid_canonico, "UUID", uuid_canonico),
        (
            "channel_uuid",
            uuid_canal_original,
            "UUID_CANAL",
            uuid_canonico,
        ),
        (
            "session_uuid",
            uuid_sessao_original,
            "UUID_SESSAO",
            uuid_canonico,
        ),
        (
            "telefone",
            telefone_formatado,
            "TELEFONE",
            digitos_telefone,
        ),
        (
            "phone",
            telefone_equivalente,
            "TELEFONE",
            digitos_telefone,
        ),
        (
            "documento",
            documento_formatado,
            "DOCUMENTO",
            digitos_documento,
        ),
        (
            "cpf",
            documento_equivalente,
            "DOCUMENTO",
            digitos_documento,
        ),
        ("ip", ip_interno, "IP", ip_interno),
        (
            "host",
            host_interno,
            "HOST_INTERNO",
            host_interno.casefold(),
        ),
        ("url", url_interna, "URL_INTERNA", url_interna),
        ("token", credencial, "CREDENCIAL", credencial),
        (
            "customer_data",
            dado_cliente,
            "DADO_CLIENTE",
            dado_cliente,
        ),
        ("email", dado_cliente, "DADO_CLIENTE", dado_cliente),
    )
    especificacoes = tuple(
        especificacoes_base[indice] for indice in ordem_campos
    )
    campos = tuple(
        CampoEstruturado(
            nome=nome,
            valor_original=valor,
            proveniencia=Proveniencia(
                arquivo_token=arquivo_vpl,
                entrada_id=entrada_vpl_id,
                linha_inicial=1,
                linha_final=2,
                nome_campo=nome,
                regra_extracao="extrator-sintetico-property-25-v1",
            ),
        )
        for nome, valor, _, _ in especificacoes
    )

    proveniencia_call_id = Proveniencia(
        arquivo_token=arquivo_vpl,
        entrada_id=entrada_vpl_id,
        linha_inicial=1,
        linha_final=1,
        nome_campo="CallId",
        regra_extracao="extrator-sintetico-property-25-v1",
    )
    proveniencia_uuid_canal = Proveniencia(
        arquivo_token=arquivo_vpl,
        entrada_id=entrada_vpl_id,
        linha_inicial=1,
        linha_final=1,
        nome_campo="channel_uuid",
        regra_extracao="extrator-sintetico-property-25-v1",
    )
    proveniencia_uuid_sessao = Proveniencia(
        arquivo_token=arquivo_vpl,
        entrada_id=entrada_vpl_id,
        linha_inicial=2,
        linha_final=2,
        nome_campo="session_uuid",
        regra_extracao="extrator-sintetico-property-25-v1",
    )
    identificadores_base = (
        IdentificadorTecnico(
            tipo=TipoIdentificador.CALL_ID,
            namespace_comparacao="chamada_externa",
            nome_campo="CallId",
            valor_original=call_id,
            valor_normalizado=call_id.casefold(),
            proveniencia=proveniencia_call_id,
        ),
        IdentificadorTecnico(
            tipo=TipoIdentificador.UUID_CANAL,
            namespace_comparacao="uuid_canal",
            nome_campo="channel_uuid",
            valor_original=uuid_canal_original,
            valor_normalizado=uuid_canonico,
            proveniencia=proveniencia_uuid_canal,
        ),
        IdentificadorTecnico(
            tipo=TipoIdentificador.UUID_SESSAO,
            namespace_comparacao="uuid_sessao",
            nome_campo="session_uuid",
            valor_original=uuid_sessao_original,
            valor_normalizado=uuid_canonico,
            proveniencia=proveniencia_uuid_sessao,
        ),
    )
    identificadores = tuple(
        identificadores_base[indice] for indice in ordem_identificadores
    )

    proveniencia_vinculo = Proveniencia(
        arquivo_token=arquivo_vpl,
        entrada_id=entrada_vpl_id,
        linha_inicial=1,
        linha_final=2,
        nome_campo="vinculo_sintetico",
        regra_extracao="esquema-sintetico-property-25-v1",
    )
    vinculos_base = (
        VinculoIdentificadores(
            origem=identificadores_base[0],
            destino=identificadores_base[1],
            tipo_relacao="chamada_para_canal",
            evidencia=proveniencia_vinculo,
            esquema_id="schema-sintetico-call-channel",
            esquema_versao=1,
            permite_correlacao=True,
        ),
        VinculoIdentificadores(
            origem=identificadores_base[1],
            destino=identificadores_base[2],
            tipo_relacao="canal_para_sessao",
            evidencia=proveniencia_vinculo,
            esquema_id="schema-sintetico-channel-session",
            esquema_versao=2,
            permite_correlacao=True,
        ),
    )
    vinculos = tuple(vinculos_base[indice] for indice in ordem_vinculos)

    instante_vpl = datetime(2035, 6, 1, 12, 30, tzinfo=timezone.utc)
    instante_ork = instante_vpl + timedelta(seconds=1)
    fragmentos_textuais = (
        f"CallId={call_id}",
        f"TelecomCallId={call_id_equivalente}",
        f"telefone={telefone_formatado}",
        f"phone={telefone_equivalente}",
        f"documento={documento_formatado}",
        f"cpf={documento_equivalente}",
        f"ip={ip_interno}",
        f"host={host_interno}",
        f"url={url_interna}",
        f"token={credencial}",
        f"customer_data={dado_cliente}",
    )
    texto_vpl = " | ".join(
        (*fragmentos_textuais, *((f"CallId={call_id}",) * repeticoes))
    )
    texto_ork = " | ".join(
        (
            f"CallId={call_id_equivalente}",
            f"host={host_interno}",
            f"url={url_interna}",
            f"token={credencial}",
            f"customer_data={dado_cliente}",
        )
    )

    entrada_vpl = EntradaDeLog(
        texto_original=texto_vpl,
        aplicacao="VPL",
        ordem_de_leitura=0,
        interpretada=True,
        carimbo_de_tempo=instante_vpl,
        nivel_de_severidade="INFO",
        mensagem=texto_vpl,
        categoria=Categoria.NAO_CLASSIFICADA,
        correlacionada=True,
        entrada_id=entrada_vpl_id,
        arquivo_origem=origem_vpl,
        arquivo_token=arquivo_vpl,
        posicao_inicial=1,
        posicao_final=2,
        timestamp_original="2035-06-01T12:30:00+00:00",
        timestamp_normalizado=instante_vpl,
        precisao_fracionaria=0,
        origem_evento="modulo.sintetico.vpl",
        formato_origem="perfil-sintetico-property-25",
        campos_estruturados=campos,
        identificadores=identificadores,
        representacao_sanitizada=texto_vpl,
    )
    entrada_ork = EntradaDeLog(
        texto_original=texto_ork,
        aplicacao="ORK",
        ordem_de_leitura=1,
        interpretada=True,
        carimbo_de_tempo=instante_ork,
        nivel_de_severidade="NOTICE",
        mensagem=texto_ork,
        categoria=Categoria.NAO_CLASSIFICADA,
        correlacionada=True,
        entrada_id=entrada_ork_id,
        arquivo_origem=origem_ork,
        arquivo_token=arquivo_ork,
        posicao_inicial=3,
        posicao_final=3,
        timestamp_original="2035-06-01T12:30:01+00:00",
        timestamp_normalizado=instante_ork,
        precisao_fracionaria=0,
        origem_evento="modulo.sintetico.ork",
        formato_origem="perfil-sintetico-property-25",
        representacao_sanitizada=texto_ork,
    )
    entradas_base = (entrada_vpl, entrada_ork)
    timeline = [entradas_base[indice] for indice in ordem_timeline]

    evidencia = Evidencia(
        tipo="vinculo_explicito",
        aplicacao="VPL",
        proveniencia=proveniencia_vinculo,
        timestamp_original="2035-06-01T12:30:00+00:00",
        timestamp_normalizado=instante_vpl,
        campo_ou_condicao="cadeia_sintetica_presente",
        representacao_sanitizada=(
            f"CallId={call_id} channel_uuid={uuid_canal_original} "
            f"token={credencial}"
        ),
    )
    correlacao = ResultadoCorrelacao(
        encontrada=True,
        base_primaria=BaseCorrelacao.CADEIA_DE_VINCULOS,
        bases=(BaseCorrelacao.CADEIA_DE_VINCULOS,),
        evidencias=(evidencia,),
        vinculos_percorridos=vinculos,
        motivo_seguro=f"cadeia explícita para CallId={call_id}",
    )
    resultado = ResultadoDeAnalise(
        identificador=call_id,
        entradas_por_aplicacao={"VPL": [entrada_vpl], "ORK": [entrada_ork]},
        linha_do_tempo=timeline,
        contagem_por_categoria={Categoria.NAO_CLASSIFICADA: 2},
        contagem_por_aplicacao={"VPL": 1, "ORK": 1},
        correlacao_encontrada=True,
        erros=[
            MensagemDeErro(
                arquivo_ou_app=origem_vpl,
                descricao=f"falha sintética token={credencial}",
            )
        ],
        mensagens=[
            f"resumo CallId={call_id_equivalente}",
            f"cliente={dado_cliente}",
        ],
        identificadores_extraidos=list(identificadores),
        vinculos=list(vinculos),
        correlacao=correlacao,
        evidencias=[evidencia],
        aplicacoes_analisadas=["VPL", "ORK"],
    )

    segura = SanitizadorDeResultado().criar_visao_segura(resultado)
    serializada = json.dumps(
        serializar_resultado_de_analise(segura),
        ensure_ascii=False,
        sort_keys=True,
    )
    serializada_normalizada = serializada.casefold()

    valores_originais = {
        call_id,
        call_id_equivalente,
        uuid_canonico,
        uuid_canal_original,
        uuid_sessao_original,
        telefone_formatado,
        telefone_equivalente,
        documento_formatado,
        documento_equivalente,
        ip_interno,
        host_interno,
        url_interna,
        credencial,
        dado_cliente,
        origem_vpl,
        origem_ork,
    }
    assert all(
        valor.casefold() not in serializada_normalizada
        for valor in valores_originais
    )
    assert segura.estado_sanitizacao is EstadoSanitizacao.CONCLUIDA
    assert segura is not resultado

    assert tuple(segura.entradas_por_aplicacao) == tuple(
        resultado.entradas_por_aplicacao
    )
    assert {
        aplicacao: tuple(entrada.entrada_id for entrada in entradas)
        for aplicacao, entradas in segura.entradas_por_aplicacao.items()
    } == {
        aplicacao: tuple(entrada.entrada_id for entrada in entradas)
        for aplicacao, entradas in resultado.entradas_por_aplicacao.items()
    }
    assert tuple(entrada.entrada_id for entrada in segura.linha_do_tempo) == tuple(
        entrada.entrada_id for entrada in resultado.linha_do_tempo
    )
    assert segura.contagem_por_categoria == resultado.contagem_por_categoria
    assert segura.contagem_por_aplicacao == resultado.contagem_por_aplicacao
    assert segura.aplicacoes_analisadas == resultado.aplicacoes_analisadas
    assert len(segura.erros) == len(resultado.erros)
    assert len(segura.mensagens) == len(resultado.mensagens)

    entrada_vpl_segura = segura.entradas_por_aplicacao["VPL"][0]
    entrada_ork_segura = segura.entradas_por_aplicacao["ORK"][0]
    assert len(entrada_vpl_segura.campos_estruturados) == len(campos)
    assert tuple(
        campo.nome for campo in entrada_vpl_segura.campos_estruturados
    ) == tuple(campo.nome for campo in campos)
    assert tuple(
        campo.proveniencia.nome_campo
        for campo in entrada_vpl_segura.campos_estruturados
    ) == tuple(campo.proveniencia.nome_campo for campo in campos)

    placeholders_por_chave: dict[tuple[str, str], set[str]] = {}
    for especificacao, campo_seguro in zip(
        especificacoes,
        entrada_vpl_segura.campos_estruturados,
        strict=True,
    ):
        nome, _, prefixo, normalizado = especificacao
        assert campo_seguro.nome == nome
        assert _PADRAO_PLACEHOLDER.fullmatch(campo_seguro.valor_original)
        assert campo_seguro.valor_original.startswith(f"<{prefixo}_")
        placeholders_por_chave.setdefault((prefixo, normalizado), set()).add(
            campo_seguro.valor_original
        )

    assert set(placeholders_por_chave) == {
        (prefixo, normalizado)
        for _, _, prefixo, normalizado in especificacoes_base
    }
    assert {prefixo for prefixo, _ in placeholders_por_chave} == set(
        _PREFIXOS_ESPERADOS
    )
    assert all(
        placeholders == {f"<{prefixo}_1>"}
        for (prefixo, _), placeholders in placeholders_por_chave.items()
    )
    placeholders_unicos = {
        next(iter(placeholders))
        for placeholders in placeholders_por_chave.values()
    }
    assert len(placeholders_unicos) == len(placeholders_por_chave)

    placeholders_uuid = {
        next(iter(placeholders_por_chave[(prefixo, uuid_canonico)]))
        for prefixo in ("UUID", "UUID_CANAL", "UUID_SESSAO")
    }
    assert placeholders_uuid == {
        "<UUID_1>",
        "<UUID_CANAL_1>",
        "<UUID_SESSAO_1>",
    }

    identificadores_seguros = tuple(entrada_vpl_segura.identificadores)
    assert len(identificadores_seguros) == len(identificadores)
    assert tuple(
        (item.tipo, item.namespace_comparacao, item.nome_campo)
        for item in identificadores_seguros
    ) == tuple(
        (item.tipo, item.namespace_comparacao, item.nome_campo)
        for item in identificadores
    )
    chave_por_tipo = {
        TipoIdentificador.CALL_ID: ("CALL_ID", call_id.casefold()),
        TipoIdentificador.UUID_CANAL: ("UUID_CANAL", uuid_canonico),
        TipoIdentificador.UUID_SESSAO: ("UUID_SESSAO", uuid_canonico),
    }
    for original, sanitizado in zip(
        identificadores,
        identificadores_seguros,
        strict=True,
    ):
        placeholder = next(
            iter(placeholders_por_chave[chave_por_tipo[original.tipo]])
        )
        assert sanitizado.valor_original == placeholder
        assert sanitizado.valor_normalizado == placeholder
        assert sanitizado.proveniencia.nome_campo == original.proveniencia.nome_campo

    call_placeholder = next(
        iter(placeholders_por_chave[("CALL_ID", call_id.casefold())])
    )
    credencial_placeholder = next(
        iter(placeholders_por_chave[("CREDENCIAL", credencial)])
    )
    assert segura.identificador == call_placeholder
    assert call_placeholder in entrada_vpl_segura.texto_original
    assert call_placeholder in entrada_ork_segura.texto_original
    assert call_placeholder in segura.evidencias[0].representacao_sanitizada
    assert credencial_placeholder in segura.erros[0].descricao
    assert all(
        item_entrada is item_extraido
        for item_entrada, item_extraido in zip(
            identificadores_seguros,
            segura.identificadores_extraidos,
            strict=True,
        )
    )

    assert len(segura.vinculos) == len(resultado.vinculos)
    assert tuple(
        (
            vinculo.origem.tipo,
            vinculo.destino.tipo,
            vinculo.tipo_relacao,
            vinculo.esquema_id,
            vinculo.esquema_versao,
            vinculo.permite_correlacao,
            vinculo.ambiguo,
        )
        for vinculo in segura.vinculos
    ) == tuple(
        (
            vinculo.origem.tipo,
            vinculo.destino.tipo,
            vinculo.tipo_relacao,
            vinculo.esquema_id,
            vinculo.esquema_versao,
            vinculo.permite_correlacao,
            vinculo.ambiguo,
        )
        for vinculo in resultado.vinculos
    )
    identificador_seguro_por_tipo = {
        identificador.tipo: identificador
        for identificador in segura.identificadores_extraidos
    }
    for vinculo in segura.vinculos:
        assert vinculo.origem is identificador_seguro_por_tipo[vinculo.origem.tipo]
        assert vinculo.destino is identificador_seguro_por_tipo[vinculo.destino.tipo]

    assert segura.correlacao is not None
    assert segura.correlacao.encontrada == resultado.correlacao.encontrada
    assert segura.correlacao.base_primaria is resultado.correlacao.base_primaria
    assert segura.correlacao.bases == resultado.correlacao.bases
    assert len(segura.correlacao.evidencias) == len(
        resultado.correlacao.evidencias
    )
    assert len(segura.correlacao.vinculos_percorridos) == len(
        resultado.correlacao.vinculos_percorridos
    )
    assert all(
        vinculo_aninhado is vinculo_superficial
        for vinculo_aninhado, vinculo_superficial in zip(
            segura.correlacao.vinculos_percorridos,
            segura.vinculos,
            strict=True,
        )
    )
    assert segura.correlacao.evidencias[0] is segura.evidencias[0]
