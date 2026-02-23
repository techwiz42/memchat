# Vision Analysis + Settings Enhancements

## Context

Two sets of changes:

**A. Settings enhancements** — Add GPT-5 models to dropdown, fetch all Omnia languages/voices from API (not hardcoded), add "Agent Name" field so the agent refers to itself by the user's chosen name.

**B. Vision analysis** — Add OpenCV + YOLO-based still image analysis (full suite: detection, segmentation, classification, pose estimation) and live video stream analysis (RTSP/IP camera URLs with real-time MJPEG + SSE).

---

## Part A: Settings Enhancements

### 1. `backend/models/user_settings.py` — Add `agent_name` column

Add `agent_name: Mapped[str] = mapped_column(String(100), default="Memchat")`. Table auto-recreated on startup.

### 2. `backend/api/settings.py` — Add agent_name + languages endpoint

- Add `agent_name` to `SettingsOut` and `SettingsPatch`
- Add `GET /api/settings/languages` — proxy to `OmniaVoiceClient.list_languages()`

### 3. `backend/api/chat.py` — Use agent name in system prompt

Load user settings (already loaded for LLM params). Prepend `"Your name is {agent_name}."` to the system prompt.

### 4. `backend/voice/omnia_config.py` — Use agent name in voice prompt

Accept `agent_name` kwarg in `build_inline_call_config()`. Prepend name to the voice system prompt. Update the greeting to use the name.

### 5. `backend/api/voice.py` — Pass agent_name to config builder

Load user settings (already loaded for voice/language). Pass `agent_name=user_settings.agent_name`.

### 6. `frontend/src/app/settings/page.tsx` — Full rewrite of settings form

- **Agent Name** field at the top (text input)
- **Language dropdown**: Fetch from `/api/settings/languages` (all Omnia languages), not hardcoded
- **Voice dropdown**: Already fetched from API; filter by selected language
- **LLM Models**: Add GPT-5 models: `gpt-5`, `gpt-5-mini`, `gpt-5-turbo` alongside existing ones
- Add `agent_name` to Settings interface and save payload

---

## Part B: Vision Analysis (OpenCV + YOLO Full Suite)

### Architecture

**Still images**: Upload in chat → run 4 YOLO models (detection, segmentation, classification, pose) → return annotated image + text description → embed in RAG.

**Live streams**: Paste RTSP/IP camera URL → backend connects with OpenCV → continuously analyze frames with YOLO detection → serve annotated video as MJPEG + detection events as SSE → on stop, generate summary → embed in RAG.

**Media storage**: Docker volume `/data/media` mounted in backend (rw) and nginx (ro). Annotated images served at `/media/{user_id}/{uuid}.jpg`.

**YOLO models** (all YOLOv8s variants, cached on Docker volume `/data/models`):
- `yolov8s.pt` — object detection (~22MB)
- `yolov8s-seg.pt` — instance segmentation (~24MB)
- `yolov8s-cls.pt` — classification (~11MB)
- `yolov8s-pose.pt` — pose estimation (~23MB)

### New Files

**`backend/vision/__init__.py`** — Package init.

**`backend/vision/detector.py`** — YOLO model loading + inference.

Singleton model loaders download to `/data/models/` on first use. All inference runs in `run_in_executor()` to avoid blocking the event loop.

- `get_detection_model()`, `get_segmentation_model()`, `get_classification_model()`, `get_pose_model()`
- `async analyze_image(image_bytes, user_id) -> ImageAnalysisResult` — full suite on a single image
- `async analyze_frame(frame) -> FrameResult` — detection only (for live stream speed)

**`backend/vision/stream_manager.py`** — Live stream session management.

In-memory manager (single-process, same pattern as summarizer worker):

- `StreamSession` — holds OpenCV capture, latest annotated frame, detection event queue, cumulative counts. `run()` loops at ~2 FPS: read frame (in executor) → YOLO detect (in executor) → encode JPEG → update latest frame → push event.
- `StreamManager` — class-level dict of active sessions. `start()`, `stop()`, `get_session()`, `get_user_stream()`. One active stream per user.

**`backend/vision/storage.py`** — Media file helpers.

- `save_image(user_id, image_bytes) -> url_path` — saves to `/data/media/{user_id}/{uuid}.jpg`, returns `/media/{user_id}/{uuid}.jpg`
- `get_media_dir(user_id) -> Path`

**`backend/api/vision.py`** — API endpoints.

Still image:
- `POST /api/vision/analyze` — multipart (file + optional message). Run full-suite YOLO. Save annotated image. Embed description in RAG. Store user/assistant messages. Return `{ response, image_url, objects, classification, poses }`.

Stream management:
- `POST /api/vision/stream/start` — JSON `{ url }`. Validate URL, enforce one stream per user. Launch background task. Return `{ stream_id, status }`.
- `POST /api/vision/stream/stop` — JSON `{ stream_id }`. Stop session. Generate summary. Embed in RAG. Store assistant message. Return `{ summary, detection_counts }`.
- `GET /api/vision/stream/{id}/feed` — MJPEG `StreamingResponse` of annotated frames.
- `GET /api/vision/stream/{id}/events` — SSE `StreamingResponse` of detection events JSON.
- `GET /api/vision/stream/status` — Current user's active stream info.

**`frontend/src/components/StreamPanel.tsx`** — Live stream viewer.

Overlay panel (same pattern as TranscriptPanel for voice):
- `<img>` tag pointed at MJPEG feed URL
- `EventSource` for detection event log
- Running detection count display
- Stop button

