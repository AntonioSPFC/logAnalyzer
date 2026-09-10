"""Tests for CallLogParser line filtering (pass 1)."""

import os
import sys
import importlib
import importlib.util
import tempfile

import pytest

# Import directly from the module file to avoid circular import
# that exists in log_analyzer.apps.__init__.py
_module_path = os.path.join(
    os.path.dirname(__file__), "..", "log_analyzer", "apps", "call_parser.py"
)
_spec = importlib.util.spec_from_file_location(
    "log_analyzer.apps.call_parser", _module_path
)
_call_parser = importlib.util.module_from_spec(_spec)
sys.modules["log_analyzer.apps.call_parser"] = _call_parser
_spec.loader.exec_module(_call_parser)
CallLogParser = _call_parser.CallLogParser


class TestCallLogParserInit:
    """Tests for CallLogParser.__init__ and file discovery."""

    def test_discovers_log_files_in_directory(self, tmp_path):
        """Parser discovers .log files in the given directory."""
        (tmp_path / "app.log").write_text("line1\nline2\n")
        (tmp_path / "other.log").write_text("line3\n")
        (tmp_path / "readme.txt").write_text("not a log\n")

        parser = CallLogParser(str(tmp_path))

        assert len(parser._log_files) == 2
        assert all(f.endswith(".log") for f in parser._log_files)

    def test_discovers_olos_ai_orchestrator_files(self, tmp_path):
        """Parser discovers files with 'olos-ai-orchestrator' in the name."""
        (tmp_path / "olos-ai-orchestrator-2024-01-01").write_text("data\n")
        (tmp_path / "unrelated.txt").write_text("not a log\n")

        parser = CallLogParser(str(tmp_path))

        assert len(parser._log_files) == 1
        assert "olos-ai-orchestrator" in parser._log_files[0]

    def test_includes_gz_files(self, tmp_path):
        """Parser includes .gz compressed files (gzip support)."""
        (tmp_path / "olos-ai-orchestrator-2024.gz").write_text("compressed\n")
        (tmp_path / "app.log").write_text("line\n")

        parser = CallLogParser(str(tmp_path))

        assert len(parser._log_files) == 2
        basenames = [os.path.basename(f) for f in parser._log_files]
        assert "olos-ai-orchestrator-2024.gz" in basenames
        assert "app.log" in basenames

    def test_nonexistent_directory_returns_empty(self, tmp_path):
        """Parser handles missing directory gracefully."""
        parser = CallLogParser(str(tmp_path / "nonexistent"))

        assert parser._log_files == []

    def test_files_sorted_reverse(self, tmp_path):
        """Discovered files are sorted in reverse order (newest first)."""
        (tmp_path / "aaa.log").write_text("a\n")
        (tmp_path / "zzz.log").write_text("z\n")

        parser = CallLogParser(str(tmp_path))

        assert "zzz.log" in parser._log_files[0]
        assert "aaa.log" in parser._log_files[1]


