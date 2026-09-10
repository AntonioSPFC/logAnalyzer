"""Property 12 da busca estruturada e do fallback literal da Fase 2.

Todos os valores, namespaces, textos e identificadores são sintéticos e criados
em memória. O modelo ingênuo compara valores normalizados diretamente e não usa
o índice HMAC nem qualquer função da implementação da busca.
"""

from __future__ import annotations

from dataclasses import dataclass
import string

from hypothesis import event, given, settings, strategies as st

from log_analyzer.core.busca import BuscadorDeCenario, MotivoInclusaoBusca
from log_analyzer.core.indice import IndiceTemporario
from log_analyzer.core.modelos import (
    EntradaDeLog,
    IdentificadorTecnico,
    Proveniencia,
    TipoIdentificador,
)


_NAMESPACES = (
    "chamada_sintetica_p12_a",
    "chamada_sintetica_p12_b",
    "chamada_sintetica_p12_c",
)
_PARES_DE_NAMESPACES = tuple(
    (compativel, incompativel)
    for compativel in _NAMESPACES
    for incompativel in _NAMESPACES
    if compativel != incompativel
)
_MODOS_OBRIGATORIOS = (
    "estruturada",
    "fallback",
    "duplo",
    "estruturada_duplicada",
    "namespace_com_fallback",
    "namespace_isolado",
    "parcial",
    "sem_correspondencia",
)
_FRAGMENTO = st.text(
    alphabet=string.ascii_letters + string.digits,
    min_size=3,
    max_size=16,
)


@dataclass(frozen=True)
class _RegistroSintetico:
    modo: str
    entrada: EntradaDeLog
    duplicar_no_indice: bool = False


def _criar_identificador(
    *,
    entrada_id: str,
    arquivo_token: str,
    linha: int,
    slot: int,
    namespace: str,
    valor_normalizado: str,
    compativel: bool,
) -> IdentificadorTecnico:
    nome_campo = (
        f"CallIdSintetico{slot:02d}"
        if compativel
        else f"SipIdSintetico{slot:02d}"
    )
    valor_original = f"<{valor_normalizado.swapcase()}>"
    return IdentificadorTecnico(
        tipo=(
            TipoIdentificador.CALL_ID
            if compativel
            else TipoIdentificador.SIP
        ),
        namespace_comparacao=namespace,
        nome_campo=nome_campo,
        valor_original=valor_original,
        valor_normalizado=valor_normalizado,
        proveniencia=Proveniencia(
            arquivo_token=arquivo_token,
            entrada_id=entrada_id,
            linha_inicial=linha,
            linha_final=linha,
            span_inicial=slot * 64,
            span_final=slot * 64 + len(valor_original),
            nome_campo=nome_campo,
            regra_extracao="property-12-extrator-sintetico-v1",
        ),
    )


def _criar_registro(
    *,
    modo: str,
    indice: int,
    sal: int,
    consulta: str,
    namespace_compativel: str,
    namespace_incompativel: str,
) -> _RegistroSintetico:
    entrada_id = f"entrada-p12-{sal:016x}-{indice:02d}"
    arquivo_token = f"<ARQUIVO_SINTETICO_P12_{sal:016X}>"
    linha = indice + 1
    consulta_normalizada = consulta.casefold()
    valor_irrelevante = f"outro-p12-{sal:016x}-{indice:02d}"

    identificadores = [
        _criar_identificador(
            entrada_id=entrada_id,
            arquivo_token=arquivo_token,
            linha=linha,
            slot=0,
            namespace=namespace_compativel,
            valor_normalizado=valor_irrelevante,
            compativel=True,
        )
    ]

    if modo in {"estruturada", "duplo", "estruturada_duplicada"}:
        identificadores.append(
            _criar_identificador(
                entrada_id=entrada_id,
                arquivo_token=arquivo_token,
                linha=linha,
                slot=1,
                namespace=namespace_compativel,
                valor_normalizado=consulta_normalizada,
                compativel=True,
            )
        )
    if modo == "estruturada_duplicada":
        identificadores.append(
            _criar_identificador(
                entrada_id=entrada_id,
                arquivo_token=arquivo_token,
                linha=linha,
                slot=2,
                namespace=namespace_compativel,
                valor_normalizado=consulta_normalizada,
                compativel=True,
            )
        )
    if modo in {"namespace_com_fallback", "namespace_isolado"}:
        identificadores.append(
            _criar_identificador(
                entrada_id=entrada_id,
                arquivo_token=arquivo_token,
                linha=linha,
                slot=1,
                namespace=namespace_incompativel,
                valor_normalizado=consulta_normalizada,
                compativel=False,
            )
        )
    if modo == "parcial":
        identificadores.append(
            _criar_identificador(
                entrada_id=entrada_id,
                arquivo_token=arquivo_token,
                linha=linha,
                slot=1,
                namespace=namespace_compativel,
                valor_normalizado=consulta_normalizada[:-1],
                compativel=True,
            )
        )

    literal_com_caixa_alternada = (
        consulta.upper() if indice % 2 else consulta.swapcase()
    )
    if modo in {"fallback", "duplo", "namespace_com_fallback"}:
        texto = (
            "cabecalho sintetico\n"
            f"continuacao com [{literal_com_caixa_alternada}] no bloco\n"
            "rodape sintetico"
        )
    elif modo == "parcial":
        texto = (
            "cabecalho sintetico\n"
            f"continuacao apenas com [{literal_com_caixa_alternada[:-1]}]\n"
            "rodape sintetico"
        )
    else:
        texto = f"evento sintetico sem literal {sal:016x} {indice:02d}"

    entrada = EntradaDeLog(
        texto_original=texto,
        aplicacao="VPL" if indice % 2 == 0 else "ORK",
        ordem_de_leitura=indice,
        interpretada=False,
        entrada_id=entrada_id,
        arquivo_token=arquivo_token,
        posicao_inicial=linha,
        posicao_final=linha + texto.count("\n"),
        identificadores=tuple(identificadores),
    )
    return _RegistroSintetico(
        modo=modo,
        entrada=entrada,
        duplicar_no_indice=modo in {"duplo", "estruturada_duplicada"},
    )


