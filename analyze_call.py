import re
import json
from collections import Counter, defaultdict
from datetime import datetime

log_file = r'C:\Users\antrib\Documents\Visual Studio Code\AnalisadorLogs\logs\olos-ai-orchestrator.log-20260630-070050'

# Pick a few complete calls to analyze deeply - find calls that went through multiple stages
# First pass: find calls with the most log lines (most activity)
call_line_counts = Counter()
call_id_pattern = re.compile(r'\[CallId: ([a-f0-9]+)\]')

print("Pass 1: Finding most active calls...")
with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
    for line in f:
        m = call_id_pattern.search(line)
        if m:
            call_line_counts[m.group(1)] += 1

# Get top 5 most active calls (likely went through full conversation)
top_calls = [cid for cid, _ in call_line_counts.most_common(20)]
print(f"Top 20 calls by activity: {[(c, call_line_counts[c]) for c in top_calls[:5]]}")

# Now extract detailed info for one rich call
# Pick a call with many lines (full conversation)
target_call = None
for cid in top_calls:
    if call_line_counts[cid] > 200:  # Rich conversation
        target_call = cid
        break

if not target_call:
    target_call = top_calls[0]

print(f"\nAnalyzing call: {target_call} ({call_line_counts[target_call]} lines)")

# Second pass: extract all info for this call
call_lines = []
with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
    for line in f:
        if target_call in line:
            call_lines.append(line.strip())

print(f"Extracted {len(call_lines)} lines for call {target_call}")

# Now parse all relevant information from this call
info = {
    'call_id': target_call,
    'timestamps': [],
    'mailing_data': None,
    'customer_name': None,
    'cpf': None,
    'phone': None,
    'product': None,
    'campaign_id': None,
    'empresa': None,
    'assistente': None,
    'debt_value': None,
    'discount_value': None,
    'due_date': None,
    'stages_visited': [],
    'conversation': [],  # (speaker, text)
    'tts_texts': [],
    'asr_transcriptions': [],
    'categorizer_decisions': [],
    'ai_responses': [],
    'errors': [],
    'warnings': [],
    'tts_latencies': [],
    'categorizer_latencies': [],
    'llm_latencies': [],
    'hangup_reason': None,
    'total_duration': None,
    'ai_models_used': [],
    'tts_supplier': None,
    'final_stage': None,
    'audio_files_played': [],
    'multiple_speakers_detected': 0,
    'no_voice_timeouts': 0,
    'audio_repetitions': 0,
    'session_summary': None,
}

# Parse patterns
mailing_pattern = re.compile(r"Processando mensagem de texto: ({.+})")
transcription_pattern = re.compile(r"transcri\xe7\xe3o='([^']*)'")
tts_text_pattern = re.compile(r"Generating audio for text: (.+)")
response_pattern = re.compile(r"Resposta do assistente: (.+)")
stage_transition = re.compile(r"Transitioning from '([^']+)' to '([^']+)'")
categorizer_option = re.compile(r'Op\xe7\xe3o escolhida: ({.+}), Confian\xe7a: ([\d.]+)')
tts_first_chunk = re.compile(r'First ElevenLabs chunk received - latency: (\d+) ms')
categorizer_time = re.compile(r'categorizer_client_call took ([\d.]+)ms')
hangup_reason_pattern = re.compile(r'WebSocket fechado ap\xf3s hangup por (\w+)')
ai_response_pattern = re.compile(r"Resposta gerada: AIResponse\((.+)\)")
session_summary_pattern = re.compile(r"Session summary: (.+)")
llm_time_pattern = re.compile(r'LLM call.*?(\d+)ms')
empty_transcription_pattern = re.compile(r'Empty transcription|EmptyTranscription|transcri\xe7\xe3o vazia')
confidence_pattern = re.compile(r'asr_confidence=([\d.]+)')
buffer_clean_pattern = re.compile(r"BUFFER LIMPO.*transcri\xe7\xe3o='([^']*)'")
ai_text_vocalize = re.compile(r"ai_text_to_vocalize no JSON final: '([^']*)'")
milestone_pattern = re.compile(r"ai_milestone='([^']*)'")

timestamp_pattern = re.compile(r'^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+[+-]\d{2}:\d{2})')

