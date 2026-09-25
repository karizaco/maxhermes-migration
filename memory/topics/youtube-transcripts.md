---
description: Canonical%20procedure%20for%20getting%20a%20YouTube%20video's%20transcript%20when%20manual%20captions%20may%20be%20absent.%20Covers%20yt-dlp%20CLI%20vs%20Python%20module%20detection%2C%20the%20429%20workaround%20via%20urllib%20%2B%20signed%20timedtext%20URLs%2C%20and%20the%20VTT%20cleanup%20needed%20for%20YouTube's%20auto-aligned%20captions.
---

# YouTube transcripts — canonical procedure

**Apply when:** user asks for a YouTube video summary / transcript / quote / caption extraction, especially when manual subs may be absent or in a non-English language.

## 0. Probe the environment first
- CLI `yt-dlp` — `Get-Command yt-dlp` or `where.exe yt-dlp`. Often missing on stock Windows even when Python has the module.
- Python module — `python -c "import yt_dlp"`. Usually present if the user installed anything video-related.
- Fallback libs — `youtube-transcript-api` (captions only, no metadata; slower; can hit YouTube's bot wall).

## 1. Get metadata + caption manifest (no download)

```python
import yt_dlp
ydl = yt_dlp.YoutubeDL({'skip_download': True, 'quiet': True})
info = ydl.extract_info(url, download=False)
# info['title'], info['uploader'], info['duration'], info['description']
# info['subtitles']           -> manual subs {lang: [{ext,url,...}]}
# info['automatic_captions']  -> ASR + ASR-translated {lang: [{ext,url,...}]}
```

**Pick the best variant in this order:**
1. Manual subs in the user's requested language → `subtitles[lang]`
2. No manual → auto-generated ASR in the *spoken* language → `automatic_captions[spoken_lang]`
3. No spoken-language ASR either → auto-translated → `automatic_captions[spoken_lang]` with `tlang=<target>` URL (noisier — it's ASR + MT)

## 2. Download the actual file

Prefer yt-dlp's writer (it handles signature refresh + chunked timedtext merging):

```python
ydl = yt_dlp.YoutubeDL({
    'skip_download': True,
    'writesubtitles': True, 'writeautomaticsub': True,
    'subtitleslangs': ['en'], 'subtitlesformat': 'vtt',
    'outtmpl': 'C:/Users/admin/AppData/Local/Temp/yt_%(id)s.%(ext)s',
})
ydl.download([url])
```

**If yt-dlp hits `HTTP 429: Too Many Requests`** (common — Google rate-limits timedtext aggressively):
- The URL inside `info['automatic_captions'][lang][i]['url']` is already a usable timedtext URL with a short-lived signature.
- Fetch it directly with `urllib.request` + a normal browser `User-Agent`. No cookies needed. `fmt=vtt` and `fmt=srv3` both work.
- Save with `.vtt` extension.
- Do NOT retry yt-dlp in a tight loop — it gets throttled harder each attempt. Wait ~60s if you must.

## 3. Parse + clean the VTT

YouTube's auto-aligned captions are noisy. Each cue is repeated 2–3× with `align:start position:%` lines and inline `<HH:MM:SS.mmm>` word-timing tags. Cleanup algorithm:

```python
import re

def parse_vtt(path):
    raw = open(path, encoding='utf-8').read()
    cues = []
    for block in re.split(r'\n\n+', raw.strip()):
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        ts, body = None, []
        for l in lines:
            m = re.match(r'^(\d{2}:\d{2}:\d{2}\.\d{3})\s+-->', l)
            if m:
                ts = m.group(1)
            elif l.startswith(('WEBVTT','Kind:','Language:','NOTE')):
                continue
            else:
                body.append(l)
        if not ts or not body: continue
        # keep only real text lines
        text_lines = []
        for l in body:
            if l.startswith('align:start'): continue
            if re.match(r'^\s*$', l): continue
            text_lines.append(re.sub(r'<[^>]+>', '', l).strip())
        text_lines = [l for l in text_lines if l]
        # dedupe consecutive identical lines (collapses 2-3x repeat)
        dedup = [text_lines[0]] + [l for i,l in enumerate(text_lines[1:],1) if l != text_lines[i-1]]
        cues.append((ts, ' '.join(dedup)))
    return cues
```

Then drop `[music]` / `[applause]` markers and join. **Typical size:** 60-min talk ≈ 400 KB raw → 125 KB / ~24k words after cleanup.

## 4. Summarize honestly
- Always disclose the source language and whether captions were **manual / ASR / auto-translated** (changes the trust level).
- If auto-translated, list the key corrections you made (proper nouns, tool names) — ASR word error rate on tech talks is high, especially for project/protocol names (e.g. `Nostr`, `blossom`, `NIP-90` get mangled to `Noster`, `blossom relay`, `NIP-something`).
- Save the cleaned text next to your session notes (`<temp>/<id>_en.txt`) so the user can re-read or quote it.

## Failure modes worth coding defensively against
- **yt-dlp JS-runtime warning** (`Only deno is enabled by default`) is harmless for caption extraction. Ignore it.
- **Signature expiry**: timedtext URLs typically expire in hours. If you extract_info → sleep → download, the URL may 403. Re-extract immediately before downloading.
- **Auto-translated only**: some videos have manual subs only in the spoken language and no English ASR at all → fall back to translating the original VTT (the timedtext endpoint supports `tlang=`).
- **Very long videos (>2 h)** produce multi-MB VTTs that may truncate shell output. Save to file, then read in chunks.
- **Console encoding** on Windows: never `print()` the raw description to a default cp1252 console — encode errors on diacritics will raise. Use `sys.stdout.reconfigure(encoding='utf-8', errors='replace')` or write to a file.
- **Speaker language detection**: read `info['description']` and `info['title']` to figure out the spoken language *before* asking yt-dlp for subs — guessing `subtitleslangs=['en']` first wastes a round trip if the talk is e.g. Slovak.

## 5. STT fallback for caption-less videos (added Sep 2026)
When no caption track exists at all (rare: new uploads, live-stream archives, region-blocked), use the **`deepgram-stt`** MCP server (registered in mavis, transport `stdio`). It runs `C:\Users\admin\.minimax\bin\deepgram_stt_mcp.py` — a ~120-line Python stdio MCP server wrapping Deepgram's REST `POST /v1/listen` endpoint. The `DEEPGRAM_API_KEY` lives in the MCP server's env block (mavis stores it as a write-only `envKeys` reference, never echoed back).

**Tools exposed:**
- `transcribe_file(path, language?, diarize?, model?)` — local audio/video file. Defaults: en, no diarize, nova-2.
- `transcribe_url(url, language?, diarize?, model?)` — public HTTPS URL; Deepgram fetches it itself, no local download needed.

Both return plain text by default, or speaker-labeled paragraphs (`[Speaker 0] …\n[Speaker 1] …`) when `diarize=true`.

**Workflow for caption-less YouTube videos:**
1. `yt-dlp -x --audio-format mp3 -o <temp>/yt_<id>.mp3 <url>` (audio-only, ~1 MB/min)
2. Call `transcribe_file(path="<temp>/yt_<id>.mp3", language="en")` — returns plain transcript with `[model=…  duration=…s  channels=…]` header
3. Run the existing VTT-cleanup pipeline (drop `[music]` / `[applause]`, dedupe repeated lines) on the returned text

**Why stdio, not HTTP:** mavis spawns the script on first tool call and tears it down on idle. No port, no detached process, no reboot dance, no log files. The mavis runtime already manages 5 of its 6 existing MCPs this way; stdio is the idiomatic pattern for wrapping a single REST API.

## Verified-working stack (Windows, Sep 2026)
- Python 3.14 with `yt_dlp` module installed at `C:/Python314` and `C:/Users/admin/AppData/Roaming/Python/Python314/site-packages/`.
- `urllib.request` works directly against `https://www.youtube.com/api/timedtext?...` with a Mozilla User-Agent header.
- Temp dir `C:/Users/admin/AppData/Local/Temp/` is writable for raw and cleaned transcripts.
- `mcp` Python SDK 2.2.0 installed via `pip install mcp`. Stdio transport via `mcp.server.stdio.stdio_server`.
- Deepgram MCP server at `C:\Users\admin\.minimax\bin\deepgram_stt_mcp.py` (~120 lines, stdlib only + `mcp`).