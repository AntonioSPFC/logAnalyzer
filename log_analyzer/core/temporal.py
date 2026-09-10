"""Normalização temporal segura dos perfis VPL e ORK.

O serviço produz somente os metadados aditivos da Fase 2. Em particular, ele
não altera ``EntradaDeLog.carimbo_de_tempo``: consumidores podem anexar o
resultado a uma entrada preservando integralmente o campo legado.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from log_analyzer.core.modelos import FalhaDeEntrada, Proveniencia


_PADRAO_VPL = re.compile(
    r"(?P<data>\d{4}-\d{2}-\d{2}) "
    r"(?P<hora>\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<fracao>\d+))?\Z"
)
_PADRAO_ORK = re.compile(
    r"(?P<data>\d{4}-\d{2}-\d{2})[T ]"
    r"(?P<hora>\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<fracao>\d+))?"
    r"(?P<offset>Z|[+-]\d{2}:\d{2})\Z"
)
_PADRAO_ORK_SEM_OFFSET = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?\Z"
)


@dataclass(frozen=True)
class ResultadoNormalizacaoTemporal:
    """Resultado total da resolução de um ``Timestamp_Original``.

    Uma resolução válida possui ``timestamp_normalizado`` em UTC e nenhuma
    falha. Uma resolução inválida preserva o texto original, não fornece um
    instante parcial e contém exatamente uma falha segura associada à
    proveniência recebida.
    """

    timestamp_original: str
    timestamp_normalizado: datetime | None
    precisao_fracionaria: int | None
    falhas: tuple[FalhaDeEntrada, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.timestamp_original, str):
            raise TypeError("timestamp_original deve ser string.")
        if self.precisao_fracionaria is not None and (
            isinstance(self.precisao_fracionaria, bool)
            or not isinstance(self.precisao_fracionaria, int)
            or not 0 <= self.precisao_fracionaria <= 6
        ):
            raise ValueError("precisao_fracionaria deve estar entre 0 e 6.")
        if not isinstance(self.falhas, tuple) or not all(
            isinstance(falha, FalhaDeEntrada) for falha in self.falhas
        ):
            raise TypeError("falhas deve ser uma tupla de FalhaDeEntrada.")

        if self.timestamp_normalizado is None:
            if len(self.falhas) != 1:
                raise ValueError(
                    "normalização sem instante requer exatamente uma falha."
                )
            return

        if not isinstance(self.timestamp_normalizado, datetime):
            raise TypeError("timestamp_normalizado deve ser datetime ou None.")
        if (
            self.timestamp_normalizado.tzinfo is None
            or self.timestamp_normalizado.utcoffset() != timedelta(0)
        ):
            raise ValueError("timestamp_normalizado deve estar em UTC.")
        if self.precisao_fracionaria is None:
            raise ValueError(
                "normalização válida requer precisao_fracionaria preservada."
            )
        if self.falhas:
            raise ValueError("normalização válida não pode conter falhas.")

    @property
    def resolvido(self) -> bool:
        """Indica se um instante UTC foi obtido sem escolha silenciosa."""

        return self.timestamp_normalizado is not None

    @property
    def sucesso(self) -> bool:
        """Alias legível de :attr:`resolvido`."""

        return self.resolvido

    @property
    def falha(self) -> FalhaDeEntrada | None:
        """Retorna a falha única, quando a resolução não foi possível."""

        return self.falhas[0] if self.falhas else None

    def formatar_timestamp_normalizado(self) -> str | None:
        """Representa o UTC com a mesma precisão fracionária da origem."""

        if self.timestamp_normalizado is None:
            return None

        precisao = self.precisao_fracionaria
        if precisao is None:  # Proteção para analisadores de tipo.
            return None

        base = self.timestamp_normalizado.strftime("%Y-%m-%dT%H:%M:%S")
        if precisao:
            fracao = f"{self.timestamp_normalizado.microsecond:06d}"[:precisao]
            base = f"{base}.{fracao}"
        return f"{base}+00:00"

    @property
    def timestamp_normalizado_texto(self) -> str | None:
        """Forma textual UTC com precisão preservada."""

        return self.formatar_timestamp_normalizado()


class NormalizadorTemporal:
    """Normaliza timestamps conforme as regras temporais de cada aplicação."""

    FUSO_HORARIO_VPL = "America/Sao_Paulo"

    CODIGO_TIMESTAMP_INVALIDO = "TEMPORAL_TIMESTAMP_INVALIDO"
    CODIGO_PRECISAO_NAO_SUPORTADA = "TEMPORAL_PRECISAO_NAO_SUPORTADA"
    CODIGO_HORARIO_INEXISTENTE = "TEMPORAL_HORARIO_INEXISTENTE"
    CODIGO_HORARIO_AMBIGUO = "TEMPORAL_HORARIO_AMBIGUO"
    CODIGO_OFFSET_AUSENTE = "TEMPORAL_OFFSET_AUSENTE"
    CODIGO_PERFIL_NAO_SUPORTADO = "TEMPORAL_PERFIL_NAO_SUPORTADO"

    def __init__(self) -> None:
        self._fuso_vpl = ZoneInfo(self.FUSO_HORARIO_VPL)

    @property
    def fuso_vpl(self) -> ZoneInfo:
        """Zona IANA normativa usada para timestamps locais do VPL."""

        return self._fuso_vpl

    def normalizar(
        self,
        aplicacao: str,
        timestamp_original: str,
        proveniencia: Proveniencia,
    ) -> ResultadoNormalizacaoTemporal:
        """Despacha a normalização pelo ID de aplicação VPL ou ORK."""

        self._validar_argumentos(timestamp_original, proveniencia)
        if isinstance(aplicacao, str):
            perfil = aplicacao.casefold()
            if perfil == "vpl":
                return self.normalizar_vpl(timestamp_original, proveniencia)
            if perfil == "ork":
                return self.normalizar_ork(timestamp_original, proveniencia)

        return self._falhar(
            timestamp_original,
            proveniencia,
            codigo=self.CODIGO_PERFIL_NAO_SUPORTADO,
            detalhe="Perfil temporal não suportado.",
        )

    def normalizar_vpl(
        self,
        timestamp_original: str,
        proveniencia: Proveniencia,
    ) -> ResultadoNormalizacaoTemporal:
        """Resolve um timestamp local VPL em ``America/Sao_Paulo``.

        Os dois valores de ``fold`` são testados por ida e volta via UTC. Zero
        candidatos válidos identifica um horário inexistente; dois instantes
        UTC distintos identificam um horário ambíguo. Nenhum dos casos escolhe
        um instante arbitrariamente.
        """

        self._validar_argumentos(timestamp_original, proveniencia)
        correspondencia = _PADRAO_VPL.fullmatch(timestamp_original)
        if correspondencia is None:
            return self._falhar(
                timestamp_original,
                proveniencia,
                codigo=self.CODIGO_TIMESTAMP_INVALIDO,
                detalhe="Timestamp inválido para o perfil VPL.",
            )

        precisao = self._precisao(correspondencia)
        if precisao > 6:
            return self._falhar(
                timestamp_original,
                proveniencia,
                codigo=self.CODIGO_PRECISAO_NAO_SUPORTADA,
                detalhe="Precisão fracionária não suportada.",
            )

        try:
            local_sem_fuso = datetime.fromisoformat(timestamp_original)
        except ValueError:
            return self._falhar(
                timestamp_original,
                proveniencia,
                codigo=self.CODIGO_TIMESTAMP_INVALIDO,
                detalhe="Timestamp inválido para o perfil VPL.",
                precisao=precisao,
            )

        candidatos = self._candidatos_vpl(local_sem_fuso)
        if not candidatos:
            return self._falhar(
                timestamp_original,
                proveniencia,
                codigo=self.CODIGO_HORARIO_INEXISTENTE,
                detalhe="Horário local inexistente no fuso VPL.",
                precisao=precisao,
            )
        if len(candidatos) > 1:
            return self._falhar(
                timestamp_original,
                proveniencia,
                codigo=self.CODIGO_HORARIO_AMBIGUO,
                detalhe="Horário local ambíguo no fuso VPL.",
                precisao=precisao,
            )

        return ResultadoNormalizacaoTemporal(
            timestamp_original=timestamp_original,
            timestamp_normalizado=candidatos[0],
            precisao_fracionaria=precisao,
        )

    def normalizar_ork(
        self,
        timestamp_original: str,
        proveniencia: Proveniencia,
    ) -> ResultadoNormalizacaoTemporal:
        """Converte para UTC um timestamp ORK com offset explícito."""

        self._validar_argumentos(timestamp_original, proveniencia)
        correspondencia = _PADRAO_ORK.fullmatch(timestamp_original)
        if correspondencia is None:
            if _PADRAO_ORK_SEM_OFFSET.fullmatch(timestamp_original) is not None:
                return self._falhar(
                    timestamp_original,
                    proveniencia,
                    codigo=self.CODIGO_OFFSET_AUSENTE,
                    detalhe="Timestamp ORK requer offset explícito.",
                )
            return self._falhar(
                timestamp_original,
                proveniencia,
                codigo=self.CODIGO_TIMESTAMP_INVALIDO,
                detalhe="Timestamp inválido para o perfil ORK.",
            )

        precisao = self._precisao(correspondencia)
        if precisao > 6:
            return self._falhar(
                timestamp_original,
                proveniencia,
                codigo=self.CODIGO_PRECISAO_NAO_SUPORTADA,
                detalhe="Precisão fracionária não suportada.",
            )

        texto_para_parse = (
            f"{timestamp_original[:-1]}+00:00"
            if timestamp_original.endswith("Z")
            else timestamp_original
        )
        try:
            instante_com_offset = datetime.fromisoformat(texto_para_parse)
        except ValueError:
            return self._falhar(
                timestamp_original,
                proveniencia,
                codigo=self.CODIGO_TIMESTAMP_INVALIDO,
                detalhe="Timestamp inválido para o perfil ORK.",
                precisao=precisao,
            )

        if (
            instante_com_offset.tzinfo is None
            or instante_com_offset.utcoffset() is None
        ):
            return self._falhar(
                timestamp_original,
                proveniencia,
                codigo=self.CODIGO_OFFSET_AUSENTE,
                detalhe="Timestamp ORK requer offset explícito.",
                precisao=precisao,
            )

        return ResultadoNormalizacaoTemporal(
            timestamp_original=timestamp_original,
            timestamp_normalizado=instante_com_offset.astimezone(timezone.utc),
            precisao_fracionaria=precisao,
        )

    def _candidatos_vpl(self, local_sem_fuso: datetime) -> tuple[datetime, ...]:
        candidatos: dict[datetime, None] = {}
        for fold in (0, 1):
            local_com_fuso = local_sem_fuso.replace(
                tzinfo=self._fuso_vpl,
                fold=fold,
            )
            instante_utc = local_com_fuso.astimezone(timezone.utc)
            volta = instante_utc.astimezone(self._fuso_vpl)
            if (
                volta.replace(tzinfo=None) == local_sem_fuso
                and volta.fold == fold
            ):
                candidatos[instante_utc] = None
        return tuple(sorted(candidatos))

    @staticmethod
    def _precisao(correspondencia: re.Match[str]) -> int:
        fracao = correspondencia.group("fracao")
        return len(fracao) if fracao is not None else 0

    @staticmethod
    def _validar_argumentos(
        timestamp_original: str,
        proveniencia: Proveniencia,
    ) -> None:
        if not isinstance(timestamp_original, str):
            raise TypeError("timestamp_original deve ser string.")
        if not isinstance(proveniencia, Proveniencia):
            raise TypeError("proveniencia deve ser Proveniencia.")

    @staticmethod
    def _falhar(
        timestamp_original: str,
        proveniencia: Proveniencia,
        *,
        codigo: str,
        detalhe: str,
        precisao: int | None = None,
    ) -> ResultadoNormalizacaoTemporal:
        precisao_suportada = precisao if precisao is not None and precisao <= 6 else None
        return ResultadoNormalizacaoTemporal(
            timestamp_original=timestamp_original,
            timestamp_normalizado=None,
            precisao_fracionaria=precisao_suportada,
            falhas=(
                FalhaDeEntrada(
                    codigo=codigo,
                    proveniencia=proveniencia,
                    detalhe_seguro=detalhe,
                ),
            ),
        )
