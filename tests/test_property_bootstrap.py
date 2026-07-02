"""Testes de propriedade para o bootstrap do Registro_de_Aplicacoes.

Feature: log-analyzer
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from log_analyzer.core.interfaces import Padrao_de_Analise, Parser_de_Aplicacao
from log_analyzer.core.modelos import Categoria, EntradaDeLog
from log_analyzer.core.registro import Registro_de_Aplicacoes


# ---------------------------------------------------------------------------
# Helpers: implementações concretas mínimas com identidade única
# ---------------------------------------------------------------------------


class _ParserUnico(Parser_de_Aplicacao):
    """Parser concreto mínimo com identidade única para verificação de roteamento."""

    def __init__(self, app_id: str) -> None:
        self._app_id = app_id

    @property
    def niveis_de_severidade(self) -> frozenset[str]:
        return frozenset({"INFO", "ERROR"})

    def interpretar_entrada(self, texto: str) -> EntradaDeLog:
        return EntradaDeLog(
            texto_original=texto,
            aplicacao=self._app_id,
            ordem_de_leitura=0,
            interpretada=False,
        )

    def imprimir_entrada(self, entrada: EntradaDeLog) -> str:
        return entrada.texto_original


class _PadraoUnico(Padrao_de_Analise):
    """Padrão concreto mínimo com identidade única para verificação de roteamento."""

    def __init__(self, app_id: str) -> None:
        self._app_id = app_id

    @property
    def categorias(self) -> tuple[Categoria, ...]:
        return (Categoria.SUCESSO, Categoria.ERRO, Categoria.NAO_CLASSIFICADA)

    def classificar(self, entrada: EntradaDeLog) -> Categoria:
        return Categoria.NAO_CLASSIFICADA


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Estratégia para gerar app_ids: strings alfanuméricas não vazias
_app_id_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd"),
        min_codepoint=48,
        max_codepoint=122,
    ),
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


# ---------------------------------------------------------------------------
# Property 7: Roteamento parser/padrão pela Aplicação associada
# ---------------------------------------------------------------------------


@given(app_ids=_unique_app_ids_strategy)
@settings(max_examples=100)
def test_property_7_roteamento_parser_padrao_pela_aplicacao(
    app_ids: list[str],
) -> None:
    """Feature: log-analyzer, Property 7: Roteamento parser/padrão pela Aplicação associada

    Para todo conjunto de Arquivos_de_Log com Aplicações associadas variadas, cada
    Arquivo_de_Log é interpretado pelo Parser_de_Aplicacao e classificado pelo
    Padrao_de_Analise registrados para a sua Aplicação no Registro_de_Aplicacoes.

    **Validates: Requirements 1.3, 5.2**
    """
    # --- Arrange: criar registro e registrar apps com parsers/padrões únicos ---
    registro = Registro_de_Aplicacoes()

    # Mapear cada app_id ao par (parser, padrao) registrado
    pares_registrados: dict[str, tuple[_ParserUnico, _PadraoUnico]] = {}

    for app_id in app_ids:
        parser = _ParserUnico(app_id)
        padrao = _PadraoUnico(app_id)
        registro.registrar(app_id, parser, padrao)
        pares_registrados[app_id] = (parser, padrao)

    # --- Act & Assert: para cada app, obter retorna exatamente o par registrado ---
    for app_id in app_ids:
        parser_obtido, padrao_obtido = registro.obter(app_id)

        parser_esperado, padrao_esperado = pares_registrados[app_id]

        # Verificar identidade de objeto — é exatamente o parser que foi registrado
        assert parser_obtido is parser_esperado, (
            f"Para app '{app_id}', obter() retornou parser diferente do registrado. "
            f"Esperado: {parser_esperado!r}, Obtido: {parser_obtido!r}"
        )

        # Verificar identidade de objeto — é exatamente o padrão que foi registrado
        assert padrao_obtido is padrao_esperado, (
            f"Para app '{app_id}', obter() retornou padrão diferente do registrado. "
            f"Esperado: {padrao_esperado!r}, Obtido: {padrao_obtido!r}"
        )

        # Verificar que são instâncias das interfaces corretas
        assert isinstance(parser_obtido, Parser_de_Aplicacao)
        assert isinstance(padrao_obtido, Padrao_de_Analise)
