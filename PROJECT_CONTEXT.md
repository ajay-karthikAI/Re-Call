# Re: Call Project Context For Claude

Last updated: 2026-06-17

This is a handoff summary for giving the Re: Call repo to Claude or another fresh coding session. It intentionally avoids secrets from `.env`. Treat `.env.example`, `README.md`, and the source files as the source of truth when details differ.

## One Paragraph Summary

Re: Call is a desktop meeting-memory app. It records meetings, transcribes them, generates structured notes, live insights, suggested answers, visual chart cards, action items, searchable meeting history, and exports to PPTX, PDF, and Markdown. The app is Electron + React/Vite on the frontend, FastAPI + Celery on the backend, Redis for buffering/tasks/live state, PostgreSQL 16 + pgvector for history/search, OpenAI for transcription/analysis/embeddings, local filesystem or S3 for file storage, and an experimental macOS ScreenCaptureKit helper for system audio.

## Current Product Surface

- Electron desktop app with a full dashboard and a compact always-on-top overlay.
- React/Vite frontend with dark/light theme support and Re: Call branding assets.
- FastAPI backend with recording, meetings, export, integrations, search, file-serving, and websocket routes.
- Celery workers for transcription, analysis, embeddings, PPTX/export work, and live insights.
- Redis for audio chunk buffering, Celery broker/result backend, live transcript/memory/insight state, and overlay card de-duping.
- PostgreSQL with pgvector for meeting records and transcript chunk embeddings.
- OpenAI transcription, chat analysis, and embeddings.
- Local storage under `backend/storage/` when `S3_BUCKET_NAME` is blank; S3 storage when configured.
- Zoom, Google Meet, Microsoft Teams, and manual transcript import paths.
- Browser meeting overlay extension for Google Meet web, Teams web, and Zoom web client.
- Experimental macOS system-audio capture is default-on on macOS and can be disabled with `RECALL_ENABLE_SYSTEM_AUDIO=false`.
- Structured chart card rendering in the overlay, live insights panel, notes panel, Markdown export, PDF export, and PPTX export.

## Repository Layout

```text
ReCall/
  PROJECT_CONTEXT.md
  README.md
  .env.example
  docker-compose.yml          # local infra; optional app profile for API/worker
  docker-compose.app.yml      # fuller app stack with restart policies/password requirement
  backend/
    main.py                   # FastAPI app, CORS, routers, startup migrations flag
    config.py                 # Pydantic settings and production validation
    database.py               # SQLAlchemy async engine/session/migrations/vector extension
    models.py                 # Meeting, IntegrationConnection, TranscriptChunk
    schemas.py
    Dockerfile
    Procfile
    routes/
      recording.py            # start/chunk/system-chunk/stop recording pipeline
      meetings.py             # list/get/delete meetings
      export.py               # PPTX/PDF/Markdown export API
      integrations.py         # Zoom/Meet/Teams/manual transcript import
      search.py               # pgvector-backed RAG search
      files.py                # local/S3 download serving
      ws.py                   # meeting events websocket
    services/
      whisper_service.py
      analysis_service.py
      speaker_service.py
      chart_export_service.py
      export_service.py
      export_formatting.py
      pptx_service.py
      s3_service.py
      provider_transcript_service.py
      transcript_import_service.py
      embedding_service.py
      rag_service.py
      live_memory_service.py
      live_insight_service.py
      overlay_answer_service.py
      overlay_chart_service.py
      events.py
    tasks/
      celery_app.py
      transcribe_task.py
      analyze_task.py
      live_insight_task.py
      embedding_task.py
      pptx_task.py
      task_utils.py
    migrations/
      versions/
        0001_initial.py
        0002_integration_connections.py
  frontend/
    package.json
    electron/
      main.js                 # windows, runtime config, backend/worker spawn, system helper spawn
      preload.js              # safe Electron bridge
    src/
      App.jsx                 # main dashboard shell
      OverlayApp.jsx          # compact overlay shell
      main.jsx
      hooks/
        useRecorder.js        # mic MediaRecorder, chunk upload, system helper coordination
        useWebSocket.js
      components/
        ChartCard.jsx         # shared structured chart rendering helpers
        ExportButton.jsx
        HomeScreen.jsx
        LiveInsightsPanel.jsx
        MeetingHistory.jsx
        NotesPanel.jsx
        RecordingBar.jsx
        SearchBar.jsx
        TranscriptImportPanel.jsx
        TranscriptPane.jsx
        ReCallLogo.jsx
        overlay/
          OverlayAskBar.jsx
          OverlayCard.jsx
          OverlayFeed.jsx
      styles/globals.css
    public/
      recall-light-logo.png
  extension/
    manifest.json
    background.js
    content.js
    popup.html
    popup.js
    popup.css
  native/
    macos-screen-capture/
      Package.swift
      Sources/RecallMacOSCapture/main.swift
    experiments/screencapturekit-audio-test/
      Package.swift
      README.md
      Sources/ScreenCaptureKitAudioTest/main.swift
```