class TestFilterLines:
    """Tests for CallLogParser._filter_lines (pass 1 filtering)."""

    def test_returns_only_matching_lines(self, tmp_path):
        """Only lines containing the CallId are returned."""
        log_content = (
            "2024-01-01 INFO CallId=abc123 Starting session\n"
            "2024-01-01 INFO General system log\n"
            "2024-01-01 ERROR CallId=abc123 Something failed\n"
            "2024-01-01 DEBUG CallId=xyz789 Other call\n"
        )
        log_file = tmp_path / "test.log"
        log_file.write_text(log_content)

        parser = CallLogParser(str(tmp_path))
        result = parser._filter_lines("abc123", str(log_file))

        assert len(result) == 2
        assert all("abc123" in line for line in result)
        assert "General system log" not in "\n".join(result)
        assert "xyz789" not in "\n".join(result)

    def test_returns_empty_for_no_matches(self, tmp_path):
        """Returns empty list when no lines match the CallId."""
        log_file = tmp_path / "test.log"
        log_file.write_text("line without any call id\nanother line\n")

        parser = CallLogParser(str(tmp_path))
        result = parser._filter_lines("nonexistent-id", str(log_file))

        assert result == []

    def test_handles_missing_file_gracefully(self, tmp_path):
        """Returns empty list for missing file without raising exception."""
        parser = CallLogParser(str(tmp_path))
        result = parser._filter_lines("abc123", str(tmp_path / "missing.log"))

        assert result == []

    def test_strips_trailing_newlines(self, tmp_path):
        """Returned lines have trailing newlines/carriage returns stripped."""
        log_file = tmp_path / "test.log"
        log_file.write_text("CallId=abc123 first line\r\nCallId=abc123 second line\n")

        parser = CallLogParser(str(tmp_path))
        result = parser._filter_lines("abc123", str(log_file))

        for line in result:
            assert not line.endswith('\n')
            assert not line.endswith('\r')

    def test_handles_file_with_encoding_errors(self, tmp_path):
        """Files with encoding errors are read using replacement characters."""
        log_file = tmp_path / "test.log"
        # Write binary content that includes invalid UTF-8 and the CallId
        content = b"CallId=abc123 valid line\n\xff\xfe invalid bytes CallId=abc123\n"
        log_file.write_bytes(content)

        parser = CallLogParser(str(tmp_path))
        result = parser._filter_lines("abc123", str(log_file))

        assert len(result) == 2
        assert all("abc123" in line for line in result)

    def test_case_sensitive_matching(self, tmp_path):
        """Filter is case-sensitive (exact string match)."""
        log_file = tmp_path / "test.log"
        log_file.write_text("CallId=ABC123 upper\nCallId=abc123 lower\n")

        parser = CallLogParser(str(tmp_path))
        result = parser._filter_lines("abc123", str(log_file))

        assert len(result) == 1
        assert "lower" in result[0]


class TestDecodificarPrompt:
    """Tests for CallLogParser._decodificar_prompt (MAS prompt decoding)."""

    def test_converts_hash012_to_newline(self):
        """The literal '#012' syslog marker becomes a real newline."""
        result = CallLogParser._decodificar_prompt("linha1#012#012linha2")
        assert result == "linha1\n\nlinha2"

    def test_fixes_mojibake(self):
        """Double-encoded mojibake is corrected to proper UTF-8."""
        # 'Você é' double-encoded shows up as 'VocÃª Ã©' in the logs.
        mojibake = "VocÃª Ã©"
        result = CallLogParser._decodificar_prompt(mojibake)
        assert result == "Você é"

    def test_fixes_mojibake_and_newlines_together(self):
        """Both transformations apply on the same string."""
        mojibake = "VocÃª Ã© responsÃ¡vel#012#012Sempre responda"
        result = CallLogParser._decodificar_prompt(mojibake)
        assert result == "Você é responsável\n\nSempre responda"

    def test_pure_ascii_is_not_corrupted(self):
        """Plain ASCII text passes through unchanged (idempotent/safe)."""
        text = "Classifier prompt with only ASCII 123 and #012 markers"
        result = CallLogParser._decodificar_prompt(text)
        # '#012' still converted, rest untouched
        assert result == "Classifier prompt with only ASCII 123 and \n markers"

    def test_already_valid_utf8_without_hash012_unchanged(self):
        """Valid UTF-8 without markers is preserved (no corruption)."""
        text = "texto simples sem marcadores"
        assert CallLogParser._decodificar_prompt(text) == text


