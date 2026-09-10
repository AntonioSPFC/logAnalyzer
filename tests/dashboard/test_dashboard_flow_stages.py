"""Testes de integração do seletor de arquivo de fluxo no dashboard legado.

Todos os dados são 100% sintéticos. Verificam:
  (a) GET / renderiza o novo select ``flow_file`` com a opção ``(nenhum)``.
  (b) POST /analyze com um JSON de fluxo sintético renderiza ``analysis.html``
      exibindo TODOS os nomes de estágio definidos no fluxo.

O ``CallLogParser`` é substituído por um objeto de chamada sintético mínimo, de
forma a exercitar apenas a fiação de ``flow_stages`` sem depender do parsing de
logs reais.
"""

from __future__ import annotations

import json

import pytest

from dashboard.app import create_app


CALL_ID = "0018c4102ff2d6c7"


class _FakeSpeaker:
    value = "assistant"


class _FakeCall:
    """Objeto de chamada sintético com os atributos usados por analysis.html."""

    def __init__(self):
        self.call_id = CALL_ID
        self.customer_name = None
        self.cpf = None
        self.phone = None
        self.company = None
        self.product = None
        self.debt_total = None
        self.debt_discount = None
        self.debt_due_date = None
        self.days_overdue = None
        self.installments_overdue = None
        self.assistant_name = None
        self.tts_supplier = None
        self.tts_voice = None
        self.tts_voice_id = None
        self.tts_model_id = None
        self.vpl_ip = None
        self.ork_ip = None
        self.kamailio_ip = None
        self.ai_models = []
        self.tts_latencies = []
        self.categorizer_latencies = []
        self.cache_hits = 0
        self.cache_misses = 0
        self.session_summary = None
        self.no_voice_timeouts = 0
        self.error_entries = []
        self.audio_repetitions = []
        self.missing_audio_files = []
        self.start_time = None
        self.end_time = None
        self.hangup_reason = None
        self.disposition_description = None
        self.conversation = []
        self.classifier_prompt = None
        self.finalizer_prompt = None
        self.stage_sequence = []
        self.events = []
        self.raw_mailing_data = None


def _fluxo_sintetico() -> dict:
    nomes = [
        "flow_start",
        "identificacao_do_cliente",
        "negociacao_da_divida",
        "acordo_realizado",
        "cliente_ja_pagou",
        "nova_ligacao",
        "general_instructions",
        "staging",
        "finalize",
        "call-disposition",
    ]
    nodes = [
        {
            "name": nome,
            "promptText": {
                "instruction": f"Instrução do estágio {nome}.",
                "name": "Curadoria_V10",
            },
        }
        for nome in nomes
    ]
    return {
        "flows": [
            {"name": "Main", "type": "start", "nodes": []},
            {"name": "Stages Module", "type": "other", "nodes": nodes},
        ]
    }


@pytest.fixture
def log_dir(tmp_path):
    directory = tmp_path / "logs"
    directory.mkdir()
    (directory / "app.log").write_text("linha sintetica\n", encoding="utf-8")
    (directory / "fluxo.json").write_text(
        json.dumps(_fluxo_sintetico()), encoding="utf-8"
    )
    return directory


@pytest.fixture
def app(tmp_path, log_dir):
    return create_app({
        'LOG_DIRECTORY': str(log_dir),
        'DB_PATH': str(tmp_path / 'curation.db'),
        'TESTING': True,
    })


@pytest.fixture
def client(app):
    return app.test_client()


def test_get_index_contem_select_flow_file(client):
    """(a) A tela de busca oferece o select de arquivo de fluxo."""
    resposta = client.get('/')
    assert resposta.status_code == 200
    corpo = resposta.get_data(as_text=True)
    assert 'name="flow_file"' in corpo
    assert '(nenhum)' in corpo
    assert 'fluxo.json' in corpo


def test_post_analyze_exibe_estagios_do_fluxo(client, monkeypatch):
    """(b) POST /analyze com fluxo selecionado exibe todos os 10 estágios."""
    import log_analyzer.apps.call_parser as modulo_parser

    monkeypatch.setattr(
        modulo_parser.CallLogParser, 'parse',
        lambda self, call_id: _FakeCall()
    )

    resposta = client.post('/analyze', data={
        'call_id': CALL_ID,
        'log_file': '',
        'flow_file': 'fluxo.json',
    })
    assert resposta.status_code == 200
    corpo = resposta.get_data(as_text=True)

    nomes = [
        "flow_start",
        "identificacao_do_cliente",
        "negociacao_da_divida",
        "acordo_realizado",
        "cliente_ja_pagou",
        "nova_ligacao",
        "general_instructions",
        "staging",
        "finalize",
        "call-disposition",
    ]
    for nome in nomes:
        assert nome in corpo
    assert 'Curadoria_V10' in corpo
    assert 'Estágios (10)' in corpo


def test_post_analyze_sem_fluxo_nao_quebra(client, monkeypatch):
    """Sem flow_file, a análise ainda renderiza (sem seção de estágios do fluxo)."""
    import log_analyzer.apps.call_parser as modulo_parser

    monkeypatch.setattr(
        modulo_parser.CallLogParser, 'parse',
        lambda self, call_id: _FakeCall()
    )

    resposta = client.post('/analyze', data={
        'call_id': CALL_ID,
        'log_file': '',
        'flow_file': '',
    })
    assert resposta.status_code == 200
