# Mentra Smart Glasses Integration Plan

## Overview

This document describes how to integrate Mentra smart glasses into Memchat, enabling users to stream live video from their glasses camera and use the glasses microphone for voice conversations — hands-free, from a first-person perspective.

**What this enables:**
- Glasses camera streams live video to Memchat's vision analysis pipeline
- Glasses microphone feeds into Memchat's voice conversation system (Omnia/Ultravox)
- Transcriptions and AI responses are displayed on the glasses HUD
- Users interact with Memchat entirely through their glasses — no phone or browser needed

## Current Memchat Architecture

### Voice (Omnia/Ultravox WebRTC)
- `POST /api/voice/start` creates an Omnia call, returns a `joinUrl`
- Browser joins via WebRTC, sending mic audio directly to Omnia
- Omnia handles STT + LLM + TTS in a real-time voice loop
- On session end, transcript is parsed into Message records and memories are extracted

### Vision (Browser WebSocket)
- Browser captures camera frames as JPEG via `getUserMedia()`
- Frames sent over WebSocket to `ws://.../api/vision/ws?token=...`
- Backend runs YOLO object detection on each frame
- When significant changes are detected, frames are sent to an LLM for scene analysis
- Analysis results are stored as vision messages and fed to the voice agent if active

### Key insight
Both systems currently depend on the **browser** as the media source. The Mentra integration replaces the browser with the glasses as the media source, while keeping the backend pipeline unchanged.

---

## Mentra SDK Primer

MentraOS apps are TypeScript servers that communicate with the glasses via the MentraOS Cloud over WebSocket.

```
MentraOS App Server  <--WebSocket-->  MentraOS Cloud  <--BLE-->  Smart Glasses
```

### App structure

```typescript
import { AppServer, AppSession } from '@mentraos/sdk';

class MemchatGlassesApp extends AppServer {
  // Called when a user launches the app on their glasses
  async onSession(session: AppSession, sessionId: string, userId: string) {
    // session.events   — voice transcription, button presses
    // session.camera   — photo capture, managed video streaming
    // session.audio    — TTS playback, audio file playback
    // session.layouts  — display text/cards on the glasses HUD
    // session.dashboard — persistent status display
    // session.capabilities — check hardware features
  }

  async onStop(sessionId: string, userId: string, reason: string) {
    // cleanup
  }
}
```

### Key APIs we need

| Capability | MentraOS API | Data format |
|---|---|---|
| Live video stream | `session.camera.startManagedStream()` | Returns HLS/DASH/WebRTC URLs |
| Photo capture | `session.camera.requestPhoto()` | Returns `{ buffer, mimeType, size }` |
| Voice transcription | `session.events.onTranscription(cb)` | `{ text, isFinal, transcribeLanguage }` |
| Display text on HUD | `session.layouts.showTextWall(text)` | Plain text string |
| Display card on HUD | `session.layouts.showReferenceCard(title, body)` | Title + body strings |
| Text-to-speech | `session.audio.speak(text, options)` | Text + ElevenLabs voice config |
| Button events | `session.events.onButtonPress(cb)` | Button press data |
| Audio playback | `session.audio.playAudio({ audioUrl })` | URL to audio file |

---

## Integration Architecture

### Option A: MentraOS App as a Bridge (Recommended)

Build a standalone MentraOS app server that acts as a bridge between the glasses and Memchat's existing API. This is the simplest approach — it keeps the existing backend untouched and adds a new service alongside it.

```
Mentra Glasses
    |  (BLE)
MentraOS Cloud
    |  (WebSocket)
Mentra Bridge App (new TypeScript service)
    |  (HTTP/WebSocket)
Memchat Backend (existing, unchanged)
```

#### How it works

1. **User authenticates**: Bridge app maps the MentraOS `userId` (email) to a Memchat JWT token. On first connection, the user authenticates via the glasses HUD (e.g., display a pairing code on glasses, enter it on memchat.cyberiad.ai). The bridge stores the Memchat JWT for subsequent sessions.

2. **Video pipeline**: Bridge starts a managed camera stream, receives the HLS URL, then either:
   - **(a) Frame extraction approach**: Periodically fetches frames from the HLS stream and sends them as JPEG over the existing `/api/vision/ws` WebSocket — mimicking what the browser does today. This requires no backend changes.
   - **(b) Direct photo approach**: Uses `session.camera.requestPhoto()` on a timer (e.g., every 2-3 seconds) and sends each photo buffer to the vision WebSocket. Simpler, lower bandwidth, no HLS parsing needed.

