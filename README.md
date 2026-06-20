# Re: Call

Re: Call is a desktop meeting notes app built with Electron, React, FastAPI, Celery, Redis, PostgreSQL, pgvector, OpenAI transcription/analysis/embeddings, and export storage. Local dev can use filesystem storage; production should use S3.

## Prerequisites

- Node 20+
- Python 3.11+
- Docker Desktop
- ffmpeg
- AWS region plus credentials or an instance/task role with access to the S3 bucket in `S3_BUCKET_NAME` for production storage
- OpenAI API key

## Local Dev Setup

1. Start Postgres with pgvector and Redis:

   ```bash
   docker compose up -d
   ```

2. Create a backend virtual environment and install dependencies:

   ```bash
   cd backend
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. Create your environment file:

   ```bash
   cp ../.env.example ../.env
   ```

4. Run migrations:

   ```bash
   PYTHONDONTWRITEBYTECODE=1 python -m alembic upgrade head
   ```

5. Start the API:

   ```bash
   PYTHONDONTWRITEBYTECODE=1 python -m uvicorn main:app --host 127.0.0.1 --port 8000
   ```

6. Start the Celery worker from `backend/` in another terminal:

   ```bash
   PYTHONDONTWRITEBYTECODE=1 python -m celery -A tasks.celery_app:celery_app worker --loglevel=info -Q transcription,analysis,live_insights --concurrency=1 -n recall@%h
   ```

   The worker must listen to every routed queue:

   - `transcription`: audio transcription
   - `analysis`: summaries, exports, embeddings, etc.
   - `live_insights`: real-time overlay/live AI cards

7. Start the desktop app:

   ```bash
   cd ../frontend
   npm install
   RECALL_START_BACKEND=false npm run electron
   ```

The Electron process can spawn FastAPI automatically in development. Use `RECALL_START_BACKEND=false` when you are already running `uvicorn` yourself.

The local environment remains unchanged: `.env.example` defaults to `APP_ENV=development`, `BACKEND_PUBLIC_URL=http://127.0.0.1:8000`, `FRONTEND_ORIGIN=http://127.0.0.1:5173`, blank `RECALL_API_TOKEN`, local Postgres/Redis URLs, and filesystem storage. With `RECALL_API_TOKEN` blank, local API auth is disabled.

The desktop app opens both the full dashboard and a compact always-on-top overlay window. Use the overlay when you are in Zoom, Microsoft Teams, or Google Meet desktop/web meetings.

## Desktop Packaging

The existing Electron dev workflow is unchanged:

```bash
cd frontend
RECALL_START_BACKEND=false npm run electron
```

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

Package output is written to `frontend/release/` by default. The package uses `electron-builder`. Packaged Electron keeps using the `app.isPackaged` branch in `frontend/electron/main.js`, which loads `frontend/dist/index.html` from the packaged app. The package scripts build the macOS ScreenCaptureKit helper first, then include it at `Contents/Resources/native/recall-macos-capture` alongside the built `dist/` UI, `electron/` main/preload code, and `public/` assets such as the Re: Call logos.

The packaged app does not embed production secrets or API keys. By default, development and local validation still expect the backend at `http://127.0.0.1:8000`. To point a packaged app at a deployed backend, set `RECALL_API_BASE_URL` and `RECALL_API_TOKEN` when launching Electron. When `APP_ENV=production`, Electron requires `RECALL_API_BASE_URL` to be set and non-local, and requires `RECALL_API_TOKEN`:

```bash
APP_ENV=production RECALL_API_BASE_URL=https://api.your-domain.example RECALL_API_TOKEN=replace-with-a-long-random-token /Applications/Re\ Call.app/Contents/MacOS/Re\ Call
```

For a local backend that is already running, keep automatic spawning off:

```bash
RECALL_API_BASE_URL=http://127.0.0.1:8000 RECALL_START_BACKEND=false /Applications/Re\ Call.app/Contents/MacOS/Re\ Call
```

