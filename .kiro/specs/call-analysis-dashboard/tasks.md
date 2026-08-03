# Implementation Plan: Call Analysis Dashboard

## Overview

Build a Flask web application that parses olos-ai-orchestrator syslog files for a given CallId, displays structured call analysis (customer data, conversation, metrics, problems), and supports curation report creation/storage in SQLite. Implementation uses a two-pass parsing strategy for performance on ~700MB files, with server-side rendered templates via Bootstrap 5.

## Tasks

- [x] 1. Set up project structure and core data models
  - [x] 1.1 Create data model definitions in `log_analyzer/apps/call_parser.py`
    - Define `EventType` enum, `CallEvent`, `ConversationMessage`, `Speaker`, `AIModelInfo`, `SessionSummary`, `AudioRepetition`, and `CallData` frozen dataclasses
    - All fields must match the design specification exactly
    - _Requirements: 2.2, 2.5, 3.1, 3.2, 3.3, 4.1, 5.1, 6.1, 6.4, 7.1, 7.2_

  - [x] 1.2 Create CallId validator in `dashboard/validators.py`
    - Implement `validate_call_id(call_id: str) -> tuple[bool, str | None]`
    - Must reject strings that are not exactly 16 hexadecimal characters
    - Return descriptive error messages for empty input, wrong length, and non-hex characters
    - _Requirements: 1.5_

  - [ ]* 1.3 Write property test for CallId validation
    - **Property 1: Invalid CallId rejection**
    - **Validates: Requirements 1.5**
    - File: `tests/test_call_parser_property.py`
    - Use Hypothesis to generate arbitrary strings that are NOT 16-char hex and assert rejection
    - Also verify that valid 16-char hex strings are accepted

  - [x] 1.4 Create Flask app skeleton in `dashboard/app.py`
    - Initialize Flask app with configuration (log directory, DB path)
    - Register routes: `GET /`, `POST /analyze`, `GET /analyze/<call_id>`, `GET /reports`, `POST /reports/save`, `GET /reports/export`
    - Create `dashboard/__init__.py` for package initialization
    - _Requirements: 1.1, 1.4, 1.5, 8.1, 10.1, 10.3_

  - [x] 1.5 Create base template and search page
    - Create `dashboard/templates/base.html` with Bootstrap 5 CDN, navbar with links to Search and Reports
    - Create `dashboard/templates/search.html` with CallId text input form, validation feedback area, and submit button
    - _Requirements: 1.1, 1.2_

