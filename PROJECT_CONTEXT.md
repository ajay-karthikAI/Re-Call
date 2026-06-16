# Re: Call Project Context

Last updated: 2026-06-12

This file is a handoff summary for continuing Re: Call from a fresh account or new Codex session. It intentionally avoids secrets from `.env`.

## What Re: Call Is

Re: Call is a desktop meeting-memory app. It records meetings, transcribes them, generates structured notes/insights/action items, supports export to PPTX/PDF/Markdown, stores searchable meeting history, and can import provider transcripts from Zoom, Google Meet, and Microsoft Teams.

The app currently has:

- Electron desktop app with a full dashboard and always-on-top overlay.
- React/Vite frontend.
- FastAPI backend.
- Celery workers for transcription, analysis, embeddings, and export generation.
- Redis for audio chunk buffering and Celery broker/result backend.
- PostgreSQL 16 with pgvector for meeting search.
- OpenAI transcription, analysis, and embeddings.
- Local filesystem storage when `S3_BUCKET_NAME` is blank; S3 storage when configured.
- macOS ScreenCaptureKit system-audio helper behind a feature flag.
- Live meeting memory and live-insights overlay cards.
- Voice-triggered suggested-answer cards.
- Voice-triggered structured chart cards, with frontend chart rendering still needing polish/fix.

## Project Layout

```text
ReCall/
  backend/
    main.py
    config.py
    database.py
    models.py
    schemas.py
    routes/
      recording.py       # start/chunk/system-chunk/stop recording pipeline
      meetings.py        # list/get/delete meetings
      export.py          # pptx/pdf/markdown export API
      integrations.py    # Zoom/Meet/Teams/manual transcript import
      search.py          # pgvector-backed RAG search
      files.py           # local/S3 download serving
      ws.py              # meeting events websocket
    services/
      whisper_service.py
      analysis_service.py
      speaker_service.py
      export_service.py
      s3_service.py
      provider_transcript_service.py
      transcript_import_service.py
      embedding_service.py
      live_memory_service.py
      live_insight_service.py
      overlay_answer_service.py
      overlay_chart_service.py
    tasks/
      transcribe_task.py
      analyze_task.py
      live_insight_task.py
      embedding_task.py
      pptx_task.py
      celery_app.py
  frontend/
    electron/
      main.js            # Electron windows, system-audio helper spawn
      preload.js         # Electron bridge APIs
    src/
      App.jsx            # main dashboard
      OverlayApp.jsx     # compact overlay
      hooks/useRecorder.js
      components/
        LiveInsightsPanel.jsx
        overlay/
          OverlayCard.jsx
          OverlayFeed.jsx
          OverlayAskBar.jsx
      styles/globals.css
  extension/             # Chrome/Edge web meeting overlay extension
  native/
    experiments/screencapturekit-audio-test/
      # standalone Swift proof-of-concept that writes system-audio-test.wav
    macos-screen-capture/
      # native ScreenCaptureKit helper used by Electron bridge
  docker-compose.yml     # Postgres + Redis
  README.md
```

## Current Runtime Pieces

Local dev needs these running:

1. Docker containers:
   - `postgres` on host port `5433`
   - `redis` on host port `6379`
2. FastAPI backend on `127.0.0.1:8000`
3. Celery worker queue `transcription,analysis`
4. Celery worker queue `live_insights`
5. Electron/Vite UI from `frontend/`

Current normal launch commands:

```bash
cd /Users/ajayk/Desktop/ReCall
docker compose up -d
```