This packaging config is frontend/Electron-only. If a packaged build is expected to spawn a local Python backend, the backend directory must be made available where Electron looks for it, and the Python runtime, backend dependencies, `ffmpeg`, Redis/Postgres access, and `.env` values must already be present on that machine.

macOS metadata is configured with app ID `com.recall.desktop`, product name `Re: Call`, `Re-Call-*` artifact names, a generated app icon at `frontend/build/icon.icns`, and microphone/screen-capture permission descriptions. Production signing and notarization are intentionally not configured with secrets. For release, add Developer ID signing outside the repo or through CI secrets, enable hardened runtime/entitlements as needed, then add an `@electron/notarize` after-sign step or equivalent `electron-builder` notarization flow with Apple credentials supplied from the release environment.

## Docker Compose

The default Compose workflow still runs only local infrastructure:

```bash
docker compose up -d
```

This starts pgvector Postgres on `127.0.0.1:5433` and Redis on `127.0.0.1:6379`, so the non-Docker backend commands above continue to work.

To run the FastAPI API and Celery worker in Docker too, create `.env` and set at least `OPENAI_API_KEY`:

```bash
cp .env.example .env
RUN_MIGRATIONS_ON_STARTUP=true docker compose --profile app up --build -d
```

The app containers use the same backend code and environment variable names as local dev. Compose overrides container networking so `DATABASE_URL` points to `postgres:5432`, and `REDIS_URL`, `CELERY_BROKER_URL`, and `CELERY_RESULT_BACKEND` point to `redis:6379`.

The API runs:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

The worker runs the existing Celery app on the queues used by recording, transcription, analysis, exports, and live insights:

```bash
celery -A tasks.celery_app:celery_app worker --loglevel=info -Q transcription,analysis,live_insights
```

The backend image includes `ffmpeg`. API and worker share the `app_storage` Docker volume at `/app/storage`, so generated audio, files, and exports survive local container restarts when `S3_BUCKET_NAME` is blank. Treat this filesystem mode as local/dev only unless you are deliberately running a single-host deployment with durable shared storage; cloud production should set `S3_BUCKET_NAME`.

Electron can use the Docker API at `http://127.0.0.1:8000`. When the API is already running in Docker, start Electron with:

```bash
cd frontend
RECALL_START_BACKEND=false npm run electron
```

## Environment

Copy `.env.example` for local development. Its defaults are intentionally local:

```bash
APP_ENV=development
BACKEND_PUBLIC_URL=http://127.0.0.1:8000
FRONTEND_ORIGIN=http://127.0.0.1:5173
VITE_APP_ENV=development
VITE_API_BASE_URL=http://127.0.0.1:8000
RECALL_API_TOKEN=
VITE_RECALL_API_TOKEN=
OPENAI_API_KEY=
DATABASE_URL=postgresql+asyncpg://recall:recall@localhost:5433/recall
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
S3_BUCKET_NAME=
LOCAL_STORAGE_DIR=./storage
```

Leave `S3_BUCKET_NAME` blank for local development. Audio and generated export files will be copied under `backend/storage/` and served through `/api/files/...`.

Do not rely on local container disk for cloud production. Many cloud platforms replace containers during deploys, restarts, autoscaling, or health recovery, and API and worker processes may run on different instances. If `S3_BUCKET_NAME` is blank in that shape of deployment, recordings and generated exports can disappear or become unavailable to another process.

For production/cloud storage, configure:

- `S3_BUCKET_NAME` for the bucket that stores recordings and exports
- `AWS_REGION` for that bucket
- AWS credentials from the deployment secret manager, or an instance/task role with bucket access
- IAM permission to read and write objects for the configured bucket or prefix, for example `s3:GetObject` and `s3:PutObject` on `arn:aws:s3:::your-bucket/your-prefix/*`

For Docker app services, leave the Docker-specific URL values blank to use the bundled Compose Postgres and Redis services. The local `DATABASE_URL` and Redis URLs remain pointed at `localhost` for non-Docker backend development.

