# Re: Call

Re: Call is a desktop meeting-memory app for recording calls, generating live assistance, and turning conversations into searchable notes and exports.

It combines an Electron + React desktop UI with a FastAPI backend, Celery workers, Redis, PostgreSQL + pgvector, OpenAI transcription/analysis/embeddings, local or S3-backed file storage, an unpacked browser meeting overlay extension, and an experimental macOS ScreenCaptureKit helper for system audio.

## Contents

- [What It Does](#what-it-does)
- [Quick Start](#quick-start)
- [Docker Workflows](#docker-workflows)
- [Desktop App And Overlay](#desktop-app-and-overlay)
- [Transcript Integrations](#transcript-integrations)
- [Production Configuration](#production-configuration)
- [Packaging](#packaging)
- [Processing Pipeline](#processing-pipeline)
- [Verification Commands](#verification-commands)

## What It Does

- Records meetings from the Electron dashboard or always-on-top desktop overlay.
- Captures microphone audio everywhere, with experimental macOS system-audio capture when the native helper is available.
- Streams live transcript previews, summaries, risks, action items, suggested answers, and structured chart cards.
- Imports provider transcripts from Zoom, Google Meet, Microsoft Teams, or manual `.vtt`, `.srt`, `.txt`, and `.docx` uploads.
- Generates structured notes with summary, key decisions, next steps, participants, topics, sentiment, and technical/code sections when relevant.
- Exports meeting notes as PowerPoint, Markdown, or PDF.
- Embeds transcript chunks into pgvector for retrieval-augmented search across past meetings.
- Includes an unpacked Chrome/Edge extension for Google Meet web, Teams web, and Zoom web client.

## Stack

- Desktop/frontend: Electron, React, Vite, lucide-react
- Backend: FastAPI, SQLAlchemy async, Alembic, Pydantic settings
- Async work: Celery, Redis
- Data: PostgreSQL 16 with pgvector
- AI: OpenAI chat, Whisper transcription, `text-embedding-3-large`
- Exports/storage: python-pptx, generated Markdown/PDF, local filesystem or AWS S3
- Native helper: Swift 5.9 ScreenCaptureKit executable for macOS 13+

## Repository Layout

```text
.
|-- backend/
|   |-- main.py                 # FastAPI app, CORS, routers, startup migration hook
|   |-- config.py               # Environment settings and production validation
|   |-- database.py             # Async SQLAlchemy, migrations, pgvector extension
|   |-- models.py               # Meeting, integration, transcript chunk tables
|   |-- routes/                 # Recording, meetings, export, integrations, search, files, ws
|   |-- services/               # AI, storage, export, transcript, live insight, RAG services
|   |-- tasks/                  # Celery transcription, analysis, embedding, export tasks
|   `-- migrations/
|-- frontend/
|   |-- electron/               # Main/preload processes, windows, helper spawning
|   |-- src/                    # React dashboard, overlay, hooks, components, styles
|   |-- public/                 # Re: Call logos
|   `-- package.json            # Vite/Electron/electron-builder scripts
|-- extension/                  # Unpacked Chrome/Edge meeting overlay
|-- native/macos-screen-capture/ # macOS ScreenCaptureKit system-audio helper
|-- docker-compose.yml          # Local infra plus optional app profile
|-- docker-compose.app.yml      # Fuller app stack variant
|-- .env.example
`-- PROJECT_CONTEXT.md
```

## Prerequisites

- Node 20+
- Python 3.11+
- Docker Desktop
- ffmpeg for non-Docker backend runs
- OpenAI API key
- Swift toolchain only if you are building the macOS system-audio helper locally
- AWS bucket, region, and credentials or instance/task role for production S3 storage

## Quick Start

Create a local environment file from the repo root and add your OpenAI key:

```bash
cp .env.example .env
```

At minimum, set:

```bash
OPENAI_API_KEY=sk-...
```

Start local infrastructure:

```bash
docker compose up -d
```

This starts:

- PostgreSQL + pgvector on `127.0.0.1:5433`
- Redis on `127.0.0.1:6379`

Set up the backend:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PYTHONDONTWRITEBYTECODE=1 python -m alembic upgrade head
```

Run the API:

```bash
cd backend
source .venv/bin/activate
PYTHONDONTWRITEBYTECODE=1 python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Run the Celery worker in another terminal:

```bash
cd backend
source .venv/bin/activate
PYTHONDONTWRITEBYTECODE=1 python -m celery -A tasks.celery_app:celery_app worker --loglevel=info -Q transcription,analysis,live_insights --concurrency=1 -n recall@%h
```

Run the desktop app in a third terminal:

```bash
cd frontend
npm install
RECALL_START_BACKEND=false RECALL_START_WORKER=false npm run electron
```

The Electron app opens both the full dashboard and a compact always-on-top overlay. The manual three-terminal setup above is easiest to debug. Electron can also spawn the backend and worker automatically when the backend virtual environment is installed and `RECALL_START_BACKEND` / `RECALL_START_WORKER` are not set to `false`.

Check backend health:

```bash
curl -sS http://127.0.0.1:8000/health
```

Expected:

```json
{"status":"ok","app":"Re: Call"}
```

## Local Development Notes

The default `.env.example` is local-development friendly:

```bash
APP_ENV=development
BACKEND_PUBLIC_URL=http://127.0.0.1:8000
FRONTEND_ORIGIN=http://127.0.0.1:5173
VITE_API_BASE_URL=http://127.0.0.1:8000
RECALL_API_TOKEN=
DATABASE_URL=postgresql+asyncpg://recall:recall@localhost:5433/recall
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
S3_BUCKET_NAME=
LOCAL_STORAGE_DIR=./storage
RUN_MIGRATIONS_ON_STARTUP=false
```

When `RECALL_API_TOKEN` is blank, local API auth is disabled.

The worker must listen on every routed queue:

- `transcription`: chunk and full-meeting transcription
- `analysis`: notes, exports, embeddings, and post-processing
- `live_insights`: live summaries, suggested answers, chart cards, and overlay state

## Docker Workflows

Default Compose runs local infrastructure only:

```bash
docker compose up -d
```

To run the API and worker in Docker too:

```bash
cp .env.example .env
# Edit .env and set OPENAI_API_KEY first.
RUN_MIGRATIONS_ON_STARTUP=true docker compose --profile app up --build -d
```

The app profile builds `backend/Dockerfile`, includes `ffmpeg`, runs the API on `${API_PORT:-8000}`, and shares the `app_storage` volume between API and worker at `/app/storage`.

For a fuller app-stack variant with restart policies, persistent Redis append-only data, and a required database password:

```bash
POSTGRES_PASSWORD=replace-me RUN_MIGRATIONS_ON_STARTUP=true docker compose -f docker-compose.app.yml up --build -d
```

When the Docker API is already running, launch Electron against it:

```bash
cd frontend
RECALL_START_BACKEND=false RECALL_START_WORKER=false npm run electron
```

## Desktop App And Overlay

The desktop app has two Electron windows:

- Main dashboard: meeting history, recording controls, notes, transcript, live insights, search, imports, exports, and theme toggle.
- Always-on-top overlay: compact meeting controls plus live cards for answers, charts, risks, actions, objectives, and summary.

On macOS, system audio capture is enabled by default when the helper exists. Re: Call still records microphone audio if the helper is missing or permissions are denied.

Force mic-only mode:

```bash
RECALL_ENABLE_SYSTEM_AUDIO=false
```

Build the native helper locally:

```bash
cd native/macos-screen-capture
CLANG_MODULE_CACHE_PATH=/private/tmp/recall-clang-cache swift build --cache-path /private/tmp/recall-swiftpm-cache
```

The helper uses ScreenCaptureKit and requires macOS permission:

```text
System Settings > Privacy & Security > Screen & System Audio Recording
```

Enable it for the process launching the app, such as Terminal, Electron, or the packaged app.

You can override helper discovery with:

```bash
RECALL_SYSTEM_AUDIO_HELPER_BIN=/absolute/path/to/recall-macos-capture
```

## Browser Meeting Overlay Extension

The unpacked extension in `extension/` works on:

- Google Meet web
- Microsoft Teams web
- Zoom web client

Load it locally:

1. Start the backend API and Celery worker.
2. Open `chrome://extensions` or `edge://extensions`.
3. Enable Developer mode.
4. Choose Load unpacked.
5. Select the `extension/` directory.
6. Open the Re: Call extension popup.
7. Keep the backend URL as `http://127.0.0.1:8000` for local development.
8. Leave the API token blank unless your backend has `RECALL_API_TOKEN` set.

The extension is consent-first: it asks before recording, then Chrome asks which tab to share. Choose the meeting tab and enable tab audio.

The extension does not cover native Zoom or Teams desktop apps. Use the Electron desktop overlay for those.

## Transcript Integrations

Re: Call can sync provider-created transcripts and run them through the same analysis, embeddings, search, and export pipeline as recorded calls.

Supported sources:

- Zoom cloud recording transcripts
- Google Meet conference transcripts
- Microsoft Teams `.vtt` transcripts through Microsoft Graph
- Manual upload or paste for `.vtt`, `.srt`, `.txt`, and `.docx`

Local OAuth callback URLs:

```text
Zoom:      http://127.0.0.1:8000/api/integrations/zoom/callback
Google:    http://127.0.0.1:8000/api/integrations/meet/callback
Microsoft: http://127.0.0.1:8000/api/integrations/teams/callback
```

Provider requirements:

- Zoom needs cloud recording transcription enabled and cloud recording read scopes.
- Google Meet needs transcription enabled and completed for the conference record.
- Microsoft Teams needs a work or school account, an exact Teams meeting join URL, and may require tenant admin approval for transcript permissions.

## Exports

The export menu supports:

- PowerPoint (`pptx`)
- Markdown (`markdown` or `md`)
- PDF (`pdf`)

API endpoints:

```http
POST /api/export/{meeting_id}?format=pptx
GET  /api/export/{meeting_id}/download?format=markdown
```

Chart cards are exported as structured chart sections/slides when possible. Supported chart types are:

- `line_chart`
- `bar_chart`
- `table`
- `timeline`
- `needs_data`

## Search

After processing completes, Re: Call chunks the transcript, embeds each chunk, stores vectors in `transcript_chunks`, and supports natural-language search through:

```http
POST /api/search
{
  "query": "What did we decide about the mobile launch?",
  "limit": 5
}
```

The RAG service retrieves relevant transcript chunks by cosine similarity and asks the configured chat model to answer from the retrieved meeting context.

## Storage

Local development uses filesystem storage when `S3_BUCKET_NAME` is blank. Files are written under `backend/storage/` and served through `/api/files/...`.

Production should use S3:

```bash
S3_BUCKET_NAME=your-production-bucket
AWS_REGION=us-east-1
```

Provide AWS credentials through the deployment secret manager, environment variables, or an instance/task role. The app needs object read/write access for the configured bucket or prefix, for example:

```text
s3:GetObject
s3:PutObject
```

Do not rely on container-local disk for cloud production. API and worker processes may run on different instances, and deployments or restarts can replace container files.

## Access Control

Re: Call has a minimal bearer-token gate for backend access. It is disabled when `RECALL_API_TOKEN` is blank.

When `RECALL_API_TOKEN` is set, protected HTTP routes require:

```http
Authorization: Bearer your-token
```

Protected websocket connections pass the same token as a `token` query parameter. The React app and Electron preload bridge pass the configured token automatically.

Client token configuration:

- Backend and Electron runtime: `RECALL_API_TOKEN`
- Vite web build: `VITE_RECALL_API_TOKEN`
- Browser extension: set the token in the extension popup

This is a deployment gate, not multi-user authentication. Use HTTPS, private networking, secret rotation, and normal production controls for public deployments.

## Production Configuration

Set `APP_ENV=production` only when all production dependencies are ready. The backend fails fast if required values are missing, invalid, or still pointed at localhost.

Production backend checklist:

- `APP_ENV=production`
- `BACKEND_PUBLIC_URL` set to the public HTTPS API URL
- `FRONTEND_ORIGIN` set to the deployed frontend origin
- `RECALL_API_TOKEN` set to a long random value of at least 24 characters
- `DATABASE_URL` set to production Postgres, not localhost
- `REDIS_URL` set to production Redis, not localhost
- `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` set only when they should differ from `REDIS_URL`
- `OPENAI_API_KEY` supplied from secrets
- `S3_BUCKET_NAME` and `AWS_REGION` set for S3 storage
- AWS credentials or role-based access supplied by the runtime

Example:

```bash
APP_ENV=production
BACKEND_PUBLIC_URL=https://api.your-domain.example
FRONTEND_ORIGIN=https://app.your-domain.example
RECALL_API_TOKEN=replace-with-a-long-random-token
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@db.your-domain.example:5432/recall
REDIS_URL=rediss://:PASSWORD@redis.your-domain.example:6379/0
OPENAI_API_KEY=sk-...
S3_BUCKET_NAME=your-production-bucket
AWS_REGION=us-east-1
```

For a deployed Vite web UI:

```bash
VITE_APP_ENV=production
VITE_API_BASE_URL=https://api.your-domain.example
VITE_RECALL_API_TOKEN=replace-with-the-same-token-if-needed
```

For Electron pointed at a deployed backend:

```bash
APP_ENV=production RECALL_API_BASE_URL=https://api.your-domain.example RECALL_API_TOKEN=replace-with-a-long-random-token /Applications/Re\ Call.app/Contents/MacOS/Re\ Call
```

In Electron production mode, `RECALL_API_BASE_URL` is required, must be valid, and must not point to localhost.

## Packaging

Build the Vite frontend only:

```bash
cd frontend
npm run build
```

Create an unpacked Electron app for local validation:

```bash
cd frontend
npm run package
```

Create distributable artifacts:

```bash
cd frontend
npm run dist
```

Package output is written to `frontend/release/`.

Packaging notes:

- `electron-builder` config lives in `frontend/package.json`.
- App ID is `com.recall.desktop`.
- Product name is `Re: Call`.
- macOS artifacts use `Re-Call-*` names and `frontend/build/icon.icns`.
- Package scripts build the macOS ScreenCaptureKit helper first.
- The helper is bundled at `Contents/Resources/native/recall-macos-capture`.
- Production signing and notarization are intentionally not configured with repository secrets.

Important caveat: the packaged app does not yet bundle a Python backend runtime, Python dependencies, Redis, Postgres, ffmpeg, migrations, or secrets. For local validation, run the backend separately and launch the packaged app with:

```bash
RECALL_API_BASE_URL=http://127.0.0.1:8000 RECALL_START_BACKEND=false RECALL_START_WORKER=false /Applications/Re\ Call.app/Contents/MacOS/Re\ Call
```

## Processing Pipeline

Recording flow:

1. Frontend starts a meeting with `POST /api/recording/start`.
2. Mic chunks upload to `POST /api/recording/chunk`.
3. macOS system-audio chunks, when available, upload to `POST /api/recording/system-chunk`.
4. Redis buffers chunk bytes and metadata while live transcription tasks run.
5. Stop calls `POST /api/recording/stop`.
6. The backend stores audio locally or in S3, writes capture diagnostics, clears chunk buffers, and starts the Celery pipeline.

Celery flow:

1. `transcribe_full_task` transcribes mic audio, optional system audio chunks, and merges timed transcript segments.
2. `analyze_meeting_task` writes structured notes and preserves live state.
3. `embed_meeting_task` chunks and embeds the transcript into pgvector.
4. `generate_pptx_task` creates the default PowerPoint export.

Live insight flow:

1. Chunk transcripts update Redis live state.
2. Live memory tracks summary, questions, actions, and key points.
3. Live insight tasks generate overlay cards, risks, suggested answers, and chart cards.
4. Websocket events update the dashboard and overlay.

## API Overview

```text
GET  /health

/api/recording
  POST /start
  POST /chunk
  POST /system-chunk
  POST /stop

/api/meetings
  GET    /
  GET    /{meeting_id}
  GET    /{meeting_id}/live-memory
  DELETE /{meeting_id}

/api/export
  POST /{meeting_id}
  GET  /{meeting_id}/download

/api/integrations
  GET  /connections
  GET  /{provider}/authorize
  GET  /{provider}/callback
  POST /{provider}/sync
  POST /transcript

/api/search
  POST /

/api/files
  GET /...

/api/ws
  Websocket meeting events
```

## Verification Commands

Backend compile:

```bash
cd backend
env PYTHONPYCACHEPREFIX=/private/tmp/recall-pycache .venv/bin/python -m compileall -q .
```

Frontend build:

```bash
cd frontend
npm run build
```

Electron syntax checks:

```bash
cd frontend
node --check electron/main.js
node --check electron/preload.js
```

Native helper build:

```bash
cd native/macos-screen-capture
CLANG_MODULE_CACHE_PATH=/private/tmp/recall-clang-cache swift build --cache-path /private/tmp/recall-swiftpm-cache
```

## Troubleshooting

### `npm error ENOENT Could not read package.json`

Run npm from `frontend/`:

```bash
cd frontend
npm run electron
```

### `Address already in use` on port 8000

Find and stop the old backend process:

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
kill <pid>
```

### Alembic config not found

Run Alembic from `backend/`:

```bash
cd backend
source .venv/bin/activate
PYTHONDONTWRITEBYTECODE=1 python -m alembic upgrade head
```

### `S3_BUCKET_NAME is required`

You are running with `APP_ENV=production`. For local dev, keep `APP_ENV=development` and leave `S3_BUCKET_NAME` blank. For production, configure S3.

### System audio helper unavailable

Build the helper:

```bash
cd native/macos-screen-capture
CLANG_MODULE_CACHE_PATH=/private/tmp/recall-clang-cache swift build --cache-path /private/tmp/recall-swiftpm-cache
```

Then restart Electron. If system audio is still unavailable, check macOS Screen & System Audio Recording permission.

### Computer audio only says `Computer audio`

Current speaker labels for system audio are inferred from transcript text. They are not true acoustic diarization.

## Known Limitations

- macOS system-audio capture is experimental.
- Windows system-audio capture is not implemented yet.
- Speaker labels for system audio are best-effort text inference, not voiceprint diarization.
- Browser extension support is limited to web meeting clients.
- Native Zoom and Teams app coverage depends on the desktop overlay and system audio helper.
- Packaged desktop builds do not yet provision the backend runtime, Redis/Postgres, ffmpeg, migrations, or secrets end to end.
- Production macOS signing and notarization still need a release-environment setup.
- Windows and Linux packaging targets exist in config but have not been fully validated.
- OAuth app setup still requires provider-side configuration and approval depending on account or tenant.
- `OverlayAskBar.jsx` is currently frontend-local placeholder behavior; a backend ask/RAG route is still needed.
- Deleting a meeting removes database history, but storage cleanup for local/S3 audio and generated exports can be improved.
