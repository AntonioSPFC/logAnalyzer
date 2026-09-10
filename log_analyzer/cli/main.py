"""Ponto de entrada seguro da CLI do Analisador de Logs.

A sintaxe posicional da Fase 1 permanece inalterada::

    python -m log_analyzer <identificador> <app_id>:<caminho> [...]

A fronteira de saída nunca renderiza diretamente um ``ResultadoDeAnalise``
bruto. Resultados da Fase 2 já concluídos usam o iterador seguro; resultados do
fluxo legado são copiados para uma visão sanitizada antes da apresentação. O
payload completo é preparado antes de uma única chamada ao writer para impedir
prefixos parciais em falhas de sanitização ou renderização.

Requirements: 1.3, 14.1, 16.3, 16.4, 16.6
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import replace
from typing import NoReturn, TextIO

from log_analyzer.cli.apresentacao import (
    MENSAGEM_FALHA_APRESENTACAO,
    iterar_linhas_resultado,
)
from log_analyzer.core.analisador import Analisador_de_Logs
from log_analyzer.core.bootstrap import criar_registro_padrao
from log_analyzer.core.excecoes import ErroDeIdentificador, ErroDeSanitizacao
from log_analyzer.core.modelos import (
    ArquivoSelecionado,
    EntradaDeLog,
    EstadoSanitizacao,
    ResultadoDeAnalise,
)
from log_analyzer.core.visao_segura import (
    MENSAGEM_FALHA_VISAO_SEGURA,
    criar_visao_segura,
)


CODIGO_SAIDA_SUCESSO = 0
CODIGO_SAIDA_ERRO = 1
MENSAGEM_IDENTIFICADOR_INVALIDO = "Erro: Identificador inválido."
MENSAGEM_FALHA_ANALISE = "Erro: não foi possível concluir a análise."

_USO = (
    "Uso: python -m log_analyzer <identificador> "
    "<app_id>:<caminho> [...]\n"
    "Exemplo: python -m log_analyzer 'call-123' "
    "VPL:logs/vpl.log ORK:logs/ork.log\n"
)
_MENSAGENS_DE_FALHA_DO_RENDERER = frozenset(
    {MENSAGEM_FALHA_APRESENTACAO, MENSAGEM_FALHA_VISAO_SEGURA}
)


class _FalhaDeApresentacao(Exception):
    """Sinal interno constante; nunca transporta conteúdo de origem."""


class _FalhaDeWriter(Exception):
    """Sinal interno constante para uma escrita não concluída."""


def _parsear_selecao(argumentos: Sequence[str]) -> list[ArquivoSelecionado]:
    """Preserva exatamente a associação posicional ``app_id:caminho``."""

    selecao: list[ArquivoSelecionado] = []
    for argumento in argumentos:
        if ":" in argumento:
            app_id, caminho = argumento.split(":", 1)
            selecao.append(ArquivoSelecionado(caminho=caminho, app_id=app_id))
        else:
            selecao.append(
                ArquivoSelecionado(caminho=argumento, app_id=None)
            )
    return selecao


def _adaptar_resultado_bruto(
    resultado: ResultadoDeAnalise,
) -> ResultadoDeAnalise:
    """Cria um envelope para sanitizar entradas legadas sem mudar o original.

    A visão segura preserva ``representacao_sanitizada=None`` em objetos
    puramente legados para o wrapper histórico da Fase 1. A CLI, porém, não
    pode atravessar essa fronteira bruta. Esta cópia marca o texto como fonte
    da representação; o sanitizador ainda é quem substitui todo dado sensível.

    Entradas legadas sem ``timestamp_normalizado`` são movidas para
    ``entradas_sem_ordenacao_temporal`` antes da construção do resultado
    adaptado, pois a atribuição de ``representacao_sanitizada`` ativa a
    validação da partição Fase 2 e essa partição exige UTC em
    ``linha_do_tempo``.
    """

    adaptadas: dict[int, EntradaDeLog] = {}

    def adaptar(entrada: EntradaDeLog) -> EntradaDeLog:
        if not isinstance(entrada, EntradaDeLog):
            raise ErroDeSanitizacao()
        chave = id(entrada)
        existente = adaptadas.get(chave)
        if existente is not None:
            return existente
        representacao = entrada.representacao_sanitizada
        if representacao is None:
            representacao = entrada.texto_original
            if not isinstance(representacao, str) or not representacao.strip():
                representacao = "Entrada sem representação disponível."
            entrada = replace(
                entrada,
                representacao_sanitizada=representacao,
            )
        adaptadas[chave] = entrada
        return entrada

    linha_do_tempo_adaptada: list[EntradaDeLog] = []
    sem_ordenacao_extra: list[EntradaDeLog] = []
    for entrada in resultado.linha_do_tempo:
        adaptada = adaptar(entrada)
        if adaptada.timestamp_normalizado is not None:
            linha_do_tempo_adaptada.append(adaptada)
        else:
            sem_ordenacao_extra.append(adaptada)

    return replace(
        resultado,
        entradas_por_aplicacao={
            aplicacao: [adaptar(entrada) for entrada in entradas]
            for aplicacao, entradas in resultado.entradas_por_aplicacao.items()
        },
        linha_do_tempo=linha_do_tempo_adaptada,
        entradas_sem_ordenacao_temporal=[
            adaptar(entrada)
            for entrada in resultado.entradas_sem_ordenacao_temporal
        ]
        + sem_ordenacao_extra,
    )


def _obter_visao_concluida(
    resultado: ResultadoDeAnalise,
) -> ResultadoDeAnalise:
    """Mantém a visão Fase 2 ou sanitiza uma cópia do resultado legado."""

    if not isinstance(resultado, ResultadoDeAnalise):
        raise ErroDeSanitizacao()
    if resultado.estado_sanitizacao is EstadoSanitizacao.CONCLUIDA:
        return resultado
    return criar_visao_segura(_adaptar_resultado_bruto(resultado))


def _preparar_payload_seguro(resultado: ResultadoDeAnalise) -> str:
    """Materializa o iterador seguro antes de atravessar a fronteira de I/O."""

    visao = _obter_visao_concluida(resultado)
    linhas = tuple(iterar_linhas_resultado(visao))
    if len(linhas) == 1 and linhas[0] in _MENSAGENS_DE_FALHA_DO_RENDERER:
        if linhas[0] == MENSAGEM_FALHA_VISAO_SEGURA:
            raise ErroDeSanitizacao()
        raise _FalhaDeApresentacao
    return "\n".join(linhas) + "\n"


def _posicao_para_rollback(destino: TextIO) -> int | None:
    """Obtém uma posição reversível sem exigir que stdout seja seekable."""

    try:
        if destino.seekable():
            return destino.tell()
    except Exception:
        return None
    return None


def _reverter_escrita(destino: TextIO, posicao: int | None) -> None:
    """Remove uma escrita parcial quando o writer oferece transação local."""

    if posicao is None:
        return
    try:
        destino.seek(posicao)
        destino.truncate()
    except Exception:
        # Streams de terminal e pipes normalmente não permitem rollback. Neles
        # a prevenção disponível é preparar tudo e fazer uma única escrita.
        pass


def _escrever_uma_vez(destino: TextIO, payload: str) -> None:
    """Entrega o payload em uma chamada e converte falhas sem detalhes brutos."""

    posicao = _posicao_para_rollback(destino)
    try:
        quantidade = destino.write(payload)
        if quantidade != len(payload):
            raise OSError
    except Exception:
        _reverter_escrita(destino, posicao)
        raise _FalhaDeWriter from None


def _emitir_mensagem_segura(destino: TextIO, mensagem: str) -> None:
    """Tenta emitir somente uma constante; falha do canal nunca gera traceback."""

    try:
        destino.write(f"{mensagem}\n")
    except Exception:
        pass


def _encerrar_com_erro(mensagem: str) -> NoReturn:
    _emitir_mensagem_segura(sys.stderr, mensagem)
    raise SystemExit(CODIGO_SAIDA_ERRO) from None


def main() -> None:
    """Analisa os argumentos posicionais e apresenta somente conteúdo seguro."""

    if len(sys.argv) < 3:
        try:
            _escrever_uma_vez(sys.stdout, _USO)
        except _FalhaDeWriter:
            _encerrar_com_erro(MENSAGEM_FALHA_APRESENTACAO)
        raise SystemExit(CODIGO_SAIDA_ERRO) from None

    identificador = sys.argv[1]
    selecao = _parsear_selecao(sys.argv[2:])

    try:
        registro = criar_registro_padrao()
        analisador = Analisador_de_Logs(registro)
        # A referência permanece viva e nunca é substituída ou alterada pela
        # visão sanitizada, inclusive se a escrita falhar.
        resultado_interno = analisador.analisar(selecao, identificador)
    except ErroDeIdentificador:
        _encerrar_com_erro(MENSAGEM_IDENTIFICADOR_INVALIDO)
    except ErroDeSanitizacao:
        _encerrar_com_erro(MENSAGEM_FALHA_VISAO_SEGURA)
    except Exception:
        _encerrar_com_erro(MENSAGEM_FALHA_ANALISE)

    try:
        payload = _preparar_payload_seguro(resultado_interno)
        _escrever_uma_vez(sys.stdout, payload)
    except ErroDeSanitizacao:
        _encerrar_com_erro(MENSAGEM_FALHA_VISAO_SEGURA)
    except (_FalhaDeApresentacao, _FalhaDeWriter):
        _encerrar_com_erro(MENSAGEM_FALHA_APRESENTACAO)
    except Exception:
        _encerrar_com_erro(MENSAGEM_FALHA_APRESENTACAO)


if __name__ == "__main__":
    main()
