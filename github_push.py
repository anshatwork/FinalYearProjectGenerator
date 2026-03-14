"""
github_push.py — GitHub PR Pusher

Uses PyGithub to:
  1. Validate token has write access to GITHUB_REPO
  2. Guard against duplicate branches (feat/<slug>)
  3. Create branch from main
  4. Commit output/<slug>.py -> solutions/<slug>/visualizer.py
  5. Open a PR with title + body (README + LeetCode URL)
"""

import base64
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
import os

from github import Github, GithubException

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "anshatwork/Reelcode")

logger = logging.getLogger("github_push")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [GITHUB] %(levelname)s — %(message)s",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_repo():
    if not GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN not set in .env")
    g = Github(GITHUB_TOKEN)
    try:
        repo = g.get_repo(GITHUB_REPO)
    except GithubException as exc:
        raise RuntimeError(f"Cannot access repo '{GITHUB_REPO}': {exc.data}") from exc

    # Check write access
    try:
        perms = repo.get_collaborator_permission(g.get_user().login)
        if perms not in ("write", "admin", "maintain"):
            raise RuntimeError(f"Token has only '{perms}' permission on {GITHUB_REPO} — need write or above")
    except GithubException:
        # For public repos the above may fail; skip permission check and proceed
        logger.warning("Could not verify collaborator permission — proceeding anyway")

    return repo


def _extract_readme(code: str) -> str:
    """Pull the module-level docstring from generated code to use as PR body."""
    lines = code.splitlines()
    in_doc = False
    readme_lines = []
    for line in lines:
        stripped = line.strip()
        if not in_doc and (stripped.startswith('"""') or stripped.startswith("'''")):
            in_doc = True
            inner = stripped[3:]
            if inner.endswith('"""') or inner.endswith("'''"):
                # Single-line docstring
                return inner[:-3].strip()
            readme_lines.append(inner)
            continue
        if in_doc:
            if stripped.endswith('"""') or stripped.endswith("'''"):
                readme_lines.append(stripped[:-3])
                break
            readme_lines.append(line)
    return "\n".join(readme_lines).strip()


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------
def push_to_github(submission: dict, generated_file_path: str) -> str:
    """
    Create a branch, commit the generated visualizer, and open a PR.

    Args:
        submission:          Dict from poller.py (must include problem_slug,
                             problem_title, problem_url).
        generated_file_path: Absolute path to the output/<slug>.py file.

    Returns:
        HTML URL of the opened PR.

    Raises:
        RuntimeError: On any GitHub API error.
    """
    slug = submission["problem_slug"]
    title = submission["problem_title"]
    problem_url = submission["problem_url"]
    branch_name = f"feat/{slug}"
    target_path = f"solutions/{slug}/visualizer.py"

    repo = _get_repo()
    logger.info("Connected to repo: %s", repo.full_name)

    # --- Dedup guard ---
    existing_branches = [b.name for b in repo.get_branches()]
    if branch_name in existing_branches:
        raise RuntimeError(
            f"Branch '{branch_name}' already exists — submission may have been processed already"
        )

    # --- Get main branch SHA ---
    main_ref = repo.get_git_ref("heads/main")
    main_sha = main_ref.object.sha
    logger.info("main SHA: %s", main_sha)

    # --- Create branch ---
    repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=main_sha)
    logger.info("Created branch: %s", branch_name)

    # --- Read generated file ---
    code_path = Path(generated_file_path)
    if not code_path.exists():
        raise RuntimeError(f"Generated file not found: {generated_file_path}")
    code_content = code_path.read_text(encoding="utf-8")

    # --- Commit file ---
    commit_message = f"feat({slug}): add Streamlit visualizer for {title}"
    try:
        repo.create_file(
            path=target_path,
            message=commit_message,
            content=code_content,
            branch=branch_name,
        )
    except GithubException as exc:
        raise RuntimeError(f"Failed to commit file: {exc.data}") from exc

    logger.info("Committed: %s → %s", code_path.name, target_path)

    # --- Build PR body ---
    readme_text = _extract_readme(code_content)
    pr_body = f"""## [{title}]({problem_url})

{readme_text}

---

**LeetCode Problem:** {problem_url}

*Generated by ReelCode Automation Agent* 🤖
"""

    # --- Open PR ---
    try:
        pr = repo.create_pull(
            title=f"[ReelCode] {title}",
            body=pr_body,
            head=branch_name,
            base="main",
        )
    except GithubException as exc:
        raise RuntimeError(f"Failed to create PR: {exc.data}") from exc

    logger.info("PR opened: %s", pr.html_url)
    return pr.html_url


# ---------------------------------------------------------------------------
# CLI helper (for manual testing)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import json

    if len(sys.argv) < 3:
        print("Usage: python github_push.py <submission_json> <generated_file.py>")
        sys.exit(1)

    with open(sys.argv[1], encoding="utf-8") as f:
        sub = json.load(f)

    url = push_to_github(sub, sys.argv[2])
    print(f"\n✅ PR created: {url}")