def _indexar(
    indice: IndiceTemporario,
    registros: tuple[_RegistroSintetico, ...],
) -> None:
    for ordem, registro in enumerate(registros):
        entrada = registro.entrada
        assert entrada.entrada_id is not None
        assert entrada.arquivo_token is not None
        assert entrada.posicao_inicial is not None
        assert entrada.posicao_final is not None
        inicio_byte = ordem * 1_000
        indice.adicionar_entrada(
            entrada_id=entrada.entrada_id,
            arquivo_token=entrada.arquivo_token,
            aplicacao_codigo=entrada.aplicacao,
            ordem_de_leitura=entrada.ordem_de_leitura,
            inicio_byte=inicio_byte,
            fim_byte=inicio_byte + len(entrada.texto_original.encode("utf-8")),
            linha_inicial=entrada.posicao_inicial,
            linha_final=entrada.posicao_final,
        )
        for identificador in entrada.identificadores:
            indice.indexar_identificador(
                entrada_id=entrada.entrada_id,
                namespace=identificador.namespace_comparacao,
                valor_normalizado=identificador.valor_normalizado,
            )
            if registro.duplicar_no_indice:
                indice.indexar_identificador(
                    entrada_id=entrada.entrada_id,
                    namespace=identificador.namespace_comparacao,
                    valor_normalizado=identificador.valor_normalizado,
                )


def _modelo_ingenuo(
    registros: tuple[_RegistroSintetico, ...],
    consulta: str,
    namespaces_compativeis: tuple[str, ...],
) -> tuple[
    tuple[str, ...],
    dict[str, MotivoInclusaoBusca],
    dict[str, tuple[str, ...]],
]:
    consulta_normalizada = consulta.casefold()
    namespaces_permitidos = set(namespaces_compativeis)
    motivos: dict[str, MotivoInclusaoBusca] = {}
    namespaces_por_entrada: dict[str, tuple[str, ...]] = {}

    for registro in registros:
        entrada = registro.entrada
        assert entrada.entrada_id is not None
        correspondentes = tuple(
            sorted(
                {
                    identificador.namespace_comparacao
                    for identificador in entrada.identificadores
                    if identificador.namespace_comparacao
                    in namespaces_permitidos
                    and identificador.valor_normalizado
                    == consulta_normalizada
                }
            )
        )
        if correspondentes:
            motivos[entrada.entrada_id] = (
                MotivoInclusaoBusca.IGUALDADE_ESTRUTURADA
            )
            namespaces_por_entrada[entrada.entrada_id] = correspondentes
        elif consulta.casefold() in entrada.texto_original.casefold():
            motivos[entrada.entrada_id] = MotivoInclusaoBusca.FALLBACK_LITERAL
            namespaces_por_entrada[entrada.entrada_id] = ()

    sementes = tuple(sorted(motivos))
    return sementes, motivos, namespaces_por_entrada


