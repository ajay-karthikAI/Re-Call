from __future__ import annotations


def format_duration(duration_seconds: int | float | None) -> str:
    total_seconds = max(0, int(round(float(duration_seconds or 0))))
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"