## Local Development

Start local infrastructure:

```bash
cd /Users/ajayk/Desktop/ReCall
docker compose up -d
```

If Docker is not in PATH on this Mac, use:

```bash
/Applications/Docker.app/Contents/Resources/bin/docker compose up -d
```

Backend setup and migrations:

```bash
cd /Users/ajayk/Desktop/ReCall/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PYTHONDONTWRITEBYTECODE=1 python -m alembic upgrade head
```

Run the API:

```bash
cd /Users/ajayk/Desktop/ReCall/backend
source .venv/bin/activate
PYTHONDONTWRITEBYTECODE=1 python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Run one combined worker for normal local dev and manual production starts:

```bash
cd /Users/ajayk/Desktop/ReCall/backend
source .venv/bin/activate
PYTHONDONTWRITEBYTECODE=1 python -m celery -A tasks.celery_app:celery_app worker --loglevel=info -Q transcription,analysis,live_insights --concurrency=1 -n recall@%h
```

This worker must include `transcription` for audio transcription, `analysis` for summaries, exports, embeddings, etc., and `live_insights` for real-time overlay/live AI cards.

Run Electron against a manually started backend:

```bash
cd /Users/ajayk/Desktop/ReCall/frontend
npm install
RECALL_START_BACKEND=false npm run electron
```

Mac desktop defaults to mic + system audio when the helper is available:

```bash
RECALL_START_BACKEND=false npm run electron
```

Force mic-only fallback:

```bash
RECALL_START_BACKEND=false RECALL_ENABLE_SYSTEM_AUDIO=false npm run electron
```

Electron can also spawn the backend and Celery worker itself when `RECALL_START_BACKEND` and `RECALL_START_WORKER` are not set to `false`, but manual backend/worker terminals are easier to debug.

## Environment

Use `.env.example` as the public template. Do not paste real keys into docs or commits.

Important local defaults:

```bash
APP_ENV=development
APP_NAME="Re: Call"
API_PREFIX=/api
BACKEND_PUBLIC_URL=http://127.0.0.1:8000
FRONTEND_ORIGIN=http://127.0.0.1:5173
VITE_APP_ENV=development
VITE_API_BASE_URL=http://127.0.0.1:8000
OPENAI_API_KEY=
OPENAI_CHAT_MODEL=gpt-5
OPENAI_TRANSCRIPTION_MODEL=whisper-1
OPENAI_EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_DIMENSIONS=1536
DATABASE_URL=postgresql+asyncpg://recall:recall@localhost:5433/recall
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
S3_BUCKET_NAME=
LOCAL_STORAGE_DIR=./storage
RUN_MIGRATIONS_ON_STARTUP=false
```

Storage behavior:

- Leave `S3_BUCKET_NAME` blank for local dev.
- When blank, generated files are copied under local backend storage and served through `/api/files/...`.
- In production, `APP_ENV=production` requires `S3_BUCKET_NAME`.

Production behavior:

- `backend/config.py` fails fast when `APP_ENV=production` and key values are blank, invalid, or still localhost.
- Required production values include non-local `BACKEND_PUBLIC_URL`, `FRONTEND_ORIGIN`, `DATABASE_URL`, `REDIS_URL`, `OPENAI_API_KEY`, and `S3_BUCKET_NAME`.
- `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` can be omitted to reuse `REDIS_URL`; if set in production, they must also be non-local.
- Electron production also requires `RECALL_API_BASE_URL` and rejects localhost when `APP_ENV=production`.
- Vite web production should set `VITE_APP_ENV=production` and `VITE_API_BASE_URL`.

OAuth callback URLs for local provider apps:

```text
Zoom:      http://127.0.0.1:8000/api/integrations/zoom/callback
Google:    http://127.0.0.1:8000/api/integrations/meet/callback
Microsoft: http://127.0.0.1:8000/api/integrations/teams/callback
```

## Docker

Default Compose starts local infrastructure only:

```bash
docker compose up -d
```

Services:

- `postgres`: pgvector Postgres 16 on host `127.0.0.1:5433`
- `redis`: Redis 7 on host `127.0.0.1:6379`

Optional API/worker containers are available behind the `app` profile:

```bash
cd /Users/ajayk/Desktop/ReCall
cp .env.example .env
RUN_MIGRATIONS_ON_STARTUP=true docker compose --profile app up --build -d
```

The app containers use `backend/Dockerfile`, include `ffmpeg`, run as a non-root `recall` user, and share the `app_storage` volume at `/app/storage`.

`docker-compose.app.yml` is a fuller app-stack variant with restart policies, persistent Redis append-only data, named app volumes, and a required `POSTGRES_PASSWORD` interpolation check:

```bash
docker compose -f docker-compose.app.yml up --build -d
```

## Desktop Packaging

Frontend package scripts:

```bash
cd /Users/ajayk/Desktop/ReCall/frontend
npm run build
npm run package
npm run dist
```

Packaging details:

- `npm run package` creates an unpacked app for local validation.
- `npm run dist` creates distributable artifacts.
- Output goes to `frontend/release/`.
- `electron-builder` config lives inside `frontend/package.json`.
- App ID is `com.recall.desktop`; product name is `Re: Call`.
- macOS artifacts use `Re-Call-*` names and `frontend/build/icon.icns`.
- Packaged Electron loads `frontend/dist/index.html`.
- Packaged files include `dist/`, `electron/`, `public/`, and `package.json`.
- Production signing/notarization is intentionally not configured with repo secrets.

Important packaging caveat:

- The current packaged app does not embed a Python backend, Python deps, Redis, Postgres, ffmpeg, or secrets.
- The macOS ScreenCaptureKit helper is built by `npm run build:native` and bundled at `Contents/Resources/native/recall-macos-capture`.
- For local validation with an already running backend:

```bash
RECALL_API_BASE_URL=http://127.0.0.1:8000 RECALL_START_BACKEND=false /Applications/Re\ Call.app/Contents/MacOS/Re\ Call
```

- For production:

```bash
APP_ENV=production RECALL_API_BASE_URL=https://api.your-domain.example /Applications/Re\ Call.app/Contents/MacOS/Re\ Call
```

## Recording Pipeline

### Mic Recording Path

Force mic-only mode:

```bash
RECALL_ENABLE_SYSTEM_AUDIO=false
```

Flow:

1. `frontend/src/hooks/useRecorder.js` uses `navigator.mediaDevices.getUserMedia` for mic audio.
2. Browser `MediaRecorder` emits 6-second chunks.
3. Chunks upload to `POST /api/recording/chunk` with timing metadata.
4. Backend stores mic chunks in Redis list `audio:{session_id}` and metadata in `audio_meta:{session_id}`.
5. `transcribe_chunk_task` creates best-effort live transcript previews while recording.
6. On stop, backend concatenates mic chunks into `/tmp/{session_id}.webm`, uploads to local/S3 storage as `meetings/{session_id}/audio.webm`, stores capture diagnostics, clears Redis chunk buffers, and starts the Celery pipeline.
7. `transcribe_full_task` transcribes the full mic file, then analysis, embeddings, and PPTX generation continue through Celery chains/groups.

Mic diagnostics:

- `useRecorder.js` monitors RMS locally.
- If mic looks silent, the UI warns about selected mic, mute switch, and macOS microphone permission.
- Stop payload includes `capture_diagnostics` with mic and optional system-audio diagnostics.

### Experimental macOS System Audio Path

Default-on for macOS unless explicitly disabled with:

```bash
RECALL_ENABLE_SYSTEM_AUDIO=false
```

Native helper:

```text
native/macos-screen-capture/
```

Electron finds the helper from:

```text
RECALL_SYSTEM_AUDIO_HELPER_BIN
process.resourcesPath/native/recall-macos-capture     # packaged candidate
native/macos-screen-capture/.build/debug/recall-macos-capture
native/macos-screen-capture/.build/release/recall-macos-capture
```

Build helper:

```bash
cd /Users/ajayk/Desktop/ReCall/native/macos-screen-capture
CLANG_MODULE_CACHE_PATH=/private/tmp/recall-clang-cache swift build --cache-path /private/tmp/recall-swiftpm-cache
```

Helper behavior:

- macOS only.
- Uses ScreenCaptureKit.
- Requires Screen & System Audio Recording permission for Terminal/Electron/built app.
- Captures display/system audio while excluding Re: Call itself.
- Writes rotating `.m4a` chunks.
- Emits JSON events on stdout for startup, chunk upload, skipped chunks, and errors.
- Measures RMS, peak, duration, start/end offsets.
- Skips silent chunks before upload to avoid fake low-signal Whisper outputs.
- Uploads non-silent chunks to `POST /api/recording/system-chunk`.

Backend system-audio behavior:

- Stores chunks in Redis list `system_audio:{session_id}`.
- Stores metadata in `system_audio_meta:{session_id}`.
- Uploads chunks individually as `meetings/{session_id}/system-audio-{index}.m4a`.
- Live system chunks are transcribed independently and merged into the live transcript segment set.
- Final transcription downloads/transcribes mic and system files separately.
- Mic segments are labeled `You`.
- System segments are initially labeled `Computer audio`, then `backend/services/speaker_service.py` attempts text-inferred speaker labels such as `Person 1`, `Person 2`.
- Final transcript is time-aligned by segment start offsets.

Important limitation:

- `Person 1` / `Person 2` is text-inferred speaker attribution, not true acoustic diarization.
- It can improve meeting-style dialogue but cannot reliably separate voices.
- True diarization will need an acoustic diarization provider/model later.

Desired merged transcript shape:

```text
[00:01] You: ...
[00:04] Person 1: ...
[00:09] Person 2: ...
[00:13] You: ...
```

Silence/hallucination handling:

- Helper skips silent system chunks.
- Backend drops obvious low-signal hallucinations such as `you`, repeated `you`, `thank you`, `thanks`, `ok`, and `bye` when system RMS/peak is low.

## Live Intelligence And Overlay Cards

Key live state files:

```text
backend/services/live_memory_service.py
backend/services/live_insight_service.py
backend/services/overlay_answer_service.py
backend/services/overlay_chart_service.py
backend/tasks/live_insight_task.py
frontend/src/components/LiveInsightsPanel.jsx
frontend/src/components/overlay/OverlayFeed.jsx
frontend/src/components/ChartCard.jsx
```

Live flow:

1. Chunk transcription updates Redis live transcript segments.
2. `live_memory_service.py` keeps per-meeting summary/questions/actions/keys in Redis.
3. `queue_live_insights_if_due` schedules `generate_live_insights_task` on the `live_insights` queue.
4. `live_insight_service.py` asks the OpenAI chat model for current summary, questions, risks, actions, suggested answers, and overlay cards.
5. `overlay_answer_service.py` detects spoken question-like transcript chunks and creates `suggested_answer` cards.
6. `overlay_chart_service.py` detects spoken chart/graph/timeline/breakdown requests and creates structured `chart` cards.
7. Events publish through the meeting websocket route.
8. Frontend merges live state into selected meeting state in `App.jsx` and `OverlayApp.jsx`.

Structured chart cards:

- Stored under `notes_json.live_insights.overlay_cards[]`.
- Card type is `chart`.
- Supported frontend/export chart types are `line_chart`, `bar_chart`, `table`, `timeline`, and `needs_data`.
- `overlay_chart_service.py` may internally consider additional spoken request categories, but `chart_export_service.py` and `ChartCard.jsx` normalize renderable cards to the supported set.
- Chart cards do not generate bitmap images.
- Chart extraction should not invent numbers.
- If the request is clear but required values are missing, use `chart_type: "needs_data"` and a `missing_data_prompt`.
- Follow-up complaints such as "where's the graph?" are filtered so they do not become new chart requests.

Example structured chart card:

```json
{
  "type": "chart",
  "chart_type": "line_chart",
  "title": "Weekly earnings",
  "data": [
    { "label": "Week 1", "value": 12000 },
    { "label": "Week 2", "value": 18000 },
    { "label": "Week 3", "value": 15000 },
    { "label": "Week 4", "value": 22000 }
  ],
  "source_type": "current_meeting",
  "confidence": "high"
}
```

Current chart UI/export status:

- `frontend/src/components/ChartCard.jsx` renders structured chart cards as React/SVG/CSS visuals.
- `OverlayFeed.jsx` shows live chart cards before suggested answers.
- `LiveInsightsPanel.jsx` shows live charts.
- `NotesPanel.jsx` shows structured charts and filters graph-like Python/matplotlib snippets out of the visible code section.
- If final analysis only produced graph code and no structured data, the notes panel shows a `needs_data` fallback instead of presenting Python as the graph.
- `backend/services/chart_export_service.py` normalizes chart cards for exports and filters graph code snippets when chart slides/sections exist.
- `backend/services/pptx_service.py` draws chart slides for bar, line, timeline, table, and missing-data states.
- `backend/services/export_service.py` includes chart sections in Markdown/PDF-style exports.

## Final AI/Processing Pipeline

After stop:

1. `transcribe_full_task`
   - downloads stored mic audio
   - optionally downloads/transcribes system audio chunks
   - labels mic as `You`
   - labels system audio through `speaker_service.py`
   - merges transcript chronologically
   - runs a final chart-card merge pass from full transcript/live memory
2. `analyze_meeting_task`
   - uses `analysis_service.py`
   - writes title, summary, insights, participants, key decisions, action items, next steps, sentiment, topics, and optional technical/code snippets
   - preserves live state keys like `live_insights` and capture diagnostics
3. `embed_meeting_task`
   - chunks transcript
   - stores pgvector embeddings in `transcript_chunks`
4. `generate_pptx_task`
   - creates the default PowerPoint export

## Backend Routes

Main route groups:

- `GET /health`
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
- `/api/ws`
  - meeting status/events websocket

## Frontend Notes

Main dashboard:

- Home screen with Re: Call branding.
- Dark/light theme stored under `recall-theme`.
- History sidebar with pagination and deletion.
- Recording bar with mic meter and warnings.
- Summary/transcript/live-insights dashboard tabs.
- Transcript pane.
- Notes panel.
- Search over past meetings.
- Transcript import panel.
- Export button/menu.

Overlay:

- Always-on-top frameless Electron window.
- Starts/stops recording.
- Can resize between compact/expanded/recording modes through Electron IPC.
- Shows live transcript status, live summary, chart cards, suggested answers, risks, action items, questions, and local ask-response placeholder cards.
- `OverlayAskBar.jsx` is still frontend-local/placeholder; it does not call a backend ask route yet.

Browser extension:

- Folder: `extension/`.
- Load unpacked in Chrome/Edge.
- Works on Google Meet web, Microsoft Teams web, and Zoom web client.
- Does not cover native Zoom/Teams desktop apps.

## Transcript Integrations

Re: Call can connect to provider transcript sources and run the same notes/search/export pipeline used for recorded calls.

Provider behavior:

- Zoom syncs transcript files from cloud recordings. Zoom cloud recording transcription must be enabled, and the OAuth app needs cloud recording read scopes.
- Google Meet syncs transcript entries from the Google Meet API. Meet transcription must be enabled and finished for the conference record.
- Microsoft Teams syncs transcript `.vtt` content through Microsoft Graph. A work/school Microsoft account and exact Teams meeting join URL are expected; tenant admin approval may be needed.
- Manual upload/paste supports `.vtt`, `.srt`, `.txt`, and `.docx` transcript files.

## Search And Data Model

Tables:

- `meetings`
  - title/status/duration/transcript/notes/audio/export keys
  - `notes_json` stores analysis, live state, capture diagnostics, system audio keys, etc.
- `integration_connections`
  - provider OAuth tokens/metadata
- `transcript_chunks`
  - chunk text, start/end time, pgvector embedding

Search:

- `embedding_service.py` creates transcript chunk embeddings.
- `rag_service.py` and `routes/search.py` retrieve relevant chunks for query/search use cases.
- Vector dimensions are 1536 and should match `OPENAI_EMBEDDING_MODEL=text-embedding-3-large` plus `EMBEDDING_DIMENSIONS=1536`.

## Verification Commands

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

For local dev, keep `APP_ENV=development` and leave `S3_BUCKET_NAME` blank. In production, set `S3_BUCKET_NAME` and AWS credentials/roles.

### System audio helper unavailable

Build the helper and run Electron with the feature flag:

```bash
cd /Users/ajayk/Desktop/ReCall/native/macos-screen-capture
CLANG_MODULE_CACHE_PATH=/private/tmp/recall-clang-cache swift build --cache-path /private/tmp/recall-swiftpm-cache

