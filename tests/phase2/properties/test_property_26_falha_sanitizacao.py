"""Property 26: falhas de sanitização são atômicas e não vazam dados.

Todos os segredos são sintéticos e gerados em memória. Cada exemplo injeta
falhas nas fronteiras suportadas de snapshot, criação do contexto, etapa
estruturada, etapa textual, scanner final e descarte do contexto.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import logging

from hypothesis import given, settings
import pytest

from log_analyzer.core.excecoes import ErroDeSanitizacao
from log_analyzer.core.modelos import (
    Categoria,
    EntradaDeLog,
    EstadoSanitizacao,
    MensagemDeErro,
    ResultadoDeAnalise,
    TipoIdentificador,
)
from log_analyzer.core.sanitizacao import (
    SanitizationContext,
    TipoDadoSensivel,
)
from log_analyzer.core.serializacao import serializar_resultado_de_analise
from log_analyzer.core.visao_segura import (
    CODIGO_FALHA_VISAO_SEGURA,
    MENSAGEM_FALHA_VISAO_SEGURA,
    SanitizadorDeResultado,
)
from tests.phase2.strategies.fields import opaque_values


_ETAPAS_SUPORTADAS = (
    "snapshot",
    "fabrica-contexto",
    "estrutura",
    "texto",
    "scanner-final",
    "descarte",
)
_CAMPOS_MUTAVEIS = (
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

_CALL_IDS = opaque_values("CALL", min_bytes=8, max_bytes=16)
_CREDENCIAIS = opaque_values("TEST_CREDENTIAL", min_bytes=8, max_bytes=16)
_DADOS_CLIENTE = opaque_values("CUSTOMER", min_bytes=8, max_bytes=16)
_SEGREDOS_DE_FALHA = opaque_values("FAILURE_SECRET", min_bytes=8, max_bytes=16)


class _FalhaInjetada(RuntimeError):
    """Falha de teste cujo texto jamais deve atravessar a API segura."""


class _ColecaoComFalhaControlada(list[str]):
    """Permite falhar durante o snapshot e ser inspecionada depois."""

    def __init__(self, mensagem: str, segredo: str) -> None:
        super().__init__([mensagem])
        self.segredo = segredo
        self.falha_ativa = False

    def __iter__(self) -> Iterator[str]:
        if self.falha_ativa:
            raise _FalhaInjetada(self.segredo)
        return super().__iter__()

    def __repr__(self) -> str:
        return "<colecao-sintetica-com-falha-controlada>"


class _FabricaComFalha:
    def __init__(self, segredo: str) -> None:
        self.segredo = segredo

    def __call__(self) -> SanitizationContext:
        raise _FalhaInjetada(self.segredo)


class _ContextoComFalhaEstruturada(SanitizationContext):
    __slots__ = ("_segredo_teste",)

    def __init__(self, segredo: str) -> None:
        super().__init__()
        self._segredo_teste = segredo

    def placeholder_para(
        self,
        tipo: TipoDadoSensivel | TipoIdentificador | str,
        valor: str,
        *,
        valor_normalizado: str | None = None,
    ) -> str:
        raise _FalhaInjetada(self._segredo_teste)


class _ContextoComFalhaTextual(SanitizationContext):
    __slots__ = ("_segredo_teste",)

    def __init__(self, segredo: str) -> None:
        super().__init__()
        self._segredo_teste = segredo

    def sanitizar_texto(self, texto: str) -> str:
        raise _FalhaInjetada(self._segredo_teste)


class _ContextoComFalhaNoDescarte(SanitizationContext):
    __slots__ = ("_segredo_teste",)

    def __init__(self, segredo: str) -> None:
        super().__init__()
        self._segredo_teste = segredo

    def descartar_mapa_bruto(self) -> None:
        super().descartar_mapa_bruto()
        raise _FalhaInjetada(self._segredo_teste)


class _ScannerFinalComFalha:
    def __init__(self, segredo: str) -> None:
        self.segredo = segredo

    def validar(self, resultado: ResultadoDeAnalise) -> None:
        raise _FalhaInjetada(self.segredo)


def _criar_resultado_sensivel(
    call_id: str,
    credencial: str,
    dado_cliente: str,
) -> tuple[ResultadoDeAnalise, EntradaDeLog, MensagemDeErro, str, str]:
    texto_bruto = (
        f"CallId={call_id} token={credencial} customer_data={dado_cliente}"
    )
    origem_bruta = f"C:/synthetic-input/{call_id}.txt"
    entrada = EntradaDeLog(
        texto_original=texto_bruto,
        aplicacao="VPL",
        ordem_de_leitura=0,
        interpretada=False,
    )
    erro = MensagemDeErro(
        arquivo_ou_app=origem_bruta,
        descricao=f"falha sintética token={credencial}",
    )
    resultado = ResultadoDeAnalise(
        identificador=call_id,
        entradas_por_aplicacao={"VPL": [entrada]},
        linha_do_tempo=[entrada],
        contagem_por_categoria={Categoria.NAO_CLASSIFICADA: 1},
        contagem_por_aplicacao={"VPL": 1},
        erros=[erro],
        mensagens=[f"customer_data={dado_cliente}"],
    )
    return resultado, entrada, erro, texto_bruto, origem_bruta


def _preparar_falha(
    etapa: str,
    resultado: ResultadoDeAnalise,
    segredo: str,
) -> tuple[SanitizadorDeResultado, _ColecaoComFalhaControlada | None]:
    colecao: _ColecaoComFalhaControlada | None = None
    if etapa == "snapshot":
        colecao = _ColecaoComFalhaControlada(resultado.mensagens[0], segredo)
        resultado.mensagens = colecao
        sanitizador = SanitizadorDeResultado()
    elif etapa == "fabrica-contexto":
        sanitizador = SanitizadorDeResultado(
            fabrica_contexto=_FabricaComFalha(segredo)
        )
    elif etapa == "estrutura":
        sanitizador = SanitizadorDeResultado(
            fabrica_contexto=lambda: _ContextoComFalhaEstruturada(segredo)
        )
    elif etapa == "texto":
        sanitizador = SanitizadorDeResultado(
            fabrica_contexto=lambda: _ContextoComFalhaTextual(segredo)
        )
    elif etapa == "scanner-final":
        sanitizador = SanitizadorDeResultado(
            scanner_final=_ScannerFinalComFalha(segredo)
        )
    elif etapa == "descarte":
        sanitizador = SanitizadorDeResultado(
            fabrica_contexto=lambda: _ContextoComFalhaNoDescarte(segredo)
        )
    else:
        raise AssertionError("etapa de teste desconhecida")
    return sanitizador, colecao


# Feature: log-analyzer-phase-2, Property 26: Falha de sanitização não vaza conteúdo
@given(
    call_id=_CALL_IDS,
    credencial=_CREDENCIAIS,
    dado_cliente=_DADOS_CLIENTE,
    segredo_da_falha=_SEGREDOS_DE_FALHA,
)
@settings(max_examples=100)
def test_property_26_falha_de_sanitizacao_nao_vaza_conteudo(
    call_id: str,
    credencial: str,
    dado_cliente: str,
    segredo_da_falha: str,
) -> None:
    """Toda fronteira falha fechada sem alterar o resultado bruto.

    **Validates: Requirements 14.7, 16.6**
    """

    for etapa in _ETAPAS_SUPORTADAS:
        resultado, entrada, erro_interno, texto_bruto, origem_bruta = (
            _criar_resultado_sensivel(call_id, credencial, dado_cliente)
        )
        sanitizador, colecao_controlada = _preparar_falha(
            etapa,
            resultado,
            segredo_da_falha,
        )
        snapshot = serializar_resultado_de_analise(resultado)
        referencias_mutaveis = {
            campo: getattr(resultado, campo) for campo in _CAMPOS_MUTAVEIS
        }
        entradas_vpl = resultado.entradas_por_aplicacao["VPL"]

        if colecao_controlada is not None:
            colecao_controlada.falha_ativa = True

        stdout = StringIO()
        stderr = StringIO()
        logs = StringIO()
        handler = logging.StreamHandler(logs)
        logger_raiz = logging.getLogger()
        logger_raiz.addHandler(handler)
        try:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                with pytest.raises(ErroDeSanitizacao) as exc_info:
                    sanitizador.criar_visao_segura(resultado)
        finally:
            logger_raiz.removeHandler(handler)
            handler.flush()
            handler.close()

        erro_publico = exc_info.value
        assert type(erro_publico) is ErroDeSanitizacao
        assert erro_publico.codigo == CODIGO_FALHA_VISAO_SEGURA
        assert erro_publico.mensagem == MENSAGEM_FALHA_VISAO_SEGURA
        assert str(erro_publico) == MENSAGEM_FALHA_VISAO_SEGURA
        assert erro_publico.args == (MENSAGEM_FALHA_VISAO_SEGURA,)
        assert erro_publico.contexto == {
            "codigo": CODIGO_FALHA_VISAO_SEGURA
        }
        assert erro_publico.arquivo_token is None
        assert erro_publico.posicao is None
        assert erro_publico.__cause__ is None
        assert erro_publico.__context__ is None

        assert stdout.getvalue() == ""
        assert stderr.getvalue() == ""
        assert logs.getvalue() == ""

        for campo, referencia in referencias_mutaveis.items():
            assert getattr(resultado, campo) is referencia
        assert resultado.entradas_por_aplicacao["VPL"] is entradas_vpl
        assert resultado.entradas_por_aplicacao["VPL"][0] is entrada
        assert resultado.linha_do_tempo[0] is entrada
        assert resultado.erros[0] is erro_interno
        assert resultado.estado_sanitizacao is EstadoSanitizacao.INTERNA_BRUTA
        assert resultado.identificador == call_id
        assert entrada.texto_original == texto_bruto
        assert erro_interno.arquivo_ou_app == origem_bruta
        assert erro_interno.descricao == f"falha sintética token={credencial}"

        if colecao_controlada is not None:
            assert colecao_controlada.falha_ativa
            colecao_controlada.falha_ativa = False
        try:
            assert serializar_resultado_de_analise(resultado) == snapshot
        finally:
            if colecao_controlada is not None:
                colecao_controlada.falha_ativa = True

        superficie_publica = "\n".join(
            (
                erro_publico.codigo,
                erro_publico.mensagem,
                str(erro_publico),
                repr(erro_publico),
                repr(erro_publico.contexto),
                repr(sanitizador),
                stdout.getvalue(),
                stderr.getvalue(),
                logs.getvalue(),
            )
        ).casefold()
        valores_sensiveis = (
            call_id,
            credencial,
            dado_cliente,
            segredo_da_falha,
            texto_bruto,
            origem_bruta,
            erro_interno.descricao,
        )
        for valor in valores_sensiveis:
            assert valor.casefold() not in superficie_publica
        for valor in (call_id, credencial, dado_cliente, segredo_da_falha):
            for inicio in range(len(valor) - 7):
                assert valor[inicio : inicio + 8].casefold() not in superficie_publica
