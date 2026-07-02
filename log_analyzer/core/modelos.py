"""Modelos de dados do domínio do Analisador de Logs.

Define as estruturas centrais usadas em todo o pipeline de análise:
- Categoria: classificação de uma entrada de log (sucesso, erro, não classificada)
- EntradaDeLog: representação imutável de uma linha/bloco de log
- ArquivoSelecionado: associação de um arquivo à sua aplicação
- MensagemDeErro: erro identificando o arquivo/aplicação afetado
- ResultadoDeAnalise: saída estruturada da análise

Invariantes:
- INV-1: se interpretada=True, então carimbo_de_tempo, nivel_de_severidade e mensagem
  são todos não nulos e não vazios.
- INV-2: texto_original nunca é descartado nem alterado.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Categoria(Enum):
    """Categorias de classificação de uma Entrada de Log (Req 5.3, 5.4, 6.6)."""

    SUCESSO = "sucesso"
    ERRO = "erro"
    NAO_CLASSIFICADA = "não classificada"


@dataclass(frozen=True)
class EntradaDeLog:
    """Representação imutável de uma entrada de log.

    Campos obrigatórios quando interpretada=True (INV-1):
    - carimbo_de_tempo: não pode ser None
    - nivel_de_severidade: não pode ser None nem vazio
    - mensagem: não pode ser None nem vazia

    O campo texto_original é sempre preservado (INV-2).
    """

    texto_original: str
    aplicacao: str
    ordem_de_leitura: int
    interpretada: bool
    carimbo_de_tempo: datetime | None = None
    nivel_de_severidade: str | None = None
    mensagem: str | None = None
    categoria: Categoria = Categoria.NAO_CLASSIFICADA
    correlacionada: bool = False

    def __post_init__(self) -> None:
        """Valida INV-1: campos obrigatórios quando interpretada=True."""
        if self.interpretada:
            if self.carimbo_de_tempo is None:
                raise ValueError(
                    "EntradaDeLog interpretada requer carimbo_de_tempo não nulo."
                )
            if not self.nivel_de_severidade:
                raise ValueError(
                    "EntradaDeLog interpretada requer nivel_de_severidade não nulo/não vazio."
                )
            if not self.mensagem:
                raise ValueError(
                    "EntradaDeLog interpretada requer mensagem não nula/não vazia."
                )


@dataclass
class ArquivoSelecionado:
    """Associação de um arquivo de log à sua aplicação.

    Se app_id for None, a aplicação não foi informada (Req 2.3).
    """

    caminho: str
    app_id: str | None


@dataclass
class MensagemDeErro:
    """Mensagem de erro identificando o arquivo ou aplicação afetado."""

    arquivo_ou_app: str
    descricao: str


@dataclass
class ResultadoDeAnalise:
    """Saída estruturada produzida pelo Analisador de Logs.

    Contém as entradas selecionadas agrupadas por aplicação, a linha do tempo
    ordenada, contagens e erros acumulados.
    """

    identificador: str
    entradas_por_aplicacao: dict[str, list[EntradaDeLog]] = field(
        default_factory=dict
    )
    linha_do_tempo: list[EntradaDeLog] = field(default_factory=list)
    contagem_por_categoria: dict[Categoria, int] = field(default_factory=dict)
    contagem_por_aplicacao: dict[str, int] = field(default_factory=dict)
    correlacao_encontrada: bool = False
    erros: list[MensagemDeErro] = field(default_factory=list)
    mensagens: list[str] = field(default_factory=list)