- [x] 2. Implement CallLogParser (two-pass parsing)
  - [x] 2.1 Implement pass 1 — line filtering in `log_analyzer/apps/call_parser.py`
    - Implement `CallLogParser.__init__(self, log_directory: str)` — store path, discover `.log` files
    - Implement `_filter_lines(self, call_id: str, file_path: str) -> list[str]` — read file with `errors='replace'`, collect lines containing CallId string
    - Handle missing files gracefully (log warning, skip)
    - _Requirements: 2.1, 2.3, 2.4_

  - [x] 2.2 Implement pass 2 — regex extraction in `log_analyzer/apps/call_parser.py`
    - Implement `_parse_lines(self, call_id: str, lines: list[str]) -> CallData`
    - Extract timestamp from each line using ISO 8601 regex
    - Parse Mailing_Data JSON from "Processando mensagem de texto" lines
    - Extract customer fields (name, CPF, phone, product, company) and debt fields from mailing data
    - Extract ASR transcriptions from `BUFFER LIMPO.*transcrição='TEXT'` pattern
    - Extract bot responses from `Resposta do assistente: TEXT` pattern
    - Extract stage transitions from `Transitioning from 'X' to 'Y'` pattern
    - Extract categorizer decisions from `Opção escolhida: X, Confiança: Y` pattern
    - Extract TTS latencies from `First ElevenLabs chunk received - latency: N ms`
    - Extract categorizer latencies from `categorizer_client_call took Nms`
    - Extract cache hits/misses from `cache:HIT` / `cache:MISS`
    - Extract no-voice timeouts, audio repetitions, missing audio files, hangup reason, error entries
    - Parse session summary JSON from `Session summary:` line
    - Determine start_time and end_time from first/last parsed timestamps
    - _Requirements: 2.2, 2.5, 3.1, 3.2, 3.3, 4.2, 4.3, 4.4, 4.5, 5.3, 5.4, 6.1, 6.2, 6.3, 6.4, 7.1, 7.2, 7.3, 7.4, 7.5_

  - [x] 2.3 Implement `parse(self, call_id: str) -> CallData | None` method
    - Iterate all log files, call `_filter_lines` then `_parse_lines`
    - Return `None` if CallId not found in any file
    - Aggregate lines from all files before parsing (CallId may span multiple files)
    - _Requirements: 2.1, 2.4_

  - [ ]* 2.4 Write property tests for log parsing
    - **Property 2: Syslog line parsing round-trip**
    - **Property 3: Mailing data extraction preserves fields**
    - **Property 8: ASR transcription extraction round-trip**
    - **Property 9: Bot response extraction round-trip**
    - **Validates: Requirements 2.2, 2.5, 5.3, 5.4**
    - File: `tests/test_call_parser_property.py`
    - Use Hypothesis to generate syslog lines and verify round-trip extraction

  - [ ]* 2.5 Write unit tests for CallLogParser
    - File: `tests/test_call_parser.py`
    - Test with sample log lines from real olos-ai-orchestrator output
    - Test edge cases: empty files, missing mailing data, encoding errors, CallId not found
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

- [x] 3. Checkpoint - Ensure parser tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implement CurationStore (SQLite persistence)
  - [x] 4.1 Implement CurationStore in `dashboard/store.py`
    - Define `CurationReport` dataclass with `call_id`, `report_text`, `created_at`, `modified_at`
    - Implement `CurationStore.__init__(self, db_path: str)` — create DB and table if not exists
    - Implement `save_report(self, call_id: str, report_text: str) -> CurationReport` — upsert with preserved `created_at`
    - Implement `get_report(self, call_id: str) -> CurationReport | None`
    - Implement `list_reports(self) -> list[CurationReport]` — ordered by `modified_at` DESC
    - Implement `export_reports(self, call_data_loader: Callable) -> list[dict]` — include CallId, customer name, company, product, hangup reason, report text, timestamps
    - Handle SQLite BUSY with one retry, catch `DatabaseError` for corrupt DB
    - _Requirements: 8.2, 9.1, 9.2, 9.3, 9.4, 10.3, 10.4_

  - [ ]* 4.2 Write property tests for CurationStore
    - **Property 14: Curation report persistence round-trip**
    - **Property 15: Report update preserves creation timestamp**
    - **Property 16: Multiple reports independence**
    - **Property 17: Export completeness**
    - **Validates: Requirements 8.2, 9.2, 9.3, 9.4, 10.3, 10.4**
    - File: `tests/test_curation_store_property.py`
    - Use Hypothesis with temporary SQLite DBs to test persistence invariants

  - [ ]* 4.3 Write unit tests for CurationStore
    - File: `tests/test_curation_store.py`
    - Test save, retrieve, update, list, export operations
    - Test edge cases: empty DB, concurrent-like access, corrupt DB handling
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 10.3, 10.4_

