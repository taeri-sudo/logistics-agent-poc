"""여러 노드가 공유하는 작은 헬퍼. 그 자체는 그래프 노드가 아니다."""

from __future__ import annotations

from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