for line in call_lines:
    # Timestamp
    ts_match = timestamp_pattern.match(line)
    if ts_match:
        info['timestamps'].append(ts_match.group(1))
    
    # Mailing data (first message with all customer info)
    if 'Processando mensagem de texto' in line and info['mailing_data'] is None:
        m = mailing_pattern.search(line)
        if m:
            try:
                data = eval(m.group(1))  # It's a Python dict literal
                info['mailing_data'] = data
                info['customer_name'] = data.get('Nome')
                info['cpf'] = data.get('CPF') or data.get('cpf')
                info['phone'] = data.get('OriginalPhoneNumber')
                info['product'] = data.get('produto') or data.get('Produto')
                info['campaign_id'] = data.get('CampaignId')
                info['empresa'] = data.get('empresa')
                info['assistente'] = data.get('assistente')
                info['debt_value'] = data.get('Valor')
                info['discount_value'] = data.get('Valor_Desconto')
                info['due_date'] = data.get('Vencimento')
            except:
                pass
    
    # Stage transitions
    st_match = stage_transition.search(line)
    if st_match:
        info['stages_visited'].append({
            'from': st_match.group(1).split('-')[-1],
            'to': st_match.group(2).split('-')[-1],
        })
        info['final_stage'] = st_match.group(2).split('-')[-1]
    
    # ASR transcriptions (what the customer said)
    buf_match = buffer_clean_pattern.search(line)
    if buf_match:
        text = buf_match.group(1)
        if text and text.strip():
            info['asr_transcriptions'].append(text)
            info['conversation'].append(('CLIENTE', text))
    
    # AI/Assistant responses (what the bot said)
    resp_match = response_pattern.search(line)
    if resp_match:
        text = resp_match.group(1)
        info['ai_responses'].append(text)
        info['conversation'].append(('ASSISTENTE', text))
    
    # TTS texts generated
    tts_match = tts_text_pattern.search(line)
    if tts_match:
        info['tts_texts'].append(tts_match.group(1))
    
    # Categorizer decisions
    cat_match = categorizer_option.search(line)
    if cat_match:
        try:
            option = json.loads(cat_match.group(1))
            confidence = float(cat_match.group(2))
            info['categorizer_decisions'].append({
                'option': option,
                'confidence': confidence,
            })
        except:
            pass
    
    # TTS latency
    tts_lat = tts_first_chunk.search(line)
    if tts_lat:
        info['tts_latencies'].append(int(tts_lat.group(1)))
    
    # Categorizer latency
    cat_lat = categorizer_time.search(line)
    if cat_lat:
        info['categorizer_latencies'].append(float(cat_lat.group(1)))
    
    # Hangup reason
    hangup_match = hangup_reason_pattern.search(line)
    if hangup_match:
        info['hangup_reason'] = hangup_match.group(1)
    
    # Errors
    if 'ERROR -' in line:
        info['errors'].append(line)
    
    # Warnings (only significant ones)
    if 'WARNING -' in line and ('timeout' in line.lower() or 'error' in line.lower() or 'n\xe3o encontrado' in line.lower() or 'falha' in line.lower()):
        info['warnings'].append(line)
    
    # No voice timeouts
    if 'Timeout de detec\xe7\xe3o de voz expirado' in line:
        info['no_voice_timeouts'] += 1
    
    # Audio repetitions
    if 'Sequ\xeancia de \xe1udios repetida' in line:
        rep_match = re.search(r'repetida (\d+)', line)
        if rep_match:
            info['audio_repetitions'] = max(info['audio_repetitions'], int(rep_match.group(1)))
    
    # Multiple speakers
    if 'multiple_speakers_detected' in line.lower() or 'MultipleSpeakersDetected' in line:
        info['multiple_speakers_detected'] += 1
    
    # Session summary
    sess_match = session_summary_pattern.search(line)
    if sess_match:
        info['session_summary'] = sess_match.group(1)
    
    # AI models
    if 'AIModelsSettings criado' in line:
        models_match = re.findall(r"ai_type='([^']+)', ai_model='([^']+)'", line)
        info['ai_models_used'] = [{'type': t, 'model': m} for t, m in models_match]
    
    # TTS supplier
    if 'TTS configured with' in line:
        sup_match = re.search(r'TTS configured with (\w+)', line)
        if sup_match:
            info['tts_supplier'] = sup_match.group(1)

# Calculate duration
if info['timestamps']:
    try:
        start = datetime.fromisoformat(info['timestamps'][0])
        end = datetime.fromisoformat(info['timestamps'][-1])
        info['total_duration'] = (end - start).total_seconds()
    except:
        pass

# Print the analysis
print(f"\n{'='*70}")
print(f"ANALISE DETALHADA DA CHAMADA: {info['call_id']}")
print(f"{'='*70}")

print(f"\nDADOS DO CLIENTE:")
print(f"  Nome: {info['customer_name']}")
print(f"  CPF: {info['cpf']}")
print(f"  Telefone: {info['phone']}")
print(f"  Empresa: {info['empresa']}")
print(f"  Produto: {info['product']}")
print(f"  Campanha: {info['campaign_id']}")

print(f"\nDADOS DA DIVIDA:")
print(f"  Valor total: R${info['debt_value']}")
print(f"  Valor com desconto: R${info['discount_value']}")
print(f"  Vencimento: {info['due_date']}")

print(f"\nCONFIGURACAO DA CHAMADA:")
print(f"  Assistente: {info['assistente']}")
print(f"  TTS: {info['tts_supplier']}")
print(f"  Modelos de IA:")
for model in info['ai_models_used']:
    print(f"    - {model['type']}: {model['model']}")

