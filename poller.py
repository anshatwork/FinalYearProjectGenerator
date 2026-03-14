"""
poller.py — LeetCode Submission Poller

Runs in a background thread. Every 5 minutes it:
  1. Authenticates with LeetCode using a session cookie (no password stored)
  2. Hits the submissions API and filters for Accepted submissions in the last 24 hours
  3. Queues the single most-recent submission if not already processed
"""

import json
import logging
import queue
import threading
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
import os

import asyncio
import sys

from playwright.sync_api import sync_playwright

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
LEETCODE_SESSION = os.getenv("LEETCODE_SESSION", "")
SUBMISSIONS_URL = "https://leetcode.com/api/submissions/?offset=0&limit=20"
POLL_INTERVAL = 5 * 60  # 5 minutes in seconds
PROCESSED_FILE = Path(__file__).parent / "processed.json"
LOG_FILE = Path(__file__).parent / "poller.log"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [POLLER] %(levelname)s — %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("poller")

# ---------------------------------------------------------------------------
# Shared state (written to from poller thread, read from app.py)
#
# IMPORTANT: app.py owns the *canonical* queue and status dict via
# @st.cache_resource.  These module-level objects are only used when
# poller.py is run standalone (e.g. for manual testing).  When called from
# app.py, start_poller() receives the cache_resource-owned objects and
# injects them into the loop so the thread always writes to the same
# objects the UI reads from — even if this module is reimported.
# ---------------------------------------------------------------------------
submission_queue: queue.Queue = queue.Queue(maxsize=1)

