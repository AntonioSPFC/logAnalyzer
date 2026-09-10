"""Caracterização dos contratos públicos legados da Fase 1.

Os testes deste módulo usam somente valores e arquivos temporários sintéticos. Eles
protegem o prefixo legado dos modelos para permitir extensões estritamente aditivas
na Fase 2 sem congelar a ausência de novos campos ou exports.

Validates: Requirements 1.3, 1.4, 1.5, 16.1, 16.5.
"""

from dataclasses import MISSING, FrozenInstanceError, fields, replace
from datetime import datetime
from inspect import Parameter, signature
from pathlib import Path
from typing import get_type_hints

import pytest

import log_analyzer.core as core
from log_analyzer.core.carregador import carregar_arquivo
from log_analyzer.core.correlacao import correlacionar_vpl_ork
from log_analyzer.core.filtro import filtrar_por_identificador
from log_analyzer.core.modelos import (
    Categoria,
    EntradaDeLog,
    MensagemDeErro,
    ResultadoDeAnalise,
)
from log_analyzer.core.ordenacao import ordenar_linha_do_tempo


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

_EXPORTS_CORE_FASE1 = {
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
}


def _entrada_nao_interpretada(
    texto: str, aplicacao: str, ordem: int
) -> EntradaDeLog:
    return EntradaDeLog(texto, aplicacao, ordem, False)


def test_categoria_preserva_nomes_valores_e_semantica_de_enum() -> None:
    assert [(membro.name, membro.value) for membro in Categoria] == [
        ("SUCESSO", "sucesso"),
        ("ERRO", "erro"),
        ("NAO_CLASSIFICADA", "não classificada"),
    ]
    assert Categoria("sucesso") is Categoria.SUCESSO
    assert Categoria("erro") is Categoria.ERRO
    assert Categoria("não classificada") is Categoria.NAO_CLASSIFICADA
    assert all(isinstance(membro.value, str) for membro in Categoria)


def test_entrada_de_log_preserva_prefixo_assinatura_tipos_e_defaults() -> None:
    parametros = list(signature(EntradaDeLog).parameters.values())
    campos = list(fields(EntradaDeLog))
    tipos = get_type_hints(EntradaDeLog)

    assert tuple(parametro.name for parametro in parametros[:9]) == _CAMPOS_ENTRADA_FASE1
    assert tuple(campo.name for campo in campos[:9]) == _CAMPOS_ENTRADA_FASE1
    assert all(
        parametro.kind is Parameter.POSITIONAL_OR_KEYWORD
        for parametro in parametros[:9]
    )
    assert EntradaDeLog.__dataclass_params__.frozen is True

    assert {nome: tipos[nome] for nome in _CAMPOS_ENTRADA_FASE1} == {
        "texto_original": str,
        "aplicacao": str,
        "ordem_de_leitura": int,
        "interpretada": bool,
        "carimbo_de_tempo": datetime | None,
        "nivel_de_severidade": str | None,
        "mensagem": str | None,
        "categoria": Categoria,
        "correlacionada": bool,
    }

    por_nome = {campo.name: campo for campo in campos}
    for nome in _CAMPOS_ENTRADA_FASE1[:4]:
        assert por_nome[nome].default is MISSING
        assert por_nome[nome].default_factory is MISSING

    assert por_nome["carimbo_de_tempo"].default is None
    assert por_nome["nivel_de_severidade"].default is None
    assert por_nome["mensagem"].default is None
    assert por_nome["categoria"].default is Categoria.NAO_CLASSIFICADA
    assert por_nome["correlacionada"].default is False