3. **Voice pipeline**: Two sub-options:
   - **(a) Transcription relay**: Use `session.events.onTranscription()` to get text from the glasses' built-in STT, then send the final transcript to `POST /api/chat` or `/api/chat/stream` as a regular text message. Responses are displayed on the HUD via `session.layouts` and spoken via `session.audio.speak()`. This is simpler but loses real-time voice interaction.
   - **(b) Omnia integration**: Start an Omnia voice session via `POST /api/voice/start`, then relay audio between the glasses mic and Omnia. This requires raw audio chunk access from the glasses (via `session.events` audio subscription) and a way to pipe them to Omnia's WebRTC endpoint. More complex but preserves real-time conversational voice.

4. **HUD display**: AI responses are shown on the glasses display:
   - Short responses: `session.layouts.showReferenceCard('Memchat', response)`
   - Long responses: `session.layouts.showTextWall(response)`
   - Status: `session.dashboard.write({ text: "Listening..." })`

### Option B: Direct Backend Integration

Add MentraOS SDK directly to the Memchat backend. This is tighter coupling but fewer moving parts.

This would mean adding a TypeScript MentraOS service alongside the Python FastAPI backend, likely as a separate container in docker-compose. The integration points would be the same as Option A, but communication between the bridge and backend would be in-process or via localhost.

**Recommendation: Option A** — keeps concerns separated, the MentraOS app can be developed and deployed independently, and the existing backend needs zero changes.

---

## Detailed Design: Bridge App

### Project setup

```
mentra-bridge/
  package.json          # @mentraos/sdk dependency
  src/
    index.ts            # AppServer entrypoint
    memchat-client.ts   # HTTP/WS client for Memchat API
    session-handler.ts  # Per-user session logic
  .env                  # API keys
  Dockerfile
```

### Authentication flow

```typescript
// On first glasses session, if no stored Memchat token:
session.layouts.showTextWall('Visit memchat.cyberiad.ai/pair\nYour code: 847291');

// Bridge app exposes GET /pair?code=847291 which the user hits from
// their browser while logged in to Memchat. This links the MentraOS
// userId (email) to a Memchat refresh token.

// On subsequent sessions, the bridge uses the stored refresh token
// to get a fresh access token and proceed automatically.
```

### Vision: periodic photo capture

```typescript
async function startVisionLoop(session: AppSession, memchat: MemchatClient) {
  // Connect to Memchat vision WebSocket
  const visionWs = memchat.connectVisionWebSocket();

  // Capture a photo every 3 seconds
  const interval = setInterval(async () => {
    if (!session.capabilities?.hasCamera) return;

    const photo = await session.camera.requestPhoto({ saveToGallery: false });
    // photo.buffer is an ArrayBuffer of JPEG data
    // Send it as a binary frame to Memchat's vision WebSocket
    visionWs.send(photo.buffer);
  }, 3000);

  return () => clearInterval(interval);
}
```

**Why photos instead of managed stream?** The managed stream returns HLS/DASH URLs designed for video players. Extracting individual frames from an HLS stream requires ffmpeg or similar tooling, adding complexity. Periodic `requestPhoto()` is simpler and matches Memchat's vision pipeline (which processes individual JPEG frames).

**Alternative — managed stream for continuous analysis:**
If we later want continuous video analysis (not just periodic snapshots), we could:
1. Start a managed stream: `session.camera.startManagedStream()`
2. Use the returned HLS URL with an ffmpeg process to extract frames
3. Pipe frames to the vision WebSocket

### Voice: transcription relay (simple path)

```typescript
async function startVoiceRelay(session: AppSession, memchat: MemchatClient) {
  session.layouts.showReferenceCard('Memchat', 'Listening...');

  session.events.onTranscription(async (data) => {
    if (!data.isFinal) {
      // Show interim transcript on HUD
      session.layouts.showTextWall(data.text);
      return;
    }

    // Final transcript — send to Memchat as a chat message
    session.layouts.showReferenceCard('You', data.text);

    const response = await memchat.sendMessage(data.text);

    // Display response on glasses
    session.layouts.showReferenceCard('Memchat', response);

    // Speak the response
    await session.audio.speak(response, {
      model_id: 'eleven_flash_v2_5',  // ~75ms latency
    });
  });
}
```

### Voice: Omnia integration (advanced path)

For real-time conversational voice (interruptions, low latency), we need to pipe audio between glasses and Omnia:

