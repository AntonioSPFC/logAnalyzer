"""Testes unitários dos modelos, erros e contratos opcionais da Fase 2.

Todos os valores usados são sintéticos e permanecem em memória.

Validates: Requirements 1.4, 1.5, 1.6, 5.1, 6.8, 14.7, 16.2.
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from log_analyzer.core import (
    BaseCorrelacao,
    CampoEstruturado,
    Categoria,
    EntradaDeLog,
    EntradaIndexada,
    ErroDeCatalogo,
    ErroDeDecodificacao,
    ErroDeIntegridadeDaFonte,
    ErroDeSanitizacao,
    ErroTemporal,
    EstadoCausaRaiz,
    EstadoSanitizacao,
    Evidencia,
    FalhaDeEntrada,
    IdentificadorTecnico,
    Padrao_de_Analise,
    Parser_de_Aplicacao,
    Parser_de_Bloco,
    Proveniencia,
    ReferenciaRegra,
    ReferenciaTextoOriginal,
    Registro_de_Aplicacoes,
    ResultadoCausaRaiz,
    ResultadoCorrelacao,
    ResultadoDeAnalise,
    TipoIdentificador,
    VinculoIdentificadores,
    serializar_entrada_de_log,
    serializar_resultado_de_analise,
)

_INSTANTE_UTC = datetime(2030, 2, 3, 7, 5, 6, 7000, tzinfo=timezone.utc)
_TIMESTAMP_ORIGINAL = "2030-02-03T07:05:06.007+00:00"
_TEXTO_ORIGINAL = "  evento sintético CallId=<CALL_ID_1>\ncontinuação preservada  "


def _proveniencia(
    *,
    entrada_id: str = "entrada-sintetica-1",
    arquivo_token: str = "<ARQUIVO_1>",
    linha_inicial: int = 1,
    linha_final: int = 2,
    nome_campo: str = "CallId",
) -> Proveniencia:
    return Proveniencia(
        arquivo_token=arquivo_token,
        entrada_id=entrada_id,
        linha_inicial=linha_inicial,
        linha_final=linha_final,
        span_inicial=20,
        span_final=31,
        nome_campo=nome_campo,
        regra_extracao="extrator-sintetico-v1",
    )


def _campo(proveniencia: Proveniencia | None = None) -> CampoEstruturado:
    return CampoEstruturado(
        nome="CallId",
        valor_original="<CALL_ID_1>",
        proveniencia=proveniencia or _proveniencia(),
    )


def _identificador(
    proveniencia: Proveniencia | None = None,
    *,
    tipo: TipoIdentificador = TipoIdentificador.CALL_ID,
    nome_campo: str = "CallId",
    namespace: str = "chamada_externa",
    valor: str = "<CALL_ID_1>",
) -> IdentificadorTecnico:
    return IdentificadorTecnico(
        tipo=tipo,
        namespace_comparacao=namespace,
        nome_campo=nome_campo,
        valor_original=valor,
        valor_normalizado=valor.casefold(),
        proveniencia=proveniencia or _proveniencia(nome_campo=nome_campo),
    )


def _falha(proveniencia: Proveniencia | None = None) -> FalhaDeEntrada:
    return FalhaDeEntrada(
        codigo="SYNTHETIC_FAILURE",
        proveniencia=proveniencia or _proveniencia(),
        detalhe_seguro="Falha sintética sem conteúdo de origem.",
    )


def _evidencia(timestamp_normalizado: datetime = _INSTANTE_UTC) -> Evidencia:
    return Evidencia(
        tipo="campo_estruturado",
        aplicacao="VPL",
        proveniencia=_proveniencia(),
        timestamp_original=_TIMESTAMP_ORIGINAL,
        timestamp_normalizado=timestamp_normalizado,
        campo_ou_condicao="CallId presente",
        representacao_sanitizada="CallId=<CALL_ID_1>",
    )


def _texto_ref() -> ReferenciaTextoOriginal:
    return ReferenciaTextoOriginal(
        arquivo_token="<ARQUIVO_1>",
        inicio_byte=0,
        fim_byte=96,
        linha_inicial=1,
        linha_final=2,
        sha256="0" * 64,
    )


def _entrada_indexada(timestamp_normalizado: datetime = _INSTANTE_UTC) -> EntradaIndexada:
    proveniencia = _proveniencia()
    return EntradaIndexada(
        entrada_id="entrada-sintetica-1",
        aplicacao="VPL",
        ordem_de_leitura=0,
        texto_ref=_texto_ref(),
        cabecalho=(_campo(proveniencia),),
        identificadores_digest=("digest-sintetico-1",),
        timestamp_original=_TIMESTAMP_ORIGINAL,
        timestamp_normalizado=timestamp_normalizado,
        falhas=(_falha(proveniencia),),
        interpretada=True,
    )


def _entrada_fase2(
    *,
    entrada_id: str = "entrada-sintetica-1",
    ordem: int = 0,
    timestamp_normalizado: datetime | None = _INSTANTE_UTC,
    arquivo_origem: str | None = None,
    representacao_sanitizada: str | None = None,
) -> EntradaDeLog:
    proveniencia = _proveniencia(entrada_id=entrada_id)
    timestamp_original = (
        _TIMESTAMP_ORIGINAL if timestamp_normalizado is not None else None
    )
    return EntradaDeLog(
        texto_original=_TEXTO_ORIGINAL,
        aplicacao="VPL",
        ordem_de_leitura=ordem,
        interpretada=True,
        carimbo_de_tempo=_INSTANTE_UTC,
        nivel_de_severidade="INFO",
        mensagem="evento sintético CallId=<CALL_ID_1>",
        entrada_id=entrada_id,
        arquivo_origem=arquivo_origem,
        arquivo_token="<ARQUIVO_1>",
        posicao_inicial=1,
        posicao_final=2,
        timestamp_original=timestamp_original,
        timestamp_normalizado=timestamp_normalizado,
        precisao_fracionaria=3 if timestamp_original is not None else None,
        origem_evento="modulo.sintetico",
        formato_origem="perfil-sintetico",
        campos_estruturados=(_campo(proveniencia),),
        identificadores=(_identificador(proveniencia),),
        falhas=(_falha(proveniencia),),
        representacao_sanitizada=representacao_sanitizada,
    )


def _entrada_com_timestamp(timestamp_normalizado: datetime) -> EntradaDeLog:
    return _entrada_fase2(timestamp_normalizado=timestamp_normalizado)


def _evidencia_com_timestamp(timestamp_normalizado: datetime) -> Evidencia:
    return _evidencia(timestamp_normalizado)


def _indexada_com_timestamp(timestamp_normalizado: datetime) -> EntradaIndexada:
    return _entrada_indexada(timestamp_normalizado)


class _ParserLegadoMinimo(Parser_de_Aplicacao):
    """Plugin line-based que implementa somente o ABC preservado da Fase 1."""

    @property
    def niveis_de_severidade(self) -> frozenset[str]:
        return frozenset({"INFO"})

    def interpretar_entrada(self, texto: str) -> EntradaDeLog:
        return EntradaDeLog(
            texto_original=texto,
            aplicacao="SINTETICA",
            ordem_de_leitura=0,
            interpretada=False,
        )

    def imprimir_entrada(self, entrada: EntradaDeLog) -> str:
        return entrada.texto_original


class _PadraoLegadoMinimo(Padrao_de_Analise):
    @property
    def categorias(self) -> tuple[Categoria, ...]:
        return (Categoria.SUCESSO, Categoria.ERRO, Categoria.NAO_CLASSIFICADA)

    def classificar(self, entrada: EntradaDeLog) -> Categoria:
        return Categoria.NAO_CLASSIFICADA


def test_defaults_mutaveis_do_resultado_sao_independentes() -> None:
    primeiro = ResultadoDeAnalise("<CALL_ID_1>")
    segundo = ResultadoDeAnalise("<CALL_ID_2>")

    campos_mutaveis = (
        "entradas_por_aplicacao",
        "linha_do_tempo",
        "contagem_por_categoria",
        "contagem_por_aplicacao",
        "erros",
        "mensagens",
        "entradas_sem_ordenacao_temporal",
        "identificadores_extraidos",
        "vinculos",
        "evidencias",
        "aplicacoes_analisadas",
        "aplicacoes_ausentes_ou_invalidas",
    )
    for nome in campos_mutaveis:
        assert getattr(primeiro, nome) is not getattr(segundo, nome)

    primeiro.entradas_por_aplicacao["VPL"] = []
    primeiro.linha_do_tempo.append(
        EntradaDeLog("evento sintético", "VPL", 0, False)
    )
    primeiro.contagem_por_categoria[Categoria.NAO_CLASSIFICADA] = 1
    primeiro.contagem_por_aplicacao["VPL"] = 1
    primeiro.mensagens.append("mensagem sintética")
    primeiro.aplicacoes_analisadas.append("VPL")

    assert segundo.entradas_por_aplicacao == {}
    assert segundo.linha_do_tempo == []
    assert segundo.contagem_por_categoria == {}
    assert segundo.contagem_por_aplicacao == {}
    assert segundo.mensagens == []
    assert segundo.aplicacoes_analisadas == []
    assert primeiro.causa_raiz is not segundo.causa_raiz

    assert segundo.categoria_de_cenario is Categoria.NAO_CLASSIFICADA
    assert segundo.correlacao is None
    assert segundo.regra_aplicada is None
    assert segundo.versao_catalogo == "sem-catalogo-ativo"
    assert segundo.estado_sanitizacao is EstadoSanitizacao.INTERNA_BRUTA
    assert segundo.causa_raiz.estado is EstadoCausaRaiz.NAO_DETERMINADA
    assert segundo.causa_raiz.descricao_sanitizada == "não determinada"
    assert segundo.cobertura_rotulada == "1 cenário de sucesso; 0 cenários de erro"


def test_modelos_aditivos_sao_imutaveis_e_preservam_valores_originais() -> None:
    proveniencia = _proveniencia()
    campo = _campo(proveniencia)
    identificador = _identificador(proveniencia)
    falha = _falha(proveniencia)
    destino = _identificador(
        proveniencia,
        tipo=TipoIdentificador.UUID_SESSAO,
        nome_campo="SessionId",
        namespace="sessao",
        valor="<UUID_SESSAO_1>",
    )
    vinculo = VinculoIdentificadores(
        origem=identificador,
        destino=destino,
        tipo_relacao="mapeia_sessao",
        evidencia=proveniencia,
        esquema_id="esquema-sintetico",
        esquema_versao=1,
        permite_correlacao=True,
    )
    evidencia = _evidencia()
    regra = ReferenciaRegra("regra-sintetica", 1, "catalogo-sintetico-v1")
    correlacao = ResultadoCorrelacao(
        encontrada=True,
        base_primaria=BaseCorrelacao.CADEIA_DE_VINCULOS,
        bases=(BaseCorrelacao.CADEIA_DE_VINCULOS,),
        evidencias=(evidencia,),
        vinculos_percorridos=(vinculo,),
    )
    causa = ResultadoCausaRaiz(
        estado=EstadoCausaRaiz.DETERMINADA,
        descricao_sanitizada="causa sintética determinada",
        regra=regra,
    )
    referencia = _texto_ref()
    indexada = _entrada_indexada()
    entrada = _entrada_fase2()

    objetos_e_campos = (
        (proveniencia, "linha_inicial"),
        (campo, "valor_original"),
        (identificador, "valor_original"),
        (falha, "codigo"),
        (vinculo, "ambiguo"),
        (evidencia, "campo_ou_condicao"),
        (regra, "versao"),
        (correlacao, "encontrada"),
        (causa, "descricao_sanitizada"),
        (referencia, "inicio_byte"),
        (indexada, "interpretada"),
        (entrada, "texto_original"),
    )
    for objeto, nome_campo in objetos_e_campos:
        with pytest.raises(FrozenInstanceError):
            setattr(objeto, nome_campo, getattr(objeto, nome_campo))

    assert entrada.texto_original == _TEXTO_ORIGINAL
    assert campo.valor_original == "<CALL_ID_1>"
    assert identificador.valor_original == "<CALL_ID_1>"
    assert identificador.valor_normalizado == "<call_id_1>"


def test_construcao_legada_posicional_nao_exige_metadados_da_fase2() -> None:
    instante_legado = datetime(2030, 2, 3, 4, 5, 6)
    entrada = EntradaDeLog(
        "evento legado sintético",
        "VOCI",
        7,
        True,
        instante_legado,
        "INFO",
        "mensagem legada sintética",
        Categoria.SUCESSO,
        True,
    )
    resultado = ResultadoDeAnalise(
        "ID-SINTETICO-LEGADO",
        {"VOCI": [entrada]},
        [entrada],
        {Categoria.SUCESSO: 1},
        {"VOCI": 1},
        True,
        [],
        ["análise legada sintética"],
    )

    assert entrada.entrada_id is None
    assert entrada.timestamp_original is None
    assert entrada.timestamp_normalizado is None
    assert entrada.campos_estruturados == ()
    assert entrada.identificadores == ()
    assert entrada.falhas == ()
    assert resultado.categoria_de_cenario is Categoria.NAO_CLASSIFICADA
    assert resultado.entradas_sem_ordenacao_temporal == []
    assert resultado.causa_raiz == ResultadoCausaRaiz()

    serializada = serializar_entrada_de_log(entrada)
    assert tuple(serializada)[:9] == (
        "texto_original",
        "aplicacao",
        "ordem_de_leitura",
        "interpretada",
        "carimbo_de_tempo",
        "nivel_de_severidade",
        "mensagem",
        "categoria",
        "correlacionada",
    )
    assert serializada["carimbo_de_tempo"] == "2030-02-03T04:05:06"
    assert serializada["categoria"] == "sucesso"


@pytest.mark.parametrize(
    "construtor",
    (_entrada_com_timestamp, _evidencia_com_timestamp, _indexada_com_timestamp),
    ids=("entrada", "evidencia", "entrada-indexada"),
)
def test_timestamp_normalizado_aceita_datetime_aware_em_utc(construtor) -> None:
    objeto = construtor(_INSTANTE_UTC)

    assert objeto.timestamp_normalizado == _INSTANTE_UTC
    assert objeto.timestamp_normalizado.tzinfo is not None
    assert objeto.timestamp_normalizado.utcoffset() == timedelta(0)
    assert objeto.timestamp_original == _TIMESTAMP_ORIGINAL


@pytest.mark.parametrize(
    "instante_invalido",
    (
        datetime(2030, 2, 3, 7, 5, 6),
        datetime(
            2030,
            2,
            3,
            4,
            5,
            6,
            tzinfo=timezone(timedelta(hours=-3)),
        ),
    ),
    ids=("naive", "offset-nao-utc"),
)
@pytest.mark.parametrize(
    "construtor",
    (_entrada_com_timestamp, _evidencia_com_timestamp, _indexada_com_timestamp),
    ids=("entrada", "evidencia", "entrada-indexada"),
)
def test_timestamp_normalizado_rejeita_naive_e_offset_nao_utc(
    construtor, instante_invalido: datetime
) -> None:
    with pytest.raises(ValueError, match="UTC"):
        construtor(instante_invalido)


def test_timestamp_normalizado_requer_timestamp_original_preservado() -> None:
    with pytest.raises(ValueError, match="timestamp_original"):
        EntradaDeLog(
            texto_original="evento sintético",
            aplicacao="VPL",
            ordem_de_leitura=0,
            interpretada=False,
            timestamp_normalizado=_INSTANTE_UTC,
        )


def test_invariantes_de_entrada_e_proveniencia_rejeitam_metadados_incoerentes() -> None:
    with pytest.raises(ValueError, match="linha_inicial"):
        Proveniencia("<ARQUIVO_1>", "entrada-sintetica-1", 0, 1)

    proveniencia_de_outra_entrada = _proveniencia(entrada_id="entrada-sintetica-2")
    with pytest.raises(ValueError, match="entrada_id diferente"):
        EntradaDeLog(
            texto_original="evento sintético",
            aplicacao="VPL",
            ordem_de_leitura=0,
            interpretada=False,
            entrada_id="entrada-sintetica-1",
            arquivo_token="<ARQUIVO_1>",
            posicao_inicial=1,
            posicao_final=2,
            campos_estruturados=(_campo(proveniencia_de_outra_entrada),),
        )

    with pytest.raises(ValueError, match="arquivo_token diferente"):
        EntradaIndexada(
            entrada_id="entrada-sintetica-1",
            aplicacao="VPL",
            ordem_de_leitura=0,
            texto_ref=_texto_ref(),
            cabecalho=(
                _campo(_proveniencia(arquivo_token="<ARQUIVO_2>")),
            ),
            identificadores_digest=(),
            timestamp_original=None,
            timestamp_normalizado=None,
            falhas=(),
            interpretada=False,
        )


@pytest.mark.parametrize(
    ("campo_invalido", "valor_invalido"),
    (
        ("carimbo_de_tempo", None),
        ("nivel_de_severidade", ""),
        ("mensagem", ""),
    ),
)
def test_entrada_interpretada_mantem_invariante_legado(
    campo_invalido: str, valor_invalido: object
) -> None:
    argumentos: dict[str, object] = {
        "texto_original": "evento sintético",
        "aplicacao": "VPL",
        "ordem_de_leitura": 0,
        "interpretada": True,
        "carimbo_de_tempo": _INSTANTE_UTC,
        "nivel_de_severidade": "INFO",
        "mensagem": "mensagem sintética",
    }
    argumentos[campo_invalido] = valor_invalido

    with pytest.raises(ValueError, match=campo_invalido):
        EntradaDeLog(**argumentos)  # type: ignore[arg-type]


def test_resultado_fase2_exige_particao_temporal_total_e_disjunta() -> None:
    com_utc = _entrada_fase2()
    sem_utc = _entrada_fase2(
        entrada_id="entrada-sintetica-2",
        ordem=1,
        timestamp_normalizado=None,
    )

    resultado = ResultadoDeAnalise(
        identificador="<CALL_ID_1>",
        entradas_por_aplicacao={"VPL": [com_utc, sem_utc]},
        linha_do_tempo=[com_utc],
        entradas_sem_ordenacao_temporal=[sem_utc],
    )
    assert resultado.linha_do_tempo == [com_utc]
    assert resultado.entradas_sem_ordenacao_temporal == [sem_utc]

    with pytest.raises(ValueError, match="somente timestamps UTC"):
        ResultadoDeAnalise(
            identificador="<CALL_ID_1>",
            entradas_por_aplicacao={"VPL": [com_utc, sem_utc]},
            linha_do_tempo=[com_utc, sem_utc],
        )

    with pytest.raises(ValueError, match="exatamente as entradas selecionadas"):
        ResultadoDeAnalise(
            identificador="<CALL_ID_1>",
            entradas_por_aplicacao={"VPL": [com_utc, sem_utc]},
            linha_do_tempo=[com_utc],
        )

    sem_utc_com_mesma_identidade = _entrada_fase2(
        entrada_id="entrada-sintetica-1",
        ordem=2,
        timestamp_normalizado=None,
    )
    with pytest.raises(ValueError, match="união disjunta"):
        ResultadoDeAnalise(
            identificador="<CALL_ID_1>",
            entradas_por_aplicacao={
                "VPL": [com_utc, sem_utc_com_mesma_identidade]
            },
            linha_do_tempo=[com_utc],
            entradas_sem_ordenacao_temporal=[sem_utc_com_mesma_identidade],
        )


def test_classificacao_correlacao_e_causa_raiz_exigem_evidencia_e_regra() -> None:
    evidencia = _evidencia()
    regra = ReferenciaRegra("regra-sintetica", 1, "catalogo-sintetico-v1")

    with pytest.raises(ValueError, match="requer evidências"):
        ResultadoCorrelacao(
            encontrada=True,
            base_primaria=BaseCorrelacao.VALOR_COMPARTILHADO,
            bases=(BaseCorrelacao.VALOR_COMPARTILHADO,),
        )

    with pytest.raises(ValueError, match="regra_aplicada"):
        ResultadoDeAnalise(
            identificador="<CALL_ID_1>",
            categoria_de_cenario=Categoria.SUCESSO,
            evidencias=[evidencia],
            versao_catalogo="catalogo-sintetico-v1",
        )

    with pytest.raises(ValueError, match="requer evidências"):
        ResultadoDeAnalise(
            identificador="<CALL_ID_1>",
            categoria_de_cenario=Categoria.SUCESSO,
            regra_aplicada=regra,
            versao_catalogo="catalogo-sintetico-v1",
        )

    with pytest.raises(ValueError, match="referência de regra"):
        ResultadoCausaRaiz(
            estado=EstadoCausaRaiz.DETERMINADA,
            descricao_sanitizada="causa sintética",
        )

    classificado = ResultadoDeAnalise(
        identificador="<CALL_ID_1>",
        categoria_de_cenario=Categoria.SUCESSO,
        evidencias=[evidencia],
        regra_aplicada=regra,
        versao_catalogo="catalogo-sintetico-v1",
    )
    assert classificado.regra_aplicada is regra

    correlacao_ambigua = ResultadoCorrelacao(
        encontrada=False,
        base_primaria=BaseCorrelacao.AMBIGUA,
        bases=(BaseCorrelacao.AMBIGUA,),
        motivo_seguro="associação sintética ambígua",
    )
    with pytest.raises(ValueError, match="ambígua"):
        ResultadoDeAnalise(
            identificador="<CALL_ID_1>",
            correlacao_encontrada=False,
            correlacao=correlacao_ambigua,
            categoria_de_cenario=Categoria.SUCESSO,
            evidencias=[evidencia],
            regra_aplicada=regra,
            versao_catalogo="catalogo-sintetico-v1",
        )


def test_visao_concluida_exige_representacao_sanitizada_e_sem_fonte_interna() -> None:
    entrada_segura = _entrada_fase2(
        representacao_sanitizada="evento sintético CallId=<CALL_ID_1>"
    )
    resultado = ResultadoDeAnalise(
        identificador="<CALL_ID_1>",
        entradas_por_aplicacao={"VPL": [entrada_segura]},
        linha_do_tempo=[entrada_segura],
        estado_sanitizacao=EstadoSanitizacao.CONCLUIDA,
    )
    assert resultado.estado_sanitizacao is EstadoSanitizacao.CONCLUIDA

    sem_representacao = _entrada_fase2()
    with pytest.raises(ValueError, match="representação sanitizada"):
        ResultadoDeAnalise(
            identificador="<CALL_ID_1>",
            entradas_por_aplicacao={"VPL": [sem_representacao]},
            linha_do_tempo=[sem_representacao],
            estado_sanitizacao=EstadoSanitizacao.CONCLUIDA,
        )

    com_fonte_interna = _entrada_fase2(
        arquivo_origem="C:/fontes-sinteticas/entrada.txt",
        representacao_sanitizada="evento sintético CallId=<CALL_ID_1>",
    )
    with pytest.raises(ValueError, match="arquivo_origem"):
        ResultadoDeAnalise(
            identificador="<CALL_ID_1>",
            entradas_por_aplicacao={"VPL": [com_fonte_interna]},
            linha_do_tempo=[com_fonte_interna],
            estado_sanitizacao=EstadoSanitizacao.CONCLUIDA,
        )


def test_serializacao_aditiva_e_json_safe_sem_reinterpretar_campos() -> None:
    entrada = _entrada_fase2()
    resultado = ResultadoDeAnalise(
        identificador="<CALL_ID_1>",
        entradas_por_aplicacao={"VPL": [entrada]},
        linha_do_tempo=[entrada],
        contagem_por_categoria={Categoria.NAO_CLASSIFICADA: 1},
        contagem_por_aplicacao={"VPL": 1},
        identificadores_extraidos=list(entrada.identificadores),
        aplicacoes_analisadas=["VPL"],
    )

    serializado = serializar_resultado_de_analise(resultado)
    entrada_serializada = serializado["linha_do_tempo"][0]

    assert entrada_serializada["texto_original"] == _TEXTO_ORIGINAL
    assert entrada_serializada["timestamp_original"] == _TIMESTAMP_ORIGINAL
    assert entrada_serializada["timestamp_normalizado"] == (
        "2030-02-03T07:05:06.007000+00:00"
    )
    assert entrada_serializada["identificadores"][0]["tipo"] == "call_id"
    assert serializado["contagem_por_categoria"] == {"não classificada": 1}
    assert serializado["categoria_de_cenario"] == "não classificada"
    assert serializado["estado_sanitizacao"] == "interna_bruta"
    assert json.loads(json.dumps(serializado, ensure_ascii=False)) == serializado


_ERROS_SEGUROS = (
    (ErroDeDecodificacao, "Falha de decodificação da fonte."),
    (ErroTemporal, "Falha na resolução temporal da entrada."),
    (ErroDeCatalogo, "Falha no catálogo de regras."),
    (ErroDeSanitizacao, "Falha de sanitização; conteúdo suprimido."),
    (
        ErroDeIntegridadeDaFonte,
        "A integridade da fonte não pôde ser confirmada.",
    ),
)


@pytest.mark.parametrize(("classe_erro", "mensagem_esperada"), _ERROS_SEGUROS)
def test_erros_fase2_expoem_somente_mensagem_e_contexto_seguros(
    classe_erro, mensagem_esperada: str
) -> None:
    erro = classe_erro(
        codigo="SYNTHETIC_FAILURE",
        arquivo_token="<ARQUIVO_2>",
        posicao=17,
    )

    assert str(erro) == mensagem_esperada
    assert erro.mensagem == mensagem_esperada
    assert erro.contexto == {
        "codigo": "SYNTHETIC_FAILURE",
        "arquivo_token": "<ARQUIVO_2>",
        "posicao": 17,
    }
    assert "<ARQUIVO_2>" not in str(erro)
    assert "17" not in str(erro)

    dado_bruto_sintetico = "SEGREDO_SINTETICO_42"
    with pytest.raises(TypeError) as exc_info:
        classe_erro(texto_bruto=dado_bruto_sintetico)
    assert dado_bruto_sintetico not in str(exc_info.value)

    token_invalido = f"C:/fontes-sinteticas/{dado_bruto_sintetico}.txt"
    with pytest.raises(ValueError) as exc_info:
        classe_erro(arquivo_token=token_invalido)
    assert dado_bruto_sintetico not in str(exc_info.value)
    assert token_invalido not in str(exc_info.value)


def test_registro_resolve_plugin_minimo_sem_parser_de_bloco() -> None:
    parser = _ParserLegadoMinimo()
    padrao = _PadraoLegadoMinimo()
    registro = Registro_de_Aplicacoes()

    assert Parser_de_Aplicacao.__abstractmethods__ == frozenset(
        {"niveis_de_severidade", "interpretar_entrada", "imprimir_entrada"}
    )
    assert not isinstance(parser, Parser_de_Bloco)
    assert not hasattr(parser, "detectar_inicio")
    assert not hasattr(parser, "interpretar_bloco")

    registro.registrar("SINTETICA", parser, padrao)
    parser_resolvido, padrao_resolvido = registro.obter("SINTETICA")

    assert parser_resolvido is parser
    assert padrao_resolvido is padrao
    assert registro.aplicacoes_suportadas() == ("SINTETICA",)
    assert [
        entrada.texto_original
        for entrada in parser_resolvido.interpretar_arquivo(
            iter(("linha sintética 1", "linha sintética 2"))
        )
    ] == ["linha sintética 1", "linha sintética 2"]
