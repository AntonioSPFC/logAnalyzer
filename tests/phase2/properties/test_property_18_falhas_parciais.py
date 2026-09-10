"""Property 18: preservação de resultados diante de falhas parciais.

As fontes e os identificadores são inteiramente sintéticos. O modelo de
referência usa apenas estados primitivos de cada aplicação e não consulta o
pipeline para decidir entradas, falhas ou cobertura esperadas.
"""

from __future__ import annotations

from hypothesis import event, given, settings
from hypothesis import strategies as st

from log_analyzer.core.bootstrap import criar_registro_padrao
from log_analyzer.core.modelos import ArquivoSelecionado, EstadoSanitizacao
from log_analyzer.core.pipeline_fase2 import PipelineFase2


_ESTADOS_DA_FONTE = ("valida", "ausente", "invalida")
_APLICACOES = ("VPL", "ORK")


# Feature: log-analyzer-phase-2, Property 18: Falhas parciais preservam o lado disponível e a cobertura
@given(
    estado_vpl=st.sampled_from(_ESTADOS_DA_FONTE),
    estado_ork=st.sampled_from(_ESTADOS_DA_FONTE),
    quantidade_vpl=st.integers(min_value=1, max_value=3),
    quantidade_ork=st.integers(min_value=1, max_value=3),
    sal=st.integers(min_value=0, max_value=2**64 - 1),
)
@settings(max_examples=100, deadline=500)
def test_property_18_falhas_parciais_preservam_lado_disponivel_e_cobertura(
    estado_vpl: str,
    estado_ork: str,
    quantidade_vpl: int,
    quantidade_ork: int,
    sal: int,
    tmp_path_factory,
) -> None:
    """O resultado coincide com o modelo independente de fontes parciais.

    **Validates: Requirements 9.7, 15.6, 17.1**
    """

    estados = {"VPL": estado_vpl, "ORK": estado_ork}
    quantidades = {"VPL": quantidade_vpl, "ORK": quantidade_ork}
    modelo_entradas = {
        aplicacao: tuple(
            f"detalhe sintético p18 {aplicacao.casefold()} índice {indice}"
            for indice in range(quantidades[aplicacao])
        )
        for aplicacao in _APLICACOES
        if estados[aplicacao] == "valida"
    }
    modelo_analisadas = [
        aplicacao
        for aplicacao in _APLICACOES
        if estados[aplicacao] == "valida"
    ]
    modelo_ausentes_ou_invalidas = [
        aplicacao
        for aplicacao in _APLICACOES
        if estados[aplicacao] != "valida"
    ]

    raiz = tmp_path_factory.mktemp("property-18-falhas-parciais")
    identificador = f"SYNTHETIC-P18-{sal:016X}"
    selecao: list[ArquivoSelecionado] = []
    modelo_falhas: list[tuple[str, str]] = []
    caminhos_invalidos: list[str] = []

    for aplicacao in _APLICACOES:
        estado = estados[aplicacao]
        if estado == "ausente":
            continue

        token = f"<ARQUIVO_{len(selecao) + 1}>"
        caminho = raiz / f"{aplicacao.casefold()}-{estado}.log"
        selecao.append(ArquivoSelecionado(str(caminho), aplicacao))

        if estado == "invalida":
            caminho.write_bytes(b"")
            modelo_falhas.append((token, "EMPTY_FILE"))
            caminhos_invalidos.append(str(caminho))
            continue

        linhas: list[str] = []
        for indice, marcador in enumerate(modelo_entradas[aplicacao]):
            if aplicacao == "VPL":
                linhas.append(
                    "2035-04-05 06:07:"
                    f"{indice:02d}.123456 99.00% [NOTICE] "
                    "modulo_p18.c:18 "
                    f"canal sofia/external/{identificador}@sip.invalid "
                    f"{marcador}\n"
                )
            else:
                linhas.append(
                    "2035-04-05T09:07:"
                    f"{indice:02d}.123456+00:00 "
                    "ork-p18.synthetic.invalid ork-worker[1800]: "
                    "INFO - property18.synthetic - "
                    f"TelecomCallId={identificador} {marcador}\n"
                )
        caminho.write_text("".join(linhas), encoding="utf-8", newline="")

    event(f"VPL={estado_vpl}, ORK={estado_ork}")
    resultado = PipelineFase2(criar_registro_padrao()).executar(
        tuple(selecao),
        identificador,
    )

    assert resultado.estado_sanitizacao is EstadoSanitizacao.CONCLUIDA
    assert resultado.aplicacoes_analisadas == modelo_analisadas
    assert (
        resultado.aplicacoes_ausentes_ou_invalidas
        == modelo_ausentes_ou_invalidas
    )
    assert set(resultado.aplicacoes_analisadas).isdisjoint(
        resultado.aplicacoes_ausentes_ou_invalidas
    )
    assert set(resultado.aplicacoes_analisadas).union(
        resultado.aplicacoes_ausentes_ou_invalidas
    ) == set(_APLICACOES)

    assert set(resultado.entradas_por_aplicacao) == set(modelo_entradas)
    assert resultado.contagem_por_aplicacao == {
        aplicacao: len(marcadores)
        for aplicacao, marcadores in modelo_entradas.items()
    }
    for aplicacao, marcadores in modelo_entradas.items():
        entradas = resultado.entradas_por_aplicacao[aplicacao]
        assert len(entradas) == len(marcadores)
        for entrada, marcador in zip(entradas, marcadores, strict=True):
            assert entrada.aplicacao == aplicacao
            assert entrada.interpretada
            assert marcador in entrada.texto_original
            assert marcador in (entrada.mensagem or "")

    falhas_observadas = [
        (falha.arquivo_ou_app, falha.descricao)
        for falha in resultado.erros
    ]
    assert falhas_observadas == modelo_falhas
    assert len(resultado.erros) == sum(
        estado == "invalida" for estado in estados.values()
    )

    superficie_segura = "\n".join(
        f"{falha.arquivo_ou_app!r}:{falha.descricao!r}"
        for falha in resultado.erros
    )
    for caminho_invalido in caminhos_invalidos:
        assert caminho_invalido not in superficie_segura
