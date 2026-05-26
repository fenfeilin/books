#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
  echo "Usage: $0 <input.mp3> [output_dir]" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" >/dev/null 2>&1 && pwd -P)"
OUTPUT_DIR="${2:-$(pwd)/transcripts}"
LANG="${AUDIO_TRANSCRIBE_LANG:-en}"

"$SCRIPT_DIR/transcribe_audio.sh" "$1" "$OUTPUT_DIR" "$LANG"
