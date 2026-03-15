"""
agent.py — Ollama LLM Project Creator

Accepts a submission dict (from poller.py) plus optional user context.
Calls a local Ollama model to generate a single self-contained Python
Streamlit file that visualises the algorithm, then saves it to output/.
"""

import ast
import json
import logging
import os
import re
import sys
from pathlib import Path

import ollama
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
OUTPUT_DIR = Path(__file__).parent / "output"
MAX_CODE_CHARS = 3000
MAX_RETRIES = 2

logger = logging.getLogger("agent")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [AGENT] %(levelname)s — %(message)s",
    )

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """\
You are an expert Python developer and educator.

Your task is to produce a SINGLE, complete, self-contained Python Streamlit file.
The file must contain:

1. The algorithm solution ported to Python, with inline comments explaining
   EVERY non-trivial step.

2. A Streamlit UI that:
   - Shows the problem statement (short summary at the top)
   - Lets the user input example data relevant to the problem
   - Visualises the algorithm step-by-step using st.write, st.code,
     st.dataframe, st.progress, or st.pyplot — whichever fits best
   - Shows the final answer clearly with st.success or st.metric

CRITICAL RULES:
- Output ONLY raw Python code. Do NOT wrap output in markdown code fences.
- Do NOT include ``` or ```python anywhere in your output.
- Do NOT add any explanation, preamble, or commentary outside the Python file.
- The file must be syntactically valid Python that can be saved and run directly.

EXAMPLE OUTPUT STRUCTURE (follow this pattern exactly):

import streamlit as st

# ── Algorithm ───────────────────────────────────────────────────────────────
def solve(data):
    # Step 1: find the maximum value — this is the core insight
    result = max(data)
    return result

# ── Streamlit UI ─────────────────────────────────────────────────────────────
def main():
    st.title("Example Visualizer")
    st.markdown("**Problem:** Find the maximum value in a list of integers.")

    user_input = st.text_input("Enter comma-separated numbers", "3,1,4,1,5")

    try:
        nums = list(map(int, user_input.split(",")))
    except ValueError:
        st.error("Please enter valid comma-separated integers.")
        return

    st.subheader("Step-by-step")
    for i, n in enumerate(nums):
        st.write(f"Step {i+1}: current value = {n}")

    answer = solve(nums)
    st.success(f"Answer: {answer}")

if __name__ == "__main__":
    main()
"""


def _build_user_message(submission: dict, user_context: str = "") -> str:
    code = submission["code"]
    if len(code) > MAX_CODE_CHARS:
        code = code[:MAX_CODE_CHARS] + "\n# ... (truncated for context window)"
        logger.warning("Submitted code truncated to %d chars", MAX_CODE_CHARS)

    context_section = (
        f"\n\nAdditional notes from the user:\n{user_context.strip()}"
        if user_context and user_context.strip()
        else ""
    )

    return f"""\
Create the Python Streamlit visualizer file for the following LeetCode submission.

Problem Title: {submission["problem_title"]}
Problem URL: {submission["problem_url"]}
Language submitted: {submission["language"]}

Original submitted code:
{code}
{context_section}

Remember: output ONLY the raw Python file contents. No markdown fences.\
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _strip_fences(text: str) -> str:
    """Remove accidental markdown code fences the model may produce."""
    text = re.sub(r"^```(?:python)?\s*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n?```\s*$", "", text, flags=re.MULTILINE)
    return text.strip()


def _validate_python(code: str, slug: str) -> None:
    """Raise RuntimeError if the generated code is not valid Python."""
    try:
        ast.parse(code)
    except SyntaxError as e:
        raise RuntimeError(
            f"Generated code has syntax errors for '{slug}': {e}"
        ) from e


def _call_ollama(messages: list) -> str:
    """Call Ollama with streaming, return full response string."""
    try:
        stream = ollama.chat(
            model=OLLAMA_MODEL,
            messages=messages,
            stream=True,
            options={"temperature": 0.2},
        )
        chunks = []
        for chunk in stream:
            chunks.append(chunk["message"]["content"])
        return "".join(chunks)
    except Exception as exc:
        raise RuntimeError(f"Ollama call failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------
def run_agent(submission: dict, user_context: str = "") -> str:
    """
    Generate a Streamlit visualizer for the given submission.

    Args:
        submission: Dict from poller.py with keys problem_title, problem_slug,
                    problem_url, language, code, timestamp.
        user_context: Optional free-text notes from the Streamlit UI.

    Returns:
        Absolute path to the generated .py file.

    Raises:
        RuntimeError: If Ollama call fails or returns invalid Python after retries.
    """
    slug = submission["problem_slug"]
    OUTPUT_DIR.mkdir(exist_ok=True)
    out_path = OUTPUT_DIR / f"{slug}.py"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_message(submission, user_context)},
    ]

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        logger.info(
            "Calling Ollama model '%s' for '%s' (attempt %d/%d)",
            OLLAMA_MODEL,
            submission["problem_title"],
            attempt,
            MAX_RETRIES,
        )

        try:
            raw_content = _call_ollama(messages)
            clean_code = _strip_fences(raw_content)

            if not clean_code:
                raise RuntimeError("Ollama returned an empty response")

            _validate_python(clean_code, slug)

            out_path.write_text(clean_code, encoding="utf-8")
            logger.info("Saved generated file → %s", out_path)

            # Dry-run sidecar
            if os.getenv("DRY_RUN", "false").lower() == "true":
                meta_path = OUTPUT_DIR / f"{slug}_meta.json"
                meta_path.write_text(json.dumps(submission, indent=2), encoding="utf-8")
                logger.info("DRY_RUN: saved metadata → %s", meta_path)

            return str(out_path)

        except RuntimeError as e:
            last_error = e
            if attempt < MAX_RETRIES:
                logger.warning("Attempt %d failed: %s — retrying…", attempt, e)
            else:
                logger.error("All %d attempts failed.", MAX_RETRIES)

    raise RuntimeError(f"Agent failed after {MAX_RETRIES} attempts: {last_error}") from last_error


# ---------------------------------------------------------------------------
# CLI helper (manual testing)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python agent.py <submission_json_file>")
        sys.exit(1)

    with open(sys.argv[1], encoding="utf-8") as f:
        sub = json.load(f)

    context = input("Optional user context (press Enter to skip): ").strip()
    result = run_agent(sub, context)
    print(f"\n✅ Generated: {result}")