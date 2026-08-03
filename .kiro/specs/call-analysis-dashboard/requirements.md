# Requirements Document

## Introduction

The Call Analysis Dashboard is a web interface for curators and QA analysts to inspect individual AI-orchestrated debt collection calls. Given a CallId, the system parses syslog-format log files from the olos-ai-orchestrator, extracts structured call data, and presents it in a readable layout. Curators can then write and save curation reports for each call. The tool prioritizes efficient parsing of large log files (~700MB) by first filtering lines by CallId before detailed parsing.

## Glossary

- **Dashboard**: The Flask/FastAPI web application that serves the call analysis interface
- **Log_Parser**: The component responsible for extracting and filtering log lines from olos-ai-orchestrator log files by CallId
- **Call_Renderer**: The component that transforms parsed call data into structured HTML sections for display
- **Curation_Store**: The local persistence layer (SQLite or JSON) that stores curation reports written by curators
- **CallId**: A hexadecimal identifier (e.g., `0018c4102ff2d6c7`) uniquely identifying a single outbound call session
- **Mailing_Data**: The JSON payload in the first log message of a call, containing customer information, debt data, and call configuration
- **Stage_Transition**: A log event indicating the conversation flow moved from one state to another (e.g., `flow_start` → `ask_cpc`)
- **ASR_Transcription**: Customer speech converted to text by the Automatic Speech Recognition system, extracted from BUFFER LIMPO log entries
- **Bot_Response**: Text the AI assistant generated to vocalize to the customer, extracted from "Resposta do assistente" log entries
- **Categorizer_Decision**: A log event showing the option chosen by the categorizer model along with a confidence score
- **Session_Summary**: The final log entry summarizing LLM calls, TTS calls, ASR usage, and costs for the entire call session

## Requirements

### Requirement 1: CallId Search Interface

**User Story:** As a curator, I want to input a CallId and retrieve its call analysis, so that I can review individual calls efficiently.

#### Acceptance Criteria

1. THE Dashboard SHALL present a text input field for entering a CallId on the main page
2. WHEN a CallId is submitted, THE Dashboard SHALL display a loading indicator while parsing is in progress
3. WHEN a valid CallId is submitted, THE Log_Parser SHALL return all parsed call data within 10 seconds for log files up to 1GB
4. IF a submitted CallId is not found in any log file, THEN THE Dashboard SHALL display a clear error message stating the CallId was not found
5. IF a submitted CallId has an invalid format (not hexadecimal, wrong length), THEN THE Dashboard SHALL display a validation error before attempting to parse

### Requirement 2: Efficient Log Parsing

**User Story:** As a curator, I want the system to parse large log files quickly, so that I do not wait excessively for results.

#### Acceptance Criteria

1. WHEN a CallId search is initiated, THE Log_Parser SHALL first filter log lines containing the target CallId before performing detailed regex parsing
2. THE Log_Parser SHALL support syslog-format log files with the pattern `TIMESTAMP HOSTNAME olos_ai_orchestrator[PID]: LEVEL - MODULE - [User UUID][CallId: HEXID] MESSAGE`
3. THE Log_Parser SHALL handle log files encoded in UTF-8 with graceful handling of encoding errors
4. WHEN multiple log files exist in the configured log directory, THE Log_Parser SHALL search across all files until the CallId is found
5. THE Log_Parser SHALL parse the Mailing_Data JSON payload from the first message containing "Processando mensagem de texto"

### Requirement 3: Customer and Debt Data Display

**User Story:** As a curator, I want to see customer and debt information at a glance, so that I understand the call context before reviewing the conversation.

#### Acceptance Criteria

1. WHEN call data is loaded, THE Call_Renderer SHALL display customer data including: name, CPF, phone number, product, and company
2. WHEN call data is loaded, THE Call_Renderer SHALL display debt data including: total value, discount value, due date, days overdue, and number of overdue installments
3. WHEN call data is loaded, THE Call_Renderer SHALL display call configuration including: AI assistant name, TTS supplier, and AI models used (staging, finalize, categorizer, summary, call-disposition)
4. IF any customer or debt field is missing from the Mailing_Data, THEN THE Call_Renderer SHALL display a placeholder indicating the data is unavailable

### Requirement 4: Call Timeline Display

**User Story:** As a curator, I want to see a chronological timeline of the call, so that I can understand the sequence of events.

#### Acceptance Criteria

1. WHEN call data is loaded, THE Call_Renderer SHALL display a chronological timeline with timestamps for each significant event
2. THE Call_Renderer SHALL include Stage_Transition events in the timeline with source and destination stage names (without the application prefix)
3. THE Call_Renderer SHALL include ASR_Transcription events in the timeline showing what the customer said
4. THE Call_Renderer SHALL include Bot_Response events in the timeline showing what the assistant said
5. THE Call_Renderer SHALL include Categorizer_Decision events in the timeline showing the chosen option and confidence level
6. THE Call_Renderer SHALL display the call start time, end time, and total duration at the top of the timeline

