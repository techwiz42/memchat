# Memchat

A web-based AI chat application with per-user RAG memory, real-time voice conversations, document processing, live camera vision, and web search — deployed at [memchat.cyberiad.ai](https://memchat.cyberiad.ai).

## Features

- **RAG-augmented chat** — Every conversation is grounded in the user's personal memory. Messages are embedded and retrieved via pgvector cosine similarity, giving the LLM long-term context across sessions.
- **Token streaming** — LLM responses stream token-by-token over SSE, rendering as plain text during generation and snapping to formatted markdown on completion.
- **Voice conversations** — Real-time WebRTC voice sessions via Omnia (Ultravox). The voice agent has access to RAG memory, web search, and memory storage tools.
- **Document processing** — Upload PDF, DOCX, XLSX, FDX (screenplays), TXT, Markdown, or images. Files are parsed, chunked, embedded into RAG, and available for in-context editing with format preservation.
- **Live camera vision** — WebSocket-based camera streaming with YOLO object detection and GPT-4o vision analysis triggered on scene changes.
- **Web search** — Google Custom Search integration lets the LLM fetch current information and read web pages.
- **Memory dashboard** — Browse, search (semantic), add, and delete memories at `/memory`.
- **Document library** — View all uploaded documents across conversations, preview content, and manage files at `/documents`.
- **Conversation search** — Full-text search across all messages using PostgreSQL tsvector with highlighted snippets.
- **Conversation export** — Download any conversation as a Markdown file.
- **Message edit and regenerate** — Edit user messages and regenerate assistant responses from any point in the conversation.
- **Custom system prompt** — Per-user instructions injected into every LLM call, configurable in settings.
- **Per-user settings** — Configurable LLM model, temperature, max tokens, history token budget, voice, and language.
- **Background summarization** — A worker runs hourly, summarizing and re-embedding old memories to compress the knowledge base over time.

## Architecture

```
Browser ──── nginx (reverse proxy) ──┬── Next.js frontend (port 3000)
                                     └── FastAPI backend  (port 8000)
                                              │
                                    ┌─────────┼─────────┐
                                    │         │         │
                               PostgreSQL   Redis    OpenAI API
                               (pgvector)  (sessions)  (LLM + embeddings)
```

**Stack**: FastAPI, SQLAlchemy (async), PostgreSQL with pgvector, Redis, Next.js 14, Tailwind CSS, Docker Compose.

**External services**: OpenAI (chat + embeddings), Omnia/Ultravox (voice), Google Custom Search.

## Repository Structure

```
memchat/
├── backend/
│   ├── api/                 # FastAPI routers (11 modules, 40+ endpoints)
│   │   ├── auth.py          # Registration, login, Google OAuth
│   │   ├── chat.py          # Text chat with RAG, streaming, tool calls
│   │   ├── conversations.py # CRUD, full-text search, markdown export
│   │   ├── documents.py     # Upload, parse, chunk, embed
│   │   ├── document_library.py  # Cross-conversation document browsing
│   │   ├── memory.py        # Memory CRUD + semantic search
│   │   ├── settings.py      # Per-user settings
│   │   ├── voice.py         # Omnia WebRTC session lifecycle
│   │   ├── voice_tools.py   # Tools callable by voice agent
│   │   └── vision_ws.py     # Camera WebSocket + YOLO detection
│   ├── auth/                # JWT tokens + Google OAuth 2.0
│   ├── memory/              # Embeddings, vector store, RAG retrieval
│   ├── document/            # Parsing, chunking, editing, generation
│   ├── search/              # Google Search + web page fetching
│   ├── vision/              # YOLO detection + change tracking
│   ├── workers/             # Background memory summarizer
│   ├── models/              # SQLAlchemy ORM (User, Conversation, Message, etc.)
│   ├── config.py            # Settings with Docker secrets support
│   └── main.py              # App entry point, migrations, startup
├── frontend/
│   ├── src/app/             # Next.js app router pages
│   │   ├── chat/            # Main chat interface
│   │   ├── memory/          # Memory dashboard
│   │   ├── documents/       # Document library
│   │   ├── settings/        # User settings
│   │   ├── login/           # Login page
│   │   └── auth/            # OAuth callback
│   ├── src/components/      # ChatWindow, ChatSidebar, MessageBubble, etc.
│   ├── src/hooks/           # useChat, useAuth, useVoiceSession, useVideoStream
│   └── src/lib/             # API client (SSE streaming), auth helpers
├── docker-compose.yml
├── nginx.conf
├── secrets/                 # Docker secrets (not committed)
└── .env                     # Environment config
```

## Setup

### Prerequisites

- Docker and Docker Compose
- An OpenAI API key
- (Optional) Omnia API key for voice, Google OAuth credentials, Google Search API key

### 1. Clone and configure

```bash
git clone <repo-url> memchat
cd memchat
cp .env.example .env
# Edit .env with your domain and preferences
```

### 2. Create secrets

Each secret is a single file in the `secrets/` directory:

```bash
mkdir -p secrets

# Required
openssl rand -hex 32 > secrets/app_secret_key
echo "your-openai-api-key" > secrets/llm_api_key
echo "your-openai-api-key" > secrets/embedding_api_key
echo "your-db-password" > secrets/postgres_password

# Voice (optional — voice features disabled without this)
echo "your-omnia-api-key" > secrets/omnia_api_key

# Google OAuth (optional — Google login disabled without these)
echo "your-client-id" > secrets/google_client_id
echo "your-client-secret" > secrets/google_client_secret

# Web search (optional — search tool disabled without these)
echo "your-google-api-key" > secrets/google_api_key
echo "your-search-engine-id" > secrets/google_search_engine_id
```

### 3. Build and run

```bash
docker compose build
docker compose up -d
```

The app will be available at the URL configured in your nginx/reverse proxy setup.

### 4. Database

Tables and indexes are created automatically on startup via SQLAlchemy `create_all` and inline migrations in `main.py`. No manual migration step needed.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PUBLIC_BASE_URL` | — | Public URL for OAuth callbacks (e.g. `https://memchat.cyberiad.ai`) |
| `POSTGRES_USER` | `memchat` | Database user |
| `POSTGRES_DB` | `memchat` | Database name |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection |
| `LLM_MODEL` | `gpt-4o` | Default chat model |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model |
| `EMBEDDING_DIMENSIONS` | `1536` | Embedding vector size |
| `YOLO_MODEL` | `yolov8n.pt` | Object detection model |
| `YOLO_CONFIDENCE` | `0.35` | Detection threshold |
| `VISION_CHANGE_COOLDOWN` | `10` | Seconds between vision analyses |

## How It Works

### RAG Memory

Every chat exchange is embedded and stored in pgvector. On each new message, the system retrieves the top-5 most similar memories via cosine distance and injects them as context into the LLM prompt. A background worker runs hourly to summarize and re-embed old memories, keeping the knowledge base compact.

### Chat Flow

```
User message
  → Embed query → Vector search (top-5 memories)
  → Build prompt: system prompt + custom instructions + memory context
                   + document context + conversation history + user message
  → Stream LLM response (with tool calls: web search, document creation, etc.)
  → Save messages → Embed exchange in background → Update conversation summary
```

### Voice Sessions

Voice uses Omnia (Ultravox) for WebRTC audio. The voice agent receives the user's recent conversation history and has access to tools for RAG queries, memory storage, and web search. Transcripts are parsed back into user/assistant messages and embedded into memory.

### Document Processing

Uploaded files are parsed (PDF, DOCX, XLSX, FDX, images), chunked into ~500-token segments, batch-embedded, and stored in the vector database. Large documents are scene-split (FDX) or section-split with a table of contents, allowing the LLM to read specific sections on demand rather than loading everything into context.

## Authentication

- **Email/password**: bcrypt-hashed passwords, JWT access tokens (60 min) + refresh tokens (30 days)
- **Google OAuth 2.0**: Server-side code exchange flow with CSRF state validation
- All API calls use `Authorization: Bearer <token>` headers
- Tokens stored in browser localStorage

## API Overview

| Router | Prefix | Endpoints |
|--------|--------|-----------|
| Auth | `/api/auth` | register, login, refresh, me, Google OAuth |
| Chat | `/api/chat` | stream, history, edit, delete, regenerate |
| Conversations | `/api/conversations` | list, create, delete, search, export |
| Documents | `/api/documents` | upload, download, edit |
| Document Library | `/api/documents/library` | list, detail, delete |
| Memory | `/api/memory` | list, search, add, delete |
| Settings | `/api/settings` | get, patch, list voices |
| Voice | `/api/voice` | start, end |
| Voice Tools | `/api/voice-tools` | rag-query, store-memory, web-search, web-fetch |
| Vision | `/ws/vision` | WebSocket (YOLO detection + GPT-4o analysis) |
| Health | `/api/health` | status check |

## Database Schema

**PostgreSQL with pgvector extension.** Key tables:

- **users** — id, email, hashed_password, google_id, display_name
- **user_settings** — agent_name, voice, LLM model, temperature, custom_system_prompt, etc.
- **conversations** — title, summary, timestamps
- **messages** — role, content, source (text/voice/vision), conversation_id
- **memory_embeddings** — content, embedding (Vector 1536), HNSW-indexed
- **conversation_documents** — filename, content, original_bytes, sections_json
- **voice_sessions** — omnia_call_id, status, transcript, summary

**Indexes**: HNSW on embeddings for fast vector search, GIN on message content for full-text search, B-tree on all foreign keys and timestamps.

## License

To be determined.
