"""
Supabase Logger — logs viral hook generation results to a Supabase database.

If Supabase credentials are not configured, all logging calls are gracefully
skipped with a debug-level message.

Expected table schema (create in your Supabase dashboard):

    CREATE TABLE viral_hooks_log (
        id            BIGSERIAL PRIMARY KEY,
        task_id       TEXT NOT NULL,
        video_subject TEXT NOT NULL,
        all_hooks     JSONB NOT NULL,
        evaluated_hooks JSONB NOT NULL,
        selected_hook TEXT NOT NULL,
        selected_score INTEGER NOT NULL,
        created_at    TIMESTAMPTZ DEFAULT NOW()
    );
"""

from typing import List, Optional

from loguru import logger

from app.config import config

_client = None
_initialized = False


def _get_client():
    """Lazily initialize and return the Supabase client, or None."""
    global _client, _initialized

    if _initialized:
        return _client

    _initialized = True

    supabase_cfg = getattr(config, "supabase", {})
    if not isinstance(supabase_cfg, dict):
        supabase_cfg = {}

    url = supabase_cfg.get("supabase_url", "")
    key = supabase_cfg.get("supabase_key", "")

    if not url or not key:
        logger.debug("supabase not configured — hook logging disabled")
        return None

    try:
        from supabase import create_client

        _client = create_client(url, key)
        logger.info("supabase client initialized successfully")
        return _client
    except ImportError:
        logger.warning(
            "supabase package not installed — run: pip install supabase"
        )
        return None
    except Exception as exc:
        logger.error(f"failed to initialize supabase client: {exc}")
        return None


def log_hook_results(
    task_id: str,
    video_subject: str,
    hooks: List[str],
    evaluated_hooks: List[dict],
    selected_hook: str,
    selected_score: int,
) -> bool:
    """Insert a row into the ``viral_hooks_log`` table.

    Returns True on success, False if logging was skipped or failed.
    """
    client = _get_client()
    if client is None:
        return False

    row = {
        "task_id": task_id,
        "video_subject": video_subject,
        "all_hooks": hooks,
        "evaluated_hooks": evaluated_hooks,
        "selected_hook": selected_hook,
        "selected_score": selected_score,
    }

    try:
        result = client.table("viral_hooks_log").insert(row).execute()
        logger.info(f"logged hook results to supabase for task {task_id}")
        return True
    except Exception as exc:
        logger.error(f"failed to log hook results to supabase: {exc}")
        return False
