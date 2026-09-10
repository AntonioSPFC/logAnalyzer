"""Property 29: compatibilidade de plugins line-based da Fase 1."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given, settings
from hypothesis import strategies as st

from log_analyzer.core.analisador import Analisador_de_Logs
from log_analyzer.core.interfaces import (
    Padrao_de_Analise,
    Parser_de_Aplicacao,
    Parser_de_Bloco,
)
from log_analyzer.core.modelos import ArquivoSelecionado, Categoria, EntradaDeLog
from log_analyzer.core.registro import Registro_de_Aplicacoes
from tests.phase2.strategies.fields import opaque_values


class _ParserLegadoGerado(Parser_de_Aplicacao):
    """Parser que implementa somente o contrato line-based da Fase 1."""

    def __init__(self, app_id: str, niveis: frozenset[str]) -> None:
        self._app_id = app_id
        self._niveis = niveis
        self.linhas_recebidas: list[str] = []

    @property
    def niveis_de_severidade(self) -> frozenset[str]:
        return self._niveis

    def interpretar_entrada(self, texto: str) -> EntradaDeLog:
        self.linhas_recebidas.append(texto)
        return EntradaDeLog(
            texto_original=texto,
            aplicacao=self._app_id,
            ordem_de_leitura=0,
            interpretada=False,
        )

    def imprimir_entrada(self, entrada: EntradaDeLog) -> str:
        return entrada.texto_original


class _PadraoLegadoGerado(Padrao_de_Analise):
    """Padrão que implementa somente a classificação por entrada da Fase 1."""

    def __init__(self, categoria: Categoria) -> None:
        self._categoria = categoria
        self.entradas_recebidas: list[tuple[str, str, int]] = []

    @property
    def categorias(self) -> tuple[Categoria, ...]:
        return (Categoria.SUCESSO, Categoria.ERRO, Categoria.NAO_CLASSIFICADA)

    def classificar(self, entrada: EntradaDeLog) -> Categoria:
        self.entradas_recebidas.append(
            (entrada.texto_original, entrada.aplicacao, entrada.ordem_de_leitura)
        )
        return self._categoria


_IDS_EXISTENTES = st.lists(
    opaque_values("EXISTING_APP", min_bytes=1, max_bytes=4),
    min_size=0,
    max_size=4,
    unique=True,
)
_ID_NOVO_PLUGIN = opaque_values("LEGACY_APP", min_bytes=1, max_bytes=4)
_IDENTIFICADORES = opaque_values("CALL", min_bytes=1, max_bytes=8)
_CONTEUDOS_DE_LINHA = st.lists(
    opaque_values("LINE", min_bytes=1, max_bytes=12),
    min_size=1,
    max_size=6,
)
_NIVEIS = st.sets(
    st.sampled_from(("TRACE", "DEBUG", "INFO", "WARN", "ERROR")),
    min_size=1,
    max_size=5,
).map(frozenset)


# Feature: log-analyzer-phase-2, Property 29: Plugins legados permanecem válidos
@given(
    ids_existentes=_IDS_EXISTENTES,
    novo_app_id=_ID_NOVO_PLUGIN,
    identificador=_IDENTIFICADORES,
    conteudos=_CONTEUDOS_DE_LINHA,
    niveis=_NIVEIS,
    categoria=st.sampled_from(tuple(Categoria)),
    terminador=st.sampled_from((b"\n", b"\r\n")),
    terminar_ultima_linha=st.booleans(),
)
@settings(max_examples=100)
def test_property_29_plugins_legados_permanecem_validos(
    ids_existentes: list[str],
    novo_app_id: str,
    identificador: str,
    conteudos: list[str],
    niveis: frozenset[str],
    categoria: Categoria,
    terminador: bytes,
    terminar_ultima_linha: bool,
) -> None:
    """Plugins restritos aos ABCs antigos mantêm registro e fluxo line-based.

    **Validates: Requirements 1.2, 1.6**
    """
    registro = Registro_de_Aplicacoes()
    pares_existentes: dict[
        str, tuple[_ParserLegadoGerado, _PadraoLegadoGerado]
    ] = {}

    for app_id in ids_existentes:
        parser_existente = _ParserLegadoGerado(app_id, frozenset({"INFO"}))
        padrao_existente = _PadraoLegadoGerado(Categoria.NAO_CLASSIFICADA)
        registro.registrar(app_id, parser_existente, padrao_existente)
        pares_existentes[app_id] = (parser_existente, padrao_existente)

    apps_antes = registro.aplicacoes_suportadas()
    parser = _ParserLegadoGerado(novo_app_id, niveis)
    padrao = _PadraoLegadoGerado(categoria)

    assert Parser_de_Aplicacao.__abstractmethods__ == frozenset(
        {"niveis_de_severidade", "interpretar_entrada", "imprimir_entrada"}
    )
    assert Padrao_de_Analise.__abstractmethods__ == frozenset(
        {"categorias", "classificar"}
    )
    assert type(parser).interpretar_arquivo is Parser_de_Aplicacao.interpretar_arquivo
    assert not isinstance(parser, Parser_de_Bloco)
    assert not hasattr(parser, "detectar_inicio")
    assert not hasattr(parser, "interpretar_bloco")

    registro.registrar(novo_app_id, parser, padrao)

    assert registro.aplicacoes_suportadas() == (*apps_antes, novo_app_id)
    assert registro.esta_registrada(novo_app_id)
    parser_resolvido, padrao_resolvido = registro.obter(novo_app_id)
    assert parser_resolvido is parser
    assert padrao_resolvido is padrao
    for app_id, (parser_antes, padrao_antes) in pares_existentes.items():
        parser_depois, padrao_depois = registro.obter(app_id)
        assert parser_depois is parser_antes
        assert padrao_depois is padrao_antes

    linhas = [f"{conteudo} {identificador}" for conteudo in conteudos]
    payload = terminador.join(linha.encode("ascii") for linha in linhas)
    if terminar_ultima_linha:
        payload += terminador

    with TemporaryDirectory(prefix="phase2-property29-synthetic-") as diretorio:
        arquivo = Path(diretorio) / "legacy-plugin-synthetic.log"
        arquivo.write_bytes(payload)
        resultado = Analisador_de_Logs(registro).analisar(
            [ArquivoSelecionado(caminho=str(arquivo), app_id=novo_app_id)],
            identificador,
        )

    assert resultado.erros == []
    entradas = resultado.entradas_por_aplicacao[novo_app_id]
    assert [entrada.texto_original for entrada in entradas] == linhas
    assert [entrada.aplicacao for entrada in entradas] == [novo_app_id] * len(linhas)
    assert [entrada.ordem_de_leitura for entrada in entradas] == list(
        range(len(linhas))
    )
    assert [entrada.categoria for entrada in entradas] == [categoria] * len(linhas)
    assert parser.linhas_recebidas == linhas
    assert padrao.entradas_recebidas == [
        (linha, novo_app_id, ordem) for ordem, linha in enumerate(linhas)
    ]

    assert registro.aplicacoes_suportadas() == (*apps_antes, novo_app_id)
    assert registro.obter(novo_app_id) == (parser, padrao)
    for app_id, (parser_antes, padrao_antes) in pares_existentes.items():
        parser_depois, padrao_depois = registro.obter(app_id)
        assert parser_depois is parser_antes
        assert padrao_depois is padrao_antes
        assert parser_depois.linhas_recebidas == []
        assert padrao_depois.entradas_recebidas == []
