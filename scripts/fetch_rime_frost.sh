#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

RIME_FROST_URL="${RIME_FROST_URL:-https://github.com/gaboolic/rime-frost.git}"
RIME_FROST_COMMIT="${RIME_FROST_COMMIT:-7c8a908a92fa67fe1be9279b523b3cf95366e27d}"
VENDOR_DIR="$REPO_DIR/vendor/rime-frost"

usage() {
  cat <<EOF
Usage: $(basename "$0") [--rime-frost-dir <path>]

Fetches gaboolic/rime-frost pinned to RIME_FROST_COMMIT (default: $RIME_FROST_COMMIT).
Options:
  --rime-frost-dir <path>   Destination checkout directory (default: ./vendor/rime-frost)
  -h, --help                Show this help message
Environment:
  RIME_FROST_COMMIT         Override pinned upstream commit SHA
  RIME_FROST_URL            Override upstream git remote URL
EOF
}

POSITIONAL_SET=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --rime-frost-dir)
      if [[ $# -lt 2 ]]; then
        echo "Error: --rime-frost-dir requires a path argument." >&2
        exit 1
      fi
      VENDOR_DIR="$2"
      shift 2
      ;;
    --rime-frost-dir=*)
      VENDOR_DIR="${1#*=}"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      echo "Error: Unknown option '$1'" >&2
      usage >&2
      exit 1
      ;;
    *)
      if [[ "$POSITIONAL_SET" -eq 1 ]]; then
        echo "Error: Unexpected extra argument '$1'" >&2
        usage >&2
        exit 1
      fi
      VENDOR_DIR="$1"
      POSITIONAL_SET=1
      shift
      ;;
  esac
done

mkdir -p "$(dirname "$VENDOR_DIR")"

if [[ -d "$VENDOR_DIR/.git" ]]; then
  CURRENT_HEAD="$(git -C "$VENDOR_DIR" rev-parse HEAD 2>/dev/null || true)"
  if [[ "$CURRENT_HEAD" == "$RIME_FROST_COMMIT" ]]; then
    echo "==> rime-frost already at pinned commit $RIME_FROST_COMMIT"
  else
    echo "==> Updating existing checkout at $VENDOR_DIR to $RIME_FROST_COMMIT..."
    if ! git -C "$VENDOR_DIR" fetch --depth 1 origin "$RIME_FROST_COMMIT"; then
      git -C "$VENDOR_DIR" fetch origin "$RIME_FROST_COMMIT"
    fi
    git -C "$VENDOR_DIR" checkout --detach FETCH_HEAD
  fi
else
  if [[ -e "$VENDOR_DIR" ]] && [[ -n "$(ls -A "$VENDOR_DIR" 2>/dev/null || true)" ]]; then
    echo "Error: $VENDOR_DIR exists and is not a git repository." >&2
    exit 1
  fi
  echo "==> Fetching gaboolic/rime-frost @ $RIME_FROST_COMMIT into $VENDOR_DIR..."
  rm -rf "$VENDOR_DIR"
  git init "$VENDOR_DIR" >/dev/null
  git -C "$VENDOR_DIR" remote add origin "$RIME_FROST_URL"
  if git -C "$VENDOR_DIR" fetch --depth 1 origin "$RIME_FROST_COMMIT"; then
    git -C "$VENDOR_DIR" checkout --detach FETCH_HEAD
  else
    echo "==> Shallow SHA fetch rejected by remote; falling back to full clone..."
    rm -rf "$VENDOR_DIR"
    git clone "$RIME_FROST_URL" "$VENDOR_DIR"
    git -C "$VENDOR_DIR" checkout --detach "$RIME_FROST_COMMIT"
  fi
fi

HEAD_SHA="$(git -C "$VENDOR_DIR" rev-parse HEAD)"
if [[ "$HEAD_SHA" != "$RIME_FROST_COMMIT" ]]; then
  echo "Error: Expected HEAD $RIME_FROST_COMMIT, got $HEAD_SHA" >&2
  exit 1
fi

if [[ ! -f "$VENDOR_DIR/rime_frost.dict.yaml" ]]; then
  echo "Error: Missing $VENDOR_DIR/rime_frost.dict.yaml" >&2
  exit 1
fi

if [[ ! -f "$VENDOR_DIR/LICENSE" ]]; then
  echo "Error: Missing $VENDOR_DIR/LICENSE" >&2
  exit 1
fi

COMMIT_DATE="$(git -C "$VENDOR_DIR" log -1 --format='%cs')"
echo "==> rime-frost ready: $HEAD_SHA ($COMMIT_DATE) at $VENDOR_DIR"
