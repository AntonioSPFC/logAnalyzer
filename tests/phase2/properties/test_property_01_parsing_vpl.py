"""Property 1 do parsing completo e tipado do perfil VPL real.

Todos os valores são gerados em memória pelo Hypothesis. O teste não lê
arquivos, logs locais, bancos de dados ou serviços externos.
"""

from __future__ import annotations

from dataclasses import dataclass
import string

from hypothesis import given, settings, strategies as st
from hypothesis.strategies import SearchStrategy

from log_analyzer.apps.vpl import VplParser
from log_analyzer.core.modelos import (
    CampoEstruturado,
    EntradaDeLog,
    IdentificadorTecnico,
    Proveniencia,
    TipoIdentificador,
)
from tests.phase2.strategies import (
    TimestampSpec,
    assert_no_raw_source_reference,
    opaque_values,
    vpl_timestamps,
)

_ARQUIVO_TOKEN = "<ARQUIVO_1>"
_ENTRADA_ID = f"{_ARQUIVO_TOKEN}:entrada:0"
_REGRA_CABECALHO = "vpl.cabecalho.real.v1"
_REGRA_UUID_PREFIXO = "vpl.uuid-canal-prefixo.v1"
_REGRA_CALL_ID = "vpl.identificador-chamada-rotulado.v1"
_REGRA_CANAL_SIP = "vpl.canal-sip-usuario.v1"
_REGRA_UUID_CANAL = "vpl.uuid-canal-rotulado.v1"
_REGRA_UUID_SESSAO = "vpl.uuid-sessao-rotulado.v1"

_SEVERIDADES = ("DEBUG", "INFO", "NOTICE", "WARNING", "ERR", "CRIT", "ALERT")
_DELIMITADORES = (
    ("", ""),
    ('"', '"'),
    ("'", "'"),
    ("<", ">"),
    ("[", "]"),
    ("(", ")"),
    ("{", "}"),
)
_DELIMITADORES_SIP = (("", ""), ("<", ">"))
_FECHAMENTO_POR_ABERTURA = dict(_DELIMITADORES[1:])
_ESPACOS_DE_CAMPO = ("", " ", "  ", "\t")
_CARACTERES_UNICODE = tuple("áéíóúçãõÁÉÍÓÚÇÃÕΩЖŁ漢字🙂🚀")


@dataclass(frozen=True)
class _IdentificadorEsperado:
    tipo: TipoIdentificador
    namespace: str
    nome_campo: str
    valor_original: str
    valor_normalizado: str
    regra: str
    inicio: int
    fim: int


@dataclass(frozen=True)
class _ParteMensagem:
    texto: str
    identificador: _IdentificadorEsperado | None = None


@dataclass(frozen=True)
class _CasoVpl:
    texto: str
    mensagem: str
    unicode_gerado: str
    entrada_esperada: EntradaDeLog
    valores_incidentais_normalizados: tuple[str, ...]


def _normalizar_referencia(valor: str) -> str:
    resultado = valor.strip()
    while len(resultado) >= 2:
        fechamento = _FECHAMENTO_POR_ABERTURA.get(resultado[0])
        if fechamento is None or resultado[-1] != fechamento:
            break
        resultado = resultado[1:-1].strip()
    return resultado.casefold()


def _valor_delimitado(
    valor: str,
    delimitadores: tuple[str, str],
) -> str:
    abertura, fechamento = delimitadores
    return f"{abertura}{valor}{fechamento}"


def _parte_rotulada(
    *,
    nome_campo: str,
    valor_original: str,
    tipo: TipoIdentificador,
    namespace: str,
    regra: str,
    aspas_nome: str,
    separador: str,
    espaco_antes: str,
    espaco_depois: str,
) -> _ParteMensagem:
    texto = (
        f"{aspas_nome}{nome_campo}{aspas_nome}{espaco_antes}"
        f"{separador}{espaco_depois}{valor_original}"
    )
    inicio = texto.index(valor_original)
    return _ParteMensagem(
        texto=texto,
        identificador=_IdentificadorEsperado(
            tipo=tipo,
            namespace=namespace,
            nome_campo=nome_campo,
            valor_original=valor_original,
            valor_normalizado=_normalizar_referencia(valor_original),
            regra=regra,
            inicio=inicio,
            fim=inicio + len(valor_original),
        ),
    )


def _proveniencia(
    *,
    nome_campo: str,
    inicio: int,
    fim: int,
    regra: str,
) -> Proveniencia:
    return Proveniencia(
        arquivo_token=_ARQUIVO_TOKEN,
        entrada_id=_ENTRADA_ID,
        linha_inicial=1,
        linha_final=1,
        span_inicial=inicio,
        span_final=fim,
        nome_campo=nome_campo,
        regra_extracao=regra,
    )


