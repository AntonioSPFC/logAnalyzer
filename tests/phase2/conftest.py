"""Fixtures comuns da suíte sintética da Fase 2."""

from pathlib import Path

import pytest

from tests.phase2.strategies.files import TemporaryLogFactory


@pytest.fixture
def synthetic_log_factory(tmp_path: Path) -> TemporaryLogFactory:
    """Factory limitada ao diretório temporário exclusivo do teste."""

    return TemporaryLogFactory(tmp_path)
