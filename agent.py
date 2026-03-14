"""
agent.py — Ollama LLM Project Creator

Accepts a submission dict (from poller.py) plus optional user context.
Calls a local Ollama model to generate a single self-contained Python
Streamlit file that visualises the algorithm, then saves it to output/.
"""

import json
import logging
import re
import sys
from pathlib import Path

import ollama
from dotenv import load_dotenv
import os

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
OUTPUT_DIR = Path(__file__).parent / "output"

logger = logging.getLogger("agent")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [AGENT] %(levelname)s — %(message)s",
    )

# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """\
You are an expert Python developer and educator.

Your task is to produce a SINGLE, complete, self-contained Python file.
The file must contain:

1. A top-level module docstring acting as an inline README (wrap at 80 chars).
   Include:
   - Problem title and link
   - Algorithm summary
   - How to run the Streamlit app
   - How to print the README: `python <filename>.py --readme`

2. The algorithm solution ported to Python, with inline comments explaining
   EVERY non-trivial step.

3. A Streamlit UI that:
   - Shows the problem statement (short)
   - Lets the user input example data
   - Visualises the algorithm step-by-step (use st.write, st.code, st.dataframe,
     st.progress, or st.pyplot — whatever fits the problem)
   - Shows the final answer

4. A CLI entry point at the bottom:
   if __name__ == "__main__":
       if "--readme" in sys.argv:
           print(__doc__)
       else:
           # Streamlit is launched externally via `streamlit run`
           pass

CRITICAL RULES:
- Output ONLY raw Python code. Do NOT wrap output in markdown code fences.
- Do NOT include ``` or ```python anywhere in your output.
- Do NOT add any explanation, preamble, or commentary outside the Python file.
- The file must be syntactically valid Python that can be saved and run directly.
"""


def _build_user_message(submission: dict, user_context: str = "") -> str:
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
{submission["code"]}
{context_section}

Remember: output ONLY the raw Python file contents. No markdown fences.\
"""


# ---------------------------------------------------------------------------
# Output cleaner
# ---------------------------------------------------------------------------
def _strip_fences(text: str) -> str:
    """Remove accidental markdown code fences the model may produce."""
    # Strip ```python ... ``` or ``` ... ```
    text = re.sub(r"^```(?:python)?\s*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n?```\s*$", "", text, flags=re.MULTILINE)
    return text.strip()


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
        RuntimeError: If Ollama call fails.
    """
    slug = submission["problem_slug"]
    OUTPUT_DIR.mkdir(exist_ok=True)
    out_path = OUTPUT_DIR / f"{slug}.py"

    logger.info("Calling Ollama model '%s' for problem: %s", OLLAMA_MODEL, submission["problem_title"])

    user_message = _build_user_message(submission, user_context)

    try:
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            options={"temperature": 0.2},  # low temperature for deterministic code
        )
    except Exception as exc:
        raise RuntimeError(f"Ollama call failed: {exc}") from exc

    raw_content = response["message"]["content"]
    clean_code = _strip_fences(raw_content)

    if not clean_code:
        raise RuntimeError("Ollama returned an empty response")

    out_path.write_text(clean_code, encoding="utf-8")
    logger.info("Saved generated file to: %s", out_path)

    return str(out_path)


# ---------------------------------------------------------------------------
# CLI helper (for manual testing)
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
