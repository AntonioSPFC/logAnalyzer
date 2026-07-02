"""Testes de propriedade para o Registro_de_Aplicacoes.

Feature: log-analyzer
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from log_analyzer.core.excecoes import ErroDeRegistro
from log_analyzer.core.interfaces import Padrao_de_Analise, Parser_de_Aplicacao
from log_analyzer.core.modelos import Categoria, EntradaDeLog
from log_analyzer.core.registro import Registro_de_Aplicacoes


# ---------------------------------------------------------------------------
# Helpers: implementações concretas mínimas que satisfazem as interfaces
# ---------------------------------------------------------------------------


class _ParserValido(Parser_de_Aplicacao):
    """Parser concreto mínimo para testes de propriedade."""

    @property
    def niveis_de_severidade(self) -> frozenset[str]:
        return frozenset({"INFO", "ERROR"})

    def interpretar_entrada(self, texto: str) -> EntradaDeLog:
        return EntradaDeLog(
            texto_original=texto,
            aplicacao="test",
            ordem_de_leitura=0,
            interpretada=False,
        )

    def imprimir_entrada(self, entrada: EntradaDeLog) -> str:
        return entrada.texto_original


class _PadraoValido(Padrao_de_Analise):
    """Padrão concreto mínimo para testes de propriedade."""

    @property
    def categorias(self) -> tuple[Categoria, ...]:
        return (Categoria.SUCESSO, Categoria.ERRO, Categoria.NAO_CLASSIFICADA)

    def classificar(self, entrada: EntradaDeLog) -> Categoria:
        return Categoria.NAO_CLASSIFICADA


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Estratégia para gerar app_ids únicos: strings ASCII alfanuméricas não vazias
_app_id_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), min_codepoint=48, max_codepoint=122),
    min_size=1,
    max_size=20,
)

# Estratégia para gerar listas de app_ids únicos (mínimo 1, máximo 10)
_unique_app_ids_strategy = st.lists(
    _app_id_strategy,
    min_size=1,
    max_size=10,
    unique=True,
)

# Objetos que NÃO implementam Parser_de_Aplicacao
_invalid_parser_strategy = st.sampled_from(
    [None, 42, "not_a_parser", 3.14, [], {}, object(), True]
)

# Objetos que NÃO implementam Padrao_de_Analise
_invalid_padrao_strategy = st.sampled_from(
    [None, 99, "not_a_padrao", 2.71, [], {}, object(), False]
)

# Estratégia para o tipo de invalidade que será testada
_invalidity_kind = st.sampled_from(["invalid_parser", "invalid_padrao", "duplicate_id"])


# ---------------------------------------------------------------------------
# Property 12: Registro/associação inválida não altera o estado
# ---------------------------------------------------------------------------


@given(
    pre_registered_ids=st.lists(_app_id_strategy, min_size=0, max_size=5, unique=True),
    target_id=_app_id_strategy,
    invalidity=_invalidity_kind,
    invalid_parser=_invalid_parser_strategy,
    invalid_padrao=_invalid_padrao_strategy,
)
@settings(max_examples=100)
def test_property_12_registro_invalido_nao_altera_estado(
    pre_registered_ids: list[str],
    target_id: str,
    invalidity: str,
    invalid_parser: object,
    invalid_padrao: object,
) -> None:
    """Feature: log-analyzer, Property 12: Registro/associação inválida não altera o estado

    Para todo Registro_de_Aplicacoes e toda tentativa de registro inválida — parser ou padrão
    que não implementa a interface comum, Identificador de Aplicação duplicado, ou associação
    a uma Aplicação não registrada — o registro é rejeitado, o conjunto de Aplicações
    reconhecidas permanece inalterado e é produzida uma indicação de erro identificando a causa
    (interface não implementada, identificador duplicado ou aplicação não suportada).

    **Validates: Requirements 2.2, 6.8, 7.5, 7.6**
    """
    # --- Arrange: criar um registro e pré-popular com aplicações válidas ---
    registro = Registro_de_Aplicacoes()
    for app_id in pre_registered_ids:
        registro.registrar(app_id, _ParserValido(), _PadraoValido())

    # Capturar o estado antes da tentativa inválida
    apps_antes = registro.aplicacoes_suportadas()

    # --- Act: tentar um registro inválido conforme o tipo sorteado ---
    if invalidity == "invalid_parser":
        # Parser que não implementa Parser_de_Aplicacao
        with pytest.raises(ErroDeRegistro) as exc_info:
            registro.registrar(
                target_id,
                invalid_parser,  # type: ignore[arg-type]
                _PadraoValido(),
            )
        # Verificar que o erro identifica a causa: interface não implementada
        assert "Parser_de_Aplicacao" in exc_info.value.mensagem

    elif invalidity == "invalid_padrao":
        # Padrão que não implementa Padrao_de_Analise
        with pytest.raises(ErroDeRegistro) as exc_info:
            registro.registrar(
                target_id,
                _ParserValido(),
                invalid_padrao,  # type: ignore[arg-type]
            )
        # Verificar que o erro identifica a causa: interface não implementada
        assert "Padrao_de_Analise" in exc_info.value.mensagem

    elif invalidity == "duplicate_id":
        # Identificador de Aplicação duplicado — precisamos que target_id já exista
        if target_id not in apps_antes:
            # Registrar o target_id para torná-lo duplicado
            registro.registrar(target_id, _ParserValido(), _PadraoValido())
            # Atualizar o snapshot do estado (inclui target_id agora)
            apps_antes = registro.aplicacoes_suportadas()

        # Agora tentar registrar com o mesmo id novamente
        with pytest.raises(ErroDeRegistro) as exc_info:
            registro.registrar(target_id, _ParserValido(), _PadraoValido())
        # Verificar que o erro identifica a causa: duplicado
        erro_msg = exc_info.value.mensagem.lower()
        erro_ctx = str(exc_info.value.contexto.get("causa", "")).lower()
        assert "duplicado" in erro_msg or "duplicado" in erro_ctx

    # --- Assert: o estado do registro não foi alterado ---
    apps_depois = registro.aplicacoes_suportadas()
    assert apps_depois == apps_antes, (
        f"Estado do registro foi alterado! Antes: {apps_antes}, Depois: {apps_depois}"
    )

    # Verificar que cada aplicação pré-existente ainda pode ser resolvida
    for app_id in apps_antes:
        assert registro.esta_registrada(app_id)
        parser_obtido, padrao_obtido = registro.obter(app_id)
        assert isinstance(parser_obtido, Parser_de_Aplicacao)
        assert isinstance(padrao_obtido, Padrao_de_Analise)

    # Verificar que obter para uma aplicação não registrada levanta ErroDeRegistro
    app_inexistente = "___INEXISTENTE___"
    if not registro.esta_registrada(app_inexistente):
        with pytest.raises(ErroDeRegistro):
            registro.obter(app_inexistente)


# ---------------------------------------------------------------------------
# Property 13: Extensibilidade preserva as Aplicações existentes
# ---------------------------------------------------------------------------


@given(app_ids=_unique_app_ids_strategy)
@settings(max_examples=100)
def test_property_13_extensibilidade_preserva_aplicacoes_existentes(
    app_ids: list[str],
) -> None:
    """Feature: log-analyzer, Property 13: Extensibilidade preserva as Aplicações existentes

    Para todo Registro_de_Aplicacoes e toda nova Aplicação válida com Identificador inédito
    (parser e padrão implementando as interfaces comuns), após o registro a nova Aplicação
    passa a ser reconhecida e disponível para seleção, enquanto os pares parser/padrão de
    todas as Aplicações previamente registradas permanecem idênticos.

    **Validates: Requirements 7.1, 7.2**
    """
    registro = Registro_de_Aplicacoes()

    # Registrar as aplicações uma a uma, verificando as invariantes após cada registro
    for i, app_id in enumerate(app_ids):
        # Capturar o estado anterior: snapshot dos pares parser/padrão existentes
        apps_antes = registro.aplicacoes_suportadas()
        pares_antes: dict[str, tuple[Parser_de_Aplicacao, Padrao_de_Analise]] = {}
        for existing_id in apps_antes:
            pares_antes[existing_id] = registro.obter(existing_id)

        # Criar instâncias únicas de parser e padrão para esta aplicação
        novo_parser = _ParserValido()
        novo_padrao = _PadraoValido()

        # Registrar a nova aplicação
        registro.registrar(app_id, novo_parser, novo_padrao)

        # Verificar: a nova app é reconhecida (esta_registrada retorna True)
        assert registro.esta_registrada(app_id), (
            f"Após registro, '{app_id}' deveria estar registrada."
        )

        # Verificar: aplicacoes_suportadas cresce exatamente por 1
        apps_depois = registro.aplicacoes_suportadas()
        assert len(apps_depois) == len(apps_antes) + 1, (
            f"Esperava {len(apps_antes) + 1} apps, obteve {len(apps_depois)}."
        )

        # Verificar: a nova app está disponível para seleção
        assert app_id in apps_depois, (
            f"'{app_id}' deveria estar em aplicacoes_suportadas após o registro."
        )

        # Verificar: todas as aplicações previamente registradas permanecem com
        # pares parser/padrão idênticos (identidade — mesmos objetos)
        for existing_id, (parser_antes, padrao_antes) in pares_antes.items():
            parser_depois, padrao_depois = registro.obter(existing_id)
            assert parser_depois is parser_antes, (
                f"Parser de '{existing_id}' mudou após registrar '{app_id}'."
            )
            assert padrao_depois is padrao_antes, (
                f"Padrão de '{existing_id}' mudou após registrar '{app_id}'."
            )