def _campo(
    *,
    nome: str,
    valor: str,
    inicio: int,
    fim: int,
    regra: str,
) -> CampoEstruturado:
    return CampoEstruturado(
        nome=nome,
        valor_original=valor,
        proveniencia=_proveniencia(
            nome_campo=nome,
            inicio=inicio,
            fim=fim,
            regra=regra,
        ),
    )


def _percentuais() -> SearchStrategy[str]:
    return st.tuples(
        st.integers(min_value=0, max_value=100_000),
        st.one_of(
            st.none(),
            st.text(alphabet=string.digits, min_size=1, max_size=6),
        ),
    ).map(
        lambda partes: (
            f"{partes[0]}%"
            if partes[1] is None
            else f"{partes[0]}.{partes[1]}%"
        )
    )


def _timestamps_vpl_reais() -> SearchStrategy[TimestampSpec]:
    return vpl_timestamps().filter(lambda timestamp: timestamp.precision >= 1)


@st.composite
def _casos_vpl_reais(draw: st.DrawFn) -> _CasoVpl:
    timestamp = draw(_timestamps_vpl_reais())
    percentual = draw(_percentuais())
    severidade = draw(st.sampled_from(_SEVERIDADES))

    inicio_origem = draw(st.sampled_from(string.ascii_letters))
    restante_origem = draw(
        st.text(
            alphabet=string.ascii_letters + string.digits + "_-.:",
            min_size=0,
            max_size=16,
        )
    )
    origem = f"{inicio_origem}{restante_origem}.c:{draw(st.integers(1, 99999))}"

    unicode_gerado = draw(
        st.text(alphabet=_CARACTERES_UNICODE, min_size=1, max_size=12)
    )
    valores_chamada = draw(
        st.lists(
            opaque_values("CALL", min_bytes=3, max_bytes=8),
            min_size=5,
            max_size=5,
            unique=True,
        )
    )
    uuids = draw(
        st.lists(
            st.uuids(version=4),
            min_size=4,
            max_size=4,
            unique=True,
        )
    )
    caixa_uuid = draw(
        st.lists(st.booleans(), min_size=4, max_size=4)
    )
    valores_uuid = tuple(
        str(valor).upper() if maiusculo else str(valor)
        for valor, maiusculo in zip(uuids, caixa_uuid, strict=True)
    )

    delimitadores_call_id = draw(
        st.lists(
            st.sampled_from(_DELIMITADORES),
            min_size=3,
            max_size=3,
        )
    )
    delimitador_sip = draw(st.sampled_from(_DELIMITADORES_SIP))
    delimitadores_uuid = draw(
        st.lists(
            st.sampled_from(_DELIMITADORES),
            min_size=2,
            max_size=2,
        )
    )
    aspas_nomes = draw(
        st.lists(st.sampled_from(("", '"', "'")), min_size=5, max_size=5)
    )
    separadores = draw(
        st.lists(st.sampled_from(("=", ":")), min_size=5, max_size=5)
    )
    espacos = draw(
        st.lists(
            st.tuples(
                st.sampled_from(_ESPACOS_DE_CAMPO),
                st.sampled_from(_ESPACOS_DE_CAMPO),
            ),
            min_size=5,
            max_size=5,
        )
    )

    partes: dict[str, _ParteMensagem] = {}
    for indice, nome_campo in enumerate(("CALLID", "CallId", "call-id")):
        partes[f"call-{indice}"] = _parte_rotulada(
            nome_campo=nome_campo,
            valor_original=_valor_delimitado(
                valores_chamada[indice],
                delimitadores_call_id[indice],
            ),
            tipo=TipoIdentificador.CALL_ID,
            namespace="chamada_externa",
            regra=_REGRA_CALL_ID,
            aspas_nome=aspas_nomes[indice],
            separador=separadores[indice],
            espaco_antes=espacos[indice][0],
            espaco_depois=espacos[indice][1],
        )

    perfil_sip = draw(
        st.text(
            alphabet=string.ascii_letters + string.digits + "_.-",
            min_size=1,
            max_size=12,
        )
    )
    valor_sip = _valor_delimitado(valores_chamada[3], delimitador_sip)
    texto_sip = (
        f"canal=sofia/{perfil_sip}/{valor_sip}@sip.synthetic.invalid"
    )
    inicio_sip = texto_sip.index(valor_sip)
    partes["sip"] = _ParteMensagem(
        texto=texto_sip,
        identificador=_IdentificadorEsperado(
            tipo=TipoIdentificador.CHAMADA_EXTERNA,
            namespace="chamada_externa",
            nome_campo="SipChannelUser",
            valor_original=valor_sip,
            valor_normalizado=_normalizar_referencia(valor_sip),
            regra=_REGRA_CANAL_SIP,
            inicio=inicio_sip,
            fim=inicio_sip + len(valor_sip),
        ),
    )

    nome_uuid_canal = draw(
        st.sampled_from(
            (
                "channel_uuid",
                "channel-uuid",
                "channeluuid",
                "CHANNEL_UUID",
            )
        )
    )
    valor_uuid_canal = _valor_delimitado(
        valores_uuid[1],
        delimitadores_uuid[0],
    )
    partes["uuid-canal"] = _parte_rotulada(
        nome_campo=nome_uuid_canal,
        valor_original=valor_uuid_canal,
        tipo=TipoIdentificador.UUID_CANAL,
        namespace="uuid_canal",
        regra=_REGRA_UUID_CANAL,
        aspas_nome=aspas_nomes[3],
        separador=separadores[3],
        espaco_antes=espacos[3][0],
        espaco_depois=espacos[3][1],
    )

    nome_uuid_sessao = draw(
        st.sampled_from(
            (
                "session_uuid",
                "session-uuid",
                "sessionuuid",
                "session_id",
                "session-id",
                "sessionid",
                "SESSION_UUID",
            )
        )
    )
    valor_uuid_sessao = _valor_delimitado(
        valores_uuid[2],
        delimitadores_uuid[1],
    )
    partes["uuid-sessao"] = _parte_rotulada(
        nome_campo=nome_uuid_sessao,
        valor_original=valor_uuid_sessao,
        tipo=TipoIdentificador.UUID_SESSAO,
        namespace="uuid_sessao",
        regra=_REGRA_UUID_SESSAO,
        aspas_nome=aspas_nomes[4],
        separador=separadores[4],
        espaco_antes=espacos[4][0],
        espaco_depois=espacos[4][1],
    )

    partes["uuid-incidental"] = _ParteMensagem(
        texto=f"uuid_incidental={valores_uuid[3]}"
    )
    partes["campo-nao-aprovado"] = _ParteMensagem(
        texto=f"callid=<{valores_chamada[4]}>"
    )

    ordem_partes = draw(st.permutations(tuple(partes)))
    fragmentos_mensagem = [f"evento Unicode {unicode_gerado}"]
    cursor_mensagem = len(fragmentos_mensagem[0])
    identificadores_mensagem: list[_IdentificadorEsperado] = []
    for chave in ordem_partes:
        parte = partes[chave]
        cursor_mensagem += 1
        fragmentos_mensagem.append(parte.texto)
        if parte.identificador is not None:
            identificador = parte.identificador
            identificadores_mensagem.append(
                _IdentificadorEsperado(
                    tipo=identificador.tipo,
                    namespace=identificador.namespace,
                    nome_campo=identificador.nome_campo,
                    valor_original=identificador.valor_original,
                    valor_normalizado=identificador.valor_normalizado,
                    regra=identificador.regra,
                    inicio=cursor_mensagem + identificador.inicio,
                    fim=cursor_mensagem + identificador.fim,
                )
            )
        cursor_mensagem += len(parte.texto)
    mensagem = " ".join(fragmentos_mensagem)

    incluir_uuid_prefixo = draw(st.booleans())
    uuid_prefixo = valores_uuid[0]
    prefixo = f"{uuid_prefixo} " if incluir_uuid_prefixo else ""
    inicio_timestamp = len(prefixo)
    fim_timestamp = inicio_timestamp + len(timestamp.original)
    inicio_percentual = fim_timestamp + 1
    fim_percentual = inicio_percentual + len(percentual)
    inicio_token_severidade = fim_percentual + 1
    inicio_severidade = inicio_token_severidade + 1
    fim_severidade = inicio_severidade + len(severidade)
    inicio_origem_no_texto = fim_severidade + 2
    fim_origem_no_texto = inicio_origem_no_texto + len(origem)
    inicio_mensagem = fim_origem_no_texto + 1
    texto = (
        f"{prefixo}{timestamp.original} {percentual} [{severidade}] "
        f"{origem} {mensagem}"
    )

    campos: list[CampoEstruturado] = []
    identificadores: list[IdentificadorTecnico] = []
    if incluir_uuid_prefixo:
        campo_uuid_prefixo = _campo(
            nome="ChannelUuid",
            valor=uuid_prefixo,
            inicio=0,
            fim=len(uuid_prefixo),
            regra=_REGRA_UUID_PREFIXO,
        )
        campos.append(campo_uuid_prefixo)
        identificadores.append(
            IdentificadorTecnico(
                tipo=TipoIdentificador.UUID_CANAL,
                namespace_comparacao="uuid_canal",
                nome_campo="ChannelUuid",
                valor_original=uuid_prefixo,
                valor_normalizado=uuid_prefixo.casefold(),
                proveniencia=campo_uuid_prefixo.proveniencia,
            )
        )

    campos.extend(
        (
            _campo(
                nome="timestamp",
                valor=timestamp.original,
                inicio=inicio_timestamp,
                fim=fim_timestamp,
                regra=_REGRA_CABECALHO,
            ),
            _campo(
                nome="percentual_operacional",
                valor=percentual,
                inicio=inicio_percentual,
                fim=fim_percentual,
                regra=_REGRA_CABECALHO,
            ),
            _campo(
                nome="severidade",
                valor=severidade,
                inicio=inicio_severidade,
                fim=fim_severidade,
                regra=_REGRA_CABECALHO,
            ),
            _campo(
                nome="origem",
                valor=origem,
                inicio=inicio_origem_no_texto,
                fim=fim_origem_no_texto,
                regra=_REGRA_CABECALHO,
            ),
            _campo(
                nome="mensagem",
                valor=mensagem,
                inicio=inicio_mensagem,
                fim=len(texto),
                regra=_REGRA_CABECALHO,
            ),
        )
    )

    identificadores_mensagem.sort(
        key=lambda item: (item.inicio, item.fim, item.nome_campo)
    )
    for esperado in identificadores_mensagem:
        inicio_absoluto = inicio_mensagem + esperado.inicio
        fim_absoluto = inicio_mensagem + esperado.fim
        campo = _campo(
            nome=esperado.nome_campo,
            valor=esperado.valor_original,
            inicio=inicio_absoluto,
            fim=fim_absoluto,
            regra=esperado.regra,
        )
        campos.append(campo)
        identificadores.append(
            IdentificadorTecnico(
                tipo=esperado.tipo,
                namespace_comparacao=esperado.namespace,
                nome_campo=esperado.nome_campo,
                valor_original=esperado.valor_original,
                valor_normalizado=esperado.valor_normalizado,
                proveniencia=campo.proveniencia,
            )
        )

    entrada_esperada = EntradaDeLog(
        texto_original=texto,
        aplicacao="VPL",
        ordem_de_leitura=0,
        interpretada=True,
        carimbo_de_tempo=timestamp.source_datetime,
        nivel_de_severidade=severidade,
        mensagem=mensagem,
        entrada_id=_ENTRADA_ID,
        arquivo_token=_ARQUIVO_TOKEN,
        posicao_inicial=1,
        posicao_final=1,
        timestamp_original=timestamp.original,
        timestamp_normalizado=timestamp.expected_utc,
        precisao_fracionaria=timestamp.precision,
        origem_evento=origem,
        formato_origem="vpl-real",
        campos_estruturados=tuple(campos),
        identificadores=tuple(identificadores),
        falhas=(),
    )
    return _CasoVpl(
        texto=texto,
        mensagem=mensagem,
        unicode_gerado=unicode_gerado,
        entrada_esperada=entrada_esperada,
        valores_incidentais_normalizados=(
            valores_uuid[3].casefold(),
            valores_chamada[4].casefold(),
        ),
    )


