"""Regressão de plugins de terceiros e registro.

Verifica que plugins mínimos line-based (implementando somente os ABCs da Fase 1)
continuam funcionando corretamente: registro dinâmico, resolução, análise via
Analisador_de_Logs e falhas atômicas. Também garante que o bootstrap padrão
continua produzindo exatamente VPL, ORK e VOCI.

Requirements: 1.3, 1.6
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from log_analyzer.core.analisador import Analisador_de_Logs
from log_analyzer.core.bootstrap import criar_registro_padrao
from log_analyzer.core.excecoes import ErroDeRegistro
from log_analyzer.core.interfaces import (
    Padrao_de_Analise,
    Parser_de_Aplicacao,
    Parser_de_Bloco,
)
from log_analyzer.core.modelos import ArquivoSelecionado, Categoria, EntradaDeLog
from log_analyzer.core.registro import Registro_de_Aplicacoes


# ---------------------------------------------------------------------------
# Plugins mínimos line-based para testes
# ---------------------------------------------------------------------------


class _PluginParserMinimo(Parser_de_Aplicacao):
    """Parser mínimo que implementa somente os ABCs da Fase 1."""

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


class _PluginPadraoMinimo(Padrao_de_Analise):
    """Padrão mínimo que implementa somente a classificação da Fase 1."""

    def __init__(self, categoria_fixa: Categoria = Categoria.NAO_CLASSIFICADA) -> None:
        self._categoria = categoria_fixa

    @property
    def categorias(self) -> tuple[Categoria, ...]:
        return (Categoria.SUCESSO, Categoria.ERRO, Categoria.NAO_CLASSIFICADA)

    def classificar(self, entrada: EntradaDeLog) -> Categoria:
        return self._categoria


# ---------------------------------------------------------------------------
# Dados sintéticos
# ---------------------------------------------------------------------------

_ID_SINTETICO = "SYN_PLUGIN_REGRESSAO_A1B2C3"
_LINHAS_SINTETICAS = [
    f"mensagem alfa {_ID_SINTETICO}",
    f"mensagem beta {_ID_SINTETICO}",
    f"mensagem gama {_ID_SINTETICO}",
]


# ---------------------------------------------------------------------------
# Testes de bootstrap (exatamente VPL, ORK e VOCI)
# ---------------------------------------------------------------------------


class TestBootstrapExato:
    """Verifica que o bootstrap padrão contém exatamente VPL, ORK e VOCI."""

    def test_bootstrap_contem_exatamente_tres_apps(self) -> None:
        registro = criar_registro_padrao()
        assert len(registro.aplicacoes_suportadas()) == 3

    def test_bootstrap_ids_exatos(self) -> None:
        registro = criar_registro_padrao()
        apps = set(registro.aplicacoes_suportadas())
        assert apps == {"VPL", "ORK", "VOCI"}

    def test_bootstrap_ordem_preservada(self) -> None:
        """A ordem de registro é VPL, ORK, VOCI."""
        registro = criar_registro_padrao()
        assert registro.aplicacoes_suportadas() == ("VPL", "ORK", "VOCI")

    def test_bootstrap_todos_tem_parser_e_padrao(self) -> None:
        registro = criar_registro_padrao()
        for app_id in ("VPL", "ORK", "VOCI"):
            parser, padrao = registro.obter(app_id)
            assert isinstance(parser, Parser_de_Aplicacao)
            assert isinstance(padrao, Padrao_de_Analise)

    def test_bootstrap_nenhum_extra_registrado(self) -> None:
        """Nenhuma aplicação além das três iniciais está registrada."""
        registro = criar_registro_padrao()
        for app_id in ("XPTO", "CUSTOM", "LEGACY"):
            assert not registro.esta_registrada(app_id)


# ---------------------------------------------------------------------------
# Testes de registro dinâmico de plugins line-based
# ---------------------------------------------------------------------------


class TestRegistroDinamico:
    """Registro dinâmico de um plugin line-based sem alterar o bootstrap."""

    def test_registrar_plugin_terceiro(self) -> None:
        """Um plugin mínimo line-based pode ser registrado após o bootstrap."""
        registro = criar_registro_padrao()
        parser = _PluginParserMinimo("CUSTOM_APP")
        padrao = _PluginPadraoMinimo()
        registro.registrar("CUSTOM_APP", parser, padrao)
        assert registro.esta_registrada("CUSTOM_APP")
        assert "CUSTOM_APP" in registro.aplicacoes_suportadas()

    def test_registrar_nao_altera_existentes(self) -> None:
        """Registrar um novo plugin não altera VPL, ORK nem VOCI."""
        registro = criar_registro_padrao()
        apps_antes = registro.aplicacoes_suportadas()
        registro.registrar(
            "TERCEIRO", _PluginParserMinimo("TERCEIRO"), _PluginPadraoMinimo()
        )
        # Os três iniciais continuam inalterados
        for app_id in ("VPL", "ORK", "VOCI"):
            assert registro.esta_registrada(app_id)
        # E mantêm a mesma ordem original
        assert registro.aplicacoes_suportadas()[:3] == apps_antes

    def test_registrar_multiplos_plugins(self) -> None:
        """Múltiplos plugins de terceiros podem coexistir."""
        registro = criar_registro_padrao()
        for i in range(3):
            app_id = f"PLUGIN_{i}"
            registro.registrar(
                app_id, _PluginParserMinimo(app_id), _PluginPadraoMinimo()
            )
        assert len(registro.aplicacoes_suportadas()) == 6  # 3 + 3

    def test_plugin_nao_implementa_parser_de_bloco(self) -> None:
        """Plugin line-based não implementa Parser_de_Bloco."""
        parser = _PluginParserMinimo("TEST")
        assert not isinstance(parser, Parser_de_Bloco)


# ---------------------------------------------------------------------------
# Testes de resolução
# ---------------------------------------------------------------------------


class TestResolucao:
    """Resolução de plugin registrado dinamicamente."""

    def test_resolver_plugin_registrado(self) -> None:
        registro = criar_registro_padrao()
        parser = _PluginParserMinimo("MEU_PLUGIN")
        padrao = _PluginPadraoMinimo(Categoria.SUCESSO)
        registro.registrar("MEU_PLUGIN", parser, padrao)
        parser_resolvido, padrao_resolvido = registro.obter("MEU_PLUGIN")
        assert parser_resolvido is parser
        assert padrao_resolvido is padrao

    def test_resolver_plugin_nao_registrado_falha(self) -> None:
        registro = criar_registro_padrao()
        with pytest.raises(ErroDeRegistro):
            registro.obter("NAO_EXISTE")

    def test_resolucao_preserva_bootstrap(self) -> None:
        """Registrar e resolver plugin não muda a resolução dos existentes."""
        registro = criar_registro_padrao()
        vpl_parser, vpl_padrao = registro.obter("VPL")
        registro.registrar(
            "EXTRA", _PluginParserMinimo("EXTRA"), _PluginPadraoMinimo()
        )
        vpl_parser_depois, vpl_padrao_depois = registro.obter("VPL")
        assert vpl_parser_depois is vpl_parser
        assert vpl_padrao_depois is vpl_padrao


# ---------------------------------------------------------------------------
# Testes de análise com plugin de terceiro
# ---------------------------------------------------------------------------


class TestAnaliseComPlugin:
    """Análise end-to-end usando um plugin de terceiro line-based."""

    def _criar_arquivo_sintetico(self, diretorio: Path) -> Path:
        """Cria um arquivo temporário com linhas sintéticas."""
        arquivo = diretorio / "plugin_sintetico.log"
        arquivo.write_text("\n".join(_LINHAS_SINTETICAS) + "\n", encoding="utf-8")
        return arquivo

    def test_analise_plugin_terceiro_basica(self, tmp_path: Path) -> None:
        """O plugin line-based é analisado corretamente pelo fluxo legado."""
        registro = criar_registro_padrao()
        parser = _PluginParserMinimo("TERCEIRO")
        padrao = _PluginPadraoMinimo(Categoria.NAO_CLASSIFICADA)
        registro.registrar("TERCEIRO", parser, padrao)

        arquivo = self._criar_arquivo_sintetico(tmp_path)
        resultado = Analisador_de_Logs(registro).analisar(
            [ArquivoSelecionado(caminho=str(arquivo), app_id="TERCEIRO")],
            _ID_SINTETICO,
        )

        # Sem erros
        assert resultado.erros == []
        # Entradas encontradas
        entradas = resultado.entradas_por_aplicacao.get("TERCEIRO", [])
        assert len(entradas) == len(_LINHAS_SINTETICAS)

    def test_analise_plugin_preserva_texto_original(self, tmp_path: Path) -> None:
        """As entradas preservam o texto original das linhas."""
        registro = criar_registro_padrao()
        registro.registrar(
            "TERCEIRO", _PluginParserMinimo("TERCEIRO"), _PluginPadraoMinimo()
        )

        arquivo = self._criar_arquivo_sintetico(tmp_path)
        resultado = Analisador_de_Logs(registro).analisar(
            [ArquivoSelecionado(caminho=str(arquivo), app_id="TERCEIRO")],
            _ID_SINTETICO,
        )

        entradas = resultado.entradas_por_aplicacao.get("TERCEIRO", [])
        textos = [e.texto_original for e in entradas]
        assert textos == _LINHAS_SINTETICAS

    def test_analise_plugin_classificacao_aplicada(self, tmp_path: Path) -> None:
        """O padrão do plugin é usado para classificar cada entrada."""
        registro = criar_registro_padrao()
        registro.registrar(
            "CLASSIF",
            _PluginParserMinimo("CLASSIF"),
            _PluginPadraoMinimo(Categoria.SUCESSO),
        )

        arquivo = tmp_path / "classif.log"
        arquivo.write_text(
            f"linha {_ID_SINTETICO}\n", encoding="utf-8"
        )
        resultado = Analisador_de_Logs(registro).analisar(
            [ArquivoSelecionado(caminho=str(arquivo), app_id="CLASSIF")],
            _ID_SINTETICO,
        )

        entradas = resultado.entradas_por_aplicacao.get("CLASSIF", [])
        assert len(entradas) == 1
        assert entradas[0].categoria == Categoria.SUCESSO

    def test_analise_plugin_ordem_de_leitura(self, tmp_path: Path) -> None:
        """A ordem de leitura é atribuída sequencialmente."""
        registro = criar_registro_padrao()
        registro.registrar(
            "SEQAPP", _PluginParserMinimo("SEQAPP"), _PluginPadraoMinimo()
        )

        arquivo = self._criar_arquivo_sintetico(tmp_path)
        resultado = Analisador_de_Logs(registro).analisar(
            [ArquivoSelecionado(caminho=str(arquivo), app_id="SEQAPP")],
            _ID_SINTETICO,
        )

        entradas = resultado.entradas_por_aplicacao.get("SEQAPP", [])
        ordens = [e.ordem_de_leitura for e in entradas]
        assert ordens == list(range(len(_LINHAS_SINTETICAS)))

    def test_analise_plugin_coexiste_com_voci(self, tmp_path: Path) -> None:
        """Plugin de terceiro e VOCI coexistem na mesma análise."""
        registro = criar_registro_padrao()
        registro.registrar(
            "EXTRA", _PluginParserMinimo("EXTRA"), _PluginPadraoMinimo()
        )

        # Arquivo para o plugin
        arquivo_extra = tmp_path / "extra.log"
        arquivo_extra.write_text(
            f"dado extra {_ID_SINTETICO}\n", encoding="utf-8"
        )

        # Arquivo para VOCI
        arquivo_voci = tmp_path / "voci.log"
        arquivo_voci.write_text(
            f"2031-06-15 10:20:30\tINFO\tmensagem voci {_ID_SINTETICO}\n",
            encoding="utf-8",
        )

        resultado = Analisador_de_Logs(registro).analisar(
            [
                ArquivoSelecionado(caminho=str(arquivo_extra), app_id="EXTRA"),
                ArquivoSelecionado(caminho=str(arquivo_voci), app_id="VOCI"),
            ],
            _ID_SINTETICO,
        )

        assert resultado.erros == []
        assert "EXTRA" in resultado.entradas_por_aplicacao
        assert "VOCI" in resultado.entradas_por_aplicacao


# ---------------------------------------------------------------------------
# Testes de falhas atômicas
# ---------------------------------------------------------------------------


class TestFalhasAtomicas:
    """Falhas de registro e resolução são atômicas e não corrompem o catálogo."""

    def test_registro_duplicado_preserva_catalogo(self) -> None:
        """Tentativa de registrar app_id duplicado não altera o existente."""
        registro = criar_registro_padrao()
        snapshot = registro.aplicacoes_suportadas()

        with pytest.raises(ErroDeRegistro):
            registro.registrar(
                "VPL", _PluginParserMinimo("VPL"), _PluginPadraoMinimo()
            )

        # Catálogo não alterado
        assert registro.aplicacoes_suportadas() == snapshot

    def test_registro_parser_invalido_preserva_catalogo(self) -> None:
        """Parser inválido não deixa o catálogo corrompido."""
        registro = criar_registro_padrao()
        snapshot = registro.aplicacoes_suportadas()

        with pytest.raises(ErroDeRegistro):
            registro.registrar(
                "NOVO", "nao_sou_parser", _PluginPadraoMinimo()  # type: ignore[arg-type]
            )

        assert registro.aplicacoes_suportadas() == snapshot
        assert not registro.esta_registrada("NOVO")

    def test_registro_padrao_invalido_preserva_catalogo(self) -> None:
        """Padrão inválido não deixa o catálogo corrompido."""
        registro = criar_registro_padrao()
        snapshot = registro.aplicacoes_suportadas()

        with pytest.raises(ErroDeRegistro):
            registro.registrar(
                "NOVO", _PluginParserMinimo("NOVO"), 42  # type: ignore[arg-type]
            )

        assert registro.aplicacoes_suportadas() == snapshot
        assert not registro.esta_registrada("NOVO")

    def test_falha_de_um_plugin_nao_afeta_outros(self, tmp_path: Path) -> None:
        """Se um plugin falha no registro, os outros continuam operacionais."""
        registro = criar_registro_padrao()
        registro.registrar(
            "BOM", _PluginParserMinimo("BOM"), _PluginPadraoMinimo()
        )

        with pytest.raises(ErroDeRegistro):
            registro.registrar(
                "BOM", _PluginParserMinimo("BOM2"), _PluginPadraoMinimo()
            )

        # O plugin "BOM" continua funcional
        parser, padrao = registro.obter("BOM")
        assert isinstance(parser, Parser_de_Aplicacao)
        assert isinstance(padrao, Padrao_de_Analise)

    def test_analise_com_app_nao_registrada_gera_erro(
        self, tmp_path: Path
    ) -> None:
        """Análise com app_id não registrado gera erro sem travar."""
        registro = criar_registro_padrao()
        arquivo = tmp_path / "inexistente.log"
        arquivo.write_text("conteudo\n", encoding="utf-8")

        resultado = Analisador_de_Logs(registro).analisar(
            [ArquivoSelecionado(caminho=str(arquivo), app_id="NAO_EXISTE")],
            _ID_SINTETICO,
        )

        # Deve produzir erro, não travar
        assert len(resultado.erros) > 0

    def test_analise_falha_parcial_preserva_outros(self, tmp_path: Path) -> None:
        """Falha em um arquivo não impede análise dos outros."""
        registro = criar_registro_padrao()
        registro.registrar(
            "PLUGIN_OK", _PluginParserMinimo("PLUGIN_OK"), _PluginPadraoMinimo()
        )

        # Arquivo válido
        arquivo_ok = tmp_path / "ok.log"
        arquivo_ok.write_text(f"ok {_ID_SINTETICO}\n", encoding="utf-8")

        # Arquivo com app inválida
        resultado = Analisador_de_Logs(registro).analisar(
            [
                ArquivoSelecionado(caminho=str(arquivo_ok), app_id="PLUGIN_OK"),
                ArquivoSelecionado(
                    caminho=str(tmp_path / "falha.log"), app_id="NAO_EXISTE"
                ),
            ],
            _ID_SINTETICO,
        )

        # O plugin OK foi processado
        entradas = resultado.entradas_por_aplicacao.get("PLUGIN_OK", [])
        assert len(entradas) == 1
        # E o erro foi registrado
        assert len(resultado.erros) > 0

    def test_falha_sequencial_nao_corrompe_registro(self) -> None:
        """Múltiplas falhas sequenciais não corrompem o catálogo."""
        registro = criar_registro_padrao()

        for i in range(5):
            with pytest.raises(ErroDeRegistro):
                registro.registrar(
                    "VPL",  # duplicado
                    _PluginParserMinimo(f"VPL_{i}"),
                    _PluginPadraoMinimo(),
                )

        # Catálogo inalterado após todas as falhas
        assert registro.aplicacoes_suportadas() == ("VPL", "ORK", "VOCI")
        # Ainda podemos registrar plugins válidos
        registro.registrar(
            "NOVO_OK", _PluginParserMinimo("NOVO_OK"), _PluginPadraoMinimo()
        )
        assert registro.esta_registrada("NOVO_OK")
