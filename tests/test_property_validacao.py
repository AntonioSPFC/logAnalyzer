"""Testes de propriedade para a validação do Identificador.

Feature: log-analyzer
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from log_analyzer.core.excecoes import ErroDeIdentificador
from log_analyzer.core.validacao import validar_identificador


# ---------------------------------------------------------------------------
# Strategies para identificadores inválidos
# ---------------------------------------------------------------------------

# Estratégia: string vazia
_empty_strategy = st.just("")

# Estratégia: composto apenas por espaços em branco (whitespace-only, min 1 char)
_whitespace_only_strategy = st.from_regex(r"^\s+$", fullmatch=True)

# Estratégia: mais de 256 caracteres
_too_long_strategy = st.text(min_size=257, max_size=500)

# Combinar todas as estratégias de identificadores inválidos
_invalid_identifier_strategy = st.one_of(
    _empty_strategy,
    _whitespace_only_strategy,
    _too_long_strategy,
)

# Estratégia para identificadores válidos: 1-256 chars, não composto somente por whitespace
_valid_identifier_strategy = st.text(min_size=1, max_size=256).filter(
    lambda s: not s.isspace()
)


# ---------------------------------------------------------------------------
# Property 9: Validação do Identificador rejeita e preserva o estado
# ---------------------------------------------------------------------------


@given(identificador=_invalid_identifier_strategy)
@settings(max_examples=100)
def test_property_9_validacao_identificador_rejeita_invalidos(
    identificador: str,
) -> None:
    """Feature: log-analyzer, Property 9: Validação do Identificador rejeita e preserva o estado

    Para toda string de Identificador inválida (vazia, composta apenas por espaços em branco,
    ou com mais de 256 caracteres), o Analisador_de_Logs rejeita a busca, preserva inalterados
    o Resultado_de_Analise anterior e os Arquivos_de_Log já selecionados, e produz uma mensagem
    de Identificador inválido.

    **Validates: Requirements 3.5, 10.2, 10.3**
    """
    # A função validar_identificador deve levantar ErroDeIdentificador para todos
    # os identificadores inválidos gerados pela estratégia
    with pytest.raises(ErroDeIdentificador) as exc_info:
        validar_identificador(identificador)

    # A exceção deve conter uma mensagem não vazia
    assert exc_info.value.mensagem, (
        f"ErroDeIdentificador sem mensagem para identificador: {identificador!r}"
    )

    # A exceção deve preservar o identificador original no contexto
    assert exc_info.value.identificador == identificador, (
        f"Identificador na exceção ({exc_info.value.identificador!r}) difere do "
        f"fornecido ({identificador!r})"
    )


@given(identificador=_valid_identifier_strategy)
@settings(max_examples=100)
def test_property_9_validacao_identificador_aceita_validos(
    identificador: str,
) -> None:
    """Feature: log-analyzer, Property 9: Validação do Identificador (caso positivo)

    Para toda string de Identificador válida (1-256 caracteres, não composta apenas por
    espaços em branco), validar_identificador não levanta exceção.

    **Validates: Requirements 3.5, 10.2, 10.3**
    """
    # Não deve levantar nenhuma exceção para identificadores válidos
    result = validar_identificador(identificador)
    assert result is None
