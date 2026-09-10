"""Primitivas fail-closed para sanitização de dados sensíveis.

O módulo mantém o estado bruto somente durante uma análise. Um
:class:`SanitizationContext` associa ``(tipo, valor_normalizado)`` a um
placeholder tipado, na ordem da primeira ocorrência, e descarta todos os
valores usados para substituição ao ser fechado.

Campos estruturados devem ser sanitizados antes do texto livre. Isso permite
que uma ocorrência textual reutilize o placeholder atribuído ao campo que lhe
deu significado. Detectores conservadores acrescentam defesa em profundidade
para valores que não tenham sido registrados estruturalmente.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from ipaddress import ip_address
import re
from typing import Iterable, Mapping
from urllib.parse import urlsplit
from uuid import UUID

from log_analyzer.core.excecoes import ErroDeSanitizacao
from log_analyzer.core.modelos import (
    CampoEstruturado,
    IdentificadorTecnico,
    TipoIdentificador,
)


class TipoDadoSensivel(str, Enum):
    """Classes que recebem namespaces de placeholder independentes."""

    CALL_ID = "call_id"
    IDENTIFICADOR_CHAMADA = "call_id"
    UUID = "uuid"
    UUID_CANAL = "uuid_canal"
    UUID_SESSAO = "uuid_sessao"
    TELEFONE = "telefone"
    DOCUMENTO = "documento"
    IP = "ip"
    ENDERECO_IP = "ip"
    HOST_INTERNO = "host_interno"
    HOSTNAME_INTERNO = "host_interno"
    URL_INTERNA = "url_interna"
    CREDENCIAL = "credencial"
    DADO_CLIENTE = "dado_cliente"


_PREFIXO_PLACEHOLDER = {
    TipoDadoSensivel.CALL_ID: "CALL_ID",
    TipoDadoSensivel.UUID: "UUID",
    TipoDadoSensivel.UUID_CANAL: "UUID_CANAL",
    TipoDadoSensivel.UUID_SESSAO: "UUID_SESSAO",
    TipoDadoSensivel.TELEFONE: "TELEFONE",
    TipoDadoSensivel.DOCUMENTO: "DOCUMENTO",
    TipoDadoSensivel.IP: "IP",
    TipoDadoSensivel.HOST_INTERNO: "HOST_INTERNO",
    TipoDadoSensivel.URL_INTERNA: "URL_INTERNA",
    TipoDadoSensivel.CREDENCIAL: "CREDENCIAL",
    TipoDadoSensivel.DADO_CLIENTE: "DADO_CLIENTE",
}

_TIPO_POR_PREFIXO = {
    prefixo: tipo for tipo, prefixo in _PREFIXO_PLACEHOLDER.items()
}

_TIPO_POR_IDENTIFICADOR = {
    TipoIdentificador.CHAMADA_EXTERNA: TipoDadoSensivel.CALL_ID,
    TipoIdentificador.SIP: TipoDadoSensivel.CALL_ID,
    TipoIdentificador.TELECOM_CALL_ID: TipoDadoSensivel.CALL_ID,
    TipoIdentificador.CALL_ID: TipoDadoSensivel.CALL_ID,
    TipoIdentificador.UUID_CANAL: TipoDadoSensivel.UUID_CANAL,
    TipoIdentificador.UUID_SESSAO: TipoDadoSensivel.UUID_SESSAO,
}

_ALIASES_TIPO = {
    "call_id": TipoDadoSensivel.CALL_ID,
    "callid": TipoDadoSensivel.CALL_ID,
    "identificador_chamada": TipoDadoSensivel.CALL_ID,
    "chamada": TipoDadoSensivel.CALL_ID,
    "chamada_externa": TipoDadoSensivel.CALL_ID,
    "telecom_call_id": TipoDadoSensivel.CALL_ID,
    "sip": TipoDadoSensivel.CALL_ID,
    "uuid": TipoDadoSensivel.UUID,
    "uuid_canal": TipoDadoSensivel.UUID_CANAL,
    "uuid_sessao": TipoDadoSensivel.UUID_SESSAO,
    "telefone": TipoDadoSensivel.TELEFONE,
    "phone": TipoDadoSensivel.TELEFONE,
    "documento": TipoDadoSensivel.DOCUMENTO,
    "document": TipoDadoSensivel.DOCUMENTO,
    "cpf": TipoDadoSensivel.DOCUMENTO,
    "cnpj": TipoDadoSensivel.DOCUMENTO,
    "ip": TipoDadoSensivel.IP,
    "endereco_ip": TipoDadoSensivel.IP,
    "ipv4": TipoDadoSensivel.IP,
    "ipv6": TipoDadoSensivel.IP,
    "host_interno": TipoDadoSensivel.HOST_INTERNO,
    "hostname_interno": TipoDadoSensivel.HOST_INTERNO,
    "internal_host": TipoDadoSensivel.HOST_INTERNO,
    "url_interna": TipoDadoSensivel.URL_INTERNA,
    "internal_url": TipoDadoSensivel.URL_INTERNA,
    "credencial": TipoDadoSensivel.CREDENCIAL,
    "credential": TipoDadoSensivel.CREDENCIAL,
    "token": TipoDadoSensivel.CREDENCIAL,
    "secret": TipoDadoSensivel.CREDENCIAL,
    "password": TipoDadoSensivel.CREDENCIAL,
    "dado_cliente": TipoDadoSensivel.DADO_CLIENTE,
    "customer_data": TipoDadoSensivel.DADO_CLIENTE,
    "conteudo_cliente": TipoDadoSensivel.DADO_CLIENTE,
}

_TIPOS_CASE_INSENSITIVE = frozenset(
    {
        TipoDadoSensivel.CALL_ID,
        TipoDadoSensivel.UUID,
        TipoDadoSensivel.UUID_CANAL,
        TipoDadoSensivel.UUID_SESSAO,
        TipoDadoSensivel.IP,
        TipoDadoSensivel.HOST_INTERNO,
    }
)

# Valores que sinalizam ausência de conteúdo sensível. O scanner de governança
# ignora esses mesmos marcadores (ver ``_VALORES_NEUTROS`` em ``governanca``);
# o sanitizador precisa da simetria para não tentar normalizar um rótulo cujo
# valor já é vazio, neutro ou redigido. Inclui os marcadores de redação porque
# um valor já substituído não é dado sensível real a ser reprocessado.
_VALORES_NEUTROS = frozenset(
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


def _valor_rotulado_neutro(valor: str) -> bool:
    """Indica que o valor rotulado não carrega conteúdo sensível real.

    A comparação usa ``casefold`` após remover delimitadores externos, de modo
    que ``'callid': '[REDACTED]'`` ou ``ani: null`` sejam reconhecidos como
    marcadores neutros equivalentes aos ignorados pela governança.
    """

    base = _remover_sintaxe_externa(valor)
    return not base or base.casefold() in _VALORES_NEUTROS

_PARES_DELIMITADORES = {
    '"': '"',
    "'": "'",
    "<": ">",
    "[": "]",
    "(": ")",
    "{": "}",
}

_PADRAO_PLACEHOLDER = re.compile(
    r"<(?P<prefixo>CALL_ID|UUID_CANAL|UUID_SESSAO|UUID|TELEFONE|"
    r"DOCUMENTO|IP|HOST_INTERNO|URL_INTERNA|CREDENCIAL|DADO_CLIENTE)_"
    r"(?P<indice>[1-9][0-9]*)>"
)

_PADRAO_UUID = re.compile(
    r"(?<![0-9A-Fa-f])"
    r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
    r"(?![0-9A-Fa-f])"
)

_PADRAO_IPV4 = re.compile(
    r"(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9.])"
)

_PADRAO_IPV6 = re.compile(
    r"(?<![0-9A-Fa-f:])"
    r"(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}"
    r"(?![0-9A-Fa-f:])"
)

_PADRAO_TELEFONE = re.compile(
    r"(?<![0-9A-Za-z])"
    r"(?:\+[0-9]{1,3}[ .-]?)?"
    r"(?:\(?[0-9]{2,3}\)?[ .-]?)?"
    r"[0-9]{3,5}[ .-][0-9]{4}"
    r"(?![0-9A-Za-z])"
)

# E.164 sem separadores não é coberto pelo padrão formatado. O sinal ``+``
# reduz falsos positivos com contadores e timestamps puramente numéricos.
_PADRAO_E164 = re.compile(
    r"(?<![0-9A-Za-z])\+[1-9][0-9]{9,14}(?![0-9A-Za-z])"
)

_PADRAO_CPF = re.compile(
    r"(?<![0-9])[0-9]{3}\.[0-9]{3}\.[0-9]{3}-[0-9]{2}(?![0-9])"
)

_PADRAO_CNPJ = re.compile(
    r"(?<![0-9])[0-9]{2}\.[0-9]{3}\.[0-9]{3}/[0-9]{4}-[0-9]{2}(?![0-9])"
)

_PADRAO_URL = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:https?|wss?)://[^\s<>{}\[\]\"']+"
)

_PADRAO_HOST_INTERNO = re.compile(
    r"(?i)(?<![A-Za-z0-9-])(?:localhost|"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"(?:internal|local|lan|corp|intranet|private|invalid|test))"
    r"(?![A-Za-z0-9-])"
)

_PADRAO_EMAIL = re.compile(
    r"(?i)(?<![A-Za-z0-9.!#$%&'*+/=?^_`{|}~-])"
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*"
    r"(?![A-Za-z0-9-])"
)

_PADRAO_JWT = re.compile(
    r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{8,}\."
    r"[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?![A-Za-z0-9_-])"
)

# Valores opacos costumam ser um único token. Campos cujo domínio admite
# espaços usam a variante extensa, que termina antes de delimitador, fim de
# linha ou do próximo campo ``nome=valor``.
_VALOR_ROTULADO_CURTO = (
    r'(?:"(?P<valor_aspas_duplas>[^"\r\n]+)"'
    r"|'(?P<valor_aspas_simples>[^'\r\n]+)'"
    r"|(?P<valor>[^\s,;}\]\)\r\n]+))"
)

_LIMITE_VALOR_ROTULADO_EXTENSO = (
    r"(?=(?:[ \t]+[A-Za-z_][A-Za-z0-9_.-]*[ \t]*(?:=|:))"
    r"|[,;}\]]|\r|\n|$)"
)

_VALOR_ROTULADO_EXTENSO = (
    r'(?:"(?P<valor_aspas_duplas>[^"\r\n]+)"'
    r"|'(?P<valor_aspas_simples>[^'\r\n]+)'"
    r"|(?P<valor>[^\r\n,;}\]]+?)"
    rf"{_LIMITE_VALOR_ROTULADO_EXTENSO})"
)

_PADRAO_CALL_ID_ROTULADO = re.compile(
    rf"(?i)[\"']?\b(?:telecom[ _-]?call[ _-]?id|call[ _-]?id|"
    rf"id[ _-]?chamada)\b[\"']?\s*(?:=|:)\s*{_VALOR_ROTULADO_CURTO}"
)

_PADRAO_CALL_ID_SIP = re.compile(
    r"(?i)\bsip:(?P<valor>[^@\s;>]+)@"
)

_PADRAO_CALL_ID_CANAL = re.compile(
    r"(?i)\b(?:sofia|verto)/[^/\s]+/(?P<valor>[^@/\s;>]+)@"
)

# Identificadores de chamada OPACOS embutidos em texto livre. Espelha o
# ``_CALL_ID_OPACO_RE`` do scanner de governança para que um token do formato
# ``CALL_<...>``, ``CALL-<...>``, ``CALLID_<...>`` ou ``SYN_CALL_<...>`` seja
# substituído por ``<CALL_ID_n>`` mesmo quando aparece sob um rótulo não
# reconhecido (ex.: ``id``, ``tool_call_id``, ``ai_type``) ou colado a outros
# campos de um dicionário serializado. Sem esse detector defensivo, o valor
# cru sobreviveria à sanitização e o scanner final rejeitaria a visão
# (fail-closed). O token completo — prefixo mais sufixo — é o valor
# substituído, preservando a simetria exata com a detecção da governança.
_PADRAO_CALL_ID_OPACO = re.compile(
    r"(?i)(?<![A-Za-z0-9_-])"
    r"(?P<valor>(?:SYN_CALL|CALL(?:ID)?)[_-][A-Za-z0-9][A-Za-z0-9._-]{3,})"
    r"(?![A-Za-z0-9])"
)

_ROTULO_AUTORIZACAO = (
    r"[\"']?\bauthorization\b[\"']?\s*(?:=|:)\s*"
)
_ESQUEMA_AUTORIZACAO = r"(?:bearer|basic|api[ _-]?key|token)"

# Em esquemas conhecidos, somente o segredo é o valor sensível. Para um
# esquema desconhecido, o valor completo é tratado como credencial opaca.
_PADRAO_AUTORIZACAO_ESQUEMA = re.compile(
    rf"(?i){_ROTULO_AUTORIZACAO}{_ESQUEMA_AUTORIZACAO}\s+"
    rf"{_VALOR_ROTULADO_CURTO}"
)
_PADRAO_AUTORIZACAO_OPACA = re.compile(
    rf"(?i){_ROTULO_AUTORIZACAO}(?!{_ESQUEMA_AUTORIZACAO}\b)"
    rf"{_VALOR_ROTULADO_EXTENSO}"
)

_PADRAO_CREDENCIAL_ROTULADA = re.compile(
    rf"(?i)[\"']?\b(?:password|passwd|pwd|senha|secret|"
    rf"client[ _-]?secret|api[ _-]?key|access[ _-]?token|"
    rf"refresh[ _-]?token|token|credential|credencial)\b[\"']?"
    rf"\s*(?:=|:)\s*{_VALOR_ROTULADO_EXTENSO}"
)

_PADRAO_BEARER = re.compile(
    rf"(?i)\b{_ESQUEMA_AUTORIZACAO}\s+"
    r"(?P<valor>[^\s,;}\]\)\r\n]+)"
)

_PADRAO_TELEFONE_ROTULADO = re.compile(
    rf"(?i)[\"']?\b(?:telefone|phone|fone|celular|mobile|msisdn)\b"
    rf"[\"']?\s*(?:=|:)\s*{_VALOR_ROTULADO_EXTENSO}"
)

_PADRAO_DOCUMENTO_ROTULADO = re.compile(
    rf"(?i)[\"']?\b(?:cpf|cnpj|documento|document|doc)\b[\"']?"
    rf"\s*(?:=|:)\s*{_VALOR_ROTULADO_CURTO}"
)

_PADRAO_IP_ROTULADO = re.compile(
    rf"(?i)[\"']?\b(?:ip|ip[ _-]?address|endereco[ _-]?ip)\b[\"']?"
    rf"\s*(?:=|:)\s*{_VALOR_ROTULADO_CURTO}"
)

_PADRAO_HOST_ROTULADO = re.compile(
    rf"(?i)[\"']?\b(?:host|hostname|host[ _-]?interno|servidor)\b"
    rf"[\"']?\s*(?:=|:)\s*{_VALOR_ROTULADO_CURTO}"
)

_PADRAO_URL_ROTULADA = re.compile(
    rf"(?i)[\"']?\b(?:url|uri|url[ _-]?interna|endpoint)\b[\"']?"
    rf"\s*(?:=|:)\s*{_VALOR_ROTULADO_CURTO}"
)

_PADRAO_CLIENTE_ROTULADO = re.compile(
    rf"(?i)[\"']?\b(?:customer[ _-]?data|client[ _-]?data|"
    rf"dado[ _-]?cliente|conteudo[ _-]?cliente|nome[ _-]?cliente|"
    rf"customer|cliente|email)\b[\"']?\s*(?:=|:)\s*"
    rf"{_VALOR_ROTULADO_EXTENSO}"
)

_SUFIXOS_HOST_INTERNO = (
    ".internal",
    ".local",
    ".lan",
    ".corp",
    ".intranet",
    ".private",
    ".invalid",
    ".test",
    ".home.arpa",
)


@dataclass(frozen=True, slots=True)
class CampoSensivel:
    """Campo estruturado de entrada para sanitização.

    ``tipo`` pode ser omitido quando o nome é reconhecível ou quando o valor
    contém uma forma detectável defensivamente. Para identificadores opacos, o
    tipo deve ser informado.
    """

    nome: str
    valor: str = field(repr=False)
    tipo: TipoDadoSensivel | TipoIdentificador | str | None = None
    valor_normalizado: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.nome, str) or not self.nome.strip():
            raise ValueError("nome do campo deve ser uma string não vazia.")
        if not isinstance(self.valor, str) or not self.valor:
            raise ValueError("valor do campo deve ser uma string não vazia.")
        if self.valor_normalizado is not None and (
            not isinstance(self.valor_normalizado, str)
            or not self.valor_normalizado.strip()
        ):
            raise ValueError(
                "valor_normalizado deve ser uma string não vazia ou None."
            )


@dataclass(frozen=True, slots=True)
class CampoSanitizado:
    """Nome estrutural preservado e valor seguro correspondente."""

    nome: str
    valor: str

    @property
    def valor_sanitizado(self) -> str:
        return self.valor


@dataclass(frozen=True, slots=True)
class DeteccaoSensivel:
    """Achado seguro: informa somente tipo e intervalo, nunca o valor."""

    tipo: TipoDadoSensivel
    inicio: int
    fim: int


@dataclass(frozen=True, slots=True, repr=False)
class _Candidato:
    tipo: TipoDadoSensivel
    inicio: int
    fim: int
    valor_normalizado: str = field(repr=False)
    prioridade: int
    ordem: int

    @property
    def tamanho(self) -> int:
        return self.fim - self.inicio


@dataclass(frozen=True, slots=True, repr=False)
class _VarianteConhecida:
    texto: str = field(repr=False)
    tipo: TipoDadoSensivel
    valor_normalizado: str = field(repr=False)
    ordem: int


def _coagir_tipo(
    tipo: TipoDadoSensivel | TipoIdentificador | str,
) -> TipoDadoSensivel:
    if isinstance(tipo, TipoDadoSensivel):
        return tipo
    if isinstance(tipo, TipoIdentificador):
        try:
            return _TIPO_POR_IDENTIFICADOR[tipo]
        except KeyError:
            raise ValueError("tipo de identificador sem sanitização definida.") from None
    if isinstance(tipo, str):
        chave = tipo.strip().casefold().replace("-", " ")
        chave = "_".join(chave.split())
        try:
            return _ALIASES_TIPO[chave]
        except KeyError:
            raise ValueError("tipo de dado sensível não reconhecido.") from None
    raise TypeError("tipo de dado sensível inválido.")


def _remover_sintaxe_externa(valor: str) -> str:
    resultado = valor.strip()
    while len(resultado) >= 2:
        fechamento = _PARES_DELIMITADORES.get(resultado[0])
        if fechamento is None or resultado[-1] != fechamento:
            break
        resultado = resultado[1:-1].strip()
    return resultado


def _normalizar_valor(
    tipo: TipoDadoSensivel,
    valor: str,
    valor_normalizado: str | None = None,
) -> str:
    if not isinstance(valor, str) or not valor.strip():
        raise ValueError("valor sensível deve ser uma string não vazia.")
    if valor_normalizado is not None and (
        not isinstance(valor_normalizado, str) or not valor_normalizado.strip()
    ):
        raise ValueError(
            "valor normalizado deve ser uma string não vazia ou None."
        )

    base = valor if valor_normalizado is None else valor_normalizado
    base = _remover_sintaxe_externa(base)
    if not base:
        raise ValueError("valor sensível normalizado não pode ser vazio.")

    if tipo is TipoDadoSensivel.CALL_ID:
        return base.casefold()

    if tipo in {
        TipoDadoSensivel.UUID,
        TipoDadoSensivel.UUID_CANAL,
        TipoDadoSensivel.UUID_SESSAO,
    }:
        try:
            return str(UUID(base.strip("{}")))
        except (AttributeError, ValueError):
            raise ValueError("UUID sensível inválido.") from None

    if tipo is TipoDadoSensivel.TELEFONE:
        digitos = "".join(caractere for caractere in base if caractere.isdigit())
        if not 10 <= len(digitos) <= 15:
            raise ValueError("telefone sensível inválido.")
        return digitos

    if tipo is TipoDadoSensivel.DOCUMENTO:
        digitos = "".join(caractere for caractere in base if caractere.isdigit())
        if len(digitos) not in {11, 14}:
            raise ValueError("documento sensível inválido.")
        return digitos

    if tipo is TipoDadoSensivel.IP:
        try:
            return ip_address(base.strip("[]")).compressed.casefold()
        except ValueError:
            raise ValueError("endereço IP sensível inválido.") from None

    if tipo is TipoDadoSensivel.HOST_INTERNO:
        host = base.rstrip(".").casefold()
        if not host or any(caractere.isspace() for caractere in host):
            raise ValueError("hostname interno sensível inválido.")
        return host

    if tipo is TipoDadoSensivel.URL_INTERNA:
        try:
            partes = urlsplit(base)
        except ValueError:
            raise ValueError("URL interna sensível inválida.") from None
        if partes.scheme.casefold() not in {"http", "https", "ws", "wss"}:
            raise ValueError("URL interna sensível inválida.")
        try:
            hostname = partes.hostname
        except ValueError:
            raise ValueError("URL interna sensível inválida.") from None
        if not hostname:
            raise ValueError("URL interna sensível inválida.")
        # URLs podem possuir caminhos case-sensitive; somente esquema e host são
        # canonicalizados implicitamente pelo parser para validação. O valor
        # completo continua distinguível por comparação exata.
        return base

    if tipo in {
        TipoDadoSensivel.CREDENCIAL,
        TipoDadoSensivel.DADO_CLIENTE,
    }:
        return base

    raise ValueError("tipo de dado sensível sem normalização definida.")


def _normalizar_rotulado_opaco(
    tipo: TipoDadoSensivel,
    valor: str,
) -> str:
    """Normaliza defensivamente um valor cujo rótulo já prova sensibilidade.

    Detectores heurísticos podem descartar falsos positivos, mas um campo
    explicitamente rotulado nunca pode voltar ao texto bruto só porque seu
    formato é incomum. A chave continua determinística por tipo e conteúdo.
    """

    base = _remover_sintaxe_externa(valor)
    if not base:
        raise ValueError("valor rotulado sensível inválido.")
    if tipo in {TipoDadoSensivel.TELEFONE, TipoDadoSensivel.DOCUMENTO}:
        digitos = "".join(caractere for caractere in base if caractere.isdigit())
        if digitos:
            return digitos
    if tipo in _TIPOS_CASE_INSENSITIVE:
        return base.casefold()
    return base


def _host_eh_interno(hostname: str) -> bool:
    host = hostname.rstrip(".").casefold()
    if host == "localhost" or host.endswith(_SUFIXOS_HOST_INTERNO):
        return True
    try:
        endereco = ip_address(host.strip("[]"))
    except ValueError:
        # Host sem ponto representa resolução local; FQDN público não é
        # classificado como interno sem um sufixo aprovado.
        return "." not in host
    return not endereco.is_global


def _url_eh_interna(valor: str) -> bool:
    try:
        partes = urlsplit(valor)
        hostname = partes.hostname
    except ValueError:
        return False
    return bool(
        partes.scheme.casefold() in {"http", "https", "ws", "wss"}
        and hostname
        and _host_eh_interno(hostname)
    )


def _span_valor_rotulado(match: re.Match[str]) -> tuple[int, int] | None:
    for nome in ("valor_aspas_duplas", "valor_aspas_simples", "valor"):
        try:
            inicio, fim = match.span(nome)
        except IndexError:
            continue
        if inicio >= 0 and fim > inicio:
            return inicio, fim
    return None


def _ajustar_fim_url(texto: str, inicio: int, fim: int) -> int:
    while fim > inicio and texto[fim - 1] in ".,;!?":
        fim -= 1
    while fim > inicio and texto[fim - 1] == ")":
        trecho = texto[inicio:fim]
        if trecho.count(")") <= trecho.count("("):
            break
        fim -= 1
    return fim


def _criar_candidato(
    texto: str,
    *,
    tipo: TipoDadoSensivel,
    inicio: int,
    fim: int,
    prioridade: int,
    ordem: int,
    valor_normalizado: str | None = None,
    rotulado: bool = False,
) -> _Candidato | None:
    if inicio < 0 or fim <= inicio or fim > len(texto):
        return None
    valor = texto[inicio:fim]
    if _PADRAO_PLACEHOLDER.fullmatch(valor.strip()) is not None:
        return None
    # Um rótulo sensível cujo valor é vazio, neutro ou já redigido não expõe
    # conteúdo real. Descartá-lo evita que ``_normalizar_rotulado_opaco`` falhe
    # e derrube a sanitização inteira (fail-closed) sem haver dado a proteger.
    # A verificação restringe-se a valores rotulados: valores REAIS que falham
    # a normalização por outro motivo continuam fail-closed abaixo.
    if rotulado and _valor_rotulado_neutro(valor):
        return None
    try:
        normalizado = _normalizar_valor(tipo, valor, valor_normalizado)
    except (TypeError, ValueError):
        if not rotulado:
            return None
        normalizado = _normalizar_rotulado_opaco(tipo, valor)
    return _Candidato(
        tipo=tipo,
        inicio=inicio,
        fim=fim,
        valor_normalizado=normalizado,
        prioridade=prioridade,
        ordem=ordem,
    )


def _adicionar_rotulados(
    destino: list[_Candidato],
    texto: str,
    padrao: re.Pattern[str],
    tipo: TipoDadoSensivel,
    prioridade: int,
    ordem_inicial: int,
) -> int:
    ordem = ordem_inicial
    for match in padrao.finditer(texto):
        span = _span_valor_rotulado(match)
        if span is None:
            continue
        candidato = _criar_candidato(
            texto,
            tipo=tipo,
            inicio=span[0],
            fim=span[1],
            prioridade=prioridade,
            ordem=ordem,
            rotulado=True,
        )
        ordem += 1
        if candidato is not None:
            destino.append(candidato)
    return ordem


def _detectar_candidatos(texto: str) -> list[_Candidato]:
    candidatos: list[_Candidato] = []
    ordem = 0

    detectores_rotulados = (
        (_PADRAO_AUTORIZACAO_ESQUEMA, TipoDadoSensivel.CREDENCIAL, 8),
        (_PADRAO_AUTORIZACAO_OPACA, TipoDadoSensivel.CREDENCIAL, 9),
        (_PADRAO_CREDENCIAL_ROTULADA, TipoDadoSensivel.CREDENCIAL, 10),
        (_PADRAO_BEARER, TipoDadoSensivel.CREDENCIAL, 11),
        (_PADRAO_CALL_ID_ROTULADO, TipoDadoSensivel.CALL_ID, 20),
        (_PADRAO_CALL_ID_SIP, TipoDadoSensivel.CALL_ID, 21),
        (_PADRAO_CALL_ID_CANAL, TipoDadoSensivel.CALL_ID, 22),
        (_PADRAO_URL_ROTULADA, TipoDadoSensivel.URL_INTERNA, 30),
        (_PADRAO_DOCUMENTO_ROTULADO, TipoDadoSensivel.DOCUMENTO, 40),
        (_PADRAO_TELEFONE_ROTULADO, TipoDadoSensivel.TELEFONE, 41),
        (_PADRAO_IP_ROTULADO, TipoDadoSensivel.IP, 42),
        (_PADRAO_HOST_ROTULADO, TipoDadoSensivel.HOST_INTERNO, 43),
        (_PADRAO_CLIENTE_ROTULADO, TipoDadoSensivel.DADO_CLIENTE, 50),
    )
    for padrao, tipo, prioridade in detectores_rotulados:
        ordem = _adicionar_rotulados(
            candidatos,
            texto,
            padrao,
            tipo,
            prioridade,
            ordem,
        )

    for match in _PADRAO_URL.finditer(texto):
        fim = _ajustar_fim_url(texto, match.start(), match.end())
        valor = texto[match.start():fim]
        if not _url_eh_interna(valor):
            continue
        candidato = _criar_candidato(
            texto,
            tipo=TipoDadoSensivel.URL_INTERNA,
            inicio=match.start(),
            fim=fim,
            prioridade=30,
            ordem=ordem,
        )
        ordem += 1
        if candidato is not None:
            candidatos.append(candidato)

    detectores_diretos = (
        (_PADRAO_JWT, TipoDadoSensivel.CREDENCIAL, 12),
        (_PADRAO_CALL_ID_OPACO, TipoDadoSensivel.CALL_ID, 23),
        (_PADRAO_CNPJ, TipoDadoSensivel.DOCUMENTO, 40),
        (_PADRAO_CPF, TipoDadoSensivel.DOCUMENTO, 40),
        (_PADRAO_E164, TipoDadoSensivel.TELEFONE, 41),
        (_PADRAO_TELEFONE, TipoDadoSensivel.TELEFONE, 41),
        (_PADRAO_UUID, TipoDadoSensivel.UUID, 45),
        (_PADRAO_IPV4, TipoDadoSensivel.IP, 46),
        (_PADRAO_IPV6, TipoDadoSensivel.IP, 46),
        (_PADRAO_EMAIL, TipoDadoSensivel.DADO_CLIENTE, 50),
        (_PADRAO_HOST_INTERNO, TipoDadoSensivel.HOST_INTERNO, 60),
    )
    for padrao, tipo, prioridade in detectores_diretos:
        for match in padrao.finditer(texto):
            candidato = _criar_candidato(
                texto,
                tipo=tipo,
                inicio=match.start(),
                fim=match.end(),
                prioridade=prioridade,
                ordem=ordem,
            )
            ordem += 1
            if candidato is not None:
                candidatos.append(candidato)

    return candidatos


def _intervalos_placeholders(texto: str) -> tuple[tuple[int, int], ...]:
    return tuple(match.span() for match in _PADRAO_PLACEHOLDER.finditer(texto))


def _resolver_longest_match(
    candidatos: Iterable[_Candidato],
    protegidos: tuple[tuple[int, int], ...],
) -> list[_Candidato]:
    unicos: dict[
        tuple[int, int, TipoDadoSensivel, str], _Candidato
    ] = {}
    for candidato in candidatos:
        sobrepostos = tuple(
            (inicio, fim)
            for inicio, fim in protegidos
            if candidato.inicio < fim and candidato.fim > inicio
        )
        if sobrepostos:
            if any(
                candidato.inicio >= inicio and candidato.fim <= fim
                for inicio, fim in sobrepostos
            ):
                continue
            # Um candidato parcialmente coberto por placeholder poderia deixar
            # um sufixo bruto. Sem uma chave inequívoca para unir os intervalos,
            # a única saída segura é abortar toda a sanitização.
            raise ValueError("sobreposição sensível inconclusiva.")
        chave = (
            candidato.inicio,
            candidato.fim,
            candidato.tipo,
            candidato.valor_normalizado,
        )
        anterior = unicos.get(chave)
        if anterior is None or (
            candidato.prioridade,
            candidato.ordem,
        ) < (
            anterior.prioridade,
            anterior.ordem,
        ):
            unicos[chave] = candidato

    ordenados = sorted(
        unicos.values(),
        key=lambda item: (
            item.inicio,
            -item.tamanho,
            item.prioridade,
            item.ordem,
            item.tipo.value,
        ),
    )
    selecionados: list[_Candidato] = []
    cursor = 0
    for candidato in ordenados:
        if candidato.inicio < cursor:
            anterior = selecionados[-1]
            if candidato.fim > anterior.fim:
                # Leftmost/longest só é seguro quando todo candidato rejeitado
                # está contido no intervalo vencedor.
                raise ValueError("sobreposição sensível inconclusiva.")
            continue
        selecionados.append(candidato)
        cursor = candidato.fim
    return selecionados


def detectar_dados_sensiveis(texto: str) -> tuple[DeteccaoSensivel, ...]:
    """Detecta classes sensíveis sem retornar ou interpolar os valores.

    Placeholders tipados existentes são tratados como regiões seguras. Em caso
    de falha, nenhuma detecção parcial é retornada.
    """

    if not isinstance(texto, str):
        raise ErroDeSanitizacao() from None
    try:
        protegidos = _intervalos_placeholders(texto)
        candidatos = _detectar_candidatos(texto)
        selecionados = _resolver_longest_match(candidatos, protegidos)
        return tuple(
            DeteccaoSensivel(item.tipo, item.inicio, item.fim)
            for item in selecionados
        )
    except Exception:
        raise ErroDeSanitizacao() from None


def inferir_tipo_dado_sensivel(nome_campo: str) -> TipoDadoSensivel | None:
    """Infere somente nomes estruturados conhecidos, sem examinar o valor."""

    if not isinstance(nome_campo, str):
        return None
    nome = "".join(
        caractere
        for caractere in nome_campo.casefold()
        if caractere.isalnum()
    )
    if not nome:
        return None

    if any(
        marcador in nome
        for marcador in (
            "authorization",
            "password",
            "passwd",
            "senha",
            "secret",
            "apikey",
            "accesstoken",
            "refreshtoken",
            "credential",
            "credencial",
        )
    ) or nome in {"pwd", "token"}:
        return TipoDadoSensivel.CREDENCIAL
    if any(
        marcador in nome
        for marcador in ("telecomcallid", "callid", "idchamada")
    ):
        return TipoDadoSensivel.CALL_ID
    if "uuid" in nome:
        if any(marcador in nome for marcador in ("canal", "channel")):
            return TipoDadoSensivel.UUID_CANAL
        if any(marcador in nome for marcador in ("sessao", "session")):
            return TipoDadoSensivel.UUID_SESSAO
        return TipoDadoSensivel.UUID
    if any(
        marcador in nome
        for marcador in (
            "telefone",
            "phone",
            "fone",
            "celular",
            "mobile",
            "msisdn",
        )
    ):
        return TipoDadoSensivel.TELEFONE
    if any(marcador in nome for marcador in ("cpf", "cnpj", "documento")):
        return TipoDadoSensivel.DOCUMENTO
    if nome in {"document", "doc"}:
        return TipoDadoSensivel.DOCUMENTO
    if nome in {"ip", "ipaddress", "enderecoip", "remoteip", "clientip"}:
        return TipoDadoSensivel.IP
    if any(
        marcador in nome
        for marcador in ("urlinterna", "internalurl", "endpointinterno")
    ) or nome in {"url", "uri", "endpoint"}:
        return TipoDadoSensivel.URL_INTERNA
    if nome in {"host", "hostname", "hostinterno", "servidor"}:
        return TipoDadoSensivel.HOST_INTERNO
    if any(
        marcador in nome
        for marcador in (
            "dadocliente",
            "customerdata",
            "clientdata",
            "conteudocliente",
            "nomecliente",
            "emailcliente",
        )
    ) or nome in {"cliente", "customer", "client", "email"}:
        return TipoDadoSensivel.DADO_CLIENTE
    return None


def _coagir_campo(
    campo: CampoSensivel
    | CampoEstruturado
    | IdentificadorTecnico
    | tuple[object, ...]
    | list[object],
) -> CampoSensivel:
    if isinstance(campo, CampoSensivel):
        return campo
    if isinstance(campo, IdentificadorTecnico):
        return CampoSensivel(
            nome=campo.nome_campo,
            valor=campo.valor_original,
            tipo=campo.tipo,
            valor_normalizado=campo.valor_normalizado,
        )
    if isinstance(campo, CampoEstruturado):
        return CampoSensivel(
            nome=campo.nome,
            valor=campo.valor_original,
            tipo=inferir_tipo_dado_sensivel(campo.nome),
        )
    if isinstance(campo, (tuple, list)):
        if len(campo) == 2:
            nome, valor = campo
            tipo = None
            normalizado = None
        elif len(campo) == 3:
            nome, valor, tipo = campo
            normalizado = None
        elif len(campo) == 4:
            nome, valor, tipo, normalizado = campo
        else:
            raise TypeError("descritor de campo estruturado inválido.")
        if not isinstance(nome, str) or not isinstance(valor, str):
            raise TypeError("descritor de campo estruturado inválido.")
        if normalizado is not None and not isinstance(normalizado, str):
            raise TypeError("descritor de campo estruturado inválido.")
        return CampoSensivel(nome, valor, tipo, normalizado)
    raise TypeError("campo estruturado inválido.")


class SanitizationContext:
    """Contexto efêmero e determinístico de uma única análise.

    O objeto não expõe seu mapa bruto. Use-o como context manager ou invoque
    :meth:`descartar_mapa_bruto` em um ``finally``. Depois do descarte (ou de
    qualquer falha), novas operações falham com :class:`ErroDeSanitizacao` e
    mensagem constante.
    """

    __slots__ = (
        "_mapa",
        "_contadores",
        "_variantes",
        "_indice_variantes",
        "_proxima_ordem",
        "_texto_iniciado",
        "_ativo",
        "_falhou",
    )

    def __init__(self) -> None:
        self._mapa: dict[tuple[TipoDadoSensivel, str], str] = {}
        self._contadores: dict[TipoDadoSensivel, int] = {}
        self._variantes: list[_VarianteConhecida] = []
        self._indice_variantes: set[
            tuple[str, TipoDadoSensivel, str]
        ] = set()
        self._proxima_ordem = 0
        self._texto_iniciado = False
        self._ativo = True
        self._falhou = False

    def __enter__(self) -> SanitizationContext:
        self._assegurar_ativo()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        self.descartar_mapa_bruto()
        return False

    def __del__(self) -> None:
        try:
            self._limpar()
        except Exception:
            pass

    def __repr__(self) -> str:
        estado = "ativo" if self._ativo else ("falhou" if self._falhou else "descartado")
        return (
            f"{type(self).__name__}(estado={estado!r}, "
            f"quantidade={len(self._mapa)})"
        )

    def __len__(self) -> int:
        return len(self._mapa)

    @property
    def ativo(self) -> bool:
        return self._ativo

    @property
    def descartado(self) -> bool:
        return not self._ativo and not self._falhou

    @property
    def falhou(self) -> bool:
        return self._falhou

    @property
    def quantidade_mapeamentos(self) -> int:
        return len(self._mapa)

    def placeholder_para(
        self,
        tipo: TipoDadoSensivel | TipoIdentificador | str,
        valor: str,
        *,
        valor_normalizado: str | None = None,
    ) -> str:
        """Obtém o placeholder estável para um valor estruturado.

        O contador é independente por tipo e avança somente quando um novo par
        ``(tipo, valor_normalizado)`` é observado.
        """

        try:
            self._assegurar_fase_estruturada()
            tipo_resolvido = _coagir_tipo(tipo)
            if not isinstance(valor, str):
                raise TypeError("valor sensível inválido.")

            placeholder_existente = _PADRAO_PLACEHOLDER.fullmatch(valor.strip())
            if placeholder_existente is not None:
                self._reservar_placeholder(placeholder_existente)
                tipo_placeholder = _TIPO_POR_PREFIXO[
                    placeholder_existente.group("prefixo")
                ]
                if tipo_placeholder is not tipo_resolvido:
                    raise ValueError("placeholder possui tipo incompatível.")
                return valor.strip()

            normalizado = _normalizar_valor(
                tipo_resolvido,
                valor,
                valor_normalizado,
            )
            return self._obter_ou_criar_placeholder(
                tipo_resolvido,
                normalizado,
                valor,
            )
        except ErroDeSanitizacao:
            raise
        except Exception:
            self._falhar()
            raise ErroDeSanitizacao() from None

    obter_placeholder = placeholder_para
    registrar = placeholder_para

    def sanitizar_valor_estruturado(
        self,
        nome: str,
        valor: str,
        tipo: TipoDadoSensivel | TipoIdentificador | str | None = None,
        *,
        valor_normalizado: str | None = None,
    ) -> CampoSanitizado:
        """Sanitiza um campo sem alterar seu nome estrutural."""

        try:
            self._assegurar_fase_estruturada()
            campo = CampoSensivel(nome, valor, tipo, valor_normalizado)
            tipo_resolvido = (
                inferir_tipo_dado_sensivel(campo.nome)
                if campo.tipo is None
                else _coagir_tipo(campo.tipo)
            )
            if tipo_resolvido is None:
                valor_seguro = self._sanitizar_texto_impl(campo.valor)
            else:
                valor_seguro = self.placeholder_para(
                    tipo_resolvido,
                    campo.valor,
                    valor_normalizado=campo.valor_normalizado,
                )
            return CampoSanitizado(campo.nome, valor_seguro)
        except ErroDeSanitizacao:
            raise
        except Exception:
            self._falhar()
            raise ErroDeSanitizacao() from None

    sanitizar_campo = sanitizar_valor_estruturado

    def sanitizar_campos_estruturados(
        self,
        campos: Iterable[
            CampoSensivel
            | CampoEstruturado
            | IdentificadorTecnico
            | tuple[object, ...]
            | list[object]
        ]
        | Mapping[str, str],
    ) -> tuple[CampoSanitizado, ...]:
        """Sanitiza campos em ordem, preservando cardinalidade e nomes.

        Identificadores técnicos usam diretamente seu valor normalizado. Um
        ``Mapping`` preserva a ordem de iteração do próprio mapping.
        """

        try:
            self._assegurar_fase_estruturada()
            if isinstance(campos, Mapping):
                descritores = [
                    CampoSensivel(nome, valor)
                    for nome, valor in campos.items()
                ]
            else:
                if isinstance(campos, (str, bytes)):
                    raise TypeError("coleção de campos estruturados inválida.")
                descritores = [_coagir_campo(campo) for campo in campos]

            # Primeiro registre todos os campos semanticamente tipados. Assim,
            # um UUID incidental em campo genérico reutiliza depois o tipo do
            # campo estruturado correspondente, em vez de criar relação falsa.
            preparados: list[
                tuple[CampoSensivel, TipoDadoSensivel | None, str | None]
            ] = []
            for campo in descritores:
                tipo_resolvido = (
                    inferir_tipo_dado_sensivel(campo.nome)
                    if campo.tipo is None
                    else _coagir_tipo(campo.tipo)
                )
                placeholder = (
                    self.placeholder_para(
                        tipo_resolvido,
                        campo.valor,
                        valor_normalizado=campo.valor_normalizado,
                    )
                    if tipo_resolvido is not None
                    else None
                )
                preparados.append((campo, tipo_resolvido, placeholder))

            resultado: list[CampoSanitizado] = []
            for campo, tipo_resolvido, placeholder in preparados:
                valor_seguro = (
                    placeholder
                    if tipo_resolvido is not None
                    else self._sanitizar_texto_impl(campo.valor)
                )
                if valor_seguro is None:
                    raise RuntimeError("campo tipado sem placeholder.")
                resultado.append(CampoSanitizado(campo.nome, valor_seguro))
            if len(resultado) != len(descritores):
                raise RuntimeError("cardinalidade de campos não preservada.")
            return tuple(resultado)
        except ErroDeSanitizacao:
            raise
        except Exception:
            self._falhar()
            raise ErroDeSanitizacao() from None

    sanitizar_campos = sanitizar_campos_estruturados

    def sanitizar_texto(self, texto: str) -> str:
        """Sanitiza texto livre por leftmost/longest-match determinístico.

        A primeira chamada encerra a fase estrutural. Chamadas textuais
        subsequentes são permitidas; registrar campos depois disso é rejeitado
        para impedir que uma detecção genérica antecipe o tipo estruturado.
        """

        try:
            self._assegurar_ativo()
            self._texto_iniciado = True
            return self._sanitizar_texto_impl(texto)
        except ErroDeSanitizacao:
            raise
        except Exception:
            self._falhar()
            raise ErroDeSanitizacao() from None

    def _sanitizar_texto_impl(self, texto: str) -> str:
        if not isinstance(texto, str):
            raise TypeError("texto para sanitização deve ser string.")
        self._reservar_placeholders_no_texto(texto)
        protegidos = _intervalos_placeholders(texto)

        detectados = _resolver_longest_match(
            _detectar_candidatos(texto),
            protegidos,
        )

        variantes_provisorias = list(self._variantes)
        ordem = self._proxima_ordem
        for candidato in detectados:
            variantes_provisorias.append(
                _VarianteConhecida(
                    texto=texto[candidato.inicio:candidato.fim],
                    tipo=candidato.tipo,
                    valor_normalizado=candidato.valor_normalizado,
                    ordem=ordem,
                )
            )
            ordem += 1

        candidatos: list[_Candidato] = list(detectados)
        for variante in variantes_provisorias:
            flags = (
                re.IGNORECASE
                if variante.tipo in _TIPOS_CASE_INSENSITIVE
                else 0
            )
            for match in re.finditer(
                re.escape(variante.texto),
                texto,
                flags,
            ):
                candidatos.append(
                    _Candidato(
                        tipo=variante.tipo,
                        inicio=match.start(),
                        fim=match.end(),
                        valor_normalizado=variante.valor_normalizado,
                        prioridade=0,
                        ordem=variante.ordem,
                    )
                )

        selecionados = _resolver_longest_match(candidatos, protegidos)
        if not selecionados:
            return texto

        partes: list[str] = []
        cursor = 0
        for candidato in selecionados:
            partes.append(texto[cursor:candidato.inicio])
            valor_original = texto[candidato.inicio:candidato.fim]
            partes.append(
                self._obter_ou_criar_placeholder(
                    candidato.tipo,
                    candidato.valor_normalizado,
                    valor_original,
                )
            )
            cursor = candidato.fim
        partes.append(texto[cursor:])
        return "".join(partes)

    def sanitizar_campos_e_texto(
        self,
        campos: Iterable[
            CampoSensivel
            | CampoEstruturado
            | IdentificadorTecnico
            | tuple[object, ...]
            | list[object]
        ]
        | Mapping[str, str],
        texto: str,
    ) -> tuple[tuple[CampoSanitizado, ...], str]:
        """Executa explicitamente a ordem campos estruturados → texto livre."""

        try:
            self._assegurar_ativo()
            campos_sanitizados = self.sanitizar_campos_estruturados(campos)
            texto_sanitizado = self.sanitizar_texto(texto)
            return campos_sanitizados, texto_sanitizado
        except ErroDeSanitizacao:
            raise
        except Exception:
            self._falhar()
            raise ErroDeSanitizacao() from None

    sanitizar_estrutura_e_texto = sanitizar_campos_e_texto

    def descartar_mapa_bruto(self) -> None:
        """Remove mapa, variantes e contadores; a operação é idempotente."""

        self._limpar()
        self._ativo = False

    close = descartar_mapa_bruto
    descartar = descartar_mapa_bruto

    def _assegurar_ativo(self) -> None:
        if not self._ativo:
            raise ErroDeSanitizacao()

    def _assegurar_fase_estruturada(self) -> None:
        self._assegurar_ativo()
        if self._texto_iniciado:
            self._falhar()
            raise ErroDeSanitizacao()

    def _obter_ou_criar_placeholder(
        self,
        tipo: TipoDadoSensivel,
        valor_normalizado: str,
        valor_original: str,
    ) -> str:
        chave = (tipo, valor_normalizado)
        placeholder = self._mapa.get(chave)
        if placeholder is None:
            indice = self._contadores.get(tipo, 0) + 1
            self._contadores[tipo] = indice
            placeholder = f"<{_PREFIXO_PLACEHOLDER[tipo]}_{indice}>"
            self._mapa[chave] = placeholder
        self._registrar_variantes(tipo, valor_normalizado, valor_original)
        return placeholder

    def _registrar_variantes(
        self,
        tipo: TipoDadoSensivel,
        valor_normalizado: str,
        valor_original: str,
    ) -> None:
        variantes = [valor_original, valor_original.strip()]
        sem_sintaxe = _remover_sintaxe_externa(valor_original)
        variantes.append(sem_sintaxe)
        if valor_normalizado != sem_sintaxe:
            variantes.append(valor_normalizado)

        for variante in variantes:
            if not variante or _PADRAO_PLACEHOLDER.fullmatch(variante) is not None:
                continue
            chave = (variante, tipo, valor_normalizado)
            if chave in self._indice_variantes:
                continue
            self._indice_variantes.add(chave)
            self._variantes.append(
                _VarianteConhecida(
                    texto=variante,
                    tipo=tipo,
                    valor_normalizado=valor_normalizado,
                    ordem=self._proxima_ordem,
                )
            )
            self._proxima_ordem += 1

    def _reservar_placeholder(self, match: re.Match[str]) -> None:
        tipo = _TIPO_POR_PREFIXO[match.group("prefixo")]
        indice = int(match.group("indice"))
        self._contadores[tipo] = max(self._contadores.get(tipo, 0), indice)

    def _reservar_placeholders_no_texto(self, texto: str) -> None:
        for match in _PADRAO_PLACEHOLDER.finditer(texto):
            self._reservar_placeholder(match)

    def _falhar(self) -> None:
        self._limpar()
        self._ativo = False
        self._falhou = True

    def _limpar(self) -> None:
        self._mapa.clear()
        self._contadores.clear()
        self._variantes.clear()
        self._indice_variantes.clear()
        self._proxima_ordem = 0
        self._texto_iniciado = False


ContextoDeSanitizacao = SanitizationContext
SensitiveDataType = TipoDadoSensivel


def sanitizar_texto(texto: str) -> str:
    """Atalho para sanitizar um texto isolado e descartar o mapa em seguida."""

    with SanitizationContext() as contexto:
        return contexto.sanitizar_texto(texto)


__all__ = [
    "CampoSanitizado",
    "CampoSensivel",
    "ContextoDeSanitizacao",
    "DeteccaoSensivel",
    "SanitizationContext",
    "SensitiveDataType",
    "TipoDadoSensivel",
    "detectar_dados_sensiveis",
    "inferir_tipo_dado_sensivel",
    "sanitizar_texto",
]
