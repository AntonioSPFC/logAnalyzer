"""Núcleo do Analisador de Logs — modelos, interfaces e orquestração."""

from log_analyzer.core.agrupamento import agrupar_por_aplicacao
from log_analyzer.core.analisador import Analisador_de_Logs
from log_analyzer.core.bootstrap import criar_registro_padrao
from log_analyzer.core.contagens import calcular_contagens
from log_analyzer.core.composicao import compor_resultado_fase2
from log_analyzer.core.correlacao import correlacionar_vpl_ork
from log_analyzer.core.excecoes import (
    ErroDeArquivo,
    ErroDeCatalogo,
    ErroDeDecodificacao,
    ErroDeIdentificador,
    ErroDeIntegridadeDaFonte,
    ErroDeRegistro,
    ErroDeSanitizacao,
    ErroDoAnalisador,
    ErroTemporal,
)
from log_analyzer.core.filtro import filtrar_por_identificador
from log_analyzer.core.modelos import (
    ArquivoSelecionado,
    BaseCorrelacao,
    CampoEstruturado,
    Categoria,
    EntradaDeLog,
    EntradaIndexada,
    EstadoCausaRaiz,
    EstadoSanitizacao,
    Evidencia,
    FalhaDeEntrada,
    IdentificadorTecnico,
    MensagemDeErro,
    Proveniencia,
    ReferenciaRegra,
    ReferenciaTextoOriginal,
    ResultadoCausaRaiz,
    ResultadoCorrelacao,
    ResultadoDeAnalise,
    TipoIdentificador,
    VinculoIdentificadores,
)
from log_analyzer.core.interfaces import (
    Padrao_de_Analise,
    Parser_de_Aplicacao,
    Parser_de_Bloco,
    TipoInicio,
)
from log_analyzer.core.registro import Registro_de_Aplicacoes
from log_analyzer.core.carregador import carregar_arquivo, TAMANHO_MAXIMO_BYTES
from log_analyzer.core.ordenacao import ordenar_linha_do_tempo
from log_analyzer.core.pipeline_fase2 import (
    PipelineFase2,
    PipelineStreamingFase2,
    executar_pipeline_fase2,
)
from log_analyzer.core.serializacao import (
    serializar_entrada_de_log,
    serializar_modelo,
    serializar_resultado_de_analise,
)
from log_analyzer.core.validacao import validar_identificador
from log_analyzer.core.validacao_catalogo import (
    AvaliacaoExemploRegra,
    CodigoValidacaoCatalogo,
    CoberturaDeCondicao,
    ExemploRotuladoCatalogo,
    ManifestoAtivacaoRegra,
    PacoteValidacaoCatalogo,
    PoliticaDeAmostras,
    ReferenciaVersaoRegra,
    ResultadoValidacaoCatalogo,
    ValidadorCatalogo,
    validar_catalogo_para_publicacao,
)
from log_analyzer.core.observabilidade import (
    LABELS_METRICAS_PERMITIDOS,
    LABELS_PROIBIDOS,
    ObservabilidadeSegura,
    registrar_evento_seguro,
    validar_labels,
    validar_labels_metricas,
)
from log_analyzer.core.visao_segura import (
    SanitizadorDeResultado,
    ScannerFinalDeResultado,
    criar_visao_segura,
)

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
]
