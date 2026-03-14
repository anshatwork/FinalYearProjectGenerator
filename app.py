"""
app.py — ReelCode Automation Agent Dashboard

Streamlit single-page UI that orchestrates the poller, LLM agent, and
GitHub PR pusher. Launch with: streamlit run app.py
"""

import sys
import time
import threading
from datetime import datetime
from pathlib import Path

import streamlit as st

# ---------------------------------------------------------------------------
# Page config — must be the very first Streamlit call
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="ReelCode Agent",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# Custom CSS — dark, premium feel
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    .stApp {
        background: linear-gradient(135deg, #0d1117 0%, #161b22 50%, #0d1117 100%);
        color: #e6edf3;
    }
    .panel {
        background: rgba(22, 27, 34, 0.9);
        border: 1px solid rgba(48, 54, 61, 0.8);
        border-radius: 12px;
        padding: 20px 24px;
        margin-bottom: 16px;
        backdrop-filter: blur(10px);
    }
    .panel-title {
        font-size: 0.75rem;
        font-weight: 600;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: #7d8590;
        margin-bottom: 12px;
    }
    .status-dot {
        display: inline-block;
        width: 10px;
        height: 10px;
        border-radius: 50%;
        margin-right: 8px;
        animation: pulse 2s infinite;
    }
    .dot-green  { background: #3fb950; box-shadow: 0 0 8px #3fb950; }
    .dot-yellow { background: #d29922; box-shadow: 0 0 8px #d29922; }
    .dot-red    { background: #f85149; box-shadow: 0 0 8px #f85149; }
    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50%       { opacity: 0.5; }
    }
    .metric-label { font-size: 0.7rem; color: #7d8590; letter-spacing: 0.05em; text-transform: uppercase; }
    .metric-value { font-size: 1.1rem; font-weight: 600; color: #e6edf3; }
    .code-preview {
        background: #0d1117;
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 12px;
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.78rem;
        color: #79c0ff;
        white-space: pre-wrap;
        max-height: 200px;
        overflow-y: auto;
    }
    .badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 0.7rem;
        font-weight: 600;
        letter-spacing: 0.05em;
        text-transform: uppercase;
    }
    .badge-green  { background: rgba(63,185,80,0.15);  color: #3fb950; border: 1px solid #3fb95066; }
    .badge-blue   { background: rgba(121,192,255,0.15); color: #79c0ff; border: 1px solid #79c0ff66; }
    .badge-purple { background: rgba(188,140,255,0.15); color: #bc8cff; border: 1px solid #bc8cff66; }
    .log-box {
        background: #010409;
        border: 1px solid #21262d;
        border-radius: 8px;
        padding: 12px 16px;
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.72rem;
        color: #8b949e;
        max-height: 260px;
        overflow-y: auto;
        white-space: pre-wrap;
    }
    /* Hide Streamlit branding */
    #MainMenu, footer, header { visibility: hidden; }
    div.block-container { padding-top: 1.5rem; padding-bottom: 1rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Lazy imports (after page_config is set)
# ---------------------------------------------------------------------------
import poller as poller_module
from agent import run_agent
from github_push import push_to_github

LOG_FILE = Path(__file__).parent / "poller.log"

# ---------------------------------------------------------------------------
# Background Poller Singleton (survives reruns and module reloads)
# ---------------------------------------------------------------------------
@st.cache_resource
def get_poller_resources():
    """Create the canonical queue & status dict, then start the poller thread.

    By creating these objects HERE (inside cache_resource) rather than
    relying on poller.py's module-level variables, we guarantee that both
    the background thread and every Streamlit rerun reference the exact same
    Python objects — even if poller.py is reimported during a hot-reload.
    """
    import queue as _queue
    import time as _time

    # Canonical objects — owned by this cache_resource call forever
    q = _queue.Queue(maxsize=1)
    status = {
        "running": False,
        "last_checked": "Initializing...",
        "next_poll_at": _time.time(),
        "last_found": None,
        "error": None,
    }

    # Inject them into the poller thread so it writes here, not to its own
    # module-level copies.
    thread = poller_module.start_poller(q=q, status=status)

    return {
        "thread": thread,
        "queue": q,
        "status": status,
        "queue_id": id(q),   # diagnostic — visible in the log
    }

poller_resources = get_poller_resources()
submission_queue = poller_resources["queue"]
poller_status_ref = poller_resources["status"]

def _init_state():
    if "run_result" not in st.session_state:
        st.session_state.run_result = None   # {"pr_url": ..., "file": ...} or {"error": ...}
    if "running_agent" not in st.session_state:
        st.session_state.running_agent = False
    if "active_submission" not in st.session_state:
        st.session_state.active_submission = None
    if "last_refresh" not in st.session_state:
        st.session_state.last_refresh = time.time()

_init_state()


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.markdown(
    """
    <div style="display:flex;align-items:center;gap:14px;margin-bottom:28px;">
        <span style="font-size:2.2rem;">⚡</span>
        <div>
            <h1 style="margin:0;font-size:1.7rem;font-weight:700;
                       background:linear-gradient(90deg,#79c0ff,#bc8cff);
                       -webkit-background-clip:text;-webkit-text-fill-color:transparent;">
                ReelCode Agent
            </h1>
            <p style="margin:0;font-size:0.82rem;color:#7d8590;">
                LeetCode → Ollama → GitHub, fully automated
            </p>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Layout — two columns
# ---------------------------------------------------------------------------
col_left, col_right = st.columns([1, 1.4], gap="large")

# ===========================================================================
# LEFT COLUMN
# ===========================================================================
with col_left:

    # --- Status Panel ---
    status = poller_status_ref
    thread_alive = (
        poller_resources["thread"] is not None
        and poller_resources["thread"].is_alive()
    )
    dot_class = "dot-green" if thread_alive else "dot-red"
    dot_label = "Running" if thread_alive else "Stopped"

    last_checked = status.get("last_checked") or "Pending..."
    next_at = status.get("next_poll_at")
    if next_at and isinstance(next_at, (int, float)):
        remaining = max(0, int(next_at - time.time()))
        mins, secs = divmod(remaining, 60)
        next_str = f"{mins:02d}:{secs:02d}"
    else:
        next_str = "Calculating..."

    last_found = status.get("last_found") or "None"
    poller_error = status.get("error")

    st.markdown(
        f"""
        <div class="panel">
            <div class="panel-title">🛰 Poller Status</div>
            <div style="display:flex;align-items:center;margin-bottom:16px;">
                <span class="status-dot {dot_class}"></span>
                <span style="font-weight:600;color:#e6edf3;">{dot_label}</span>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
                <div>
                    <div class="metric-label">Last Checked</div>
                    <div class="metric-value" style="font-size:0.9rem;">{last_checked}</div>
                </div>
                <div>
                    <div class="metric-label">Next Poll In</div>
                    <div class="metric-value" style="color:#3fb950;">{next_str}</div>
                </div>
                <div style="grid-column:1/-1;">
                    <div class="metric-label">Last Found</div>
                    <div class="metric-value" style="font-size:0.9rem;color:#bc8cff;">{last_found}</div>
                </div>
            </div>
            {"" if not poller_error else f'<div style="margin-top:12px;padding:8px 12px;background:rgba(248,81,73,0.1);border:1px solid #f8514966;border-radius:6px;font-size:0.75rem;color:#f85149;">⚠ {poller_error}</div>'}
        </div>
        """,
        unsafe_allow_html=True,
    )

    # --- Queue Panel ---
    try:
        pending = submission_queue.queue[0] if not submission_queue.empty() else None
    except Exception:
        pending = None

    if pending:
        lang_badge = f'<span class="badge badge-blue">{pending["language"]}</span>'
        code_preview = pending["code"][:600] + ("…" if len(pending["code"]) > 600 else "")
        st.markdown(
            f"""
            <div class="panel">
                <div class="panel-title">📥 Pending Submission</div>
                <div style="margin-bottom:10px;">
                    <span style="font-size:1rem;font-weight:600;color:#e6edf3;">
                        {pending["problem_title"]}
                    </span>
                    &nbsp;{lang_badge}
                    <span class="badge badge-green" style="margin-left:6px;">Accepted</span>
                </div>
                <div style="margin-bottom:8px;">
                    <a href="{pending["problem_url"]}" target="_blank"
                       style="font-size:0.78rem;color:#79c0ff;text-decoration:none;">
                        🔗 {pending["problem_url"]}
                    </a>
                </div>
                <div class="metric-label" style="margin-bottom:6px;">Code Preview</div>
                <div class="code-preview">{code_preview}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            """
            <div class="panel" style="text-align:center;padding:32px;">
                <div style="font-size:2rem;margin-bottom:8px;">🔍</div>
                <div style="color:#7d8590;font-size:0.85rem;">
                    No submissions in queue.<br>Waiting for next accepted solution…
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# ===========================================================================
# RIGHT COLUMN
# ===========================================================================
with col_right:

    # --- Context Input + Run Button ---
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">🤖 Agent Controls</div>', unsafe_allow_html=True)

    user_context = st.text_area(
        "Optional notes for the AI agent",
        placeholder="e.g. 'Focus on the DP table visualisation' or 'Add a brute-force comparison'",
        height=100,
        key="user_context",
        label_visibility="collapsed",
    )

    run_disabled = (pending is None) or st.session_state.running_agent
    btn_label = "⏳ Generating…" if st.session_state.running_agent else "🚀 Run Agent & Push PR"

    if st.button(btn_label, disabled=run_disabled, use_container_width=True, type="primary"):
        st.session_state.running_agent = True
        st.session_state.run_result = None
        
        # Consume from queue and store in session state so it persists across potential reruns
        try:
            st.session_state.active_submission = submission_queue.get_nowait()
        except Exception:
            pass

        if st.session_state.active_submission:
            with st.spinner("Calling Ollama… this may take a minute"):
                try:
                    submission = st.session_state.active_submission
                    # Generate Streamlit file
                    generated_path = run_agent(submission, user_context)
                    # Push to GitHub
                    pr_url = push_to_github(submission, generated_path)
                    # Mark processed
                    poller_module._mark_processed(submission["submission_id"])
                    st.session_state.run_result = {"pr_url": pr_url, "file": generated_path}
                    # Clear active submission on success
                    st.session_state.active_submission = None
                except Exception as exc:
                    st.session_state.run_result = {"error": str(exc)}
                finally:
                    st.session_state.running_agent = False
        else:
            st.error("No submission found in queue.")
            st.session_state.running_agent = False

    # --- Run result feedback ---
    result = st.session_state.run_result
    if result:
        if "pr_url" in result:
            st.success(f"✅ PR opened successfully!")
            st.markdown(
                f"""
                <div style="margin-top:8px;padding:12px 16px;
                            background:rgba(63,185,80,0.08);
                            border:1px solid #3fb95044;border-radius:8px;">
                    <div class="metric-label">Pull Request</div>
                    <a href="{result['pr_url']}" target="_blank"
                       style="color:#3fb950;font-weight:600;font-size:0.9rem;">
                        {result['pr_url']}
                    </a>
                    <div style="margin-top:6px;" class="metric-label">
                        Generated file: {result['file']}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.error(f"❌ Error: {result['error']}")

    st.markdown("</div>", unsafe_allow_html=True)

    # --- Log Panel ---
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="panel-title">📋 Poller Log</div>', unsafe_allow_html=True)

    log_content = ""
    if LOG_FILE.exists():
        lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        # Show last 40 lines
        log_content = "\n".join(lines[-40:])
    else:
        log_content = "(Poller log not yet created)"

    st.markdown(
        f'<div class="log-box">{log_content}</div>',
        unsafe_allow_html=True,
    )

    if st.button("🔄 Refresh Log", use_container_width=False, key="refresh_log"):
        st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Auto-refresh every 30 seconds to update countdown / log
# ---------------------------------------------------------------------------
refresh_interval = 30  # seconds
elapsed = time.time() - st.session_state.last_refresh
if elapsed >= refresh_interval and not st.session_state.running_agent:
    st.session_state.last_refresh = time.time()
    time.sleep(0.1)
    st.rerun()