poller_status = {
    "running": False,
    "last_checked": "Initializing...",
    "next_poll_at": time.time(),  # Immediate poll on start
    "last_found": None,
    "error": None,
}


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------
def _load_processed() -> list[str]:
    if not PROCESSED_FILE.exists():
        return []
    with open(PROCESSED_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save_processed(processed: list[str]) -> None:
    with open(PROCESSED_FILE, "w", encoding="utf-8") as f:
        json.dump(processed, f, indent=2)


def _mark_processed(submission_id: str) -> None:
    processed = _load_processed()
    if submission_id not in processed:
        processed.append(submission_id)
        _save_processed(processed)


# ---------------------------------------------------------------------------
# LeetCode API fetch
# ---------------------------------------------------------------------------
def _fetch_submissions() -> list[dict]:
    """Use Playwright to inject the session cookie and fetch the submissions API."""
    if not LEETCODE_SESSION:
        logger.error("LEETCODE_SESSION not set in .env — cannot poll")
        return []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()

        # Inject session cookie
        context.add_cookies([
            {
                "name": "LEETCODE_SESSION",
                "value": LEETCODE_SESSION,
                "domain": ".leetcode.com",
                "path": "/",
                "httpOnly": True,
                "secure": True,
                "sameSite": "None",
            }
        ])

        page = context.new_page()

        # Fetch via page.goto and read response as JSON
        response = page.goto(SUBMISSIONS_URL, wait_until="networkidle", timeout=30000)
        if response is None or not response.ok:
            logger.error("Failed to fetch submissions — HTTP %s", response and response.status)
            browser.close()
            return []

        try:
            data = response.json()
        except Exception as exc:
            logger.error("Failed to parse submissions JSON: %s", exc)
            browser.close()
            return []

        browser.close()
        return data.get("submissions_dump", [])


# ---------------------------------------------------------------------------
# Core poll logic
# ---------------------------------------------------------------------------
def _poll_once(
    q: "queue.Queue | None" = None,
    status: "dict | None" = None,
) -> None:
    """Run one poll cycle.

    Args:
        q:      The canonical queue to push into.  Defaults to the
                module-level ``submission_queue`` (useful for standalone runs).
        status: The canonical status dict to update.  Defaults to the
                module-level ``poller_status``.
    """
    _q = q if q is not None else submission_queue
    _s = status if status is not None else poller_status

    logger.info("Polling LeetCode submissions…")
    now = int(time.time())
    cutoff = now - 86400  # 24 hours ago

    submissions = _fetch_submissions()
    if not submissions:
        logger.info("No submissions returned (session may be invalid or API changed)")
        return

    # Filter: Accepted + within last 24 hours
    accepted_recent = [
        s for s in submissions
        if s.get("status_display") == "Accepted" and s.get("timestamp", 0) >= cutoff
    ]

    if not accepted_recent:
        logger.info("No accepted submissions in the last 24 hours")
        return

    # Pick the most recent
    best = max(accepted_recent, key=lambda s: s.get("timestamp", 0))
    submission_id = str(best.get("id", ""))

    # Dedup check
    processed = _load_processed()
    if submission_id in processed:
        logger.info("Submission %s already processed — skipping", submission_id)
        return

    # Build problem slug from title_slug field (falls back to sanitising title)
    slug = best.get("title_slug") or best.get("title", "unknown").lower().replace(" ", "-")

    item = {
        "submission_id": submission_id,
        "problem_title": best.get("title", "Unknown"),
        "problem_slug": slug,
        "problem_url": f"https://leetcode.com/problems/{slug}/",
        "language": best.get("lang", "python3"),
        "code": best.get("code", ""),
        "timestamp": best.get("timestamp", now),
    }

    # Put onto the *canonical* queue (drop old item if full from a previous run)
    if _q.full():
        try:
            _q.get_nowait()
        except queue.Empty:
            pass

    _q.put(item)
    _s["last_found"] = item["problem_title"]
    logger.info("Queued submission: %s (%s) → queue id %s", item["problem_title"], item["language"], id(_q))


# ---------------------------------------------------------------------------
# Background thread
# ---------------------------------------------------------------------------
def _poller_loop(
    q: "queue.Queue | None" = None,
    status: "dict | None" = None,
) -> None:
    """Main loop for the background poller thread.

    ``q`` and ``status`` are the *canonical* objects owned by app.py's
    ``@st.cache_resource``.  Passing them in here means the thread always
    writes to the same objects the UI reads — even if this module is
    reimported after a Streamlit hot-reload.
    """
    # On Windows, sync_playwright() inside a thread requires the ProactorEventLoop
    # to support subprocesses (the browser process).
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    _s = status if status is not None else poller_status
    _q = q if q is not None else submission_queue

    _s["running"] = True
    logger.info(
        "Poller started — interval %d minutes (queue id: %s, status id: %s)",
        POLL_INTERVAL // 60, id(_q), id(_s),
    )

    while _s["running"]:
        _s["error"] = None
        try:
            _poll_once(q=_q, status=_s)
        except Exception as exc:
            logger.exception("Unexpected error during poll: %s", exc)
            _s["error"] = str(exc)

        _s["last_checked"] = datetime.now().isoformat(timespec="seconds")
        next_at = time.time() + POLL_INTERVAL
        _s["next_poll_at"] = next_at
        logger.info("Next poll at %s", datetime.fromtimestamp(next_at).strftime("%H:%M:%S"))
        time.sleep(POLL_INTERVAL)

    logger.info("Poller stopped")


def start_poller(
    q: "queue.Queue | None" = None,
    status: "dict | None" = None,
) -> threading.Thread:
    """Launch the poller background thread.

    Args:
        q:      Canonical Queue to push found submissions into.  Pass the
                queue owned by ``st.cache_resource`` so the thread and the
                Streamlit UI always share the exact same object.
        status: Canonical status dict.  Same rationale as ``q``.

    Safe to call once from app.py.
    """
    t = threading.Thread(
        target=_poller_loop,
        kwargs={"q": q, "status": status},
        name="LeetCodePoller",
        daemon=True,
    )
    t.start()
    return t


def stop_poller() -> None:
    poller_status["running"] = False