```bash
cd /Users/ajayk/Desktop/ReCall/backend
source .venv/bin/activate
PYTHONDONTWRITEBYTECODE=1 python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

```bash
cd /Users/ajayk/Desktop/ReCall/backend
source .venv/bin/activate
PYTHONDONTWRITEBYTECODE=1 python -m celery -A tasks.celery_app:celery_app worker --loglevel=info -Q transcription,analysis --concurrency=1 -n recall@%h
```

```bash
cd /Users/ajayk/Desktop/ReCall/backend
source .venv/bin/activate
PYTHONDONTWRITEBYTECODE=1 python -m celery -A tasks.celery_app:celery_app worker --loglevel=info -Q live_insights --concurrency=1 -n recall-live@%h
```

Stable mic-only Electron:

```bash
cd /Users/ajayk/Desktop/ReCall/frontend
RECALL_START_BACKEND=false RECALL_ENABLE_SYSTEM_AUDIO=false npm run electron
```

Experimental mic + macOS system-audio Electron:

```bash
cd /Users/ajayk/Desktop/ReCall/frontend
RECALL_START_BACKEND=false RECALL_ENABLE_SYSTEM_AUDIO=true npm run electron
```

If `docker` is not in PATH on this Mac, the Docker binary is usually:

```bash
/Applications/Docker.app/Contents/Resources/bin/docker compose up -d
```

## Environment

Use `.env.example` as the source of truth. Do not paste real keys into handoff notes.

Important local defaults:

```bash
BACKEND_PUBLIC_URL=http://127.0.0.1:8000
FRONTEND_ORIGIN=http://127.0.0.1:5173
DATABASE_URL=postgresql+asyncpg://recall:recall@localhost:5433/recall
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
OPENAI_TRANSCRIPTION_MODEL=whisper-1
OPENAI_CHAT_MODEL=gpt-5
OPENAI_EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_DIMENSIONS=1536
```

Storage behavior:

- Leave `S3_BUCKET_NAME` blank for local dev.
- When blank, files are copied under backend local storage and served through `/api/files/...`.
- If `S3_BUCKET_NAME` is set, AWS credentials are required.

OAuth integrations:

- Zoom callback: `http://127.0.0.1:8000/api/integrations/zoom/callback`
- Google Meet callback: `http://127.0.0.1:8000/api/integrations/meet/callback`
- Microsoft Teams callback: `http://127.0.0.1:8000/api/integrations/teams/callback`

## Recording Pipeline

### Stable Mic-Only Path

Default safest mode:

```bash
RECALL_ENABLE_SYSTEM_AUDIO=false
```

Flow:

1. React hook `frontend/src/hooks/useRecorder.js` gets microphone audio through `navigator.mediaDevices.getUserMedia`.
2. Browser `MediaRecorder` uploads chunks to `POST /api/recording/chunk`.
3. Backend stores mic chunks in Redis key `audio:{session_id}`.
4. On stop, backend joins chunks into `/tmp/{session_id}.webm`, uploads to local/S3 storage as `meetings/{session_id}/audio.webm`.
5. Celery runs `transcribe_full_task`, then analysis, embedding, and PPTX export.

### Experimental macOS System Audio Path

Enabled with:

```bash
RECALL_ENABLE_SYSTEM_AUDIO=true
```

macOS helper:

```text
native/macos-screen-capture/
```

Electron finds and spawns the helper from:

```text
native/macos-screen-capture/.build/debug/recall-macos-capture
```

The helper:

- Uses Apple ScreenCaptureKit.
- Requires macOS Screen & System Audio Recording permission for Terminal/Electron.
- Captures display/system audio, excluding Re: Call itself.
- Writes rotating `.m4a` chunks.
- Measures RMS/peak/duration for each chunk.
- Skips silent chunks before upload to avoid fake `you you you` hallucinations.
- Uploads non-silent chunks to `POST /api/recording/system-chunk`.

Backend then:

- Stores system chunks separately in Redis keys `system_audio:{session_id}` and `system_audio_meta:{session_id}`.
- Uploads system chunks separately as `meetings/{session_id}/system-audio-{index}.m4a`.
- Transcribes mic and system audio separately.
- Uses timestamps/offsets to merge mic and system transcript segments chronologically.
- Labels mic as `You`.
- Runs `backend/services/speaker_service.py` to infer `Person 1`, `Person 2`, etc. for computer-audio segments.

Important limitation:

- Current `Person 1` / `Person 2` labeling is text-inferred speaker attribution, not true acoustic voice diarization.
- It can improve meeting-style dialogue but cannot perfectly separate voices in all cases.
- True diarization will require an acoustic diarization model/provider later.

## ScreenCaptureKit Proof Of Concept

Standalone test app:

```text
native/experiments/screencapturekit-audio-test/
```

Build/run:

```bash
cd /Users/ajayk/Desktop/ReCall/native/experiments/screencapturekit-audio-test
CLANG_MODULE_CACHE_PATH=/private/tmp/recall-clang-cache swift run --cache-path /private/tmp/recall-swiftpm-cache screencapturekit-audio-test
```

Expected output:

```text
output/system-audio-test.wav
```

This was tested successfully: it captured real Mac system audio and QuickTime played the new WAV. Apple Music sometimes appeared to play an older cached file, so use QuickTime for validation.

