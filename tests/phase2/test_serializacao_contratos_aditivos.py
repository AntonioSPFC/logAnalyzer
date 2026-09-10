"""Testes focados dos exports e da serialização aditiva da Fase 2.

Todos os valores são sintéticos; nenhuma fonte local de logs é consultada.

Validates: Requirements 1.3, 1.4, 1.5, 16.1, 16.2, 16.3.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

import log_analyzer.core as core
from log_analyzer.core.excecoes import (
    ErroDeCatalogo,
    ErroDeDecodificacao,
    ErroDeIntegridadeDaFonte,
    ErroDeSanitizacao,
    ErroTemporal,
)
from log_analyzer.core.interfaces import Parser_de_Bloco, TipoInicio
from log_analyzer.core.modelos import (
    BaseCorrelacao,
    CampoEstruturado,
    Categoria,
    EntradaDeLog,
    EntradaIndexada,
    EstadoCausaRaiz,
    EstadoSanitizacao,
    Evidencia,
    FalhaDeEntrada,
    IdentificadorTecnico,
    Proveniencia,
    ReferenciaRegra,
    ReferenciaTextoOriginal,
    ResultadoCausaRaiz,
    ResultadoCorrelacao,
    ResultadoDeAnalise,
    TipoIdentificador,
    VinculoIdentificadores,
)
from log_analyzer.core.serializacao import (
    serializar_entrada_de_log,
    serializar_modelo,
    serializar_resultado_de_analise,
)


_EXPORTS_FASE1_EM_ORDEM = (
    "Analisador_de_Logs",
    "ArquivoSelecionado",
    "Categoria",
    "EntradaDeLog",
    "ErroDeArquivo",
    "ErroDeIdentificador",
    "ErroDeRegistro",
    "ErroDoAnalisador",
    "MensagemDeErro",
    "Padrao_de_Analise",
    "Parser_de_Aplicacao",
    "Registro_de_Aplicacoes",
    "ResultadoDeAnalise",
    "TAMANHO_MAXIMO_BYTES",
    "agrupar_por_aplicacao",
    "calcular_contagens",
    "carregar_arquivo",
    "correlacionar_vpl_ork",
    "criar_registro_padrao",
    "filtrar_por_identificador",
    "ordenar_linha_do_tempo",
    "validar_identificador",
)

_EXPORTS_ADITIVOS = {
    "BaseCorrelacao": BaseCorrelacao,
    "CampoEstruturado": CampoEstruturado,
    "EntradaIndexada": EntradaIndexada,
    "EstadoCausaRaiz": EstadoCausaRaiz,
    "EstadoSanitizacao": EstadoSanitizacao,
    "Evidencia": Evidencia,
    "FalhaDeEntrada": FalhaDeEntrada,
    "IdentificadorTecnico": IdentificadorTecnico,
    "Proveniencia": Proveniencia,
    "ReferenciaRegra": ReferenciaRegra,
    "ReferenciaTextoOriginal": ReferenciaTextoOriginal,
    "ResultadoCausaRaiz": ResultadoCausaRaiz,
    "ResultadoCorrelacao": ResultadoCorrelacao,
    "TipoIdentificador": TipoIdentificador,
    "VinculoIdentificadores": VinculoIdentificadores,
    "ErroDeCatalogo": ErroDeCatalogo,
    "ErroDeDecodificacao": ErroDeDecodificacao,
    "ErroDeIntegridadeDaFonte": ErroDeIntegridadeDaFonte,
    "ErroDeSanitizacao": ErroDeSanitizacao,
    "ErroTemporal": ErroTemporal,
    "Parser_de_Bloco": Parser_de_Bloco,
    "TipoInicio": TipoInicio,
    "serializar_entrada_de_log": serializar_entrada_de_log,
    "serializar_modelo": serializar_modelo,
    "serializar_resultado_de_analise": serializar_resultado_de_analise,
}

_CAMPOS_ENTRADA_FASE1 = (
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

_CAMPOS_RESULTADO_FASE1 = (
    "identificador",
    "entradas_por_aplicacao",
    "linha_do_tempo",
    "contagem_por_categoria",
    "contagem_por_aplicacao",
    "correlacao_encontrada",
    "erros",
    "mensagens",
)


@dataclass(frozen=True)
class _ContratoLegadoAindaEmMemoria:
    texto_original: str
    aplicacao: str
    categoria: Categoria


def test_exports_sao_apenas_adicionados_ao_prefixo_publico_da_fase1() -> None:
    assert tuple(core.__all__[: len(_EXPORTS_FASE1_EM_ORDEM)]) == (
        _EXPORTS_FASE1_EM_ORDEM
    )
    assert len(core.__all__) == len(set(core.__all__))

    for nome, objeto in _EXPORTS_ADITIVOS.items():
        assert nome in core.__all__
        assert getattr(core, nome) is objeto


def test_categoria_e_ids_de_aplicacao_permanecem_inalterados() -> None:
    assert [(item.name, item.value) for item in Categoria] == [
        ("SUCESSO", "sucesso"),
        ("ERRO", "erro"),
        ("NAO_CLASSIFICADA", "não classificada"),
    ]
    assert core.criar_registro_padrao().aplicacoes_suportadas() == (
        "VPL",
        "ORK",
        "VOCI",
    )


def test_serializacao_de_construcao_legada_preserva_prefixos_e_valores() -> None:
    instante = datetime(2030, 2, 3, 4, 5, 6, 7000)
    entrada = EntradaDeLog(
        "evento sintético",
        "VPL",
        7,
        True,
        instante,
        "INFO",
        "mensagem sintética",
        Categoria.SUCESSO,
        True,
    )
    resultado = ResultadoDeAnalise(
        "ID-SINTETICO-1",
        {"VPL": [entrada]},
        [entrada],
        {Categoria.SUCESSO: 1},
        {"VPL": 1},
        True,
        [],
        ["análise sintética concluída"],
    )

    entrada_serializada = serializar_entrada_de_log(entrada)
    resultado_serializado = serializar_resultado_de_analise(resultado)

    assert tuple(entrada_serializada)[:9] == _CAMPOS_ENTRADA_FASE1
    assert tuple(resultado_serializado)[:8] == _CAMPOS_RESULTADO_FASE1
    assert entrada_serializada["texto_original"] == "evento sintético"
    assert entrada_serializada["carimbo_de_tempo"] == "2030-02-03T04:05:06.007000"
    assert entrada_serializada["categoria"] == "sucesso"
    assert resultado_serializado["contagem_por_categoria"] == {"sucesso": 1}
    assert resultado_serializado["entradas_por_aplicacao"]["VPL"][0] == (
        entrada_serializada
    )
    assert json.loads(
        json.dumps(resultado_serializado, ensure_ascii=False)
    ) == resultado_serializado


def test_serializacao_aditiva_preserva_metadados_aninhados_e_utc() -> None:
    instante_utc = datetime(2030, 2, 3, 7, 5, 6, 7000, tzinfo=timezone.utc)
    proveniencia = Proveniencia(
        arquivo_token="<ARQUIVO_1>",
        entrada_id="entrada-sintetica-1",
        linha_inicial=1,
        linha_final=1,
        nome_campo="CallId",
        regra_extracao="regra-sintetica-v1",
    )
    campo = CampoEstruturado("CallId", "<CALL_ID_1>", proveniencia)
    identificador = IdentificadorTecnico(
        tipo=TipoIdentificador.CALL_ID,
        namespace_comparacao="chamada_externa",
        nome_campo="CallId",
        valor_original="<CALL_ID_1>",
        valor_normalizado="<call_id_1>",
        proveniencia=proveniencia,
    )
    entrada = EntradaDeLog(
        texto_original="evento sintético CallId=<CALL_ID_1>",
        aplicacao="VPL",
        ordem_de_leitura=0,
        interpretada=True,
        carimbo_de_tempo=instante_utc,
        nivel_de_severidade="INFO",
        mensagem="evento sintético CallId=<CALL_ID_1>",
        entrada_id="entrada-sintetica-1",
        arquivo_token="<ARQUIVO_1>",
        posicao_inicial=1,
        posicao_final=1,
        timestamp_original="2030-02-03 04:05:06.007",
        timestamp_normalizado=instante_utc,
        precisao_fracionaria=3,
        campos_estruturados=(campo,),
        identificadores=(identificador,),
    )
    resultado = ResultadoDeAnalise(
        identificador="<CALL_ID_1>",
        entradas_por_aplicacao={"VPL": [entrada]},
        linha_do_tempo=[entrada],
        contagem_por_categoria={Categoria.NAO_CLASSIFICADA: 1},
        contagem_por_aplicacao={"VPL": 1},
        identificadores_extraidos=[identificador],
        aplicacoes_analisadas=["VPL"],
    )

    serializado = serializar_resultado_de_analise(resultado)

    entrada_serializada = serializado["linha_do_tempo"][0]
    assert entrada_serializada["timestamp_original"] == (
        "2030-02-03 04:05:06.007"
    )
    assert entrada_serializada["timestamp_normalizado"] == (
        "2030-02-03T07:05:06.007000+00:00"
    )
    assert entrada_serializada["campos_estruturados"][0] == {
        "nome": "CallId",
        "valor_original": "<CALL_ID_1>",
        "proveniencia": serializar_modelo(proveniencia),
    }
    assert serializado["identificadores_extraidos"][0]["tipo"] == "call_id"
    assert serializado["categoria_de_cenario"] == "não classificada"
    assert serializado["estado_sanitizacao"] == "interna_bruta"
    assert json.loads(json.dumps(serializado, ensure_ascii=False)) == serializado


def test_serializador_aceita_dataclass_legado_sem_injetar_campos_novos() -> None:
    legado = _ContratoLegadoAindaEmMemoria(
        texto_original="evento legado sintético",
        aplicacao="VOCI",
        categoria=Categoria.NAO_CLASSIFICADA,
    )

    assert serializar_modelo(legado) == {
        "texto_original": "evento legado sintético",
        "aplicacao": "VOCI",
        "categoria": "não classificada",
    }


def test_serializador_rejeita_coercao_silenciosa_de_tipo_desconhecido() -> None:
    with pytest.raises(TypeError, match="Tipo não suportado"):
        serializar_modelo(object())
