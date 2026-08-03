import re
from collections import Counter, defaultdict
from datetime import datetime

log_file = r'C:\Users\antrib\Documents\Visual Studio Code\AnalisadorLogs\logs\olos-ai-orchestrator.log-20260630-070050'

# Counters
total_lines = 0
calls = set()
disconnection_reasons = Counter()
errors = Counter()
warnings = Counter()
timeouts = Counter()
tts_latencies = []
categorizer_latencies = []
llm_calls = 0
tts_cache_hits = 0
tts_cache_misses = 0
no_voice_timeouts = 0
hangups_by_reason = Counter()
stages_reached = Counter()
audio_file_not_found = []
call_durations = {}  # callid -> (first_timestamp, last_timestamp)

# Patterns
call_id_pattern = re.compile(r'\[CallId: ([a-f0-9]+)\]')
timestamp_pattern = re.compile(r'^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+[+-]\d{2}:\d{2})')
tts_latency_pattern = re.compile(r'First ElevenLabs chunk received - latency: (\d+) ms')
categorizer_latency_pattern = re.compile(r'categorizer_client_call took ([\d.]+)ms')
transition_pattern = re.compile(r"Transitioning from '([^']+)' to '([^']+)'")
hangup_pattern = re.compile(r'WebSocket fechado ap\u00f3s hangup por (\w+)')
no_voice_pattern = re.compile(r'Timeout de detec\u00e7\u00e3o de voz expirado')
audio_not_found_pattern = re.compile(r'Arquivo de \u00e1udio.*n\u00e3o encontrado: (.+?)\.')
cache_pattern = re.compile(r'cache:(HIT|MISS)')

print("Analyzing log file... (this may take a minute for 743MB)")

with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
    for line in f:
        total_lines += 1
        
        # Extract call ID and timestamp
        call_match = call_id_pattern.search(line)
        if call_match:
            call_id = call_match.group(1)
            calls.add(call_id)
            
            # Track call duration
            ts_match = timestamp_pattern.match(line)
            if ts_match:
                try:
                    ts = datetime.fromisoformat(ts_match.group(1))
                    if call_id not in call_durations:
                        call_durations[call_id] = [ts, ts]
                    else:
                        call_durations[call_id][1] = ts
                except:
                    pass
        
        # Count errors and warnings
        if 'ERROR -' in line or 'error' in line.lower() and 'ERROR' in line:
            if 'ERROR -' in line:
                # Extract error module
                err_match = re.search(r'ERROR - ([^\s-]+)', line)
                if err_match:
                    errors[err_match.group(1)] += 1
        
        if 'WARNING -' in line:
            warn_match = re.search(r'WARNING - ([^\s-]+)', line)
            if warn_match:
                warnings[warn_match.group(1)] += 1
        
        # TTS latency
        tts_match = tts_latency_pattern.search(line)
        if tts_match:
            tts_latencies.append(int(tts_match.group(1)))
        
        # Categorizer latency
        cat_match = categorizer_latency_pattern.search(line)
        if cat_match:
            categorizer_latencies.append(float(cat_match.group(1)))
        
        # Stage transitions
        trans_match = transition_pattern.search(line)
        if trans_match:
            stages_reached[trans_match.group(2).split('-')[-1]] += 1
        
        # Hangup reasons
        hangup_match = hangup_pattern.search(line)
        if hangup_match:
            hangups_by_reason[hangup_match.group(1)] += 1
        
        # No voice timeouts
        if no_voice_pattern.search(line):
            no_voice_timeouts += 1
        
        # Audio file not found
        audio_match = audio_not_found_pattern.search(line)
        if audio_match:
            audio_file_not_found.append(audio_match.group(1))
        
        # TTS cache
        cache_match = cache_pattern.search(line)
        if cache_match:
            if cache_match.group(1) == 'HIT':
                tts_cache_hits += 1
            else:
                tts_cache_misses += 1
        
        # Disconnection reasons
        if 'Desconectando usu\u00e1rio' in line:
            reason_match = re.search(r'Desconectando usu\u00e1rio (.+)', line)
            if reason_match:
                disconnection_reasons[reason_match.group(1).strip()] += 1