class TestSystemPromptExtraction:
    """Tests for MAS system prompt extraction in _parse_lines (ORK format)."""

    CALL_ID = "0019035e305026e7"

    def _ork_line(self, message: str) -> str:
        """Build a synthetic ORK syslog line with a valid ISO timestamp."""
        return (
            f"2026-06-30T15:44:12.068-03:00 ip-10-179-20-88 "
            f"olos_ai_orchestrator[1604]: INFO - app.assistants.phi_state_choser - "
            f"[User 11111111-2222-3333-4444-555555555555][CallId: {self.CALL_ID}] {message}"
        )

    def test_extracts_classifier_and_finalizer_prompts(self, tmp_path):
        """Both prompts are extracted, mojibake fixed, #012 converted."""
        lines = [
            self._ork_line(
                "[MAS] Classifier prompt: VocÃª Ã© responsÃ¡vel#012#012Sempre responda"
            ),
            self._ork_line(
                "[MAS] Finalizer prompt: # Papel#012#012VocÃª Ã© um agente"
            ),
        ]
        parser = CallLogParser(str(tmp_path))
        result = parser._parse_lines(self.CALL_ID, lines)

        assert result.classifier_prompt == "Você é responsável\n\nSempre responda"
        assert result.finalizer_prompt == "# Papel\n\nVocê é um agente"

    def test_keeps_first_occurrence_only(self, tmp_path):
        """When a prompt repeats, only the first occurrence is kept."""
        lines = [
            self._ork_line("[MAS] Classifier prompt: primeiro#012conteudo"),
            self._ork_line("[MAS] Classifier prompt: segundo#012conteudo"),
        ]
        parser = CallLogParser(str(tmp_path))
        result = parser._parse_lines(self.CALL_ID, lines)

        assert result.classifier_prompt == "primeiro\nconteudo"

    def test_case_insensitive_label(self, tmp_path):
        """Prompt labels match case-insensitively."""
        lines = [
            self._ork_line("[MAS] CLASSIFIER PROMPT: texto"),
            self._ork_line("[MAS] finalizer prompt: outro"),
        ]
        parser = CallLogParser(str(tmp_path))
        result = parser._parse_lines(self.CALL_ID, lines)

        assert result.classifier_prompt == "texto"
        assert result.finalizer_prompt == "outro"

    def test_no_prompt_leaves_fields_none(self, tmp_path):
        """When no MAS prompt is present, prompt fields are None and parsing
        still succeeds."""
        lines = [
            self._ork_line("General paths loaded"),
            self._ork_line("Resposta do assistente: Olá, tudo bem?"),
        ]
        parser = CallLogParser(str(tmp_path))
        result = parser._parse_lines(self.CALL_ID, lines)

        assert result.classifier_prompt is None
        assert result.finalizer_prompt is None
        # Rest of parsing unaffected: the bot response was captured.
        assert any(m.text == "Olá, tudo bem?" for m in result.conversation)


class TestLLMStageDetermination:
    """Tests for LLM stage determination extraction (phi_state_choser).

    Captures the canonical "Parsed stage: '<full_name>'" log line emitted by
    the ORK phi_state_choser logger and turns it into a STAGE_TRANSITION event
    tagged with source == 'llm_stage'.
    """

    CALL_ID = "0019035e305026e7"

    EventType = _call_parser.EventType

    def _ork_line(self, message: str) -> str:
        """Build a synthetic ORK syslog line with a valid ISO timestamp."""
        return (
            f"2026-06-30T15:44:12.068-03:00 ip-10-179-20-88 "
            f"olos_ai_orchestrator[1604]: INFO - app.assistants.phi_state_choser - "
            f"[User 11111111-2222-3333-4444-555555555555][CallId: {self.CALL_ID}] {message}"
        )

    def test_parsed_stage_creates_stage_transition_event(self, tmp_path):
        """A 'Parsed stage' line yields a STAGE_TRANSITION with llm_stage metadata."""
        full = "FastFlowCloud-ADA-Cob-Generic-Company-CPF-ask_if_will_pay"
        lines = [
            self._ork_line(f"Parsed stage: '{full}'"),
        ]
        parser = CallLogParser(str(tmp_path))
        result = parser._parse_lines(self.CALL_ID, lines)

        stage_events = [
            e for e in result.events
            if e.event_type == self.EventType.STAGE_TRANSITION
        ]
        assert len(stage_events) == 1
        ev = stage_events[0]
        assert ev.metadata["to"] == "ask_if_will_pay"
        assert ev.metadata["from"] == ""
        assert ev.metadata["source"] == "llm_stage"
        assert ev.metadata["full"] == full

    def test_multiple_determinations_preserve_order(self, tmp_path):
        """Multiple 'Parsed stage' lines produce ordered STAGE_TRANSITION events."""
        full1 = "FastFlowCloud-ADA-Cob-Generic-Company-CPF-negociacao_da_divida"
        full2 = "FastFlowCloud-ADA-Cob-Generic-Company-CPF-ask_if_will_pay"
        lines = [
            self._ork_line(f"Parsed stage: '{full1}'"),
            self._ork_line(f"Parsed stage: '{full2}'"),
        ]
        parser = CallLogParser(str(tmp_path))
        result = parser._parse_lines(self.CALL_ID, lines)

        stage_events = [
            e for e in result.events
            if e.event_type == self.EventType.STAGE_TRANSITION
            and e.metadata.get("source") == "llm_stage"
        ]
        assert [e.metadata["to"] for e in stage_events] == [
            "negociacao_da_divida",
            "ask_if_will_pay",
        ]

    def test_lines_without_parsed_stage_produce_no_llm_stage_event(self, tmp_path):
        """Lines lacking 'Parsed stage' do not create llm_stage events."""
        lines = [
            self._ork_line(
                "Stage response from google/gemma-3-4b-it (57 chars): "
                "FastFlowCloud-ADA-Cob-Generic-Company-CPF-ask_if_will_pay"
            ),
            self._ork_line(
                "Stage found directly in response: "
                "'FastFlowCloud-ADA-Cob-Generic-Company-CPF-ask_if_will_pay'"
            ),
            self._ork_line(
                "=== Total google/gemma-3-4b-it stage determination time: 921.99ms ==="
            ),
        ]
        parser = CallLogParser(str(tmp_path))
        result = parser._parse_lines(self.CALL_ID, lines)

        llm_stage_events = [
            e for e in result.events
            if e.event_type == self.EventType.STAGE_TRANSITION
            and e.metadata.get("source") == "llm_stage"
        ]
        assert llm_stage_events == []

    def test_general_parsing_still_works_with_parsed_stage_present(self, tmp_path):
        """Adding a Parsed stage line does not break other extractions."""
        full = "FastFlowCloud-ADA-Cob-Generic-Company-CPF-ask_if_will_pay"
        lines = [
            self._ork_line("Resposta do assistente: Olá, tudo bem?"),
            self._ork_line(f"Parsed stage: '{full}'"),
            self._ork_line("General paths loaded"),
        ]
        parser = CallLogParser(str(tmp_path))
        result = parser._parse_lines(self.CALL_ID, lines)

        # Bot response conversation still captured.
        assert any(m.text == "Olá, tudo bem?" for m in result.conversation)
        # LLM stage event present exactly once.
        llm_stage_events = [
            e for e in result.events
            if e.event_type == self.EventType.STAGE_TRANSITION
            and e.metadata.get("source") == "llm_stage"
        ]
        assert len(llm_stage_events) == 1
        assert llm_stage_events[0].metadata["to"] == "ask_if_will_pay"


