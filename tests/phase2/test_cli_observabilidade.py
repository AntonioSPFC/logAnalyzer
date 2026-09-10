"""Contratos unitários e integrados da CLI e da observabilidade segura.

Todos os valores deste módulo são sintéticos ou placeholders tipados.

Validates: Requirements 1.3, 13.6, 16.1, 16.2, 16.3, 16.4, 16.6.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import importlib
import logging
from io import StringIO
import sys
from types import ModuleType
from typing import Any
from unittest.mock import patch

import pytest

from log_analyzer.cli.apresentacao import (
    iterar_linhas_resultado,
    renderizar_resultado,
)
from log_analyzer.core.analisador import Analisador_de_Logs
from log_analyzer.core.modelos import (
    Categoria,
    EntradaDeLog,
    ReferenciaRegra,
    ResultadoDeAnalise,
)
from log_analyzer.core.visao_segura import criar_visao_segura


cli_main = importlib.import_module("log_analyzer.cli.main")

CONSULTA_SINTETICA = "consulta-sintetica-9001"
SEGREDO_SINTETICO = "token-sintetico-que-nao-pode-sair"
INSTANTE_UTC = datetime(2042, 5, 6, 12, 30, tzinfo=timezone.utc)

_LABELS_PERMITIDOS = frozenset(
    {
        "app",
        "categoria",
        "codigo",
        "etapa",
        "mecanismo",
        "tipo",
        "versao_catalogo",
    }
)
_LABELS_PROIBIDOS = frozenset(
    {
        "caminho",
        "documento",
        "evidencia",
        "host",
        "identificador",
        "mensagem",
        "telefone",
        "url",
        "uuid",
    }
)


def _entrada_sintetica() -> EntradaDeLog:
    return EntradaDeLog(
        texto_original=(
            "conteudo interno sintetico "
            f"Authorization: Bearer {SEGREDO_SINTETICO}"
        ),
        aplicacao="VPL",
        ordem_de_leitura=0,
        interpretada=True,
        carimbo_de_tempo=INSTANTE_UTC.replace(tzinfo=None),
        nivel_de_severidade="ERROR",
        mensagem=f"mensagem interna {SEGREDO_SINTETICO}",
        categoria=Categoria.ERRO,
        entrada_id="entrada-vpl-sintetica-1",
        arquivo_token="<ARQUIVO_VPL_1>",
        posicao_inicial=7,
        posicao_final=7,
        timestamp_original="2042-05-06T09:30:00-03:00",
        timestamp_normalizado=INSTANTE_UTC,
        precisao_fracionaria=0,
        representacao_sanitizada="evento VPL CallId=<CALL_ID_1>",
    )


def _resultado_interno() -> ResultadoDeAnalise:
    from log_analyzer.core.modelos import Evidencia, Proveniencia

    entrada = _entrada_sintetica()
    regra = ReferenciaRegra(
        rule_id="regra-sintetica-cli",
        versao=2,
        catalogo_versao="catalogo-sintetico-v2",
    )
    proveniencia = Proveniencia(
        arquivo_token="<ARQUIVO_VPL_1>",
        entrada_id="entrada-vpl-sintetica-1",
        linha_inicial=7,
        linha_final=7,
        nome_campo="CallId",
        regra_extracao="extrator-sintetico-v1",
    )
    evidencia = Evidencia(
        tipo="condicao_sintetica",
        aplicacao="VPL",
        proveniencia=proveniencia,
        timestamp_original=entrada.timestamp_original,
        timestamp_normalizado=entrada.timestamp_normalizado,
        campo_ou_condicao="CallId presente",
        representacao_sanitizada="CallId=<CALL_ID_1>",
    )
    return ResultadoDeAnalise(
        identificador="<CALL_ID_1>",
        entradas_por_aplicacao={"VPL": [entrada]},
        linha_do_tempo=[entrada],
        contagem_por_categoria={Categoria.ERRO: 1},
        contagem_por_aplicacao={"VPL": 1},
        mensagens=[
            f"Authorization: Bearer {SEGREDO_SINTETICO}",
        ],
        categoria_de_cenario=Categoria.SUCESSO,
        evidencias=[evidencia],
        regra_aplicada=regra,
        versao_catalogo=regra.catalogo_versao,
        aplicacoes_analisadas=["VPL"],
        aplicacoes_ausentes_ou_invalidas=["ORK"],
        cobertura_rotulada="1 cenário de sucesso; 0 cenários de erro",
    )


def _resultado_seguro() -> ResultadoDeAnalise:
    return criar_visao_segura(_resultado_interno())


def _carregar_observabilidade() -> ModuleType:
    """Carrega a dependência da tarefa 13.3 sem impedir a coleta da CLI."""

    try:
        return importlib.import_module("log_analyzer.core.observabilidade")
    except ModuleNotFoundError:
        pytest.fail(
            "A tarefa 13.3 não materializou "
            "log_analyzer/core/observabilidade.py",
            pytrace=False,
        )


def _atributo_publico(modulo: ModuleType, *nomes: str) -> Any:
    for nome in nomes:
        valor = getattr(modulo, nome, None)
        if valor is not None:
            return valor
    pytest.fail(
        "API de observabilidade incompleta; esperado um de: "
        + ", ".join(nomes),
        pytrace=False,
    )


def _validar_labels(modulo: ModuleType, labels: dict[str, str]) -> Any:
    validar = _atributo_publico(
        modulo,
        "validar_labels_metricas",
        "validar_labels",
    )
    assert callable(validar)
    return validar(labels)


def _registrar_evento_seguro(
    modulo: ModuleType,
    logger: logging.Logger,
    **campos: object,
) -> Any:
    registrar = getattr(modulo, "registrar_evento_seguro", None)
    if callable(registrar):
        return registrar(logger=logger, **campos)

    classe = _atributo_publico(modulo, "ObservabilidadeSegura")
    try:
        observabilidade = classe(logger=logger)
    except TypeError:
        observabilidade = classe(logger)
    metodo = _atributo_publico(
        observabilidade,
        "registrar_evento",
        "registrar_log",
    )
    assert callable(metodo)
    return metodo(**campos)


def test_cli_preserva_sintaxe_posicional_app_caminho_e_codigo_de_sucesso(
    capsys: pytest.CaptureFixture[str],
) -> None:
    resultado = _resultado_seguro()
    argumentos = (
        "VPL:fontes-sinteticas/vpl.log",
        "ORK:fontes-sinteticas/ork.log",
        "VOCI:fontes-sinteticas/voci.log",
    )
    chamada: dict[str, object] = {}

    def analisar(
        _self: Analisador_de_Logs,
        selecao: object,
        identificador: str,
    ) -> ResultadoDeAnalise:
        chamada["selecao"] = selecao
        chamada["identificador"] = identificador
        return resultado

    with (
        patch.object(
            sys,
            "argv",
            ["log_analyzer", CONSULTA_SINTETICA, *argumentos],
        ),
        patch.object(Analisador_de_Logs, "analisar", new=analisar),
    ):
        retorno = cli_main.main()

    capturado = capsys.readouterr()
    selecao = chamada["selecao"]
    assert retorno is None
    assert cli_main.CODIGO_SAIDA_SUCESSO == 0
    assert chamada["identificador"] == CONSULTA_SINTETICA
    assert [(item.app_id, item.caminho) for item in selecao] == [
        ("VPL", "fontes-sinteticas/vpl.log"),
        ("ORK", "fontes-sinteticas/ork.log"),
        ("VOCI", "fontes-sinteticas/voci.log"),
    ]
    assert "Resultado da análise para:" in capturado.out
    assert capturado.err == ""
    assert CONSULTA_SINTETICA not in capturado.out
    assert all(argumento not in capturado.out for argumento in argumentos)


def test_cli_argumentos_insuficientes_usam_codigo_de_erro_basico(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        patch.object(sys, "argv", ["log_analyzer"]),
        pytest.raises(SystemExit) as exc_info,
    ):
        cli_main.main()

    capturado = capsys.readouterr()
    assert cli_main.CODIGO_SAIDA_ERRO == 1
    assert exc_info.value.code == cli_main.CODIGO_SAIDA_ERRO
    assert capturado.out.startswith("Uso: python -m log_analyzer")
    assert capturado.err == ""


def test_iterador_wrapper_e_secoes_aditivas_preservam_secoes_legadas() -> None:
    resultado = _resultado_seguro()

    iterador = iterar_linhas_resultado(resultado)
    assert iter(iterador) is iterador
    linhas = list(iterador)
    saida = renderizar_resultado(resultado)

    assert saida == "\n".join(linhas)
    for trecho_legado in (
        "Resultado da análise para:",
        "[VPL] (1 entradas)",
        "Contagem por categoria:",
        "Contagem por aplicação:",
    ):
        assert trecho_legado in saida

    for secao_aditiva in (
        "Categoria do cenário: SUCESSO",
        "Versão do catálogo: catalogo-sintetico-v2",
        "Regra aplicada: regra-sintetica-cli v2",
        "Cobertura rotulada:",
        "Aplicações analisadas: VPL",
        "Aplicações ausentes ou inválidas: ORK",
        "Identificadores extraídos:",
        "Vínculos:",
        "Correlação: não encontrada",
        "Linha do tempo UTC:",
        "Entradas sem UTC:",
        "Evidências:",
        "Causa-raiz: não determinada",
    ):
        assert secao_aditiva in saida

    assert SEGREDO_SINTETICO not in saida


def test_categoria_de_cenario_nao_substitui_severidade_ou_categoria_da_entrada(
) -> None:
    saida = renderizar_resultado(_resultado_seguro())

    assert "Categoria do cenário: SUCESSO" in saida
    assert "Severidade de log: ERROR" in saida
    assert "Categoria da entrada: ERRO" in saida
    assert "Categoria do cenário: ERROR" not in saida
    assert "Severidade de log: SUCESSO" not in saida


def test_falha_do_writer_preserva_resultado_e_saida_atomica_constante(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class WriterSeekableQueFalha:
        def __init__(self) -> None:
            self.conteudo = "prefixo-seguro-existente\n"
            self.posicao = len(self.conteudo)

        def seekable(self) -> bool:
            return True

        def tell(self) -> int:
            return self.posicao

        def write(self, texto: str) -> int:
            parcial = texto[: max(1, len(texto) // 3)]
            self.conteudo += parcial
            self.posicao = len(self.conteudo)
            raise OSError(f"falha sintetica {SEGREDO_SINTETICO}")

        def seek(self, posicao: int) -> None:
            self.posicao = posicao

        def truncate(self) -> None:
            self.conteudo = self.conteudo[: self.posicao]

    resultado = _resultado_interno()
    snapshot = deepcopy(resultado)
    writer = WriterSeekableQueFalha()
    conteudo_inicial = writer.conteudo

    with (
        patch.object(
            sys,
            "argv",
            [
                "log_analyzer",
                CONSULTA_SINTETICA,
                "VPL:fonte-sintetica.log",
            ],
        ),
        patch.object(
            Analisador_de_Logs,
            "analisar",
            return_value=resultado,
        ),
        patch.object(cli_main.sys, "stdout", writer),
        pytest.raises(SystemExit) as exc_info,
    ):
        cli_main.main()

    capturado = capsys.readouterr()
    assert exc_info.value.code == cli_main.CODIGO_SAIDA_ERRO
    assert resultado == snapshot
    assert writer.conteudo == conteudo_inicial
    assert capturado.out == ""
    assert capturado.err == f"{cli_main.MENSAGEM_FALHA_APRESENTACAO}\n"
    assert SEGREDO_SINTETICO not in writer.conteudo + capturado.err
    assert CONSULTA_SINTETICA not in writer.conteudo + capturado.err


def test_observabilidade_declara_e_valida_labels_permitidos() -> None:
    modulo = _carregar_observabilidade()
    declarados = frozenset(
        _atributo_publico(
            modulo,
            "LABELS_METRICAS_PERMITIDOS",
            "LABELS_PERMITIDOS",
        )
    )
    labels = {
        "app": "VPL",
        "categoria": "NAO_CLASSIFICADA",
        "codigo": "PARSE_OK",
        "etapa": "parsing",
        "mecanismo": "campo_estruturado",
        "tipo": "linhas_processadas",
        "versao_catalogo": "catalogo-sintetico-v2",
    }

    assert _LABELS_PERMITIDOS <= declarados
    assert _validar_labels(modulo, labels) is not False


@pytest.mark.parametrize("label", sorted(_LABELS_PROIBIDOS))
def test_observabilidade_rejeita_label_proibido_sem_ecoa_lo(
    label: str,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    modulo = _carregar_observabilidade()
    declarados = frozenset(
        _atributo_publico(
            modulo,
            "LABELS_METRICAS_PROIBIDOS",
            "LABELS_PROIBIDOS",
        )
    )
    valor_bruto = f"valor-{label}-{SEGREDO_SINTETICO}"
    caplog.set_level(logging.DEBUG)

    assert label in declarados
    with pytest.raises(Exception) as exc_info:
        _validar_labels(modulo, {label: valor_bruto})

    capturado = capsys.readouterr()
    fronteiras = "\n".join(
        (
            capturado.out,
            capturado.err,
            caplog.text,
            str(exc_info.value),
        )
    )
    assert valor_bruto not in fronteiras
    assert SEGREDO_SINTETICO not in fronteiras


def test_debug_nao_habilita_bruto_e_falha_registra_somente_codigo() -> None:
    modulo = _carregar_observabilidade()
    fluxo = StringIO()
    logger = logging.getLogger("tests.phase2.observabilidade.sintetica")
    handler = logging.StreamHandler(fluxo)
    nivel_anterior = logger.level
    propagacao_anterior = logger.propagate
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    try:
        _registrar_evento_seguro(
            modulo,
            logger,
            nivel=logging.DEBUG,
            analysis_id="analysis-sintetica-1",
            arquivo_token="<ARQUIVO_VPL_1>",
            app="VPL",
            posicao=7,
            codigo="SOURCE_CHANGED",
        )
        try:
            _registrar_evento_seguro(
                modulo,
                logger,
                nivel=logging.DEBUG,
                analysis_id="analysis-sintetica-1",
                arquivo_token="<ARQUIVO_VPL_1>",
                app="VPL",
                posicao=7,
                codigo="SOURCE_CHANGED",
                mensagem=SEGREDO_SINTETICO,
            )
        except Exception as erro:
            assert SEGREDO_SINTETICO not in str(erro)
    finally:
        handler.flush()
        logger.removeHandler(handler)
        handler.close()
        logger.setLevel(nivel_anterior)
        logger.propagate = propagacao_anterior

    registro = fluxo.getvalue()
    assert "SOURCE_CHANGED" in registro
    assert "analysis-sintetica-1" in registro
    assert "<ARQUIVO_VPL_1>" in registro
    assert "VPL" in registro
    assert "7" in registro
    assert SEGREDO_SINTETICO not in registro
    assert "mensagem=" not in registro.casefold()