print(f"\n{'='*60}")
print(f"AN\u00c1LISE DO LOG - olos-ai-orchestrator")
print(f"{'='*60}")
print(f"\n\U0001f4ca ESTAT\u00cdSTICAS GERAIS:")
print(f"  Total de linhas: {total_lines:,}")
print(f"  Total de chamadas \u00fanicas: {len(calls):,}")

# Call duration stats
durations = []
for cid, (start, end) in call_durations.items():
    dur = (end - start).total_seconds()
    if dur > 0:
        durations.append(dur)

if durations:
    print(f"\n\u23f1\ufe0f DURA\u00c7\u00c3O DAS CHAMADAS:")
    print(f"  M\u00e9dia: {sum(durations)/len(durations):.1f}s")
    print(f"  Mediana: {sorted(durations)[len(durations)//2]:.1f}s")
    print(f"  M\u00e1xima: {max(durations):.1f}s")
    print(f"  M\u00ednima (>0): {min(d for d in durations if d > 0):.1f}s")
    print(f"  Chamadas > 60s: {sum(1 for d in durations if d > 60)}")
    print(f"  Chamadas > 120s: {sum(1 for d in durations if d > 120)}")
    print(f"  Chamadas < 10s: {sum(1 for d in durations if d < 10)}")

print(f"\n\U0001f534 MOTIVOS DE DESCONEX\u00c3O:")
for reason, count in hangups_by_reason.most_common(10):
    print(f"  {reason}: {count}")

print(f"\n\u26a0\ufe0f NO VOICE TIMEOUTS: {no_voice_timeouts}")

print(f"\n\U0001f3af EST\u00c1GIOS ALCAN\u00c7ADOS (transi\u00e7\u00f5es):")
for stage, count in stages_reached.most_common(10):
    print(f"  {stage}: {count}")

print(f"\n\u26a0\ufe0f TOP 10 WARNINGS (por m\u00f3dulo):")
for module, count in warnings.most_common(10):
    print(f"  {module}: {count}")

print(f"\n\U0001f534 TOP 10 ERRORS (por m\u00f3dulo):")
for module, count in errors.most_common(10):
    print(f"  {module}: {count}")

if tts_latencies:
    print(f"\n\U0001f50a TTS (ElevenLabs) LAT\u00caNCIA:")
    print(f"  Chamadas TTS: {len(tts_latencies)}")
    print(f"  M\u00e9dia first chunk: {sum(tts_latencies)/len(tts_latencies):.1f}ms")
    print(f"  M\u00e1xima: {max(tts_latencies)}ms")
    print(f"  M\u00ednima: {min(tts_latencies)}ms")
    print(f"  P95: {sorted(tts_latencies)[int(len(tts_latencies)*0.95)]}ms")
    print(f"  Cache HIT: {tts_cache_hits}, MISS: {tts_cache_misses}")
    if tts_cache_hits + tts_cache_misses > 0:
        print(f"  Cache hit rate: {tts_cache_hits/(tts_cache_hits+tts_cache_misses)*100:.1f}%")

if categorizer_latencies:
    print(f"\n\U0001f916 CATEGORIZER (Magic JARVIS) LAT\u00caNCIA:")
    print(f"  Chamadas: {len(categorizer_latencies)}")
    print(f"  M\u00e9dia: {sum(categorizer_latencies)/len(categorizer_latencies):.1f}ms")
    print(f"  M\u00e1xima: {max(categorizer_latencies):.1f}ms")
    print(f"  M\u00ednima: {min(categorizer_latencies):.1f}ms")
    print(f"  P95: {sorted(categorizer_latencies)[int(len(categorizer_latencies)*0.95)]:.1f}ms")
    print(f"  > 100ms: {sum(1 for l in categorizer_latencies if l > 100)}")
    print(f"  > 500ms: {sum(1 for l in categorizer_latencies if l > 500)}")

if audio_file_not_found:
    unique_missing = Counter(audio_file_not_found)
    print(f"\n\U0001f4c1 ARQUIVOS DE \u00c1UDIO N\u00c3O ENCONTRADOS ({len(audio_file_not_found)} ocorr\u00eancias):")
    for path, count in unique_missing.most_common(10):
        print(f"  [{count}x] {path}")

print(f"\n{'='*60}")
print("An\u00e1lise conclu\u00edda.")