## Transcript Output Format

When mic + system audio works, the desired merged transcript shape is:

```text
[00:01] You: ...
[00:04] Person 1: ...
[00:09] Person 2: ...
[00:13] You: ...
```

Silence behavior:

- Muted YouTube / no system audio used to produce repeated `you`.
- The helper now skips silent system chunks.
- Backend also drops obvious low-signal hallucinations such as `you`, `you you`, `thank you`, etc.

## Frontend Features

Main dashboard:

- Home screen with Re: Call branding.
- Recording bar with mic meter and warnings.
- Transcript pane.
- Notes/insights pane.
- Search panel over past meetings.
- Transcript import panel for Zoom/Meet/Teams/manual import.
- History sidebar.

Recent dashboard history updates:

- History panel now scrolls.
- Each saved meeting row has a trash button.
- Delete prompts for confirmation.
- Active recording rows cannot be deleted until stopped.
- `Load more` button fetches older meetings beyond the first page.

Overlay:

- Always-on-top Electron window.
- Start/stop recording.
- Export prompt after processing.
- Intended to float visibly over Zoom, Teams, Meet, etc.
- New AI overlay card system:
  - `frontend/src/components/overlay/OverlayCard.jsx`
  - `frontend/src/components/overlay/OverlayFeed.jsx`
  - `frontend/src/components/overlay/OverlayAskBar.jsx`
- Overlay consumes existing meeting/live-insights state, rather than touching the recording path.
- Cards include transcript status, live summary, suggested answers, risks, action items, local ask-response placeholders, and chart cards.
- The local ask bar is frontend-only for now; it does not call a backend route yet.

Browser extension:

- Folder: `extension/`
- Load unpacked in Chrome/Edge.
- Works on Google Meet web, Teams web, Zoom web client.
- Does not cover native Zoom/Teams desktop apps.

## Backend Features

Main route groups:

- `/api/recording`
  - `POST /start`
  - `POST /chunk`
  - `POST /system-chunk`
  - `POST /stop`
- `/api/meetings`
  - list meetings with `limit` / `offset`
  - get meeting by ID
  - delete meeting by ID
- `/api/export`
  - PowerPoint
  - Markdown
  - PDF
- `/api/integrations`
  - Zoom OAuth + transcript sync
  - Google Meet OAuth + transcript sync
  - Microsoft Teams OAuth + transcript sync
  - manual transcript upload/paste
- `/api/search`
  - vector search over embedded transcript chunks
- `/api/files`
  - local/S3 file serving
- WebSocket route for meeting status events.

## AI Pipeline

1. Transcription:
   - `backend/services/whisper_service.py`
   - `transcribe()` for plain text
   - `transcribe_verbose()` for timestamped segment output
2. Speaker attribution:
   - `backend/services/speaker_service.py`
   - labels computer-audio transcript segments as `Person N`
   - text-inferred only, not acoustic diarization
3. Analysis:
   - `backend/services/analysis_service.py`
   - produces JSON with title, summary, insights, decisions, actions, next steps, sentiment, topics, technical/code snippets
4. Embeddings/search:
   - `backend/services/embedding_service.py`
   - chunks transcript and stores vectors in pgvector
5. Live memory:
   - `backend/services/live_memory_service.py`
   - stores per-meeting live transcript, summary, questions, and actions in Redis while recording
6. Live insights:
   - `backend/tasks/live_insight_task.py`
   - `backend/services/live_insight_service.py`
   - runs on the separate Celery queue `live_insights`
   - generates current summary, questions, risks, action items, and suggested answers
   - publishes updates through the existing meeting WebSocket/event path
7. Spoken suggested answers:
   - `backend/services/overlay_answer_service.py`
   - detects question-like transcript chunks
   - creates `suggested_answer` overlay cards with `trigger`, `source_type`, `confidence`, and optional sources
   - throttles/de-dupes repeated questions
8. Voice-triggered charts:
   - `backend/services/overlay_chart_service.py`
   - detects spoken graph/chart/timeline/breakdown requests from live memory
   - creates structured `chart` overlay cards in `live_insights.overlay_cards`
   - does not generate images
   - does not invent numbers
   - defaults automatically when chart type is not specified:
     - weekly earnings/revenue/sales data -> `line_chart`
     - risk severity data -> `bar_chart`
     - rollout/date/order data -> `timeline`
   - returns `needs_data` when the request is clear but the transcript does not include the required values
   - follow-up complaints such as `where's the graph?` are filtered so they do not become new chart requests
