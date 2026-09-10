"""Testes de reprodução da sanitização sobre padrões de logs reais.

Estes testes reproduzem, com amostras sintéticas montadas EM MEMÓRIA, os
padrões observados no dicionário inline do ORK real que causavam resíduos de
sanitização detectados pelo ``ScannerDeFixtures``:

* ``CallId``/``TelecomCallId`` repetidos e um ``CallId`` embutido em um token
  do tipo ``{SESS=<callid>.NUANCE_ADA_V1}``.
* Campos ``document``/``cpf`` rotulados com dígitos crus (CPF de 11 e CNPJ de
  14 dígitos).
* Tokens legítimos do sistema, em maiúsculas com ``_`` (``<PROCESSING_STARTED>``
  e ``state='<PROCESSING_ADA_V1>'``), que NÃO são dados sensíveis e não devem
  ser sinalizados como ``PLACEHOLDER_INVALIDO``.

O contrato é: após ``SanitizationContext().sanitizar_texto`` seguido de
``ScannerDeFixtures().inspecionar_texto``, o número de achados deve ser ZERO
para amostras de logs reais legítimos. Ao mesmo tempo, placeholders MALFORMADOS
de tipos conhecidos (ex.: ``<CALL_ID_0>``, ``<UUID>``) DEVEM continuar sendo
detectados, provando que a proteção da governança não foi enfraquecida.

Nenhum valor sensível persiste em disco: todas as amostras são sintéticas e
vivem apenas na memória de cada teste.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from log_analyzer.core.governanca import ScannerDeFixtures, _parece_placeholder
from log_analyzer.core.modelos import (
    CampoEstruturado,
    Categoria,
    EntradaDeLog,
    Evidencia,
    IdentificadorTecnico,
    Proveniencia,
    ResultadoDeAnalise,
    TipoIdentificador,
)
from log_analyzer.core.sanitizacao import SanitizationContext
from log_analyzer.core.serializacao import serializar_resultado_de_analise
from log_analyzer.core.visao_segura import (
    SanitizadorDeResultado,
    ScannerFinalDeResultado,
)


# CallId sintético com o mesmo formato hexadecimal observado no ORK real.
_CALL_ID = "001901eb3041a19d"
# CPF (11 dígitos) e CNPJ (14 dígitos) sintéticos.
_CPF = "39053344705"
_CNPJ = "11222333000181"


def _sanitizar_e_inspecionar(amostra: str) -> list[str]:
    """Sanitiza ``amostra`` e devolve os achados do scanner como strings.

    O mapa bruto é descartado antes da inspeção para garantir que apenas o
    texto sanitizado seja avaliado.
    """

    contexto = SanitizationContext()
    resultado = contexto.sanitizar_texto(amostra)
    contexto.descartar_mapa_bruto()
    achados = ScannerDeFixtures().inspecionar_texto(resultado)
    return [str(achado) for achado in achados]


def test_dicionario_inline_ork_real_sem_residuos() -> None:
    """Amostra imitando o dicionário inline do ORK real não deixa resíduos.

    Cobre CallId/TelecomCallId repetidos, um CallId embutido em token de estado,
    document/cpf rotulados com dígitos crus e tokens legítimos do sistema.
    """

    amostra = (
        "Processando: {"
        f"'CallId': '{_CALL_ID}', "
        f"'TelecomCallId': '{_CALL_ID}', "
        f"'langFileName': '{{SESS={_CALL_ID}.NUANCE_ADA_V1}}', "
        f"'document': '{_CNPJ}', "
        f"'cpf': '{_CPF}', "
        "'state': '<PROCESSING_ADA_V1>', "
        "'phase': '<PROCESSING_STARTED>'"
        "}"
    )

    achados = _sanitizar_e_inspecionar(amostra)

    assert achados == [], f"Resíduos inesperados: {achados}"


def test_callid_embutido_em_token_de_estado_sem_residuos() -> None:
    """CallId embutido em ``{SESS=<callid>.NUANCE_ADA_V1}`` é sanitizado."""

    amostra = f"langFileName='{{SESS={_CALL_ID}.NUANCE_ADA_V1}}'"

    achados = _sanitizar_e_inspecionar(amostra)

    assert achados == [], f"Resíduos inesperados: {achados}"


def test_documento_e_cpf_com_digitos_crus_sem_residuos() -> None:
    """Campos document/cpf com dígitos crus não deixam resíduos."""

    amostra = f"document='{_CNPJ}' cpf='{_CPF}'"

    achados = _sanitizar_e_inspecionar(amostra)

    assert achados == [], f"Resíduos inesperados: {achados}"


def test_tokens_legitimos_do_sistema_nao_sao_sinalizados() -> None:
    """Tokens de estado/modelo do sistema não geram PLACEHOLDER_INVALIDO."""

    amostra = "state='<PROCESSING_ADA_V1>' phase=<PROCESSING_STARTED>"

    achados = _sanitizar_e_inspecionar(amostra)

    assert achados == [], f"Resíduos inesperados: {achados}"


@pytest.mark.parametrize(
    "token_legitimo",
    [
        "<PROCESSING_STARTED>",
        "<PROCESSING_ADA_V1>",
        "<SESSAO_INICIADA>",
        "<FOO_BAR>",
        "<STATE_MACHINE_V2>",
    ],
)
def test_parece_placeholder_ignora_identificadores_do_sistema(
    token_legitimo: str,
) -> None:
    """A heurística não sinaliza identificadores genéricos em maiúsculas."""

    assert _parece_placeholder(token_legitimo) is False


@pytest.mark.parametrize(
    "token_malformado",
    [
        "<CALL_ID_>",
        "<CALL_ID_0>",
        "<CALL_ID_01>",
        "<UUID>",
        "<CALLID_1>",
        "<UUID_CANAL>",
        "<DOCUMENTO_0>",
    ],
)
def test_parece_placeholder_detecta_variacoes_tipadas_malformadas(
    token_malformado: str,
) -> None:
    """Variações malformadas de placeholders tipados continuam detectadas."""

    assert _parece_placeholder(token_malformado) is True


def test_scanner_detecta_placeholder_invalido_em_texto() -> None:
    """Via inspecionar_texto, placeholders tipados malformados são achados.

    Prova que a governança de fixtures não foi enfraquecida: uma fixture
    sintética contendo ``<CALL_ID_0>`` (índice inválido) e ``<UUID>`` (sem
    índice) ainda produz achados ``PLACEHOLDER_INVALIDO``.
    """

    fixture_sintetica = "id=<CALL_ID_0> canal=<UUID>"

    achados = ScannerDeFixtures().inspecionar_texto(
        fixture_sintetica,
        arquivo="fixture.txt",
    )
    tipos = {achado.tipo for achado in achados}

    assert "PLACEHOLDER_INVALIDO" in tipos, achados


# ---------------------------------------------------------------------------
# Resíduo 1: rótulos sensíveis cujo valor já foi redigido ([REDACTED])
# ---------------------------------------------------------------------------


def test_campos_rotulados_com_valor_redigido_sem_residuos() -> None:
    """Campos sensíveis com valor ``[REDACTED]`` não deixam resíduos.

    Um campo cujo valor já foi substituído pelo marcador de redação não é dado
    sensível real. O scanner de governança deve tratar ``[REDACTED]`` como
    valor neutro, em simetria com o ``SanitizationContext``. Reproduz o padrão
    observado no ORK real (``'cpf': '[REDACTED]'`` e variantes) que fazia o
    scanner sinalizar um falso ``DOCUMENTO``.
    """

    amostra = (
        "'cpf': '[REDACTED]', "
        "'document': '[REDACTED]', "
        "'documento': '[REDACTED]', "
        "'cnpj': '[REDACTED]', "
        "'email': '[REDACTED]', "
        "'phone': '[REDACTED]', "
        "'token': '[REDACTED]', "
        "'CustomerId': '[REDACTED]'"
    )

    contexto = SanitizationContext()
    sanitizado = contexto.sanitizar_texto(amostra)
    contexto.descartar_mapa_bruto()
    achados = [str(a) for a in ScannerDeFixtures().inspecionar_texto(sanitizado)]

    assert achados == [], f"Resíduos inesperados: {achados}"


@pytest.mark.parametrize(
    "valor_redigido",
    ["'[REDACTED]'", "[REDACTED]", "'redacted'", "redacted", "'[redacted]'"],
)
def test_documento_redigido_nao_e_sinalizado(valor_redigido: str) -> None:
    """Variantes do marcador de redação em campo ``cpf`` não geram achado."""

    amostra = f"cpf={valor_redigido}"

    achados = ScannerDeFixtures().inspecionar_texto(amostra, arquivo="f.txt")

    assert achados == (), f"Marcador redigido foi sinalizado: {achados}"


def test_documento_com_valor_real_continua_sinalizado() -> None:
    """Fail-closed preservado: um CPF cru rotulado ainda produz achado.

    Garante que ampliar os valores neutros para incluir ``[redacted]`` não
    enfraqueceu a detecção de dados sensíveis reais.
    """

    amostra = f"cpf='{_CPF}' document='{_CNPJ}'"

    achados = ScannerDeFixtures().inspecionar_texto(amostra, arquivo="f.txt")
    tipos = {a.tipo for a in achados}

    assert "DOCUMENTO" in tipos, achados


# ---------------------------------------------------------------------------
# Resíduo 2: identificador do resultado sanitizado deve virar <CALL_ID_1>
# ---------------------------------------------------------------------------

_INSTANTE = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
_TIMESTAMP_ORIGINAL = "2025-01-01T09:00:00-03:00"


def _proveniencia(campo: str, entrada_id: str) -> Proveniencia:
    return Proveniencia(
        arquivo_token="<ARQUIVO_1>",
        entrada_id=entrada_id,
        linha_inicial=1,
        linha_final=1,
        nome_campo=campo,
        regra_extracao="extrator-sintetico-callid-v1",
    )


def _entrada_correlacionada(aplicacao: str, ordem: int) -> EntradaDeLog:
    """Entrada sintética portando o mesmo CallId em VPL e ORK."""

    texto = f"CallId={_CALL_ID}"
    entrada_id = f"entrada-{aplicacao.casefold()}-1"
    return EntradaDeLog(
        texto_original=texto,
        aplicacao=aplicacao,
        ordem_de_leitura=ordem,
        interpretada=True,
        carimbo_de_tempo=_INSTANTE,
        nivel_de_severidade="INFO",
        mensagem=texto,
        categoria=Categoria.NAO_CLASSIFICADA,
        entrada_id=entrada_id,
        arquivo_origem=f"C:/synth/{aplicacao.casefold()}.log",
        arquivo_token="<ARQUIVO_1>",
        posicao_inicial=1,
        posicao_final=1,
        timestamp_original=_TIMESTAMP_ORIGINAL,
        timestamp_normalizado=_INSTANTE,
        precisao_fracionaria=6,
        origem_evento="modulo.callid",
        formato_origem="perfil-sintetico",
        campos_estruturados=(
            CampoEstruturado("CallId", _CALL_ID, _proveniencia("CallId", entrada_id)),
        ),
        identificadores=(
            IdentificadorTecnico(
                tipo=TipoIdentificador.CALL_ID,
                namespace_comparacao="chamada_externa",
                nome_campo="CallId",
                valor_original=_CALL_ID,
                valor_normalizado=_CALL_ID.casefold(),
                proveniencia=_proveniencia("CallId", entrada_id),
            ),
        ),
    )


def _resultado_bruto_com_callid_hex() -> ResultadoDeAnalise:
    """Resultado bruto cujo identificador é o hex de 16 do ORK real."""

    vpl = _entrada_correlacionada("VPL", 0)
    ork = _entrada_correlacionada("ORK", 1)
    evidencia = Evidencia(
        tipo="campo_estruturado",
        aplicacao="VPL",
        proveniencia=_proveniencia("CallId", "entrada-vpl-1"),
        timestamp_original=_TIMESTAMP_ORIGINAL,
        timestamp_normalizado=_INSTANTE,
        campo_ou_condicao="CallId compartilhado VPL/ORK",
        representacao_sanitizada=f"CallId={_CALL_ID}",
    )
    return ResultadoDeAnalise(
        identificador=_CALL_ID,
        entradas_por_aplicacao={"VPL": [vpl], "ORK": [ork]},
        linha_do_tempo=[vpl, ork],
        contagem_por_categoria={Categoria.NAO_CLASSIFICADA: 2},
        contagem_por_aplicacao={"VPL": 1, "ORK": 1},
        identificadores_extraidos=[
            vpl.identificadores[0],
            ork.identificadores[0],
        ],
        evidencias=[evidencia],
        aplicacoes_analisadas=["VPL", "ORK"],
    )


def test_identificador_hex_vira_placeholder_callid_canonico() -> None:
    """A visão segura mapeia o hex de 16 do identificador para <CALL_ID_1>.

    Reproduz sinteticamente a consulta ``001901eb3041a19d`` com entradas
    VPL/ORK correlacionadas: o campo ``identificador`` do resultado sanitizado
    deve ser exatamente o placeholder canônico ``<CALL_ID_1>``, o scanner final
    não pode rejeitar a visão e o hex bruto não pode aparecer na superfície
    serializada.
    """

    bruto = _resultado_bruto_com_callid_hex()

    segura = SanitizadorDeResultado().criar_visao_segura(bruto)

    assert segura.identificador == "<CALL_ID_1>", segura.identificador

    # O scanner final não deve levantar sobre a visão segura.
    ScannerFinalDeResultado().validar(segura)

    serializada = json.dumps(
        serializar_resultado_de_analise(segura),
        ensure_ascii=False,
        sort_keys=True,
    )
    assert _CALL_ID not in serializada, "hex bruto vazou na superfície serializada"
    assert '"identificador": "<CALL_ID_1>"' in serializada or (
        '"identificador":"<CALL_ID_1>"' in serializada
    ), serializada


# ---------------------------------------------------------------------------
# Resíduo 3: call-ids OPACOS embutidos em texto livre sob rótulos não
# reconhecidos (ex.: id, tool_call_id, ai_type) no dicionário inline do ORK.
# O sanitizador não possuía detector opaco simétrico ao ``_CALL_ID_OPACO_RE``
# do scanner de governança, então tokens ``call_<...>``/``call-<...>``
# sobreviviam crus e o scanner final rejeitava a visão (fail-closed).
# ---------------------------------------------------------------------------

# Valores FORJADOS no mesmo formato revelado pelo diagnóstico (prefixo literal
# ``call``/``CALL`` mais sufixo opaco). Nenhum valor real é usado.
_CALL_OPACO_UNDERSCORE = "call_a1b2c3d4e5f6a7b8c9d0e1f2"
_CALL_OPACO_HIFEN = "call-9f8e7d6c5b4"
_CALLID_OPACO = "CALLID_ZX9Q7"
_SYN_CALL_OPACO = "SYN_CALL_1234abcd"


@pytest.mark.parametrize(
    "token_opaco",
    [
        _CALL_OPACO_UNDERSCORE,
        _CALL_OPACO_HIFEN,
        _CALLID_OPACO,
        _SYN_CALL_OPACO,
    ],
)
def test_call_id_opaco_em_texto_livre_sem_residuos(token_opaco: str) -> None:
    """Call-ids opacos em texto livre são substituídos por ``<CALL_ID_n>``.

    Reproduz os resíduos observados no ORK real: tokens ``call_<...>`` e
    ``call-<...>`` sob rótulos NÃO reconhecidos como call-id (``id``,
    ``tool_call_id``, ``ai_type``). Após ``sanitizar_texto`` seguido de
    ``inspecionar_texto`` o número de achados deve ser ZERO.
    """

    amostra = (
        "{'id': '" + token_opaco + "', "
        "'tool_call_id': '" + token_opaco + "', "
        "'ai_type': '" + token_opaco + "'}"
    )

    achados = _sanitizar_e_inspecionar(amostra)

    assert achados == [], f"Resíduos inesperados: {achados}"


def test_call_id_opaco_colado_a_outros_campos_sem_residuos() -> None:
    """Token opaco colado a estruturas serializadas também é sanitizado."""

    amostra = (
        "OpenAIObject(id='" + _CALL_OPACO_UNDERSCORE + "', "
        "op_type='7.0-a', model='gpt', tool_calls=[{'id': '"
        + _CALL_OPACO_UNDERSCORE + "'}])"
    )

    achados = _sanitizar_e_inspecionar(amostra)

    assert achados == [], f"Resíduos inesperados: {achados}"


def test_call_id_opaco_reusa_placeholder_estavel() -> None:
    """O mesmo call-id opaco recebe sempre o mesmo placeholder canônico."""

    contexto = SanitizationContext()
    sanitizado = contexto.sanitizar_texto(
        f"a={_CALL_OPACO_UNDERSCORE} b={_CALL_OPACO_UNDERSCORE}"
    )
    contexto.descartar_mapa_bruto()

    assert _CALL_OPACO_UNDERSCORE not in sanitizado
    assert sanitizado.count("<CALL_ID_1>") == 2, sanitizado


def test_fail_closed_para_call_id_opaco_nao_sanitizado() -> None:
    """Fail-closed preservado: um call-id opaco CRU ainda é sinalizado.

    Prova que o scanner de governança continua detectando o resíduo quando o
    valor NÃO passa pela sanitização (defesa em profundidade intacta). Se essa
    detecção fosse relaxada, a visão segura poderia vazar o valor bruto.
    """

    fixture_crua = f"id='{_CALL_OPACO_UNDERSCORE}' tool_call_id='{_CALL_OPACO_HIFEN}'"

    achados = ScannerDeFixtures().inspecionar_texto(
        fixture_crua, arquivo="fixture.txt"
    )
    tipos = {achado.tipo for achado in achados}

    assert "CALL_ID" in tipos, achados
