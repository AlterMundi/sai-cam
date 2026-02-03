#!/usr/bin/env bash
#
# release.sh — Bump version, commit, tag, push. One command releases.
#
# Usage:
#   ./scripts/release.sh              # patch bump: 0.2.11 → 0.2.12
#   ./scripts/release.sh --minor      # minor bump: 0.2.11 → 0.3.0
#   ./scripts/release.sh --major      # major bump: 0.2.11 → 1.0.0
#   ./scripts/release.sh --beta       # beta: 0.2.11 → 0.2.12-beta.1
#   ./scripts/release.sh --beta       # next beta: 0.2.12-beta.1 → 0.2.12-beta.2
#   ./scripts/release.sh --promote    # promote: 0.2.12-beta.2 → 0.2.12
#   ./scripts/release.sh --dry-run    # show what would happen
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION_FILE="$REPO_ROOT/src/version.py"

# ── Defaults ──────────────────────────────────────────────────────────
BUMP_TYPE="patch"
DRY_RUN=false
FORCE_BRANCH=false

# ── Parse arguments ───────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --patch)        BUMP_TYPE="patch";   shift ;;
        --minor)        BUMP_TYPE="minor";   shift ;;
        --major)        BUMP_TYPE="major";   shift ;;
        --beta)         BUMP_TYPE="beta";    shift ;;
        --promote)      BUMP_TYPE="promote"; shift ;;
        --dry-run)      DRY_RUN=true;        shift ;;
        --force-branch) FORCE_BRANCH=true;   shift ;;
        -h|--help)
            sed -n '3,11p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

# ── Helpers ───────────────────────────────────────────────────────────
die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "→ $*"; }
bold() { echo -e "\033[1m$*\033[0m"; }

run() {
    if $DRY_RUN; then
        echo "  [dry-run] $*"
    else
        "$@"
    fi
}

# ── Read current version from git tags (single source of truth) ──────
CURRENT_TAG=$(git -C "$REPO_ROOT" describe --tags --abbrev=0 2>/dev/null) \
    || die "No git tags found. Create an initial tag: git tag -a v0.0.0 -m 'Initial'"
CURRENT_VERSION="${CURRENT_TAG#v}"

info "Current version: $CURRENT_VERSION (from tag $CURRENT_TAG)"

# ── Parse version components ─────────────────────────────────────────
# Matches: 1.2.3, 1.2.3-beta.4, 1.2.3-rc.1, etc.
if [[ "$CURRENT_VERSION" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)(-([a-zA-Z]+)\.([0-9]+))?$ ]]; then
    MAJOR="${BASH_REMATCH[1]}"
    MINOR="${BASH_REMATCH[2]}"
    PATCH="${BASH_REMATCH[3]}"
    PRE_LABEL="${BASH_REMATCH[5]:-}"
    PRE_NUM="${BASH_REMATCH[6]:-}"
else
    die "Cannot parse version: $CURRENT_VERSION"
fi

IS_PRERELEASE=false
[[ -n "$PRE_LABEL" ]] && IS_PRERELEASE=true

# ── Compute new version ──────────────────────────────────────────────
case "$BUMP_TYPE" in
    patch)
        if $IS_PRERELEASE; then
            # If already on a prerelease, patch bump goes to the stable of that version
            NEW_VERSION="$MAJOR.$MINOR.$PATCH"
        else
            NEW_VERSION="$MAJOR.$MINOR.$((PATCH + 1))"
        fi
        ;;
    minor)
        NEW_VERSION="$MAJOR.$((MINOR + 1)).0"
        ;;
    major)
        NEW_VERSION="$((MAJOR + 1)).0.0"
        ;;
    beta)
        if $IS_PRERELEASE && [[ "$PRE_LABEL" == "beta" ]]; then
            # Already a beta → increment beta number
            NEW_VERSION="$MAJOR.$MINOR.$PATCH-beta.$((PRE_NUM + 1))"
        else
            # Not a beta → bump patch, start beta.1
            if $IS_PRERELEASE; then
                # On some other prerelease, go to beta.1 of same version
                NEW_VERSION="$MAJOR.$MINOR.$PATCH-beta.1"
            else
                NEW_VERSION="$MAJOR.$MINOR.$((PATCH + 1))-beta.1"
            fi
        fi
        ;;
    promote)
        $IS_PRERELEASE || die "Cannot promote: $CURRENT_VERSION is not a prerelease"
        NEW_VERSION="$MAJOR.$MINOR.$PATCH"
        ;;
esac

# ── Jump protection ──────────────────────────────────────────────────
# Parse new version for comparison
if [[ "$NEW_VERSION" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+) ]]; then
    NEW_MAJOR="${BASH_REMATCH[1]}"
    NEW_MINOR="${BASH_REMATCH[2]}"
fi

MINOR_JUMP=$((NEW_MINOR - MINOR))
MAJOR_JUMP=$((NEW_MAJOR - MAJOR))

if [[ "$BUMP_TYPE" != "major" ]] && (( MAJOR_JUMP > 0 )); then
    die "Major version jump ($MAJOR → $NEW_MAJOR) requires --major flag"
fi

if [[ "$BUMP_TYPE" == "patch" || "$BUMP_TYPE" == "beta" ]] && (( MINOR_JUMP > 1 )); then
    die "Minor jump of $MINOR_JUMP detected. Use --minor for intentional minor bumps."
fi

TAG="v$NEW_VERSION"

bold "\n  $CURRENT_VERSION → $NEW_VERSION  (tag: $TAG)\n"

# ── Safety checks ────────────────────────────────────────────────────
cd "$REPO_ROOT"

# Check branch
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [[ "$CURRENT_BRANCH" != "main" ]] && ! $FORCE_BRANCH; then
    die "Must be on 'main' branch (currently on '$CURRENT_BRANCH'). Use --force-branch to override."
fi

# Check clean working tree
if [[ -n "$(git status --porcelain)" ]]; then
    die "Working tree is not clean. Commit or stash changes first."
fi

# Check up-to-date with remote
git fetch origin --quiet 2>/dev/null || true
LOCAL_SHA=$(git rev-parse HEAD)
REMOTE_SHA=$(git rev-parse "origin/$CURRENT_BRANCH" 2>/dev/null || echo "")
if [[ -n "$REMOTE_SHA" && "$LOCAL_SHA" != "$REMOTE_SHA" ]]; then
    die "Local '$CURRENT_BRANCH' is not up-to-date with origin. Pull or push first."
fi

# Check tag doesn't exist
if git rev-parse "$TAG" >/dev/null 2>&1; then
    die "Tag '$TAG' already exists."
fi

# ── Execute release ──────────────────────────────────────────────────
info "Writing version to $VERSION_FILE"
run sed -i "s/VERSION = \".*\"/VERSION = \"$NEW_VERSION\"/" "$VERSION_FILE"

info "Committing version bump"
run git add "$VERSION_FILE"
run git commit -m "chore: Bump version to $NEW_VERSION"

info "Creating tag $TAG"
run git tag -a "$TAG" -m "Release $NEW_VERSION"

info "Pushing commit and tag"
run git push origin "$CURRENT_BRANCH"
run git push origin "$TAG"

if $DRY_RUN; then
    echo ""
    bold "Dry run complete. No changes were made."
else
    echo ""
    bold "Released $NEW_VERSION"
    info "Tag $TAG pushed. CI will create the GitHub Release."
fi
