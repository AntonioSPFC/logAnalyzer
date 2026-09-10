"""Composição rastreável e fail-closed de evidências da Fase 2.

O módulo não sanitiza conteúdo e nunca deriva uma representação de
``texto_original`` ou ``mensagem``. A representação recebida pelos builders é
somente destinada à etapa de sanitização; ela não deve atravessar uma fronteira
de saída antes de o sanitizador marcar a visão como concluída.

Severidade de log, categoria por entrada, categoria de cenário e causa-raiz são
mantidas em campos distintos. Ausência de regra produz mensagens canônicas,
sem incorporar texto de origem nem formular hipótese causal.

Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 17.4.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import Enum
from typing import TypeVar

from log_analyzer.core.modelos import (
    CampoEstruturado,
    Categoria,
    EntradaDeLog,
    EstadoCausaRaiz,
    Evidencia,
    IdentificadorTecnico,
    Proveniencia,
    ReferenciaRegra,
    ResultadoCausaRaiz,
    VinculoIdentificadores,
)


MENSAGEM_SEM_REGRA_CORRESPONDENTE = (
    "Nenhuma Regra_Validada correspondeu integralmente ao cenário."
)
MENSAGEM_CAUSA_RAIZ_NAO_DETERMINADA = (
    'Causa_Raiz "não determinada": nenhuma Regra_Validada causal aplicável '
    "foi fornecida e nenhuma hipótese causal foi produzida."
)

_T = TypeVar("_T")


class CodigoMensagemExplicabilidade(Enum):
    """Códigos estáveis para lacunas explicáveis, sem dados de origem."""

    NENHUMA_REGRA_VALIDADA_CORRESPONDEU = (
        "nenhuma_regra_validada_correspondeu"
    )
    CAUSA_RAIZ_NAO_DETERMINADA = "causa_raiz_nao_determinada"


@dataclass(frozen=True)
class MensagemExplicabilidade:
    """Mensagem estruturada e canônica sobre uma conclusão não disponível."""

    codigo: CodigoMensagemExplicabilidade
    descricao_segura: str
    categoria_de_cenario: Categoria
    estado_causa_raiz: EstadoCausaRaiz
    hipotese_causal: None = None

    def __post_init__(self) -> None:
        if not isinstance(self.codigo, CodigoMensagemExplicabilidade):
            raise TypeError(
                "codigo deve ser CodigoMensagemExplicabilidade."
            )
        if not isinstance(self.categoria_de_cenario, Categoria):
            raise TypeError("categoria_de_cenario deve ser Categoria.")
        if not isinstance(self.estado_causa_raiz, EstadoCausaRaiz):
            raise TypeError("estado_causa_raiz deve ser EstadoCausaRaiz.")
        if self.hipotese_causal is not None:
            raise ValueError(
                "mensagem de ausência não pode conter hipótese causal."
            )

        descricoes = {
            CodigoMensagemExplicabilidade.NENHUMA_REGRA_VALIDADA_CORRESPONDEU: (
                MENSAGEM_SEM_REGRA_CORRESPONDENTE
            ),
            CodigoMensagemExplicabilidade.CAUSA_RAIZ_NAO_DETERMINADA: (
                MENSAGEM_CAUSA_RAIZ_NAO_DETERMINADA
            ),
        }
        if self.descricao_segura != descricoes[self.codigo]:
            raise ValueError(
                "descricao_segura deve usar a mensagem canônica do código."
            )
        if (
            self.codigo
            is CodigoMensagemExplicabilidade.NENHUMA_REGRA_VALIDADA_CORRESPONDEU
            and self.categoria_de_cenario is not Categoria.NAO_CLASSIFICADA
        ):
            raise ValueError(
                "mensagem de não correspondência requer cenário não classificado."
            )
        if (
            self.codigo
            is CodigoMensagemExplicabilidade.CAUSA_RAIZ_NAO_DETERMINADA
            and self.estado_causa_raiz
            is not EstadoCausaRaiz.NAO_DETERMINADA
        ):
            raise ValueError(
                "mensagem de causa não determinada requer o estado correspondente."
            )


@dataclass(frozen=True)
class AspectosDaEntrada:
    """Dimensões próprias de uma entrada, sem categoria ou causa de cenário."""

    aplicacao: str
    entrada_id: str | None
    posicao_inicial: int | None
    posicao_final: int | None
    severidade_de_log: str | None
    categoria_da_entrada: Categoria

    def __post_init__(self) -> None:
        _exigir_texto(self.aplicacao, "aplicacao")
        if self.entrada_id is not None:
            _exigir_texto(self.entrada_id, "entrada_id")
        if (self.posicao_inicial is None) != (self.posicao_final is None):
            raise ValueError(
                "posicao_inicial e posicao_final devem ser informadas em conjunto."
            )
        if self.posicao_inicial is not None and self.posicao_final is not None:
            if self.posicao_inicial < 1:
                raise ValueError(
                    "posicao_inicial deve ser maior ou igual a 1."
                )
            if self.posicao_final < self.posicao_inicial:
                raise ValueError(
                    "posicao_final não pode anteceder posicao_inicial."
                )
        if self.severidade_de_log is not None:
            _exigir_texto(self.severidade_de_log, "severidade_de_log")
        if not isinstance(self.categoria_da_entrada, Categoria):
            raise TypeError("categoria_da_entrada deve ser Categoria.")


@dataclass(frozen=True)
class DimensoesDaAnalise:
    """Separa aspectos por entrada de categoria e causa-raiz do cenário."""

    entradas: tuple[AspectosDaEntrada, ...]
    categoria_de_cenario: Categoria
    causa_raiz: ResultadoCausaRaiz

    def __post_init__(self) -> None:
        if not isinstance(self.entradas, tuple) or not all(
            isinstance(item, AspectosDaEntrada) for item in self.entradas
        ):
            raise TypeError(
                "entradas deve ser uma tupla de AspectosDaEntrada."
            )
        if not isinstance(self.categoria_de_cenario, Categoria):
            raise TypeError("categoria_de_cenario deve ser Categoria.")
        if not isinstance(self.causa_raiz, ResultadoCausaRaiz):
            raise TypeError("causa_raiz deve ser ResultadoCausaRaiz.")
        _validar_causa_raiz(self.causa_raiz)


@dataclass(frozen=True)
class ExplicacaoRastreavel:
    """Explicação estrutural vinculada à regra, condições e evidências."""

    categoria_de_cenario: Categoria
    regra_aplicada: ReferenciaRegra | None
    condicoes_satisfeitas: tuple[str, ...]
    evidencias: tuple[Evidencia, ...]
    vinculos_percorridos: tuple[VinculoIdentificadores, ...]
    dimensoes: DimensoesDaAnalise
    mensagens: tuple[MensagemExplicabilidade, ...]

    @property
    def causa_raiz(self) -> ResultadoCausaRaiz:
        """Expõe a causa-raiz sem fundi-la à categoria de cenário."""

        return self.dimensoes.causa_raiz

    def __post_init__(self) -> None:
        if not isinstance(self.categoria_de_cenario, Categoria):
            raise TypeError("categoria_de_cenario deve ser Categoria.")
        if self.regra_aplicada is not None and not isinstance(
            self.regra_aplicada, ReferenciaRegra
        ):
            raise TypeError("regra_aplicada deve ser ReferenciaRegra ou None.")
        if not isinstance(self.condicoes_satisfeitas, tuple) or not all(
            isinstance(condicao, str) and condicao.strip()
            for condicao in self.condicoes_satisfeitas
        ):
            raise TypeError(
                "condicoes_satisfeitas deve ser uma tupla de strings não vazias."
            )
        if len(set(self.condicoes_satisfeitas)) != len(
            self.condicoes_satisfeitas
        ):
            raise ValueError(
                "condicoes_satisfeitas não pode conter duplicatas."
            )
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
        if not isinstance(self.dimensoes, DimensoesDaAnalise):
            raise TypeError("dimensoes deve ser DimensoesDaAnalise.")
        if self.dimensoes.categoria_de_cenario is not self.categoria_de_cenario:
            raise ValueError(
                "dimensoes e explicação devem usar a mesma categoria de cenário."
            )
        if not isinstance(self.mensagens, tuple) or not all(
            isinstance(mensagem, MensagemExplicabilidade)
            for mensagem in self.mensagens
        ):
            raise TypeError(
                "mensagens deve ser uma tupla de MensagemExplicabilidade."
            )

        for evidencia in self.evidencias:
            if evidencia.proveniencia.regra_extracao is None:
                raise ValueError(
                    "toda evidência explicável deve registrar regra de extração ou vínculo."
                )

        classificada = (
            self.categoria_de_cenario is not Categoria.NAO_CLASSIFICADA
        )
        if classificada:
            if self.regra_aplicada is None:
                raise ValueError(
                    "categoria de cenário classificada requer regra aplicada."
                )
            if not self.condicoes_satisfeitas:
                raise ValueError(
                    "categoria de cenário classificada requer condições satisfeitas."
                )
            if not self.evidencias:
                raise ValueError(
                    "categoria de cenário classificada requer evidências."
                )
            condicoes_evidenciadas = {
                evidencia.campo_ou_condicao for evidencia in self.evidencias
            }
            ausentes = set(self.condicoes_satisfeitas) - condicoes_evidenciadas
            if ausentes:
                raise ValueError(
                    "cada condição satisfeita deve possuir evidência correspondente."
                )
        else:
            if self.regra_aplicada is not None:
                raise ValueError(
                    "cenário não classificado não pode declarar regra aplicada."
                )
            if self.condicoes_satisfeitas:
                raise ValueError(
                    "cenário não classificado não pode declarar condições de regra aplicada."
                )

        for vinculo in self.vinculos_percorridos:
            if not any(
                _evidencia_documenta_vinculo(evidencia, vinculo)
                for evidencia in self.evidencias
            ):
                raise ValueError(
                    "cada vínculo percorrido deve possuir sua evidência de entrada."
                )

        codigos = tuple(mensagem.codigo for mensagem in self.mensagens)
        if len(set(codigos)) != len(codigos):
            raise ValueError("mensagens não pode repetir o mesmo código.")
        esperados: set[CodigoMensagemExplicabilidade] = set()
        if not classificada:
            esperados.add(
                CodigoMensagemExplicabilidade.NENHUMA_REGRA_VALIDADA_CORRESPONDEU
            )
        if self.causa_raiz.estado is EstadoCausaRaiz.NAO_DETERMINADA:
            esperados.add(
                CodigoMensagemExplicabilidade.CAUSA_RAIZ_NAO_DETERMINADA
            )
        if set(codigos) != esperados:
            raise ValueError(
                "mensagens deve representar exatamente as lacunas da explicação."
            )


class CompositorDeExplicabilidade:
    """Constrói evidências e explicações sem inferir classificação ou causa."""

    def construir_evidencia_de_entrada(
        self,
        entrada: EntradaDeLog,
        campo_ou_condicao: str,
        representacao_destinada_a_sanitizacao: str,
        *,
        tipo: str = "entrada",
        proveniencia: Proveniencia | None = None,
        regra_extracao_ou_vinculo: str | None = None,
        nome_campo: str | None = None,
    ) -> Evidencia:
        """Constrói evidência sem copiar automaticamente conteúdo bruto.

        A regra é obtida da ``proveniencia`` ou informada explicitamente. Se
        ambas forem fornecidas, devem ser iguais. Entradas sem ID, token ou
        posição da Fase 2 são rejeitadas em vez de receber localização inventada.
        """

        _validar_entrada_rastreavel(entrada)
        _exigir_texto(campo_ou_condicao, "campo_ou_condicao")
        _exigir_texto(
            representacao_destinada_a_sanitizacao,
            "representacao_destinada_a_sanitizacao",
        )
        _exigir_texto(tipo, "tipo")
        if nome_campo is not None:
            _exigir_texto(nome_campo, "nome_campo")
        if regra_extracao_ou_vinculo is not None:
            _exigir_texto(
                regra_extracao_ou_vinculo,
                "regra_extracao_ou_vinculo",
            )

        if proveniencia is None:
            if regra_extracao_ou_vinculo is None:
                raise ValueError(
                    "evidência requer regra de extração ou vínculo rastreável."
                )
            proveniencia_final = Proveniencia(
                arquivo_token=entrada.arquivo_token,  # type: ignore[arg-type]
                entrada_id=entrada.entrada_id,  # type: ignore[arg-type]
                linha_inicial=entrada.posicao_inicial,  # type: ignore[arg-type]
                linha_final=entrada.posicao_final,  # type: ignore[arg-type]
                nome_campo=nome_campo,
                regra_extracao=regra_extracao_ou_vinculo,
            )
        else:
            if not isinstance(proveniencia, Proveniencia):
                raise TypeError("proveniencia deve ser Proveniencia ou None.")
            _validar_proveniencia_da_entrada(proveniencia, entrada)
            proveniencia_final = proveniencia
            if nome_campo is not None:
                if (
                    proveniencia_final.nome_campo is not None
                    and proveniencia_final.nome_campo != nome_campo
                ):
                    raise ValueError(
                        "nome_campo diverge da proveniência fornecida."
                    )
                if proveniencia_final.nome_campo is None:
                    proveniencia_final = replace(
                        proveniencia_final, nome_campo=nome_campo
                    )

            regra_existente = proveniencia_final.regra_extracao
            if (
                regra_existente is not None
                and regra_extracao_ou_vinculo is not None
                and regra_existente != regra_extracao_ou_vinculo
            ):
                raise ValueError(
                    "regra informada diverge da proveniência fornecida."
                )
            regra_final = regra_existente or regra_extracao_ou_vinculo
            if regra_final is None:
                raise ValueError(
                    "evidência requer regra de extração ou vínculo rastreável."
                )
            if proveniencia_final.regra_extracao is None:
                proveniencia_final = replace(
                    proveniencia_final, regra_extracao=regra_final
                )

        return Evidencia(
            tipo=tipo,
            aplicacao=entrada.aplicacao,
            proveniencia=proveniencia_final,
            timestamp_original=entrada.timestamp_original,
            timestamp_normalizado=entrada.timestamp_normalizado,
            campo_ou_condicao=campo_ou_condicao,
            # O nome do campo pertence ao modelo existente. Neste estágio o
            # valor ainda é apenas destinado à sanitização.
            representacao_sanitizada=(
                representacao_destinada_a_sanitizacao
            ),
        )

    def construir_evidencia_de_campo(
        self,
        entrada: EntradaDeLog,
        campo: CampoEstruturado | IdentificadorTecnico,
        campo_ou_condicao: str,
        representacao_destinada_a_sanitizacao: str,
        *,
        tipo: str | None = None,
    ) -> Evidencia:
        """Usa a proveniência já registrada por um campo ou identificador."""

        if isinstance(campo, CampoEstruturado):
            tipo_final = tipo or "campo_estruturado"
            nome_campo = campo.nome
        elif isinstance(campo, IdentificadorTecnico):
            tipo_final = tipo or "identificador_tecnico"
            nome_campo = campo.nome_campo
        else:
            raise TypeError(
                "campo deve ser CampoEstruturado ou IdentificadorTecnico."
            )
        return self.construir_evidencia_de_entrada(
            entrada,
            campo_ou_condicao,
            representacao_destinada_a_sanitizacao,
            tipo=tipo_final,
            proveniencia=campo.proveniencia,
            nome_campo=nome_campo,
        )

    def construir_evidencia_de_vinculo(
        self,
        entrada: EntradaDeLog,
        vinculo: VinculoIdentificadores,
        representacao_destinada_a_sanitizacao: str,
        *,
        campo_ou_condicao: str | None = None,
    ) -> Evidencia:
        """Constrói evidência para uma aresta usando seu esquema versionado."""

        if not isinstance(vinculo, VinculoIdentificadores):
            raise TypeError("vinculo deve ser VinculoIdentificadores.")
        _validar_entrada_rastreavel(entrada)
        _validar_proveniencia_da_entrada(vinculo.evidencia, entrada)
        proveniencia = replace(
            vinculo.evidencia,
            regra_extracao=referencia_regra_de_vinculo(vinculo),
        )
        return self.construir_evidencia_de_entrada(
            entrada,
            campo_ou_condicao or vinculo.tipo_relacao,
            representacao_destinada_a_sanitizacao,
            tipo="vinculo",
            proveniencia=proveniencia,
        )

    def compor(
        self,
        entradas: Iterable[EntradaDeLog],
        categoria_de_cenario: Categoria,
        *,
        regra_aplicada: ReferenciaRegra | None = None,
        condicoes_satisfeitas: Iterable[str] = (),
        evidencias: Iterable[Evidencia] = (),
        vinculos_percorridos: Iterable[VinculoIdentificadores] = (),
        causa_raiz: ResultadoCausaRaiz | None = None,
    ) -> ExplicacaoRastreavel:
        """Compõe a visão explicável sem inferir decisões ausentes.

        O chamador fornece a decisão já validada. Este método apenas verifica a
        rastreabilidade e cria mensagens canônicas para lacunas. Em particular,
        severidade e categoria da entrada são copiadas sem afetar a categoria
        do cenário.
        """

        if not isinstance(categoria_de_cenario, Categoria):
            raise TypeError("categoria_de_cenario deve ser Categoria.")
        entradas_finais = _materializar_tupla(
            entradas, EntradaDeLog, "entradas"
        )
        condicoes_finais = tuple(condicoes_satisfeitas)
        evidencias_finais = _tupla_sem_duplicatas(
            _materializar_tupla(evidencias, Evidencia, "evidencias")
        )
        vinculos_finais = _tupla_sem_duplicatas(
            _materializar_tupla(
                vinculos_percorridos,
                VinculoIdentificadores,
                "vinculos_percorridos",
            )
        )
        causa_final = causa_raiz or ResultadoCausaRaiz()
        if not isinstance(causa_final, ResultadoCausaRaiz):
            raise TypeError("causa_raiz deve ser ResultadoCausaRaiz ou None.")
        _validar_causa_raiz(causa_final)

        aspectos = tuple(
            AspectosDaEntrada(
                aplicacao=entrada.aplicacao,
                entrada_id=entrada.entrada_id,
                posicao_inicial=entrada.posicao_inicial,
                posicao_final=entrada.posicao_final,
                severidade_de_log=entrada.nivel_de_severidade,
                categoria_da_entrada=entrada.categoria,
            )
            for entrada in entradas_finais
        )
        dimensoes = DimensoesDaAnalise(
            entradas=aspectos,
            categoria_de_cenario=categoria_de_cenario,
            causa_raiz=causa_final,
        )

        mensagens: list[MensagemExplicabilidade] = []
        if categoria_de_cenario is Categoria.NAO_CLASSIFICADA:
            mensagens.append(
                mensagem_sem_regra_correspondente(causa_final.estado)
            )
        if causa_final.estado is EstadoCausaRaiz.NAO_DETERMINADA:
            mensagens.append(
                mensagem_causa_raiz_nao_determinada(
                    categoria_de_cenario
                )
            )

        return ExplicacaoRastreavel(
            categoria_de_cenario=categoria_de_cenario,
            regra_aplicada=regra_aplicada,
            condicoes_satisfeitas=condicoes_finais,
            evidencias=evidencias_finais,
            vinculos_percorridos=vinculos_finais,
            dimensoes=dimensoes,
            mensagens=tuple(mensagens),
        )

    def compor_diagnostico_sem_regra(
        self,
        entradas: Iterable[EntradaDeLog],
        *,
        evidencias: Iterable[Evidencia] = (),
        vinculos_percorridos: Iterable[VinculoIdentificadores] = (),
    ) -> ExplicacaoRastreavel:
        """Retorna explicitamente o limite diagnóstico exigido pelo Req. 17.4."""

        return self.compor(
            entradas,
            Categoria.NAO_CLASSIFICADA,
            evidencias=evidencias,
            vinculos_percorridos=vinculos_percorridos,
            causa_raiz=ResultadoCausaRaiz(),
        )


def referencia_regra_de_vinculo(vinculo: VinculoIdentificadores) -> str:
    """Identifica de forma determinística o esquema versionado de uma aresta."""

    if not isinstance(vinculo, VinculoIdentificadores):
        raise TypeError("vinculo deve ser VinculoIdentificadores.")
    return f"vinculo:{vinculo.esquema_id}:v{vinculo.esquema_versao}"


def mensagem_sem_regra_correspondente(
    estado_causa_raiz: EstadoCausaRaiz = EstadoCausaRaiz.NAO_DETERMINADA,
) -> MensagemExplicabilidade:
    """Cria a mensagem canônica de não correspondência integral."""

    return MensagemExplicabilidade(
        codigo=(
            CodigoMensagemExplicabilidade.NENHUMA_REGRA_VALIDADA_CORRESPONDEU
        ),
        descricao_segura=MENSAGEM_SEM_REGRA_CORRESPONDENTE,
        categoria_de_cenario=Categoria.NAO_CLASSIFICADA,
        estado_causa_raiz=estado_causa_raiz,
    )


def mensagem_causa_raiz_nao_determinada(
    categoria_de_cenario: Categoria = Categoria.NAO_CLASSIFICADA,
) -> MensagemExplicabilidade:
    """Cria a mensagem canônica sem qualquer hipótese causal."""

    return MensagemExplicabilidade(
        codigo=CodigoMensagemExplicabilidade.CAUSA_RAIZ_NAO_DETERMINADA,
        descricao_segura=MENSAGEM_CAUSA_RAIZ_NAO_DETERMINADA,
        categoria_de_cenario=categoria_de_cenario,
        estado_causa_raiz=EstadoCausaRaiz.NAO_DETERMINADA,
    )


def construir_evidencia_de_entrada(
    entrada: EntradaDeLog,
    campo_ou_condicao: str,
    representacao_destinada_a_sanitizacao: str,
    **kwargs: object,
) -> Evidencia:
    """Wrapper funcional de :meth:`construir_evidencia_de_entrada`."""

    return CompositorDeExplicabilidade().construir_evidencia_de_entrada(
        entrada,
        campo_ou_condicao,
        representacao_destinada_a_sanitizacao,
        **kwargs,  # type: ignore[arg-type]
    )


def construir_evidencia_de_vinculo(
    entrada: EntradaDeLog,
    vinculo: VinculoIdentificadores,
    representacao_destinada_a_sanitizacao: str,
    *,
    campo_ou_condicao: str | None = None,
) -> Evidencia:
    """Wrapper funcional de :meth:`construir_evidencia_de_vinculo`."""

    return CompositorDeExplicabilidade().construir_evidencia_de_vinculo(
        entrada,
        vinculo,
        representacao_destinada_a_sanitizacao,
        campo_ou_condicao=campo_ou_condicao,
    )


def compor_explicacao(
    entradas: Iterable[EntradaDeLog],
    categoria_de_cenario: Categoria,
    **kwargs: object,
) -> ExplicacaoRastreavel:
    """Wrapper funcional para composição rastreável."""

    return CompositorDeExplicabilidade().compor(
        entradas,
        categoria_de_cenario,
        **kwargs,  # type: ignore[arg-type]
    )


def compor_diagnostico_sem_regra(
    entradas: Iterable[EntradaDeLog],
    *,
    evidencias: Iterable[Evidencia] = (),
    vinculos_percorridos: Iterable[VinculoIdentificadores] = (),
) -> ExplicacaoRastreavel:
    """Wrapper funcional para diagnóstico fail-closed sem regra aplicável."""

    return CompositorDeExplicabilidade().compor_diagnostico_sem_regra(
        entradas,
        evidencias=evidencias,
        vinculos_percorridos=vinculos_percorridos,
    )


def _validar_entrada_rastreavel(entrada: EntradaDeLog) -> None:
    if not isinstance(entrada, EntradaDeLog):
        raise TypeError("entrada deve ser EntradaDeLog.")
    _exigir_texto(entrada.aplicacao, "entrada.aplicacao")
    if entrada.entrada_id is None:
        raise ValueError("evidência requer entrada_id rastreável.")
    if entrada.arquivo_token is None:
        raise ValueError("evidência requer arquivo_token rastreável.")
    if entrada.posicao_inicial is None or entrada.posicao_final is None:
        raise ValueError("evidência requer posição inicial e final rastreável.")


def _validar_proveniencia_da_entrada(
    proveniencia: Proveniencia, entrada: EntradaDeLog
) -> None:
    if proveniencia.entrada_id != entrada.entrada_id:
        raise ValueError("proveniência referencia entrada diferente.")
    if proveniencia.arquivo_token != entrada.arquivo_token:
        raise ValueError("proveniência referencia arquivo diferente.")
    if (
        entrada.posicao_inicial is None
        or entrada.posicao_final is None
        or proveniencia.linha_inicial < entrada.posicao_inicial
        or proveniencia.linha_final > entrada.posicao_final
    ):
        raise ValueError("proveniência está fora da posição da entrada.")


def _validar_causa_raiz(causa_raiz: ResultadoCausaRaiz) -> None:
    if causa_raiz.estado is EstadoCausaRaiz.NAO_DETERMINADA:
        if causa_raiz.regra is not None:
            raise ValueError(
                "causa-raiz não determinada não pode declarar regra causal."
            )
        if causa_raiz.descricao_sanitizada != "não determinada":
            raise ValueError(
                "causa-raiz não determinada não pode conter explicação causal."
            )


def _evidencia_documenta_vinculo(
    evidencia: Evidencia, vinculo: VinculoIdentificadores
) -> bool:
    proveniencia = evidencia.proveniencia
    origem = vinculo.evidencia
    return (
        evidencia.tipo == "vinculo"
        and proveniencia.arquivo_token == origem.arquivo_token
        and proveniencia.entrada_id == origem.entrada_id
        and proveniencia.linha_inicial == origem.linha_inicial
        and proveniencia.linha_final == origem.linha_final
        and proveniencia.regra_extracao
        == referencia_regra_de_vinculo(vinculo)
    )


def _materializar_tupla(
    valores: Iterable[_T], tipo: type[_T], nome: str
) -> tuple[_T, ...]:
    if isinstance(valores, (str, bytes)):
        raise TypeError(f"{nome} deve ser um iterável de {tipo.__name__}.")
    try:
        resultado = tuple(valores)
    except TypeError:
        raise TypeError(
            f"{nome} deve ser um iterável de {tipo.__name__}."
        ) from None
    if not all(isinstance(valor, tipo) for valor in resultado):
        raise TypeError(f"{nome} deve conter somente {tipo.__name__}.")
    return resultado


def _tupla_sem_duplicatas(valores: tuple[_T, ...]) -> tuple[_T, ...]:
    resultado: list[_T] = []
    for valor in valores:
        if valor not in resultado:
            resultado.append(valor)
    return tuple(resultado)


def _exigir_texto(valor: object, nome: str) -> None:
    if not isinstance(valor, str) or not valor.strip():
        raise ValueError(f"{nome} deve ser uma string não vazia.")


# Aliases concisos para consumidores que preferem omitir a preposição.
construir_evidencia_entrada = construir_evidencia_de_entrada
construir_evidencia_vinculo = construir_evidencia_de_vinculo


__all__ = [
    "AspectosDaEntrada",
    "CodigoMensagemExplicabilidade",
    "CompositorDeExplicabilidade",
    "DimensoesDaAnalise",
    "ExplicacaoRastreavel",
    "MENSAGEM_CAUSA_RAIZ_NAO_DETERMINADA",
    "MENSAGEM_SEM_REGRA_CORRESPONDENTE",
    "MensagemExplicabilidade",
    "compor_diagnostico_sem_regra",
    "compor_explicacao",
    "construir_evidencia_de_entrada",
    "construir_evidencia_de_vinculo",
    "construir_evidencia_entrada",
    "construir_evidencia_vinculo",
    "mensagem_causa_raiz_nao_determinada",
    "mensagem_sem_regra_correspondente",
    "referencia_regra_de_vinculo",
]
