"""Política executável e scanner seguro para fixtures versionáveis.

O módulo não conhece nem consulta fontes brutas locais. A governança recebe um
diretório candidato, aceita somente artefatos textuais declarados em manifesto
JSON e produz diagnósticos minimizados. Um diagnóstico contém exclusivamente o
arquivo relativo, a linha 1-based e o tipo do achado; o valor encontrado nunca
é preservado no resultado, em exceções ou em mensagens.

O formato canônico do manifesto é::

    {
      "origin": "synthetic" | "sanitized",
      "sanitizer_version": "1.0",
      "label": "SUCESSO" | "ERRO" | "NAO_CLASSIFICADA",
      "validation_date": "2025-01-01",
      "approved_by": "<DOMAIN_OWNER_1>",
      "artifacts": [
        {"path": "vpl.log", "sha256": "<64 caracteres hexadecimais>"}
      ]
    }

Aliases em português são aceitos para facilitar migração, mas duas aliases do
mesmo campo tornam o manifesto ambíguo e, portanto, inválido. O manifesto não
pode declarar comandos, módulos, templates ou outro conteúdo executável.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
import hmac
from ipaddress import ip_address
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
from typing import Any, Final
from urllib.parse import urlsplit


# Tipos de dados sensíveis usados nos diagnósticos. Os valores coincidem com os
# prefixos de placeholders definidos no design para que consumidores não
# precisem manipular o conteúdo detectado.
TIPO_CALL_ID: Final = "CALL_ID"
TIPO_UUID: Final = "UUID"
TIPO_TELEFONE: Final = "TELEFONE"
TIPO_DOCUMENTO: Final = "DOCUMENTO"
TIPO_IP: Final = "IP"
TIPO_HOST_INTERNO: Final = "HOST_INTERNO"
TIPO_URL_INTERNA: Final = "URL_INTERNA"
TIPO_CREDENCIAL: Final = "CREDENCIAL"
TIPO_DADO_CLIENTE: Final = "DADO_CLIENTE"

TIPOS_SENSIVEIS: Final = frozenset(
    {
        TIPO_CALL_ID,
        TIPO_UUID,
        TIPO_TELEFONE,
        TIPO_DOCUMENTO,
        TIPO_IP,
        TIPO_HOST_INTERNO,
        TIPO_URL_INTERNA,
        TIPO_CREDENCIAL,
        TIPO_DADO_CLIENTE,
    }
)

NOMES_MANIFESTO: Final = (
    "manifest.json",
    "manifesto.json",
    "fixture-manifest.json",
)

EXTENSOES_VERSIONAVEIS: Final = frozenset(
    {
        ".cfg",
        ".conf",
        ".csv",
        ".ini",
        ".json",
        ".jsonl",
        ".log",
        ".md",
        ".ndjson",
        ".toml",
        ".tsv",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    }
)

TAMANHO_MAXIMO_ARTEFATO_FIXTURE: Final = 16 * 1024 * 1024

_DIRETORIOS_IGNORADOS: Final = frozenset(
    {
        ".git",
        ".hypothesis",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "node_modules",
        "venv",
    }
)

_CHAVES_EXECUTAVEIS: Final = frozenset(
    {
        "callable",
        "cmd",
        "code",
        "command",
        "eval",
        "exec",
        "executable",
        "function",
        "import",
        "module",
        "script",
        "shell",
        "template",
    }
)

_ARQUIVO_DIAGNOSTICO_RE: Final = re.compile(
    r"(?:<ARQUIVO>|[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*)\Z"
)
_TIPO_DIAGNOSTICO_RE: Final = re.compile(r"[A-Z][A-Z0-9_]{0,95}\Z")
_PLACEHOLDER_RE: Final = re.compile(
    r"<(?P<tipo>CALL_ID|UUID_CANAL|UUID_SESSAO|UUID|TELEFONE|"
    r"DOCUMENTO|IP|HOST_INTERNO|URL_INTERNA|CREDENCIAL|DADO_CLIENTE|"
    r"APROVADOR|DOMAIN_OWNER|RESPONSAVEL_DOMINIO)_"
    r"(?P<indice>[1-9][0-9]*)>\Z"
)
_CANDIDATO_ANGULAR_RE: Final = re.compile(r"<[^<>\r\n]{1,128}>")
_DIGEST_RE: Final = re.compile(r"[0-9A-Fa-f]{64}\Z")
_VERSAO_RE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}\Z")
_APROVADOR_RE: Final = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{1,127}\Z")
_ID_FIXTURE_RE: Final = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{1,127}\Z")

_PREFIXOS_POR_TIPO: Final = {
    TIPO_CALL_ID: frozenset({"CALL_ID"}),
    TIPO_UUID: frozenset({"UUID", "UUID_CANAL", "UUID_SESSAO"}),
    TIPO_TELEFONE: frozenset({"TELEFONE"}),
    TIPO_DOCUMENTO: frozenset({"DOCUMENTO"}),
    TIPO_IP: frozenset({"IP"}),
    TIPO_HOST_INTERNO: frozenset({"HOST_INTERNO"}),
    TIPO_URL_INTERNA: frozenset({"URL_INTERNA"}),
    TIPO_CREDENCIAL: frozenset({"CREDENCIAL"}),
    TIPO_DADO_CLIENTE: frozenset({"DADO_CLIENTE"}),
}

# Prefixos tipados conhecidos (canônicos) mais suas variações "coladas" sem
# underscore (ex.: CALL_ID -> CALLID), usados por ``_parece_placeholder`` para
# detectar apenas tentativas MALFORMADAS de placeholders tipados. A ordenação
# por comprimento decrescente garante que ``UUID_CANAL`` seja avaliado antes de
# ``UUID``.
_PREFIXOS_PLACEHOLDER: Final = tuple(
    sorted(
        {
            prefixo
            for grupo in _PREFIXOS_POR_TIPO.values()
            for prefixo in grupo
        }
        | {
            prefixo.replace("_", "")
            for grupo in _PREFIXOS_POR_TIPO.values()
            for prefixo in grupo
            if "_" in prefixo
        },
        key=len,
        reverse=True,
    )
)

# Marcadores que sinalizam ausência de conteúdo sensível real. Inclui os
# rótulos de redação (``[redacted]``/``redacted``) em simetria com o
# ``_VALORES_NEUTROS`` do sanitizador (ver ``log_analyzer.core.sanitizacao``):
# um campo cujo valor já foi substituído pelo marcador de redação não é dado
# sensível a ser sinalizado pela governança.
_VALORES_NEUTROS: Final = frozenset(
    {
        "",
        "-",
        "n/a",
        "na",
        "none",
        "null",
        "undefined",
        "[redacted]",
        "redacted",
    }
)


@dataclass(frozen=True, slots=True, order=True)
class DiagnosticoGovernanca:
    """Diagnóstico deliberadamente mínimo e seguro para saída/CI."""

    arquivo: str
    linha: int
    tipo: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.arquivo, str)
            or _ARQUIVO_DIAGNOSTICO_RE.fullmatch(self.arquivo) is None
        ):
            raise ValueError("Arquivo de diagnóstico seguro inválido.")
        if (
            isinstance(self.linha, bool)
            or not isinstance(self.linha, int)
            or self.linha < 1
        ):
            raise ValueError("Linha de diagnóstico segura inválida.")
        if (
            not isinstance(self.tipo, str)
            or _TIPO_DIAGNOSTICO_RE.fullmatch(self.tipo) is None
        ):
            raise ValueError("Tipo de diagnóstico seguro inválido.")

    def __str__(self) -> str:
        return f"{self.arquivo}:{self.linha}:{self.tipo}"


@dataclass(frozen=True, slots=True)
class ResultadoGovernanca:
    """Resultado fail-closed da avaliação de uma fixture candidata."""

    aprovada: bool
    diagnosticos: tuple[DiagnosticoGovernanca, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.aprovada, bool):
            raise TypeError("aprovada deve ser booleana.")
        if self.aprovada == bool(self.diagnosticos):
            raise ValueError("Resultado de governança inconsistente.")

    @property
    def aceita(self) -> bool:
        """Alias semântico para consumidores da política."""

        return self.aprovada

    @property
    def valido(self) -> bool:
        return self.aprovada

    @property
    def rejeitada(self) -> bool:
        return not self.aprovada


class _AcumuladorDiagnosticos:
    """Deduplica achados sem jamais receber o valor que originou o achado."""

    def __init__(self) -> None:
        self._itens: set[DiagnosticoGovernanca] = set()

    def adicionar(self, arquivo: str, linha: int, tipo: str) -> None:
        self._itens.add(
            DiagnosticoGovernanca(
                arquivo=_arquivo_seguro(arquivo),
                linha=max(1, linha),
                tipo=tipo,
            )
        )

    def resultado(self) -> ResultadoGovernanca:
        itens = tuple(sorted(self._itens))
        return ResultadoGovernanca(aprovada=not itens, diagnosticos=itens)


@dataclass(frozen=True, slots=True)
class _RegraContextual:
    tipo: str
    prefixos_aceitos: frozenset[str]
    padrao: re.Pattern[str]


def _padrao_campo(*nomes: str) -> re.Pattern[str]:
    alternativas = "|".join(re.escape(nome) for nome in nomes)
    return re.compile(
        rf"""
        (?<![A-Za-z0-9_])
        [\"']?(?:{alternativas})[\"']?
        \s*[:=]\s*
        (?P<valor>
            <[^<>\r\n]{{1,128}}>
            | \"(?:\\.|[^\"\r\n])*\"
            | '(?:\\.|[^'\r\n])*'
            | [^\s,;}}\]]+
        )
        """,
        flags=re.IGNORECASE | re.VERBOSE,
    )


_REGRAS_CONTEXTO: Final = (
    _RegraContextual(
        TIPO_CREDENCIAL,
        _PREFIXOS_POR_TIPO[TIPO_CREDENCIAL],
        _padrao_campo(
            "api-key",
            "api_key",
            "apikey",
            "access-token",
            "access_token",
            "authorization",
            "client-secret",
            "client_secret",
            "credential",
            "credencial",
            "password",
            "passwd",
            "pwd",
            "refresh-token",
            "refresh_token",
            "secret",
            "senha",
            "token",
        ),
    ),
    _RegraContextual(
        TIPO_CALL_ID,
        _PREFIXOS_POR_TIPO[TIPO_CALL_ID],
        _padrao_campo(
            "call-id",
            "call_id",
            "callid",
            "id_chamada",
            "telecom_call_id",
            "telecomcallid",
        ),
    ),
    _RegraContextual(
        TIPO_UUID,
        _PREFIXOS_POR_TIPO[TIPO_UUID],
        _padrao_campo(
            "channel_uuid",
            "session_uuid",
            "uuid",
            "uuid_canal",
            "uuid_sessao",
        ),
    ),
    _RegraContextual(
        TIPO_DOCUMENTO,
        _PREFIXOS_POR_TIPO[TIPO_DOCUMENTO],
        _padrao_campo("cnpj", "cpf", "doc", "document", "documento"),
    ),
    _RegraContextual(
        TIPO_TELEFONE,
        _PREFIXOS_POR_TIPO[TIPO_TELEFONE],
        _padrao_campo(
            "celular",
            "fone",
            "mobile",
            "msisdn",
            "phone",
            "tel",
            "telefone",
        ),
    ),
    _RegraContextual(
        TIPO_IP,
        _PREFIXOS_POR_TIPO[TIPO_IP],
        _padrao_campo("endereco_ip", "ip", "ip_address"),
    ),
    _RegraContextual(
        TIPO_URL_INTERNA,
        _PREFIXOS_POR_TIPO[TIPO_URL_INTERNA],
        _padrao_campo("endpoint", "internal_url", "uri", "url", "url_interna"),
    ),
    _RegraContextual(
        TIPO_HOST_INTERNO,
        _PREFIXOS_POR_TIPO[TIPO_HOST_INTERNO],
        _padrao_campo("host", "hostname", "host_interno", "servidor"),
    ),
    _RegraContextual(
        TIPO_DADO_CLIENTE,
        _PREFIXOS_POR_TIPO[TIPO_DADO_CLIENTE],
        _padrao_campo(
            "client_data",
            "cliente",
            "conteudo_cliente",
            "customer",
            "customer_data",
            "dado_cliente",
            "email",
            "email_cliente",
            "nome_cliente",
        ),
    ),
)

_REFERENCIAS_PROIBIDAS: Final = (
    (
        "FONTE_PROIBIDA_LOGS",
        re.compile(
            r"(?i)(?<![A-Za-z0-9])logs(?:[\\/]|"
            r"[._-](?:backup|brut[oa]s?|copy|export|fixture|raw|sample)s?\b)"
        ),
    ),
    (
        "FONTE_PROIBIDA_CURATION_DB",
        re.compile(r"(?i)(?<![A-Za-z0-9_])curation\.db(?![A-Za-z0-9_])"),
    ),
    (
        "FONTE_PROIBIDA_DASHBOARD",
        re.compile(r"(?i)(?<![A-Za-z0-9])dashboard(?![A-Za-z0-9])"),
    ),
    (
        "FONTE_PROIBIDA_RELATORIO_BRUTO",
        re.compile(
            r"(?i)(?:raw[\s_-]*reports?|reports?[\s_-]*raw|"
            r"relat[oó]rios?[\s_-]*brutos?)"
        ),
    ),
)

_URL_RE: Final = re.compile(r"(?i)\b(?:https?|sips?|wss?)://[^\s<>\"']+")
_UUID_RE: Final = re.compile(
    r"(?i)(?<![0-9a-f])"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}"
    r"(?![0-9a-f])"
)
_DOCUMENTO_RE: Final = re.compile(
    r"(?<!\d)(?:\d{3}\.\d{3}\.\d{3}-\d{2}|"
    r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})(?!\d)"
)
_IPV4_RE: Final = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
_IPV6_RE: Final = re.compile(
    r"(?i)(?<![0-9a-f:])(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}(?![0-9a-f:])"
)
_TELEFONE_RE: Final = re.compile(
    r"(?<![0-9A-Za-z])"
    r"(?:\+[0-9]{1,3}[ .-]?)?"
    r"(?:\(?[0-9]{2,3}\)?[ .-]?)?"
    r"[0-9]{3,5}[ .-][0-9]{4}"
    r"(?![0-9A-Za-z])"
)
_HOST_INTERNO_RE: Final = re.compile(
    r"(?i)(?<![A-Za-z0-9_-])(?:localhost|"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"(?:corp|internal|intranet|invalid|lan|local|private|test|home\.arpa))"
    r"(?![A-Za-z0-9_-])"
)
_EMAIL_RE: Final = re.compile(
    r"(?i)(?<![A-Za-z0-9.!#$%&'*+/=?^_`{|}~-])"
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"
)
_CALL_ID_OPACO_RE: Final = re.compile(
    r"(?i)(?<![A-Za-z0-9_-])(?:SYN_CALL|CALL(?:ID)?)[_-]"
    r"[A-Za-z0-9][A-Za-z0-9._-]{3,}(?![A-Za-z0-9])"
)
_JWT_RE: Final = re.compile(
    r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{8,}\."
    r"[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?![A-Za-z0-9_-])"
)
_BEARER_RE: Final = re.compile(
    r"(?i)\b(?:basic|bearer)\s+[A-Za-z0-9._~+/=-]{8,}"
)
_CHAVE_PRIVADA_RE: Final = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
_CHAVE_ACESSO_RE: Final = re.compile(r"(?<![A-Z0-9])AKIA[A-Z0-9]{16}(?![A-Z0-9])")
_SIP_USUARIO_RE: Final = re.compile(
    r"(?i)(?:\bsips?:|\bsofia/[^\s/]+/)(?P<valor>[^@\s;>]+)@"
)


class ScannerDeFixtures:
    """Scanner textual independente que não devolve os trechos detectados."""

    def inspecionar_texto(
        self,
        texto: str,
        *,
        arquivo: str = "<ARQUIVO>",
        linha_inicial: int = 1,
    ) -> tuple[DiagnosticoGovernanca, ...]:
        if not isinstance(texto, str):
            raise TypeError("texto deve ser string.")
        if (
            isinstance(linha_inicial, bool)
            or not isinstance(linha_inicial, int)
            or linha_inicial < 1
        ):
            raise ValueError("linha_inicial deve ser um inteiro positivo.")

        acumulador = _AcumuladorDiagnosticos()
        linhas = texto.splitlines()
        if not linhas:
            linhas = [""]

        for deslocamento, linha in enumerate(linhas):
            self._inspecionar_linha(
                linha,
                arquivo=_arquivo_seguro(arquivo),
                numero=linha_inicial + deslocamento,
                acumulador=acumulador,
            )

        return acumulador.resultado().diagnosticos

    # Aliases explícitos deixam a API útil tanto em testes quanto em CI.
    varrer_texto = inspecionar_texto
    analisar_texto = inspecionar_texto

    def _inspecionar_linha(
        self,
        linha: str,
        *,
        arquivo: str,
        numero: int,
        acumulador: _AcumuladorDiagnosticos,
    ) -> None:
        for tipo, padrao in _REFERENCIAS_PROIBIDAS:
            if padrao.search(linha) is not None:
                acumulador.adicionar(arquivo, numero, tipo)

        spans_mascarados: list[tuple[int, int]] = []
        for candidato in _CANDIDATO_ANGULAR_RE.finditer(linha):
            token = candidato.group(0)
            if _PLACEHOLDER_RE.fullmatch(token) is not None:
                spans_mascarados.append(candidato.span())
            elif _parece_placeholder(token):
                acumulador.adicionar(arquivo, numero, "PLACEHOLDER_INVALIDO")
                spans_mascarados.append(candidato.span())

        for regra in _REGRAS_CONTEXTO:
            for correspondencia in regra.padrao.finditer(linha):
                spans_mascarados.append(correspondencia.span())
                valor = _remover_delimitadores(correspondencia.group("valor"))
                if _e_valor_neutro(valor):
                    continue
                placeholder = _PLACEHOLDER_RE.fullmatch(valor)
                if placeholder is None:
                    acumulador.adicionar(arquivo, numero, regra.tipo)
                    continue
                if placeholder.group("tipo") not in regra.prefixos_aceitos:
                    acumulador.adicionar(
                        arquivo,
                        numero,
                        "PLACEHOLDER_TIPO_INCONSISTENTE",
                    )

        for correspondencia in _SIP_USUARIO_RE.finditer(linha):
            spans_mascarados.append(correspondencia.span())
            valor = correspondencia.group("valor")
            placeholder = _PLACEHOLDER_RE.fullmatch(valor)
            if placeholder is None:
                acumulador.adicionar(arquivo, numero, TIPO_CALL_ID)
            elif placeholder.group("tipo") not in _PREFIXOS_POR_TIPO[TIPO_CALL_ID]:
                acumulador.adicionar(
                    arquivo,
                    numero,
                    "PLACEHOLDER_TIPO_INCONSISTENTE",
                )

        restante = _mascarar_spans(linha, spans_mascarados)
        restante = self._detectar_urls(restante, arquivo, numero, acumulador)
        restante = self._detectar_credenciais(
            restante, arquivo, numero, acumulador
        )
        restante = _detectar_regex(
            restante,
            _UUID_RE,
            TIPO_UUID,
            arquivo,
            numero,
            acumulador,
        )
        restante = _detectar_regex(
            restante,
            _DOCUMENTO_RE,
            TIPO_DOCUMENTO,
            arquivo,
            numero,
            acumulador,
        )
        restante = self._detectar_ips(restante, arquivo, numero, acumulador)
        restante = self._detectar_telefones(
            restante, arquivo, numero, acumulador
        )
        restante = _detectar_regex(
            restante,
            _HOST_INTERNO_RE,
            TIPO_HOST_INTERNO,
            arquivo,
            numero,
            acumulador,
        )
        restante = _detectar_regex(
            restante,
            _EMAIL_RE,
            TIPO_DADO_CLIENTE,
            arquivo,
            numero,
            acumulador,
        )
        _detectar_regex(
            restante,
            _CALL_ID_OPACO_RE,
            TIPO_CALL_ID,
            arquivo,
            numero,
            acumulador,
        )

    @staticmethod
    def _detectar_urls(
        texto: str,
        arquivo: str,
        linha: int,
        acumulador: _AcumuladorDiagnosticos,
    ) -> str:
        spans: list[tuple[int, int]] = []
        for correspondencia in _URL_RE.finditer(texto):
            if _url_e_interna(correspondencia.group(0)):
                acumulador.adicionar(arquivo, linha, TIPO_URL_INTERNA)
                spans.append(correspondencia.span())
        return _mascarar_spans(texto, spans)

    @staticmethod
    def _detectar_credenciais(
        texto: str,
        arquivo: str,
        linha: int,
        acumulador: _AcumuladorDiagnosticos,
    ) -> str:
        for padrao in (_CHAVE_PRIVADA_RE, _BEARER_RE, _JWT_RE, _CHAVE_ACESSO_RE):
            texto = _detectar_regex(
                texto,
                padrao,
                TIPO_CREDENCIAL,
                arquivo,
                linha,
                acumulador,
            )
        return texto

    @staticmethod
    def _detectar_ips(
        texto: str,
        arquivo: str,
        linha: int,
        acumulador: _AcumuladorDiagnosticos,
    ) -> str:
        spans: list[tuple[int, int]] = []
        for padrao in (_IPV4_RE, _IPV6_RE):
            for correspondencia in padrao.finditer(texto):
                try:
                    ip_address(correspondencia.group(0))
                except ValueError:
                    continue
                acumulador.adicionar(arquivo, linha, TIPO_IP)
                spans.append(correspondencia.span())
        return _mascarar_spans(texto, spans)

    @staticmethod
    def _detectar_telefones(
        texto: str,
        arquivo: str,
        linha: int,
        acumulador: _AcumuladorDiagnosticos,
    ) -> str:
        spans: list[tuple[int, int]] = []
        for correspondencia in _TELEFONE_RE.finditer(texto):
            candidato = correspondencia.group(0)
            quantidade = sum(caractere.isdigit() for caractere in candidato)
            if not 10 <= quantidade <= 15:
                continue
            if not any(separador in candidato for separador in "+()- ."):
                continue
            acumulador.adicionar(arquivo, linha, TIPO_TELEFONE)
            spans.append(correspondencia.span())
        return _mascarar_spans(texto, spans)


@dataclass(frozen=True, slots=True)
class _ManifestoValidado:
    artefatos: Mapping[str, str]


class _ChaveJsonDuplicada(ValueError):
    pass


_AUSENTE: Final = object()


class GovernancaDeFixtures:
    """Valida integralmente uma fixture candidata sem consultar fontes reais.

    ``versoes_sanitizador`` é opcional. Quando informado pelo chamador de CI,
    além de exigir uma versão declarativa, a política exige que ela pertença ao
    conjunto revisado. O manifesto nunca pode criar sua própria allowlist.
    """

    def __init__(
        self,
        raiz: str | os.PathLike[str] | None = None,
        *,
        scanner: ScannerDeFixtures | None = None,
        versoes_sanitizador: Collection[str] | None = None,
        nome_manifesto: str | None = None,
    ) -> None:
        if scanner is not None and not isinstance(scanner, ScannerDeFixtures):
            raise TypeError("scanner deve ser ScannerDeFixtures.")
        if nome_manifesto is not None and nome_manifesto not in NOMES_MANIFESTO:
            raise ValueError("Nome de manifesto não permitido.")

        versoes: set[str] | None = None
        if versoes_sanitizador is not None:
            versoes = set()
            for versao in versoes_sanitizador:
                if not isinstance(versao, str) or _VERSAO_RE.fullmatch(versao) is None:
                    raise ValueError("Versão de sanitizador permitida inválida.")
                versoes.add(versao)
            if not versoes:
                raise ValueError("Ao menos uma versão de sanitizador é necessária.")

        self._raiz = raiz
        self._scanner = scanner or ScannerDeFixtures()
        self._versoes_sanitizador = (
            None if versoes is None else frozenset(versoes)
        )
        self._nome_manifesto = nome_manifesto

    def validar(
        self,
        raiz: str | os.PathLike[str] | None = None,
    ) -> ResultadoGovernanca:
        acumulador = _AcumuladorDiagnosticos()
        valor_raiz = self._raiz if raiz is None else raiz
        if valor_raiz is None:
            acumulador.adicionar("<ARQUIVO>", 1, "FIXTURE_NAO_INFORMADA")
            return acumulador.resultado()
        if not isinstance(valor_raiz, (str, os.PathLike)):
            raise TypeError("raiz deve representar um caminho.")

        diretorio = Path(valor_raiz)
        if _tipo_fonte_proibida(diretorio.parts) is not None:
            acumulador.adicionar(
                _arquivo_seguro(diretorio.name),
                1,
                _tipo_fonte_proibida(diretorio.parts) or "FONTE_PROIBIDA",
            )
            return acumulador.resultado()

        try:
            if diretorio.is_symlink():
                acumulador.adicionar("<ARQUIVO>", 1, "LINK_SIMBOLICO_PROIBIDO")
                return acumulador.resultado()
            if not diretorio.exists() or not diretorio.is_dir():
                acumulador.adicionar("<ARQUIVO>", 1, "FIXTURE_INACESSIVEL")
                return acumulador.resultado()
        except OSError:
            acumulador.adicionar("<ARQUIVO>", 1, "FIXTURE_INACESSIVEL")
            return acumulador.resultado()

        arquivos = self._enumerar_arquivos(diretorio, acumulador)
        manifestos = [
            caminho
            for caminho in arquivos
            if caminho.parent == diretorio and caminho.name in NOMES_MANIFESTO
        ]
        if self._nome_manifesto is not None:
            manifestos = [
                caminho
                for caminho in manifestos
                if caminho.name == self._nome_manifesto
            ]

        manifesto_path: Path | None
        if not manifestos:
            acumulador.adicionar(
                self._nome_manifesto or NOMES_MANIFESTO[0],
                1,
                "MANIFESTO_AUSENTE",
            )
            manifesto_path = None
        elif len(manifestos) > 1:
            acumulador.adicionar(
                NOMES_MANIFESTO[0],
                1,
                "MANIFESTO_AMBIGUO",
            )
            manifesto_path = None
        else:
            manifesto_path = manifestos[0]

        digests_reais: dict[str, str] = {}
        texto_manifesto: str | None = None
        for caminho in arquivos:
            relativo = _relativo_seguro(diretorio, caminho)
            conteudo = _ler_artefato(caminho, relativo, acumulador)
            if conteudo is None:
                continue
            payload, texto = conteudo
            digests_reais[relativo.casefold()] = sha256(payload).hexdigest()
            try:
                diagnosticos_scanner = self._scanner.inspecionar_texto(
                    texto,
                    arquivo=relativo,
                )
                for diagnostico in diagnosticos_scanner:
                    acumulador.adicionar(
                        diagnostico.arquivo,
                        diagnostico.linha,
                        diagnostico.tipo,
                    )
            except Exception:
                # Um scanner injetado não pode tornar a validação permissiva nem
                # propagar mensagem potencialmente controlada pela fixture.
                acumulador.adicionar(relativo, 1, "SCANNER_FALHOU")
            if manifesto_path is not None and caminho == manifesto_path:
                texto_manifesto = texto

        manifesto: _ManifestoValidado | None = None
        if manifesto_path is not None and texto_manifesto is not None:
            nome_seguro = _relativo_seguro(diretorio, manifesto_path)
            try:
                manifesto = self._validar_manifesto(
                    texto_manifesto,
                    nome_seguro,
                    acumulador,
                )
            except Exception:
                # Conteúdo declarativo inválido nunca escapa como exceção nem
                # substitui um resultado rejeitado por aprovação parcial.
                acumulador.adicionar(
                    nome_seguro,
                    1,
                    "MANIFESTO_VALIDACAO_FALHOU",
                )

        if manifesto is not None and manifesto_path is not None:
            self._validar_artefatos_declarados(
                diretorio=diretorio,
                manifesto_path=manifesto_path,
                manifesto=manifesto,
                arquivos=arquivos,
                digests_reais=digests_reais,
                acumulador=acumulador,
            )

        return acumulador.resultado()

    executar = validar
    validar_fixture = validar

    def _enumerar_arquivos(
        self,
        raiz: Path,
        acumulador: _AcumuladorDiagnosticos,
    ) -> list[Path]:
        encontrados: list[Path] = []

        def visitar(diretorio: Path) -> None:
            try:
                entradas = sorted(
                    os.scandir(diretorio),
                    key=lambda entrada: entrada.name.casefold(),
                )
            except OSError:
                acumulador.adicionar(
                    _relativo_seguro(raiz, diretorio),
                    1,
                    "DIRETORIO_INACESSIVEL",
                )
                return

            try:
                for entrada in entradas:
                    caminho = Path(entrada.path)
                    relativo = _relativo_seguro(raiz, caminho)
                    try:
                        if entrada.is_symlink():
                            acumulador.adicionar(
                                relativo,
                                1,
                                "LINK_SIMBOLICO_PROIBIDO",
                            )
                            continue
                        if entrada.is_dir(follow_symlinks=False):
                            nome_normalizado = entrada.name.casefold()
                            if nome_normalizado in _DIRETORIOS_IGNORADOS:
                                continue
                            tipo_proibido = _tipo_fonte_proibida(
                                PurePosixPath(relativo).parts
                            )
                            if tipo_proibido is not None:
                                acumulador.adicionar(relativo, 1, tipo_proibido)
                                continue
                            visitar(caminho)
                            continue
                        if not entrada.is_file(follow_symlinks=False):
                            acumulador.adicionar(
                                relativo,
                                1,
                                "ARTEFATO_NAO_REGULAR",
                            )
                            continue
                    except OSError:
                        acumulador.adicionar(
                            relativo,
                            1,
                            "ARTEFATO_INACESSIVEL",
                        )
                        continue

                    tipo_proibido = _tipo_fonte_proibida(
                        PurePosixPath(relativo).parts
                    )
                    if tipo_proibido is not None:
                        acumulador.adicionar(relativo, 1, tipo_proibido)
                        continue
                    if caminho.suffix.casefold() not in EXTENSOES_VERSIONAVEIS:
                        acumulador.adicionar(
                            relativo,
                            1,
                            "ARTEFATO_NAO_VERSIONAVEL",
                        )
                        continue
                    encontrados.append(caminho)
            finally:
                for entrada in entradas:
                    try:
                        entrada.close()
                    except AttributeError:
                        pass

        visitar(raiz)
        return encontrados

    def _validar_manifesto(
        self,
        texto: str,
        arquivo: str,
        acumulador: _AcumuladorDiagnosticos,
    ) -> _ManifestoValidado | None:
        try:
            documento = json.loads(texto, object_pairs_hook=_objeto_json_sem_duplicata)
        except json.JSONDecodeError as erro:
            acumulador.adicionar(
                arquivo,
                max(1, erro.lineno),
                "MANIFESTO_JSON_INVALIDO",
            )
            return None
        except _ChaveJsonDuplicada:
            acumulador.adicionar(arquivo, 1, "MANIFESTO_CHAVE_DUPLICADA")
            return None

        if not isinstance(documento, Mapping):
            acumulador.adicionar(arquivo, 1, "MANIFESTO_ESTRUTURA_INVALIDA")
            return None
        if _contem_chave_executavel(documento):
            acumulador.adicionar(arquivo, 1, "MANIFESTO_NAO_DECLARATIVO")

        valido = True
        origem = _campo_unico(documento, ("origin", "origem"))
        if origem is _AUSENTE:
            acumulador.adicionar(arquivo, 1, "MANIFESTO_ORIGEM_AUSENTE")
            valido = False
        elif not isinstance(origem, str) or _normalizar_palavra(origem) not in {
            "sanitized",
            "sanitizada",
            "sanitizado",
            "synthetic",
            "sintetica",
            "sintetico",
        }:
            acumulador.adicionar(arquivo, 1, "MANIFESTO_ORIGEM_INVALIDA")
            valido = False

        versao = self._obter_versao_sanitizador(documento, arquivo, acumulador)
        if versao is None:
            valido = False

        rotulo = _campo_unico(documento, ("label", "rotulo", "rótulo"))
        if rotulo is _AUSENTE:
            acumulador.adicionar(arquivo, 1, "MANIFESTO_ROTULO_AUSENTE")
            valido = False
        elif not isinstance(rotulo, str) or _normalizar_palavra(rotulo) not in {
            "erro",
            "nao_classificada",
            "nao_classificado",
            "sucesso",
        }:
            acumulador.adicionar(arquivo, 1, "MANIFESTO_ROTULO_INVALIDO")
            valido = False

        data_validacao = _campo_unico(
            documento,
            (
                "approved_at",
                "data",
                "data_validacao",
                "validated_at",
                "validation_date",
            ),
        )
        if data_validacao is _AUSENTE:
            acumulador.adicionar(arquivo, 1, "MANIFESTO_DATA_AUSENTE")
            valido = False
        elif not _data_iso_valida(data_validacao):
            acumulador.adicionar(arquivo, 1, "MANIFESTO_DATA_INVALIDA")
            valido = False

        aprovador = _campo_unico(
            documento,
            (
                "approved_by",
                "approver",
                "aprovador",
                "responsavel_dominio",
            ),
        )
        if aprovador is _AUSENTE:
            acumulador.adicionar(arquivo, 1, "MANIFESTO_APROVADOR_AUSENTE")
            valido = False
        elif not _aprovador_valido(aprovador):
            acumulador.adicionar(arquivo, 1, "MANIFESTO_APROVADOR_INVALIDO")
            valido = False

        fixture_id = _campo_unico(documento, ("fixture_id", "id_fixture"))
        if fixture_id is not _AUSENTE and (
            not isinstance(fixture_id, str)
            or _ID_FIXTURE_RE.fullmatch(fixture_id) is None
        ):
            acumulador.adicionar(arquivo, 1, "MANIFESTO_FIXTURE_ID_INVALIDO")
            valido = False

        artefatos_valor = _campo_unico(
            documento,
            ("artifacts", "artefatos", "digests", "files", "arquivos"),
        )
        artefatos = _extrair_artefatos(
            artefatos_valor,
            arquivo,
            acumulador,
        )
        if artefatos is None:
            valido = False

        if not valido or artefatos is None:
            return None
        return _ManifestoValidado(artefatos=artefatos)

    def _obter_versao_sanitizador(
        self,
        documento: Mapping[str, Any],
        arquivo: str,
        acumulador: _AcumuladorDiagnosticos,
    ) -> str | None:
        direta = _campo_unico(
            documento,
            (
                "sanitization_version",
                "sanitizer_version",
                "sanitizador_versao",
                "versao_sanitizador",
            ),
        )
        objeto = _campo_unico(documento, ("sanitizer", "sanitizador"))
        if direta is not _AUSENTE and objeto is not _AUSENTE:
            acumulador.adicionar(
                arquivo,
                1,
                "MANIFESTO_SANITIZADOR_AMBIGUO",
            )
            return None

        versao: object = direta
        if objeto is not _AUSENTE:
            if not isinstance(objeto, Mapping):
                acumulador.adicionar(
                    arquivo,
                    1,
                    "MANIFESTO_SANITIZADOR_INVALIDO",
                )
                return None
            nome = _campo_unico(objeto, ("name", "nome"))
            versao = _campo_unico(objeto, ("version", "versao", "versão"))
            if (
                nome is _AUSENTE
                or not isinstance(nome, str)
                or _VERSAO_RE.fullmatch(nome) is None
            ):
                acumulador.adicionar(
                    arquivo,
                    1,
                    "MANIFESTO_SANITIZADOR_INVALIDO",
                )
                return None

        if versao is _AUSENTE:
            acumulador.adicionar(
                arquivo,
                1,
                "MANIFESTO_SANITIZADOR_AUSENTE",
            )
            return None
        if not isinstance(versao, str) or _VERSAO_RE.fullmatch(versao) is None:
            acumulador.adicionar(
                arquivo,
                1,
                "MANIFESTO_SANITIZADOR_INVALIDO",
            )
            return None
        if not any(caractere.isdigit() for caractere in versao):
            acumulador.adicionar(
                arquivo,
                1,
                "MANIFESTO_SANITIZADOR_INVALIDO",
            )
            return None
        if (
            self._versoes_sanitizador is not None
            and versao not in self._versoes_sanitizador
        ):
            acumulador.adicionar(
                arquivo,
                1,
                "SANITIZADOR_VERSAO_NAO_SUPORTADA",
            )
            return None
        return versao

    @staticmethod
    def _validar_artefatos_declarados(
        *,
        diretorio: Path,
        manifesto_path: Path,
        manifesto: _ManifestoValidado,
        arquivos: Sequence[Path],
        digests_reais: Mapping[str, str],
        acumulador: _AcumuladorDiagnosticos,
    ) -> None:
        nome_manifesto = _relativo_seguro(diretorio, manifesto_path)
        reais: dict[str, str] = {}
        for caminho in arquivos:
            if caminho == manifesto_path:
                continue
            relativo = _relativo_seguro(diretorio, caminho)
            chave = relativo.casefold()
            if chave in reais:
                acumulador.adicionar(
                    relativo,
                    1,
                    "ARTEFATO_CAMINHO_AMBIGUO",
                )
            reais[chave] = relativo

        declarados = {chave.casefold(): valor for chave, valor in manifesto.artefatos.items()}
        for chave, relativo in reais.items():
            if chave not in declarados:
                acumulador.adicionar(
                    relativo,
                    1,
                    "ARTEFATO_NAO_DECLARADO",
                )
                continue
            digest_real = digests_reais.get(chave)
            if digest_real is None or not hmac.compare_digest(
                digest_real,
                declarados[chave],
            ):
                acumulador.adicionar(relativo, 1, "DIGEST_DIVERGENTE")

        for chave in declarados:
            if chave not in reais:
                acumulador.adicionar(
                    nome_manifesto,
                    1,
                    "ARTEFATO_DECLARADO_AUSENTE",
                )


# Alias em português usado por consumidores que preferem nome explícito.
ScannerDeDadosSensiveis = ScannerDeFixtures


def validar_fixture(
    raiz: str | os.PathLike[str],
    *,
    versoes_sanitizador: Collection[str] | None = None,
    nome_manifesto: str | None = None,
) -> ResultadoGovernanca:
    """Atalho funcional para executar a política completa."""

    return GovernancaDeFixtures(
        versoes_sanitizador=versoes_sanitizador,
        nome_manifesto=nome_manifesto,
    ).validar(raiz)


def _arquivo_seguro(valor: str) -> str:
    if not isinstance(valor, str):
        return "<ARQUIVO>"
    normalizado = valor.replace("\\", "/")
    if (
        _ARQUIVO_DIAGNOSTICO_RE.fullmatch(normalizado) is None
        or ".." in PurePosixPath(normalizado).parts
    ):
        return "<ARQUIVO>"
    return normalizado


def _relativo_seguro(raiz: Path, caminho: Path) -> str:
    try:
        relativo = caminho.relative_to(raiz).as_posix()
    except (TypeError, ValueError):
        return "<ARQUIVO>"
    return _arquivo_seguro(relativo or "<ARQUIVO>")


def _normalizar_palavra(valor: str) -> str:
    tabela = str.maketrans({"á": "a", "ã": "a", "ç": "c", "é": "e", "ó": "o"})
    return valor.strip().casefold().translate(tabela).replace(" ", "_").replace("-", "_")


def _parece_placeholder(token: str) -> bool:
    """Detecta variações INVÁLIDAS de placeholders tipados conhecidos.

    A intenção é sinalizar apenas tokens ``<...>`` que claramente imitam um
    placeholder TIPADO (ex.: ``<CALL_ID_0>``, ``<CALL_ID_>``, ``<UUID>``,
    ``<CALLID_1>``) mas não são um placeholder canônico válido — estes já são
    aceitos por ``_PLACEHOLDER_RE`` antes desta função ser chamada.

    Identificadores genéricos em maiúsculas com ``_`` (ex.: ``<PROCESSING_STARTED>``
    ou ``<PROCESSING_ADA_V1>``, nomes de estado/modelo do sistema) NÃO são
    sinalizados, evitando falsos-positivos que suprimiriam a visão segura.
    """

    conteudo = token[1:-1]
    if not conteudo:
        return False
    maiusculo = conteudo.upper()
    for prefixo in _PREFIXOS_PLACEHOLDER:
        if not maiusculo.startswith(prefixo):
            continue
        resto = maiusculo[len(prefixo):]
        # Parece um placeholder tipado quando o prefixo aparece isolado
        # (``<UUID>``) ou é imediatamente seguido por ``_`` ou por um dígito
        # (``<CALL_ID_>``, ``<CALL_ID_0>``, ``<CALLID_1>``).
        if resto == "" or resto[0] == "_" or resto[0].isdigit():
            return True
    return False


def _remover_delimitadores(valor: str) -> str:
    resultado = valor.strip()
    if len(resultado) >= 2 and resultado[0] == resultado[-1] and resultado[0] in "\"'":
        resultado = resultado[1:-1].strip()
    return resultado


def _e_valor_neutro(valor: str) -> bool:
    """Indica se ``valor`` é um marcador neutro (ausência ou redação).

    Compara a forma normalizada e também a variante sem colchetes externos, de
    modo que rótulos redigidos como ``[REDACTED]`` sejam reconhecidos mesmo
    quando ``_remover_delimitadores`` só descartou aspas envolventes.
    """

    normalizado = valor.casefold()
    if normalizado in _VALORES_NEUTROS:
        return True
    sem_colchetes = normalizado.strip("[]").strip()
    return sem_colchetes in _VALORES_NEUTROS


def _mascarar_spans(texto: str, spans: Sequence[tuple[int, int]]) -> str:
    if not spans:
        return texto
    caracteres = list(texto)
    for inicio, fim in spans:
        inicio_seguro = max(0, inicio)
        fim_seguro = min(len(caracteres), fim)
        for indice in range(inicio_seguro, fim_seguro):
            caracteres[indice] = " "
    return "".join(caracteres)


def _detectar_regex(
    texto: str,
    padrao: re.Pattern[str],
    tipo: str,
    arquivo: str,
    linha: int,
    acumulador: _AcumuladorDiagnosticos,
) -> str:
    spans = [correspondencia.span() for correspondencia in padrao.finditer(texto)]
    if spans:
        acumulador.adicionar(arquivo, linha, tipo)
    return _mascarar_spans(texto, spans)


def _url_e_interna(valor: str) -> bool:
    try:
        analisada = urlsplit(valor)
        host = analisada.hostname
    except ValueError:
        return True
    if host is None:
        return True
    if analisada.username is not None or analisada.password is not None:
        return True
    host_normalizado = host.rstrip(".").casefold()
    if host_normalizado == "localhost" or "." not in host_normalizado:
        return True
    if host_normalizado.endswith(
        (
            ".corp",
            ".home.arpa",
            ".internal",
            ".intranet",
            ".invalid",
            ".lan",
            ".local",
            ".private",
            ".test",
        )
    ):
        return True
    try:
        endereco = ip_address(host_normalizado)
    except ValueError:
        return False
    return bool(
        endereco.is_private
        or endereco.is_loopback
        or endereco.is_link_local
        or endereco.is_reserved
        or endereco.is_unspecified
    )


def _tipo_fonte_proibida(partes: Sequence[str]) -> str | None:
    normalizadas = tuple(parte.casefold() for parte in partes if parte not in {"", "."})
    for parte in normalizadas:
        if parte == "logs" or re.fullmatch(
            r"logs(?:[._-](?:backup|brut[oa]s?|copy|export|fixture|raw|sample)s?)?"
            r"(?:\.[a-z0-9]+)?",
            parte,
        ):
            return "FONTE_PROIBIDA_LOGS"
        if parte == "curation.db" or re.match(r"curation\.db(?:[._-]|\Z)", parte):
            return "FONTE_PROIBIDA_CURATION_DB"
        if parte == "dashboard" or re.match(r"dashboard(?:[._-]|\Z)", parte):
            return "FONTE_PROIBIDA_DASHBOARD"
        if re.fullmatch(
            r"(?:raw[_-]?reports?|reports?[_-]?raw|relatorios?[_-]?brutos?)"
            r"(?:[._-].*)?",
            parte,
        ):
            return "FONTE_PROIBIDA_RELATORIO_BRUTO"
    return None


def _ler_artefato(
    caminho: Path,
    arquivo: str,
    acumulador: _AcumuladorDiagnosticos,
) -> tuple[bytes, str] | None:
    try:
        status_inicial = caminho.lstat()
        if not stat.S_ISREG(status_inicial.st_mode):
            acumulador.adicionar(arquivo, 1, "ARTEFATO_NAO_REGULAR")
            return None
        if status_inicial.st_size > TAMANHO_MAXIMO_ARTEFATO_FIXTURE:
            acumulador.adicionar(arquivo, 1, "ARTEFATO_EXCEDE_LIMITE")
            return None

        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descritor = os.open(caminho, flags)
        try:
            status_aberto = os.fstat(descritor)
            if not stat.S_ISREG(status_aberto.st_mode):
                acumulador.adicionar(arquivo, 1, "ARTEFATO_NAO_REGULAR")
                return None
            if status_aberto.st_size > TAMANHO_MAXIMO_ARTEFATO_FIXTURE:
                acumulador.adicionar(arquivo, 1, "ARTEFATO_EXCEDE_LIMITE")
                return None
            blocos: list[bytes] = []
            restante = TAMANHO_MAXIMO_ARTEFATO_FIXTURE + 1
            while restante > 0:
                bloco = os.read(descritor, min(64 * 1024, restante))
                if not bloco:
                    break
                blocos.append(bloco)
                restante -= len(bloco)
            payload = b"".join(blocos)
        finally:
            os.close(descritor)

        if len(payload) > TAMANHO_MAXIMO_ARTEFATO_FIXTURE:
            acumulador.adicionar(arquivo, 1, "ARTEFATO_EXCEDE_LIMITE")
            return None
        try:
            texto = payload.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError as erro:
            linha = payload[: erro.start].count(b"\n") + 1
            acumulador.adicionar(arquivo, linha, "ARTEFATO_UTF8_INVALIDO")
            return None
        return payload, texto
    except OSError:
        acumulador.adicionar(arquivo, 1, "ARTEFATO_INACESSIVEL")
        return None


def _objeto_json_sem_duplicata(pares: list[tuple[str, Any]]) -> dict[str, Any]:
    resultado: dict[str, Any] = {}
    for chave, valor in pares:
        if chave in resultado:
            raise _ChaveJsonDuplicada("Manifesto contém chave duplicada.")
        resultado[chave] = valor
    return resultado


def _campo_unico(documento: Mapping[str, Any], aliases: Sequence[str]) -> object:
    presentes = [alias for alias in aliases if alias in documento]
    if len(presentes) != 1:
        return _AUSENTE
    return documento[presentes[0]]


def _contem_chave_executavel(valor: object) -> bool:
    if isinstance(valor, Mapping):
        for chave, item in valor.items():
            if isinstance(chave, str) and chave.casefold() in _CHAVES_EXECUTAVEIS:
                return True
            if _contem_chave_executavel(item):
                return True
    elif isinstance(valor, Sequence) and not isinstance(valor, (str, bytes, bytearray)):
        return any(_contem_chave_executavel(item) for item in valor)
    return False


def _data_iso_valida(valor: object) -> bool:
    if not isinstance(valor, str) or not valor or len(valor) > 64:
        return False
    try:
        if "T" in valor or "t" in valor or " " in valor:
            datetime.fromisoformat(valor.replace("Z", "+00:00"))
        else:
            date.fromisoformat(valor)
    except ValueError:
        return False
    return True


def _aprovador_valido(valor: object) -> bool:
    if not isinstance(valor, str):
        return False
    placeholder = _PLACEHOLDER_RE.fullmatch(valor)
    if placeholder is not None:
        return placeholder.group("tipo") in {
            "APROVADOR",
            "DOMAIN_OWNER",
            "RESPONSAVEL_DOMINIO",
        }
    if _APROVADOR_RE.fullmatch(valor) is None:
        return False
    return valor.casefold() not in {
        "anonymous",
        "none",
        "pending",
        "tbd",
        "unknown",
    }


def _normalizar_caminho_manifesto(valor: object) -> str | None:
    if not isinstance(valor, str) or not valor or "\x00" in valor:
        return None
    windows = PureWindowsPath(valor)
    posix = PurePosixPath(valor.replace("\\", "/"))
    if windows.is_absolute() or windows.drive or posix.is_absolute():
        return None
    if any(parte in {"", ".", ".."} for parte in posix.parts):
        return None
    normalizado = posix.as_posix()
    if _arquivo_seguro(normalizado) == "<ARQUIVO>":
        return None
    if _tipo_fonte_proibida(posix.parts) is not None:
        return None
    if posix.suffix.casefold() not in EXTENSOES_VERSIONAVEIS:
        return None
    if posix.name in NOMES_MANIFESTO:
        return None
    return normalizado


def _extrair_artefatos(
    valor: object,
    arquivo_manifesto: str,
    acumulador: _AcumuladorDiagnosticos,
) -> dict[str, str] | None:
    if valor is _AUSENTE:
        acumulador.adicionar(
            arquivo_manifesto,
            1,
            "MANIFESTO_ARTEFATOS_AUSENTES",
        )
        return None

    pares: list[tuple[object, object]] = []
    if isinstance(valor, Mapping):
        pares.extend(valor.items())
    elif isinstance(valor, Sequence) and not isinstance(valor, (str, bytes, bytearray)):
        for item in valor:
            if not isinstance(item, Mapping):
                acumulador.adicionar(
                    arquivo_manifesto,
                    1,
                    "MANIFESTO_ARTEFATOS_INVALIDOS",
                )
                return None
            caminho = _campo_unico(item, ("file", "path", "arquivo", "caminho"))
            digest = _campo_unico(item, ("digest", "sha256"))
            pares.append((caminho, digest))
    else:
        acumulador.adicionar(
            arquivo_manifesto,
            1,
            "MANIFESTO_ARTEFATOS_INVALIDOS",
        )
        return None

    if not pares:
        acumulador.adicionar(
            arquivo_manifesto,
            1,
            "MANIFESTO_ARTEFATOS_AUSENTES",
        )
        return None

    resultado: dict[str, str] = {}
    chaves_normalizadas: set[str] = set()
    valido = True
    for caminho_bruto, digest_bruto in pares:
        caminho = _normalizar_caminho_manifesto(caminho_bruto)
        if caminho is None:
            acumulador.adicionar(
                arquivo_manifesto,
                1,
                "MANIFESTO_CAMINHO_ARTEFATO_INVALIDO",
            )
            valido = False
            continue
        chave = caminho.casefold()
        if chave in chaves_normalizadas:
            acumulador.adicionar(
                arquivo_manifesto,
                1,
                "MANIFESTO_ARTEFATO_DUPLICADO",
            )
            valido = False
            continue
        chaves_normalizadas.add(chave)
        if not isinstance(digest_bruto, str) or _DIGEST_RE.fullmatch(digest_bruto) is None:
            acumulador.adicionar(
                arquivo_manifesto,
                1,
                "MANIFESTO_DIGEST_INVALIDO",
            )
            valido = False
            continue
        resultado[caminho] = digest_bruto.casefold()

    return resultado if valido and resultado else None


__all__ = [
    "DiagnosticoGovernanca",
    "EXTENSOES_VERSIONAVEIS",
    "GovernancaDeFixtures",
    "NOMES_MANIFESTO",
    "ResultadoGovernanca",
    "ScannerDeDadosSensiveis",
    "ScannerDeFixtures",
    "TAMANHO_MAXIMO_ARTEFATO_FIXTURE",
    "TIPOS_SENSIVEIS",
    "validar_fixture",
]