### Requirement 5: Full Conversation Display

**User Story:** As a curator, I want to read the full conversation between the customer and the bot, so that I can evaluate conversation quality.

#### Acceptance Criteria

1. WHEN call data is loaded, THE Call_Renderer SHALL display the full conversation in chronological order with speaker labels (Customer, Assistant)
2. THE Call_Renderer SHALL visually differentiate customer messages (ASR transcriptions) from assistant messages (bot responses)
3. THE Call_Renderer SHALL extract customer speech from log entries matching the pattern `BUFFER LIMPO.*transcrição='TEXT'`
4. THE Call_Renderer SHALL extract bot responses from log entries matching the pattern `Resposta do assistente: TEXT`

### Requirement 6: Performance Metrics Display

**User Story:** As a curator, I want to see performance metrics for the call, so that I can identify latency issues or service degradation.

#### Acceptance Criteria

1. WHEN call data is loaded, THE Call_Renderer SHALL display TTS latency metrics including: first chunk latency and total generation time (extracted from "First ElevenLabs chunk received" log entries)
2. WHEN call data is loaded, THE Call_Renderer SHALL display categorizer latency (extracted from "categorizer_client_call took" log entries)
3. WHEN call data is loaded, THE Call_Renderer SHALL display TTS cache hit/miss ratio (extracted from "cache:HIT" or "cache:MISS" in TTS generation completed entries)
4. WHEN the Session_Summary log entry exists, THE Call_Renderer SHALL display session totals: LLM calls, TTS calls, ASR calls, token counts, and estimated cost

### Requirement 7: Problem Detection Display

**User Story:** As a curator, I want to see problems that occurred during the call, so that I can identify issues that affected call quality.

#### Acceptance Criteria

1. WHEN call data is loaded, THE Call_Renderer SHALL display the count of no-voice timeouts (extracted from "Timeout de detecção de voz expirado" log entries)
2. WHEN call data is loaded, THE Call_Renderer SHALL display audio repetition events with the number of repetitions (extracted from "Sequência de áudios repetida N vez(es)" log entries)
3. WHEN call data is loaded, THE Call_Renderer SHALL display missing audio file paths (extracted from "Arquivo de áudio.*não encontrado" log entries)
4. WHEN call data is loaded, THE Call_Renderer SHALL display the hangup reason (extracted from "WebSocket fechado após hangup por REASON" log entries)
5. WHEN call data is loaded, THE Call_Renderer SHALL display any ERROR-level log entries associated with the call
6. WHEN no problems are detected, THE Call_Renderer SHALL display a positive indicator confirming the call had no issues

### Requirement 8: Curation Report Creation

**User Story:** As a curator, I want to write notes and a curation report about a call, so that I can document my analysis and findings.

#### Acceptance Criteria

1. WHEN call data is displayed, THE Dashboard SHALL present a multiline text field for the curator to write their curation report
2. WHEN the curator clicks the save button, THE Curation_Store SHALL persist the report associated with the CallId, the curator timestamp, and the report text
3. IF a curation report already exists for a CallId, THEN THE Dashboard SHALL display the existing report pre-filled in the text field
4. WHEN a report is saved successfully, THE Dashboard SHALL display a confirmation message

### Requirement 9: Curation Report Storage

**User Story:** As a curator, I want curation reports stored locally, so that I can reference them later without external dependencies.

#### Acceptance Criteria

1. THE Curation_Store SHALL persist reports in a local SQLite database file within the project directory
2. THE Curation_Store SHALL store for each report: CallId, report text, creation timestamp, and last modification timestamp
3. WHEN a report is updated for an existing CallId, THE Curation_Store SHALL preserve the creation timestamp and update the modification timestamp
4. THE Curation_Store SHALL support storing multiple reports (one per unique CallId)

### Requirement 10: Curation Report Listing and Export

**User Story:** As a curator, I want to view and export saved curation reports, so that I can share my findings with the team.

#### Acceptance Criteria

1. THE Dashboard SHALL provide a page listing all saved curation reports with CallId, creation date, and a preview of the report text
2. WHEN a curator clicks on a listed report, THE Dashboard SHALL navigate to the full call analysis view with the report displayed
3. THE Dashboard SHALL provide an export function that generates a JSON file containing all curation reports
4. WHEN the export is triggered, THE Dashboard SHALL include in each exported report: CallId, customer name, company, product, hangup reason, report text, and timestamps
