#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 1 ] || [ "$#" -gt 3 ]; then
  echo "Usage: $0 <input_audio> [output_dir] [language]" >&2
  echo "  language: zh | en | auto | other whisper language code" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" >/dev/null 2>&1 && pwd -P)"
TOOL_DIR="$(cd "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd -P)"

INPUT="$1"
OUTPUT_DIR="${2:-$(pwd)/transcripts}"
LANG="${3:-${AUDIO_TRANSCRIBE_LANG:-auto}}"

WHISPER="$TOOL_DIR/bin/whisper-main"
MP3_CONVERTER="$TOOL_DIR/bin/mp3_to_wav_minimp3"
THREADS="${AUDIO_TRANSCRIBE_THREADS:-4}"

if [ ! -f "$INPUT" ]; then
  echo "Input file not found: $INPUT" >&2
  exit 1
fi

if [ ! -x "$WHISPER" ]; then
  echo "whisper-main not found or not executable: $WHISPER" >&2
  exit 1
fi

case "$LANG" in
  en|EN)
    MODEL="$TOOL_DIR/models/ggml-base.en.bin"
    WHISPER_LANG="en"
    ;;
  zh|ZH|cn|CN|zh-cn|zh_CN)
    MODEL="$TOOL_DIR/models/ggml-base.bin"
    WHISPER_LANG="zh"
    ;;
  auto|AUTO)
    MODEL="$TOOL_DIR/models/ggml-base.bin"
    WHISPER_LANG="auto"
    ;;
  *)
    MODEL="$TOOL_DIR/models/ggml-base.bin"
    WHISPER_LANG="$LANG"
    ;;
esac

if [ ! -f "$MODEL" ]; then
  echo "Model file not found: $MODEL" >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR/wav" "$OUTPUT_DIR/txt" "$OUTPUT_DIR/logs"

BASE_NAME="$(basename "$INPUT")"
STEM="${BASE_NAME%.*}"
EXT="${BASE_NAME##*.}"
EXT="$(printf '%s' "$EXT" | tr '[:upper:]' '[:lower:]')"
WAV_PATH="$OUTPUT_DIR/wav/$STEM.wav"
OUT_PREFIX="$OUTPUT_DIR/txt/$STEM"
LOG_PATH="$OUTPUT_DIR/logs/$STEM.log"

find_ffmpeg() {
  if [ -n "${AUDIO_TRANSCRIBE_FFMPEG:-}" ] && [ -x "$AUDIO_TRANSCRIBE_FFMPEG" ]; then
    printf '%s\n' "$AUDIO_TRANSCRIBE_FFMPEG"
    return 0
  fi

  if [ -x "$TOOL_DIR/bin/ffmpeg" ]; then
    printf '%s\n' "$TOOL_DIR/bin/ffmpeg"
    return 0
  fi

  if command -v ffmpeg >/dev/null 2>&1; then
    command -v ffmpeg
    return 0
  fi

  if command -v python3 >/dev/null 2>&1; then
    local py_ffmpeg
    py_ffmpeg="$(python3 - <<'PY' 2>/dev/null || true
try:
    import imageio_ffmpeg
    print(imageio_ffmpeg.get_ffmpeg_exe())
except Exception:
    pass
PY
)"
    if [ -n "$py_ffmpeg" ] && [ -x "$py_ffmpeg" ]; then
      printf '%s\n' "$py_ffmpeg"
      return 0
    fi
  fi

  return 1
}

convert_with_ffmpeg() {
  local ffmpeg_bin
  if ! ffmpeg_bin="$(find_ffmpeg)"; then
    echo "ffmpeg not found. Put a binary at bin/ffmpeg, install ffmpeg, or set AUDIO_TRANSCRIBE_FFMPEG." >&2
    exit 1
  fi
  "$ffmpeg_bin" -y -i "$INPUT" -vn -ac 1 -ar 16000 -c:a pcm_s16le "$WAV_PATH"
}

echo "Converting: $INPUT" >&2
{
  case "$EXT" in
    mp3)
      if [ -x "$MP3_CONVERTER" ]; then
        "$MP3_CONVERTER" "$INPUT" "$WAV_PATH"
      else
        convert_with_ffmpeg
      fi
      ;;
    m4a|m4b|mp4|aac|wav|wave|flac|ogg|opus)
      convert_with_ffmpeg
      ;;
    *)
      echo "Unsupported extension: .$EXT" >&2
      echo "Supported: mp3, m4a, m4b, mp4, aac, wav, flac, ogg, opus" >&2
      exit 1
      ;;
  esac
} > "$LOG_PATH" 2>&1

echo "Transcribing: $INPUT" >&2
"$WHISPER" \
  -ng \
  -t "$THREADS" \
  -m "$MODEL" \
  -l "$WHISPER_LANG" \
  -otxt \
  -osrt \
  -oj \
  -of "$OUT_PREFIX" \
  "$WAV_PATH" >> "$LOG_PATH" 2>&1

echo "$OUT_PREFIX.txt"
