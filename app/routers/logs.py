# app/routers/logs.py
from fastapi import APIRouter, Query
from typing import Optional

from app.utils.logger import get_logs, clear_logs, LOG_FILE

router = APIRouter()


@router.get("/")
async def fetch_logs(
    limit: int = Query(
        100, ge=1, le=1000, description="Number of log entries to return"
    ),
    level: Optional[str] = Query(
        None, description="Filter by log level (INFO, ERROR, WARNING, DEBUG)"
    ),
):
    """
    Fetch application logs.

    Returns the most recent log entries in JSON format.
    """
    logs = get_logs(limit=limit, level=level)

    return {"total": len(logs), "logs": logs, "log_file": str(LOG_FILE)}


@router.get("/levels")
async def get_log_levels():
    """Get count of logs by level."""
    logs = get_logs(limit=10000)  # Get all logs

    level_counts = {}
    for log in logs:
        level = log.get("level", "UNKNOWN")
        level_counts[level] = level_counts.get(level, 0) + 1

    return {"levels": level_counts, "total": len(logs)}


@router.delete("/")
async def delete_logs():
    """Clear all logs."""
    success = clear_logs()

    if success:
        return {"message": "Logs cleared successfully"}
    else:
        return {"message": "Failed to clear logs", "error": True}


@router.get("/recent")
async def get_recent_logs(minutes: int = Query(60, ge=1, le=1440)):
    """Get logs from the last N minutes."""
    from datetime import datetime, timedelta

    all_logs = get_logs(limit=10000)
    cutoff_time = datetime.now() - timedelta(minutes=minutes)

    recent_logs = []
    for log in all_logs:
        try:
            log_time = datetime.strptime(log["timestamp"], "%Y-%m-%d %H:%M:%S")
            if log_time >= cutoff_time:
                recent_logs.append(log)
        except Exception:
            continue

    return {"minutes": minutes, "total": len(recent_logs), "logs": recent_logs}
