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
    error_entries: list[str]
    # Timing
    start_time: datetime | None
    end_time: datetime | None
    raw_mailing_data: dict | None


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
            if f.endswith('.log') or 'olos-ai-orchestrator' in f:
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

    def _parse_lines(self, call_id: str, lines: list[str]) -> CallData:
        """Pass 2: Regex extraction on pre-filtered log lines.

        Extracts all structured data from lines already filtered for the given call_id.

        Args:
            call_id: The call identifier.
            lines: Pre-filtered log lines containing this call_id.

        Returns:
            A fully populated CallData object.
        """
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
        error_entries: list[str] = []

        # Timing
        start_time: datetime | None = None
        end_time: datetime | None = None

        for line in lines:
            ts = self._parse_timestamp(line)

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
            error_entries=error_entries,
            start_time=start_time,
            end_time=end_time,
            raw_mailing_data=raw_mailing_data,
        )