cd /Users/ajayk/Desktop/ReCall/frontend
RECALL_START_BACKEND=false RECALL_ENABLE_SYSTEM_AUDIO=true npm run electron
```

### System audio permission error

Enable macOS permission:

```text
System Settings > Privacy & Security > Screen & System Audio Recording
```

Enable it for Terminal, Electron, or the built app that launches the helper.

### Muted audio transcribes as `you`

This used to happen when silent system chunks were transcribed. Current helper and backend both filter silence/low-signal hallucinations. If it regresses, inspect RMS/peak metadata in `system_audio_keys` and `capture_diagnostics`.

### Computer audio only says `Computer audio`

The app tries to infer `Person 1`, `Person 2`, etc. from transcript text. If it fails, the real fix is acoustic diarization.

### Graph request does not render

The correct UI/export source is:

```text
notes_json.live_insights.overlay_cards[]
```

For cards with:

```json
{ "type": "chart", "chart_type": "line_chart", "data": [...] }
```

the frontend should use `ChartCard.jsx` and exports should use `chart_export_service.py`. Avoid showing Python/matplotlib graph snippets as the primary graph output.

## Known Limitations

- macOS system audio capture is experimental.
- Windows system audio capture is not implemented. Windows likely needs a WASAPI loopback helper using the same chunk upload protocol.
- Speaker labels for computer audio are inferred from transcript text, not acoustic voiceprints.
- Native Zoom/Teams app integration is through desktop overlay/system audio, not official in-app SDK integration.
- Browser extension works only on web meeting clients.
- Packaged desktop app bundles the macOS native helper, but does not yet provision the backend runtime, Redis/Postgres, ffmpeg, or secrets end to end.
- Production Mac signing/notarization is not complete.
- Windows packaging has not been validated.
- OAuth app setup for Zoom/Google/Microsoft still needs provider-side configuration and approval depending on account/tenant.
- `OverlayAskBar.jsx` is frontend-local for now; it needs a backend ask/RAG route to become real.
- Deleting meetings removes history/database rows; storage cleanup for local/S3 audio/export files can be improved later.

## Recommended Next Steps

1. Validate the currently changed packaging/Docker work:
   - `npm run build`
   - `npm run package`
   - Docker app profile with `RUN_MIGRATIONS_ON_STARTUP=true`
2. Test chart cards end to end:
   - speak a chart request with values during a recording
   - verify overlay, Live Insights, Notes, Markdown, PDF, and PPTX all show chart output
   - verify graph-like code snippets are filtered from primary chart UI/export
3. Test system audio on a clean 30-60 second clip:
   - muted system audio should produce no fake transcript
   - YouTube/meeting audio should create system transcript
   - mic speech should appear as `You`
   - final transcript should interleave `You` and `Person N` chronologically
4. Add real backend support for `OverlayAskBar.jsx`:
   - likely route over current meeting transcript/live memory plus `rag_service.py`
   - return answer text, sources, confidence, and card metadata
5. If text-inferred speaker labels are not good enough, add real diarization:
   - options include pyannote, Deepgram, AssemblyAI, AWS Transcribe speaker labels, or another diarization-capable provider
   - target architecture: diarize system audio chunks or a combined system-audio file, then merge diarized turns with mic timestamps
6. Finish Mac distribution:
   - validate bundled Electron app on a clean Mac
   - configure entitlements/permissions
   - sign/notarize through CI or local release environment secrets
7. Add Windows system audio helper:
   - WASAPI loopback capture
   - same protocol as macOS helper: upload chunks with timing/RMS metadata
8. Improve delete cleanup:
   - remove local/S3 audio/export objects when meetings are deleted

## Current Git/Workspace Notes

As of this context refresh, the worktree is not clean. Treat existing changes as user work and do not revert them without explicit instruction.

Current modified files from `git status --short` included:

```text
.env.example
README.md
backend/config.py
backend/main.py
docker-compose.yml
frontend/electron/main.js
frontend/package-lock.json
frontend/package.json
frontend/src/App.jsx
frontend/src/OverlayApp.jsx
frontend/src/components/HomeScreen.jsx
frontend/src/components/ReCallLogo.jsx
frontend/src/components/RecordingBar.jsx
frontend/src/styles/globals.css
```

Current untracked files included:

```text
.dockerignore
backend/Dockerfile
backend/Procfile
docker-compose.app.yml
frontend/build/
frontend/public/recall-light-logo.png
```

`.gitignore` already ignores common Python caches, backend storage, frontend deps/dist, Swift `.build`, SwiftPM metadata, native output, and local env files while preserving `.env.example`.

## Mental Model For Future Work

Keep the app stable by preserving these boundaries:

- Mic-only recording must remain the default fallback when system audio is unavailable.
- System audio is default-on on macOS and can be disabled with `RECALL_ENABLE_SYSTEM_AUDIO=false`.
- The native helper should fail without breaking mic recording.
- Do not locally mix mic/system audio in the browser or helper; store/transcribe separately and merge by timestamps.
- Treat `Person 1` / `Person 2` labels as best-effort until real diarization is added.
- Keep structured chart cards as data, not generated images or Python snippets.
- Prefer shared chart helpers:
  - frontend: `frontend/src/components/ChartCard.jsx`
  - backend/export: `backend/services/chart_export_service.py`
- Preserve live insight keys in `notes_json` when final analysis runs.
- Run focused end-to-end checks after every recording pipeline change:
  - muted system audio should produce no fake system transcript
  - real computer audio should create system transcript
  - mic speech should still appear as `You`
  - stop should not hang
  - export should still work
- Before broad edits, run `git status --short` and avoid reverting unrelated user changes.
