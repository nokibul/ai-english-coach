from __future__ import annotations

from datetime import datetime
from typing import Any

from .database import Database


def getPastSessions(db: Database, user_id: int) -> dict[str, Any]:
    return {"sessions": [serialize_past_session_summary(row) for row in db.list_past_sessions(user_id)]}


def serialize_past_session_summary(row: dict[str, Any]) -> dict[str, Any]:
    session_id = int(row["id"])
    average_mastery = row.get("average_mastery_score")
    mastery_score = (
        round(float(average_mastery) * 100)
        if average_mastery is not None
        else round(float(row.get("mastery_percent") or 0.0))
        if row.get("mastery_percent") is not None
        else None
    )
    return {
        "sessionId": str(session_id),
        "id": session_id,
        "title": _past_session_title(row),
        "imageUrl": f"/api/sessions/{session_id}/image",
        "image_url": f"/api/sessions/{session_id}/image",
        "imageName": row.get("image_name") or "",
        "image_name": row.get("image_name") or "",
        "createdAt": row.get("created_at"),
        "created_at": row.get("created_at"),
        "phrasesLearnedCount": int(row.get("phrases_learned_count") or 0),
        "phrases_learned": int(row.get("phrases_learned_count") or 0),
        "newAssetCount": int(row.get("new_asset_count") or 0),
        "new_asset_count": int(row.get("new_asset_count") or 0),
        "weakAssetCount": int(row.get("weak_asset_count") or 0),
        "weak_asset_count": int(row.get("weak_asset_count") or 0),
        "masteryScore": mastery_score,
        "session_mastery_percent": mastery_score,
    }


def _past_session_title(row: dict[str, Any]) -> str:
    title = str(row.get("title") or "").strip()
    if title:
        return title
    created_at = str(row.get("created_at") or "").strip()
    if created_at:
        try:
            parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            return f"Session from {parsed.strftime('%b')} {parsed.day}"
        except ValueError:
            return "Image Session"
    return "Image Session"