- [x] 5. Implement Flask routes and analysis rendering
  - [x] 5.1 Implement search and analysis routes in `dashboard/app.py`
    - `GET /` — render search page
    - `POST /analyze` — validate CallId, call parser, handle errors (400 for invalid, 404 for not found), render analysis page
    - `GET /analyze/<call_id>` — direct-link variant of analysis
    - Load existing curation report if one exists for the CallId
    - _Requirements: 1.1, 1.2, 1.4, 1.5, 8.3_

  - [x] 5.2 Create analysis template `dashboard/templates/analysis.html`
    - Section: Customer Data (name, CPF, phone, product, company) with placeholders for missing fields
    - Section: Debt Data (total, discount, due date, days overdue, installments) with placeholders
    - Section: Call Configuration (assistant name, TTS supplier, AI models table)
    - Section: Timeline (chronological events with timestamps, stage names stripped of prefix)
    - Section: Full Conversation (speaker-labeled messages, visually differentiated Customer vs Assistant)
    - Section: Performance Metrics (TTS latencies avg/max, categorizer latencies avg/max, cache ratio, session summary)
    - Section: Problems (timeouts count, audio repetitions, missing files, hangup reason, errors, or "no issues" indicator)
    - Section: Curation Report form (textarea pre-filled if report exists, save button)
    - Display call start time, end time, and duration at top
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 5.1, 5.2, 6.1, 6.2, 6.3, 6.4, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 8.1, 8.3_

  - [ ]* 5.3 Write property tests for rendering
    - **Property 4: Call data rendering includes all non-null fields**
    - **Property 5: Missing fields produce placeholders**
    - **Property 6: Timeline chronological ordering**
    - **Property 7: Stage transition prefix stripping**
    - **Property 10: Conversation chronological order with speaker labels**
    - **Property 11: Latency metric computation correctness**
    - **Property 12: Cache hit/miss ratio computation**
    - **Property 13: Problem count accuracy**
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 5.1, 5.2, 6.1, 6.2, 6.3, 7.1, 7.2, 7.5**
    - File: `tests/test_rendering_property.py`
    - Use Hypothesis to generate CallData objects and verify rendered HTML properties

- [x] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implement reports routes and export
  - [x] 7.1 Implement report routes in `dashboard/app.py`
    - `POST /reports/save` — save report text for a CallId, return confirmation
    - `GET /reports` — list all saved reports with preview
    - `GET /reports/export` — generate and download JSON file with all reports + enriched call data
    - _Requirements: 8.2, 8.4, 10.1, 10.2, 10.3, 10.4_

  - [x] 7.2 Create reports list template `dashboard/templates/reports.html`
    - Display table of saved reports: CallId, creation date, preview text
    - Each row links to `/analyze/<call_id>` for full view
    - Include export button that triggers JSON download
    - _Requirements: 10.1, 10.2, 10.3_

  - [ ]* 7.3 Write integration tests for Flask routes
    - File: `tests/test_dashboard_routes.py`
    - Test full flow: submit CallId → parse → render → verify HTML structure
    - Test report CRUD cycle: save → retrieve → update → list → export
    - Test error responses: invalid CallId (400), not found (404)
    - Test empty state: no reports → empty list, empty export `[]`
    - _Requirements: 1.1, 1.4, 1.5, 8.2, 8.4, 10.1, 10.3_

- [x] 8. Create test fixtures and conftest
  - [x] 8.1 Create shared test fixtures in `tests/conftest.py`
    - Fixture: sample log lines (valid syslog format with various event types)
    - Fixture: temporary log directory with test files
    - Fixture: temporary SQLite database
    - Fixture: Flask test client
    - Fixture: sample `CallData` object with all fields populated
    - _Requirements: 2.2, 9.1_

- [x] 9. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties (17 total across 3 test files)
- Unit tests validate specific examples and edge cases
- The parser module in `log_analyzer/apps/call_parser.py` is standalone and reusable outside Flask
- SQLite DB auto-creates on first access — no migration step needed
- Bootstrap 5 loaded via CDN — no npm/build step required

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.4"] },
    { "id": 1, "tasks": ["1.3", "1.5", "2.1", "4.1"] },
    { "id": 2, "tasks": ["2.2", "4.2", "4.3"] },
    { "id": 3, "tasks": ["2.3", "2.4", "2.5"] },
    { "id": 4, "tasks": ["5.1", "8.1"] },
    { "id": 5, "tasks": ["5.2", "5.3"] },
    { "id": 6, "tasks": ["7.1", "7.2"] },
    { "id": 7, "tasks": ["7.3"] }
  ]
}
```