class TestStageSequence:
    """Tests for the consolidated CallData.stage_sequence field.

    The parser accumulates the short name of every LLM-decided stage
    ("Parsed stage: '<full_name>'") in chronological order, preserving
    consecutive repetitions, so the dashboard card can render the full
    progression of stages.
    """

    CALL_ID = "0019035e305026e7"

    EventType = _call_parser.EventType

    def _ork_line(self, message: str) -> str:
        """Build a synthetic ORK syslog line with a valid ISO timestamp."""
        return (
            f"2026-06-30T15:44:12.068-03:00 ip-10-179-20-88 "
            f"olos_ai_orchestrator[1604]: INFO - app.assistants.phi_state_choser - "
            f"[User 11111111-2222-3333-4444-555555555555][CallId: {self.CALL_ID}] {message}"
        )

    def test_stage_sequence_collects_short_names_in_order(self, tmp_path):
        """Multiple 'Parsed stage' lines populate stage_sequence with short names."""
        full1 = "FastFlowCloud-ADA-Cob-Generic-Company-CPF-negociacao_da_divida"
        full2 = "FastFlowCloud-ADA-Cob-Generic-Company-CPF-ask_if_will_pay"
        lines = [
            self._ork_line(f"Parsed stage: '{full1}'"),
            self._ork_line(f"Parsed stage: '{full2}'"),
        ]
        parser = CallLogParser(str(tmp_path))
        result = parser._parse_lines(self.CALL_ID, lines)

        assert result.stage_sequence == [
            "negociacao_da_divida",
            "ask_if_will_pay",
        ]

    def test_stage_sequence_preserves_consecutive_repetitions(self, tmp_path):
        """The same stage appearing twice in a row is kept faithfully."""
        full1 = "FastFlowCloud-ADA-Cob-Generic-Company-CPF-negociacao_da_divida"
        full2 = "FastFlowCloud-ADA-Cob-Generic-Company-CPF-ask_if_will_pay"
        lines = [
            self._ork_line(f"Parsed stage: '{full1}'"),
            self._ork_line(f"Parsed stage: '{full1}'"),
            self._ork_line(f"Parsed stage: '{full2}'"),
        ]
        parser = CallLogParser(str(tmp_path))
        result = parser._parse_lines(self.CALL_ID, lines)

        assert result.stage_sequence == [
            "negociacao_da_divida",
            "negociacao_da_divida",
            "ask_if_will_pay",
        ]

    def test_stage_sequence_empty_without_parsed_stage(self, tmp_path):
        """No 'Parsed stage' lines yields an empty stage_sequence."""
        lines = [
            self._ork_line("Resposta do assistente: Olá, tudo bem?"),
            self._ork_line("General paths loaded"),
        ]
        parser = CallLogParser(str(tmp_path))
        result = parser._parse_lines(self.CALL_ID, lines)

        assert result.stage_sequence == []

    def test_stage_transition_timeline_event_still_created(self, tmp_path):
        """The STAGE_TRANSITION llm_stage badge is not regressed by stage_sequence."""
        full = "FastFlowCloud-ADA-Cob-Generic-Company-CPF-ask_if_will_pay"
        lines = [
            self._ork_line(f"Parsed stage: '{full}'"),
        ]
        parser = CallLogParser(str(tmp_path))
        result = parser._parse_lines(self.CALL_ID, lines)

        llm_stage_events = [
            e for e in result.events
            if e.event_type == self.EventType.STAGE_TRANSITION
            and e.metadata.get("source") == "llm_stage"
        ]
        assert len(llm_stage_events) == 1
        assert llm_stage_events[0].metadata["to"] == "ask_if_will_pay"
        # And the consolidated sequence mirrors the timeline decision.
        assert result.stage_sequence == ["ask_if_will_pay"]


