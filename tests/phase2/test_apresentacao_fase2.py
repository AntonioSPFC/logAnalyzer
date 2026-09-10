"""Testes focados do renderer iterável e seguro da Fase 2.

Validates: Requirements 13.1, 13.2, 13.3, 13.5, 13.6, 13.7,
16.1, 16.2, 16.3, 16.4, 16.6.
"""

from __future__ import annotations

from datetime import datetime, timezone

from log_analyzer.cli.apresentacao import (
    MENSAGEM_FALHA_APRESENTACAO,
    iterar_linhas_resultado,
    renderizar_resultado,
)
from log_analyzer.core.modelos import (
    BaseCorrelacao,
    Categoria,
    EntradaDeLog,
    EstadoSanitizacao,
    Evidencia,
    IdentificadorTecnico,
    Proveniencia,
    ReferenciaRegra,
    ResultadoCorrelacao,
    ResultadoDeAnalise,
    TipoIdentificador,
    VinculoIdentificadores,
)
from log_analyzer.core.visao_segura import (
    MENSAGEM_FALHA_VISAO_SEGURA,
    criar_visao_segura,
)


UTC = timezone.utc
INSTANTE = datetime(2042, 5, 6, 12, 30, 0, 123000, tzinfo=UTC)
SEGREDO_BRUTO = "CONTEUDO_BRUTO_QUE_NAO_PODE_SER_APRESENTADO"


def _proveniencia(app: str, entrada_id: str, linha: int) -> Proveniencia:
    return Proveniencia(
        arquivo_token=f"<ARQUIVO_{app}_1>",
        entrada_id=entrada_id,
        linha_inicial=linha,
        linha_final=linha,
        nome_campo="CallId",
        regra_extracao="extrator-sintetico-v1",
    )


def _identificador(
    app: str,
    entrada_id: str,
    linha: int,
    tipo: TipoIdentificador,
) -> IdentificadorTecnico:
    return IdentificadorTecnico(
        tipo=tipo,
        namespace_comparacao="chamada-sintetica",
        nome_campo="CallId",
        valor_original="<CALL_ID_1>",
        valor_normalizado="<call_id_1>",
        proveniencia=_proveniencia(app, entrada_id, linha),
    )


def _entrada(
    app: str,
    entrada_id: str,
    linha: int,
    ordem: int,
    *,
    timestamp_utc: datetime | None,
    representacao: str,
    categoria: Categoria = Categoria.NAO_CLASSIFICADA,
    severidade: str = "INFO",
) -> EntradaDeLog:
    tipo = (
        TipoIdentificador.CHAMADA_EXTERNA
        if app == "VPL"
        else TipoIdentificador.TELECOM_CALL_ID
    )
    identificador = _identificador(app, entrada_id, linha, tipo)
    return EntradaDeLog(
        texto_original=f"{SEGREDO_BRUTO}:{app}:{entrada_id}",
        aplicacao=app,
        ordem_de_leitura=ordem,
        interpretada=True,
        carimbo_de_tempo=INSTANTE.replace(tzinfo=None),
        nivel_de_severidade=severidade,
        mensagem=f"mensagem bruta {SEGREDO_BRUTO}",
        categoria=categoria,
        correlacionada=True,
        entrada_id=entrada_id,
        arquivo_token=f"<ARQUIVO_{app}_1>",
        posicao_inicial=linha,
        posicao_final=linha,
        timestamp_original="2042-05-06T09:30:00.123-03:00",
        timestamp_normalizado=timestamp_utc,
        precisao_fracionaria=3,
        identificadores=(identificador,),
        representacao_sanitizada=representacao,
    )


def _resultado_interno() -> ResultadoDeAnalise:
    vpl = _entrada(
        "VPL",
        "entrada-vpl-1",
        2,
        0,
        timestamp_utc=INSTANTE,
        representacao="evento VPL CallId=<CALL_ID_1>",
        categoria=Categoria.ERRO,
        severidade="ERROR",
    )
    ork = _entrada(
        "ORK",
        "entrada-ork-1",
        4,
        1,
        timestamp_utc=None,
        representacao="evento ORK CallId=<CALL_ID_1>",
        severidade="WARNING",
    )
    evidencia = Evidencia(
        tipo="campo_compartilhado",
        aplicacao="VPL",
        proveniencia=vpl.identificadores[0].proveniencia,
        timestamp_original=vpl.timestamp_original,
        timestamp_normalizado=vpl.timestamp_normalizado,
        campo_ou_condicao="CallId compartilhado",
        representacao_sanitizada="CallId=<CALL_ID_1>",
    )
    vinculo = VinculoIdentificadores(
        origem=vpl.identificadores[0],
        destino=ork.identificadores[0],
        tipo_relacao="mapeia_chamada",
        evidencia=vpl.identificadores[0].proveniencia,
        esquema_id="esquema-sintetico",
        esquema_versao=1,
        permite_correlacao=True,
    )
    correlacao = ResultadoCorrelacao(
        encontrada=True,
        base_primaria=BaseCorrelacao.VALOR_COMPARTILHADO,
        bases=(BaseCorrelacao.VALOR_COMPARTILHADO,),
        evidencias=(evidencia,),
    )
    regra = ReferenciaRegra(
        rule_id="regra-sintetica",
        versao=2,
        catalogo_versao="catalogo-sintetico-v2",
    )
    return ResultadoDeAnalise(
        identificador="<CALL_ID_1>",
        entradas_por_aplicacao={"VPL": [vpl], "ORK": [ork]},
        linha_do_tempo=[vpl],
        contagem_por_categoria={
            Categoria.ERRO: 1,
            Categoria.NAO_CLASSIFICADA: 1,
        },
        contagem_por_aplicacao={"VPL": 1, "ORK": 1},
        correlacao_encontrada=True,
        categoria_de_cenario=Categoria.SUCESSO,
        entradas_sem_ordenacao_temporal=[ork],
        identificadores_extraidos=[
            vpl.identificadores[0],
            ork.identificadores[0],
        ],
        vinculos=[vinculo],
        correlacao=correlacao,
        evidencias=[evidencia],
        regra_aplicada=regra,
        versao_catalogo=regra.catalogo_versao,
        estado_sanitizacao=EstadoSanitizacao.INTERNA_BRUTA,
        aplicacoes_analisadas=["VPL", "ORK"],
        aplicacoes_ausentes_ou_invalidas=["VOCI"],
        cobertura_rotulada="1 cenário de sucesso; 0 cenários de erro",
    )