print(f"\nTIMING:")
if info['total_duration']:
    print(f"  Duracao total: {info['total_duration']:.1f}s")
else:
    print(f"  Duracao total: N/A")
if info['tts_latencies']:
    print(f"  TTS latencia (first chunk): avg={sum(info['tts_latencies'])/len(info['tts_latencies']):.0f}ms, max={max(info['tts_latencies'])}ms")
if info['categorizer_latencies']:
    print(f"  Categorizer latencia: avg={sum(info['categorizer_latencies'])/len(info['categorizer_latencies']):.0f}ms, max={max(info['categorizer_latencies']):.0f}ms")

print(f"\nFLUXO DA CONVERSA:")
print(f"  Estagios visitados:")
for i, s in enumerate(info['stages_visited']):
    print(f"    {i+1}. {s['from']} -> {s['to']}")
print(f"  Estagio final: {info['final_stage']}")

print(f"\nCONVERSA COMPLETA:")
for speaker, text in info['conversation']:
    emoji = "CLIENTE" if speaker == "CLIENTE" else "ASSISTENTE"
    print(f"  [{emoji}]: {text}")

print(f"\nDECISOES DO CATEGORIZER:")
for i, dec in enumerate(info['categorizer_decisions']):
    print(f"  {i+1}. Confianca: {dec['confidence']}")
    print(f"     Proximo passo: {dec['option'].get('next_step', '?').split('-')[-1]}")
    print(f"     Finalizar: {dec['option'].get('finaliza_atendimento', '?')}")
    if dec['option'].get('response'):
        print(f"     Resposta: {dec['option']['response']}")

print(f"\nPROBLEMAS DETECTADOS:")
print(f"  No-voice timeouts: {info['no_voice_timeouts']}")
print(f"  Repeticoes de audio: {info['audio_repetitions']}")
print(f"  Multiple speakers: {info['multiple_speakers_detected']}")
print(f"  Erros: {len(info['errors'])}")
print(f"  Motivo do hangup: {info['hangup_reason']}")

if info['session_summary']:
    print(f"\nRESUMO DA SESSAO:")
    print(f"  {info['session_summary']}")

# Now also extract info about fields available in mailing that could be displayed
if info['mailing_data']:
    print(f"\n{'='*70}")
    print(f"TODOS OS CAMPOS DISPONIVEIS NO MAILING (para exibir na ferramenta):")
    print(f"{'='*70}")
    for key, value in info['mailing_data'].items():
        if value and value != 'None' and value != 'NULL' and value != 'False':
            val_str = str(value)[:100]
            print(f"  {key}: {val_str}")

# Extract all unique field types across multiple calls
print(f"\n{'='*70}")
print(f"ANALISE DE CAMPOS PARA A FERRAMENTA DE CURADORIA")
print(f"{'='*70}")
print("""
Campos extraiveis automaticamente de cada chamada:

1. IDENTIFICACAO DA CHAMADA:
   - CallId (identificador unico)
   - TelecomCallId  
   - CampaignId
   - CustomerId (CPF)
   - MailingRecordId
   - Timestamp inicio/fim
   - Duracao total

2. DADOS DO CLIENTE:
   - Nome
   - CPF
   - Telefone (OriginalPhoneNumber)
   - PhoneIndex
   - Contrato (signatureNumber)
   - Email

3. DADOS DA DIVIDA:
   - Valor total
   - Valor com desconto  
   - Data de vencimento
   - Quantidade de parcelas em atraso
   - Aging (dias de atraso)
   - Produto

4. CONFIGURACAO DO ATENDIMENTO:
   - Empresa
   - Nome da assistente
   - VAgentId / VAgentName
   - Rota de saida (OutboundRoute)
   - AppUrl (fluxo)
   - TTS supplier e voz
   - Modelos de IA (staging, finalize, categorizer)

5. FLUXO DA CONVERSA:
   - Estagio inicial -> transicoes -> estagio final
   - Conversa completa (ASR transcriptions + AI responses)
   - Decisoes do categorizer (option + confidence)
   - Audios tocados (nomes dos arquivos)

6. METRICAS DE PERFORMANCE:
   - TTS latencia (first chunk, total)
   - Categorizer latencia
   - LLM latencia (quando usado)
   - Cache hit/miss
   - Total de tokens (input/output/cached)
   - Custo ($)

7. PROBLEMAS E MOTIVO DE ENCERRAMENTO:
   - Hangup reason (no_input, user_disconnect, completed, etc.)
   - No-voice timeouts (quantos)
   - Repeticoes de audio
   - Erros encontrados
   - Arquivos de audio nao encontrados
   - Multiple speakers detectados

8. RESUMO DA SESSAO:
   - LLM calls / tokens / custo
   - ASR calls / duracao / caracteres
   - TTS calls / caracteres / chunks / bytes
   - Categorizer calls
""")
