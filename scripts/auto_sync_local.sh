#!/usr/bin/env bash
# Auto-pull origin/main into this local clone whenever GitHub has new commits.
# Run manually or via cron (installed as: */5 * * * * ... see CHANGELOG 2026-10-12).
#
# Safety rules:
#  - never touches a working tree with uncommitted/untracked files (logs and exits)
#  - fast-forward only; never rewrites or merges diverged history
#  - logs each run that changes something to ~/Library/Logs/ila-sync.log
set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BRANCH="main"
LOG_DIR="${HOME}/Library/Logs"
LOG_FILE="${LOG_DIR}/ila-sync.log"
PATH="/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin"

log() {
  mkdir -p "$LOG_DIR"
  printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG_FILE"
}

cd "$REPO_DIR" || { log "ERROR: repo directory not found: $REPO_DIR"; exit 1; }

# Skip when local work exists — an auto-sync must never clobber it.
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  log "SKIP: local changes present in $REPO_DIR; not pulling."
  exit 0
fi

if ! git fetch --quiet origin "$BRANCH" 2>/dev/null; then
  log "SKIP: git fetch failed (offline or GitHub unreachable)."
  exit 0
fi

AHEAD="$(git rev-list --count "HEAD..origin/$BRANCH" 2>/dev/null || echo 0)"
DIVERGED="$(git rev-list --count "origin/$BRANCH..HEAD" 2>/dev/null || echo 0)"

if [ "$AHEAD" -eq 0 ]; then
  exit 0  # nothing new — stay quiet to keep the log small
fi

if [ "$DIVERGED" -gt 0 ]; then
  log "ATTENTION: local and origin/$BRANCH diverged ($DIVERGED local / $AHEAD remote commits). Manual sync required."
  exit 1
fi

if git merge --ff-only --quiet "origin/$BRANCH"; then
  log "PULLED: $(git rev-parse --short HEAD) $(git log -1 --format=%s)"
else
  log "ERROR: fast-forward to origin/$BRANCH failed."
  exit 1
fi