## Access Control

Re: Call has a minimal bearer-token deployment gate for the FastAPI backend. It is disabled by default when `RECALL_API_TOKEN` is blank, which keeps local dev, Electron recording, browser-extension recording, chunk uploads, transcription, exports, live insights, and WebSocket updates working without extra setup.

When `RECALL_API_TOKEN` is set, protected HTTP endpoints require:

```http
Authorization: Bearer your-token
```

Protected WebSocket connections pass the same token as a `token` query parameter. The React app does this automatically when a token is configured.

How clients pass the token:

- Backend and Electron runtime: set `RECALL_API_TOKEN` in the environment.
- Vite web UI: set `VITE_RECALL_API_TOKEN` to the same value for builds that talk directly to a protected backend.
- Chrome/Edge extension: enter the same token in the extension popup. Leave it blank for local dev.

This is a basic deployment gate to avoid exposing an unauthenticated public API. It is not multi-user auth, account management, OAuth login, row-level authorization, or a substitute for HTTPS, private networking, secret rotation, and normal production controls.

## Production Environment

Set `APP_ENV=production` only for deployed API, worker, and Electron runtimes. In production mode, backend startup fails fast if required values are missing, invalid, or still pointing to localhost. Explicit `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` are optional if they should reuse `REDIS_URL`, but if either is set it must also be non-local.

Production checklist:

- `APP_ENV=production`
- `BACKEND_PUBLIC_URL` set to the public HTTPS API URL
- `FRONTEND_ORIGIN` set to the deployed frontend origin
- `RECALL_API_TOKEN` set to a long random value of at least 24 characters
- `DATABASE_URL` set to production Postgres, not localhost
- `REDIS_URL` set to production Redis, not localhost
- `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` set only when they should differ from `REDIS_URL`
- `OPENAI_API_KEY` supplied from secrets
- `S3_BUCKET_NAME` set so recordings and exports use S3 instead of local disk
- `AWS_REGION` set for the S3 bucket
- AWS credentials supplied through environment variables, instance/task roles, or the deployment platform
- IAM read/write object access scoped to the configured bucket or prefix
- `VITE_APP_ENV=production`, `VITE_API_BASE_URL`, and `VITE_RECALL_API_TOKEN` set if deploying the Vite web UI outside Electron
- `RECALL_API_BASE_URL` and `RECALL_API_TOKEN` set when Electron should talk to the deployed backend

Example production values use placeholders only:

```bash
APP_ENV=production
BACKEND_PUBLIC_URL=https://api.your-domain.example
FRONTEND_ORIGIN=https://app.your-domain.example
RECALL_API_TOKEN=replace-with-a-long-random-token
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@db.your-domain.example:5432/recall
REDIS_URL=rediss://:PASSWORD@redis.your-domain.example:6379/0
CELERY_BROKER_URL=rediss://:PASSWORD@redis.your-domain.example:6379/0
CELERY_RESULT_BACKEND=rediss://:PASSWORD@redis.your-domain.example:6379/0
OPENAI_API_KEY=sk-...
S3_BUCKET_NAME=your-production-bucket
AWS_REGION=us-east-1
# Leave static keys blank when using an instance/task role.
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
VITE_APP_ENV=production
VITE_API_BASE_URL=https://api.your-domain.example
VITE_RECALL_API_TOKEN=replace-with-the-same-token-if-building-the-web-ui
```

If these values are not ready yet, keep `APP_ENV=development`; production mode is intentionally strict so deployments cannot silently fall back to localhost services.

For manual production worker startup, run one worker that listens to every routed queue:

```bash
celery -A tasks.celery_app:celery_app worker --loglevel=info -Q transcription,analysis,live_insights --concurrency=${CELERY_WORKER_CONCURRENCY:-2}
```

## Export Formats

The Export menu supports:

- PowerPoint (`.pptx`)
- Markdown (`.md`)
- PDF (`.pdf`)

## Transcript Integrations

