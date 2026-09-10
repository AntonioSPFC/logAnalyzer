"""Modelos de dados do domínio do Analisador de Logs.

Os campos e modelos da Fase 2 são estritamente aditivos. Os prefixos públicos de
``EntradaDeLog`` e ``ResultadoDeAnalise`` permanecem idênticos aos da Fase 1,
assim como ``Categoria`` e a imutabilidade de ``EntradaDeLog``.

As validações deste módulo cobrem os invariantes que podem ser decididos apenas
com os dados dos próprios modelos. Objetos legados, que não possuem metadados da
Fase 2, continuam válidos sem precisar preenchê-los.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum


class Categoria(Enum):
    """Categorias de classificação preservadas da Fase 1."""

    SUCESSO = "sucesso"
    ERRO = "erro"
    NAO_CLASSIFICADA = "não classificada"


class TipoIdentificador(Enum):
    """Tipos aprovados de identificadores técnicos."""

    CHAMADA_EXTERNA = "chamada_externa"
    SIP = "sip"
    UUID_CANAL = "uuid_canal"
    UUID_SESSAO = "uuid_sessao"
    TELECOM_CALL_ID = "telecom_call_id"
    CALL_ID = "call_id"


class BaseCorrelacao(Enum):
    """Bases possíveis para uma correlação entre aplicações."""

    VALOR_COMPARTILHADO = "valor_compartilhado"
    CADEIA_DE_VINCULOS = "cadeia_de_vinculos"
    NENHUMA = "nenhuma"
    AMBIGUA = "ambigua"


class EstadoSanitizacao(Enum):
    """Estado da visão de um resultado em relação à sanitização."""

    INTERNA_BRUTA = "interna_bruta"
    CONCLUIDA = "concluida"
    FALHOU_SUPRIMIDA = "falhou_suprimida"


class EstadoCausaRaiz(Enum):
    """Estado de determinação da causa-raiz de um cenário."""

    DETERMINADA = "determinada"
    NAO_DETERMINADA = "nao_determinada"


def _exigir_texto_preenchido(valor: object, nome_campo: str) -> None:
    """Rejeita metadado obrigatório ausente sem ecoar seu conteúdo."""

    if not isinstance(valor, str) or not valor.strip():
        raise ValueError(f"{nome_campo} deve ser uma string não vazia.")


def _validar_timestamp_utc(
    valor: datetime | None, nome_campo: str = "timestamp_normalizado"
) -> None:
    """Valida INV-4 para um timestamp normalizado opcional."""

    if valor is None:
        return
    if not isinstance(valor, datetime):
        raise TypeError(f"{nome_campo} deve ser datetime ou None.")
    if valor.tzinfo is None or valor.utcoffset() is None:
        raise ValueError(f"{nome_campo} deve possuir timezone UTC.")
    if valor.utcoffset() != timedelta(0):
        raise ValueError(f"{nome_campo} deve estar normalizado em UTC.")


def _validar_intervalo_linhas(linha_inicial: int, linha_final: int) -> None:
    if linha_inicial < 1:
        raise ValueError("linha_inicial deve ser maior ou igual a 1.")
    if linha_final < linha_inicial:
        raise ValueError("linha_final não pode anteceder linha_inicial.")


@dataclass(frozen=True)
class Proveniencia:
    """Localização rastreável de um dado extraído."""

    arquivo_token: str
    entrada_id: str
    linha_inicial: int
    linha_final: int
    span_inicial: int | None = None
    span_final: int | None = None
    nome_campo: str | None = None
    regra_extracao: str | None = None

    def __post_init__(self) -> None:
        _exigir_texto_preenchido(self.arquivo_token, "arquivo_token")
        _exigir_texto_preenchido(self.entrada_id, "entrada_id")
        _validar_intervalo_linhas(self.linha_inicial, self.linha_final)

        if (self.span_inicial is None) != (self.span_final is None):
            raise ValueError(
                "span_inicial e span_final devem ser informados em conjunto."
            )
        if self.span_inicial is not None and self.span_final is not None:
            if self.span_inicial < 0:
                raise ValueError("span_inicial deve ser maior ou igual a zero.")
            if self.span_final < self.span_inicial:
                raise ValueError("span_final não pode anteceder span_inicial.")

        if self.nome_campo is not None:
            _exigir_texto_preenchido(self.nome_campo, "nome_campo")
        if self.regra_extracao is not None:
            _exigir_texto_preenchido(self.regra_extracao, "regra_extracao")


@dataclass(frozen=True)
class CampoEstruturado:
    """Campo reconhecido pelo parser sem alteração do valor de origem."""

    nome: str
    valor_original: str
    proveniencia: Proveniencia

    def __post_init__(self) -> None:
        _exigir_texto_preenchido(self.nome, "nome")
        _exigir_texto_preenchido(self.valor_original, "valor_original")
        if not isinstance(self.proveniencia, Proveniencia):
            raise TypeError("proveniencia deve ser Proveniencia.")


@dataclass(frozen=True)
class IdentificadorTecnico:
    """Identificador tipado, normalizado e auditável (INV-6)."""

    tipo: TipoIdentificador
    namespace_comparacao: str
    nome_campo: str
    valor_original: str
    valor_normalizado: str
    proveniencia: Proveniencia

    def __post_init__(self) -> None:
        if not isinstance(self.tipo, TipoIdentificador):
            raise TypeError("tipo deve ser TipoIdentificador.")
        _exigir_texto_preenchido(
            self.namespace_comparacao, "namespace_comparacao"
        )
        _exigir_texto_preenchido(self.nome_campo, "nome_campo")
        _exigir_texto_preenchido(self.valor_original, "valor_original")
        _exigir_texto_preenchido(self.valor_normalizado, "valor_normalizado")
        if not isinstance(self.proveniencia, Proveniencia):
            raise TypeError("proveniencia deve ser Proveniencia.")


@dataclass(frozen=True)
class FalhaDeEntrada:
    """Falha associada a uma entrada, descrita somente com detalhe seguro."""

    codigo: str
    proveniencia: Proveniencia
    detalhe_seguro: str

    def __post_init__(self) -> None:
        _exigir_texto_preenchido(self.codigo, "codigo")
        _exigir_texto_preenchido(self.detalhe_seguro, "detalhe_seguro")
        if not isinstance(self.proveniencia, Proveniencia):
            raise TypeError("proveniencia deve ser Proveniencia.")


@dataclass(frozen=True)
class VinculoIdentificadores:
    """Aresta explicitamente evidenciada entre dois identificadores (INV-7)."""

    origem: IdentificadorTecnico
    destino: IdentificadorTecnico
    tipo_relacao: str
    evidencia: Proveniencia
    esquema_id: str
    esquema_versao: int
    permite_correlacao: bool
    ambiguo: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.origem, IdentificadorTecnico):
            raise TypeError("origem deve ser IdentificadorTecnico.")
        if not isinstance(self.destino, IdentificadorTecnico):
            raise TypeError("destino deve ser IdentificadorTecnico.")
        _exigir_texto_preenchido(self.tipo_relacao, "tipo_relacao")
        if not isinstance(self.evidencia, Proveniencia):
            raise TypeError("evidencia deve ser Proveniencia.")
        _exigir_texto_preenchido(self.esquema_id, "esquema_id")
        if not isinstance(self.esquema_versao, int) or self.esquema_versao < 1:
            raise ValueError("esquema_versao deve ser um inteiro positivo.")


@dataclass(frozen=True)
class Evidencia:
    """Evidência rastreável destinada a uma representação sanitizada."""

    tipo: str
    aplicacao: str
    proveniencia: Proveniencia
    timestamp_original: str | None
    timestamp_normalizado: datetime | None
    campo_ou_condicao: str
    representacao_sanitizada: str

    def __post_init__(self) -> None:
        _exigir_texto_preenchido(self.tipo, "tipo")
        _exigir_texto_preenchido(self.aplicacao, "aplicacao")
        if not isinstance(self.proveniencia, Proveniencia):
            raise TypeError("proveniencia deve ser Proveniencia.")
        if self.timestamp_original is not None:
            _exigir_texto_preenchido(
                self.timestamp_original, "timestamp_original"
            )
        _validar_timestamp_utc(self.timestamp_normalizado)
        if self.timestamp_normalizado is not None and self.timestamp_original is None:
            raise ValueError(
                "timestamp_normalizado requer timestamp_original preservado."
            )
        _exigir_texto_preenchido(
            self.campo_ou_condicao, "campo_ou_condicao"
        )
        _exigir_texto_preenchido(
            self.representacao_sanitizada, "representacao_sanitizada"
        )


@dataclass(frozen=True)
class ReferenciaRegra:
    """Identidade versionada da regra que sustentou uma decisão."""

    rule_id: str
    versao: int
    catalogo_versao: str

    def __post_init__(self) -> None:
        _exigir_texto_preenchido(self.rule_id, "rule_id")
        if not isinstance(self.versao, int) or self.versao < 1:
            raise ValueError("versao deve ser um inteiro positivo.")
        _exigir_texto_preenchido(self.catalogo_versao, "catalogo_versao")


@dataclass(frozen=True)
class ResultadoCorrelacao:
    """Resultado evidenciado da correlação entre aplicações."""

    encontrada: bool
    base_primaria: BaseCorrelacao
    bases: tuple[BaseCorrelacao, ...] = ()
    evidencias: tuple[Evidencia, ...] = ()
    vinculos_percorridos: tuple[VinculoIdentificadores, ...] = ()
    motivo_seguro: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.base_primaria, BaseCorrelacao):
            raise TypeError("base_primaria deve ser BaseCorrelacao.")
        if not isinstance(self.bases, tuple) or not all(
            isinstance(base, BaseCorrelacao) for base in self.bases
        ):
            raise TypeError("bases deve ser uma tupla de BaseCorrelacao.")
        if len(set(self.bases)) != len(self.bases):
            raise ValueError("bases não pode conter valores duplicados.")
        if not isinstance(self.evidencias, tuple) or not all(
            isinstance(evidencia, Evidencia) for evidencia in self.evidencias
        ):
            raise TypeError("evidencias deve ser uma tupla de Evidencia.")
        if not isinstance(self.vinculos_percorridos, tuple) or not all(
            isinstance(vinculo, VinculoIdentificadores)
            for vinculo in self.vinculos_percorridos
        ):
            raise TypeError(
                "vinculos_percorridos deve ser uma tupla de VinculoIdentificadores."
            )
        if self.motivo_seguro is not None:
            _exigir_texto_preenchido(self.motivo_seguro, "motivo_seguro")

        bases_validas = {
            BaseCorrelacao.VALOR_COMPARTILHADO,
            BaseCorrelacao.CADEIA_DE_VINCULOS,
        }
        if self.encontrada:
            if self.base_primaria not in bases_validas:
                raise ValueError(
                    "correlação encontrada requer uma base primária válida."
                )
            if self.base_primaria not in self.bases:
                raise ValueError("base_primaria deve constar em bases.")
            if not self.evidencias:
                raise ValueError("correlação encontrada requer evidências.")
            if BaseCorrelacao.CADEIA_DE_VINCULOS in self.bases and not self.vinculos_percorridos:
                raise ValueError(
                    "correlação por cadeia requer vínculos percorridos."
                )
            if any(
                vinculo.ambiguo or not vinculo.permite_correlacao
                for vinculo in self.vinculos_percorridos
            ):
                raise ValueError(
                    "vínculo ambíguo ou não autorizado não sustenta correlação."
                )
        elif self.base_primaria in bases_validas:
            raise ValueError(
                "correlação não encontrada não pode declarar base primária válida."
            )


@dataclass(frozen=True)
class ResultadoCausaRaiz:
    """Causa-raiz fail-closed, determinada somente com regra referenciada."""

    estado: EstadoCausaRaiz = EstadoCausaRaiz.NAO_DETERMINADA
    descricao_sanitizada: str = "não determinada"
    regra: ReferenciaRegra | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.estado, EstadoCausaRaiz):
            raise TypeError("estado deve ser EstadoCausaRaiz.")
        _exigir_texto_preenchido(
            self.descricao_sanitizada, "descricao_sanitizada"
        )
        if self.regra is not None and not isinstance(self.regra, ReferenciaRegra):
            raise TypeError("regra deve ser ReferenciaRegra ou None.")
        if self.estado is EstadoCausaRaiz.DETERMINADA:
            if self.regra is None:
                raise ValueError(
                    "causa-raiz determinada requer referência de regra."
                )
            if self.descricao_sanitizada == "não determinada":
                raise ValueError(
                    "causa-raiz determinada requer descrição sanitizada."
                )


@dataclass(frozen=True)
class ReferenciaTextoOriginal:
    """Referência lossless ao intervalo de origem de uma entrada indexada."""

    arquivo_token: str
    inicio_byte: int
    fim_byte: int
    linha_inicial: int
    linha_final: int
    sha256: str

    def __post_init__(self) -> None:
        _exigir_texto_preenchido(self.arquivo_token, "arquivo_token")
        if self.inicio_byte < 0:
            raise ValueError("inicio_byte deve ser maior ou igual a zero.")
        if self.fim_byte < self.inicio_byte:
            raise ValueError("fim_byte não pode anteceder inicio_byte.")
        _validar_intervalo_linhas(self.linha_inicial, self.linha_final)
        _exigir_texto_preenchido(self.sha256, "sha256")


def _validar_proveniencia_no_intervalo(
    proveniencia: Proveniencia,
    *,
    entrada_id: str,
    texto_ref: ReferenciaTextoOriginal,
) -> None:
    """Confere que um metadado indexado aponta para a própria entrada."""

    if proveniencia.entrada_id != entrada_id:
        raise ValueError("proveniência referencia entrada_id diferente.")
    if proveniencia.arquivo_token != texto_ref.arquivo_token:
        raise ValueError("proveniência referencia arquivo_token diferente.")
    if (
        proveniencia.linha_inicial < texto_ref.linha_inicial
        or proveniencia.linha_final > texto_ref.linha_final
    ):
        raise ValueError("proveniência está fora do intervalo da entrada.")


@dataclass(frozen=True)
class EntradaIndexada:
    """Metadados leves de uma entrada cujo texto ainda não foi materializado."""

    entrada_id: str
    aplicacao: str
    ordem_de_leitura: int
    texto_ref: ReferenciaTextoOriginal
    cabecalho: tuple[CampoEstruturado, ...]
    identificadores_digest: tuple[str, ...]
    timestamp_original: str | None
    timestamp_normalizado: datetime | None
    falhas: tuple[FalhaDeEntrada, ...]
    interpretada: bool

    def __post_init__(self) -> None:
        _exigir_texto_preenchido(self.entrada_id, "entrada_id")
        _exigir_texto_preenchido(self.aplicacao, "aplicacao")
        if not isinstance(self.ordem_de_leitura, int) or self.ordem_de_leitura < 0:
            raise ValueError("ordem_de_leitura deve ser um inteiro não negativo.")
        if not isinstance(self.texto_ref, ReferenciaTextoOriginal):
            raise TypeError("texto_ref deve ser ReferenciaTextoOriginal.")
        if not isinstance(self.cabecalho, tuple) or not all(
            isinstance(campo, CampoEstruturado) for campo in self.cabecalho
        ):
            raise TypeError("cabecalho deve ser uma tupla de CampoEstruturado.")
        if not isinstance(self.identificadores_digest, tuple) or not all(
            isinstance(digest, str) and bool(digest.strip())
            for digest in self.identificadores_digest
        ):
            raise TypeError(
                "identificadores_digest deve ser uma tupla de strings não vazias."
            )
        if self.timestamp_original is not None:
            _exigir_texto_preenchido(
                self.timestamp_original, "timestamp_original"
            )
        _validar_timestamp_utc(self.timestamp_normalizado)
        if self.timestamp_normalizado is not None and self.timestamp_original is None:
            raise ValueError(
                "timestamp_normalizado requer timestamp_original preservado."
            )
        if not isinstance(self.falhas, tuple) or not all(
            isinstance(falha, FalhaDeEntrada) for falha in self.falhas
        ):
            raise TypeError("falhas deve ser uma tupla de FalhaDeEntrada.")

        for campo in self.cabecalho:
            _validar_proveniencia_no_intervalo(
                campo.proveniencia,
                entrada_id=self.entrada_id,
                texto_ref=self.texto_ref,
            )
        for falha in self.falhas:
            _validar_proveniencia_no_intervalo(
                falha.proveniencia,
                entrada_id=self.entrada_id,
                texto_ref=self.texto_ref,
            )


@dataclass(frozen=True)
class EntradaDeLog:
    """Representação imutável de uma entrada de log materializada."""

    # Campos da Fase 1: ordem, nomes, tipos e semântica preservados.
    texto_original: str
    aplicacao: str
    ordem_de_leitura: int
    interpretada: bool
    carimbo_de_tempo: datetime | None = None
    nivel_de_severidade: str | None = None
    mensagem: str | None = None
    categoria: Categoria = Categoria.NAO_CLASSIFICADA
    correlacionada: bool = False

    # Campos aditivos da Fase 2.
    entrada_id: str | None = None
    arquivo_origem: str | None = None
    arquivo_token: str | None = None
    posicao_inicial: int | None = None
    posicao_final: int | None = None
    timestamp_original: str | None = None
    timestamp_normalizado: datetime | None = None
    precisao_fracionaria: int | None = None
    origem_evento: str | None = None
    formato_origem: str | None = None
    campos_estruturados: tuple[CampoEstruturado, ...] = ()
    identificadores: tuple[IdentificadorTecnico, ...] = ()
    falhas: tuple[FalhaDeEntrada, ...] = ()
    representacao_sanitizada: str | None = None

    def __post_init__(self) -> None:
        """Valida invariantes sem exigir metadados da Fase 2 de legados."""

        # INV-1 preservado exatamente para entradas interpretadas.
        if self.interpretada:
            if self.carimbo_de_tempo is None:
                raise ValueError(
                    "EntradaDeLog interpretada requer carimbo_de_tempo não nulo."
                )
            if not self.nivel_de_severidade:
                raise ValueError(
                    "EntradaDeLog interpretada requer nivel_de_severidade não nulo/não vazio."
                )
            if not self.mensagem:
                raise ValueError(
                    "EntradaDeLog interpretada requer mensagem não nula/não vazia."
                )

        if self.entrada_id is not None:
            _exigir_texto_preenchido(self.entrada_id, "entrada_id")
        if self.arquivo_origem is not None:
            _exigir_texto_preenchido(self.arquivo_origem, "arquivo_origem")
        if self.arquivo_token is not None:
            _exigir_texto_preenchido(self.arquivo_token, "arquivo_token")

        if (self.posicao_inicial is None) != (self.posicao_final is None):
            raise ValueError(
                "posicao_inicial e posicao_final devem ser informadas em conjunto."
            )
        if self.posicao_inicial is not None and self.posicao_final is not None:
            _validar_intervalo_linhas(
                self.posicao_inicial, self.posicao_final
            )

        if self.timestamp_original is not None:
            _exigir_texto_preenchido(
                self.timestamp_original, "timestamp_original"
            )
        _validar_timestamp_utc(self.timestamp_normalizado)
        if self.timestamp_normalizado is not None and self.timestamp_original is None:
            raise ValueError(
                "timestamp_normalizado requer timestamp_original preservado."
            )
        if self.precisao_fracionaria is not None:
            if (
                not isinstance(self.precisao_fracionaria, int)
                or not 0 <= self.precisao_fracionaria <= 6
            ):
                raise ValueError(
                    "precisao_fracionaria deve estar entre 0 e 6."
                )
            if self.timestamp_original is None:
                raise ValueError(
                    "precisao_fracionaria requer timestamp_original preservado."
                )

        if self.origem_evento is not None:
            _exigir_texto_preenchido(self.origem_evento, "origem_evento")
        if self.formato_origem is not None:
            _exigir_texto_preenchido(self.formato_origem, "formato_origem")
        if self.representacao_sanitizada is not None:
            _exigir_texto_preenchido(
                self.representacao_sanitizada, "representacao_sanitizada"
            )

        if not isinstance(self.campos_estruturados, tuple) or not all(
            isinstance(campo, CampoEstruturado)
            for campo in self.campos_estruturados
        ):
            raise TypeError(
                "campos_estruturados deve ser uma tupla de CampoEstruturado."
            )
        if not isinstance(self.identificadores, tuple) or not all(
            isinstance(identificador, IdentificadorTecnico)
            for identificador in self.identificadores
        ):
            raise TypeError(
                "identificadores deve ser uma tupla de IdentificadorTecnico."
            )
        if not isinstance(self.falhas, tuple) or not all(
            isinstance(falha, FalhaDeEntrada) for falha in self.falhas
        ):
            raise TypeError("falhas deve ser uma tupla de FalhaDeEntrada.")

        proveniencias = [
            campo.proveniencia for campo in self.campos_estruturados
        ]
        proveniencias.extend(
            identificador.proveniencia for identificador in self.identificadores
        )
        proveniencias.extend(falha.proveniencia for falha in self.falhas)
        for proveniencia in proveniencias:
            if (
                self.entrada_id is not None
                and proveniencia.entrada_id != self.entrada_id
            ):
                raise ValueError(
                    "metadado referencia entrada_id diferente da entrada."
                )
            if (
                self.arquivo_token is not None
                and proveniencia.arquivo_token != self.arquivo_token
            ):
                raise ValueError(
                    "metadado referencia arquivo_token diferente da entrada."
                )
            if (
                self.posicao_inicial is not None
                and self.posicao_final is not None
                and (
                    proveniencia.linha_inicial < self.posicao_inicial
                    or proveniencia.linha_final > self.posicao_final
                )
            ):
                raise ValueError(
                    "metadado possui proveniência fora do intervalo da entrada."
                )


@dataclass
class ArquivoSelecionado:
    """Associação de um arquivo de log à sua aplicação."""

    caminho: str
    app_id: str | None


@dataclass
class MensagemDeErro:
    """Mensagem de erro identificando o arquivo ou aplicação afetado."""

    arquivo_ou_app: str
    descricao: str


def _entrada_tem_metadados_fase2(entrada: EntradaDeLog) -> bool:
    return any(
        (
            entrada.entrada_id is not None,
            entrada.arquivo_origem is not None,
            entrada.arquivo_token is not None,
            entrada.posicao_inicial is not None,
            entrada.posicao_final is not None,
            entrada.timestamp_original is not None,
            entrada.timestamp_normalizado is not None,
            entrada.precisao_fracionaria is not None,
            entrada.origem_evento is not None,
            entrada.formato_origem is not None,
            bool(entrada.campos_estruturados),
            bool(entrada.identificadores),
            bool(entrada.falhas),
            entrada.representacao_sanitizada is not None,
        )
    )


def _chave_particao(entrada: EntradaDeLog) -> tuple[str, object]:
    if entrada.entrada_id is not None:
        return ("entrada_id", entrada.entrada_id)
    return ("objeto_legado", id(entrada))


@dataclass
class ResultadoDeAnalise:
    """Saída estruturada da análise com extensão aditiva da Fase 2."""

    # Campos da Fase 1 preservados.
    identificador: str
    entradas_por_aplicacao: dict[str, list[EntradaDeLog]] = field(
        default_factory=dict
    )
    linha_do_tempo: list[EntradaDeLog] = field(default_factory=list)
    contagem_por_categoria: dict[Categoria, int] = field(default_factory=dict)
    contagem_por_aplicacao: dict[str, int] = field(default_factory=dict)
    correlacao_encontrada: bool = False
    erros: list[MensagemDeErro] = field(default_factory=list)
    mensagens: list[str] = field(default_factory=list)

    # Campos aditivos da Fase 2.
    categoria_de_cenario: Categoria = Categoria.NAO_CLASSIFICADA
    entradas_sem_ordenacao_temporal: list[EntradaDeLog] = field(
        default_factory=list
    )
    identificadores_extraidos: list[IdentificadorTecnico] = field(
        default_factory=list
    )
    vinculos: list[VinculoIdentificadores] = field(default_factory=list)
    correlacao: ResultadoCorrelacao | None = None
    evidencias: list[Evidencia] = field(default_factory=list)
    regra_aplicada: ReferenciaRegra | None = None
    versao_catalogo: str = "sem-catalogo-ativo"
    estado_sanitizacao: EstadoSanitizacao = EstadoSanitizacao.INTERNA_BRUTA
    causa_raiz: ResultadoCausaRaiz = field(default_factory=ResultadoCausaRaiz)
    aplicacoes_analisadas: list[str] = field(default_factory=list)
    aplicacoes_ausentes_ou_invalidas: list[str] = field(default_factory=list)
    cobertura_rotulada: str = "1 cenário de sucesso; 0 cenários de erro"

    def __post_init__(self) -> None:
        """Valida a consistência estrutural disponível no resultado."""

        if not isinstance(self.categoria_de_cenario, Categoria):
            raise TypeError("categoria_de_cenario deve ser Categoria.")
        if self.correlacao is not None and not isinstance(
            self.correlacao, ResultadoCorrelacao
        ):
            raise TypeError("correlacao deve ser ResultadoCorrelacao ou None.")
        if self.regra_aplicada is not None and not isinstance(
            self.regra_aplicada, ReferenciaRegra
        ):
            raise TypeError("regra_aplicada deve ser ReferenciaRegra ou None.")
        if not isinstance(self.estado_sanitizacao, EstadoSanitizacao):
            raise TypeError("estado_sanitizacao deve ser EstadoSanitizacao.")
        if not isinstance(self.causa_raiz, ResultadoCausaRaiz):
            raise TypeError("causa_raiz deve ser ResultadoCausaRaiz.")
        _exigir_texto_preenchido(self.versao_catalogo, "versao_catalogo")
        _exigir_texto_preenchido(
            self.cobertura_rotulada, "cobertura_rotulada"
        )

        if not all(
            isinstance(item, IdentificadorTecnico)
            for item in self.identificadores_extraidos
        ):
            raise TypeError(
                "identificadores_extraidos deve conter IdentificadorTecnico."
            )
        if not all(
            isinstance(item, VinculoIdentificadores) for item in self.vinculos
        ):
            raise TypeError("vinculos deve conter VinculoIdentificadores.")
        if not all(isinstance(item, Evidencia) for item in self.evidencias):
            raise TypeError("evidencias deve conter Evidencia.")

        if self.correlacao is not None:
            if self.correlacao_encontrada != self.correlacao.encontrada:
                raise ValueError(
                    "correlacao_encontrada diverge do resultado de correlação."
                )

        # INV-9: a parte representável no resultado exige regra/versionamento e
        # evidências. A ativação e as condições completas pertencem ao catálogo.
        if self.categoria_de_cenario is not Categoria.NAO_CLASSIFICADA:
            if self.regra_aplicada is None:
                raise ValueError(
                    "categoria de cenário classificada requer regra_aplicada."
                )
            if not self.evidencias:
                raise ValueError(
                    "categoria de cenário classificada requer evidências."
                )
            if self.versao_catalogo != self.regra_aplicada.catalogo_versao:
                raise ValueError(
                    "versao_catalogo deve corresponder à regra_aplicada."
                )
            if (
                self.correlacao is not None
                and self.correlacao.base_primaria is BaseCorrelacao.AMBIGUA
            ):
                raise ValueError(
                    "correlação ambígua não pode sustentar classificação."
                )

        entradas_selecionadas = [
            entrada
            for entradas in self.entradas_por_aplicacao.values()
            for entrada in entradas
        ]
        entradas_particionadas = [
            *self.linha_do_tempo,
            *self.entradas_sem_ordenacao_temporal,
        ]
        usa_particao_fase2 = any(
            _entrada_tem_metadados_fase2(entrada)
            for entrada in entradas_selecionadas + entradas_particionadas
        ) or any(
            (
                bool(self.entradas_sem_ordenacao_temporal),
                bool(self.identificadores_extraidos),
                bool(self.vinculos),
                self.correlacao is not None,
                bool(self.evidencias),
                self.regra_aplicada is not None,
                self.categoria_de_cenario is not Categoria.NAO_CLASSIFICADA,
            )
        )

        if usa_particao_fase2:
            # INV-5 e INV-12, sem alterar resultados puramente legados.
            if any(
                entrada.timestamp_normalizado is None
                for entrada in self.linha_do_tempo
            ):
                raise ValueError(
                    "linha_do_tempo da Fase 2 aceita somente timestamps UTC."
                )
            if any(
                entrada.timestamp_normalizado is not None
                for entrada in self.entradas_sem_ordenacao_temporal
            ):
                raise ValueError(
                    "entrada com timestamp UTC deve pertencer à linha_do_tempo."
                )

            chaves_selecionadas = [
                _chave_particao(entrada) for entrada in entradas_selecionadas
            ]
            chaves_timeline = [
                _chave_particao(entrada) for entrada in self.linha_do_tempo
            ]
            chaves_sem_tempo = [
                _chave_particao(entrada)
                for entrada in self.entradas_sem_ordenacao_temporal
            ]
            if set(chaves_timeline) & set(chaves_sem_tempo):
                raise ValueError(
                    "as coleções temporais devem formar uma união disjunta."
                )
            if len(set(chaves_selecionadas)) != len(chaves_selecionadas):
                raise ValueError(
                    "cada entrada selecionada deve possuir identidade única."
                )
            if Counter(chaves_selecionadas) != Counter(
                chaves_timeline + chaves_sem_tempo
            ):
                raise ValueError(
                    "a partição temporal deve conter exatamente as entradas selecionadas."
                )

        # INV-11 possui validação estrutural aqui; a detecção de conteúdo
        # sensível é responsabilidade do scanner fail-closed da tarefa própria.
        if self.estado_sanitizacao is EstadoSanitizacao.CONCLUIDA:
            for entrada in entradas_particionadas:
                if entrada.arquivo_origem is not None:
                    raise ValueError(
                        "visão sanitizada não pode expor arquivo_origem interno."
                    )
                if (
                    _entrada_tem_metadados_fase2(entrada)
                    and entrada.representacao_sanitizada is None
                ):
                    raise ValueError(
                        "visão sanitizada requer representação sanitizada das entradas."
                    )
