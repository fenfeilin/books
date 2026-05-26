#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 1 ] || [ "$#" -gt 3 ]; then
  echo "Usage: $0 <audio_dir> [output_dir] [language]" >&2
  echo "  language: zh | en | auto | other whisper language code" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" >/dev/null 2>&1 && pwd -P)"
INPUT_DIR="$1"
OUTPUT_DIR="${2:-$INPUT_DIR/_transcripts}"
LANG="${3:-${AUDIO_TRANSCRIBE_LANG:-auto}}"

if [ ! -d "$INPUT_DIR" ]; then
  echo "Input directory not found: $INPUT_DIR" >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"

count=0
find "$INPUT_DIR" -maxdepth 1 -type f \( \
  -iname "*.mp3" -o \
  -iname "*.m4a" -o \
  -iname "*.m4b" -o \
  -iname "*.mp4" -o \
  -iname "*.aac" -o \
  -iname "*.wav" -o \
  -iname "*.wave" -o \
  -iname "*.flac" -o \
  -iname "*.ogg" -o \
  -iname "*.opus" \
\) -print0 |
while IFS= read -r -d '' AUDIO_PATH; do
  count=$((count + 1))
  echo "Transcribing: $AUDIO_PATH" >&2
  "$SCRIPT_DIR/transcribe_audio.sh" "$AUDIO_PATH" "$OUTPUT_DIR" "$LANG"
done

echo "Done: $OUTPUT_DIR"