9. Export:
   - `backend/services/export_service.py`
   - `backend/services/pptx_service.py`
   - PowerPoint, PDF, Markdown

### Current Chart Status

Backend chart-card generation is working for spoken data. Verified example:

```text
Can you make me a graph of our weekly earnings from last quarter?
Week 1 was $12,000.
Week 2 was $18,000.
Week 3 was $15,000.
Week 4 was $22,000.
Week 5 was $26,000.
Week 6 was $24,000.
```

Expected structured card:

```json
{
  "type": "chart",
  "chart_type": "line_chart",
  "title": "Weekly earnings",
  "data": [
    { "label": "Week 1", "value": 12000 },
    { "label": "Week 2", "value": 18000 },
    { "label": "Week 3", "value": 15000 },
    { "label": "Week 4", "value": 22000 },
    { "label": "Week 5", "value": 26000 },
    { "label": "Week 6", "value": 24000 }
  ],
  "source_type": "current_meeting",
  "confidence": "high"
}
```

Important current UI bug:

- The backend has structured chart cards.
- The frontend/dashboard may still show generated Python/matplotlib `code_snippets` from final analysis instead of rendering the structured chart visually.
- Next fix should be frontend-only: render `notes_json.live_insights.overlay_cards` chart cards as actual SVG/CSS graphs in the overlay/dashboard and avoid using Python code snippets as the graph UI.
- Do not change recorder/transcription/native code for this chart-rendering fix.

## Build And Verification Commands

Backend compile:

```bash
cd /Users/ajayk/Desktop/ReCall/backend
env PYTHONPYCACHEPREFIX=/private/tmp/recall-pycache .venv/bin/python -m compileall -q .
```

Frontend build:

```bash
cd /Users/ajayk/Desktop/ReCall/frontend
npm run build
```

Electron syntax checks:

```bash
cd /Users/ajayk/Desktop/ReCall/frontend
node --check electron/main.js
node --check electron/preload.js
```

Native helper build:

```bash
cd /Users/ajayk/Desktop/ReCall/native/macos-screen-capture
CLANG_MODULE_CACHE_PATH=/private/tmp/recall-clang-cache swift build --cache-path /private/tmp/recall-swiftpm-cache
```

Backend health:

```bash
curl -sS --max-time 5 http://127.0.0.1:8000/health
```

Expected:

```json
{"status":"ok","app":"Re: Call"}
```

## Common Troubleshooting

### `npm error ENOENT Could not read package.json`

You ran npm from the repo root. The frontend package is in `frontend/`.

```bash
cd /Users/ajayk/Desktop/ReCall/frontend
npm run electron
```

### `Address already in use` on port 8000

