"""Parser de Aplicação para logs reais e legados do VPL.

O perfil real é tentado antes do formato sintético da Fase 1::

    [CHANNEL_UUID ]YYYY-MM-DD HH:MM:SS.ffffff PERCENT% [LEVEL] ORIGIN message

A interpretação é feita em etapas pequenas e ancoradas. Linhas com prefixo
VPL aparente que falham em qualquer campo obrigatório são classificadas como
cabeçalhos aparentes inválidos, evitando que o agrupador multiline as anexe ao
evento anterior.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re

from log_analyzer.core.identificadores import NormalizadorDeIdentificador
from log_analyzer.core.interfaces import Parser_de_Aplicacao, TipoInicio
from log_analyzer.core.modelos import (
    CampoEstruturado,
    EntradaDeLog,
    EntradaIndexada,
    FalhaDeEntrada,
    IdentificadorTecnico,
    Proveniencia,
    TipoIdentificador,
)
from log_analyzer.core.multiline import BlocoLog
from log_analyzer.core.streaming import LinhaFisica
from log_analyzer.core.temporal import NormalizadorTemporal

_NIVEIS_VPL: frozenset[str] = frozenset(
    {"DEBUG", "INFO", "NOTICE", "WARNING", "ERR", "CRIT", "ALERT"}
)

_APLICACAO = "VPL"
_FORMATO_REAL = "vpl-real"
_FORMATO_LEGADO = "vpl-legado"
_ARQUIVO_DIRETO = "<ARQUIVO_1>"
_ENTRADA_DIRETA = f"{_ARQUIVO_DIRETO}:entrada:0"

_REGRA_CABECALHO_REAL = "vpl.cabecalho.real.v1"
_REGRA_CABECALHO_LEGADO = "vpl.cabecalho.legado.v1"
_REGRA_UUID_PREFIXO = "vpl.uuid-canal-prefixo.v1"
_REGRA_CALL_ID = "vpl.identificador-chamada-rotulado.v1"
_REGRA_CANAL_SIP = "vpl.canal-sip-usuario.v1"
_REGRA_UUID_CANAL = "vpl.uuid-canal-rotulado.v1"
_REGRA_UUID_SESSAO = "vpl.uuid-sessao-rotulado.v1"

_CODIGO_CABECALHO_INVALIDO = "VPL_CABECALHO_APARENTE_INVALIDO"
_CODIGO_CONTINUACAO_ORFA = "VPL_CONTINUACAO_ORFA"

_TIMESTAMP_REAL = re.compile(
    r"\d{4}-\d{2}-\d{2} "
    r"\d{2}:\d{2}:\d{2}\."
    r"(?P<fracao>\d{1,6})\Z"
)
_TIMESTAMP_LEGADO = re.compile(
    r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}\Z"
)
_PERCENTUAL_REAL = re.compile(r"\d+(?:\.\d+)?%\Z")
_UUID_CANONICO = re.compile(
    r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\Z"
)

_VALOR_ROTULADO = (
    r'''(?P<valor>"[^"\r\n]+"|'[^'\r\n]+'|<[^<>\r\n]+>|'''
    r'''\[[^\[\]\r\n]+\]|\([^()\r\n]+\)|\{[^{}\r\n]+\}|'''
    r'''[^\s,;}\]\)\r\n]+)'''
)
_PADRAO_CALL_ID = re.compile(
    r'''(?<!\w)(?P<aspas>["']?)'''
    r'''(?P<nome>CALLID|CallId|call-id)(?P=aspas)\s*(?:=|:)\s*'''
    + _VALOR_ROTULADO
)
_PADRAO_UUID_ROTULADO = re.compile(
    r'''(?<!\w)(?P<aspas>["']?)'''
    r'''(?P<nome>channel(?:[_-]?uuid)|session(?:[_-]?(?:uuid|id)))'''
    r'''(?P=aspas)\s*(?:=|:)\s*'''
    + _VALOR_ROTULADO,
    flags=re.IGNORECASE,
)
_PADRAO_CANAL_SIP = re.compile(
    r"(?<![\w/])sofia/"
    r"(?P<perfil>[A-Za-z0-9_.-]+)/"
    r"(?P<valor><[^<>\s/@]+>|[^<>\s/@,;]+)"
    r"@(?P<destino>[^\s,;]+)",
    flags=re.IGNORECASE,
)

_CAMPOS_DE_CABECALHO = frozenset(
    {
        "ChannelUuid",
        "timestamp",
        "percentual_operacional",
        "severidade",
        "origem",
    }
)
_REGRAS_DE_CABECALHO = frozenset(
    {_REGRA_CABECALHO_REAL, _REGRA_CABECALHO_LEGADO, _REGRA_UUID_PREFIXO}
)


@dataclass(frozen=True, slots=True)
class _ValorComSpan:
    valor: str
    inicio: int
    fim: int


@dataclass(frozen=True, slots=True)
class _CabecalhoReal:
    uuid_canal: _ValorComSpan | None
    timestamp: _ValorComSpan
    carimbo: datetime
    precisao: int
    percentual: _ValorComSpan
    severidade: _ValorComSpan
    origem: _ValorComSpan
    mensagem: _ValorComSpan


@dataclass(frozen=True, slots=True)
class _CabecalhoLegado:
    timestamp: _ValorComSpan
    carimbo: datetime
    severidade: _ValorComSpan
    origem: _ValorComSpan
    mensagem: _ValorComSpan


@dataclass(frozen=True, slots=True)
class _ContextoEntrada:
    arquivo_token: str
    entrada_id: str
    ordem_de_leitura: int
    linha_inicial: int
    linha_final: int


@dataclass(frozen=True, slots=True)
class _CandidatoIdentificador:
    nome: str
    valor: str
    tipo: TipoIdentificador
    inicio: int
    fim: int
    regra: str


class VplParser(Parser_de_Aplicacao):
    """Parser VPL com perfil real, multiline e fallback legado."""

    def __init__(self) -> None:
        self._normalizador_temporal = NormalizadorTemporal()
        self._normalizador_identificador = NormalizadorDeIdentificador()

    @property
    def niveis_de_severidade(self) -> frozenset[str]:
        """Conjunto de níveis de severidade válidos do FreeSWITCH."""

        return _NIVEIS_VPL

    def detectar_inicio(self, linha: LinhaFisica) -> TipoInicio:
        """Classifica uma linha para o agrupador multiline trivalente."""

        if not isinstance(linha, LinhaFisica):
            raise TypeError("linha deve ser LinhaFisica.")
        if linha.texto is None:
            return TipoInicio.CONTINUACAO

        texto = linha.texto
        if self._analisar_real(texto) is not None:
            return TipoInicio.CABECALHO_VALIDO
        if self._analisar_legado(texto) is not None:
            return TipoInicio.CABECALHO_VALIDO
        if self._tem_prefixo_temporal_aparente(texto):
            return TipoInicio.CABECALHO_APARENTE_INVALIDO
        return TipoInicio.CONTINUACAO

    def interpretar_entrada(self, texto: str) -> EntradaDeLog:
        """Interpreta texto materializado, inclusive conteúdo multiline."""

        if not isinstance(texto, str):
            raise TypeError("texto deve ser string.")
        return self._interpretar_com_contexto(texto, self._contexto_direto(texto))

    def interpretar_bloco(self, bloco: BlocoLog) -> EntradaIndexada:
        """Interpreta metadados de um bloco sem reter seu texto no índice.

        Os digests de identificadores permanecem vazios nesta camada. Eles
        dependem da chave HMAC efêmera do índice e não podem ser produzidos pelo
        parser. Os identificadores completos ficam na entrada materializada.
        """

        if not isinstance(bloco, BlocoLog):
            raise TypeError("bloco deve ser BlocoLog.")

        texto_ref = bloco.texto_ref
        texto = bloco.texto_original
        if texto_ref is None or texto is None:
            raise ValueError(
                "bloco sem referência textual exata não pode ser interpretado."
            )

        contexto = _ContextoEntrada(
            arquivo_token=bloco.arquivo_token,
            entrada_id=bloco.entrada_id,
            ordem_de_leitura=bloco.ordem_de_leitura,
            linha_inicial=bloco.linha_inicial,
            linha_final=bloco.linha_final,
        )

        if not bloco.interpretavel:
            codigo = (
                _CODIGO_CABECALHO_INVALIDO
                if bloco.tipo_inicio is TipoInicio.CABECALHO_APARENTE_INVALIDO
                else _CODIGO_CONTINUACAO_ORFA
            )
            falha = self._falha_de_entrada(contexto, codigo)
            return EntradaIndexada(
                entrada_id=bloco.entrada_id,
                aplicacao=_APLICACAO,
                ordem_de_leitura=bloco.ordem_de_leitura,
                texto_ref=texto_ref,
                cabecalho=(),
                identificadores_digest=(),
                timestamp_original=None,
                timestamp_normalizado=None,
                falhas=(falha,),
                interpretada=False,
            )

        entrada = self._interpretar_com_contexto(texto, contexto)
        cabecalho = tuple(
            campo
            for campo in entrada.campos_estruturados
            if campo.nome in _CAMPOS_DE_CABECALHO
            and campo.proveniencia.regra_extracao in _REGRAS_DE_CABECALHO
        )
        return EntradaIndexada(
            entrada_id=bloco.entrada_id,
            aplicacao=_APLICACAO,
            ordem_de_leitura=bloco.ordem_de_leitura,
            texto_ref=texto_ref,
            cabecalho=cabecalho,
            identificadores_digest=(),
            timestamp_original=entrada.timestamp_original,
            timestamp_normalizado=entrada.timestamp_normalizado,
            falhas=entrada.falhas,
            interpretada=entrada.interpretada,
        )

    def imprimir_entrada(self, entrada: EntradaDeLog) -> str:
        """Produz a forma canônica do perfil que originou a entrada."""

        if not entrada.interpretada:
            return entrada.texto_original

        assert entrada.carimbo_de_tempo is not None
        assert entrada.nivel_de_severidade is not None
        assert entrada.mensagem is not None

        if entrada.formato_origem == _FORMATO_REAL:
            timestamp = entrada.timestamp_original
            if timestamp is None:
                raise ValueError("entrada VPL real não preserva timestamp_original.")
            percentual = self._valor_do_campo(
                entrada,
                "percentual_operacional",
                regra=_REGRA_CABECALHO_REAL,
            )
            origem = self._valor_do_campo(
                entrada,
                "origem",
                regra=_REGRA_CABECALHO_REAL,
            )
            uuid_canal = self._valor_opcional_do_campo(
                entrada,
                "ChannelUuid",
                regra=_REGRA_UUID_PREFIXO,
            )
            prefixo_uuid = f"{uuid_canal} " if uuid_canal is not None else ""
            return (
                f"{prefixo_uuid}{timestamp} {percentual} "
                f"[{entrada.nivel_de_severidade}] {origem} {entrada.mensagem}"
            )

        # Mantém a forma sintética da Fase 1 e sua origem canônica como fallback.
        origem = (
            self._valor_opcional_do_campo(
                entrada,
                "origem",
                regra=_REGRA_CABECALHO_LEGADO,
            )
            or entrada.origem_evento
            or "vpl_source"
        )
        millis = entrada.carimbo_de_tempo.microsecond // 1000
        timestamp = (
            entrada.carimbo_de_tempo.strftime("%Y-%m-%d %H:%M:%S")
            + f".{millis:03d}"
        )
        return (
            f"{timestamp} [{entrada.nivel_de_severidade}] "
            f"{origem} {entrada.mensagem}"
        )

    def _interpretar_com_contexto(
        self,
        texto: str,
        contexto: _ContextoEntrada,
    ) -> EntradaDeLog:
        real = self._analisar_real(texto)
        if real is not None:
            return self._materializar_real(texto, contexto, real)

        legado = self._analisar_legado(texto)
        if legado is not None:
            return self._materializar_legado(texto, contexto, legado)

        falhas = (
            (
                self._falha_de_entrada(
                    contexto,
                    _CODIGO_CABECALHO_INVALIDO,
                ),
            )
            if self._tem_prefixo_temporal_aparente(texto)
            else ()
        )
        return EntradaDeLog(
            texto_original=texto,
            aplicacao=_APLICACAO,
            ordem_de_leitura=contexto.ordem_de_leitura,
            interpretada=False,
            entrada_id=contexto.entrada_id,
            arquivo_token=contexto.arquivo_token,
            posicao_inicial=contexto.linha_inicial,
            posicao_final=contexto.linha_final,
            falhas=falhas,
        )

    def _materializar_real(
        self,
        texto: str,
        contexto: _ContextoEntrada,
        cabecalho: _CabecalhoReal,
    ) -> EntradaDeLog:
        campos: list[CampoEstruturado] = []
        identificadores: list[IdentificadorTecnico] = []

        if cabecalho.uuid_canal is not None:
            campo_uuid = self._campo(
                texto,
                contexto,
                "ChannelUuid",
                cabecalho.uuid_canal,
                _REGRA_UUID_PREFIXO,
            )
            campos.append(campo_uuid)
            identificadores.append(
                self._normalizador_identificador.normalizar(
                    TipoIdentificador.UUID_CANAL,
                    campo_uuid.nome,
                    campo_uuid.valor_original,
                    campo_uuid.proveniencia,
                )
            )

        campos.extend(
            (
                self._campo(
                    texto,
                    contexto,
                    "timestamp",
                    cabecalho.timestamp,
                    _REGRA_CABECALHO_REAL,
                ),
                self._campo(
                    texto,
                    contexto,
                    "percentual_operacional",
                    cabecalho.percentual,
                    _REGRA_CABECALHO_REAL,
                ),
                self._campo(
                    texto,
                    contexto,
                    "severidade",
                    cabecalho.severidade,
                    _REGRA_CABECALHO_REAL,
                ),
                self._campo(
                    texto,
                    contexto,
                    "origem",
                    cabecalho.origem,
                    _REGRA_CABECALHO_REAL,
                ),
                self._campo(
                    texto,
                    contexto,
                    "mensagem",
                    cabecalho.mensagem,
                    _REGRA_CABECALHO_REAL,
                ),
            )
        )

        campo_timestamp = next(
            campo for campo in campos if campo.nome == "timestamp"
        )
        temporal = self._normalizador_temporal.normalizar_vpl(
            cabecalho.timestamp.valor,
            campo_timestamp.proveniencia,
        )
        campos_ids, ids_mensagem = self._extrair_identificadores(
            texto,
            contexto,
            cabecalho.mensagem,
        )
        campos.extend(campos_ids)
        identificadores.extend(ids_mensagem)

        return EntradaDeLog(
            texto_original=texto,
            aplicacao=_APLICACAO,
            ordem_de_leitura=contexto.ordem_de_leitura,
            interpretada=True,
            carimbo_de_tempo=cabecalho.carimbo,
            nivel_de_severidade=cabecalho.severidade.valor,
            mensagem=cabecalho.mensagem.valor,
            entrada_id=contexto.entrada_id,
            arquivo_token=contexto.arquivo_token,
            posicao_inicial=contexto.linha_inicial,
            posicao_final=contexto.linha_final,
            timestamp_original=cabecalho.timestamp.valor,
            timestamp_normalizado=temporal.timestamp_normalizado,
            precisao_fracionaria=temporal.precisao_fracionaria,
            origem_evento=cabecalho.origem.valor,
            formato_origem=_FORMATO_REAL,
            campos_estruturados=tuple(campos),
            identificadores=tuple(identificadores),
            falhas=temporal.falhas,
        )

    def _materializar_legado(
        self,
        texto: str,
        contexto: _ContextoEntrada,
        cabecalho: _CabecalhoLegado,
    ) -> EntradaDeLog:
        campos = [
            self._campo(
                texto,
                contexto,
                "timestamp",
                cabecalho.timestamp,
                _REGRA_CABECALHO_LEGADO,
            ),
            self._campo(
                texto,
                contexto,
                "severidade",
                cabecalho.severidade,
                _REGRA_CABECALHO_LEGADO,
            ),
            self._campo(
                texto,
                contexto,
                "origem",
                cabecalho.origem,
                _REGRA_CABECALHO_LEGADO,
            ),
            self._campo(
                texto,
                contexto,
                "mensagem",
                cabecalho.mensagem,
                _REGRA_CABECALHO_LEGADO,
            ),
        ]
        temporal = self._normalizador_temporal.normalizar_vpl(
            cabecalho.timestamp.valor,
            campos[0].proveniencia,
        )
        campos_ids, identificadores = self._extrair_identificadores(
            texto,
            contexto,
            cabecalho.mensagem,
        )
        campos.extend(campos_ids)

        return EntradaDeLog(
            texto_original=texto,
            aplicacao=_APLICACAO,
            ordem_de_leitura=contexto.ordem_de_leitura,
            interpretada=True,
            carimbo_de_tempo=cabecalho.carimbo,
            nivel_de_severidade=cabecalho.severidade.valor,
            mensagem=cabecalho.mensagem.valor,
            entrada_id=contexto.entrada_id,
            arquivo_token=contexto.arquivo_token,
            posicao_inicial=contexto.linha_inicial,
            posicao_final=contexto.linha_final,
            timestamp_original=cabecalho.timestamp.valor,
            timestamp_normalizado=temporal.timestamp_normalizado,
            precisao_fracionaria=temporal.precisao_fracionaria,
            origem_evento=cabecalho.origem.valor,
            formato_origem=_FORMATO_LEGADO,
            campos_estruturados=tuple(campos),
            identificadores=identificadores,
            falhas=temporal.falhas,
        )

    @staticmethod
    def _analisar_real(texto: str) -> _CabecalhoReal | None:
        primeiro_consumido = VplParser._consumir_token(texto, 0)
        if primeiro_consumido is None:
            return None
        primeiro, cursor = primeiro_consumido

        uuid_canal: _ValorComSpan | None = None
        if _UUID_CANONICO.fullmatch(primeiro.valor) is not None:
            uuid_canal = primeiro
            data_consumida = VplParser._consumir_token(texto, cursor)
            if data_consumida is None:
                return None
            data, cursor = data_consumida
        else:
            data = primeiro

        hora_consumida = VplParser._consumir_token(texto, cursor)
        if hora_consumida is None:
            return None
        hora, cursor = hora_consumida
        timestamp = _ValorComSpan(
            texto[data.inicio : hora.fim],
            data.inicio,
            hora.fim,
        )
        correspondencia_timestamp = _TIMESTAMP_REAL.fullmatch(timestamp.valor)
        if correspondencia_timestamp is None:
            return None
        try:
            carimbo = datetime.fromisoformat(timestamp.valor)
        except ValueError:
            return None
        precisao = len(correspondencia_timestamp.group("fracao"))

        percentual_consumido = VplParser._consumir_token(texto, cursor)
        if percentual_consumido is None:
            return None
        percentual, cursor = percentual_consumido
        if _PERCENTUAL_REAL.fullmatch(percentual.valor) is None:
            return None

        severidade_consumida = VplParser._consumir_token(texto, cursor)
        if severidade_consumida is None:
            return None
        severidade_delimitada, cursor = severidade_consumida
        severidade = VplParser._severidade_delimitada(severidade_delimitada)
        if severidade is None:
            return None

        origem_consumida = VplParser._consumir_token(texto, cursor)
        if origem_consumida is None:
            return None
        origem, cursor = origem_consumida

        mensagem_texto = texto[cursor:]
        if not mensagem_texto.strip():
            return None
        mensagem = _ValorComSpan(mensagem_texto, cursor, len(texto))

        return _CabecalhoReal(
            uuid_canal=uuid_canal,
            timestamp=timestamp,
            carimbo=carimbo,
            precisao=precisao,
            percentual=percentual,
            severidade=severidade,
            origem=origem,
            mensagem=mensagem,
        )

    @staticmethod
    def _analisar_legado(texto: str) -> _CabecalhoLegado | None:
        data_consumida = VplParser._consumir_token(texto, 0)
        if data_consumida is None:
            return None
        data, cursor = data_consumida

        hora_consumida = VplParser._consumir_token(texto, cursor)
        if hora_consumida is None:
            return None
        hora, cursor = hora_consumida
        timestamp = _ValorComSpan(
            texto[data.inicio : hora.fim],
            data.inicio,
            hora.fim,
        )
        if _TIMESTAMP_LEGADO.fullmatch(timestamp.valor) is None:
            return None
        try:
            carimbo = datetime.strptime(timestamp.valor, "%Y-%m-%d %H:%M:%S.%f")
        except ValueError:
            return None

        severidade_consumida = VplParser._consumir_token(texto, cursor)
        if severidade_consumida is None:
            return None
        severidade_delimitada, cursor = severidade_consumida
        severidade = VplParser._severidade_delimitada(severidade_delimitada)
        if severidade is None:
            return None

        origem_consumida = VplParser._consumir_token(texto, cursor)
        if origem_consumida is None:
            return None
        origem, cursor = origem_consumida

        mensagem_texto = texto[cursor:]
        if not mensagem_texto.strip():
            return None
        mensagem = _ValorComSpan(mensagem_texto, cursor, len(texto))

        return _CabecalhoLegado(
            timestamp=timestamp,
            carimbo=carimbo,
            severidade=severidade,
            origem=origem,
            mensagem=mensagem,
        )

    def _extrair_identificadores(
        self,
        texto: str,
        contexto: _ContextoEntrada,
        regiao: _ValorComSpan,
    ) -> tuple[list[CampoEstruturado], tuple[IdentificadorTecnico, ...]]:
        candidatos = self._candidatos_na_mensagem(regiao)
        candidatos.sort(key=lambda item: (item.inicio, item.fim, item.nome))

        campos: list[CampoEstruturado] = []
        identificadores: list[IdentificadorTecnico] = []
        vistos: set[tuple[int, int, TipoIdentificador, str]] = set()
        for candidato in candidatos:
            chave = (
                candidato.inicio,
                candidato.fim,
                candidato.tipo,
                candidato.nome,
            )
            if chave in vistos:
                continue
            vistos.add(chave)

            campo = self._campo(
                texto,
                contexto,
                candidato.nome,
                _ValorComSpan(
                    candidato.valor,
                    candidato.inicio,
                    candidato.fim,
                ),
                candidato.regra,
            )
            campos.append(campo)
            try:
                identificador = self._normalizador_identificador.normalizar(
                    candidato.tipo,
                    candidato.nome,
                    candidato.valor,
                    campo.proveniencia,
                )
            except ValueError:
                # Rótulos UUID inválidos permanecem no texto/campo, sem gerar
                # um identificador técnico parcial ou mudar a entrada inteira.
                continue
            identificadores.append(identificador)

        return campos, tuple(identificadores)

    @staticmethod
    def _candidatos_na_mensagem(
        regiao: _ValorComSpan,
    ) -> list[_CandidatoIdentificador]:
        candidatos: list[_CandidatoIdentificador] = []

        for correspondencia in _PADRAO_CALL_ID.finditer(regiao.valor):
            inicio_local, fim_local = correspondencia.span("valor")
            candidatos.append(
                _CandidatoIdentificador(
                    nome=correspondencia.group("nome"),
                    valor=correspondencia.group("valor"),
                    tipo=TipoIdentificador.CALL_ID,
                    inicio=regiao.inicio + inicio_local,
                    fim=regiao.inicio + fim_local,
                    regra=_REGRA_CALL_ID,
                )
            )

        for correspondencia in _PADRAO_CANAL_SIP.finditer(regiao.valor):
            inicio_local, fim_local = correspondencia.span("valor")
            candidatos.append(
                _CandidatoIdentificador(
                    nome="SipChannelUser",
                    valor=correspondencia.group("valor"),
                    tipo=TipoIdentificador.CHAMADA_EXTERNA,
                    inicio=regiao.inicio + inicio_local,
                    fim=regiao.inicio + fim_local,
                    regra=_REGRA_CANAL_SIP,
                )
            )

        for correspondencia in _PADRAO_UUID_ROTULADO.finditer(regiao.valor):
            nome = correspondencia.group("nome")
            tipo = (
                TipoIdentificador.UUID_CANAL
                if nome.casefold().startswith("channel")
                else TipoIdentificador.UUID_SESSAO
            )
            inicio_local, fim_local = correspondencia.span("valor")
            candidatos.append(
                _CandidatoIdentificador(
                    nome=nome,
                    valor=correspondencia.group("valor"),
                    tipo=tipo,
                    inicio=regiao.inicio + inicio_local,
                    fim=regiao.inicio + fim_local,
                    regra=(
                        _REGRA_UUID_CANAL
                        if tipo is TipoIdentificador.UUID_CANAL
                        else _REGRA_UUID_SESSAO
                    ),
                )
            )

        return candidatos

    def _campo(
        self,
        texto: str,
        contexto: _ContextoEntrada,
        nome: str,
        valor: _ValorComSpan,
        regra: str,
    ) -> CampoEstruturado:
        return CampoEstruturado(
            nome=nome,
            valor_original=valor.valor,
            proveniencia=self._proveniencia(
                texto,
                contexto,
                nome=nome,
                inicio=valor.inicio,
                fim=valor.fim,
                regra=regra,
            ),
        )

    @staticmethod
    def _proveniencia(
        texto: str,
        contexto: _ContextoEntrada,
        *,
        nome: str | None,
        inicio: int | None,
        fim: int | None,
        regra: str,
    ) -> Proveniencia:
        if inicio is None or fim is None:
            linha_inicial = contexto.linha_inicial
            linha_final = contexto.linha_final
        else:
            linha_inicial = contexto.linha_inicial + texto.count("\n", 0, inicio)
            ultimo_indice = inicio if fim <= inicio else fim - 1
            linha_final = contexto.linha_inicial + texto.count(
                "\n",
                0,
                ultimo_indice + 1,
            )
            # Um newline no fim exclusivo do span é o terminador da linha
            # anterior, não evidência de uma linha física adicional.
            if fim > inicio and texto[fim - 1] == "\n":
                linha_final -= 1

        return Proveniencia(
            arquivo_token=contexto.arquivo_token,
            entrada_id=contexto.entrada_id,
            linha_inicial=linha_inicial,
            linha_final=linha_final,
            span_inicial=inicio,
            span_final=fim,
            nome_campo=nome,
            regra_extracao=regra,
        )

    def _falha_de_entrada(
        self,
        contexto: _ContextoEntrada,
        codigo: str,
    ) -> FalhaDeEntrada:
        detalhe = (
            "Cabeçalho VPL aparente não pôde ser interpretado."
            if codigo == _CODIGO_CABECALHO_INVALIDO
            else "Continuação VPL sem cabeçalho anterior."
        )
        proveniencia = Proveniencia(
            arquivo_token=contexto.arquivo_token,
            entrada_id=contexto.entrada_id,
            linha_inicial=contexto.linha_inicial,
            linha_final=contexto.linha_final,
            regra_extracao=_REGRA_CABECALHO_REAL,
        )
        return FalhaDeEntrada(
            codigo=codigo,
            proveniencia=proveniencia,
            detalhe_seguro=detalhe,
        )

    @staticmethod
    def _consumir_token(
        texto: str,
        inicio: int,
    ) -> tuple[_ValorComSpan, int] | None:
        """Consome um token e exige outro campo na mesma linha física."""

        if inicio >= len(texto) or texto[inicio].isspace():
            return None

        fim = inicio
        while fim < len(texto) and not texto[fim].isspace():
            fim += 1
        if fim == len(texto):
            return None

        cursor = fim
        while cursor < len(texto) and texto[cursor] in " \t":
            cursor += 1
        if cursor == fim or cursor >= len(texto) or texto[cursor] in "\r\n":
            return None
        return _ValorComSpan(texto[inicio:fim], inicio, fim), cursor

    @staticmethod
    def _severidade_delimitada(
        token: _ValorComSpan,
    ) -> _ValorComSpan | None:
        if len(token.valor) < 3 or token.valor[0] != "[" or token.valor[-1] != "]":
            return None
        nivel = token.valor[1:-1]
        if nivel not in _NIVEIS_VPL:
            return None
        return _ValorComSpan(nivel, token.inicio + 1, token.fim - 1)

    @staticmethod
    def _tem_prefixo_temporal_aparente(texto: str) -> bool:
        if VplParser._parece_data_na_posicao(texto, 0):
            return True

        fim_token = 0
        while fim_token < len(texto) and not texto[fim_token].isspace():
            fim_token += 1
        if fim_token == 0 or fim_token == len(texto):
            return False
        if not VplParser._parece_uuid_posicional(texto[:fim_token]):
            return False

        cursor = fim_token
        while cursor < len(texto) and texto[cursor] in " \t":
            cursor += 1
        return VplParser._parece_data_na_posicao(texto, cursor)

    @staticmethod
    def _parece_data_na_posicao(texto: str, inicio: int) -> bool:
        fim = inicio + 10
        if inicio < 0 or fim > len(texto):
            return False
        candidato = texto[inicio:fim]
        if candidato[4:5] != "-" or candidato[7:8] != "-":
            return False
        if not (candidato[:4] + candidato[5:7] + candidato[8:]).isdigit():
            return False
        return fim == len(texto) or texto[fim].isspace()

    @staticmethod
    def _parece_uuid_posicional(token: str) -> bool:
        if len(token) != 36:
            return False
        if any(token[indice] != "-" for indice in (8, 13, 18, 23)):
            return False
        return all(
            caractere.isalnum()
            for indice, caractere in enumerate(token)
            if indice not in {8, 13, 18, 23}
        )

    @staticmethod
    def _contexto_direto(texto: str) -> _ContextoEntrada:
        quantidade_linhas = len(texto.splitlines()) or 1
        return _ContextoEntrada(
            arquivo_token=_ARQUIVO_DIRETO,
            entrada_id=_ENTRADA_DIRETA,
            ordem_de_leitura=0,
            linha_inicial=1,
            linha_final=quantidade_linhas,
        )

    @staticmethod
    def _valor_do_campo(
        entrada: EntradaDeLog,
        nome: str,
        *,
        regra: str,
    ) -> str:
        valor = VplParser._valor_opcional_do_campo(
            entrada,
            nome,
            regra=regra,
        )
        if valor is None:
            raise ValueError(
                f"entrada VPL real não possui campo obrigatório {nome!r}."
            )
        return valor

    @staticmethod
    def _valor_opcional_do_campo(
        entrada: EntradaDeLog,
        nome: str,
        *,
        regra: str,
    ) -> str | None:
        for campo in entrada.campos_estruturados:
            if (
                campo.nome == nome
                and campo.proveniencia.regra_extracao == regra
            ):
                return campo.valor_original
        return None