def _resultado_concluido() -> ResultadoDeAnalise:
    return criar_visao_segura(_resultado_interno())


def test_iterador_e_wrapper_exibem_as_secoes_aditivas_sem_substituir_severidade() -> None:
    resultado = _resultado_concluido()

    linhas = list(iterar_linhas_resultado(resultado))
    saida = renderizar_resultado(resultado)

    assert saida == "\n".join(linhas)
    assert linhas and all(isinstance(linha, str) for linha in linhas)
    for secao in (
        "Categoria do cenário: SUCESSO",
        "Versão do catálogo: catalogo-sintetico-v2",
        "Regra aplicada: regra-sintetica v2",
        "Cobertura rotulada:",
        "Identificadores extraídos:",
        "Vínculos:",
        "Correlação: encontrada",
        "Linha do tempo UTC:",
        "Entradas sem UTC:",
        "Evidências:",
        "Causa-raiz: não determinada",
    ):
        assert secao in saida

    assert "Base primária: VALOR_COMPARTILHADO" in saida
    assert "2042-05-06T12:30:00.123+00:00" in saida
    assert "Severidade de log: ERROR" in saida
    assert "Categoria da entrada: ERRO" in saida
    assert "evento VPL CallId=<CALL_ID_1>" in saida
    assert "evento ORK CallId=<CALL_ID_1>" in saida
    assert SEGREDO_BRUTO not in saida
    assert "mensagem bruta" not in saida


def test_resultado_fase2_bruto_e_recusado_sem_qualquer_saida_parcial() -> None:
    entrada = _entrada(
        "VPL",
        "entrada-vpl-bruta",
        1,
        0,
        timestamp_utc=None,
        representacao="evento seguro CallId=<CALL_ID_1>",
    )
    resultado = ResultadoDeAnalise(
        identificador=SEGREDO_BRUTO,
        entradas_por_aplicacao={"VPL": [entrada]},
        entradas_sem_ordenacao_temporal=[entrada],
        identificadores_extraidos=[entrada.identificadores[0]],
        estado_sanitizacao=EstadoSanitizacao.INTERNA_BRUTA,
    )

    assert list(iterar_linhas_resultado(resultado)) == [
        MENSAGEM_FALHA_VISAO_SEGURA
    ]
    assert renderizar_resultado(resultado) == MENSAGEM_FALHA_VISAO_SEGURA
    assert SEGREDO_BRUTO not in renderizar_resultado(resultado)


def test_iterador_recusa_resultado_bruto_minimo_sem_inferir_modo_legado() -> None:
    resultado = ResultadoDeAnalise(identificador=SEGREDO_BRUTO)

    assert list(iterar_linhas_resultado(resultado)) == [
        MENSAGEM_FALHA_VISAO_SEGURA
    ]


def test_mutacao_depois_da_sanitizacao_e_revalidada_e_suprimida() -> None:
    resultado = _resultado_concluido()
    dado_injetado = "10.20.30.40"
    resultado.identificador = dado_injetado
    resultado.mensagens.append("Authorization: Bearer token-injetado")

    linhas = list(iterar_linhas_resultado(resultado))
    saida = renderizar_resultado(resultado)

    assert linhas == [MENSAGEM_FALHA_VISAO_SEGURA]
    assert saida == MENSAGEM_FALHA_VISAO_SEGURA
    assert dado_injetado not in saida
    assert "token-injetado" not in saida


class _ItensQueFalhamDepoisDoPrimeiro(dict):
    def items(self):
        for item in super().items():
            yield item
            raise RuntimeError(f"falha tardia com {SEGREDO_BRUTO}")


def test_falha_tardia_de_apresentacao_substitui_todo_o_prefixo_renderizado() -> None:
    resultado = _resultado_concluido()
    resultado.entradas_por_aplicacao = _ItensQueFalhamDepoisDoPrimeiro(
        resultado.entradas_por_aplicacao
    )

    linhas = list(iterar_linhas_resultado(resultado))
    saida = renderizar_resultado(resultado)

    assert linhas == [MENSAGEM_FALHA_APRESENTACAO]
    assert saida == MENSAGEM_FALHA_APRESENTACAO
    assert "Resultado da análise" not in saida
    assert "evento VPL" not in saida
    assert SEGREDO_BRUTO not in saida
