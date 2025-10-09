# app/utils/logger.py
import logging
import os
from datetime import datetime
from pathlib import Path

# Create logs directory if it doesn't exist
LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)

# Log file path
LOG_FILE = LOGS_DIR / "trading_app.log"

# Custom formatter
formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s]: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)

# File handler
file_handler = logging.FileHandler(LOG_FILE)
file_handler.setFormatter(formatter)

# Stream handler
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)

# Configure logger
logger = logging.getLogger("trading_app")
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(stream_handler)


def parse_log_line(line: str) -> dict:
    """Parse a single log line into a structured dict."""
    try:
        # Expected format: "2025-10-10 14:30:00 [INFO]: Message"
        parts = line.strip().split(" [", 1)
        if len(parts) != 2:
            return None

        timestamp = parts[0]
        level_and_message = parts[1].split("]: ", 1)

        if len(level_and_message) != 2:
            return None

        level = level_and_message[0]
        message = level_and_message[1]

        return {"timestamp": timestamp, "level": level, "message": message}
    except Exception:
        return None


def get_logs(limit: int = 100, level: str = None) -> list:
    """
    Read logs from file and return as list of dicts.

    Args:
        limit: Maximum number of log entries to return (most recent)
        level: Filter by log level (INFO, ERROR, WARNING, etc.)

    Returns:
        List of log entries as dictionaries
    """
    logs = []

    if not LOG_FILE.exists():
        return logs

    try:
        with open(LOG_FILE, "r") as f:
            lines = f.readlines()

        # Parse lines in reverse order (most recent first)
        for line in reversed(lines):
            if not line.strip():
                continue

            parsed = parse_log_line(line)
            if parsed:
                # Filter by level if specified
                if level and parsed["level"] != level.upper():
                    continue

                logs.append(parsed)

                # Stop if we've reached the limit
                if len(logs) >= limit:
                    break

        return logs

    except Exception as e:
        return [{"error": f"Failed to read logs: {str(e)}"}]


def clear_logs() -> bool:
    """Clear the log file."""
    try:
        if LOG_FILE.exists():
            LOG_FILE.unlink()
            LOG_FILE.touch()
        return True
    except Exception:
        return False
