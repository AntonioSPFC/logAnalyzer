"""Property 6: preservação lossless de texto, posições e multiplicidade."""

from __future__ import annotations

from dataclasses import replace
import hashlib

from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.strategies import SearchStrategy

from log_analyzer.core.identificadores import NormalizadorDeIdentificador
from log_analyzer.core.interfaces import TipoInicio
from log_analyzer.core.materializacao import (
    FonteMaterializacao,
    MaterializadorSeletivo,
)
from log_analyzer.core.modelos import (
    CampoEstruturado,
    EntradaIndexada,
    IdentificadorTecnico,
    Proveniencia,
    TipoIdentificador,
)
from log_analyzer.core.multiline import AgrupadorMultiline, BlocoLog
from log_analyzer.core.streaming import LeitorStreaming, LinhaFisica
from tests.phase2.strategies.blocks import (
    BlockSpec,
    LineKind,
    PhysicalLineSpec,
)
from tests.phase2.strategies.files import TemporaryLogFactory

_ARQUIVO_TOKEN = "<ARQUIVO_6>"
_PREFIXO_CABECALHO = "CABECALHO_VALIDO|"
_ALFABETO_UNICODE = tuple("áéíóúçãõÁÉÍÓÚÇÃÕΩλЖЯ日本中文🙂🚀✨")
_TEXTO_UNICODE = st.text(
    alphabet=_ALFABETO_UNICODE,
    min_size=1,
    max_size=12,
)
_IDENTIFICADOR_SINTETICO = st.binary(min_size=1, max_size=8).map(
    lambda valor: f"SYN_CALL_{valor.hex().upper()}"
)


@st.composite
def _blocos_unicode(draw: st.DrawFn) -> BlockSpec:
    """Gera bloco multiline Unicode com LF e CRLF no mesmo bloco."""

    identificador = draw(_IDENTIFICADOR_SINTETICO)
    fragmentos = draw(
        st.lists(
            _TEXTO_UNICODE,
            min_size=2,
            max_size=4,
        )
    )
    primeiro, segundo = draw(
        st.sampled_from((("\n", "\r\n"), ("\r\n", "\n")))
    )
    terminadores = [primeiro, segundo]
    terminadores.extend(
        draw(
            st.lists(
                st.sampled_from(("\n", "\r\n")),
                min_size=len(fragmentos) - 2,
                max_size=len(fragmentos) - 2,
            )
        )
    )

    linhas = [
        PhysicalLineSpec(
            kind=LineKind.VALID_HEADER,
            text=(
                f"{_PREFIXO_CABECALHO} [{identificador}] "
                f"|{fragmentos[0]}"
            ),
            terminator=terminadores[0],
        )
    ]
    linhas.extend(
        PhysicalLineSpec(
            kind=LineKind.CONTINUATION,
            text=f"CONTINUACAO_{indice}|{fragmento}",
            terminator=terminador,
        )
        for indice, (fragmento, terminador) in enumerate(
            zip(fragmentos[1:], terminadores[1:]),
            start=1,
        )
    )
    return BlockSpec(tuple(linhas))


@st.composite
def _sequencias_com_duplicatas(
    draw: st.DrawFn,
) -> tuple[BlockSpec, ...]:
    """Gera fonte serializável com duplicatas exatas e EOF opcional."""

    duplicado = draw(_blocos_unicode())
    adicionais = list(
        draw(
            st.lists(
                _blocos_unicode(),
                min_size=0,
                max_size=3,
            )
        )
    )
    divisao = draw(st.integers(min_value=0, max_value=len(adicionais)))

    # Três ocorrências garantem duas duplicatas integrais mesmo quando a última
    # linha da fonte é transformada em EOF sem terminador.
    blocos = [
        duplicado,
        *adicionais[:divisao],
        duplicado,
        *adicionais[divisao:],
        duplicado,
    ]
    if draw(st.booleans()):
        ultimo = blocos[-1]
        linhas_finais = list(ultimo.lines)
        linhas_finais[-1] = replace(linhas_finais[-1], terminator="")
        blocos[-1] = replace(ultimo, lines=tuple(linhas_finais))

    return tuple(blocos)


_SEQUENCIAS_UNICODE: SearchStrategy[tuple[BlockSpec, ...]] = (
    _sequencias_com_duplicatas()
)