```typescript
async function startOmniaVoiceSession(session: AppSession, memchat: MemchatClient) {
  // 1. Create Omnia session via Memchat API
  const { joinUrl } = await memchat.startVoiceSession();

  // 2. Subscribe to raw audio from glasses mic
  //    (requires MICROPHONE permission + audio chunk subscription)
  await session.updateSubscriptions([
    { type: 'AUDIO_CHUNK', config: { sampleRate: 16000 } }
  ]);

  // 3. Connect to Omnia WebRTC endpoint
  //    This is the complex part — we need a WebRTC client in Node.js
  //    Libraries: werift, node-webrtc, or mediasoup-client
  const omniaConnection = await connectToOmnia(joinUrl);

  // 4. Pipe glasses audio → Omnia
  session.events.onAudioChunk((chunk) => {
    omniaConnection.sendAudio(chunk.buffer);
  });

  // 5. Pipe Omnia TTS audio → glasses
  omniaConnection.onAudio((audioBuffer) => {
    // MentraOS currently supports TTS and URL playback,
    // not raw audio streaming to glasses speaker.
    // May need to buffer and serve as a temporary audio URL.
  });
}
```

**Challenges with the Omnia path:**
- Requires server-side WebRTC (node-webrtc or werift) to connect to Omnia
- Raw audio chunk streaming from glasses may not be fully documented yet
- Piping TTS audio back to glasses speakers requires serving audio as URL
- Latency may be higher with the extra hop (glasses → cloud → bridge → Omnia → bridge → cloud → glasses)

**Recommendation:** Start with the transcription relay approach. It works with the existing APIs and provides a good user experience. Upgrade to Omnia integration later if real-time voice conversation through the glasses becomes a priority.

---

## Implementation Phases

### Phase 1: Core Bridge + Vision
1. Scaffold MentraOS bridge app with `@mentraos/sdk`
2. Register app at console.mentra.glass
3. Implement Memchat API client (auth, chat, vision WebSocket)
4. Implement pairing flow (one-time auth linking)
5. Implement periodic photo capture → vision WebSocket pipeline
6. Display vision analysis results on glasses HUD
7. Deploy as Docker container alongside Memchat

### Phase 2: Voice via Transcription Relay
1. Subscribe to glasses transcription events
2. Send final transcripts to `POST /api/chat/stream`
3. Parse SSE response stream, display on HUD
4. Speak responses via `session.audio.speak()`
5. Handle conversation context (pass `conversation_id`)

### Phase 3: Polish + UX
1. Dashboard status display (connected, listening, thinking...)
2. Button controls (tap to start/stop listening, new conversation)
3. LED feedback (recording indicator, processing indicator)
4. Error handling and reconnection logic
5. Persistent session storage (simpleStorage for conversation state)

### Phase 4: Advanced Voice (Optional)
1. Investigate raw audio chunk access from MentraOS
2. Implement server-side WebRTC client for Omnia
3. Build audio relay pipeline (glasses ↔ Omnia)
4. Test latency and quality

---

## Environment + Deployment

### New service in docker-compose

```yaml
mentra-bridge:
  build: ./mentra-bridge
  environment:
    - MENTRAOS_API_KEY=${MENTRAOS_API_KEY}
    - MEMCHAT_API_URL=http://backend:8000
    - MEMCHAT_WS_URL=ws://backend:8000
    - PORT=3100
  ports:
    - "3100:3100"
  depends_on:
    - backend
```

### Nginx config

The bridge needs to be accessible from the internet (MentraOS Cloud sends webhooks to it):

```nginx
server {
    server_name mentra.cyberiad.ai;

    location / {
        proxy_pass http://localhost:3100;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # SSL via certbot
}
```

### MentraOS Developer Console setup
- Package name: `ai.cyberiad.memchat`
- Public URL: `https://mentra.cyberiad.ai`
- Permissions: MICROPHONE, CAMERA

---

## Open Questions

1. **Raw audio chunks**: Does MentraOS expose `onAudioChunk` for raw PCM audio, or only processed transcription? This determines feasibility of Phase 4 (Omnia integration).

2. **Audio output**: Can we stream raw audio to the glasses speaker, or only TTS/URL playback? Affects whether Omnia's TTS output can be relayed.

3. **Frame rate**: What's the practical limit for `requestPhoto()` frequency? Need to test whether 3-second intervals are sustainable without draining glasses battery.

4. **Offline/reconnection**: How does MentraOS handle network drops? The bridge needs to gracefully handle WebSocket reconnection and resume sessions.

5. **Multi-device**: Can a user have both browser and glasses sessions active simultaneously? Would need to handle duplicate vision/voice inputs.

---

## References

- MentraOS SDK docs: https://docs.mentraglass.com/
- MentraOS GitHub: https://github.com/Mentra-Community/MentraOS
- MentraOS Cloud SDK integration: https://cloud-docs.mentra.glass/cloud-overview/sdk-integration
- Developer Console: https://console.mentra.glass
- Memchat voice API: `backend/api/voice.py`
- Memchat vision WebSocket: `backend/api/vision_ws.py`
