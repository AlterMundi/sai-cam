#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/claude-second-opinion.sh --task "<task description>" [options]

Options:
  --task <text>           Required. One-line task statement.
  --constraints <text>    Optional. Constraints for the assistant.
  --model <name>          Optional. Claude model alias (default: opus).
  --log-dir <path>        Optional. Output directory (default: _ai_logs).
  --max-diff-lines <n>    Optional. Max diff lines included in prompt (default: 300).
  --timeout-seconds <n>   Optional. Max wait for Claude response (default: 180).
  -h, --help              Show this help.

Example:
  scripts/claude-second-opinion.sh \
    --task "Review recent changes for regressions" \
    --constraints "Prefer minimal patch and keep tests green"
USAGE
}

TASK=""
CONSTRAINTS=""
MODEL="opus"
LOG_DIR="_ai_logs"
MAX_DIFF_LINES=300
TIMEOUT_SECONDS=180

require_option_value() {
  local option_name="$1"
  if [[ $# -lt 2 || -z "${2:-}" ]]; then
    echo "Error: ${option_name} requires a value." >&2
    usage
    exit 1
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task)
      require_option_value "$1" "${2:-}"
      TASK="$2"
      shift 2
      ;;
    --constraints)
      require_option_value "$1" "${2:-}"
      CONSTRAINTS="$2"
      shift 2
      ;;
    --model)
      require_option_value "$1" "${2:-}"
      MODEL="$2"
      shift 2
      ;;
    --log-dir)
      require_option_value "$1" "${2:-}"
      LOG_DIR="$2"
      shift 2
      ;;
    --max-diff-lines)
      require_option_value "$1" "${2:-}"
      MAX_DIFF_LINES="$2"
      shift 2
      ;;
    --timeout-seconds)
      require_option_value "$1" "${2:-}"
      TIMEOUT_SECONDS="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$TASK" ]]; then
  echo "Error: --task is required." >&2
  usage
  exit 1
fi

if ! [[ "$MAX_DIFF_LINES" =~ ^[0-9]+$ ]] || [[ "$MAX_DIFF_LINES" -le 0 ]]; then
  echo "Error: --max-diff-lines must be a positive integer." >&2
  exit 1
fi

if ! [[ "$TIMEOUT_SECONDS" =~ ^[0-9]+$ ]] || [[ "$TIMEOUT_SECONDS" -le 0 ]]; then
  echo "Error: --timeout-seconds must be a positive integer." >&2
  exit 1
fi

if ! command -v claude >/dev/null 2>&1; then
  echo "Error: claude CLI not found in PATH." >&2
  exit 1
fi

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "$REPO_ROOT" ]]; then
  echo "Error: current directory is not inside a git repository." >&2
  exit 1
fi

cd "$REPO_ROOT"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
COMMIT="$(git rev-parse --short=12 HEAD)"
STATUS="clean"
if [[ -n "$(git status --porcelain)" ]]; then
  STATUS="dirty"
fi

if git rev-parse --verify HEAD >/dev/null 2>&1; then
  DIFF_CONTENT="$(git --no-pager diff HEAD -- . | sed -n "1,${MAX_DIFF_LINES}p")"
else
  DIFF_CONTENT="$(git --no-pager diff -- . | sed -n "1,${MAX_DIFF_LINES}p")"
fi
if [[ -z "$DIFF_CONTENT" ]]; then
  DIFF_CONTENT="(No working-tree diff against HEAD.)"
fi

mkdir -p "$LOG_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG_FILE="$LOG_DIR/${STAMP}-claude-second-opinion.md"

PROMPT="[CONTEXT]
Repo: $REPO_ROOT
Branch: $BRANCH
Commit: $COMMIT
Task: $TASK
Constraints: ${CONSTRAINTS:-none}
Worktree: $STATUS

[REQUEST]
You are giving a second opinion on this coding task.
1) Proposed approach (brief)
2) Exact edits (file paths)
3) Test/verify commands
4) Risks/edge cases and likely regressions

[DIFF PREVIEW]
$DIFF_CONTENT

[OUTPUT FORMAT]
- Plan (max 6 bullets)
- Findings first (ordered by severity)
- Patch-ready edits
- Verification commands
- Short rationale"

{
  echo "# Claude Second Opinion"
  echo
  echo "- Timestamp: $(date -Iseconds)"
  echo "- Repo: $REPO_ROOT"
  echo "- Branch: $BRANCH"
  echo "- Commit: $COMMIT"
  echo "- Worktree: $STATUS"
  echo "- Model: $MODEL"
  echo "- Task: $TASK"
  echo "- Constraints: ${CONSTRAINTS:-none}"
  echo "- Timeout seconds: $TIMEOUT_SECONDS"
  echo
  echo "## Prompt"
  echo
  echo '```text'
  echo "$PROMPT"
  echo '```'
  echo
  echo "## Claude Response"
  echo
} > "$LOG_FILE"

if command -v timeout >/dev/null 2>&1; then
  CLAUDE_CMD=(timeout "$TIMEOUT_SECONDS" claude -p --model "$MODEL")
else
  CLAUDE_CMD=(claude -p --model "$MODEL")
fi

set +e
echo "$PROMPT" | "${CLAUDE_CMD[@]}" >> "$LOG_FILE"
CLAUDE_EXIT_CODE=$?
set -e

if [[ "$CLAUDE_EXIT_CODE" -ne 0 ]]; then
  if [[ "$CLAUDE_EXIT_CODE" -eq 124 ]]; then
    echo "Claude call timed out after ${TIMEOUT_SECONDS}s. Partial log saved at: $LOG_FILE" >&2
  else
    echo "Claude call failed with exit code ${CLAUDE_EXIT_CODE}. Partial log saved at: $LOG_FILE" >&2
  fi
  echo "_Claude call failed or timed out. See command stderr for details._" >> "$LOG_FILE"
  exit 1
fi

echo "Second opinion saved to: $LOG_FILE"