class TestAssistantMessageStage:
    """Tests for tagging assistant conversation messages with the current stage.

    The parser tracks the last LLM-decided stage ("Parsed stage: '<full>'")
    seen so far and attaches its short name to each subsequent assistant
    ("Resposta do assistente:") message. Customer messages keep stage=None.
    """

    CALL_ID = "0019035e305026e7"

    Speaker = _call_parser.Speaker

    def _ork_line(self, message: str) -> str:
        """Build a synthetic ORK syslog line with a valid ISO timestamp."""
        return (
            f"2026-06-30T15:44:12.068-03:00 ip-10-179-20-88 "
            f"olos_ai_orchestrator[1604]: INFO - app.assistants.phi_state_choser - "
            f"[User 11111111-2222-3333-4444-555555555555][CallId: {self.CALL_ID}] {message}"
        )

    def test_assistant_message_gets_current_stage(self, tmp_path):
        """Assistant response is tagged with the last 'Parsed stage' before it."""
        full = "FastFlowCloud-ADA-Cob-Generic-Company-CPF-negociacao_da_divida"
        lines = [
            self._ork_line(f"Parsed stage: '{full}'"),
            self._ork_line("Resposta do assistente: Vamos negociar sua dívida?"),
        ]
        parser = CallLogParser(str(tmp_path))
        result = parser._parse_lines(self.CALL_ID, lines)

        assistant_msgs = [
            m for m in result.conversation if m.speaker == self.Speaker.ASSISTANT
        ]
        assert len(assistant_msgs) == 1
        assert assistant_msgs[0].stage == "negociacao_da_divida"

    def test_assistant_message_before_any_stage_has_none(self, tmp_path):
        """An assistant response before any 'Parsed stage' line has stage=None."""
        full = "FastFlowCloud-ADA-Cob-Generic-Company-CPF-negociacao_da_divida"
        lines = [
            self._ork_line("Resposta do assistente: Olá, tudo bem?"),
            self._ork_line(f"Parsed stage: '{full}'"),
        ]
        parser = CallLogParser(str(tmp_path))
        result = parser._parse_lines(self.CALL_ID, lines)

        assistant_msgs = [
            m for m in result.conversation if m.speaker == self.Speaker.ASSISTANT
        ]
        assert len(assistant_msgs) == 1
        assert assistant_msgs[0].stage is None

    def test_customer_message_has_none_stage(self, tmp_path):
        """Customer (ASR) messages never receive a stage, even after a stage line."""
        full = "FastFlowCloud-ADA-Cob-Generic-Company-CPF-negociacao_da_divida"
        lines = [
            self._ork_line(f"Parsed stage: '{full}'"),
            self._ork_line("BUFFER LIMPO transcrição='quero pagar'"),
        ]
        parser = CallLogParser(str(tmp_path))
        result = parser._parse_lines(self.CALL_ID, lines)

        customer_msgs = [
            m for m in result.conversation if m.speaker == self.Speaker.CUSTOMER
        ]
        assert len(customer_msgs) == 1
        assert customer_msgs[0].text == "quero pagar"
        assert customer_msgs[0].stage is None

    def test_stage_changes_between_assistant_responses(self, tmp_path):
        """Each assistant response reflects the stage in effect at its time."""
        full1 = "FastFlowCloud-ADA-Cob-Generic-Company-CPF-identificacao_do_cliente"
        full2 = "FastFlowCloud-ADA-Cob-Generic-Company-CPF-negociacao_da_divida"
        lines = [
            self._ork_line(f"Parsed stage: '{full1}'"),
            self._ork_line("Resposta do assistente: Confirma seu CPF?"),
            self._ork_line(f"Parsed stage: '{full2}'"),
            self._ork_line("Resposta do assistente: Vamos negociar?"),
        ]
        parser = CallLogParser(str(tmp_path))
        result = parser._parse_lines(self.CALL_ID, lines)

        assistant_msgs = [
            m for m in result.conversation if m.speaker == self.Speaker.ASSISTANT
        ]
        assert len(assistant_msgs) == 2
        assert assistant_msgs[0].stage == "identificacao_do_cliente"
        assert assistant_msgs[1].stage == "negociacao_da_divida"