Re: Call can connect to Zoom, Microsoft Teams, and Google Meet from the dashboard sidebar, sync the provider-created transcript, then run the same Re: Call notes, insights, action items, search embedding, and export pipeline used for recorded calls.

Provider behavior:

- Zoom syncs transcript files from cloud recordings. Zoom must have cloud recording transcription enabled, and the OAuth app needs cloud recording read scopes.
- Google Meet syncs transcript entries from the Google Meet API. Meet transcription must be enabled and finished for the conference record.
- Microsoft Teams syncs transcript `.vtt` content through Microsoft Graph. You must connect a work or school Microsoft account, paste the exact Teams meeting join URL, and your tenant may need admin approval for transcript permissions.

For local OAuth redirects, add these callback URLs to your provider apps:

- Zoom: `http://127.0.0.1:8000/api/integrations/zoom/callback`
- Google: `http://127.0.0.1:8000/api/integrations/meet/callback`
- Microsoft: `http://127.0.0.1:8000/api/integrations/teams/callback`

Manual upload/paste remains available as a fallback for `.vtt`, `.srt`, `.txt`, and `.docx` transcripts.

## Browser Meeting Overlay Extension

Re: Call includes an unpacked Chrome/Edge extension in `extension/`. It adds a visible overlay on:

- Google Meet web
- Microsoft Teams web
- Zoom web client

The extension does not cover the native Zoom or Teams desktop apps. Those need a separate native overlay or platform-specific integration.

To load it locally:

1. Make sure the backend API and Celery worker are running.
2. Open `chrome://extensions` or `edge://extensions`.
3. Turn on Developer mode.
4. Choose Load unpacked.
5. Select `/Users/ajayk/Desktop/ReCall/extension`.
6. Click the Re: Call extension icon, keep the backend URL as `http://127.0.0.1:8000`, leave API token blank for local dev, and click Test. If your backend has `RECALL_API_TOKEN` set, enter the same token in the popup.

In a meeting, the overlay asks before recording. When you click Record, Chrome asks what to share. Choose the current meeting tab and enable tab audio, then grant microphone permission. When you stop recording, or when the overlay detects the meeting ended, it waits for transcription and then asks whether to export as PowerPoint, PDF, or Markdown.

## Desktop Overlay

The Electron app includes a separate always-on-top Re: Call overlay window. It is designed to float visibly above Zoom, Microsoft Teams, Google Meet, or other meeting apps.

Run it with:

```bash
cd /Users/ajayk/Desktop/ReCall/frontend
RECALL_START_BACKEND=false npm run electron
```

Keep the backend API and Celery worker running in their own terminals. On macOS, the overlay now tries to capture both microphone audio and system audio through the native ScreenCaptureKit helper. If the helper is unavailable or macOS permission is missing, recording falls back to microphone-only mode. Set `RECALL_ENABLE_SYSTEM_AUDIO=false` to force mic-only recording.

After the meeting is stopped and processing completes, the overlay asks whether to export as PowerPoint, PDF, or Markdown.

## Architecture

```text
Electron + React
      |
      v
FastAPI REST + WebSocket API
      |
      +------> Redis audio chunk buffer
      |             |
      |             v
      |       Celery Workers
      |         |   |   |
      |         |   |   +--> PPTX / Markdown / PDF export -> local storage (dev) or AWS S3 (production)
      |         |   +------> GPT analysis
      |         +----------> Whisper transcription
      |
      +------> PostgreSQL 16
                    |
                    v
                pgvector
                    |
                    v
              RAG search over past calls
```

## RAG Search

After a meeting completes, Re: Call chunks the transcript, embeds each chunk with `text-embedding-3-large` at 1536 dimensions, and stores vectors in Postgres via pgvector. The search panel sends natural-language questions to:

```http
POST /api/search
{
  "query": "What did we decide about the mobile launch?",
  "limit": 5
}
```

The API embeds the query, runs cosine similarity against transcript chunks, and asks the chat model to answer only from the retrieved meeting context.