An old backend process is still running.

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
kill <pid>
```

If normal kill fails:

```bash
kill -9 <pid>
```

### Docker command not found

Use full path:

```bash
/Applications/Docker.app/Contents/Resources/bin/docker compose up -d
```

### Alembic config not found

Run Alembic from `backend/`, not the repo root.

```bash
cd /Users/ajayk/Desktop/ReCall/backend
source .venv/bin/activate
PYTHONDONTWRITEBYTECODE=1 python -m alembic upgrade head
```

### `S3_BUCKET_NAME is required`

For local dev, leave `S3_BUCKET_NAME` blank and use local storage. If using S3, all AWS env vars and bucket permissions must be configured.

### System audio permission error

Enable macOS permission:

```text
System Settings > Privacy & Security > Screen & System Audio Recording
```

Enable it for Terminal and/or the built Electron app.

### Muted audio transcribes as `you`

This was caused by transcribing silent system chunks. The current helper skips silent system chunks and the backend filters obvious low-signal hallucinations.

### Computer audio only says `Computer audio`

The app now tries to label computer speakers as `Person 1`, `Person 2`, etc. If it still fails, that is because text inference is not enough. The next true fix is acoustic diarization.

### Graph request shows Python code instead of a graph

Backend chart-card generation may be working, but the frontend is likely surfacing `notes_json.code_snippets` from final analysis. The correct UI source is:

```text
notes_json.live_insights.overlay_cards[]
```

For cards with:

```json
{ "type": "chart", "chart_type": "line_chart", "data": [...] }
```

the frontend should render a compact visual chart with React/CSS/SVG. It should not show matplotlib/Python code as the primary graph result. This fix belongs in frontend UI files such as:

```text
frontend/src/components/overlay/OverlayFeed.jsx
frontend/src/components/LiveInsightsPanel.jsx
frontend/src/components/NotesPanel.jsx
frontend/src/styles/globals.css
```

## Current Known Limitations

- macOS system audio capture is experimental.
- Windows system audio capture is not implemented yet. Windows likely needs WASAPI loopback in a native helper.
- Speaker labels for computer audio are inferred from transcript text, not acoustic voiceprints.
- Live chart generation produces structured chart cards, but dashboard/overlay rendering still needs to be fixed so users see actual graphs instead of code snippets.
- Native Zoom/Teams app integration is through desktop overlay/system audio, not official in-app SDK integration.
- Browser extension works only on web meeting clients.
- Packaging/notarization for public Mac distribution is not complete.
- Windows packaging is not complete.
- OAuth app setup for Zoom/Google/Microsoft still needs provider-side configuration and approval depending on account/tenant.

## Recommended Next Steps

1. Test the current speaker attribution on a clean 30-60 second YouTube/meeting clip:
   - two distinct computer speakers
   - one or two mic comments from `You`
   - verify chronological `You`, `Person 1`, `Person 2` transcript
2. If text-inferred speaker attribution is not good enough, add real diarization:
   - options: pyannote, Deepgram, AssemblyAI, AWS Transcribe speaker labels, or another diarization-capable service
   - target architecture: diarize system audio chunks or a combined system-audio file, then merge diarized turns with mic timestamps
3. Fix chart rendering in the frontend:
   - inspect the latest meeting payload
   - render `live_insights.overlay_cards` with `type: chart` as SVG/CSS charts
   - support `line_chart`, `bar_chart`, `table`, `timeline`, and `needs_data`
   - show chart cards before generic suggested-answer cards
   - do not show Python/matplotlib code snippets as graph output
   - do not touch recorder/transcription/native code
4. Clean repository before pushing:
   - `.build` artifacts under `native/macos-screen-capture/.build` currently show changes after Swift builds
   - decide whether build artifacts should be committed or ignored
5. Package Mac app:
   - bundle Electron app
   - include native helper binary in resources
   - configure entitlements/permissions
   - sign/notarize for distribution
6. Add Windows system audio helper:
   - WASAPI loopback capture
   - same helper protocol as macOS: upload chunks with timing/RMS metadata
7. Improve deletion cleanup:
   - current UI deletes meetings from history/database
   - storage cleanup for local/S3 audio/export files can be added later

## Git/Workspace Notes

At the time of this handoff, there are uncommitted changes across backend, frontend, and native helper files. Important changed/added files include:

```text
backend/routes/recording.py
backend/services/whisper_service.py
backend/services/live_memory_service.py
backend/services/live_insight_service.py
backend/services/overlay_answer_service.py
backend/services/overlay_chart_service.py
backend/services/speaker_service.py
backend/tasks/transcribe_task.py
backend/tasks/live_insight_task.py
frontend/electron/main.js
frontend/electron/preload.js
frontend/src/App.jsx
frontend/src/OverlayApp.jsx
frontend/src/components/LiveInsightsPanel.jsx
frontend/src/components/MeetingHistory.jsx
frontend/src/components/overlay/
frontend/src/hooks/useRecorder.js
frontend/src/styles/globals.css
native/macos-screen-capture/Sources/RecallMacOSCapture/main.swift
native/experiments/screencapturekit-audio-test/
```

There are also modified Swift `.build` artifacts because the native helper was built locally. Review `.gitignore` and decide whether these should remain tracked before pushing to GitHub.

## Mental Model For Future Work

Keep the app stable by preserving these boundaries:

- Mic-only recording must remain the default fallback.
- System audio stays behind `RECALL_ENABLE_SYSTEM_AUDIO=true`.
- The native helper should fail without breaking mic recording.
- Do not locally mix mic/system audio yet; store/transcribe separately and merge by timestamps.
- Treat `Person 1`/`Person 2` labels as best-effort until real diarization is added.
- Prefer small end-to-end tests after every recording pipeline change:
  - muted system audio should produce no fake system transcript
  - YouTube/meeting audio should create system transcript
  - mic speech should still appear as `You`
  - stop should not hang
  - export should still work