class TestVplTurnosAda:
    """Tests for enriched ADA turn extraction from VPL ``[AFTER]`` blocks.

    All input lines are 100% synthetic and follow the real VPL prefix:
    ``<ts> <pct>% [LEVEL] jsmain.cpp:NN [tag] CALLID: <hex> ...``
    """

    CALL_ID = "abc123def456"

    @staticmethod
    def _vpl_after(json_str, ts="2026-09-08 10:56:52.212650", tag="askADA"):
        """Build a synthetic VPL [AFTER] line carrying the ADA turn JSON."""
        return (
            f"{ts} 98.43% [ALERT] jsmain.cpp:1332 [{tag}] "
            f"CALLID: {TestVplTurnosAda.CALL_ID} targetContact.ada [AFTER]: {json_str}"
        )

    @staticmethod
    def _vpl_finalizada(ts="2026-09-08 10:57:10.000000"):
        return (
            f"{ts} 99.00% [ALERT] jsmain.cpp:267 [flow] "
            f"CALLID: {TestVplTurnosAda.CALL_ID} [ChamadaFinalizada]"
        )

    def _parse(self, lines):
        parser = CallLogParser.__new__(CallLogParser)
        return parser._parse_vpl_lines(self.CALL_ID, lines)

    def test_extracts_turno_fields(self):
        """A conversation [AFTER] turn is captured with all fields."""
        import json
        body = json.dumps({
            "asr_transcription": "Oi, sou eu sim",
            "asr_confidence": 1.0,
            "ai_system": "Categorizer",
            "ai_model": "AISM",
            "ai_text_to_vocalize": "Ótimo, vamos confirmar seu CPF.",
            "ai_milestone": "FastFlowCloud-ADA-Cob-Generic-Company-CPF-identify_contact",
            "ai_hangup_call": False,
        })
        call = self._parse([self._vpl_after(body)])

        assert len(call.turnos_ada) == 1
        t = call.turnos_ada[0]
        assert t.asr == "Oi, sou eu sim"
        assert t.asr_confidence == 1.0
        assert t.ai_system == "Categorizer"
        assert t.ai_model == "AISM"
        assert t.assistant_text == "Ótimo, vamos confirmar seu CPF."
        assert t.stage == "identify_contact"
        assert t.hangup is False

    def test_no_input_increments_timeout_and_no_stage(self):
        """NoInputHandler turn counts as voice timeout and is not a conv stage."""
        import json
        body = json.dumps({
            "asr_transcription": "",
            "asr_confidence": None,
            "ai_system": "NoInputHandler",
            "ai_model": "No Input Timeout",
            "ai_text_to_vocalize": "Você ainda está aí?",
            "ai_milestone": "no_input_timeout_1",
            "ai_hangup_call": False,
        })
        call = self._parse([self._vpl_after(body)])

        assert call.no_voice_timeouts == 1
        assert call.stage_sequence == []
        assert len(call.turnos_ada) == 1
        assert call.turnos_ada[0].stage == ""

    def test_ai_hangup_marks_ia_hangup(self):
        """A turn with ai_hangup_call true sets ia_hangup on the CallData."""
        import json
        body = json.dumps({
            "asr_transcription": "Não tenho interesse",
            "asr_confidence": 0.9,
            "ai_system": "Categorizer",
            "ai_model": "AISM",
            "ai_text_to_vocalize": "Tudo bem, até logo.",
            "ai_milestone": "FastFlowCloud-ADA-Cob-Generic-Company-End-finalize_call",
            "ai_hangup_call": True,
        })
        call = self._parse([self._vpl_after(body)])

        assert call.ia_hangup is True
        assert call.turnos_ada[0].hangup is True

    def test_chamada_finalizada_marks_flag(self):
        """A [ChamadaFinalizada] marker sets call_finalizada."""
        call = self._parse([self._vpl_finalizada()])
        assert call.call_finalizada is True

    def test_stage_sequence_order(self):
        """stage_sequence receives conversation milestones in order."""
        import json
        b1 = json.dumps({
            "asr_transcription": "alo",
            "asr_confidence": 1.0,
            "ai_system": "Categorizer",
            "ai_model": "AISM",
            "ai_text_to_vocalize": "oi",
            "ai_milestone": "FastFlowCloud-ADA-Cob-Generic-Company-CPF-identify_contact",
            "ai_hangup_call": False,
        })
        b2 = json.dumps({
            "asr_transcription": "sim",
            "asr_confidence": 1.0,
            "ai_system": "Categorizer",
            "ai_model": "AISM",
            "ai_text_to_vocalize": "confirmado",
            "ai_milestone": "FastFlowCloud-ADA-Cob-Generic-Company-Deal-offer_deal",
            "ai_hangup_call": False,
        })
        call = self._parse([
            self._vpl_after(b1, ts="2026-09-08 10:56:52.212650"),
            self._vpl_after(b2, ts="2026-09-08 10:56:58.000000"),
        ])
        assert call.stage_sequence == ["identify_contact", "offer_deal"]

    def test_malformed_json_after_is_ignored(self):
        """A malformed [AFTER] JSON is skipped without breaking the parse."""
        bad = self._vpl_after("{not valid json")
        good_body = (
            '{"asr_transcription": "ok", "asr_confidence": 1.0, '
            '"ai_system": "Categorizer", "ai_model": "AISM", '
            '"ai_text_to_vocalize": "certo", '
            '"ai_milestone": "FastFlowCloud-ADA-Cob-Generic-Company-CPF-identify_contact", '
            '"ai_hangup_call": false}'
        )
        call = self._parse([bad, self._vpl_after(good_body, ts="2026-09-08 10:57:00.000000")])

        assert len(call.turnos_ada) == 1
        assert call.turnos_ada[0].asr == "ok"

    def test_conversation_populated_from_after_when_no_ada_conversation(self):
        """When no adaConversation exists, [AFTER] fills the flat conversation."""
        import json
        body = json.dumps({
            "asr_transcription": "boa tarde",
            "asr_confidence": 1.0,
            "ai_system": "Categorizer",
            "ai_model": "AISM",
            "ai_text_to_vocalize": "boa tarde, tudo bem?",
            "ai_milestone": "FastFlowCloud-ADA-Cob-Generic-Company-CPF-identify_contact",
            "ai_hangup_call": False,
        })
        call = self._parse([self._vpl_after(body)])

        assert len(call.conversation) == 2
        assert call.conversation[0].speaker.value == "customer"
        assert call.conversation[1].speaker.value == "assistant"
        assert call.conversation[1].stage == "identify_contact"


