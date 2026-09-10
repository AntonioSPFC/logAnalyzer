"""Regressão de imports, wrappers, modelos e CLI da API pública.

Verifica que ``core.__all__`` mantém todos os exports esperados, que
``EntradaDeLog`` e ``ResultadoDeAnalise`` aceitam construções legadas e da
Fase 2, que a serialização produz dicionários JSON compatíveis, que os
wrappers públicos de carga/filtro/correlação/ordenação/renderização preservam
os contratos de assinatura e comportamento e que a CLI aceita os argumentos
posicionais caracterizados com os códigos de saída corretos.

Todos os dados são sintéticos. Nenhuma fonte bruta ou rede é utilizada.

Requirements: 1.3, 1.4, 1.5, 16.1, 16.3
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import fields, replace
from datetime import datetime, timezone
from inspect import Parameter, signature
from pathlib import Path
from typing import get_type_hints

import pytest

import log_analyzer.core as core
from log_analyzer.cli.apresentacao import renderizar_resultado
from log_analyzer.core.carregador import carregar_arquivo
from log_analyzer.core.correlacao import correlacionar_vpl_ork
from log_analyzer.core.filtro import filtrar_por_identificador
from log_analyzer.core.modelos import (
    Categoria,
    EntradaDeLog,
    MensagemDeErro,
    ResultadoDeAnalise,
)
from log_analyzer.core.ordenacao import ordenar_linha_do_tempo
from log_analyzer.core.serializacao import (
    serializar_entrada_de_log,
    serializar_modelo,
    serializar_resultado_de_analise,
)


_RAIZ_PROJETO = Path(__file__).resolve().parents[2]


# ===========================================================================
# core.__all__ — completude e unicidade
# ===========================================================================

_EXPORTS_CORE_FASE1 = {
    "Analisador_de_Logs",
    "ArquivoSelecionado",
    "Categoria",
    "EntradaDeLog",
    "ErroDeArquivo",
    "ErroDeIdentificador",
    "ErroDeRegistro",
    "ErroDoAnalisador",
    "MensagemDeErro",
    "Padrao_de_Analise",
    "Parser_de_Aplicacao",
    "Registro_de_Aplicacoes",
    "ResultadoDeAnalise",
    "TAMANHO_MAXIMO_BYTES",
    "agrupar_por_aplicacao",
    "calcular_contagens",
    "carregar_arquivo",
    "correlacionar_vpl_ork",
    "criar_registro_padrao",
    "filtrar_por_identificador",
    "ordenar_linha_do_tempo",
    "validar_identificador",
}

_EXPORTS_FASE2_ADITIVOS = {
    "TipoIdentificador",
    "BaseCorrelacao",
    "EstadoSanitizacao",
    "EstadoCausaRaiz",
    "Proveniencia",
    "CampoEstruturado",
    "IdentificadorTecnico",
    "FalhaDeEntrada",
    "VinculoIdentificadores",
    "Evidencia",
    "ReferenciaRegra",
    "ResultadoCorrelacao",
    "ResultadoCausaRaiz",
    "ReferenciaTextoOriginal",
    "EntradaIndexada",
    "ErroDeDecodificacao",
    "ErroTemporal",
    "ErroDeCatalogo",
    "ErroDeSanitizacao",
    "ErroDeIntegridadeDaFonte",
    "TipoInicio",
    "Parser_de_Bloco",
    "serializar_modelo",
    "serializar_entrada_de_log",
    "serializar_resultado_de_analise",
    "SanitizadorDeResultado",
    "ScannerFinalDeResultado",
    "criar_visao_segura",
    "AvaliacaoExemploRegra",
    "CodigoValidacaoCatalogo",
    "CoberturaDeCondicao",
    "ExemploRotuladoCatalogo",
    "ManifestoAtivacaoRegra",
    "PacoteValidacaoCatalogo",
    "PoliticaDeAmostras",
    "ReferenciaVersaoRegra",
    "ResultadoValidacaoCatalogo",
    "ValidadorCatalogo",
    "validar_catalogo_para_publicacao",
    "compor_resultado_fase2",
    "PipelineFase2",
    "PipelineStreamingFase2",
    "executar_pipeline_fase2",
    "LABELS_METRICAS_PERMITIDOS",
    "LABELS_PROIBIDOS",
    "ObservabilidadeSegura",
    "registrar_evento_seguro",
    "validar_labels",
    "validar_labels_metricas",
}


class TestCoreAllExports:
    """Regressão de ``core.__all__``: exports legados e aditivos presentes."""

    def test_exports_fase1_presentes(self) -> None:
        assert _EXPORTS_CORE_FASE1 <= set(core.__all__)

    def test_exports_aditivos_fase2_presentes(self) -> None:
        assert _EXPORTS_FASE2_ADITIVOS <= set(core.__all__)

    def test_sem_duplicatas(self) -> None:
        assert len(core.__all__) == len(set(core.__all__))

    def test_todos_os_nomes_resolvem_para_atributo(self) -> None:
        for nome in core.__all__:
            assert hasattr(core, nome), f"{nome!r} em __all__ mas não acessível"

    def test_exports_totais_incluem_fase1_e_fase2(self) -> None:
        """Union dos conjuntos conhecidos está contida em __all__."""
        esperado = _EXPORTS_CORE_FASE1 | _EXPORTS_FASE2_ADITIVOS
        assert esperado <= set(core.__all__)


# ===========================================================================
# Construções legadas de EntradaDeLog
# ===========================================================================


class TestEntradaDeLogConstrucoesLegadas:
    """Garante que construções posicional e por kwargs da Fase 1 continuam."""

    def test_construcao_posicional_completa(self) -> None:
        instante = datetime(2024, 2, 3, 4, 5, 6)
        entrada = EntradaDeLog(
            "texto sintético regressão",
            "VPL",
            7,
            True,
            instante,
            "INFO",
            "mensagem sintética",
            Categoria.SUCESSO,
            True,
        )
        assert entrada.texto_original == "texto sintético regressão"
        assert entrada.aplicacao == "VPL"
        assert entrada.ordem_de_leitura == 7
        assert entrada.interpretada is True
        assert entrada.carimbo_de_tempo == instante
        assert entrada.nivel_de_severidade == "INFO"
        assert entrada.mensagem == "mensagem sintética"
        assert entrada.categoria is Categoria.SUCESSO
        assert entrada.correlacionada is True

    def test_construcao_minima_por_kwargs(self) -> None:
        entrada = EntradaDeLog(
            texto_original="mínimo",
            aplicacao="ORK",
            ordem_de_leitura=0,
            interpretada=False,
        )
        assert entrada.carimbo_de_tempo is None
        assert entrada.nivel_de_severidade is None
        assert entrada.mensagem is None
        assert entrada.categoria is Categoria.NAO_CLASSIFICADA
        assert entrada.correlacionada is False

    def test_frozen_impede_alteracao(self) -> None:
        entrada = EntradaDeLog(
            texto_original="frozen",
            aplicacao="VOCI",
            ordem_de_leitura=0,
            interpretada=False,
        )
        with pytest.raises(Exception):
            entrada.mensagem = "alterada"  # type: ignore[misc]

    def test_campos_novos_possuem_defaults(self) -> None:
        """Campos da Fase 2 têm defaults e não quebram construção legada."""
        entrada = EntradaDeLog(
            texto_original="regressão legada",
            aplicacao="VPL",
            ordem_de_leitura=1,
            interpretada=False,
        )
        # Campos aditivos não exigem fornecimento explícito
        assert entrada.entrada_id is None
        assert entrada.arquivo_origem is None
        assert entrada.arquivo_token is None
        assert entrada.posicao_inicial is None
        assert entrada.posicao_final is None
        assert entrada.timestamp_original is None
        assert entrada.timestamp_normalizado is None
        assert entrada.precisao_fracionaria is None
        assert entrada.origem_evento is None
        assert entrada.formato_origem is None
        assert entrada.campos_estruturados == ()
        assert entrada.identificadores == ()
        assert entrada.falhas == ()
        assert entrada.representacao_sanitizada is None


# ===========================================================================
# Construções legadas de ResultadoDeAnalise
# ===========================================================================


class TestResultadoDeAnaliseConstrucoesLegadas:
    """Garante que construções posicional e por kwargs do resultado continuam."""

    def test_construcao_posicional_completa(self) -> None:
        entrada = EntradaDeLog(
            "txt", "VPL", 0, False,
        )
        resultado = ResultadoDeAnalise(
            "ID-REGRESSAO",
            {"VPL": [entrada]},
            [entrada],
            {Categoria.NAO_CLASSIFICADA: 1},
            {"VPL": 1},
            False,
            [],
            ["mensagem"],
        )
        assert resultado.identificador == "ID-REGRESSAO"
        assert "VPL" in resultado.entradas_por_aplicacao
        assert len(resultado.linha_do_tempo) == 1
        assert resultado.correlacao_encontrada is False

    def test_construcao_com_defaults_independentes(self) -> None:
        r1 = ResultadoDeAnalise(identificador="REGRESSAO-1")
        r2 = ResultadoDeAnalise(identificador="REGRESSAO-2")
        # Coleções devem ser objetos independentes
        assert r1.entradas_por_aplicacao is not r2.entradas_por_aplicacao
        assert r1.linha_do_tempo is not r2.linha_do_tempo
        assert r1.erros is not r2.erros
        assert r1.mensagens is not r2.mensagens

    def test_campos_aditivos_fase2_existem_com_defaults(self) -> None:
        resultado = ResultadoDeAnalise(identificador="REGRESSAO-3")
        assert resultado.categoria_de_cenario is Categoria.NAO_CLASSIFICADA
        assert resultado.entradas_sem_ordenacao_temporal == []
        assert resultado.identificadores_extraidos == []
        assert resultado.vinculos == []
        assert resultado.correlacao is None
        assert resultado.evidencias == []
        assert resultado.regra_aplicada is None


# ===========================================================================
# Serialização
# ===========================================================================


class TestSerializacao:
    """Regressão da serialização de modelos legados e aditivos."""

    def test_serializar_entrada_legada(self) -> None:
        entrada = EntradaDeLog(
            texto_original="evento-reg-serialize",
            aplicacao="ORK",
            ordem_de_leitura=5,
            interpretada=True,
            carimbo_de_tempo=datetime(2031, 1, 2, 3, 4, 5),
            nivel_de_severidade="WARNING",
            mensagem="msg serialize",
        )
        resultado = serializar_entrada_de_log(entrada)
        assert isinstance(resultado, dict)
        assert resultado["texto_original"] == "evento-reg-serialize"
        assert resultado["aplicacao"] == "ORK"
        assert resultado["ordem_de_leitura"] == 5
        assert resultado["interpretada"] is True
        assert resultado["nivel_de_severidade"] == "WARNING"
        assert resultado["mensagem"] == "msg serialize"
        assert resultado["categoria"] == "não classificada"
        assert resultado["correlacionada"] is False
        # Datetime serializado como ISO
        assert "2031-01-02" in resultado["carimbo_de_tempo"]

    def test_serializar_resultado_legado(self) -> None:
        resultado = ResultadoDeAnalise(
            identificador="SER-REGRESSAO",
            correlacao_encontrada=True,
            mensagens=["detalhe"],
        )
        ser = serializar_resultado_de_analise(resultado)
        assert isinstance(ser, dict)
        assert ser["identificador"] == "SER-REGRESSAO"
        assert ser["correlacao_encontrada"] is True
        assert ser["mensagens"] == ["detalhe"]
        assert ser["entradas_por_aplicacao"] == {}
        assert ser["linha_do_tempo"] == []
        assert ser["contagem_por_categoria"] == {}
        assert ser["contagem_por_aplicacao"] == {}
        assert ser["erros"] == []

    def test_serializar_modelo_enum_usa_value(self) -> None:
        assert serializar_modelo(Categoria.SUCESSO) == "sucesso"
        assert serializar_modelo(Categoria.ERRO) == "erro"
        assert serializar_modelo(Categoria.NAO_CLASSIFICADA) == "não classificada"

    def test_serializar_modelo_datetime_usa_iso(self) -> None:
        instante = datetime(2042, 6, 7, 8, 9, 10, tzinfo=timezone.utc)
        assert serializar_modelo(instante) == instante.isoformat()

    def test_serializar_modelo_primitivos(self) -> None:
        assert serializar_modelo(None) is None
        assert serializar_modelo(True) is True
        assert serializar_modelo(42) == 42
        assert serializar_modelo(3.14) == 3.14
        assert serializar_modelo("txt") == "txt"

    def test_serializar_modelo_listas_e_dicts(self) -> None:
        assert serializar_modelo([1, "a"]) == [1, "a"]
        assert serializar_modelo({"chave": 10}) == {"chave": 10}

    def test_serializar_tipo_nao_suportado_gera_type_error(self) -> None:
        with pytest.raises(TypeError):
            serializar_modelo(object())


# ===========================================================================
# Wrappers públicos — carga
# ===========================================================================


class TestWrapperCargaRegressao:
    """Regressão do wrapper ``carregar_arquivo``."""

    def test_carrega_linhas_utf8(self, tmp_path: Path) -> None:
        arquivo = tmp_path / "carga_regressao.log"
        arquivo.write_bytes("alfa\r\nbeta\r\ngama ação".encode("utf-8"))
        resultado = carregar_arquivo(str(arquivo))
        assert resultado == ["alfa", "beta", "gama ação"]

    def test_arquivo_ausente_retorna_mensagem_de_erro(
        self, tmp_path: Path
    ) -> None:
        ausente = tmp_path / "nao_existe.log"
        resultado = carregar_arquivo(str(ausente))
        assert isinstance(resultado, MensagemDeErro)
        assert resultado.arquivo_ou_app == str(ausente)

    def test_preserva_assinatura_publica(self) -> None:
        sig = signature(carregar_arquivo)
        assert list(sig.parameters) == ["caminho"]
        assert sig.parameters["caminho"].kind is Parameter.POSITIONAL_OR_KEYWORD


# ===========================================================================
# Wrappers públicos — filtro
# ===========================================================================


class TestWrapperFiltroRegressao:
    """Regressão do wrapper ``filtrar_por_identificador``."""

    def test_filtra_por_substring_case_insensitive(self) -> None:
        e1 = EntradaDeLog("REGRESSAO-ID-FILTRO abc", "VPL", 0, False)
        e2 = EntradaDeLog("sem match", "ORK", 1, False)
        e3 = EntradaDeLog("regressao-id-filtro def", "VOCI", 2, False)
        resultado = filtrar_por_identificador([e1, e2, e3], "Regressao-Id-Filtro")
        assert resultado == [e1, e3]

    def test_nao_muta_entrada(self) -> None:
        e1 = EntradaDeLog("regressão xyz", "VPL", 0, False)
        entradas = [e1]
        copia = list(entradas)
        filtrar_por_identificador(entradas, "xyz")
        assert entradas == copia

    def test_preserva_assinatura_publica(self) -> None:
        sig = signature(filtrar_por_identificador)
        assert list(sig.parameters) == ["entradas", "identificador"]


# ===========================================================================
# Wrappers públicos — correlação
# ===========================================================================


class TestWrapperCorrelacaoRegressao:
    """Regressão do wrapper ``correlacionar_vpl_ork``."""

    def test_correlaciona_ambos_lados_presentes(self) -> None:
        vpl = EntradaDeLog("vpl reg evento", "VPL", 0, False)
        ork = EntradaDeLog("ork reg evento", "ORK", 0, False)
        vpl_out, ork_out, encontrada, erros = correlacionar_vpl_ork(
            [vpl], [ork], "ID-NAO-PRESENTE"
        )
        # Ambos lados presentes → correlação encontrada
        assert encontrada is True
        assert erros == []
        assert all(e.correlacionada for e in vpl_out + ork_out)

    def test_lado_ausente_reporta_erro(self) -> None:
        vpl = EntradaDeLog("vpl reg", "VPL", 0, False)
        _, _, encontrada, erros = correlacionar_vpl_ork(
            [vpl], [], "ID-REGRESSAO"
        )
        assert encontrada is False
        assert len(erros) == 1
        assert erros[0].arquivo_ou_app == "ORK"

    def test_preserva_assinatura_publica(self) -> None:
        sig = signature(correlacionar_vpl_ork)
        assert list(sig.parameters) == [
            "entradas_vpl", "entradas_ork", "identificador",
        ]
        for param in sig.parameters.values():
            assert param.kind is Parameter.POSITIONAL_OR_KEYWORD


# ===========================================================================
# Wrappers públicos — ordenação
# ===========================================================================


class TestWrapperOrdenacaoRegressao:
    """Regressão do wrapper ``ordenar_linha_do_tempo``."""

    def test_ordena_por_chave_total(self) -> None:
        t1 = datetime(2031, 1, 1, 10, 0, 0)
        t2 = datetime(2031, 1, 1, 10, 0, 1)
        e_posterior = EntradaDeLog("b", "VPL", 0, True, t2, "INFO", "b")
        e_anterior = EntradaDeLog("a", "ORK", 0, True, t1, "INFO", "a")
        resultado = ordenar_linha_do_tempo([e_posterior, e_anterior])
        assert resultado[0] is e_anterior
        assert resultado[1] is e_posterior

    def test_entradas_sem_tempo_ao_final(self) -> None:
        com_tempo = EntradaDeLog(
            "t", "VPL", 0, True, datetime(2031, 1, 1), "INFO", "t"
        )
        sem_tempo = EntradaDeLog("s", "ORK", 0, False)
        resultado = ordenar_linha_do_tempo([sem_tempo, com_tempo])
        assert resultado[0] is com_tempo
        assert resultado[1] is sem_tempo

    def test_nao_muta_entrada(self) -> None:
        entradas = [
            EntradaDeLog("x", "VPL", 0, True, datetime(2031, 1, 1), "INFO", "x"),
        ]
        copia = list(entradas)
        ordenar_linha_do_tempo(entradas)
        assert entradas == copia

    def test_preserva_assinatura_publica(self) -> None:
        sig = signature(ordenar_linha_do_tempo)
        assert list(sig.parameters) == ["entradas"]


# ===========================================================================
# Wrappers públicos — renderização
# ===========================================================================


class TestWrapperRenderizacaoRegressao:
    """Regressão do wrapper ``renderizar_resultado``."""

    def test_renderiza_resultado_legado_sem_entradas(self) -> None:
        resultado = ResultadoDeAnalise(
            identificador="RENDER-REGRESSAO-VAZIO",
            mensagens=["sem dados"],
        )
        saida = renderizar_resultado(resultado)
        assert "Resultado da análise para: RENDER-REGRESSAO-VAZIO" in saida
        assert "Nenhuma entrada encontrada" in saida

    def test_renderiza_resultado_legado_com_entradas(self) -> None:
        entrada = EntradaDeLog(
            "evento render regressão",
            "VPL",
            0,
            True,
            datetime(2031, 3, 4, 5, 6, 7),
            "INFO",
            "msg render",
            Categoria.NAO_CLASSIFICADA,
        )
        resultado = ResultadoDeAnalise(
            identificador="RENDER-REGRESSAO",
            entradas_por_aplicacao={"VPL": [entrada]},
            contagem_por_categoria={Categoria.NAO_CLASSIFICADA: 1},
            contagem_por_aplicacao={"VPL": 1},
        )
        saida = renderizar_resultado(resultado)
        assert "[VPL] (1 entradas)" in saida
        assert "Contagem por categoria:" in saida
        assert "Contagem por aplicação:" in saida

    def test_falha_de_entrada_invalida_retorna_mensagem_constante(self) -> None:
        saida = renderizar_resultado(None)  # type: ignore[arg-type]
        # Deve retornar mensagem de falha constante sem exceção propagada
        assert isinstance(saida, str)
        assert len(saida) > 0


# ===========================================================================
# CLI — argumentos posicionais e códigos de saída
# ===========================================================================


class TestCLIRegressao:
    """Regressão da sintaxe posicional e códigos de saída da CLI."""

    def _executar_cli(
        self, args: list[str]
    ) -> subprocess.CompletedProcess:
        ambiente = os.environ.copy()
        ambiente["PYTHONUTF8"] = "1"
        return subprocess.run(
            [sys.executable, "-m", "log_analyzer"] + args,
            cwd=_RAIZ_PROJETO,
            env=ambiente,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=30,
        )

    def test_uso_sem_argumentos_retorna_codigo_erro(self) -> None:
        resultado = self._executar_cli([])
        assert resultado.returncode == 1
        assert "Uso: python -m log_analyzer" in resultado.stdout

    def test_uso_com_um_argumento_retorna_codigo_erro(self) -> None:
        resultado = self._executar_cli(["apenas-id"])
        assert resultado.returncode == 1
        assert "Uso: python -m log_analyzer" in resultado.stdout

    def test_sintaxe_posicional_identificador_app_caminho(
        self, tmp_path: Path
    ) -> None:
        arquivo = tmp_path / "api_pub_regressao.log"
        arquivo.write_text(
            "2031-06-15 10:20:30\tINFO\tregressao-api-pub-id-001\n",
            encoding="utf-8",
        )
        resultado = self._executar_cli([
            "regressao-api-pub-id-001",
            f"VOCI:{arquivo}",
        ])
        assert resultado.returncode == 0
        assert "Traceback" not in resultado.stdout + resultado.stderr

    def test_multiplas_aplicacoes_na_mesma_invocacao(
        self, tmp_path: Path
    ) -> None:
        arq_vpl = tmp_path / "vpl_multi.log"
        arq_ork = tmp_path / "ork_multi.log"
        arq_vpl.write_text(
            "2031-06-15 10:20:30\tINFO\tregressao-multi-id\n",
            encoding="utf-8",
        )
        arq_ork.write_text(
            "2031-06-15 10:20:31\tINFO\tregressao-multi-id\n",
            encoding="utf-8",
        )
        resultado = self._executar_cli([
            "regressao-multi-id",
            f"VPL:{arq_vpl}",
            f"ORK:{arq_ork}",
        ])
        assert resultado.returncode == 0
        assert resultado.stderr == ""

    def test_identificador_invalido_retorna_codigo_erro(self) -> None:
        resultado = self._executar_cli([
            "",  # identificador vazio
            "VPL:inexistente.log",
        ])
        assert resultado.returncode == 1

    def test_arquivo_inexistente_retorna_sucesso_com_mensagem(
        self, tmp_path: Path
    ) -> None:
        inexistente = tmp_path / "fantasma.log"
        resultado = self._executar_cli([
            "regressao-fantasma",
            f"VOCI:{inexistente}",
        ])
        # O pipeline processa sem exceções mesmo sem arquivo válido
        assert resultado.returncode == 0
        assert "Traceback" not in resultado.stdout + resultado.stderr

    def test_saida_nao_contem_traceback_em_erro_generico(self) -> None:
        resultado = self._executar_cli([
            "   ",  # espaços apenas → identificador inválido
            "VPL:naoexiste.log",
        ])
        assert resultado.returncode == 1
        assert "Traceback" not in resultado.stdout + resultado.stderr

    def test_codigos_de_saida_conhecidos(self) -> None:
        from log_analyzer.cli.main import (
            CODIGO_SAIDA_ERRO,
            CODIGO_SAIDA_SUCESSO,
        )
        assert CODIGO_SAIDA_SUCESSO == 0
        assert CODIGO_SAIDA_ERRO == 1
