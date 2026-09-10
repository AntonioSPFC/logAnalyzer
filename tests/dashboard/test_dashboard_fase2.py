"""Testes do fluxo web da Fase 2 no dashboard Flask.

Todos os dados são 100% sintéticos. O fluxo exercita a nova rota aditiva
``/analyze-fase2`` e a página ``/fase2`` sem tocar no fluxo legado.
"""

from __future__ import annotations

import os

import pytest

from dashboard.app import create_app


CALL_ID = "CALL-SYN-2042"


def _vpl(call_id: str = CALL_ID) -> str:
    return (
        "2035-06-07 08:09:10.123456 99.50% "
        f"[NOTICE] mod_sintetico.c:42 CallId={call_id} evento sintetico VPL\n"
    )


def _ork(call_id: str = CALL_ID) -> str:
    return (
        "2035-06-07T11:09:10.123456+00:00 "
        "ork-node.synthetic.invalid ork-worker[4242]: "
        f"INFO - agent.synthetic - TelecomCallId={call_id} "
        f"CallId={call_id} evento sintetico ORK\n"
    )


@pytest.fixture
def log_dir(tmp_path):
    directory = tmp_path / "logs"
    directory.mkdir()
    (directory / "vpl.log").write_text(_vpl(), encoding="utf-8", newline="")
    (directory / "ork.log").write_text(_ork(), encoding="utf-8", newline="")
    return directory


@pytest.fixture
def client(tmp_path, log_dir):
    app = create_app({
        'LOG_DIRECTORY': str(log_dir),
        'DB_PATH': str(tmp_path / 'curation.db'),
        'TESTING': True,
    })
    return app.test_client()


def test_get_fase2_lista_arquivos(client):
    """(a) GET /fase2 retorna 200 e lista os arquivos disponíveis."""
    resposta = client.get('/fase2')
    assert resposta.status_code == 200
    corpo = resposta.get_data(as_text=True)
    assert 'vpl.log' in corpo
    assert 'ork.log' in corpo
    # A página deve conter as opções (nenhum) dos selects VPL/ORK.
    assert corpo.count('(nenhum)') >= 2


def test_post_analyze_fase2_sucesso_exibe_placeholders(client):
    """(b) POST com VPL+ORK correlacionáveis exibe placeholders, não o bruto."""
    resposta = client.post('/analyze-fase2', data={
        'identificador': CALL_ID,
        'vpl_file': 'vpl.log',
        'ork_file': 'ork.log',
    })
    assert resposta.status_code == 200
    corpo = resposta.get_data(as_text=True)
    assert '&lt;CALL_ID_1&gt;' in corpo or '<CALL_ID_1>' in corpo
    # O identificador bruto nunca pode aparecer na página.
    assert CALL_ID not in corpo


def test_post_analyze_fase2_identificador_invalido(client):
    """(c) POST com identificador vazio retorna 400 e volta ao formulário."""
    resposta = client.post('/analyze-fase2', data={
        'identificador': '   ',
        'vpl_file': 'vpl.log',
        'ork_file': '',
    })
    assert resposta.status_code == 400
    corpo = resposta.get_data(as_text=True)
    assert 'Analisar (Fase 2)' in corpo
    assert CALL_ID not in corpo


def test_post_analyze_fase2_sem_arquivo_retorna_400(client):
    """POST sem VPL nem ORK volta ao formulário com erro (fail-closed)."""
    resposta = client.post('/analyze-fase2', data={
        'identificador': CALL_ID,
        'vpl_file': '',
        'ork_file': '',
    })
    assert resposta.status_code == 400
    corpo = resposta.get_data(as_text=True)
    assert 'Analisar (Fase 2)' in corpo


def test_post_analyze_fase2_sanitizacao_suprimida(client, monkeypatch):
    """(d) Resultado suprimido mostra mensagem segura sem dados brutos."""
    from log_analyzer.core.excecoes import ErroDeSanitizacao
    import log_analyzer.core.pipeline_fase2 as modulo_pipeline

    def _falhar(self, selecao, identificador):
        raise ErroDeSanitizacao()

    monkeypatch.setattr(
        modulo_pipeline.PipelineFase2, 'executar', _falhar
    )

    resposta = client.post('/analyze-fase2', data={
        'identificador': CALL_ID,
        'vpl_file': 'vpl.log',
        'ork_file': 'ork.log',
    })
    assert resposta.status_code == 200
    corpo = resposta.get_data(as_text=True)
    assert 'fail-closed' in corpo
    assert 'visão segura foi suprimida' in corpo
    assert CALL_ID not in corpo
    # Nenhum conteúdo bruto/renderizado deve aparecer.
    assert 'Visão segura renderizada' not in corpo


def test_fluxo_legado_intacto(client):
    """A rota legada /analyze continua rejeitando CallId inválido com 400."""
    resposta = client.post('/analyze', data={'call_id': 'zzz', 'log_file': ''})
    assert resposta.status_code == 400