**`frontend/src/hooks/useVideoStream.ts`** — Stream management hook.

- State: `streamId`, `isActive`, `detections[]`, `feedUrl`
- `startStream(url)` → POST /api/vision/stream/start
- `stopStream()` → POST /api/vision/stream/stop → returns summary
- Auto-connects EventSource when streamId is set

### Modified Files

**`backend/requirements.txt`** — Add:
```
ultralytics>=8.3.0
opencv-python-headless>=4.9.0
```

**`backend/Dockerfile`** — Add system deps + CPU-only PyTorch:
```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libglib2.0-0 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# CPU-only PyTorch (avoids ~1.5GB CUDA bloat)
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt
```

**`docker-compose.yml`** — Add volumes + env vars:
```yaml
backend:
  volumes:
    - media_data:/data/media
    - yolo_models:/data/models
  environment:
    YOLO_MODEL_DIR: /data/models
    MEDIA_DIR: /data/media

nginx:
  volumes:
    - media_data:/data/media:ro

volumes:
  pgdata:
  media_data:
  yolo_models:
```

**`nginx.conf`** — Serve media + increase body size:
```nginx
client_max_body_size 20m;

location /media/ {
    alias /data/media/;
    expires 30d;
    add_header Cache-Control "public, immutable";
    autoindex off;
}
```

**`backend/config.py`** — Add vision settings:
```python
self.yolo_model_dir = os.environ.get("YOLO_MODEL_DIR", "/data/models")
self.media_dir = os.environ.get("MEDIA_DIR", "/data/media")
self.yolo_confidence = float(os.environ.get("YOLO_CONFIDENCE", "0.25"))
self.stream_fps = float(os.environ.get("STREAM_FPS", "2.0"))
```

**`backend/main.py`** — Register vision router.

**`frontend/src/hooks/useChat.ts`** — In `sendMessageWithFile()`, detect image MIME type and POST to `/vision/analyze` instead of `/documents/upload`. Parse response to get `image_url` and build assistant message with inline markdown image.

**`frontend/src/components/ChatWindow.tsx`** — Add image types to accepted extensions (`.jpg,.jpeg,.png,.gif,.webp,.bmp`). Show thumbnail preview when image file is staged.

**`frontend/src/components/MessageBubble.tsx`** — Add `components` prop to ReactMarkdown to style `img` with `max-w-full rounded-lg`. Detect `[Uploaded image: ...]` pattern for camera icon.

**`frontend/src/app/chat/page.tsx`** — Import StreamPanel + useVideoStream. Show StreamPanel when stream is active. Add stream URL input in header area.

---

## Files Summary

| Action | File | Part |
|--------|------|------|
| MODIFY | `backend/models/user_settings.py` | A |
| MODIFY | `backend/api/settings.py` | A |
| MODIFY | `backend/api/chat.py` | A |
| MODIFY | `backend/voice/omnia_config.py` | A |
| MODIFY | `backend/api/voice.py` | A |
| MODIFY | `frontend/src/app/settings/page.tsx` | A |
| CREATE | `backend/vision/__init__.py` | B |
| CREATE | `backend/vision/detector.py` | B |
| CREATE | `backend/vision/stream_manager.py` | B |
| CREATE | `backend/vision/storage.py` | B |
| CREATE | `backend/api/vision.py` | B |
| CREATE | `frontend/src/components/StreamPanel.tsx` | B |
| CREATE | `frontend/src/hooks/useVideoStream.ts` | B |
| MODIFY | `backend/requirements.txt` | B |
| MODIFY | `backend/Dockerfile` | B |
| MODIFY | `docker-compose.yml` | B |
| MODIFY | `nginx.conf` | B |
| MODIFY | `backend/config.py` | B |
| MODIFY | `backend/main.py` | B |
| MODIFY | `frontend/src/hooks/useChat.ts` | B |
| MODIFY | `frontend/src/components/ChatWindow.tsx` | B |
| MODIFY | `frontend/src/components/MessageBubble.tsx` | B |
| MODIFY | `frontend/src/app/chat/page.tsx` | B |

## Implementation Order

1. **Part A** — Settings enhancements (agent name, GPT-5 models, dynamic languages/voices)
2. **Infrastructure** — Dockerfile, requirements.txt, docker-compose.yml, nginx.conf, config.py
3. **Backend vision core** — detector.py, storage.py, vision/__init__.py
4. **Still image endpoint** — api/vision.py (POST /analyze), main.py registration
5. **Frontend image upload** — useChat.ts, ChatWindow.tsx, MessageBubble.tsx
6. **Test still images** — upload image, verify annotated result + RAG embedding
7. **Stream backend** — stream_manager.py, stream endpoints in api/vision.py
8. **Stream frontend** — useVideoStream.ts, StreamPanel.tsx, chat/page.tsx
9. **Test live streams** — paste URL, verify MJPEG feed + detection events + summary

## Verification

1. Rebuild Docker images (larger due to PyTorch + ultralytics)
2. Visit `/settings` — agent name field works, languages fetched from Omnia, GPT-5 models in dropdown
3. Set agent name → chat response uses that name, voice greeting uses it
4. Upload image in chat → full-suite annotated image inline + text description
5. Annotated image served via nginx at `/media/...`
6. Paste RTSP URL → stream panel shows live annotated video + detection events
7. Stop stream → summary appears in chat
8. Ask "what did you see?" → RAG retrieves vision analysis descriptions
