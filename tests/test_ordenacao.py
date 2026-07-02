"""Testes para a ordenação determinística da linha do tempo (log_analyzer.core.ordenacao).

Verifica:
- Ordenação crescente por carimbo_de_tempo
- Desempate por nome da aplicação (alfabético)
- Desempate final por ordem_de_leitura
- Entradas sem carimbo_de_tempo ficam ao final
- A lista de entrada não é mutada

Requirements: 3.4, 8.1, 8.2
"""

from datetime import datetime

import pytest

from log_analyzer.core.modelos import EntradaDeLog
from log_analyzer.core.ordenacao import ordenar_linha_do_tempo


def _entrada(
    ts: datetime | None,
    app: str,
    ordem: int,
    interpretada: bool = True,
    texto: str = "texto",
) -> EntradaDeLog:
    """Helper para criar EntradaDeLog com os campos mínimos."""
    if interpretada and ts is not None:
        return EntradaDeLog(
            texto_original=texto,
            aplicacao=app,
            ordem_de_leitura=ordem,
            interpretada=True,
            carimbo_de_tempo=ts,
            nivel_de_severidade="INFO",
            mensagem="msg",
        )
    return EntradaDeLog(
        texto_original=texto,
        aplicacao=app,
        ordem_de_leitura=ordem,
        interpretada=False,
    )


class TestOrdenarLinhaDeTempo:
    """Testes unitários para ordenar_linha_do_tempo."""

    def test_lista_vazia(self):
        resultado = ordenar_linha_do_tempo([])
        assert resultado == []

    def test_uma_entrada(self):
        e = _entrada(datetime(2024, 1, 1, 10, 0), "vpl", 0)
        resultado = ordenar_linha_do_tempo([e])
        assert resultado == [e]

    def test_ordenacao_por_tempo_crescente(self):
        e1 = _entrada(datetime(2024, 1, 1, 12, 0), "vpl", 0)
        e2 = _entrada(datetime(2024, 1, 1, 10, 0), "vpl", 1)
        e3 = _entrada(datetime(2024, 1, 1, 11, 0), "vpl", 2)

        resultado = ordenar_linha_do_tempo([e1, e2, e3])
        assert resultado == [e2, e3, e1]

    def test_desempate_por_aplicacao_alfabetica(self):
        ts = datetime(2024, 6, 15, 8, 30)
        e_ork = _entrada(ts, "ork", 0)
        e_vpl = _entrada(ts, "vpl", 0)
        e_voci = _entrada(ts, "voci", 0)

        resultado = ordenar_linha_do_tempo([e_vpl, e_ork, e_voci])
        assert resultado == [e_ork, e_voci, e_vpl]

    def test_desempate_por_ordem_de_leitura(self):
        ts = datetime(2024, 3, 10, 14, 0)
        e1 = _entrada(ts, "ork", 5)
        e2 = _entrada(ts, "ork", 2)
        e3 = _entrada(ts, "ork", 8)

        resultado = ordenar_linha_do_tempo([e1, e2, e3])
        assert resultado == [e2, e1, e3]

    def test_chave_total_completa(self):
        """Testa combinação de todos os critérios de desempate."""
        ts1 = datetime(2024, 1, 1, 10, 0)
        ts2 = datetime(2024, 1, 1, 10, 0)  # mesmo tempo

        e1 = _entrada(ts1, "vpl", 3)
        e2 = _entrada(ts1, "ork", 1)
        e3 = _entrada(ts2, "ork", 5)
        e4 = _entrada(datetime(2024, 1, 1, 9, 0), "vpl", 0)

        resultado = ordenar_linha_do_tempo([e1, e2, e3, e4])
        # Esperado: e4 (09:00), e2 (10:00, ork, 1), e3 (10:00, ork, 5), e1 (10:00, vpl, 3)
        assert resultado == [e4, e2, e3, e1]

    def test_entradas_sem_carimbo_ficam_ao_final(self):
        e_interpretada = _entrada(datetime(2024, 1, 1, 10, 0), "vpl", 0)
        e_nao_interpretada = _entrada(None, "ork", 1, interpretada=False)

        resultado = ordenar_linha_do_tempo([e_nao_interpretada, e_interpretada])
        assert resultado == [e_interpretada, e_nao_interpretada]

    def test_multiplas_nao_interpretadas_ordenadas_por_app_e_ordem(self):
        e1 = _entrada(None, "vpl", 2, interpretada=False)
        e2 = _entrada(None, "ork", 0, interpretada=False)
        e3 = _entrada(None, "ork", 3, interpretada=False)

        resultado = ordenar_linha_do_tempo([e1, e2, e3])
        # Todas no final (datetime.max), desempate por app e ordem
        assert resultado == [e2, e3, e1]

    def test_nao_muta_a_lista_de_entrada(self):
        e1 = _entrada(datetime(2024, 1, 1, 12, 0), "vpl", 0)
        e2 = _entrada(datetime(2024, 1, 1, 10, 0), "ork", 1)
        original = [e1, e2]
        copia = list(original)

        ordenar_linha_do_tempo(original)
        assert original == copia

    def test_mistura_vpl_e_ork_linha_do_tempo_unificada(self):
        """Cenário de correlação: VPL e ORK na mesma linha do tempo (Req 8.1)."""
        e_vpl_1 = _entrada(datetime(2024, 5, 1, 10, 0, 0), "vpl", 0)
        e_ork_1 = _entrada(datetime(2024, 5, 1, 10, 0, 1), "ork", 0)
        e_vpl_2 = _entrada(datetime(2024, 5, 1, 10, 0, 1), "vpl", 1)
        e_ork_2 = _entrada(datetime(2024, 5, 1, 10, 0, 2), "ork", 1)

        resultado = ordenar_linha_do_tempo([e_ork_2, e_vpl_2, e_ork_1, e_vpl_1])
        # 10:00:00 vpl, 10:00:01 ork, 10:00:01 vpl, 10:00:02 ork
        assert resultado == [e_vpl_1, e_ork_1, e_vpl_2, e_ork_2]
