"""In-memory document store with automatic expiry."""

import uuid
import threading
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass

TTL_SECONDS = 3600  # 1 hour


@dataclass
class StoredDocument:
    user_id: uuid.UUID
    filename: str
    data: bytes
    expires_at: datetime


_store: dict[str, StoredDocument] = {}
_lock = threading.Lock()


def store_document(user_id: uuid.UUID, filename: str, data: bytes) -> str:
    """Store a generated document and return its ID.

    Args:
        user_id: Owner of the document.
        filename: Original filename (for Content-Disposition).
        data: Raw file bytes.

    Returns:
        A unique document ID (UUID string).
    """
    doc_id = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=TTL_SECONDS)
    with _lock:
        _cleanup()
        _store[doc_id] = StoredDocument(
            user_id=user_id,
            filename=filename,
            data=data,
            expires_at=expires_at,
        )
    return doc_id


def get_document(doc_id: str, user_id: uuid.UUID) -> tuple[str, bytes] | None:
    """Retrieve a stored document if it belongs to the user and hasn't expired.

    Args:
        doc_id: The document ID returned by store_document.
        user_id: The requesting user's ID.

    Returns:
        (filename, data) tuple, or None if not found / expired / wrong user.
    """
    with _lock:
        _cleanup()
        doc = _store.get(doc_id)
        if doc is None:
            return None
        if doc.user_id != user_id:
            return None
        return doc.filename, doc.data


def _cleanup() -> None:
    """Remove expired entries. Called while holding _lock."""
    now = datetime.now(timezone.utc)
    expired = [k for k, v in _store.items() if v.expires_at <= now]
    for k in expired:
        del _store[k]
