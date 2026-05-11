#!/usr/bin/env bash
# Internal site puller — runs on YOUR nginx box (NOT in GitHub Actions).
#
# Two delivery channels are kept in sync by .github/workflows/build.yml;
# this script consumes either, pick one with $MODE.
#
#   MODE=branch  (default)   git fetch + reset --hard origin/site
#                            into $WEBROOT. Requires git + HTTPS to github.com.
#   MODE=tarball             curl the `site-latest` release tarball and atomically
#                            swap $WEBROOT. Requires curl + HTTPS to github.com.
#
# Install on the internal box:
#
#   sudo install -m 0755 internal-puller.sh /usr/local/bin/llm-wiki-pull
#   # ---- /etc/cron.d/llm-wiki ----
#   */5 * * * * www-data WEBROOT=/var/www/llm-wiki \
#               REPO=dujeonglee/code-llm-wiki \
#               /usr/local/bin/llm-wiki-pull >> /var/log/llm-wiki-pull.log 2>&1
#
# Required env:
#   REPO       = "owner/repo", e.g. "dujeonglee/code-llm-wiki"
#   WEBROOT    = absolute path that nginx serves, e.g. /var/www/llm-wiki
# Optional env:
#   MODE       = branch | tarball   (default: branch)
#   BRANCH     = git branch holding built HTML (default: site)
#   GITHUB_TOKEN = personal access token (only needed for PRIVATE repos)
#   RELEASE_TAG  = release tag for tarball mode (default: site-latest)
set -euo pipefail

MODE="${MODE:-branch}"
BRANCH="${BRANCH:-site}"
RELEASE_TAG="${RELEASE_TAG:-site-latest}"
: "${REPO:?REPO env var is required (e.g. owner/repo)}"
: "${WEBROOT:?WEBROOT env var is required (e.g. /var/www/llm-wiki)}"

log() { printf '%s [%s] %s\n' "$(date -u +%FT%TZ)" "$MODE" "$*"; }

auth_url() {
    # For private repos add a token; for public the bare URL is fine.
    if [[ -n "${GITHUB_TOKEN:-}" ]]; then
        echo "https://x-access-token:${GITHUB_TOKEN}@github.com/${REPO}.git"
    else
        echo "https://github.com/${REPO}.git"
    fi
}

case "$MODE" in
  branch)
    if [[ ! -d "$WEBROOT/.git" ]]; then
        log "first-run clone of $BRANCH into $WEBROOT"
        mkdir -p "$WEBROOT"
        git clone --depth=1 --branch="$BRANCH" "$(auth_url)" "$WEBROOT"
        exit 0
    fi
    cd "$WEBROOT"
    log "fetching $BRANCH"
    git fetch --depth=1 origin "$BRANCH"
    local_sha=$(git rev-parse HEAD)
    remote_sha=$(git rev-parse "origin/$BRANCH")
    if [[ "$local_sha" == "$remote_sha" ]]; then
        log "no change ($local_sha)"
        exit 0
    fi
    log "resetting $local_sha -> $remote_sha"
    git reset --hard "origin/$BRANCH"
    # garbage-collect the previous history; site branch is force-pushed
    # so old commits are unreachable.
    git -c gc.auto=1 gc --prune=now --quiet || true
    ;;

  tarball)
    api="https://api.github.com/repos/${REPO}/releases/tags/${RELEASE_TAG}"
    auth_header=()
    if [[ -n "${GITHUB_TOKEN:-}" ]]; then
        auth_header=(-H "Authorization: Bearer ${GITHUB_TOKEN}")
    fi
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    log "fetching release $RELEASE_TAG metadata"
    asset_url=$(curl -fsSL "${auth_header[@]}" "$api" \
        | python3 -c '
import json, sys
data = json.load(sys.stdin)
for a in data.get("assets", []):
    if a["name"] == "llm-wiki-site.tar.gz":
        print(a["url"])
        sys.exit(0)
sys.exit("llm-wiki-site.tar.gz asset not found")')
    log "downloading tarball"
    curl -fsSL "${auth_header[@]}" -H "Accept: application/octet-stream" \
        -o "$tmp/site.tar.gz" "$asset_url"
    mkdir -p "$tmp/site"
    tar xzf "$tmp/site.tar.gz" -C "$tmp/site"
    # Atomic swap so nginx never serves a half-extracted tree.
    new="$WEBROOT.new.$$"
    rm -rf "$new"
    mv "$tmp/site" "$new"
    if [[ -e "$WEBROOT" ]]; then
        old="$WEBROOT.old.$$"
        mv "$WEBROOT" "$old"
        mv "$new" "$WEBROOT"
        rm -rf "$old"
    else
        mv "$new" "$WEBROOT"
    fi
    log "swap complete"
    ;;

  *)
    echo "unknown MODE=$MODE (use 'branch' or 'tarball')" >&2
    exit 2
    ;;
esac