# Feature: log-analyzer-phase-2, Property 12: Busca estruturada e fallback são corretos, completos e sem duplicatas
@given(
    dados=st.data(),
    sal=st.integers(min_value=0, max_value=2**64 - 1),
    fragmento=_FRAGMENTO,
)
@settings(max_examples=100)
def test_property_12_busca_equivale_ao_modelo_ingenuo(
    dados,
    sal: int,
    fragmento: str,
) -> None:
    """As sementes coincidem exatamente com a semântica aprovada.

    **Validates: Requirements 7.2, 7.3, 7.4, 7.5**
    """

    namespace_compativel, namespace_incompativel = dados.draw(
        st.sampled_from(_PARES_DE_NAMESPACES),
        label="namespaces",
    )
    consulta_base = f"QRY-P12-{sal:016X}-{fragmento}"
    forma_da_consulta = dados.draw(
        st.sampled_from(("original", "minuscula", "caixa_invertida")),
        label="forma_da_consulta",
    )
    if forma_da_consulta == "minuscula":
        consulta = consulta_base.lower()
    elif forma_da_consulta == "caixa_invertida":
        consulta = consulta_base.swapcase()
    else:
        consulta = consulta_base

    modos_extras = tuple(
        dados.draw(
            st.lists(
                st.sampled_from(_MODOS_OBRIGATORIOS),
                min_size=0,
                max_size=4,
            ),
            label="modos_extras",
        )
    )
    modos = _MODOS_OBRIGATORIOS + modos_extras
    ordem_modos = dados.draw(
        st.permutations(tuple(range(len(modos)))),
        label="ordem_das_entradas",
    )
    modos = tuple(modos[indice] for indice in ordem_modos)
    registros = tuple(
        _criar_registro(
            modo=modo,
            indice=indice,
            sal=sal,
            consulta=consulta,
            namespace_compativel=namespace_compativel,
            namespace_incompativel=namespace_incompativel,
        )
        for indice, modo in enumerate(modos)
    )

    sementes_esperadas, motivos_esperados, namespaces_esperados = (
        _modelo_ingenuo(
            registros,
            consulta,
            (namespace_compativel,),
        )
    )
    entradas_unicas = tuple(registro.entrada for registro in registros)
    entradas_com_repeticoes = (
        tuple(reversed(entradas_unicas))
        + (entradas_unicas[0], entradas_unicas[-1])
    )

    with IndiceTemporario(limiar_memoria=1_000) as indice:
        _indexar(indice, registros)
        resultado = BuscadorDeCenario(indice).buscar(
            entradas_com_repeticoes,
            consulta,
            namespaces=(namespace_compativel,),
        )
        identificadores_indexados = tuple(indice.iterar_identificadores())
        assert identificadores_indexados
        assert all(
            len(item.hmac_sha256) == 64
            for item in identificadores_indexados
        )
        assert all(
            not hasattr(item, "valor_normalizado")
            for item in identificadores_indexados
        )

    assert resultado.entrada_ids == sementes_esperadas
    assert resultado.selecao == sementes_esperadas
    assert tuple(
        inclusao.entrada_id for inclusao in resultado.inclusoes
    ) == sementes_esperadas
    assert tuple(
        entrada.entrada_id for entrada in resultado.entradas_selecionadas
    ) == sementes_esperadas
    assert len(resultado.entrada_ids) == len(set(resultado.entrada_ids))
    assert resultado.entrada_ids == tuple(sorted(resultado.entrada_ids))
    assert resultado.caminhos_evidenciados == ()

    for entrada_id in sementes_esperadas:
        inclusao = resultado.inclusao_de(entrada_id)
        assert inclusao is not None
        assert inclusao.motivos == (motivos_esperados[entrada_id],)
        assert inclusao.namespaces_correspondentes == (
            namespaces_esperados[entrada_id]
        )
        assert inclusao.caminhos_evidenciados == ()

    ids_parciais = {
        registro.entrada.entrada_id
        for registro in registros
        if registro.modo == "parcial"
    }
    ids_namespace_isolado = {
        registro.entrada.entrada_id
        for registro in registros
        if registro.modo == "namespace_isolado"
    }
    ids_namespace_com_fallback = {
        registro.entrada.entrada_id
        for registro in registros
        if registro.modo == "namespace_com_fallback"
    }
    assert ids_parciais.isdisjoint(resultado.entrada_ids)
    assert ids_namespace_isolado.isdisjoint(resultado.entrada_ids)
    assert ids_namespace_com_fallback.issubset(resultado.entrada_ids)
    assert all(
        resultado.inclusao_de(entrada_id).motivo
        is MotivoInclusaoBusca.FALLBACK_LITERAL
        for entrada_id in ids_namespace_com_fallback
    )

    event(f"quantidade_entradas={len(registros)}")
    event(f"forma_consulta={forma_da_consulta}")
    event(f"quantidade_sementes={len(sementes_esperadas)}")
