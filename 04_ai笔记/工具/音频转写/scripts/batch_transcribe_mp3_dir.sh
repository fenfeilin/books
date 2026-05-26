#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
  echo "Usage: $0 <mp3_dir> [output_dir]" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" >/dev/null 2>&1 && pwd -P)"
INPUT_DIR="$1"
OUTPUT_DIR="${2:-$INPUT_DIR/_transcripts}"
LANG="${AUDIO_TRANSCRIBE_LANG:-en}"

if [ ! -d "$INPUT_DIR" ]; then
  echo "Input directory not found: $INPUT_DIR" >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"

find "$INPUT_DIR" -maxdepth 1 -type f -iname "*.mp3" -print0 |
while IFS= read -r -d '' MP3_PATH; do
  echo "Transcribing: $MP3_PATH" >&2
  "$SCRIPT_DIR/transcribe_audio.sh" "$MP3_PATH" "$OUTPUT_DIR" "$LANG"
done

echo "Done: $OUTPUT_DIR"
