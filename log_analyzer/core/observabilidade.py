"""Observabilidade segura do Analisador de Logs — Fase 2.

Este módulo expõe métricas (contagem, duração e código) e logs estruturados
que respeitam as fronteiras de confiança do sistema. Labels e campos são
governados por conjuntos explícitos de permissão e proibição. Dados brutos,
caminhos, IDs de negócio, UUIDs, telefones, documentos, IPs, hosts, URLs,
credenciais, mensagens de log e evidências jamais podem aparecer em labels
de métricas ou em campos de eventos de observabilidade, mesmo em nível debug.

Falhas são registradas exclusivamente por códigos constantes.

Requirements: 13.3, 14.1, 14.7, 16.4
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any


# ---------------------------------------------------------------------------
# Labels permitidos e proibidos para métricas
# ---------------------------------------------------------------------------

LABELS_METRICAS_PERMITIDOS: frozenset[str] = frozenset(
    {
        "analysis_id",
        "arquivo_token",
        "aplicacao",
        "app",
        "posicao",
        "codigo",
        "etapa",
        "resultado",
        "operacao",
        "categoria",
        "mecanismo",
        "tipo",
        "versao_catalogo",
    }
)

LABELS_PROIBIDOS: frozenset[str] = frozenset(
    {
        "caminho",
        "path",
        "filepath",
        "arquivo",
        "id_negocio",
        "business_id",
        "uuid",
        "telefone",
        "phone",
        "documento",
        "document",
        "cpf",
        "cnpj",
        "ip",
        "ip_address",
        "host",
        "hostname",
        "url",
        "uri",
        "endpoint",
        "credencial",
        "credential",
        "token",
        "secret",
        "senha",
        "password",
        "mensagem",
        "message",
        "msg",
        "texto",
        "text",
        "conteudo",
        "content",
        "evidencia",
        "evidence",
        "valor",
        "value",
        "dado",
        "data",
        "texto_original",
        "raw",
        "corpo",
        "body",
        "payload",
        "call_id",
        "identificador",
        "identifier",
    }
)

# Padrão para validar formato de label (alfanumérico + underscore, sem iniciar com dígito)
_PADRAO_LABEL = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")

# Logger dedicado — nunca propaga conteúdo bruto
_logger = logging.getLogger("log_analyzer.observabilidade")


# ---------------------------------------------------------------------------
# Validação de labels
# ---------------------------------------------------------------------------


def validar_labels(labels: dict[str, Any]) -> None:
    """Valida um dicionário de labels para uso em eventos de observabilidade.

    Rejeita com ``ValueError`` se qualquer chave estiver em ``LABELS_PROIBIDOS``
    ou se qualquer chave não obedecer ao formato seguro (lowercase, sem dados
    sensíveis).

    Args:
        labels: Dicionário com chaves sendo nomes de labels e valores associados.

    Raises:
        ValueError: Se algum label for proibido ou inválido.
    """
    if not isinstance(labels, dict):
        raise ValueError("Labels devem ser um dicionário.")

    for chave in labels:
        if not isinstance(chave, str):
            raise ValueError("Chave de label deve ser string.")

        chave_lower = chave.lower()

        if chave_lower in LABELS_PROIBIDOS:
            raise ValueError(
                f"Label proibido detectado: uso de label em LABELS_PROIBIDOS não é permitido."
            )

        if _PADRAO_LABEL.fullmatch(chave_lower) is None:
            raise ValueError(
                "Label com formato inválido: somente letras minúsculas, dígitos e underscore são permitidos."
            )


def validar_labels_metricas(labels: dict[str, Any]) -> None:
    """Valida labels especificamente para uso em métricas.

    Além das regras de ``validar_labels``, exige que todas as chaves estejam
    no conjunto ``LABELS_METRICAS_PERMITIDOS``.

    Args:
        labels: Dicionário com chaves sendo nomes de labels de métricas.

    Raises:
        ValueError: Se algum label for proibido, inválido ou não estiver na
            lista de permitidos para métricas.
    """
    # Primeiro aplica validação geral (proibidos e formato)
    validar_labels(labels)

    for chave in labels:
        chave_lower = chave.lower()
        if chave_lower not in LABELS_METRICAS_PERMITIDOS:
            raise ValueError(
                f"Label não permitido para métricas: somente labels em LABELS_METRICAS_PERMITIDOS são aceitos."
            )


# ---------------------------------------------------------------------------
# Classe de observabilidade segura
# ---------------------------------------------------------------------------


class ObservabilidadeSegura:
    """Componente de observabilidade que garante ausência de dados sensíveis.

    Expõe métricas de contagem, duração e código, além de logs estruturados.
    Toda emissão passa por validação de labels/campos antes de ser registrada.
    Nível debug jamais habilita conteúdo bruto. Falhas registram somente
    códigos constantes.
    """

    def __init__(
        self,
        analysis_id: str | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        """Cria instância vinculada a uma análise específica.

        Args:
            analysis_id: Identificador opaco da análise corrente (pode ser None
                para contextos de inicialização).
            logger: Logger externo para emitir eventos. Se None, usa o logger
                interno do módulo.
        """
        self._analysis_id = analysis_id
        self._logger = logger or _logger
        self._contadores: dict[str, int] = {}
        self._duracoes: dict[str, list[float]] = {}

    @property
    def analysis_id(self) -> str | None:
        return self._analysis_id

    # ------------------------------------------------------------------
    # Métricas
    # ------------------------------------------------------------------

    def registrar_contagem(self, nome: str, labels: dict[str, Any] | None = None, valor: int = 1) -> None:
        """Registra uma métrica de contagem com labels validados.

        Args:
            nome: Nome da métrica (ex: ``entradas_processadas``).
            labels: Labels opcionais para a métrica.
            valor: Incremento (default 1).

        Raises:
            ValueError: Se labels contiverem chaves proibidas.
        """
        if labels:
            validar_labels_metricas(labels)

        chave = self._chave_metrica(nome, labels)
        self._contadores[chave] = self._contadores.get(chave, 0) + valor

    def registrar_duracao(self, nome: str, duracao_s: float, labels: dict[str, Any] | None = None) -> None:
        """Registra uma métrica de duração em segundos.

        Args:
            nome: Nome da métrica (ex: ``tempo_parsing``).
            duracao_s: Duração em segundos.
            labels: Labels opcionais para a métrica.

        Raises:
            ValueError: Se labels contiverem chaves proibidas.
        """
        if labels:
            validar_labels_metricas(labels)

        chave = self._chave_metrica(nome, labels)
        if chave not in self._duracoes:
            self._duracoes[chave] = []
        self._duracoes[chave].append(duracao_s)

    def registrar_codigo(self, codigo: str, labels: dict[str, Any] | None = None) -> None:
        """Registra uma ocorrência de código de erro/resultado.

        O código deve seguir o padrão seguro: letras maiúsculas, dígitos e
        underscore, sem dados brutos.

        Args:
            codigo: Código constante (ex: ``DECODE_ERROR``).
            labels: Labels opcionais para a métrica.

        Raises:
            ValueError: Se o código ou labels forem inválidos.
        """
        if not isinstance(codigo, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", codigo):
            raise ValueError("Código de observabilidade deve ser constante alfanumérico maiúsculo.")

        if labels:
            validar_labels_metricas(labels)

        chave = self._chave_metrica(f"codigo_{codigo}", labels)
        self._contadores[chave] = self._contadores.get(chave, 0) + 1

    # ------------------------------------------------------------------
    # Logs estruturados seguros
    # ------------------------------------------------------------------

    def registrar_evento_seguro(
        self,
        evento: str | None = None,
        *,
        analysis_id: str | None = None,
        arquivo_token: str | None = None,
        aplicacao: str | None = None,
        app: str | None = None,
        posicao: int | None = None,
        codigo: str | None = None,
        nivel: int | None = None,
        extra: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Registra um evento de observabilidade com campos seguros.

        Somente campos permitidos podem ser emitidos: ``analysis_id``,
        ``arquivo_token``, ``aplicacao``/``app``, ``posicao`` e ``codigo``.
        Campos extras são validados contra labels proibidos.

        Nível debug NUNCA habilita conteúdo bruto. Qualquer tentativa de
        passar campos proibidos resulta em ``ValueError``.

        Args:
            evento: Nome constante do evento (sem dados brutos).
            analysis_id: Identificador opaco da análise.
            arquivo_token: Token do arquivo (ex: ``<ARQUIVO_1>``).
            aplicacao: Nome da aplicação (VPL, ORK, VOCI).
            app: Alias para aplicacao.
            posicao: Posição numérica segura.
            codigo: Código de erro/resultado constante.
            nivel: Nível de logging (não altera o que pode ser emitido).
            extra: Labels adicionais (validados contra proibidos).
            **kwargs: Campos adicionais validados contra proibidos.

        Raises:
            ValueError: Se qualquer campo for proibido ou inválido.
        """
        # Rejeitar qualquer campo proibido nos kwargs
        all_extra = dict(kwargs)
        if extra:
            all_extra.update(extra)

        if all_extra:
            validar_labels(all_extra)

        # Construir dicionário de campos seguros para o log
        campos: dict[str, Any] = {}
        if evento is not None:
            campos["evento"] = evento

        resolved_analysis_id = analysis_id or self._analysis_id
        if resolved_analysis_id is not None:
            campos["analysis_id"] = resolved_analysis_id

        if arquivo_token is not None:
            campos["arquivo_token"] = arquivo_token

        resolved_app = aplicacao or app
        if resolved_app is not None:
            campos["app"] = resolved_app

        if posicao is not None:
            if isinstance(posicao, bool) or not isinstance(posicao, int) or posicao < 0:
                raise ValueError("Posição deve ser inteiro não negativo.")
            campos["posicao"] = posicao

        if codigo is not None:
            if not isinstance(codigo, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", codigo):
                raise ValueError("Código deve ser constante alfanumérico maiúsculo.")
            campos["codigo"] = codigo

        if all_extra:
            campos.update(all_extra)

        log_level = nivel if nivel is not None else logging.INFO
        self._logger.log(log_level, "%s", campos)

    # Aliases for registrar_evento_seguro
    registrar_evento = registrar_evento_seguro
    registrar_log = registrar_evento_seguro

    def registrar_falha_segura(
        self,
        codigo: str,
        *,
        arquivo_token: str | None = None,
        aplicacao: str | None = None,
        posicao: int | None = None,
    ) -> None:
        """Registra uma falha usando exclusivamente um código constante.

        Nenhuma mensagem, dado bruto ou stacktrace é emitido. Somente o código
        e metadados seguros de localização são registrados.

        Args:
            codigo: Código constante da falha.
            arquivo_token: Token opaco do arquivo onde ocorreu.
            aplicacao: Nome da aplicação.
            posicao: Posição numérica no arquivo.

        Raises:
            ValueError: Se o código for inválido.
        """
        if not isinstance(codigo, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", codigo):
            raise ValueError("Código de falha deve ser constante alfanumérico maiúsculo.")

        self.registrar_evento_seguro(
            "FALHA",
            codigo=codigo,
            arquivo_token=arquivo_token,
            aplicacao=aplicacao,
            posicao=posicao,
        )

    # ------------------------------------------------------------------
    # Context manager para medição de duração
    # ------------------------------------------------------------------

    class _MedidorDuracao:
        """Context manager para medir duração de uma operação."""

        def __init__(self, obs: "ObservabilidadeSegura", nome: str, labels: dict[str, Any] | None) -> None:
            self._obs = obs
            self._nome = nome
            self._labels = labels
            self._inicio: float = 0.0

        def __enter__(self) -> "ObservabilidadeSegura._MedidorDuracao":
            self._inicio = time.perf_counter()
            return self

        def __exit__(self, *_: Any) -> None:
            duracao = time.perf_counter() - self._inicio
            self._obs.registrar_duracao(self._nome, duracao, self._labels)

    def medir_duracao(self, nome: str, labels: dict[str, Any] | None = None) -> _MedidorDuracao:
        """Retorna context manager que mede e registra a duração de um bloco.

        Args:
            nome: Nome da métrica de duração.
            labels: Labels opcionais (validados ao registrar).

        Returns:
            Context manager que registra a duração ao sair.
        """
        return self._MedidorDuracao(self, nome, labels)

    # ------------------------------------------------------------------
    # Utilitários internos
    # ------------------------------------------------------------------

    @staticmethod
    def _chave_metrica(nome: str, labels: dict[str, Any] | None) -> str:
        """Cria chave composta para armazenamento interno de métricas."""
        if not labels:
            return nome
        partes = sorted(f"{k}={v}" for k, v in labels.items())
        return f"{nome}|{'|'.join(partes)}"

    def obter_contadores(self) -> dict[str, int]:
        """Retorna cópia dos contadores acumulados (para testes)."""
        return dict(self._contadores)

    def obter_duracoes(self) -> dict[str, list[float]]:
        """Retorna cópia das durações acumuladas (para testes)."""
        return {k: list(v) for k, v in self._duracoes.items()}


# ---------------------------------------------------------------------------
# Função de conveniência para eventos avulsos
# ---------------------------------------------------------------------------


def registrar_evento_seguro(
    evento: str | None = None,
    *,
    logger: logging.Logger | None = None,
    analysis_id: str | None = None,
    arquivo_token: str | None = None,
    aplicacao: str | None = None,
    app: str | None = None,
    posicao: int | None = None,
    codigo: str | None = None,
    nivel: int | None = None,
    extra: dict[str, Any] | None = None,
    **kwargs: Any,
) -> None:
    """Função de conveniência para registrar evento seguro sem instanciar classe.

    Mesma semântica de ``ObservabilidadeSegura.registrar_evento_seguro``.

    Args:
        evento: Nome constante do evento.
        logger: Logger externo (opcional).
        analysis_id: Identificador opaco da análise.
        arquivo_token: Token do arquivo.
        aplicacao: Nome da aplicação.
        app: Alias para aplicacao.
        posicao: Posição numérica segura.
        codigo: Código de erro/resultado constante.
        nivel: Nível de logging.
        extra: Labels adicionais.
        **kwargs: Campos adicionais validados contra proibidos.

    Raises:
        ValueError: Se qualquer campo for proibido ou inválido.
    """
    obs = ObservabilidadeSegura(analysis_id=analysis_id, logger=logger)
    obs.registrar_evento_seguro(
        evento,
        analysis_id=analysis_id,
        arquivo_token=arquivo_token,
        aplicacao=aplicacao,
        app=app,
        posicao=posicao,
        codigo=codigo,
        nivel=nivel,
        extra=extra,
        **kwargs,
    )
