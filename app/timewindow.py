"""Utilidades de rango horario para consultas del dashboard."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from app.config import AppConfig


def resolve_time_window(
    config: AppConfig,
    preset: str = "last_night",
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
) -> tuple[datetime, datetime]:
    """Resuelve el rango horario en UTC a partir de un preset o fechas."""
    now_local = datetime.now().astimezone()
    now_utc = now_local.astimezone(timezone.utc)

    if preset == "custom" and start and end:
        start_dt = start if start.tzinfo else start.replace(tzinfo=now_local.tzinfo)
        end_dt = end if end.tzinfo else end.replace(tzinfo=now_local.tzinfo)
        return start_dt.astimezone(timezone.utc), end_dt.astimezone(timezone.utc)

    if preset == "last_night":
        n_start = config.monitoring.night_start_hour
        n_end = config.monitoring.night_end_hour
        if now_local.hour >= n_start:
            start_local = now_local.replace(hour=n_start, minute=0, second=0, microsecond=0)
            end_local = now_local
        elif now_local.hour < n_end:
            start_local = (now_local - timedelta(days=1)).replace(
                hour=n_start, minute=0, second=0, microsecond=0
            )
            end_local = now_local
        else:
            start_local = (now_local - timedelta(days=1)).replace(
                hour=n_start, minute=0, second=0, microsecond=0
            )
            end_local = now_local.replace(hour=n_end, minute=0, second=0, microsecond=0)
        return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)

    hours_map = {
        "1h": 1,
        "6h": 6,
        "12h": 12,
        "24h": 24,
        "7d": 24 * 7,
        "30d": 24 * 30,
    }
    hours = hours_map.get(preset, 24)
    return now_utc - timedelta(hours=hours), now_utc


def choose_bucket_seconds(start_dt: datetime, end_dt: datetime) -> int:
    span_hours = max(0.1, (end_dt - start_dt).total_seconds() / 3600.0)
    if span_hours <= 6:
        return 60
    if span_hours <= 24:
        return 120
    if span_hours <= 72:
        return 300
    return 900
