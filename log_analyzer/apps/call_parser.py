"""Call log parser data models for the Call Analysis Dashboard.

Defines immutable data structures used to represent parsed call data from
olos-ai-orchestrator syslog files. All dataclasses are frozen to ensure
thread safety and predictable behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

__all__ = [
    "EventType",
    "Speaker",
    "CallEvent",
    "ConversationMessage",
    "AIModelInfo",
    "SessionSummary",
    "AudioRepetition",
    "TurnoAda",
    "CallData",
    "CallLogParser",
]


class EventType(Enum):
    """Types of events that can occur during a call session."""

    STAGE_TRANSITION = "stage_transition"
    ASR_TRANSCRIPTION = "asr_transcription"
    BOT_RESPONSE = "bot_response"
    CATEGORIZER_DECISION = "categorizer_decision"
    TTS_GENERATION = "tts_generation"
    TOOL_CALL = "tool_call"
    STAGING_DECISION = "staging_decision"
    FINALIZE_DECISION = "finalize_decision"
    BARGE_IN = "barge_in"
    FILLER = "filler"
    VOICE_DETECTION = "voice_detection"
    ERROR = "error"
    OTHER = "other"


class Speaker(Enum):
    """Identifies the speaker in a conversation message."""

    CUSTOMER = "customer"
    ASSISTANT = "assistant"


@dataclass(frozen=True)
class CallEvent:
    """A single event in the call timeline."""

    timestamp: datetime
    event_type: EventType
    content: str
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ConversationMessage:
    """A single message in the call conversation."""

    timestamp: datetime
    speaker: Speaker
    text: str
    # Short name of the LLM-decided stage in effect when an assistant message
    # was produced. Added last with a default so existing positional
    # construction (timestamp, speaker, text) keeps working. None for customer
    # messages and for flows without stage tracking (e.g. VPL).
    stage: str | None = None


@dataclass(frozen=True)
class AIModelInfo:
    """Information about an AI model used during the call."""

    ai_type: str
    model_name: str


@dataclass(frozen=True)
class SessionSummary:
    """Aggregated session metrics from the session summary log entry."""

    llm_calls: int
    llm_tokens_input: int
    llm_tokens_output: int
    llm_tokens_cached: int
    llm_cost: float
    tts_calls: int
    tts_characters: int
    tts_chunks: int
    tts_bytes: int
    asr_calls: int
    asr_duration_seconds: float
    asr_characters: int
    categorizer_calls: int


@dataclass(frozen=True)
class AudioRepetition:
    """Represents an audio repetition event detected during the call."""

    timestamp: datetime
    repetition_count: int


@dataclass(frozen=True)
class TurnoAda:
    """A single ADA conversation turn extracted from a VPL ``[AFTER]`` block.

    Each turn corresponds to one ``targetContact.ada [AFTER]: {JSON}`` log line
    and captures the customer's transcription, the assistant's response and the
    decision metadata (system/model/stage/hangup) reported by the ADA engine.
    """

    timestamp: datetime | None
    asr: str
    asr_confidence: float | None
    ai_system: str
    ai_model: str
    assistant_text: str
    stage: str
    hangup: bool


@dataclass(frozen=True)
class CallData:
    """Immutable result of parsing a call's log entries.

    Contains all structured data extracted from olos-ai-orchestrator log files
    for a single call session identified by call_id.
    """

    call_id: str
    # Customer data
    customer_name: str | None
    cpf: str | None
    phone: str | None
    product: str | None
    company: str | None
    # Debt data
    debt_total: str | None
    debt_discount: str | None
    debt_due_date: str | None
    days_overdue: str | None
    installments_overdue: str | None
    # Call configuration
    assistant_name: str | None
    tts_supplier: str | None
    tts_voice: str | None
    tts_voice_id: str | None
    tts_model_id: str | None
    vpl_ip: str | None
    ork_ip: str | None
    kamailio_ip: str | None
    ai_models: list[AIModelInfo]
    # Timeline events
    events: list[CallEvent]
    # Conversation
    conversation: list[ConversationMessage]
    # Performance metrics
    tts_latencies: list[int]
    categorizer_latencies: list[float]
    cache_hits: int
    cache_misses: int
    session_summary: SessionSummary | None
    # Problems
    no_voice_timeouts: int
    audio_repetitions: list[AudioRepetition]
    missing_audio_files: list[str]
    hangup_reason: str | None
    disposition_description: str | None
    error_entries: list[str]
    # Timing
    start_time: datetime | None
    end_time: datetime | None
    raw_mailing_data: dict | None
    # System prompts (MAS) - captured from ORK phi_state_choser logs
    classifier_prompt: str | None = field(default=None)
    finalizer_prompt: str | None = field(default=None)
    # Sequence of LLM-decided stages (short names), in chronological order.
    # Includes consecutive repetitions to stay faithful to the log.
    stage_sequence: list[str] = field(default_factory=list)
    # Structured per-turn ADA data extracted from VPL ``[AFTER]`` blocks.
    # Empty for ORK flows. Added last with a default so existing construction
    # keeps working.
    turnos_ada: list["TurnoAda"] = field(default_factory=list)
    # True if a ``[ChamadaFinalizada]`` marker was seen (effective call end).
    call_finalizada: bool = False
    # True if any ADA turn reported ``ai_hangup_call: true`` (AI ended the call).
    ia_hangup: bool = False
    # -- Enriched mailing fields (VPL WaySchInfo). Added last with defaults so
    # existing keyword construction (ORK and VPL) keeps working. --
    debt_minimum: str | None = None
    payment_profile: str | None = None
    overdue_dates: list[str] = field(default_factory=list)
    accounts: list[dict] = field(default_factory=list)
    campaign_id: str | None = None
    mailing_table: str | None = None
    mailing_record_id: str | None = None
    vagent_id: str | None = None


import ast
import json
import os
import re
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class CallLogParser:
    """Parses olos-ai-orchestrator syslog files for a specific CallId.

    Uses a two-pass strategy for performance on large files:
    1. Fast string-contains filter (no regex)
    2. Detailed regex extraction on pre-filtered lines
    """

    def __init__(self, log_directory: str):
        """Initialize parser with the directory containing log files.

        Args:
            log_directory: Path to directory containing .log files and .gz files.
        """
        self._log_directory = log_directory
        self._log_files = self._discover_log_files()

    def parse(self, call_id: str) -> CallData | None:
        """Parse all log files for the given CallId.

        Iterates through discovered log files, filters lines, and parses.
        Returns None if CallId not found in any file.
        """
        all_lines = []
        for file_path in self._log_files:
            lines = self._filter_lines(call_id, file_path)
            all_lines.extend(lines)

        if not all_lines:
            return None

        return self._parse_lines(call_id, all_lines)

    def _discover_log_files(self) -> list[str]:
        """Discover all log files in the directory, sorted by name (newest first)."""
        if not os.path.isdir(self._log_directory):
            logger.warning(f"Log directory not found: {self._log_directory}")
            return []

        files = []
        for f in os.listdir(self._log_directory):
            # Match: .log files, .gz files, olos-ai-orchestrator files,
            # and rotated logs like ecos.log.2026-08-07-10-54-52.1
            if f.endswith('.log') or f.endswith('.gz') or 'olos-ai-orchestrator' in f or '.log.' in f:
                files.append(os.path.join(self._log_directory, f))

        return sorted(files, reverse=True)

    def _filter_lines(self, call_id: str, file_path: str) -> list[str]:
        """Pass 1: Fast string-contains filter. No regex, just 'in' check.
        
        Supports both plain text and gzip compressed files (.gz).

        Args:
            call_id: The CallId to search for.
            file_path: Path to the log file to search.

        Returns:
            List of raw log lines containing the CallId string.
        """
        import gzip

        if not os.path.isfile(file_path):
            logger.warning(f"Log file not found, skipping: {file_path}")
            return []

        matching_lines = []
        try:
            if file_path.endswith('.gz'):
                opener = gzip.open(file_path, 'rt', encoding='utf-8', errors='replace')
            else:
                opener = open(file_path, 'r', encoding='utf-8', errors='replace')
            
            with opener as f:
                for line in f:
                    if call_id in line:
                        matching_lines.append(line.rstrip('\n').rstrip('\r'))
        except OSError as e:
            logger.warning(f"Error reading log file {file_path}: {e}")
            return []

        return matching_lines

    # -- Compiled regex patterns for pass 2 --
    _RE_TIMESTAMP = re.compile(
        r'^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+[+-]\d{2}:\d{2})'
    )
    _RE_MAILING = re.compile(r"Processando mensagem de texto: (.+)")
    _RE_ASR = re.compile(r"BUFFER LIMPO.*transcrição='([^']*)'")
    _RE_BOT_RESPONSE = re.compile(r"Resposta do assistente: (.+)")
    _RE_TRANSITION = re.compile(r"Transitioning from '([^']+)' to '([^']+)'")
    # LLM stage determination (phi_state_choser): captures the decided stage
    # from the canonical "Parsed stage: '<full_name>'" log line.
    _RE_PARSED_STAGE = re.compile(r"Parsed stage:\s*'([^']+)'")
    _RE_CATEGORIZER_DECISION = re.compile(r"Opção escolhida: (.+), Confiança: ([\d.]+)")
    _RE_TTS_LATENCY = re.compile(r"First ElevenLabs chunk received - latency: (\d+) ms")
    _RE_CATEGORIZER_LATENCY = re.compile(r"categorizer_client_call took ([\d.]+)ms")
    _RE_TTS_CACHE = re.compile(r"cache:(HIT|MISS)")
    _RE_NO_VOICE_TIMEOUT = re.compile(r"Timeout de detecção de voz expirado")
    _RE_AUDIO_REPETITION = re.compile(r"Sequência de áudios repetida (\d+) vez")
    _RE_MISSING_AUDIO = re.compile(r"não encontrado: (.+?)\.")
    _RE_HANGUP = re.compile(r"WebSocket fechado após hangup por (\w+)")
    _RE_SESSION_SUMMARY = re.compile(r"Session summary: (.+)")
    _RE_AI_MODELS = re.compile(r"AIModelsSettings criado: ai_models=\[(.+)\]")
    _RE_TTS_SUPPLIER = re.compile(r"TTS configured with (\w+) supplier")
    _RE_TOOL_CALL_DETECTED = re.compile(r"tool call detected: (\w+)")
    _RE_TOOL_CALL_PROCESSING = re.compile(r"Processing tool call: (\w+)")
    _RE_TOOL_CALL_SECOND = re.compile(r"SENDING MESSAGE FOR SECOND CALL \(TOOL CALL\): (.+)")
    _RE_STAGE_NAME = re.compile(r'-([a-z][a-z_]+)$')

    # VPL ADA turn (askADA) canonical JSON block and effective call end marker.
    _RE_ADA_AFTER = re.compile(r"targetContact\.ada \[AFTER\]:\s*(\{.*\})\s*$")
    _RE_CHAMADA_FINALIZADA = re.compile(r"\[ChamadaFinalizada\]")

    # MAS system prompt pattern (phi_state_choser): captures Classifier/Finalizer
    # prompt content from the label up to end of line.
    _RE_MAS_PROMPT = re.compile(
        r"\[MAS\]\s*(Classifier|Finalizer)\s+prompt:\s*(.*)$", re.IGNORECASE
    )

    # Session summary sub-patterns
    _RE_SS_LLM = re.compile(
        r"LLM:(\d+) calls, \d+t \(in:(\d+) out:(\d+) cached:(\d+)\), \$([\d.]+)"
    )
    _RE_SS_ASR = re.compile(r"ASR:(\d+) calls, ([\d.]+)s audio, (\d+) chars")
    _RE_SS_TTS = re.compile(
        r"TTS:(\d+) calls, (\d+) chars, (\d+) chunks \((\d+) bytes\)"
    )
    _RE_SS_CATEGORIZER = re.compile(r"Categorizer:(\d+) calls")

    # AI model config pattern
    _RE_AI_MODEL_CONFIG = re.compile(
        r"AIModelConfig\(ai_type='([^']*)', ai_model='([^']*)',"
    )

    # Pattern to extract just the level + message from a syslog line
    _RE_STRIP_PREFIX = re.compile(
        r'^[\d\-T:\.+]+\s+'           # timestamp
        r'\S+\s+'                      # hostname
        r'\S+:\s+'                     # process[pid]:
        r'(\w+)\s+-\s+'                # level (captured)
        r'[\w\.\-]+\s+-\s+'           # module name
        r'(?:\[.*?\]\s*)*'            # [User ...][CallId: ...] brackets
        r'(.*)$'                       # actual message (captured)
    )

    @staticmethod
    def _clean_log_line(line: str) -> str:
        """Strip syslog prefix from a log line, keeping only LEVEL - message.

        Input:  '2026-06-30T15:44:12.068-03:00 ip-10-179-20-88 olos_ai_orchestrator[1604]: INFO - user - [User UUID][CallId: HEX] General paths loaded'
        Output: 'INFO - General paths loaded'
        """
        m = CallLogParser._RE_STRIP_PREFIX.match(line)
        if m:
            level = m.group(1)
            message = m.group(2).strip()
            return f"{level} - {message}" if message else level
        return line

    @staticmethod
    def _decodificar_prompt(texto: str) -> str:
        """Decode a MAS system prompt for display.

        1. Replaces the literal syslog newline sequence ``#012`` with real
           newlines.
        2. Fixes double-encoding mojibake (e.g. ``VocÃª Ã©`` -> ``Você é``) by
           re-interpreting the text as latin-1 bytes decoded as utf-8. If that
           fails, the original text is returned unchanged.

        ``#012`` is pure ASCII, so it is unaffected by the latin-1/utf-8
        round-trip regardless of ordering; the newline substitution is applied
        first for clarity.
        """
        # (a) Convert literal '#012' syslog newline markers into real newlines.
        texto = texto.replace("#012", "\n")

        # (b) Fix mojibake from double-encoding. ASCII-only text is a no-op.
        try:
            texto = texto.encode("latin-1").decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass

        return texto

    @staticmethod
    def _extract_stage_name(full_name: str) -> str:
        """Extract the stage name from a full qualified stage name.

        E.g. 'FastFlowCloud-ADA-Cob-Generic-Company-ask_cpc' -> 'ask_cpc'
        """
        m = CallLogParser._RE_STAGE_NAME.search(full_name)
        if m:
            return m.group(1)
        return full_name

    @staticmethod
    def _parse_timestamp(line: str) -> datetime | None:
        """Extract and parse the ISO timestamp from a log line."""
        m = CallLogParser._RE_TIMESTAMP.match(line)
        if not m:
            return None
        try:
            return datetime.fromisoformat(m.group(1))
        except ValueError:
            return None

    def _parse_session_summary(self, text: str) -> SessionSummary | None:
        """Parse the session summary metrics string into a SessionSummary."""
        llm_m = self._RE_SS_LLM.search(text)
        asr_m = self._RE_SS_ASR.search(text)
        tts_m = self._RE_SS_TTS.search(text)
        cat_m = self._RE_SS_CATEGORIZER.search(text)

        if not (llm_m and asr_m and tts_m and cat_m):
            logger.warning("Could not fully parse session summary")
            return None

        return SessionSummary(
            llm_calls=int(llm_m.group(1)),
            llm_tokens_input=int(llm_m.group(2)),
            llm_tokens_output=int(llm_m.group(3)),
            llm_tokens_cached=int(llm_m.group(4)),
            llm_cost=float(llm_m.group(5)),
            tts_calls=int(tts_m.group(1)),
            tts_characters=int(tts_m.group(2)),
            tts_chunks=int(tts_m.group(3)),
            tts_bytes=int(tts_m.group(4)),
            asr_calls=int(asr_m.group(1)),
            asr_duration_seconds=float(asr_m.group(2)),
            asr_characters=int(asr_m.group(3)),
            categorizer_calls=int(cat_m.group(1)),
        )

    @staticmethod
    def _detect_vpl_format(lines: list[str]) -> bool:
        """Detect if lines are from VPL (FreeSWITCH) format."""
        for line in lines[:10]:
            if 'sofia/external/' in line or 'jsmain.cpp' in line or 'mod_sofia' in line or 'switch_core' in line:
                return True
        return False

    def _parse_vpl_lines(self, call_id: str, lines: list[str]) -> CallData:
        """Parse VPL (FreeSWITCH) format log lines."""
        import json as json_mod

        customer_name = None
        cpf = None
        phone = None
        product = None
        company = None
        assistant_name = None
        debt_total = None
        debt_discount = None
        debt_due_date = None
        days_overdue = None
        installments_overdue = None
        raw_mailing_data = None
        # Enriched mailing locals (VPL WaySchInfo)
        debt_minimum = None
        payment_profile = None
        overdue_dates = []
        accounts = []
        campaign_id = None
        mailing_table = None
        mailing_record_id = None
        vagent_id = None
        tts_supplier = None
        tts_voice = None
        tts_voice_id = None
        tts_model_id = None
        vpl_ip = None
        ork_ip = None
        kamailio_ip = None
        ai_models = []
        events = []
        conversation = []
        tts_latencies = []
        categorizer_latencies = []
        cache_hits = 0
        cache_misses = 0
        session_summary = None
        no_voice_timeouts = 0
        audio_repetitions = []
        missing_audio_files = []
        hangup_reason = None
        disposition_description = None
        error_entries = []
        start_time = None
        end_time = None
        # Group A/B/C accumulators (enriched ADA extraction from [AFTER] blocks).
        turnos_ada = []
        stage_sequence = []
        call_finalizada = False
        ia_hangup = False
        # Last conversation-stage milestone seen, so assistant messages produced
        # outside adaConversation (i.e. directly from [AFTER]) can carry a stage
        # (analogous to the ORK flow's estagio_atual tracking).
        estagio_atual = None

        # VPL timestamp pattern: "2026-08-03 10:00:36.756713"
        re_vpl_ts = re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)')

        for line in lines:
            # Parse timestamp
            ts = None
            ts_match = re_vpl_ts.search(line)
            if ts_match:
                try:
                    ts = datetime.strptime(ts_match.group(1)[:23], '%Y-%m-%d %H:%M:%S.%f')
                except ValueError:
                    pass

            if ts:
                if start_time is None or ts < start_time:
                    start_time = ts
                if end_time is None or ts > end_time:
                    end_time = ts

            # Extract Kamailio IP from sofia URI
            if kamailio_ip is None and f'{call_id}@' in line:
                km = re.search(rf'{call_id}@([\d.]+)', line)
                if km:
                    kamailio_ip = km.group(1)

            # Extract VPL IP
            if vpl_ip is None and '[x-way-ip]=' in line:
                m = re.search(r'\[x-way-ip\]=\[([\d.]+)\]', line)
                if m:
                    vpl_ip = m.group(1)

            # Extract ORK IP
            if ork_ip is None and '[ork_ip]=' in line:
                m = re.search(r'\[ork_ip\]=\[([\d.]+)\]', line)
                if m:
                    ork_ip = m.group(1)

            # Extract mailing data from MailingData or WaySchInfo JSON
            if raw_mailing_data is None and ('MailingData:' in line or 'WaySchInfo:' in line):
                m = re.search(r'(?:MailingData|WaySchInfo): ({.+})', line)
                if m:
                    try:
                        data = json_mod.loads(m.group(1))
                        raw_mailing_data = data
                        # Real WaySchInfo field names first, ORK-style fallbacks kept.
                        customer_name = (
                            data.get('NOME_CLIENTE')
                            or data.get('Nome')
                            or data.get('name')
                            or data.get('CustomerNameRecord')
                        )
                        # CustomerId is an internal id, NOT a CPF. Leave cpf as
                        # None for VPL unless a real CPF field exists.
                        cpf = data.get('CPF')
                        phone = data.get('OriginalPhoneNumber')
                        product = (
                            data.get('PRODUTO')
                            or data.get('Produto')
                            or data.get('produto')
                        )
                        company = data.get('empresa')
                        assistant_name = data.get('VAgentName') or data.get('assistente')
                        installments_overdue = (
                            data.get('parcelasEmAtraso')
                            or data.get('installments_overdue')
                        )
                        debt_total = (
                            data.get('valorDivida')
                            or data.get('Valor_Atualizado')
                            or data.get('Valor')
                        )
                        debt_discount = data.get('Valor_Desconto')
                        debt_due_date = (
                            data.get('dtPrimeiraParcelaAtrasada')
                            or data.get('Vencimento')
                        )
                        days_overdue = data.get('Dias_Atraso')
                        tts_supplier = data.get('WayEngine') or tts_supplier
                        tts_voice = data.get('WayVoice') or tts_voice

                        # -- Enriched WaySchInfo fields --
                        debt_minimum = data.get('valorMinimo')
                        payment_profile = data.get('perfilPagamento')
                        overdue_dates = [
                            d for d in (
                                data.get('dtPrimeiraParcelaAtrasada'),
                                data.get('dtSegundaParcelaAtrasada'),
                                data.get('dtTerceiraParcelaAtrasada'),
                            ) if d
                        ]
                        accounts = []
                        for idx in ('1', '2', '3'):
                            valor = data.get(f'valorConta{idx}')
                            barras = data.get(f'codigoBarrasConta{idx}')
                            pix = data.get(f'CodigoPixConta{idx}')
                            if valor or barras or pix:
                                accounts.append({
                                    'valor': valor,
                                    'codigo_barras': barras,
                                    'codigo_pix': pix,
                                })
                        campaign_id = data.get('CampaignId')
                        mailing_table = data.get('TableName')
                        mailing_record_id = data.get('MailingRecordId')
                        vagent_id = data.get('VAgentId')
                    except (json_mod.JSONDecodeError, ValueError):
                        pass

            # Extract conversation from adaConversation JSON (keep the LAST entry which has full history)
            if 'adaConversation:' in line:
                m = re.search(r'adaConversation: (\[.+\])', line)
                if m:
                    try:
                        conv_data = json_mod.loads(m.group(1))
                        conversation = []  # Clear - we want the LAST (most complete) entry
                        for turn in conv_data:
                            if turn.get('user') and ts:
                                conversation.append(ConversationMessage(
                                    timestamp=ts, speaker=Speaker.CUSTOMER, text=turn['user']
                                ))
                            if turn.get('assistant') and ts:
                                conversation.append(ConversationMessage(
                                    timestamp=ts, speaker=Speaker.ASSISTANT, text=turn['assistant']
                                ))
                    except (json_mod.JSONDecodeError, ValueError):
                        pass

            # --- Group A/B/C: per-turn ADA data from the canonical [AFTER] block ---
            # The [AFTER] line carries the authoritative per-turn JSON. We use it
            # as the single source for structured turns (turnos_ada), stage
            # sequence, voice-timeout counting and AI-hangup detection. We do NOT
            # parse [BEFORE]/detected-speech for turns to avoid duplicating them.
            # adaConversation (handled above) remains the source for the flat
            # conversation list; here we only enrich assistant messages with a
            # stage when they don't come from adaConversation.
            ada_m = self._RE_ADA_AFTER.search(line)
            if ada_m:
                try:
                    body = json_mod.loads(ada_m.group(1))
                except (json_mod.JSONDecodeError, ValueError):
                    body = None
                if body is not None:
                    asr_text = body.get('asr_transcription', '') or ''
                    asr_conf = body.get('asr_confidence')
                    try:
                        asr_conf = float(asr_conf) if asr_conf is not None else None
                    except (TypeError, ValueError):
                        asr_conf = None
                    ai_sys = body.get('ai_system', '') or ''
                    ai_mod = body.get('ai_model', '') or ''
                    assistant_text = body.get('ai_text_to_vocalize', '') or ''
                    milestone = body.get('ai_milestone', '') or ''
                    hangup = bool(body.get('ai_hangup_call', False))

                    # Classify the milestone: NoInput/timeout turns are not
                    # conversation stages. A conversation stage is anything that
                    # yields a short suffix name via _extract_stage_name (i.e. a
                    # trailing "-lower_case" segment) and is not a no_input_timeout.
                    is_no_input = (
                        ai_sys == 'NoInputHandler'
                        or milestone.startswith('no_input_timeout')
                    )
                    short_stage = self._extract_stage_name(milestone) if milestone else ''
                    is_conversation_stage = (
                        bool(milestone)
                        and not is_no_input
                        and short_stage != milestone
                    )

                    if is_conversation_stage:
                        estagio_atual = short_stage
                        stage_sequence.append(short_stage)
                        events.append(CallEvent(
                            timestamp=ts,
                            event_type=EventType.STAGE_TRANSITION,
                            content=f"→ {short_stage}",
                            metadata={
                                "to": short_stage,
                                "from": "",
                                "source": "vpl_milestone",
                                "full": milestone,
                            },
                        ))

                    turnos_ada.append(TurnoAda(
                        timestamp=ts,
                        asr=asr_text,
                        asr_confidence=asr_conf,
                        ai_system=ai_sys,
                        ai_model=ai_mod,
                        assistant_text=assistant_text,
                        stage=short_stage if is_conversation_stage else '',
                        hangup=hangup,
                    ))

                    # Materialize conversation messages only if adaConversation
                    # has not already populated the flat conversation list, to
                    # avoid duplicating turns.
                    if not conversation:
                        if asr_text and ts:
                            conversation.append(ConversationMessage(
                                timestamp=ts, speaker=Speaker.CUSTOMER, text=asr_text
                            ))
                        if assistant_text and ts:
                            conversation.append(ConversationMessage(
                                timestamp=ts,
                                speaker=Speaker.ASSISTANT,
                                text=assistant_text,
                                stage=estagio_atual if is_conversation_stage else None,
                            ))

                    if is_no_input:
                        no_voice_timeouts += 1
                        if ts:
                            events.append(CallEvent(
                                timestamp=ts,
                                event_type=EventType.VOICE_DETECTION,
                                content="🔇 NoInput / timeout",
                            ))

                    if hangup:
                        ia_hangup = True
                        if ts:
                            events.append(CallEvent(
                                timestamp=ts,
                                event_type=EventType.FINALIZE_DECISION,
                                content="🔴 IA decidiu encerrar (ai_hangup_call)",
                            ))
                # Skip further generic processing of this [AFTER] line.
                continue

            # Group B: effective call-end marker.
            if self._RE_CHAMADA_FINALIZADA.search(line):
                call_finalizada = True
                if ts:
                    events.append(CallEvent(
                        timestamp=ts,
                        event_type=EventType.FINALIZE_DECISION,
                        content="🏁 Chamada finalizada",
                    ))

            # Extract ASR + Bot response from detected-speech JSON bodies
            if 'detected-speech' in line or '"asr_transcription"' in line:
                m = re.search(r'parsedBody: ({.+})', line)
                if m:
                    try:
                        body = json_mod.loads(m.group(1))
                        asr_text = body.get('asr_transcription', '')
                        bot_text = body.get('ai_text_to_vocalize', '')
                        milestone = body.get('ai_milestone', '')

                        if asr_text and ts:
                            events.append(CallEvent(
                                timestamp=ts, event_type=EventType.ASR_TRANSCRIPTION, content=asr_text
                            ))
                        if bot_text and ts:
                            events.append(CallEvent(
                                timestamp=ts, event_type=EventType.BOT_RESPONSE, content=bot_text
                            ))
                        if milestone and ts:
                            stage_name = self._extract_stage_name(milestone)
                            events.append(CallEvent(
                                timestamp=ts, event_type=EventType.STAGE_TRANSITION,
                                content=f"→ {stage_name}",
                                metadata={"to": stage_name, "from": ""}
                            ))

                        # Extract TTS supplier
                        if not tts_supplier:
                            tts_supplier = 'elevenlabs' if 'elevenlabs' in line else None

                        # Extract AI model info
                        ai_sys = body.get('ai_system', '')
                        ai_mod = body.get('ai_model', '')
                        if ai_sys and ai_mod and not ai_models:
                            ai_models.append(AIModelInfo(ai_type=ai_sys, model_name=ai_mod))
                    except (json_mod.JSONDecodeError, ValueError):
                        pass

            # Extract disposition
            if 'callDisposition [dispositionId:' in line:
                m = re.search(r'dispositionId: (\d+)', line)
                if m:
                    hangup_reason = f"disposition_{m.group(1)}"

            # Extract disposition description from callDisposition JSON
            if disposition_description is None and 'callDisposition:' in line and 'navigationDescription' in line:
                disp_m = re.search(r'"navigationDescription":\s*"([^"]+)"', line)
                if disp_m:
                    disposition_description = disp_m.group(1).encode().decode('unicode_escape')

            # Extract hangup cause
            if 'Hangup' in line and 'NORMAL_CLEARING' in line:
                hangup_reason = 'NORMAL_CLEARING'
            elif 'Hangup' in line:
                m = re.search(r'\[(\w+)\]$', line.strip())
                if m:
                    hangup_reason = m.group(1)

            # Errors - catch [ERR] level and real ERROR messages (not JSON "error":"" fields)
            if '[ERR]' in line or (' ERROR: ' in line and 'CALLID:' in line and '"error"' not in line):
                error_entries.append(line)
                if ts:
                    events.append(CallEvent(timestamp=ts, event_type=EventType.ERROR, content=self._clean_vpl_line(line)))

            # TTS supplier from speak lines
            if tts_supplier is None and 'rest:elevenlabs' in line:
                tts_supplier = 'elevenlabs'

            # Extract TTS voice name from promptVoice line
            if tts_voice is None and 'promptVoice:' in line:
                vm = re.search(r'promptVoice: (\w+)', line)
                if vm:
                    tts_voice = vm.group(1)

            # Extract ElevenLabs voice_id and model_id from tts_payload in getMASFlowIInfo response
            if tts_voice_id is None and 'tts_payload' in line and 'voice_id' in line:
                vid_m = re.search(r'"voice_id":\s*\["([^"]+)"\]', line)
                if vid_m:
                    tts_voice_id = vid_m.group(1)
                mid_m = re.search(r'"model_id":\s*"([^"]+)"', line)
                if mid_m:
                    tts_model_id = mid_m.group(1)

            # Add all lines with timestamps to timeline (cleaned)
            if ts:
                event_type_final = EventType.OTHER
                content = self._clean_vpl_line(line)

                # Skip if already added as a specific event type above
                if '[ERR]' not in line and 'parsedBody:' not in line and '[ChamadaFinalizada]' not in line and not (' ERROR: ' in line and 'CALLID:' in line and '"error"' not in line):
                    events.append(CallEvent(
                        timestamp=ts, event_type=event_type_final, content=content
                    ))

        return CallData(
            call_id=call_id,
            customer_name=customer_name,
            cpf=cpf,
            phone=phone,
            product=product,
            company=company,
            debt_total=debt_total,
            debt_discount=debt_discount,
            debt_due_date=debt_due_date,
            days_overdue=days_overdue,
            installments_overdue=installments_overdue,
            assistant_name=assistant_name,
            tts_supplier=tts_supplier,
            tts_voice=tts_voice,
            tts_voice_id=tts_voice_id,
            tts_model_id=tts_model_id,
            vpl_ip=vpl_ip,
            ork_ip=ork_ip,
            kamailio_ip=kamailio_ip,
            ai_models=ai_models,
            events=events,
            conversation=conversation,
            tts_latencies=tts_latencies,
            categorizer_latencies=categorizer_latencies,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            session_summary=session_summary,
            no_voice_timeouts=no_voice_timeouts,
            audio_repetitions=audio_repetitions,
            missing_audio_files=missing_audio_files,
            hangup_reason=hangup_reason,
            disposition_description=disposition_description,
            error_entries=error_entries,
            start_time=start_time,
            end_time=end_time,
            raw_mailing_data=raw_mailing_data,
            classifier_prompt=None,
            finalizer_prompt=None,
            stage_sequence=stage_sequence,
            turnos_ada=turnos_ada,
            call_finalizada=call_finalizada,
            ia_hangup=ia_hangup,
            debt_minimum=debt_minimum,
            payment_profile=payment_profile,
            overdue_dates=overdue_dates,
            accounts=accounts,
            campaign_id=campaign_id,
            mailing_table=mailing_table,
            mailing_record_id=mailing_record_id,
            vagent_id=vagent_id,
        )

    @staticmethod
    def _clean_vpl_line(line: str) -> str:
        """Clean VPL log line for display - remove UUID prefix and timestamp."""
        # VPL lines often start with UUID or timestamp
        # Pattern: "UUID TIMESTAMP PERCENT [LEVEL] module message"
        # or: "TIMESTAMP PERCENT [LEVEL] module message"
        m = re.match(
            r'^(?:[0-9a-f-]{36}\s+)?'  # optional UUID
            r'\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+\s+'  # timestamp
            r'[\d.]+%\s+'  # percentage
            r'\[(\w+)\]\s+'  # level
            r'(\S+)\s+'  # module
            r'(.*)$',  # message
            line
        )
        if m:
            level = m.group(1)
            message = m.group(3).strip()
            # Also strip CALLID prefix from message
            message = re.sub(r'^(?:\[?CALLID:?\s*[0-9a-f]+\]?\s*)', '', message)
            message = re.sub(r'^\[?CallId:?\s*[0-9a-f]+\]?\s*', '', message)
            return f"{level} - {message}" if message else level
        return line

    def _parse_lines(self, call_id: str, lines: list[str]) -> CallData:
        """Pass 2: Regex extraction on pre-filtered log lines.

        Extracts all structured data from lines already filtered for the given call_id.

        Args:
            call_id: The call identifier.
            lines: Pre-filtered log lines containing this call_id.

        Returns:
            A fully populated CallData object.
        """
        # Detect log format: VPL (FreeSWITCH) vs ORK (syslog)
        if self._detect_vpl_format(lines):
            return self._parse_vpl_lines(call_id, lines)

        # Mailing / customer data
        customer_name: str | None = None
        cpf: str | None = None
        phone: str | None = None
        product: str | None = None
        company: str | None = None
        assistant_name: str | None = None
        debt_total: str | None = None
        debt_discount: str | None = None
        debt_due_date: str | None = None
        days_overdue: str | None = None
        installments_overdue: str | None = None
        raw_mailing_data: dict | None = None

        # Call config
        tts_supplier: str | None = None
        tts_voice: str | None = None
        tts_voice_id: str | None = None
        tts_model_id: str | None = None
        vpl_ip: str | None = None
        ork_ip: str | None = None
        kamailio_ip: str | None = None
        ai_models: list[AIModelInfo] = []

        # Extract ORK orchestrator IP from hostname in log line (e.g., "ip-10-179-20-110")
        ork_orchestrator_ip: str | None = None
        if lines:
            hostname_match = re.search(r'ip-(\d+-\d+-\d+-\d+)', lines[0])
            if hostname_match:
                ork_orchestrator_ip = hostname_match.group(1).replace('-', '.')

        # Timeline and conversation
        events: list[CallEvent] = []
        conversation: list[ConversationMessage] = []

        # Performance
        tts_latencies: list[int] = []
        categorizer_latencies: list[float] = []
        cache_hits: int = 0
        cache_misses: int = 0
        session_summary: SessionSummary | None = None

        # Problems
        no_voice_timeouts: int = 0
        audio_repetitions: list[AudioRepetition] = []
        missing_audio_files: list[str] = []
        hangup_reason: str | None = None
        disposition_description: str | None = None
        error_entries: list[str] = []

        # Timing
        start_time: datetime | None = None
        end_time: datetime | None = None

        # System prompts (MAS)
        classifier_prompt: str | None = None
        finalizer_prompt: str | None = None

        # Sequence of LLM-decided stages (short names), chronological order.
        stage_sequence: list[str] = []

        # Current LLM-decided stage, updated as "Parsed stage" lines are seen.
        # Because lines are processed in chronological order, this reflects the
        # last stage decided BEFORE any given assistant response.
        estagio_atual: str | None = None

        for line in lines:
            ts = self._parse_timestamp(line)

            # MAS system prompts (phi_state_choser). Keep only the first
            # occurrence of each type. Detected before the generic event chain
            # so it never affects other extraction; the line still flows into
            # the timeline via the generic handling below.
            mas_m = self._RE_MAS_PROMPT.search(line)
            if mas_m:
                kind = mas_m.group(1).lower()
                content = mas_m.group(2)
                if kind == "classifier" and classifier_prompt is None:
                    classifier_prompt = self._decodificar_prompt(content)
                elif kind == "finalizer" and finalizer_prompt is None:
                    finalizer_prompt = self._decodificar_prompt(content)

            # Track start/end time
            if ts is not None:
                if start_time is None or ts < start_time:
                    start_time = ts
                if end_time is None or ts > end_time:
                    end_time = ts

            # Determine event type and extract specific data
            event_type = EventType.OTHER
            event_content = line
            event_metadata: dict = {}

            # Check for ERROR level
            if 'ERROR -' in line:
                error_entries.append(line)
                event_type = EventType.ERROR

            # 1. Mailing data extraction
            elif self._RE_MAILING.search(line):
                m = self._RE_MAILING.search(line)
                if m:
                    raw_str = m.group(1)
                    try:
                        data = ast.literal_eval(raw_str)
                        raw_mailing_data = data
                        customer_name = data.get('Nome') or data.get('name')
                        cpf = data.get('CPF') or data.get('cpf')
                        phone = data.get('OriginalPhoneNumber')
                        product = data.get('Produto') or data.get('produto')
                        company = data.get('empresa')
                        assistant_name = data.get('assistente')
                        debt_total = data.get('Valor')
                        debt_discount = data.get('Valor_Desconto')
                        debt_due_date = data.get('Vencimento')
                        days_overdue = data.get('Aging__Dias_Atraso_')
                        installments_overdue = data.get('Quantidade_Parcelas_Atraso')

                        # Extract VPL IP from UUI field (X-WayIp)
                        uui = data.get('uui', '')
                        vpl_ip_match = re.search(r'WayIp[=:]?([\d.]+)', uui)
                        if vpl_ip_match:
                            vpl_ip = vpl_ip_match.group(1)

                        # Extract Kamailio IP from OutboundDnis (user@IP)
                        outbound_dnis = data.get('OutboundDnis', '')
                        kamailio_ip_match = re.search(r'@([\d.]+)', outbound_dnis)
                        if kamailio_ip_match:
                            kamailio_ip = kamailio_ip_match.group(1)

                        # ORK IP comes from the log hostname (already extracted as ork_orchestrator_ip)
                        # No need to extract from mailing
                    except (ValueError, SyntaxError):
                        logger.warning(f"Failed to parse mailing data for call {call_id}")
                        raw_mailing_data = None
                event_content = "[Mailing data received]"

            # 2. ASR transcription (customer speech)
            elif self._RE_ASR.search(line):
                m = self._RE_ASR.search(line)
                if m:
                    text = m.group(1)
                    if text and ts:
                        conversation.append(ConversationMessage(
                            timestamp=ts, speaker=Speaker.CUSTOMER, text=text,
                        ))
                        event_type = EventType.ASR_TRANSCRIPTION
                        event_content = text

            # 3. Bot response
            elif self._RE_BOT_RESPONSE.search(line):
                m = self._RE_BOT_RESPONSE.search(line)
                if m:
                    text = m.group(1)
                    if ts:
                        conversation.append(ConversationMessage(
                            timestamp=ts, speaker=Speaker.ASSISTANT, text=text,
                            stage=estagio_atual,
                        ))
                        event_type = EventType.BOT_RESPONSE
                        event_content = text

            # 4. Stage transition
            elif self._RE_TRANSITION.search(line):
                m = self._RE_TRANSITION.search(line)
                if m:
                    from_stage = self._extract_stage_name(m.group(1))
                    to_stage = self._extract_stage_name(m.group(2))
                    event_type = EventType.STAGE_TRANSITION
                    event_content = f"{from_stage} -> {to_stage}"
                    event_metadata = {"from": from_stage, "to": to_stage}

            # 4b. LLM stage determination (phi_state_choser "Parsed stage: '<X>'").
            # The model decides the conversation stage; there is no explicit
            # "from" stage, so from is empty and source marks it as llm_stage.
            elif self._RE_PARSED_STAGE.search(line):
                m = self._RE_PARSED_STAGE.search(line)
                if m:
                    full_name = m.group(1)
                    to_stage = self._extract_stage_name(full_name)
                    event_type = EventType.STAGE_TRANSITION
                    event_content = f"-> {to_stage}"
                    event_metadata = {
                        "to": to_stage,
                        "from": "",
                        "source": "llm_stage",
                        "full": full_name,
                    }
                    # Consolidated chronological stage sequence for the card.
                    stage_sequence.append(to_stage)
                    # Track the current stage so subsequent assistant responses
                    # can be tagged with the stage in effect at their time.
                    estagio_atual = to_stage

            # 5. Categorizer decision
            elif self._RE_CATEGORIZER_DECISION.search(line):
                m = self._RE_CATEGORIZER_DECISION.search(line)
                if m:
                    option_str = m.group(1)
                    confidence = float(m.group(2))
                    try:
                        option = json.loads(option_str)
                    except (json.JSONDecodeError, ValueError):
                        option = option_str
                    event_type = EventType.CATEGORIZER_DECISION
                    event_content = f"confidence={confidence}"
                    event_metadata = {"option": option, "confidence": confidence}

            # 6. TTS first chunk latency
            elif self._RE_TTS_LATENCY.search(line):
                m = self._RE_TTS_LATENCY.search(line)
                if m:
                    latency = int(m.group(1))
                    tts_latencies.append(latency)

            # 7. Categorizer latency
            elif self._RE_CATEGORIZER_LATENCY.search(line):
                m = self._RE_CATEGORIZER_LATENCY.search(line)
                if m:
                    latency = float(m.group(1))
                    categorizer_latencies.append(latency)

            # 7.5 Tool call detection
            elif 'Processing tool call:' in line or 'SENDING MESSAGE FOR SECOND CALL' in line:
                m = self._RE_TOOL_CALL_PROCESSING.search(line)
                if m:
                    tool_name = m.group(1)
                    event_type = EventType.TOOL_CALL
                    event_content = f"🔧 Calling: {tool_name}"
                    event_metadata = {"tool_name": tool_name}
                else:
                    m2 = self._RE_TOOL_CALL_SECOND.search(line)
                    if m2:
                        raw_data = m2.group(1)
                        event_type = EventType.TOOL_CALL
                        # Extract tool name, arguments and result from the JSON-like structure
                        try:
                            data_list = ast.literal_eval(raw_data)
                            # Find the tool_calls entry (assistant role with tool_calls)
                            tool_info = ""
                            tool_result = ""
                            for item in data_list:
                                if isinstance(item, dict):
                                    if item.get('role') == 'assistant' and 'tool_calls' in item:
                                        for tc in item['tool_calls']:
                                            func = tc.get('function', {})
                                            tool_info = f"{func.get('name', '?')}({func.get('arguments', '')})"
                                    elif item.get('role') == 'tool':
                                        tool_result = item.get('content', '')
                            event_content = f"🔧 {tool_info}"
                            event_metadata = {
                                "tool_name": tool_info.split('(')[0] if '(' in tool_info else tool_info,
                                "arguments": tool_info,
                                "result": tool_result
                            }
                        except Exception:
                            event_type = EventType.TOOL_CALL
                            event_content = f"🔧 Tool call: {raw_data[:100]}"
                            event_metadata = {"raw": raw_data[:500]}

            # 7.6 Staging decision (categorizer failed, using staging model)
            elif 'Categorização falhou por threshold baixo' in line or 'Using LLM path instead of categorization' in line:
                event_type = EventType.STAGING_DECISION
                event_content = "⚡ Categorizer falhou → usando staging model"
                # Extract confidence if available
                conf_match = re.search(r'confidence: ([\d.]+)', line)
                if conf_match:
                    event_content += f" (conf={conf_match.group(1)})"

            # 7.7 Finalize decision
            elif 'Finalize response' in line or 'Parsed finalizar_atendimento' in line:
                event_type = EventType.FINALIZE_DECISION
                if '1' in line or 'True' in line:
                    event_content = "🔴 Decisão: ENCERRAR chamada"
                else:
                    event_content = "🟢 Decisão: MANTER chamada"

            # 7.8 Barge-in
            elif 'bargein_activated' in line or 'barge-in' in line.lower():
                event_type = EventType.BARGE_IN
                event_content = "⚡ Barge-in: cliente interrompeu"

            # 7.9 Filler events
            elif 'Filler task iniciada' in line or 'filler_shown' in line:
                event_type = EventType.FILLER
                event_content = "💬 Filler: frase de espera ativada"
            elif 'Cancelling filler' in line or 'cancelando filler' in line.lower():
                event_type = EventType.FILLER
                event_content = "💬 Filler cancelado (resposta pronta)"

            # 7.10 Voice detection
            elif '🎤 VOZ DETECTADA' in line or 'voz detectada' in line.lower() or 'Cancelando timer de detecção de voz (voz detectada)' in line:
                event_type = EventType.VOICE_DETECTION
                event_content = "🎤 Voz detectada"
            elif '🔇' in line or 'Silêncio confirmado' in line:
                event_type = EventType.VOICE_DETECTION
                event_content = "🔇 Silêncio detectado"

            # 7.11 Turn timing
            elif 'TURN_TIMING' in line or 'Tempo total de processamento para chunk' in line:
                m = re.search(r'(\d+\.?\d*)ms', line)
                if m:
                    event_content = f"⏱️ Turno: {m.group(1)}ms"
                    event_metadata = {"total_ms": float(m.group(1))}

            # 8. TTS cache (in TTS generation completed lines)
            elif 'TTS generation completed' in line:
                m = self._RE_TTS_CACHE.search(line)
                if m:
                    if m.group(1) == 'HIT':
                        cache_hits += 1
                    else:
                        cache_misses += 1
                event_type = EventType.TTS_GENERATION
                event_content = line

            # 9. No-voice timeout
            elif self._RE_NO_VOICE_TIMEOUT.search(line):
                no_voice_timeouts += 1

            # 10. Audio repetition
            elif self._RE_AUDIO_REPETITION.search(line):
                m = self._RE_AUDIO_REPETITION.search(line)
                if m:
                    count = int(m.group(1))
                    if ts:
                        audio_repetitions.append(AudioRepetition(
                            timestamp=ts, repetition_count=count,
                        ))

            # 11. Missing audio file
            elif 'não encontrado:' in line:
                m = self._RE_MISSING_AUDIO.search(line)
                if m:
                    missing_audio_files.append(m.group(1))

            # 12. Hangup reason
            elif self._RE_HANGUP.search(line):
                m = self._RE_HANGUP.search(line)
                if m:
                    hangup_reason = m.group(1)

            # 13. Session summary
            elif self._RE_SESSION_SUMMARY.search(line):
                m = self._RE_SESSION_SUMMARY.search(line)
                if m:
                    session_summary = self._parse_session_summary(m.group(1))

            # ORK disposition description (from ADAClassifier log)
            elif 'navigationDescription' in line and 'dispositionId' in line:
                disp_m = re.search(r'"navigationDescription":\s*"([^"]+)"', line)
                if disp_m:
                    disposition_description = disp_m.group(1)

            # 14. AI models
            elif self._RE_AI_MODELS.search(line):
                m = self._RE_AI_MODELS.search(line)
                if m:
                    models_str = m.group(1)
                    for model_match in self._RE_AI_MODEL_CONFIG.finditer(models_str):
                        ai_models.append(AIModelInfo(
                            ai_type=model_match.group(1),
                            model_name=model_match.group(2),
                        ))

            # 15. TTS supplier
            elif self._RE_TTS_SUPPLIER.search(line):
                m = self._RE_TTS_SUPPLIER.search(line)
                if m:
                    tts_supplier = m.group(1)

            # 15b. TTS voice name
            elif 'tts_voice' in line or 'WayVoice' in line:
                vm = re.search(r'"WayVoice":\s*"([^"]+)"', line)
                if vm:
                    tts_voice = vm.group(1)
                elif 'tts_voice' in line:
                    vm = re.search(r"tts_voice[=:]\s*['\"]?(\w+)", line)
                    if vm:
                        tts_voice = vm.group(1)

            # 15c. TTS voice_id and model_id from tts_payload
            elif 'tts_payload' in line and 'voice_id' in line:
                vid_m = re.search(r'"voice_id":\s*\["([^"]+)"\]', line)
                if vid_m:
                    tts_voice_id = vid_m.group(1)
                mid_m = re.search(r'"model_id":\s*"([^"]+)"', line)
                if mid_m:
                    tts_model_id = mid_m.group(1)

            # ADD EVERY LINE to the timeline events
            if ts:
                # For OTHER events, strip the repetitive syslog prefix
                if event_type == EventType.OTHER:
                    event_content = self._clean_log_line(event_content)
                events.append(CallEvent(
                    timestamp=ts,
                    event_type=event_type,
                    content=event_content,
                    metadata=event_metadata,
                ))

        return CallData(
            call_id=call_id,
            customer_name=customer_name,
            cpf=cpf,
            phone=phone,
            product=product,
            company=company,
            debt_total=debt_total,
            debt_discount=debt_discount,
            debt_due_date=debt_due_date,
            days_overdue=days_overdue,
            installments_overdue=installments_overdue,
            assistant_name=assistant_name,
            tts_supplier=tts_supplier,
            tts_voice=tts_voice,
            tts_voice_id=tts_voice_id,
            tts_model_id=tts_model_id,
            vpl_ip=vpl_ip,
            ork_ip=ork_orchestrator_ip,
            kamailio_ip=kamailio_ip,
            ai_models=ai_models,
            events=events,
            conversation=conversation,
            tts_latencies=tts_latencies,
            categorizer_latencies=categorizer_latencies,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            session_summary=session_summary,
            no_voice_timeouts=no_voice_timeouts,
            audio_repetitions=audio_repetitions,
            missing_audio_files=missing_audio_files,
            hangup_reason=hangup_reason,
            disposition_description=disposition_description,
            error_entries=error_entries,
            start_time=start_time,
            end_time=end_time,
            raw_mailing_data=raw_mailing_data,
            classifier_prompt=classifier_prompt,
            finalizer_prompt=finalizer_prompt,
            stage_sequence=stage_sequence,
            turnos_ada=[],
            call_finalizada=False,
            ia_hangup=False,
        )
