"""Carregamento tolerante de estágios definidos em arquivos de fluxo Studio.

Um arquivo de fluxo Studio é um JSON cujo objeto raiz possui a chave ``flows``
(lista). O flow de estágios é aquele com ``name == "Stages Module"`` (ou, na
ausência dele, o primeiro flow cujo ``type`` seja diferente de ``"start"``).
Cada node desse flow define um estágio.

O objetivo deste módulo é expor TODOS os estágios DEFINIDOS no fluxo (não apenas
os executados durante uma chamada), preservando a ordem em que aparecem no JSON.

A função pública :func:`carregar_estagios` é intencionalmente tolerante a erros:
qualquer falha de leitura/parsing resulta em uma lista vazia, garantindo que uma
seleção de arquivo inválida nunca quebre a análise da chamada.
"""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass
class EstagioFluxo:
    """Um estágio definido no fluxo Studio.

    Attributes:
        name: Nome do estágio (ex.: ``negociacao_da_divida``).
        versao: Versão/rótulo do prompt, quando disponível (ex.: ``Curadoria_V10``).
        instruction: Texto do prompt do estágio, quando disponível.
    """

    name: str
    versao: str | None
    instruction: str | None


def _encontrar_flow_de_estagios(flows):
    """Localiza o flow de estágios dentro da lista ``flows``.

    Primeiro tenta pelo nome ``"Stages Module"``; se não encontrar, usa o
    primeiro flow cujo ``type`` seja diferente de ``"start"``. Retorna ``None``
    quando nenhum candidato é encontrado.
    """
    for flow in flows:
        if isinstance(flow, dict) and flow.get('name') == 'Stages Module':
            return flow
    for flow in flows:
        if isinstance(flow, dict) and flow.get('type') != 'start':
            return flow
    return None


def _extrair_estagio(node):
    """Constrói um :class:`EstagioFluxo` a partir de um node do flow.

    Retorna ``None`` quando o node não possui ``name`` (nodes sem nome são
    ignorados).
    """
    name = node.get('name')
    if not name:
        return None

    prompt_text = node.get('promptText')
    if isinstance(prompt_text, dict):
        instruction = prompt_text.get('instruction')
        versao = (
            prompt_text.get('name')
            or prompt_text.get('value')
            or prompt_text.get('label')
        )
    elif isinstance(prompt_text, str) and prompt_text.strip():
        instruction = prompt_text
        versao = None
    else:
        instruction = None
        versao = None

    return EstagioFluxo(name=name, versao=versao, instruction=instruction)


def carregar_estagios(caminho_json: str) -> list[EstagioFluxo]:
    """Carrega os estágios definidos em um arquivo de fluxo Studio JSON.

    Args:
        caminho_json: Caminho para o arquivo JSON do fluxo Studio.

    Returns:
        Lista de :class:`EstagioFluxo` na ordem em que os nodes aparecem no
        flow de estágios. Retorna ``[]`` em qualquer situação de erro (arquivo
        inexistente, JSON inválido, estrutura inesperada).
    """
    try:
        with open(caminho_json, encoding='utf-8') as arquivo:
            dados = json.load(arquivo)

        flows = dados['flows']
        flow = _encontrar_flow_de_estagios(flows)
        if flow is None:
            return []

        estagios = []
        for node in flow['nodes']:
            if not isinstance(node, dict):
                continue
            estagio = _extrair_estagio(node)
            if estagio is not None:
                estagios.append(estagio)
        return estagios
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return []
