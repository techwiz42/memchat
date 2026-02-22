# Per-User LLM + Local RAG Architecture

## Technical Specification, Threat Model, and Implementation Roadmap

------------------------------------------------------------------------

# 1. Overview

This project implements a web-based chat system combining:

-   Cloud-hosted LLM API
-   Per-user Retrieval-Augmented Generation (RAG)
-   Embedding-only memory persistence
-   Periodic summarization + re-embedding
-   No STM/LTM distinction (initial version)

This system is independent of any DSO-related infrastructure.

------------------------------------------------------------------------

# 2. System Architecture

## High-Level Components

1.  Web Client (React/TypeScript)
2.  API Server (FastAPI)
3.  Embedding Model (API or local)
4.  Vector Store (per-user namespace)
5.  Cloud LLM API
6.  Background Summarization Worker

------------------------------------------------------------------------

# 3. Sequence Diagrams

## 3.1 Chat Request Flow

``` mermaid
sequenceDiagram
    participant User
    participant Browser
    participant API
    participant VectorDB
    participant LLM

    User->>Browser: Send message
    Browser->>API: POST /chat
    API->>VectorDB: Retrieve top-k embeddings
    VectorDB-->>API: Relevant memories
    API->>LLM: Prompt + retrieved context
    LLM-->>API: Response
    API->>VectorDB: Store new embedding
    API-->>Browser: Return response
```

------------------------------------------------------------------------

## 3.2 Memory Summarization Flow

``` mermaid
sequenceDiagram
    participant Worker
    participant VectorDB
    participant LLM

    Worker->>VectorDB: Fetch old memory chunks
    Worker->>LLM: Summarize chunks
    LLM-->>Worker: Summary
    Worker->>VectorDB: Delete old embeddings
    Worker->>VectorDB: Store summary embedding
```

------------------------------------------------------------------------

# 4. Threat Model (Lightweight STRIDE)

## 4.1 Assets

-   User embeddings
-   Conversation content (ephemeral)
-   API keys
-   Access tokens

## 4.2 Threat Categories

### Spoofing

-   Stolen JWT tokens Mitigation:
-   Short-lived access tokens
-   Refresh tokens with rotation

### Tampering

-   Injection into prompt context Mitigation:
-   Input validation
-   Context boundary enforcement

### Repudiation

-   User disputes stored memory Mitigation:
-   Memory audit log (hash-only, optional)

### Information Disclosure

-   Cross-user vector retrieval Mitigation:
-   Strict namespace isolation
-   Per-user encryption key

### Denial of Service

-   Excessive embedding calls Mitigation:
-   Rate limiting
-   Per-user quotas

### Elevation of Privilege

-   API key leakage Mitigation:
-   Environment variable isolation
-   Server-side only key usage

------------------------------------------------------------------------

# 5. Data Security Design

-   Embeddings stored instead of raw text
-   Optional at-rest encryption
-   No memory used for global training
-   Namespace isolation required
-   Access control enforced at API layer

------------------------------------------------------------------------

# 6. Deployment Model

-   Single cloud VM or container
-   PostgreSQL + pgvector OR managed vector DB
-   Background job worker (Celery or simple async scheduler)
-   Reverse proxy (NGINX optional)

------------------------------------------------------------------------

# 7. Performance Targets

-   Retrieval latency: <150ms
-   LLM roundtrip: <3s
-   Embedding write latency: <100ms
-   Memory size target: <10k embeddings per user (initial scale)

------------------------------------------------------------------------

# 8. Roadmap

## Phase 1 --- Core System (Weeks 1--3)

-   [ ] FastAPI chat endpoint
-   [ ] Embedding generation
-   [ ] Vector DB integration
-   [ ] Basic retrieval injection
-   [ ] Per-user namespace isolation

Deliverable: Working RAG chat with persistent embeddings

------------------------------------------------------------------------

## Phase 2 --- Memory Lifecycle (Weeks 4--6)

-   [ ] Background summarization worker
-   [ ] Re-embedding summaries
-   [ ] Memory pruning logic
-   [ ] Simple admin inspection tool

Deliverable: Stable long-running memory system

------------------------------------------------------------------------

## Phase 3 --- Security Hardening (Weeks 7--8)

-   [ ] JWT rotation
-   [ ] Rate limiting
-   [ ] Input sanitization layer
-   [ ] Logging and monitoring
-   [ ] Threat model review

Deliverable: Production-ready MVP

------------------------------------------------------------------------

## Phase 4 --- Advanced Capabilities

-   [ ] Personal embedding model option
-   [ ] User-controlled memory deletion
-   [ ] Edge-device RAG support
-   [ ] Multi-tier memory architecture
-   [ ] Structured memory schema

------------------------------------------------------------------------

# 9. Future Extensions

-   Hybrid symbolic + embedding memory
-   Memory salience scoring
-   Hierarchical context injection
-   Growing context window simulation via retrieval layers

------------------------------------------------------------------------

# 10. Repository Structure (Suggested)

    /frontend
    /backend
        /api
        /memory
        /workers
        /auth
    /docs
    docker-compose.yml
    README.md

------------------------------------------------------------------------

# 11. License

To be determined.

------------------------------------------------------------------------

End of Document.
