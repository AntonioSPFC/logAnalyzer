"""Property 13 da rejeição atômica de consultas inválidas.

Todos os identificadores, textos e metadados são sintéticos e gerados em
memória. O teste não lê arquivos, dados reais ou serviços externos.
"""

from __future__ import annotations

import string

from hypothesis import event, given, settings, strategies as st
import pytest

from log_analyzer.core.busca import BuscadorDeCenario
from log_analyzer.core.excecoes import ErroDeIdentificador
from log_analyzer.core.indice import IndiceTemporario
from log_analyzer.core.modelos import EntradaDeLog


_WHITESPACE = (" ", "\t", "\r", "\n", "\v", "\f", "\u00a0", "\u2003")
_CONSULTAS_INVALIDAS = st.one_of(
    st.just(""),
    st.text(
        alphabet=st.sampled_from(_WHITESPACE),
        min_size=1,
        max_size=256,
    ),
    st.text(
        alphabet=string.ascii_letters + string.digits + "-_",
        min_size=257,
        max_size=320,
    ),
)


# Feature: log-analyzer-phase-2, Property 13: Consulta inválida preserva o estado
@given(
    consulta_invalida=_CONSULTAS_INVALIDAS,
    semente_sintetica=st.binary(min_size=1, max_size=16),
)
@settings(max_examples=100)
def test_property_13_consulta_invalida_preserva_estado(
    consulta_invalida: str,
    semente_sintetica: bytes,
) -> None:
    """A rejeição preserva resultado, seleção e índice confirmados.

    **Validates: Requirements 7.7**
    """

    if consulta_invalida == "":
        classe = "vazia"
    elif consulta_invalida.isspace():
        classe = "somente_whitespace"
    else:
        assert len(consulta_invalida) > 256
        classe = "maior_que_256"
    event(f"classe_consulta={classe}")

    sufixo = semente_sintetica.hex()
    consulta_valida = f"cenario-sintetico-{sufixo}"
    entrada_id = f"entrada-sintetica-{sufixo}"
    arquivo_token = f"<ARQUIVO_PROPERTY_13_{sufixo.upper()}>"
    namespace = "cenario_property_13"
    texto = f"evento sintético previamente confirmado: {consulta_valida}"
    entrada = EntradaDeLog(
        texto_original=texto,
        aplicacao="APP_PROPERTY_13",
        ordem_de_leitura=0,
        interpretada=False,
        entrada_id=entrada_id,
        arquivo_token=arquivo_token,
        posicao_inicial=1,
        posicao_final=1,
    )

    with IndiceTemporario(limiar_memoria=1_000) as indice:
        indice.adicionar_entrada(
            entrada_id=entrada_id,
            arquivo_token=arquivo_token,
            aplicacao_codigo="APP_PROPERTY_13",
            ordem_de_leitura=0,
            inicio_byte=0,
            fim_byte=len(texto.encode("utf-8")),
            linha_inicial=1,
            linha_final=1,
        )
        indice.indexar_identificador(
            entrada_id=entrada_id,
            namespace=namespace,
            valor_normalizado=consulta_valida,
        )
        indice.adicionar_codigo(
            entrada_id=entrada_id,
            codigo="ESTADO_VALIDO_PROPERTY_13",
        )

        buscador = BuscadorDeCenario(indice)
        resultado_confirmado = buscador.buscar(
            (entrada,),
            consulta_valida,
            namespaces=(namespace,),
        )
        assert resultado_confirmado.entrada_ids == (entrada_id,)

        resultado_antes = buscador.resultado_atual
        assert resultado_antes is resultado_confirmado
        snapshot_resultado_antes = (
            resultado_antes.consulta_normalizada,
            resultado_antes.inclusoes,
            resultado_antes.entrada_ids,
            resultado_antes.entradas_selecionadas,
            resultado_antes.encontrou,
            resultado_antes.caminhos_evidenciados,
            resultado_antes.vinculos_percorridos,
        )
        snapshot_selecao_antes = buscador.selecao_atual
        entradas_indexadas_antes = tuple(indice.iterar_entradas())
        snapshot_indice_antes = (
            len(indice),
            indice.em_disco,
            entradas_indexadas_antes,
            tuple(indice.iterar_identificadores()),
            tuple(indice.iterar_arestas()),
            tuple(
                (
                    registro.entrada_id,
                    indice.codigos_da_entrada(registro.entrada_id),
                )
                for registro in entradas_indexadas_antes
            ),
        )

        with pytest.raises(ErroDeIdentificador):
            buscador.buscar(
                (entrada,),
                consulta_invalida,
                namespaces=(namespace,),
            )

        resultado_depois = buscador.resultado_atual
        assert resultado_depois is resultado_confirmado
        snapshot_resultado_depois = (
            resultado_depois.consulta_normalizada,
            resultado_depois.inclusoes,
            resultado_depois.entrada_ids,
            resultado_depois.entradas_selecionadas,
            resultado_depois.encontrou,
            resultado_depois.caminhos_evidenciados,
            resultado_depois.vinculos_percorridos,
        )
        entradas_indexadas_depois = tuple(indice.iterar_entradas())
        snapshot_indice_depois = (
            len(indice),
            indice.em_disco,
            entradas_indexadas_depois,
            tuple(indice.iterar_identificadores()),
            tuple(indice.iterar_arestas()),
            tuple(
                (
                    registro.entrada_id,
                    indice.codigos_da_entrada(registro.entrada_id),
                )
                for registro in entradas_indexadas_depois
            ),
        )

        assert snapshot_resultado_depois == snapshot_resultado_antes
        assert buscador.selecao_atual == snapshot_selecao_antes
        assert snapshot_indice_depois == snapshot_indice_antes