class _ParserSinteticoDeBloco:
    """Converte blocos em metadados sem reter ou reescrever seu texto."""

    def __init__(self) -> None:
        self.identificadores: dict[str, IdentificadorTecnico] = {}
        self._normalizador = NormalizadorDeIdentificador()

    @staticmethod
    def detectar_inicio(linha: LinhaFisica) -> TipoInicio:
        if linha.texto is not None and linha.texto.startswith(_PREFIXO_CABECALHO):
            return TipoInicio.CABECALHO_VALIDO
        return TipoInicio.CONTINUACAO

    def interpretar_bloco(self, bloco: BlocoLog) -> EntradaIndexada:
        referencia = bloco.texto_ref
        cabecalho = bloco.linhas[0].texto
        if referencia is None or cabecalho is None or not bloco.interpretavel:
            raise AssertionError("O gerador deve produzir somente blocos UTF-8 válidos.")

        prefixo, valor_original, _mensagem = cabecalho.split("|", maxsplit=2)
        if f"{prefixo}|" != _PREFIXO_CABECALHO:
            raise AssertionError("Cabeçalho sintético inesperado.")

        span_inicial = len(_PREFIXO_CABECALHO)
        span_final = span_inicial + len(valor_original)
        proveniencia = Proveniencia(
            arquivo_token=bloco.arquivo_token,
            entrada_id=bloco.entrada_id,
            linha_inicial=bloco.linha_inicial,
            linha_final=bloco.linha_final,
            span_inicial=span_inicial,
            span_final=span_final,
            nome_campo="CallId",
            regra_extracao="property-06-sintetica-v1",
        )
        campo = CampoEstruturado(
            nome="CallId",
            valor_original=valor_original,
            proveniencia=proveniencia,
        )
        identificador = self._normalizador.normalizar(
            TipoIdentificador.CALL_ID,
            campo.nome,
            campo.valor_original,
            proveniencia,
        )
        self.identificadores[bloco.entrada_id] = identificador
        digest = hashlib.sha256(
            (
                f"{identificador.namespace_comparacao}\0"
                f"{identificador.valor_normalizado}"
            ).encode("utf-8")
        ).hexdigest()

        return EntradaIndexada(
            entrada_id=bloco.entrada_id,
            aplicacao="VPL",
            ordem_de_leitura=bloco.ordem_de_leitura,
            texto_ref=referencia,
            cabecalho=(campo,),
            identificadores_digest=(digest,),
            timestamp_original=None,
            timestamp_normalizado=None,
            falhas=(),
            interpretada=True,
        )


def _entrada_id_sintetica(_arquivo_token: str, ordem: int) -> str:
    return f"property-06-entry-{ordem}"


