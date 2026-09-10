"""DSL fechada e total para predicados estruturados de regras da Fase 2.

O módulo avalia somente aplicações declaradas, campos estruturados, vínculos
explícitos, fatos estruturados, cardinalidades e timestamps UTC já
normalizados. Texto livre de entradas (``texto_original`` e ``mensagem``) não é
consultado. O catálogo fornece apenas dados: não existe despacho dinâmico,
regex configurável, ``eval``, ``exec``, importação, SQL, templates ou callables.

Condições desconhecidas ou malformadas produzem ``ERRO_SEGURO``. Um conjunto de
condições só fica satisfeito quando é não vazio e todas as condições ficam
satisfeitas; qualquer ausência, ambiguidade ou erro permanece fail-closed.

Requirements: 10.1, 10.2, 10.3, 13.2, 17.6
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from typing import TypeAlias

from log_analyzer.core.catalogo import CondicaoRegra
from log_analyzer.core.modelos import (
    CampoEstruturado,
    EntradaDeLog,
    Proveniencia,
    TipoIdentificador,
    VinculoIdentificadores,
)


class OperadorDSL(str, Enum):
    """Conjunto fechado de operadores aceitos do catálogo."""

    APLICACAO_PRESENTE = "APPLICATION_PRESENT"
    CAMPO_PRESENTE = "FIELD_PRESENT"
    CAMPO_IGUAL = "FIELD_EQUALS"
    VINCULO_EXPLICITO_PRESENTE = "EXPLICIT_LINK_PRESENT"
    VINCULO_PRESENTE = "LINK_PRESENT"
    FATO_PRESENTE = "FACT_PRESENT"
    CARDINALIDADE = "CARDINALITY"
    ORDEM_TEMPORAL = "TEMPORAL_ORDER"


OPERADORES_SUPORTADOS = frozenset(operador.value for operador in OperadorDSL)


class EstadoAvaliacaoDSL(str, Enum):
    """Resultado total de uma condição ou conjunto de condições."""

    SATISFEITA = "satisfeita"
    NAO_SATISFEITA = "nao_satisfeita"
    ERRO_SEGURO = "erro_seguro"


class CodigoErroDSL(str, Enum):
    """Códigos constantes que nunca incorporam dados do catálogo ou cenário."""

    CONDICAO_INVALIDA = "DSL_CONDITION_INVALID"
    OPERADOR_NAO_SUPORTADO = "DSL_OPERATOR_NOT_ALLOWED"
    PARAMETROS_INVALIDOS = "DSL_PARAMETERS_INVALID"
    CONTEXTO_INVALIDO = "DSL_CONTEXT_INVALID"
    AVALIACAO_FALHOU = "DSL_EVALUATION_ERROR"
    SEM_CONDICOES = "DSL_EMPTY_CONDITIONS"
    CONDICAO_DUPLICADA = "DSL_DUPLICATE_CONDITION"


class TipoReferenciaDSL(str, Enum):
    """Tipos não textuais de evidência que uma condição pode referenciar."""

    APLICACAO = "aplicacao"
    ENTRADA = "entrada"
    CAMPO = "campo_estruturado"
    VINCULO = "vinculo_explicito"
    FATO = "fato_estruturado"


class AlvoCardinalidade(str, Enum):
    """Coleções estruturadas que o operador de cardinalidade pode contar."""

    APLICACAO = "APPLICATION"
    ENTRADA = "ENTRY"
    CAMPO = "FIELD"
    VINCULO = "LINK"
    FATO = "FACT"


class ComparadorCardinalidade(str, Enum):
    """Comparadores inteiros fechados do operador ``CARDINALITY``."""

    IGUAL = "EQ"
    MAIOR_OU_IGUAL = "GTE"
    MENOR_OU_IGUAL = "LTE"
    MAIOR = "GT"
    MENOR = "LT"


@dataclass(frozen=True)
class FatoEstruturado:
    """Fato opaco produzido pelo pipeline, sem qualquer texto livre.

    ``codigo`` identifica o tipo de fato. A proveniência é opcional para fatos
    globais; quando presente, permite uma referência determinística à entrada
    que produziu o fato.
    """

    codigo: str
    aplicacao: str | None = None
    proveniencia: Proveniencia | None = None

    def __post_init__(self) -> None:
        _validar_texto_estrutural(self.codigo, "codigo")
        if self.aplicacao is not None:
            _validar_texto_estrutural(self.aplicacao, "aplicacao")
        if self.proveniencia is not None and not isinstance(
            self.proveniencia, Proveniencia
        ):
            raise TypeError("proveniencia deve ser Proveniencia ou None.")


@dataclass(frozen=True)
class ContextoAvaliacaoDSL:
    """Snapshot imutável dos dados estruturados visíveis à DSL."""

    entradas: tuple[EntradaDeLog, ...] = ()
    aplicacoes: tuple[str, ...] = ()
    vinculos: tuple[VinculoIdentificadores, ...] = ()
    fatos: tuple[FatoEstruturado, ...] = ()

    def __post_init__(self) -> None:
        _validar_tupla_tipificada(
            self.entradas, EntradaDeLog, "entradas"
        )
        if not isinstance(self.aplicacoes, tuple) or not all(
            isinstance(aplicacao, str) and bool(aplicacao.strip())
            for aplicacao in self.aplicacoes
        ):
            raise TypeError(
                "aplicacoes deve ser uma tupla de strings não vazias."
            )
        _validar_tupla_tipificada(
            self.vinculos, VinculoIdentificadores, "vinculos"
        )
        _validar_tupla_tipificada(self.fatos, FatoEstruturado, "fatos")

    @property
    def aplicacoes_presentes(self) -> tuple[str, ...]:
        """Aplicações explícitas ou representadas por entradas estruturadas."""

        return tuple(
            sorted(
                {
                    *(aplicacao.strip() for aplicacao in self.aplicacoes),
                    *(entrada.aplicacao for entrada in self.entradas),
                }
            )
        )


ContextoDeAvaliacao = ContextoAvaliacaoDSL


@dataclass(frozen=True)
class ReferenciaEvidenciaDSL:
    """Referência estrutural, determinística e sem valores de campos/IDs."""

    tipo: TipoReferenciaDSL
    chave: str
    aplicacao: str | None = None
    entrada_id: str | None = None
    arquivo_token: str | None = None
    linha_inicial: int | None = None
    linha_final: int | None = None
    nome_estrutural: str | None = None
    regra_estrutural: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.tipo, TipoReferenciaDSL):
            raise TypeError("tipo deve ser TipoReferenciaDSL.")
        _validar_texto_estrutural(self.chave, "chave")
        for nome, valor in (
            ("aplicacao", self.aplicacao),
            ("entrada_id", self.entrada_id),
            ("arquivo_token", self.arquivo_token),
            ("nome_estrutural", self.nome_estrutural),
            ("regra_estrutural", self.regra_estrutural),
        ):
            if valor is not None:
                _validar_texto_estrutural(valor, nome)
        if (self.linha_inicial is None) != (self.linha_final is None):
            raise ValueError(
                "linha_inicial e linha_final devem ser informadas juntas."
            )
        if self.linha_inicial is not None and self.linha_final is not None:
            if self.linha_inicial < 1 or self.linha_final < self.linha_inicial:
                raise ValueError("intervalo de linhas inválido.")


@dataclass(frozen=True)
class ResultadoAvaliacaoCondicao:
    """Resultado total de uma condição individual."""

    condicao_id: str
    operador: str
    estado: EstadoAvaliacaoDSL
    referencias: tuple[ReferenciaEvidenciaDSL, ...] = ()
    codigo_erro: str | None = None

    def __post_init__(self) -> None:
        _validar_texto_estrutural(self.condicao_id, "condicao_id")
        _validar_texto_estrutural(self.operador, "operador")
        if not isinstance(self.estado, EstadoAvaliacaoDSL):
            raise TypeError("estado deve ser EstadoAvaliacaoDSL.")
        _validar_tupla_tipificada(
            self.referencias, ReferenciaEvidenciaDSL, "referencias"
        )
        if self.estado is EstadoAvaliacaoDSL.ERRO_SEGURO:
            if self.codigo_erro is None:
                raise ValueError("erro seguro requer codigo_erro.")
            _validar_texto_estrutural(self.codigo_erro, "codigo_erro")
            if self.referencias:
                raise ValueError("erro seguro não pode expor referências.")
        elif self.codigo_erro is not None:
            raise ValueError(
                "resultado sem erro não pode declarar codigo_erro."
            )
        if (
            self.estado is EstadoAvaliacaoDSL.NAO_SATISFEITA
            and self.referencias
        ):
            raise ValueError(
                "condição não satisfeita não pode declarar evidências."
            )

    @property
    def satisfeita(self) -> bool:
        return self.estado is EstadoAvaliacaoDSL.SATISFEITA

    @property
    def nao_satisfeita(self) -> bool:
        return self.estado is EstadoAvaliacaoDSL.NAO_SATISFEITA

    @property
    def erro_seguro(self) -> bool:
        return self.estado is EstadoAvaliacaoDSL.ERRO_SEGURO

    @property
    def evidencias(self) -> tuple[ReferenciaEvidenciaDSL, ...]:
        return self.referencias


@dataclass(frozen=True)
class ReferenciaCondicaoSatisfeita:
    """Associa deterministicamente uma condição às evidências que a cobrem."""

    condicao_id: str
    operador: str
    evidencias: tuple[ReferenciaEvidenciaDSL, ...] = ()

    def __post_init__(self) -> None:
        _validar_texto_estrutural(self.condicao_id, "condicao_id")
        if self.operador not in OPERADORES_SUPORTADOS:
            raise ValueError("operador deve pertencer ao conjunto fechado.")
        _validar_tupla_tipificada(
            self.evidencias, ReferenciaEvidenciaDSL, "evidencias"
        )


@dataclass(frozen=True)
class ResultadoAvaliacaoDSL:
    """Conjunção total e fail-closed de condições de uma regra."""

    estado: EstadoAvaliacaoDSL
    resultados: tuple[ResultadoAvaliacaoCondicao, ...] = ()
    codigo_erro: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.estado, EstadoAvaliacaoDSL):
            raise TypeError("estado deve ser EstadoAvaliacaoDSL.")
        _validar_tupla_tipificada(
            self.resultados, ResultadoAvaliacaoCondicao, "resultados"
        )
        if self.estado is EstadoAvaliacaoDSL.ERRO_SEGURO:
            if self.codigo_erro is None:
                raise ValueError("erro seguro requer codigo_erro.")
            _validar_texto_estrutural(self.codigo_erro, "codigo_erro")
        elif self.codigo_erro is not None:
            raise ValueError(
                "resultado sem erro não pode declarar codigo_erro."
            )

    @property
    def satisfeita(self) -> bool:
        return self.estado is EstadoAvaliacaoDSL.SATISFEITA

    @property
    def condicoes_satisfeitas(self) -> tuple[str, ...]:
        return tuple(
            resultado.condicao_id
            for resultado in self.resultados
            if resultado.satisfeita
        )

    @property
    def referencias_satisfeitas(
        self,
    ) -> tuple[ReferenciaCondicaoSatisfeita, ...]:
        return tuple(
            ReferenciaCondicaoSatisfeita(
                condicao_id=resultado.condicao_id,
                operador=resultado.operador,
                evidencias=resultado.referencias,
            )
            for resultado in self.resultados
            if resultado.satisfeita
        )


class _FalhaDSL(Exception):
    def __init__(self, codigo: CodigoErroDSL) -> None:
        super().__init__(codigo.value)
        self.codigo = codigo


_ParValue: TypeAlias = object
_Parametros: TypeAlias = dict[str, _ParValue]


class AvaliadorDSL:
    """Despacha somente os operadores enumerados e sempre retorna resultado."""

    def avaliar_condicao(
        self,
        condicao: CondicaoRegra,
        contexto: ContextoAvaliacaoDSL,
    ) -> ResultadoAvaliacaoCondicao:
        condicao_id = _id_seguro_da_condicao(condicao)
        operador_seguro = _operador_seguro(condicao)

        if not isinstance(condicao, CondicaoRegra):
            return _resultado_erro(
                condicao_id,
                operador_seguro,
                CodigoErroDSL.CONDICAO_INVALIDA,
            )
        if not _id_catalogo_valido(condicao.condition_id):
            return _resultado_erro(
                "CONDICAO_INVALIDA",
                operador_seguro,
                CodigoErroDSL.CONDICAO_INVALIDA,
            )
        if not isinstance(contexto, ContextoAvaliacaoDSL):
            return _resultado_erro(
                condicao_id,
                operador_seguro,
                CodigoErroDSL.CONTEXTO_INVALIDO,
            )

        try:
            operador = OperadorDSL(condicao.operator)
        except (TypeError, ValueError):
            return _resultado_erro(
                condicao_id,
                "UNKNOWN",
                CodigoErroDSL.OPERADOR_NAO_SUPORTADO,
            )

        try:
            parametros = _materializar_parametros(condicao)
            if operador is OperadorDSL.APLICACAO_PRESENTE:
                referencias = _avaliar_aplicacao(parametros, contexto)
            elif operador in {
                OperadorDSL.CAMPO_PRESENTE,
                OperadorDSL.CAMPO_IGUAL,
            }:
                referencias = _avaliar_campo(
                    operador, parametros, contexto
                )
            elif operador in {
                OperadorDSL.VINCULO_EXPLICITO_PRESENTE,
                OperadorDSL.VINCULO_PRESENTE,
            }:
                referencias = _avaliar_vinculo(parametros, contexto)
            elif operador is OperadorDSL.FATO_PRESENTE:
                referencias = _avaliar_fato(parametros, contexto)
            elif operador is OperadorDSL.CARDINALIDADE:
                satisfeita, referencias = _avaliar_cardinalidade(
                    parametros, contexto
                )
                return _resultado_booleano(
                    condicao_id,
                    operador.value,
                    satisfeita,
                    referencias,
                )
            elif operador is OperadorDSL.ORDEM_TEMPORAL:
                satisfeita, referencias = _avaliar_ordem_temporal(
                    parametros, contexto
                )
                return _resultado_booleano(
                    condicao_id,
                    operador.value,
                    satisfeita,
                    referencias,
                )
            else:  # pragma: no cover - proteção para evolução incorreta do enum
                raise _FalhaDSL(CodigoErroDSL.OPERADOR_NAO_SUPORTADO)

            return _resultado_booleano(
                condicao_id,
                operador.value,
                bool(referencias),
                referencias,
            )
        except _FalhaDSL as falha:
            return _resultado_erro(
                condicao_id, operador.value, falha.codigo
            )
        except Exception:
            # Nenhuma exceção ou dado do cenário atravessa a fronteira da DSL.
            return _resultado_erro(
                condicao_id,
                operador.value,
                CodigoErroDSL.AVALIACAO_FALHOU,
            )

    def avaliar_condicoes(
        self,
        condicoes: Iterable[CondicaoRegra],
        contexto: ContextoAvaliacaoDSL,
    ) -> ResultadoAvaliacaoDSL:
        """Avalia uma conjunção; vazio, duplicata e erro falham fechados."""

        if isinstance(condicoes, (str, bytes)):
            return ResultadoAvaliacaoDSL(
                estado=EstadoAvaliacaoDSL.ERRO_SEGURO,
                codigo_erro=CodigoErroDSL.CONDICAO_INVALIDA.value,
            )
        try:
            materializadas = tuple(condicoes)
        except Exception:
            return ResultadoAvaliacaoDSL(
                estado=EstadoAvaliacaoDSL.ERRO_SEGURO,
                codigo_erro=CodigoErroDSL.CONDICAO_INVALIDA.value,
            )

        if not materializadas:
            return ResultadoAvaliacaoDSL(
                estado=EstadoAvaliacaoDSL.ERRO_SEGURO,
                codigo_erro=CodigoErroDSL.SEM_CONDICOES.value,
            )

        resultados = tuple(
            sorted(
                (
                    self.avaliar_condicao(condicao, contexto)
                    for condicao in materializadas
                ),
                key=lambda resultado: (
                    resultado.condicao_id,
                    resultado.operador,
                ),
            )
        )
        ids = tuple(resultado.condicao_id for resultado in resultados)
        if len(ids) != len(set(ids)):
            return ResultadoAvaliacaoDSL(
                estado=EstadoAvaliacaoDSL.ERRO_SEGURO,
                resultados=resultados,
                codigo_erro=CodigoErroDSL.CONDICAO_DUPLICADA.value,
            )

        erros = tuple(
            resultado for resultado in resultados if resultado.erro_seguro
        )
        if erros:
            codigo = min(
                resultado.codigo_erro
                for resultado in erros
                if resultado.codigo_erro is not None
            )
            return ResultadoAvaliacaoDSL(
                estado=EstadoAvaliacaoDSL.ERRO_SEGURO,
                resultados=resultados,
                codigo_erro=codigo,
            )
        if all(resultado.satisfeita for resultado in resultados):
            return ResultadoAvaliacaoDSL(
                estado=EstadoAvaliacaoDSL.SATISFEITA,
                resultados=resultados,
            )
        return ResultadoAvaliacaoDSL(
            estado=EstadoAvaliacaoDSL.NAO_SATISFEITA,
            resultados=resultados,
        )

    avaliar = avaliar_condicao
    avaliar_regra = avaliar_condicoes


DSLDeRegras = AvaliadorDSL


def avaliar_condicao(
    condicao: CondicaoRegra,
    contexto: ContextoAvaliacaoDSL,
) -> ResultadoAvaliacaoCondicao:
    """Wrapper funcional para avaliação total de uma condição."""

    return AvaliadorDSL().avaliar_condicao(condicao, contexto)


def avaliar_condicoes(
    condicoes: Iterable[CondicaoRegra],
    contexto: ContextoAvaliacaoDSL,
) -> ResultadoAvaliacaoDSL:
    """Wrapper funcional para conjunção fail-closed de condições."""

    return AvaliadorDSL().avaliar_condicoes(condicoes, contexto)


def _avaliar_aplicacao(
    parametros: _Parametros,
    contexto: ContextoAvaliacaoDSL,
) -> tuple[ReferenciaEvidenciaDSL, ...]:
    _exigir_chaves(parametros, requeridas={"application"})
    aplicacao = _parametro_texto(parametros, "application")
    if aplicacao not in contexto.aplicacoes_presentes:
        return ()
    return (_referencia_aplicacao(aplicacao),)


def _avaliar_campo(
    operador: OperadorDSL,
    parametros: _Parametros,
    contexto: ContextoAvaliacaoDSL,
) -> tuple[ReferenciaEvidenciaDSL, ...]:
    requeridas = {"field"}
    opcionais = {"application"}
    if operador is OperadorDSL.CAMPO_IGUAL:
        requeridas.add("expected")
    _exigir_chaves(parametros, requeridas=requeridas, opcionais=opcionais)

    nome = _parametro_texto(parametros, "field")
    aplicacao = _parametro_texto_opcional(parametros, "application")
    esperado = (
        _parametro_texto(parametros, "expected")
        if operador is OperadorDSL.CAMPO_IGUAL
        else None
    )
    referencias: list[ReferenciaEvidenciaDSL] = []
    for entrada, campo in _campos_ordenados(contexto):
        if aplicacao is not None and entrada.aplicacao != aplicacao:
            continue
        if campo.nome != nome:
            continue
        if esperado is not None and campo.valor_original != esperado:
            continue
        referencias.append(_referencia_campo(entrada, campo))
    return _normalizar_referencias(referencias)


def _avaliar_vinculo(
    parametros: _Parametros,
    contexto: ContextoAvaliacaoDSL,
) -> tuple[ReferenciaEvidenciaDSL, ...]:
    _exigir_chaves(
        parametros,
        requeridas={"relation"},
        opcionais={
            "schema_id",
            "schema_version",
            "source_type",
            "target_type",
            "allows_correlation",
        },
    )
    filtros = _filtros_vinculo(parametros, relacao_obrigatoria=True)
    return _selecionar_vinculos(contexto, filtros)


def _avaliar_fato(
    parametros: _Parametros,
    contexto: ContextoAvaliacaoDSL,
) -> tuple[ReferenciaEvidenciaDSL, ...]:
    _exigir_chaves(
        parametros,
        requeridas={"fact"},
        opcionais={"application"},
    )
    codigo = _parametro_texto(parametros, "fact")
    aplicacao = _parametro_texto_opcional(parametros, "application")
    return _selecionar_fatos(contexto, codigo=codigo, aplicacao=aplicacao)


def _avaliar_cardinalidade(
    parametros: _Parametros,
    contexto: ContextoAvaliacaoDSL,
) -> tuple[bool, tuple[ReferenciaEvidenciaDSL, ...]]:
    for chave in ("target", "comparison", "value"):
        if chave not in parametros:
            raise _FalhaDSL(CodigoErroDSL.PARAMETROS_INVALIDOS)

    alvo = _parametro_enum(
        parametros, "target", AlvoCardinalidade
    )
    comparador = _comparador_cardinalidade(parametros["comparison"])
    valor = _parametro_inteiro_nao_negativo(parametros, "value")

    base = {"target", "comparison", "value"}
    if alvo is AlvoCardinalidade.APLICACAO:
        _exigir_chaves(
            parametros, requeridas=base, opcionais={"application"}
        )
        aplicacao = _parametro_texto_opcional(parametros, "application")
        referencias = tuple(
            _referencia_aplicacao(item)
            for item in contexto.aplicacoes_presentes
            if aplicacao is None or item == aplicacao
        )
    elif alvo is AlvoCardinalidade.ENTRADA:
        _exigir_chaves(
            parametros, requeridas=base, opcionais={"application"}
        )
        aplicacao = _parametro_texto_opcional(parametros, "application")
        referencias = _normalizar_referencias(
            _referencia_entrada(entrada)
            for entrada in _entradas_ordenadas(contexto)
            if aplicacao is None or entrada.aplicacao == aplicacao
        )
    elif alvo is AlvoCardinalidade.CAMPO:
        _exigir_chaves(
            parametros,
            requeridas=base,
            opcionais={"application", "field", "expected"},
        )
        aplicacao = _parametro_texto_opcional(parametros, "application")
        nome = _parametro_texto_opcional(parametros, "field")
        esperado = _parametro_texto_opcional(parametros, "expected")
        referencias = _normalizar_referencias(
            _referencia_campo(entrada, campo)
            for entrada, campo in _campos_ordenados(contexto)
            if (aplicacao is None or entrada.aplicacao == aplicacao)
            and (nome is None or campo.nome == nome)
            and (esperado is None or campo.valor_original == esperado)
        )
    elif alvo is AlvoCardinalidade.VINCULO:
        opcionais = {
            "relation",
            "schema_id",
            "schema_version",
            "source_type",
            "target_type",
            "allows_correlation",
        }
        _exigir_chaves(parametros, requeridas=base, opcionais=opcionais)
        referencias = _selecionar_vinculos(
            contexto,
            _filtros_vinculo(parametros, relacao_obrigatoria=False),
        )
    elif alvo is AlvoCardinalidade.FATO:
        _exigir_chaves(
            parametros,
            requeridas=base,
            opcionais={"application", "fact"},
        )
        referencias = _selecionar_fatos(
            contexto,
            codigo=_parametro_texto_opcional(parametros, "fact"),
            aplicacao=_parametro_texto_opcional(
                parametros, "application"
            ),
        )
    else:  # pragma: no cover - enum fechado
        raise _FalhaDSL(CodigoErroDSL.PARAMETROS_INVALIDOS)

    quantidade = len(referencias)
    satisfeita = {
        ComparadorCardinalidade.IGUAL: quantidade == valor,
        ComparadorCardinalidade.MAIOR_OU_IGUAL: quantidade >= valor,
        ComparadorCardinalidade.MENOR_OU_IGUAL: quantidade <= valor,
        ComparadorCardinalidade.MAIOR: quantidade > valor,
        ComparadorCardinalidade.MENOR: quantidade < valor,
    }[comparador]
    return satisfeita, referencias if satisfeita else ()


@dataclass(frozen=True)
class _SeletorTemporal:
    tipo: str
    valor: str
    aplicacao: str | None = None


def _avaliar_ordem_temporal(
    parametros: _Parametros,
    contexto: ContextoAvaliacaoDSL,
) -> tuple[bool, tuple[ReferenciaEvidenciaDSL, ...]]:
    _exigir_chaves(
        parametros,
        requeridas={"before", "after"},
        opcionais={"allow_equal"},
    )
    antes = _seletor_temporal(parametros["before"])
    depois = _seletor_temporal(parametros["after"])
    permite_igual = _parametro_booleano_opcional(
        parametros, "allow_equal", padrao=False
    )

    entradas_antes = _entradas_do_seletor(antes, contexto)
    entradas_depois = _entradas_do_seletor(depois, contexto)
    if not entradas_antes or not entradas_depois:
        return False, ()
    if any(
        entrada.timestamp_normalizado is None
        for entrada in (*entradas_antes, *entradas_depois)
    ):
        return False, ()

    ultimo_antes = max(
        entrada.timestamp_normalizado for entrada in entradas_antes
    )
    primeiro_depois = min(
        entrada.timestamp_normalizado for entrada in entradas_depois
    )
    satisfeita = (
        ultimo_antes <= primeiro_depois
        if permite_igual
        else ultimo_antes < primeiro_depois
    )
    if not satisfeita:
        return False, ()
    return True, _normalizar_referencias(
        _referencia_entrada(entrada)
        for entrada in (*entradas_antes, *entradas_depois)
    )


def _seletor_temporal(valor: object) -> _SeletorTemporal:
    dados = _materializar_objeto_fechado(valor)
    chaves = set(dados)
    if chaves == {"application"}:
        return _SeletorTemporal(
            "application", _parametro_texto(dados, "application")
        )
    if chaves == {"entry_id"}:
        return _SeletorTemporal(
            "entry_id", _parametro_texto(dados, "entry_id")
        )
    if chaves in ({"fact"}, {"fact", "application"}):
        return _SeletorTemporal(
            "fact",
            _parametro_texto(dados, "fact"),
            _parametro_texto_opcional(dados, "application"),
        )
    raise _FalhaDSL(CodigoErroDSL.PARAMETROS_INVALIDOS)


def _entradas_do_seletor(
    seletor: _SeletorTemporal,
    contexto: ContextoAvaliacaoDSL,
) -> tuple[EntradaDeLog, ...]:
    entradas = _entradas_ordenadas(contexto)
    if seletor.tipo == "application":
        return tuple(
            entrada
            for entrada in entradas
            if entrada.aplicacao == seletor.valor
        )
    if seletor.tipo == "entry_id":
        return tuple(
            entrada
            for entrada in entradas
            if entrada.entrada_id == seletor.valor
        )
    if seletor.tipo == "fact":
        chaves = {
            (
                fato.proveniencia.arquivo_token,
                fato.proveniencia.entrada_id,
            )
            for fato in contexto.fatos
            if fato.codigo == seletor.valor
            and (
                seletor.aplicacao is None
                or fato.aplicacao == seletor.aplicacao
            )
            and fato.proveniencia is not None
        }
        return tuple(
            entrada
            for entrada in entradas
            if (entrada.arquivo_token, entrada.entrada_id) in chaves
        )
    raise _FalhaDSL(CodigoErroDSL.PARAMETROS_INVALIDOS)


def _filtros_vinculo(
    parametros: _Parametros,
    *,
    relacao_obrigatoria: bool,
) -> dict[str, object]:
    filtros: dict[str, object] = {}
    if relacao_obrigatoria or "relation" in parametros:
        filtros["relation"] = _parametro_texto(parametros, "relation")
    if "schema_id" in parametros:
        filtros["schema_id"] = _parametro_texto(parametros, "schema_id")
    if "schema_version" in parametros:
        filtros["schema_version"] = _parametro_inteiro_positivo(
            parametros, "schema_version"
        )
    if "source_type" in parametros:
        filtros["source_type"] = _tipo_identificador(
            parametros["source_type"]
        )
    if "target_type" in parametros:
        filtros["target_type"] = _tipo_identificador(
            parametros["target_type"]
        )
    if "allows_correlation" in parametros:
        filtros["allows_correlation"] = _parametro_booleano(
            parametros, "allows_correlation"
        )
    return filtros


def _selecionar_vinculos(
    contexto: ContextoAvaliacaoDSL,
    filtros: dict[str, object],
) -> tuple[ReferenciaEvidenciaDSL, ...]:
    referencias: list[ReferenciaEvidenciaDSL] = []
    for vinculo in sorted(contexto.vinculos, key=_ordem_vinculo):
        # Ambiguidade nunca pode satisfazer uma condição de regra.
        if vinculo.ambiguo:
            continue
        if (
            "relation" in filtros
            and vinculo.tipo_relacao != filtros["relation"]
        ):
            continue
        if (
            "schema_id" in filtros
            and vinculo.esquema_id != filtros["schema_id"]
        ):
            continue
        if (
            "schema_version" in filtros
            and vinculo.esquema_versao != filtros["schema_version"]
        ):
            continue
        if (
            "source_type" in filtros
            and vinculo.origem.tipo is not filtros["source_type"]
        ):
            continue
        if (
            "target_type" in filtros
            and vinculo.destino.tipo is not filtros["target_type"]
        ):
            continue
        if (
            "allows_correlation" in filtros
            and vinculo.permite_correlacao
            is not filtros["allows_correlation"]
        ):
            continue
        referencias.append(_referencia_vinculo(vinculo, contexto))
    return _normalizar_referencias(referencias)


def _selecionar_fatos(
    contexto: ContextoAvaliacaoDSL,
    *,
    codigo: str | None,
    aplicacao: str | None,
) -> tuple[ReferenciaEvidenciaDSL, ...]:
    referencias = (
        _referencia_fato(fato)
        for fato in sorted(contexto.fatos, key=_ordem_fato)
        if (codigo is None or fato.codigo == codigo)
        and (aplicacao is None or fato.aplicacao == aplicacao)
    )
    return _normalizar_referencias(referencias)


def _campos_ordenados(
    contexto: ContextoAvaliacaoDSL,
) -> tuple[tuple[EntradaDeLog, CampoEstruturado], ...]:
    pares = (
        (entrada, campo)
        for entrada in contexto.entradas
        for campo in entrada.campos_estruturados
    )
    return tuple(
        sorted(
            pares,
            key=lambda par: (
                _ordem_entrada(par[0]),
                par[1].nome,
                _ordem_proveniencia(par[1].proveniencia),
            ),
        )
    )


def _entradas_ordenadas(
    contexto: ContextoAvaliacaoDSL,
) -> tuple[EntradaDeLog, ...]:
    return tuple(sorted(contexto.entradas, key=_ordem_entrada))


def _ordem_entrada(entrada: EntradaDeLog) -> tuple[object, ...]:
    return (
        entrada.aplicacao,
        entrada.arquivo_token or "",
        entrada.entrada_id or "",
        -1 if entrada.posicao_inicial is None else entrada.posicao_inicial,
        -1 if entrada.posicao_final is None else entrada.posicao_final,
        entrada.ordem_de_leitura,
    )


def _ordem_proveniencia(proveniencia: Proveniencia) -> tuple[object, ...]:
    return (
        proveniencia.arquivo_token,
        proveniencia.entrada_id,
        proveniencia.linha_inicial,
        proveniencia.linha_final,
        -1 if proveniencia.span_inicial is None else proveniencia.span_inicial,
        -1 if proveniencia.span_final is None else proveniencia.span_final,
        proveniencia.nome_campo or "",
        proveniencia.regra_extracao or "",
    )


def _ordem_vinculo(vinculo: VinculoIdentificadores) -> tuple[object, ...]:
    return (
        vinculo.esquema_id,
        vinculo.esquema_versao,
        vinculo.tipo_relacao,
        _ordem_proveniencia(vinculo.evidencia),
        vinculo.origem.tipo.value,
        vinculo.destino.tipo.value,
        vinculo.origem.nome_campo,
        vinculo.destino.nome_campo,
    )


def _ordem_fato(fato: FatoEstruturado) -> tuple[object, ...]:
    return (
        fato.codigo,
        fato.aplicacao or "",
        () if fato.proveniencia is None else _ordem_proveniencia(fato.proveniencia),
    )


def _referencia_aplicacao(aplicacao: str) -> ReferenciaEvidenciaDSL:
    return ReferenciaEvidenciaDSL(
        tipo=TipoReferenciaDSL.APLICACAO,
        chave=f"application:{aplicacao}",
        aplicacao=aplicacao,
        nome_estrutural=aplicacao,
    )


def _referencia_entrada(entrada: EntradaDeLog) -> ReferenciaEvidenciaDSL:
    token = entrada.arquivo_token or "SEM_TOKEN"
    entrada_id = entrada.entrada_id or f"ORDEM_{entrada.ordem_de_leitura}"
    inicio = entrada.posicao_inicial
    fim = entrada.posicao_final
    intervalo = (
        "SEM_POSICAO" if inicio is None else f"{inicio}:{fim}"
    )
    return ReferenciaEvidenciaDSL(
        tipo=TipoReferenciaDSL.ENTRADA,
        chave=(
            f"entry:{entrada.aplicacao}:{token}:{entrada_id}:{intervalo}"
        ),
        aplicacao=entrada.aplicacao,
        entrada_id=entrada.entrada_id,
        arquivo_token=entrada.arquivo_token,
        linha_inicial=inicio,
        linha_final=fim,
        nome_estrutural="timestamp_normalizado",
    )


def _referencia_campo(
    entrada: EntradaDeLog,
    campo: CampoEstruturado,
) -> ReferenciaEvidenciaDSL:
    proveniencia = campo.proveniencia
    return ReferenciaEvidenciaDSL(
        tipo=TipoReferenciaDSL.CAMPO,
        chave=(
            f"field:{entrada.aplicacao}:{proveniencia.arquivo_token}:"
            f"{proveniencia.entrada_id}:{campo.nome}:"
            f"{proveniencia.linha_inicial}:{proveniencia.linha_final}"
        ),
        aplicacao=entrada.aplicacao,
        entrada_id=proveniencia.entrada_id,
        arquivo_token=proveniencia.arquivo_token,
        linha_inicial=proveniencia.linha_inicial,
        linha_final=proveniencia.linha_final,
        nome_estrutural=campo.nome,
        regra_estrutural=proveniencia.regra_extracao,
    )


def _referencia_vinculo(
    vinculo: VinculoIdentificadores,
    contexto: ContextoAvaliacaoDSL,
) -> ReferenciaEvidenciaDSL:
    proveniencia = vinculo.evidencia
    aplicacao = _aplicacao_da_proveniencia(proveniencia, contexto)
    regra = f"link:{vinculo.esquema_id}:v{vinculo.esquema_versao}"
    return ReferenciaEvidenciaDSL(
        tipo=TipoReferenciaDSL.VINCULO,
        chave=(
            f"link:{vinculo.esquema_id}:v{vinculo.esquema_versao}:"
            f"{vinculo.tipo_relacao}:{proveniencia.arquivo_token}:"
            f"{proveniencia.entrada_id}:{proveniencia.linha_inicial}:"
            f"{proveniencia.linha_final}"
        ),
        aplicacao=aplicacao,
        entrada_id=proveniencia.entrada_id,
        arquivo_token=proveniencia.arquivo_token,
        linha_inicial=proveniencia.linha_inicial,
        linha_final=proveniencia.linha_final,
        nome_estrutural=vinculo.tipo_relacao,
        regra_estrutural=regra,
    )


def _referencia_fato(fato: FatoEstruturado) -> ReferenciaEvidenciaDSL:
    proveniencia = fato.proveniencia
    if proveniencia is None:
        return ReferenciaEvidenciaDSL(
            tipo=TipoReferenciaDSL.FATO,
            chave=f"fact:{fato.aplicacao or 'GLOBAL'}:{fato.codigo}",
            aplicacao=fato.aplicacao,
            nome_estrutural=fato.codigo,
        )
    return ReferenciaEvidenciaDSL(
        tipo=TipoReferenciaDSL.FATO,
        chave=(
            f"fact:{fato.aplicacao or 'GLOBAL'}:{fato.codigo}:"
            f"{proveniencia.arquivo_token}:{proveniencia.entrada_id}:"
            f"{proveniencia.linha_inicial}:{proveniencia.linha_final}"
        ),
        aplicacao=fato.aplicacao,
        entrada_id=proveniencia.entrada_id,
        arquivo_token=proveniencia.arquivo_token,
        linha_inicial=proveniencia.linha_inicial,
        linha_final=proveniencia.linha_final,
        nome_estrutural=fato.codigo,
        regra_estrutural=proveniencia.regra_extracao,
    )


def _aplicacao_da_proveniencia(
    proveniencia: Proveniencia,
    contexto: ContextoAvaliacaoDSL,
) -> str | None:
    aplicacoes = {
        entrada.aplicacao
        for entrada in contexto.entradas
        if entrada.entrada_id == proveniencia.entrada_id
        and entrada.arquivo_token == proveniencia.arquivo_token
    }
    return min(aplicacoes) if aplicacoes else None


def _normalizar_referencias(
    referencias: Iterable[ReferenciaEvidenciaDSL],
) -> tuple[ReferenciaEvidenciaDSL, ...]:
    unicas = set(referencias)
    return tuple(
        sorted(
            unicas,
            key=lambda referencia: (
                referencia.tipo.value,
                referencia.chave,
                referencia.aplicacao or "",
                referencia.entrada_id or "",
            ),
        )
    )


def _resultado_booleano(
    condicao_id: str,
    operador: str,
    satisfeita: bool,
    referencias: Iterable[ReferenciaEvidenciaDSL] = (),
) -> ResultadoAvaliacaoCondicao:
    normalizadas = _normalizar_referencias(referencias) if satisfeita else ()
    return ResultadoAvaliacaoCondicao(
        condicao_id=condicao_id,
        operador=operador,
        estado=(
            EstadoAvaliacaoDSL.SATISFEITA
            if satisfeita
            else EstadoAvaliacaoDSL.NAO_SATISFEITA
        ),
        referencias=normalizadas,
    )


def _resultado_erro(
    condicao_id: str,
    operador: str,
    codigo: CodigoErroDSL,
) -> ResultadoAvaliacaoCondicao:
    return ResultadoAvaliacaoCondicao(
        condicao_id=condicao_id,
        operador=operador,
        estado=EstadoAvaliacaoDSL.ERRO_SEGURO,
        codigo_erro=codigo.value,
    )


def _materializar_parametros(condicao: CondicaoRegra) -> _Parametros:
    if not isinstance(condicao.parametros, tuple):
        raise _FalhaDSL(CodigoErroDSL.PARAMETROS_INVALIDOS)
    resultado: _Parametros = {}
    for item in condicao.parametros:
        if (
            not isinstance(item, tuple)
            or len(item) != 2
            or not isinstance(item[0], str)
            or not item[0]
            or item[0] in resultado
        ):
            raise _FalhaDSL(CodigoErroDSL.PARAMETROS_INVALIDOS)
        resultado[item[0]] = item[1]
    return resultado


def _materializar_objeto_fechado(valor: object) -> _Parametros:
    if type(valor) is dict:
        itens = tuple(valor.items())
    elif isinstance(valor, tuple):
        itens = valor
    else:
        raise _FalhaDSL(CodigoErroDSL.PARAMETROS_INVALIDOS)
    resultado: _Parametros = {}
    for item in itens:
        if (
            not isinstance(item, tuple)
            or len(item) != 2
            or not isinstance(item[0], str)
            or not item[0]
            or item[0] in resultado
        ):
            raise _FalhaDSL(CodigoErroDSL.PARAMETROS_INVALIDOS)
        resultado[item[0]] = item[1]
    return resultado


def _exigir_chaves(
    parametros: _Parametros,
    *,
    requeridas: set[str],
    opcionais: set[str] = frozenset(),
) -> None:
    chaves = set(parametros)
    if not requeridas.issubset(chaves) or not chaves.issubset(
        requeridas | opcionais
    ):
        raise _FalhaDSL(CodigoErroDSL.PARAMETROS_INVALIDOS)


def _parametro_texto(
    parametros: _Parametros,
    nome: str,
) -> str:
    valor = parametros.get(nome)
    if not isinstance(valor, str) or not valor.strip() or len(valor) > 16_384:
        raise _FalhaDSL(CodigoErroDSL.PARAMETROS_INVALIDOS)
    return valor


def _parametro_texto_opcional(
    parametros: _Parametros,
    nome: str,
) -> str | None:
    if nome not in parametros:
        return None
    return _parametro_texto(parametros, nome)


def _parametro_booleano(
    parametros: _Parametros,
    nome: str,
) -> bool:
    valor = parametros.get(nome)
    if type(valor) is not bool:
        raise _FalhaDSL(CodigoErroDSL.PARAMETROS_INVALIDOS)
    return valor


def _parametro_booleano_opcional(
    parametros: _Parametros,
    nome: str,
    *,
    padrao: bool,
) -> bool:
    if nome not in parametros:
        return padrao
    return _parametro_booleano(parametros, nome)


def _parametro_inteiro_nao_negativo(
    parametros: _Parametros,
    nome: str,
) -> int:
    valor = parametros.get(nome)
    if type(valor) is not int or valor < 0:
        raise _FalhaDSL(CodigoErroDSL.PARAMETROS_INVALIDOS)
    return valor


def _parametro_inteiro_positivo(
    parametros: _Parametros,
    nome: str,
) -> int:
    valor = _parametro_inteiro_nao_negativo(parametros, nome)
    if valor < 1:
        raise _FalhaDSL(CodigoErroDSL.PARAMETROS_INVALIDOS)
    return valor


def _parametro_enum(
    parametros: _Parametros,
    nome: str,
    enum: type[Enum],
) -> Enum:
    valor = parametros.get(nome)
    if isinstance(valor, enum):
        return valor
    if not isinstance(valor, str):
        raise _FalhaDSL(CodigoErroDSL.PARAMETROS_INVALIDOS)
    try:
        return enum(valor)
    except ValueError:
        raise _FalhaDSL(CodigoErroDSL.PARAMETROS_INVALIDOS) from None


def _tipo_identificador(valor: object) -> TipoIdentificador:
    if isinstance(valor, TipoIdentificador):
        return valor
    if not isinstance(valor, str):
        raise _FalhaDSL(CodigoErroDSL.PARAMETROS_INVALIDOS)
    if valor in TipoIdentificador.__members__:
        return TipoIdentificador[valor]
    try:
        return TipoIdentificador(valor)
    except ValueError:
        raise _FalhaDSL(CodigoErroDSL.PARAMETROS_INVALIDOS) from None


def _comparador_cardinalidade(valor: object) -> ComparadorCardinalidade:
    if isinstance(valor, ComparadorCardinalidade):
        return valor
    aliases = {
        "EXACTLY": ComparadorCardinalidade.IGUAL,
        "AT_LEAST": ComparadorCardinalidade.MAIOR_OU_IGUAL,
        "AT_MOST": ComparadorCardinalidade.MENOR_OU_IGUAL,
    }
    if isinstance(valor, str) and valor in aliases:
        return aliases[valor]
    if not isinstance(valor, str):
        raise _FalhaDSL(CodigoErroDSL.PARAMETROS_INVALIDOS)
    try:
        return ComparadorCardinalidade(valor)
    except ValueError:
        raise _FalhaDSL(CodigoErroDSL.PARAMETROS_INVALIDOS) from None


def _validar_texto_estrutural(valor: object, nome: str) -> None:
    if not isinstance(valor, str) or not valor.strip():
        raise ValueError(f"{nome} deve ser uma string não vazia.")


def _validar_tupla_tipificada(
    valores: object,
    tipo: type[object],
    nome: str,
) -> None:
    if not isinstance(valores, tuple) or not all(
        isinstance(valor, tipo) for valor in valores
    ):
        raise TypeError(f"{nome} deve ser uma tupla de {tipo.__name__}.")


def _id_catalogo_valido(valor: object) -> bool:
    if not isinstance(valor, str) or not 1 <= len(valor) <= 128:
        return False
    if not valor[0].isalpha():
        return False
    return all(
        caractere.isalnum() or caractere in "._:-" for caractere in valor
    )


def _id_seguro_da_condicao(condicao: object) -> str:
    if isinstance(condicao, CondicaoRegra) and _id_catalogo_valido(
        condicao.condition_id
    ):
        return condicao.condition_id
    return "CONDICAO_INVALIDA"


def _operador_seguro(condicao: object) -> str:
    if (
        isinstance(condicao, CondicaoRegra)
        and isinstance(condicao.operator, str)
        and condicao.operator in OPERADORES_SUPORTADOS
    ):
        return condicao.operator
    return "UNKNOWN"


__all__ = [
    "AlvoCardinalidade",
    "AvaliadorDSL",
    "CodigoErroDSL",
    "ComparadorCardinalidade",
    "ContextoAvaliacaoDSL",
    "ContextoDeAvaliacao",
    "DSLDeRegras",
    "EstadoAvaliacaoDSL",
    "FatoEstruturado",
    "OPERADORES_SUPORTADOS",
    "OperadorDSL",
    "ReferenciaCondicaoSatisfeita",
    "ReferenciaEvidenciaDSL",
    "ResultadoAvaliacaoCondicao",
    "ResultadoAvaliacaoDSL",
    "TipoReferenciaDSL",
    "avaliar_condicao",
    "avaliar_condicoes",
]
