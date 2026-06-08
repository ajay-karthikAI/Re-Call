# Re: Call

Re: Call is a desktop meeting notes app built with Electron, React, FastAPI, Celery, Redis, PostgreSQL, pgvector, OpenAI transcription/analysis/embeddings, and export storage. Local dev can use filesystem storage; production can use S3.

## Prerequisites

- Node 20+
- Python 3.11+
- Docker Desktop
- ffmpeg
- AWS credentials with access to the S3 bucket in `S3_BUCKET_NAME` for production storage
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

6. Start Celery workers from `backend/` in another terminal:

   ```bash
   PYTHONDONTWRITEBYTECODE=1 python -m celery -A tasks.celery_app:celery_app worker --loglevel=info -Q transcription,analysis --concurrency=1 -n recall@%h
   ```

7. Start the desktop app:

   ```bash
   cd ../frontend
   npm install
   RECALL_START_BACKEND=false npm run electron
   ```

The Electron process can spawn FastAPI automatically in development. Use `RECALL_START_BACKEND=false` when you are already running `uvicorn` yourself.

The desktop app opens both the full dashboard and a compact always-on-top overlay window. Use the overlay when you are in Zoom, Microsoft Teams, or Google Meet desktop/web meetings.

## Environment Template

```bash
APP_NAME="Re: Call"
API_PREFIX=/api
BACKEND_PUBLIC_URL=http://127.0.0.1:8000
FRONTEND_ORIGIN=http://127.0.0.1:5173

OPENAI_API_KEY=
OPENAI_CHAT_MODEL=gpt-5
OPENAI_TRANSCRIPTION_MODEL=whisper-1
OPENAI_EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_DIMENSIONS=1536

DATABASE_URL=postgresql+asyncpg://recall:recall@localhost:5433/recall
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_REGION=us-east-1
S3_BUCKET_NAME=
LOCAL_STORAGE_DIR=./storage

ZOOM_CLIENT_ID=
ZOOM_CLIENT_SECRET=
ZOOM_OAUTH_SCOPES=cloud_recording:read:list_recording_files cloud_recording:read:meeting_recording cloud_recording:read:meeting_transcript

GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_OAUTH_SCOPES=openid email profile https://www.googleapis.com/auth/meetings.space.readonly

MICROSOFT_CLIENT_ID=
MICROSOFT_CLIENT_SECRET=
MICROSOFT_TENANT_ID=common
MICROSOFT_OAUTH_SCOPES=offline_access User.Read OnlineMeetings.Read OnlineMeetingTranscript.Read.All

RUN_MIGRATIONS_ON_STARTUP=false
```

Leave `S3_BUCKET_NAME` blank for local development. Audio and generated export files will be copied under `backend/storage/` and served through `/api/files/...`.

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
6. Click the Re: Call extension icon, keep the backend URL as `http://127.0.0.1:8000`, and click Test.

In a meeting, the overlay asks before recording. When you click Record, Chrome asks what to share. Choose the current meeting tab and enable tab audio, then grant microphone permission. When you stop recording, or when the overlay detects the meeting ended, it waits for transcription and then asks whether to export as PowerPoint, PDF, or Markdown.

## Desktop Overlay

The Electron app includes a separate always-on-top Re: Call overlay window. It is designed to float visibly above Zoom, Microsoft Teams, Google Meet, or other meeting apps.

Run it with:

```bash
cd /Users/ajayk/Desktop/ReCall/frontend
RECALL_START_BACKEND=false npm run electron
```

Keep the backend API and Celery worker running in their own terminals. The overlay currently records microphone audio only through Electron MediaRecorder. Native system audio capture is intentionally disabled while the mic-only path is being stabilized.

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
      |         |   |   +--> PPTX / Markdown / PDF export -> local storage or AWS S3
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
