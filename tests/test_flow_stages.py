"""Testes de ``dashboard.flow_stages.carregar_estagios``.

Todos os dados são 100% sintéticos. Cobrem a extração correta de estágios (com
promptText dict e string), a ordem preservada, o descarte de nodes sem ``name``
e a tolerância a erros (arquivo inexistente, JSON inválido, JSON sem ``flows``).
"""

from __future__ import annotations

import json

import pytest

from dashboard.flow_stages import EstagioFluxo, carregar_estagios


def _fluxo_sintetico() -> dict:
    """Fluxo Studio sintético com dois flows.

    O flow "Main" é o ``start`` e deve ser ignorado. O flow "Stages Module"
    contém: um node com promptText dict completo, um node com promptText string
    curta, um node sem promptText, e um node SEM ``name`` (deve ser ignorado).
    """
    return {
        "flows": [
            {"name": "Main", "type": "start", "nodes": []},
            {
                "name": "Stages Module",
                "type": "other",
                "nodes": [
                    {
                        "name": "identificacao_do_cliente",
                        "promptText": {
                            "instruction": "Peça o CPF do cliente.",
                            "name": "Curadoria_V10",
                            "value": "v10-valor",
                            "label": "v10-label",
                        },
                    },
                    {
                        "name": "finalize",
                        "promptText": "placeholder curto",
                    },
                    {
                        "name": "flow_start",
                        "promptText": None,
                    },
                    {
                        # Sem 'name' -> deve ser ignorado.
                        "promptText": {"instruction": "sem nome"},
                    },
                ],
            },
        ]
    }


def test_extrai_estagios_na_ordem_ignorando_sem_name(tmp_path):
    caminho = tmp_path / "fluxo.json"
    caminho.write_text(
        json.dumps(_fluxo_sintetico()), encoding="utf-8"
    )

    estagios = carregar_estagios(str(caminho))

    # Node sem 'name' foi descartado -> 3 estágios.
    assert len(estagios) == 3
    assert [e.name for e in estagios] == [
        "identificacao_do_cliente",
        "finalize",
        "flow_start",
    ]

    # promptText dict: instruction e versao (name tem prioridade).
    assert estagios[0] == EstagioFluxo(
        name="identificacao_do_cliente",
        versao="Curadoria_V10",
        instruction="Peça o CPF do cliente.",
    )

    # promptText string: vira a própria instruction, sem versao.
    assert estagios[1] == EstagioFluxo(
        name="finalize", versao=None, instruction="placeholder curto"
    )

    # promptText None: instruction e versao ausentes.
    assert estagios[2] == EstagioFluxo(
        name="flow_start", versao=None, instruction=None
    )


def test_versao_cai_para_value_depois_label(tmp_path):
    """Quando ``name`` está ausente, usa ``value``; depois ``label``."""
    dados = {
        "flows": [
            {
                "name": "Stages Module",
                "nodes": [
                    {"name": "a", "promptText": {"value": "vv", "label": "ll"}},
                    {"name": "b", "promptText": {"label": "ll2"}},
                ],
            }
        ]
    }
    caminho = tmp_path / "fluxo.json"
    caminho.write_text(json.dumps(dados), encoding="utf-8")

    estagios = carregar_estagios(str(caminho))
    assert estagios[0].versao == "vv"
    assert estagios[1].versao == "ll2"


def test_usa_flow_nao_start_quando_sem_stages_module(tmp_path):
    """Sem 'Stages Module', usa o primeiro flow com type != 'start'."""
    dados = {
        "flows": [
            {"name": "Main", "type": "start", "nodes": []},
            {"name": "Outro", "type": "other", "nodes": [
                {"name": "so_um_estagio", "promptText": "x"}
            ]},
        ]
    }
    caminho = tmp_path / "fluxo.json"
    caminho.write_text(json.dumps(dados), encoding="utf-8")

    estagios = carregar_estagios(str(caminho))
    assert [e.name for e in estagios] == ["so_um_estagio"]


def test_caminho_inexistente_retorna_lista_vazia(tmp_path):
    inexistente = tmp_path / "nao_existe.json"
    assert carregar_estagios(str(inexistente)) == []


def test_json_invalido_retorna_lista_vazia(tmp_path):
    caminho = tmp_path / "invalido.json"
    caminho.write_text("{ isto nao e json valido ", encoding="utf-8")
    assert carregar_estagios(str(caminho)) == []


def test_json_sem_flows_retorna_lista_vazia(tmp_path):
    caminho = tmp_path / "sem_flows.json"
    caminho.write_text(json.dumps({"outra_chave": 1}), encoding="utf-8")
    assert carregar_estagios(str(caminho)) == []


def test_flows_sem_stages_module_nem_outro_retorna_vazia(tmp_path):
    """Só há flow start -> nenhum candidato -> []."""
    dados = {"flows": [{"name": "Main", "type": "start", "nodes": []}]}
    caminho = tmp_path / "so_start.json"
    caminho.write_text(json.dumps(dados), encoding="utf-8")
    assert carregar_estagios(str(caminho)) == []
