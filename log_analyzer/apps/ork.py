"""Parser de Aplicação para logs reais e legados do ORK.

O perfil real é tentado antes do perfil pipe-delimited da Fase 1::

    ISO_TIMESTAMP HOST PROCESS[PID]: LEVEL - LOGGER - message

A interpretação do cabeçalho real é feita em etapas pequenas e ancoradas. Linhas
que começam com um prefixo ISO aparente, mas não satisfazem todos os campos
obrigatórios, são classificadas como cabeçalhos aparentes inválidos para que o
agrupador multiline inicie uma entrada própria.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re

from log_analyzer.core.identificadores import NormalizadorDeIdentificador
from log_analyzer.core.interfaces import (
    Parser_de_Aplicacao,
    TipoInicio,
)
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

_ORK_NIVEIS = frozenset({"DEBUG", "INFO", "WARN", "ERROR", "FATAL"})
_APLICACAO = "ORK"
_FORMATO_REAL = "ork-real"
_FORMATO_LEGADO = "ork-legado"
_ARQUIVO_DIRETO = "<ARQUIVO_1>"
_ENTRADA_DIRETA = f"{_ARQUIVO_DIRETO}:entrada:0"

_REGRA_CABECALHO_REAL = "ork.cabecalho.real.v1"
_REGRA_CABECALHO_LEGADO = "ork.cabecalho.legado.v1"
_REGRA_TELECOM_CALL_ID = "ork.telecom-identificador-chamada.v1"
_REGRA_CALL_ID = "ork.identificador-chamada.v1"
_REGRA_UUID_SESSAO = "ork.uuid-sessao-rotulado.v1"

_CODIGO_CABECALHO_INVALIDO = "ORK_CABECALHO_APARENTE_INVALIDO"
_CODIGO_CONTINUACAO_ORFA = "ORK_CONTINUACAO_ORFA"

_PREFIXO_ISO_APARENTE = re.compile(r"^\d{4}-\d{2}-\d{2}T")
_TIMESTAMP_REAL = re.compile(
    r"\d{4}-\d{2}-\d{2}T"
    r"\d{2}:\d{2}:\d{2}"
    r"(?:\.(?P<fracao>\d{1,6}))?"
    r"(?:Z|[+-]\d{2}:\d{2})\Z"
)
_PROCESSO_PID = re.compile(
    r"(?P<processo>[^\s\[\]:]+)\[(?P<pid>[0-9]+)\]:\Z"
)

_VALOR_ROTULADO = (
    r'''(?P<valor>"[^"\r\n]+"|'[^'\r\n]+'|<[^<>\r\n]+>|'''
    r'''\[[^\[\]\r\n]+\]|\([^()\r\n]+\)|\{[^{}\r\n]+\}|'''
    r'''[^\s,;}\]\)\r\n]+)'''
)
_PADRAO_ID_CHAMADA = re.compile(
    r'''(?<!\w)(?P<aspas>["']?)'''
    r'''(?P<nome>TelecomCallId|CallId)(?P=aspas)\s*(?:=|:)\s*'''
    + _VALOR_ROTULADO
)
_PADRAO_UUID_SESSAO = re.compile(
    r'''(?<!\w)(?P<aspas>["']?)'''
    r'''(?P<nome>session(?:_?uuid|_?id))(?P=aspas)\s*(?:=|:)\s*'''
    + _VALOR_ROTULADO,
    flags=re.IGNORECASE,
)

_CAMPOS_DE_CABECALHO = frozenset(
    {"timestamp", "host", "processo", "pid", "severidade", "logger"}
)


@dataclass(frozen=True, slots=True)
class _ValorComSpan:
    valor: str
    inicio: int
    fim: int


@dataclass(frozen=True, slots=True)
class _CabecalhoReal:
    timestamp: _ValorComSpan
    carimbo: datetime
    precisao: int
    host: _ValorComSpan
    processo: _ValorComSpan
    pid: _ValorComSpan
    severidade: _ValorComSpan
    logger: _ValorComSpan
    mensagem: _ValorComSpan


@dataclass(frozen=True, slots=True)
class _CabecalhoLegado:
    timestamp: _ValorComSpan
    carimbo: datetime
    severidade: _ValorComSpan
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


class OrkParser(Parser_de_Aplicacao):
    """Parser ORK compatível com o perfil real e o pipe legado da Fase 1."""

    def __init__(self) -> None:
        self._normalizador_temporal = NormalizadorTemporal()
        self._normalizador_identificador = NormalizadorDeIdentificador()

    @property
    def niveis_de_severidade(self) -> frozenset[str]:
        """Retorna os níveis preservados pelo contrato ORK da Fase 1."""

        return _ORK_NIVEIS

    def detectar_inicio(self, linha: LinhaFisica) -> TipoInicio:
        """Classifica uma linha para o agrupador multiline trivalente.

        Um perfil real ou legado completo abre um bloco interpretável. Qualquer
        linha com prefixo temporal ISO aparente que falhe na gramática abre um
        bloco não interpretado próprio; todo o restante é continuação.
        """

        if not isinstance(linha, LinhaFisica):
            raise TypeError("linha deve ser LinhaFisica.")
        if linha.texto is None:
            return TipoInicio.CONTINUACAO

        texto = linha.texto
        if self._analisar_real(texto) is not None:
            return TipoInicio.CABECALHO_VALIDO
        if self._analisar_legado(texto) is not None:
            return TipoInicio.CABECALHO_VALIDO
        if _PREFIXO_ISO_APARENTE.match(texto) is not None:
            return TipoInicio.CABECALHO_APARENTE_INVALIDO
        return TipoInicio.CONTINUACAO

    def interpretar_entrada(self, texto: str) -> EntradaDeLog:
        """Interpreta texto materializado, inclusive continuações multiline."""

        if not isinstance(texto, str):
            raise TypeError("texto deve ser string.")
        return self._interpretar_com_contexto(texto, self._contexto_direto(texto))

    def interpretar_bloco(self, bloco: BlocoLog) -> EntradaIndexada:
        """Interpreta um bloco agrupado sem perder sua referência de origem.

        Os digests dos identificadores ficam vazios nesta camada. A geração de
        HMAC depende da chave efêmera do índice e, portanto, não pertence ao
        parser. Os campos conhecidos continuam disponíveis na entrada
        materializada produzida por :meth:`interpretar_entrada`.
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
        """Produz forma canônica do perfil original para round-trip."""

        if not entrada.interpretada:
            return entrada.texto_original

        assert entrada.carimbo_de_tempo is not None
        assert entrada.nivel_de_severidade is not None
        assert entrada.mensagem is not None

        timestamp = entrada.timestamp_original or entrada.carimbo_de_tempo.isoformat()
        severidade = entrada.nivel_de_severidade
        for campo in entrada.campos_estruturados:
            if campo.nome == "severidade":
                severidade = campo.valor_original
                break

        if entrada.formato_origem == _FORMATO_REAL:
            host = self._valor_do_campo(entrada, "host")
            processo = self._valor_do_campo(entrada, "processo")
            pid = self._valor_do_campo(entrada, "pid")
            logger = self._valor_do_campo(entrada, "logger")
            return (
                f"{timestamp} {host} {processo}[{pid}]: "
                f"{severidade} - {logger} - {entrada.mensagem}"
            )

        return f"{timestamp} | {severidade} | {entrada.mensagem}"

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

        aparente = _PREFIXO_ISO_APARENTE.match(texto) is not None
        falhas = (
            (self._falha_de_entrada(contexto, _CODIGO_CABECALHO_INVALIDO),)
            if aparente
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
        campos = [
            self._campo(texto, contexto, "timestamp", cabecalho.timestamp, _REGRA_CABECALHO_REAL),
            self._campo(texto, contexto, "host", cabecalho.host, _REGRA_CABECALHO_REAL),
            self._campo(texto, contexto, "processo", cabecalho.processo, _REGRA_CABECALHO_REAL),
            self._campo(texto, contexto, "pid", cabecalho.pid, _REGRA_CABECALHO_REAL),
            self._campo(texto, contexto, "severidade", cabecalho.severidade, _REGRA_CABECALHO_REAL),
            self._campo(texto, contexto, "logger", cabecalho.logger, _REGRA_CABECALHO_REAL),
            self._campo(texto, contexto, "mensagem", cabecalho.mensagem, _REGRA_CABECALHO_REAL),
        ]

        proveniencia_timestamp = campos[0].proveniencia
        temporal = self._normalizador_temporal.normalizar_ork(
            cabecalho.timestamp.valor,
            proveniencia_timestamp,
        )
        campos_ids, identificadores = self._extrair_identificadores(
            texto,
            contexto,
            regioes=(cabecalho.logger, cabecalho.mensagem),
        )
        campos.extend(campos_ids)

        return EntradaDeLog(
            texto_original=texto,
            aplicacao=_APLICACAO,
            ordem_de_leitura=contexto.ordem_de_leitura,
            interpretada=True,
            carimbo_de_tempo=cabecalho.carimbo,
            nivel_de_severidade=cabecalho.severidade.valor.upper(),
            mensagem=cabecalho.mensagem.valor,
            entrada_id=contexto.entrada_id,
            arquivo_token=contexto.arquivo_token,
            posicao_inicial=contexto.linha_inicial,
            posicao_final=contexto.linha_final,
            timestamp_original=cabecalho.timestamp.valor,
            timestamp_normalizado=temporal.timestamp_normalizado,
            precisao_fracionaria=temporal.precisao_fracionaria,
            origem_evento=cabecalho.logger.valor,
            formato_origem=_FORMATO_REAL,
            campos_estruturados=tuple(campos),
            identificadores=identificadores,
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
                "mensagem",
                cabecalho.mensagem,
                _REGRA_CABECALHO_LEGADO,
            ),
        ]
        temporal = self._normalizador_temporal.normalizar_ork(
            cabecalho.timestamp.valor,
            campos[0].proveniencia,
        )
        campos_ids, identificadores = self._extrair_identificadores(
            texto,
            contexto,
            regioes=(cabecalho.mensagem,),
        )
        campos.extend(campos_ids)

        return EntradaDeLog(
            texto_original=texto,
            aplicacao=_APLICACAO,
            ordem_de_leitura=contexto.ordem_de_leitura,
            interpretada=True,
            carimbo_de_tempo=cabecalho.carimbo,
            nivel_de_severidade=cabecalho.severidade.valor.upper(),
            mensagem=cabecalho.mensagem.valor,
            entrada_id=contexto.entrada_id,
            arquivo_token=contexto.arquivo_token,
            posicao_inicial=contexto.linha_inicial,
            posicao_final=contexto.linha_final,
            timestamp_original=cabecalho.timestamp.valor,
            timestamp_normalizado=temporal.timestamp_normalizado,
            precisao_fracionaria=temporal.precisao_fracionaria,
            formato_origem=_FORMATO_LEGADO,
            campos_estruturados=tuple(campos),
            identificadores=identificadores,
            falhas=temporal.falhas,
        )

    @staticmethod
    def _analisar_real(texto: str) -> _CabecalhoReal | None:
        timestamp_consumido = OrkParser._consumir_token(texto, 0)
        if timestamp_consumido is None:
            return None
        timestamp, cursor = timestamp_consumido

        correspondencia_timestamp = _TIMESTAMP_REAL.fullmatch(timestamp.valor)
        if correspondencia_timestamp is None:
            return None
        try:
            texto_parse = (
                f"{timestamp.valor[:-1]}+00:00"
                if timestamp.valor.endswith("Z")
                else timestamp.valor
            )
            carimbo = datetime.fromisoformat(texto_parse)
        except ValueError:
            return None
        if carimbo.tzinfo is None or carimbo.utcoffset() is None:
            return None
        fracao = correspondencia_timestamp.group("fracao")
        precisao = len(fracao) if fracao is not None else 0

        host_consumido = OrkParser._consumir_token(texto, cursor)
        if host_consumido is None:
            return None
        host, cursor = host_consumido

        processo_consumido = OrkParser._consumir_token(texto, cursor)
        if processo_consumido is None:
            return None
        processo_pid, cursor = processo_consumido
        correspondencia_processo = _PROCESSO_PID.fullmatch(processo_pid.valor)
        if correspondencia_processo is None:
            return None

        delimitador_nivel = texto.find(" - ", cursor)
        if delimitador_nivel < 0:
            return None
        nivel_texto = texto[cursor:delimitador_nivel]
        if (
            not nivel_texto
            or nivel_texto.strip() != nivel_texto
            or any(caractere in "\r\n\t" for caractere in nivel_texto)
            or nivel_texto.upper() not in _ORK_NIVEIS
        ):
            return None
        severidade = _ValorComSpan(nivel_texto, cursor, delimitador_nivel)

        inicio_logger = delimitador_nivel + len(" - ")
        delimitador_logger = texto.find(" - ", inicio_logger)
        if delimitador_logger < 0:
            return None
        logger_texto = texto[inicio_logger:delimitador_logger]
        if (
            not logger_texto
            or logger_texto.strip() != logger_texto
            or any(caractere in "\r\n\t" for caractere in logger_texto)
        ):
            return None
        logger = _ValorComSpan(logger_texto, inicio_logger, delimitador_logger)

        inicio_mensagem = delimitador_logger + len(" - ")
        mensagem_texto = texto[inicio_mensagem:]
        if not mensagem_texto.strip():
            return None
        mensagem = _ValorComSpan(mensagem_texto, inicio_mensagem, len(texto))

        processo_inicio = processo_pid.inicio
        processo_texto = correspondencia_processo.group("processo")
        pid_texto = correspondencia_processo.group("pid")
        processo = _ValorComSpan(
            processo_texto,
            processo_inicio,
            processo_inicio + len(processo_texto),
        )
        pid_inicio = processo_inicio + len(processo_texto) + 1
        pid = _ValorComSpan(pid_texto, pid_inicio, pid_inicio + len(pid_texto))

        return _CabecalhoReal(
            timestamp=timestamp,
            carimbo=carimbo,
            precisao=precisao,
            host=host,
            processo=processo,
            pid=pid,
            severidade=severidade,
            logger=logger,
            mensagem=mensagem,
        )

    @staticmethod
    def _analisar_legado(texto: str) -> _CabecalhoLegado | None:
        primeiro = texto.find(" | ")
        if primeiro < 0:
            return None
        segundo = texto.find(" | ", primeiro + len(" | "))
        if segundo < 0:
            return None

        timestamp = OrkParser._recortar_strip(texto, 0, primeiro)
        severidade = OrkParser._recortar_strip(
            texto,
            primeiro + len(" | "),
            segundo,
        )
        mensagem = OrkParser._recortar_strip(
            texto,
            segundo + len(" | "),
            len(texto),
        )
        if timestamp is None or severidade is None or mensagem is None:
            return None
        if severidade.valor.upper() not in _ORK_NIVEIS:
            return None

        try:
            texto_parse = (
                f"{timestamp.valor[:-1]}+00:00"
                if timestamp.valor.endswith("Z")
                else timestamp.valor
            )
            carimbo = datetime.fromisoformat(texto_parse)
        except ValueError:
            return None

        return _CabecalhoLegado(
            timestamp=timestamp,
            carimbo=carimbo,
            severidade=severidade,
            mensagem=mensagem,
        )

    def _extrair_identificadores(
        self,
        texto: str,
        contexto: _ContextoEntrada,
        *,
        regioes: tuple[_ValorComSpan, ...],
    ) -> tuple[list[CampoEstruturado], tuple[IdentificadorTecnico, ...]]:
        candidatos: list[_CandidatoIdentificador] = []
        for regiao in regioes:
            candidatos.extend(self._candidatos_na_regiao(regiao))
        candidatos.sort(key=lambda item: (item.inicio, item.fim, item.nome))

        campos: list[CampoEstruturado] = []
        identificadores: list[IdentificadorTecnico] = []
        for candidato in candidatos:
            valor = _ValorComSpan(
                candidato.valor,
                candidato.inicio,
                candidato.fim,
            )
            campo = self._campo(
                texto,
                contexto,
                candidato.nome,
                valor,
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
                # Um rótulo de sessão com valor não UUID continua sendo texto
                # preservado, mas não se torna identificador técnico parcial.
                continue
            identificadores.append(identificador)

        return campos, tuple(identificadores)

    @staticmethod
    def _candidatos_na_regiao(
        regiao: _ValorComSpan,
    ) -> list[_CandidatoIdentificador]:
        candidatos: list[_CandidatoIdentificador] = []
        for correspondencia in _PADRAO_ID_CHAMADA.finditer(regiao.valor):
            nome = correspondencia.group("nome")
            tipo = (
                TipoIdentificador.TELECOM_CALL_ID
                if nome == "TelecomCallId"
                else TipoIdentificador.CALL_ID
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
                        _REGRA_TELECOM_CALL_ID
                        if tipo is TipoIdentificador.TELECOM_CALL_ID
                        else _REGRA_CALL_ID
                    ),
                )
            )

        for correspondencia in _PADRAO_UUID_SESSAO.finditer(regiao.valor):
            inicio_local, fim_local = correspondencia.span("valor")
            candidatos.append(
                _CandidatoIdentificador(
                    nome=correspondencia.group("nome"),
                    valor=correspondencia.group("valor"),
                    tipo=TipoIdentificador.UUID_SESSAO,
                    inicio=regiao.inicio + inicio_local,
                    fim=regiao.inicio + fim_local,
                    regra=_REGRA_UUID_SESSAO,
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
        proveniencia = self._proveniencia(
            texto,
            contexto,
            nome=nome,
            inicio=valor.inicio,
            fim=valor.fim,
            regra=regra,
        )
        return CampoEstruturado(
            nome=nome,
            valor_original=valor.valor,
            proveniencia=proveniencia,
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
            # O terminador físico pertence à linha que ele encerra. Contar um
            # ``\n`` situado exatamente no último caractere do span criaria
            # artificialmente uma linha seguinte e faria a proveniência sair
            # do intervalo do BlocoLog.
            linha_final = contexto.linha_inicial + texto.count(
                "\n", 0, ultimo_indice
            )

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
            "Cabeçalho ORK aparente não pôde ser interpretado."
            if codigo == _CODIGO_CABECALHO_INVALIDO
            else "Continuação ORK sem cabeçalho anterior."
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
    def _recortar_strip(
        texto: str,
        inicio: int,
        fim: int,
    ) -> _ValorComSpan | None:
        while inicio < fim and texto[inicio].isspace():
            inicio += 1
        while fim > inicio and texto[fim - 1].isspace():
            fim -= 1
        if inicio == fim:
            return None
        return _ValorComSpan(texto[inicio:fim], inicio, fim)

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
    def _valor_do_campo(entrada: EntradaDeLog, nome: str) -> str:
        for campo in entrada.campos_estruturados:
            if campo.nome == nome:
                return campo.valor_original
        raise ValueError(f"entrada ORK real não possui campo obrigatório {nome!r}.")