class TestVplWaySchInfo:
    """Tests for enriched mailing extraction from VPL ``WaySchInfo`` lines.

    All input is 100% synthetic (fake names, phones, PIX/barcode strings).
    """

    CALL_ID = "cafe1234beef5678"

    @staticmethod
    def _vpl_waysch(json_str, ts="2026-09-08 11:23:34.112641"):
        """Build a synthetic VPL WS_WAY_START line carrying WaySchInfo JSON."""
        return (
            f"{ts} 99.03% [INFO] jsmain.cpp:541 [WAY][WS_WAY_START] "
            f"CallInfo CALLID: {TestVplWaySchInfo.CALL_ID} WaySchInfo: {json_str}"
        )

    def _parse(self, lines):
        parser = CallLogParser.__new__(CallLogParser)
        return parser._parse_vpl_lines(self.CALL_ID, lines)

    @staticmethod
    def _fake_waysch():
        import json
        return json.dumps({
            "OriginalPhoneNumber": "11999990000",
            "Prefix": "11",
            "CustomerNameRecord": None,
            "NOME_CLIENTE": "FULANO DE TAL",
            "PRODUTO": "EAC",
            "parcelasEmAtraso": "2",
            "dtPrimeiraParcelaAtrasada": "06/08/2026",
            "dtSegundaParcelaAtrasada": "08/07/2026",
            "dtTerceiraParcelaAtrasada": None,
            "valorDivida": "12345,67",
            "valorMinimo": "1000,15",
            "valorParcelaMaisAntiga": "9000,52",
            "codigoBarrasConta1": "00000BARCODE1",
            "codigoBarrasConta2": "00000BARCODE2",
            "codigoBarrasConta3": None,
            "CodigoPixConta1": "FAKEPIX0001",
            "CodigoPixConta2": "FAKEPIX0002",
            "CodigoPixConta3": None,
            "valorConta1": "1000,15",
            "valorConta2": "9000,52",
            "valorConta3": None,
            "perfilPagamento": "VISTA",
            "CampaignId": "999",
            "CustomerId": "11111",
            "TableName": "FAKE_TABLE_TESTE",
            "MailingRecordId": "7",
            "MailingPhoneNumberId": "7",
            "VAgentId": "1234",
            "VAgentName": "Assistente Fake",
            "WayEngine": "rest:elevenlabs",
            "WayVoice": "jessica",
        })

    def test_maps_core_fields(self):
        call = self._parse([self._vpl_waysch(self._fake_waysch())])
        assert call.customer_name == "FULANO DE TAL"
        assert call.product == "EAC"
        assert call.phone == "11999990000"
        assert call.installments_overdue == "2"
        assert call.debt_total == "12345,67"
        assert call.debt_minimum == "1000,15"
        assert call.payment_profile == "VISTA"
        assert call.assistant_name == "Assistente Fake"

    def test_cpf_is_none_for_vpl(self):
        """CustomerId is an internal id, not a CPF -> cpf stays None."""
        call = self._parse([self._vpl_waysch(self._fake_waysch())])
        assert call.cpf is None

    def test_overdue_dates_in_order_non_null(self):
        call = self._parse([self._vpl_waysch(self._fake_waysch())])
        assert call.overdue_dates == ["06/08/2026", "08/07/2026"]

    def test_accounts_extracted(self):
        call = self._parse([self._vpl_waysch(self._fake_waysch())])
        assert len(call.accounts) == 2
        assert call.accounts[0] == {
            "valor": "1000,15",
            "codigo_barras": "00000BARCODE1",
            "codigo_pix": "FAKEPIX0001",
        }
        assert call.accounts[1] == {
            "valor": "9000,52",
            "codigo_barras": "00000BARCODE2",
            "codigo_pix": "FAKEPIX0002",
        }

    def test_campaign_and_mailing_metadata(self):
        call = self._parse([self._vpl_waysch(self._fake_waysch())])
        assert call.campaign_id == "999"
        assert call.mailing_table == "FAKE_TABLE_TESTE"
        assert call.mailing_record_id == "7"
        assert call.vagent_id == "1234"

    def test_tts_supplier_and_voice(self):
        call = self._parse([self._vpl_waysch(self._fake_waysch())])
        assert call.tts_supplier == "rest:elevenlabs"
        assert call.tts_voice == "jessica"
