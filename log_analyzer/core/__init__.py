"""Núcleo do Analisador de Logs — modelos, interfaces e orquestração."""

from log_analyzer.core.agrupamento import agrupar_por_aplicacao
from log_analyzer.core.analisador import Analisador_de_Logs
from log_analyzer.core.bootstrap import criar_registro_padrao
from log_analyzer.core.contagens import calcular_contagens
from log_analyzer.core.correlacao import correlacionar_vpl_ork
from log_analyzer.core.excecoes import (
    ErroDoAnalisador,
    ErroDeArquivo,
    ErroDeIdentificador,
    ErroDeRegistro,
)
from log_analyzer.core.filtro import filtrar_por_identificador
from log_analyzer.core.modelos import (
    ArquivoSelecionado,
    Categoria,
    EntradaDeLog,
    MensagemDeErro,
    ResultadoDeAnalise,
)
from log_analyzer.core.interfaces import Padrao_de_Analise, Parser_de_Aplicacao
from log_analyzer.core.registro import Registro_de_Aplicacoes
from log_analyzer.core.carregador import carregar_arquivo, TAMANHO_MAXIMO_BYTES
from log_analyzer.core.ordenacao import ordenar_linha_do_tempo
from log_analyzer.core.validacao import validar_identificador

__all__ = [
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
]