def test_entrada_de_log_aceita_construcao_posicional_e_por_palavras_chave() -> None:
    instante = datetime(2024, 2, 3, 4, 5, 6)
    posicional = EntradaDeLog(
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

    assert tuple(getattr(posicional, nome) for nome in _CAMPOS_ENTRADA_FASE1) == (
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

    por_palavras_chave = EntradaDeLog(
        texto_original="entrada não interpretada",
        aplicacao="ORK",
        ordem_de_leitura=11,
        interpretada=False,
    )
    assert por_palavras_chave.carimbo_de_tempo is None
    assert por_palavras_chave.nivel_de_severidade is None
    assert por_palavras_chave.mensagem is None
    assert por_palavras_chave.categoria is Categoria.NAO_CLASSIFICADA
    assert por_palavras_chave.correlacionada is False

    with pytest.raises(FrozenInstanceError):
        por_palavras_chave.mensagem = "alterada"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("campo_invalido", "valor_invalido"),
    [
        ("carimbo_de_tempo", None),
        ("nivel_de_severidade", ""),
        ("mensagem", ""),
    ],
)
def test_entrada_interpretada_preserva_invariante_da_fase1(
    campo_invalido: str, valor_invalido: object
) -> None:
    argumentos: dict[str, object] = {
        "texto_original": "evento sintético",
        "aplicacao": "VOCI",
        "ordem_de_leitura": 0,
        "interpretada": True,
        "carimbo_de_tempo": datetime(2024, 1, 1),
        "nivel_de_severidade": "INFO",
        "mensagem": "mensagem",
    }
    argumentos[campo_invalido] = valor_invalido

    with pytest.raises(ValueError, match=campo_invalido):
        EntradaDeLog(**argumentos)  # type: ignore[arg-type]


def test_resultado_preserva_prefixo_assinatura_tipos_e_defaults() -> None:
    parametros = list(signature(ResultadoDeAnalise).parameters.values())
    campos = list(fields(ResultadoDeAnalise))
    tipos = get_type_hints(ResultadoDeAnalise)

    assert tuple(parametro.name for parametro in parametros[:8]) == _CAMPOS_RESULTADO_FASE1
    assert tuple(campo.name for campo in campos[:8]) == _CAMPOS_RESULTADO_FASE1
    assert all(
        parametro.kind is Parameter.POSITIONAL_OR_KEYWORD
        for parametro in parametros[:8]
    )
    assert ResultadoDeAnalise.__dataclass_params__.frozen is False

    assert {nome: tipos[nome] for nome in _CAMPOS_RESULTADO_FASE1} == {
        "identificador": str,
        "entradas_por_aplicacao": dict[str, list[EntradaDeLog]],
        "linha_do_tempo": list[EntradaDeLog],
        "contagem_por_categoria": dict[Categoria, int],
        "contagem_por_aplicacao": dict[str, int],
        "correlacao_encontrada": bool,
        "erros": list[MensagemDeErro],
        "mensagens": list[str],
    }

    por_nome = {campo.name: campo for campo in campos}
    assert por_nome["identificador"].default is MISSING
    assert por_nome["entradas_por_aplicacao"].default_factory is dict
    assert por_nome["linha_do_tempo"].default_factory is list
    assert por_nome["contagem_por_categoria"].default_factory is dict
    assert por_nome["contagem_por_aplicacao"].default_factory is dict
    assert por_nome["correlacao_encontrada"].default is False
    assert por_nome["erros"].default_factory is list
    assert por_nome["mensagens"].default_factory is list


def test_resultado_aceita_construcao_posicional_e_defaults_independentes() -> None:
    entrada = _entrada_nao_interpretada("evento sintético", "VPL", 0)
    entradas_por_app = {"VPL": [entrada]}
    linha_do_tempo = [entrada]
    contagem_categoria = {Categoria.NAO_CLASSIFICADA: 1}
    contagem_app = {"VPL": 1}
    erros = [MensagemDeErro("ORK", "fonte sintética ausente")]
    mensagens = ["análise sintética concluída"]

    posicional = ResultadoDeAnalise(
        "ID-SINTETICO-1",
        entradas_por_app,
        linha_do_tempo,
        contagem_categoria,
        contagem_app,
        True,
        erros,
        mensagens,
    )

    assert posicional.identificador == "ID-SINTETICO-1"
    assert posicional.entradas_por_aplicacao is entradas_por_app
    assert posicional.linha_do_tempo is linha_do_tempo
    assert posicional.contagem_por_categoria is contagem_categoria
    assert posicional.contagem_por_aplicacao is contagem_app
    assert posicional.correlacao_encontrada is True
    assert posicional.erros is erros
    assert posicional.mensagens is mensagens

    primeiro = ResultadoDeAnalise(identificador="ID-SINTETICO-2")
    segundo = ResultadoDeAnalise(identificador="ID-SINTETICO-3")
    for nome in (
        "entradas_por_aplicacao",
        "linha_do_tempo",
        "contagem_por_categoria",
        "contagem_por_aplicacao",
        "erros",
        "mensagens",
    ):
        assert getattr(primeiro, nome) == getattr(segundo, nome)
        assert getattr(primeiro, nome) is not getattr(segundo, nome)


def test_core_preserva_exports_publicos_da_fase1() -> None:
    assert _EXPORTS_CORE_FASE1 <= set(core.__all__)
    assert len(core.__all__) == len(set(core.__all__))
    assert all(hasattr(core, nome) for nome in _EXPORTS_CORE_FASE1)

    assert core.Categoria is Categoria
    assert core.EntradaDeLog is EntradaDeLog
    assert core.MensagemDeErro is MensagemDeErro
    assert core.ResultadoDeAnalise is ResultadoDeAnalise
    assert core.carregar_arquivo is carregar_arquivo
    assert core.filtrar_por_identificador is filtrar_por_identificador
    assert core.correlacionar_vpl_ork is correlacionar_vpl_ork
    assert core.ordenar_linha_do_tempo is ordenar_linha_do_tempo


@pytest.mark.parametrize(
    ("funcao", "parametros_esperados", "retorno_esperado"),
    [
        (
            carregar_arquivo,
            {"caminho": str},
            list[str] | MensagemDeErro,
        ),
        (
            filtrar_por_identificador,
            {"entradas": list[EntradaDeLog], "identificador": str},
            list[EntradaDeLog],
        ),
        (
            correlacionar_vpl_ork,
            {
                "entradas_vpl": list[EntradaDeLog],
                "entradas_ork": list[EntradaDeLog],
                "identificador": str,
            },
            tuple[
                list[EntradaDeLog],
                list[EntradaDeLog],
                bool,
                list[MensagemDeErro],
            ],
        ),
        (
            ordenar_linha_do_tempo,
            {"entradas": list[EntradaDeLog]},
            list[EntradaDeLog],
        ),
    ],
    ids=("carregar", "filtrar", "correlacionar", "ordenar"),
)
def test_wrappers_preservam_assinaturas_publicas(
    funcao: object,
    parametros_esperados: dict[str, object],
    retorno_esperado: object,
) -> None:
    assinatura = signature(funcao)
    tipos = get_type_hints(funcao)

    assert list(assinatura.parameters) == list(parametros_esperados)
    for nome, tipo_esperado in parametros_esperados.items():
        parametro = assinatura.parameters[nome]
        assert parametro.kind is Parameter.POSITIONAL_OR_KEYWORD
        assert parametro.default is Parameter.empty
        assert tipos[nome] == tipo_esperado
    assert tipos["return"] == retorno_esperado


def test_carregar_arquivo_preserva_retorno_e_semantica_legados(
    tmp_path: Path,
) -> None:
    arquivo = tmp_path / "entrada-sintetica.log"
    arquivo.write_bytes("primeira\r\n\r\nterceira com ação".encode("utf-8"))

    esperado = ["primeira", "", "terceira com ação"]
    assert carregar_arquivo(str(arquivo)) == esperado
    assert carregar_arquivo(str(arquivo)) == esperado

    ausente = tmp_path / "ausente.log"
    erro = carregar_arquivo(str(ausente))
    assert erro == MensagemDeErro(
        arquivo_ou_app=str(ausente),
        descricao="Arquivo não encontrado ou não é um arquivo regular.",
    )


def test_filtrar_por_identificador_preserva_substring_case_e_ordem() -> None:
    primeira = _entrada_nao_interpretada(
        "prefixo ID-SINTETICO-42 sufixo", "VPL", 0
    )
    ignorada = _entrada_nao_interpretada("outro evento", "ORK", 1)
    terceira = _entrada_nao_interpretada("id-sintetico-42 novamente", "VOCI", 2)
    entradas = [primeira, ignorada, terceira]
    snapshot = list(entradas)

    resultado = filtrar_por_identificador(entradas, "Id-Sintetico-42")

    assert resultado == [primeira, terceira]
    assert resultado[0] is primeira
    assert resultado[1] is terceira
    assert entradas == snapshot
    assert resultado is not entradas
    assert filtrar_por_identificador(entradas, "Id-Sintetico-42") == resultado
    # O wrapper isolado não valida consulta; a string vazia casa com todo texto.
    assert filtrar_por_identificador(entradas, "") == entradas


def test_correlacionar_preserva_semantica_de_listas_pre_filtradas() -> None:
    entrada_vpl = _entrada_nao_interpretada("evento VPL sem a consulta", "VPL", 0)
    entrada_ork = _entrada_nao_interpretada("evento ORK sem a consulta", "ORK", 0)
    entradas_vpl = [entrada_vpl]
    entradas_ork = [entrada_ork]

    primeiro = correlacionar_vpl_ork(
        entradas_vpl, entradas_ork, "ID-SINTETICO-AUSENTE-DO-TEXTO"
    )
    segundo = correlacionar_vpl_ork(
        entradas_vpl, entradas_ork, "ID-SINTETICO-AUSENTE-DO-TEXTO"
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
    assert entrada_vpl.correlacionada is False
    assert entrada_ork.correlacionada is False


@pytest.mark.parametrize("lado_ausente", ["VPL", "ORK"])
def test_correlacionar_preserva_lado_disponivel_e_reporta_ausente(
    lado_ausente: str,
) -> None:
    identificador = "ID-SINTETICO-ERRO"
    disponivel = _entrada_nao_interpretada("evento sintético", "ORK", 0)
    entradas_vpl = [] if lado_ausente == "VPL" else [disponivel]
    entradas_ork = [disponivel] if lado_ausente == "VPL" else []

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

    assert correlacionar_vpl_ork([], [], identificador) == ([], [], False, [])


def test_ordenar_linha_do_tempo_preserva_chave_total_e_nao_muta_entrada() -> None:
    instante = datetime(2024, 4, 5, 10, 0, 0)
    anterior = EntradaDeLog(
        "evento anterior",
        "VPL",
        9,
        True,
        datetime(2024, 4, 5, 9, 59, 59),
        "INFO",
        "anterior",
    )
    ork_ordem_2 = EntradaDeLog(
        "evento ORK 2", "ORK", 2, True, instante, "DEBUG", "segundo"
    )
    ork_ordem_1 = EntradaDeLog(
        "evento ORK 1", "ORK", 1, True, instante, "DEBUG", "primeiro"
    )
    vpl = EntradaDeLog(
        "evento VPL", "VPL", 0, True, instante, "INFO", "terceiro"
    )
    sem_tempo_ork = _entrada_nao_interpretada("sem tempo ORK", "ORK", 4)
    sem_tempo_vpl = _entrada_nao_interpretada("sem tempo VPL", "VPL", 0)
    entradas = [
        sem_tempo_vpl,
        vpl,
        ork_ordem_2,
        anterior,
        sem_tempo_ork,
        ork_ordem_1,
    ]
    snapshot = list(entradas)
    esperado = [
        anterior,
        ork_ordem_1,
        ork_ordem_2,
        vpl,
        sem_tempo_ork,
        sem_tempo_vpl,
    ]

    primeiro = ordenar_linha_do_tempo(entradas)
    segundo = ordenar_linha_do_tempo(entradas)

    assert primeiro == esperado
    assert segundo == esperado
    assert entradas == snapshot
    assert primeiro is not entradas