# Feature: log-analyzer-phase-2, Property 1: Parsing VPL completo e tipado
@given(caso=_casos_vpl_reais())
@settings(max_examples=100, deadline=500)
def test_property_01_parsing_vpl_completo_e_tipado(caso: _CasoVpl) -> None:
    """O parser real equivale ao modelo gerado e não infere IDs incidentais.

    **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.6, 7.1**
    """

    assert_no_raw_source_reference(caso)

    entrada = VplParser().interpretar_entrada(caso.texto)

    assert entrada == caso.entrada_esperada
    assert entrada.campos_estruturados == (
        caso.entrada_esperada.campos_estruturados
    )
    assert entrada.identificadores == caso.entrada_esperada.identificadores
    assert entrada.texto_original == caso.texto
    assert entrada.mensagem == caso.mensagem
    assert caso.unicode_gerado in entrada.texto_original
    assert caso.unicode_gerado in (entrada.mensagem or "")
    assert any(ord(caractere) > 127 for caractere in caso.unicode_gerado)

    campos_por_proveniencia = {
        (
            campo.nome,
            campo.proveniencia.span_inicial,
            campo.proveniencia.span_final,
        ): campo
        for campo in entrada.campos_estruturados
    }
    for identificador in entrada.identificadores:
        chave = (
            identificador.nome_campo,
            identificador.proveniencia.span_inicial,
            identificador.proveniencia.span_final,
        )
        assert identificador.proveniencia is (
            campos_por_proveniencia[chave].proveniencia
        )

    normalizados = {
        identificador.valor_normalizado
        for identificador in entrada.identificadores
    }
    assert normalizados.isdisjoint(caso.valores_incidentais_normalizados)