# Feature: log-analyzer-phase-2, Property 6: Preservação integral e multiplicidade
@given(blocos_esperados=_SEQUENCIAS_UNICODE)
@settings(max_examples=100)
def test_property_06_preservacao_integral_e_multiplicidade(
    blocos_esperados: tuple[BlockSpec, ...],
    tmp_path_factory,
) -> None:
    """Parsing e metadados não alteram a materialização nem as ocorrências.

    **Validates: Requirements 4.3, 5.1, 5.2, 5.3, 7.6, 15.7**
    """

    raiz = tmp_path_factory.mktemp("property-06-preservacao")
    fonte_sintetica = TemporaryLogFactory(raiz).write_blocks(
        blocos_esperados,
        filename="unicode-duplicado-sintetico.log",
    )
    texto_fonte = "".join(bloco.text for bloco in blocos_esperados)
    linhas_esperadas = tuple(
        linha for bloco in blocos_esperados for linha in bloco.lines
    )
    assert fonte_sintetica.payload == texto_fonte.encode("utf-8")

    leitor = LeitorStreaming(fonte_sintetica.path, _ARQUIVO_TOKEN)
    parser = _ParserSinteticoDeBloco()
    agrupador = AgrupadorMultiline.para_parser(
        parser,
        _ARQUIVO_TOKEN,
        fabrica_entrada_id=_entrada_id_sintetica,
    )
    blocos_observados = tuple(agrupador.agrupar(leitor))
    entradas_indexadas = tuple(
        parser.interpretar_bloco(bloco) for bloco in blocos_observados
    )

    assert leitor.fingerprint.sha256 == fonte_sintetica.digest
    assert len(blocos_observados) == len(blocos_esperados)
    assert tuple(bloco.ordem_de_leitura for bloco in blocos_observados) == tuple(
        range(len(blocos_esperados))
    )
    assert len({entrada.entrada_id for entrada in entradas_indexadas}) == len(
        entradas_indexadas
    )

    linhas_observadas = tuple(
        linha for bloco in blocos_observados for linha in bloco.linhas
    )
    assert len(linhas_observadas) == len(linhas_esperadas)
    posicao_byte = 0
    for numero, (esperada, observada) in enumerate(
        zip(linhas_esperadas, linhas_observadas),
        start=1,
    ):
        payload_linha = esperada.serialized.encode("utf-8")
        assert observada.numero_1_based == numero
        assert observada.inicio_byte == posicao_byte
        assert observada.fim_byte == posicao_byte + len(payload_linha)
        assert observada.texto == esperada.text
        assert observada.terminador == esperada.terminator
        assert observada.texto_com_terminador == esperada.serialized
        posicao_byte = observada.fim_byte
    assert posicao_byte == len(fonte_sintetica.payload)

    resultado = MaterializadorSeletivo(
        (
            FonteMaterializacao(
                arquivo_token=_ARQUIVO_TOKEN,
                caminho=fonte_sintetica.path,
                fingerprint=leitor.fingerprint,
            ),
        )
    ).materializar(entradas_indexadas)

    assert resultado.falhas == ()
    assert len(resultado.entradas) == len(blocos_esperados)
    assert "".join(
        entrada.texto_original for entrada in resultado.entradas
    ) == texto_fonte

    inicio_byte = 0
    linha_inicial = 1
    for esperado, observado, indexada, materializada in zip(
        blocos_esperados,
        blocos_observados,
        entradas_indexadas,
        resultado.entradas,
    ):
        fim_byte = inicio_byte + len(esperado.payload)
        linha_final = linha_inicial + len(esperado.lines) - 1
        referencia = indexada.texto_ref

        assert observado.texto_original == esperado.text
        assert observado.texto_ref == referencia
        assert referencia.inicio_byte == inicio_byte
        assert referencia.fim_byte == fim_byte
        assert referencia.linha_inicial == linha_inicial
        assert referencia.linha_final == linha_final
        assert referencia.sha256 == hashlib.sha256(esperado.payload).hexdigest()
        assert materializada.entrada_indexada is indexada
        assert materializada.texto_original == esperado.text
        assert materializada.texto_original.encode("utf-8") == (
            fonte_sintetica.payload[inicio_byte:fim_byte]
        )

        campo = indexada.cabecalho[0]
        identificador = parser.identificadores[indexada.entrada_id]
        valor_esperado = esperado.lines[0].text.split("|", maxsplit=2)[1]
        assert campo.valor_original == valor_esperado
        assert identificador.valor_original == valor_esperado
        assert identificador.valor_normalizado == (
            valor_esperado.strip()[1:-1].casefold()
        )
        assert identificador.proveniencia is campo.proveniencia
        assert campo.proveniencia.linha_inicial == linha_inicial
        assert campo.proveniencia.linha_final == linha_final
        assert esperado.lines[0].text[
            campo.proveniencia.span_inicial : campo.proveniencia.span_final
        ] == valor_esperado

        inicio_byte = fim_byte
        linha_inicial = linha_final + 1

    assert inicio_byte == len(fonte_sintetica.payload)
    assert linha_inicial == fonte_sintetica.line_count + 1

    indices_duplicados = tuple(
        indice
        for indice, bloco in enumerate(blocos_esperados)
        if bloco.text == blocos_esperados[0].text
    )
    assert len(indices_duplicados) >= 2
    posicoes_duplicadas = tuple(
        (
            entradas_indexadas[indice].texto_ref.inicio_byte,
            entradas_indexadas[indice].texto_ref.fim_byte,
            entradas_indexadas[indice].texto_ref.linha_inicial,
            entradas_indexadas[indice].texto_ref.linha_final,
        )
        for indice in indices_duplicados
    )
    assert len(set(posicoes_duplicadas)) == len(posicoes_duplicadas)
    assert tuple(
        resultado.entradas[indice].texto_original
        for indice in indices_duplicados
    ) == (blocos_esperados[0].text,) * len(indices_duplicados)
