#!/usr/bin/env bash
set -euo pipefail

input_file="${1:-/Users/lisuiting/Downloads/book.txt}"
output_root="${2:-/Users/lisuiting/Downloads/Obsidian Vault/Littlebean音频下载}"

sanitize_name() {
  printf '%s' "$1" |
    tr '/:' '__' |
    tr -d '\r' |
    sed -E 's/[[:space:]]+/ /g; s/^ //; s/ $//; s/^\.+//; s/[[:cntrl:]]//g' |
    cut -c 1-120
}

book_id_from_url() {
  printf '%s' "$1" | sed -nE 's/.*[?&]xbe_book_id=([0-9]+).*/\1/p'
}

mkdir -p "$output_root"
manifest="$output_root/manifest.tsv"
printf 'line\tbook_id\tfolder\taudio_count\tstatus\n' > "$manifest"

line_no=0
while IFS= read -r page_url || [ -n "$page_url" ]; do
  page_url="${page_url//$'\r'/}"
  [ -z "$page_url" ] && continue
  line_no=$((line_no + 1))

  book_id="$(book_id_from_url "$page_url")"
  if [ -z "$book_id" ]; then
    printf '%s\t\t\t0\tmissing_book_id\n' "$line_no" >> "$manifest"
    continue
  fi

  api_url="https://littlebean.baobaobooks.com/xiaobienapi/bookshelf/v1/v3_3_0/user/audios?book_id=${book_id}"
  json_file="$output_root/${line_no}-${book_id}.json"
  curl -L -sS \
    -H 'X-HB-Client-Type: xiaobien-mobile' \
    -H 'User-Agent: Mozilla/5.0' \
    -H "Wechat-Url: $page_url" \
    "$api_url" > "$json_file"

  audio_count="$(jq '[.items[]? | select(.resource_url != null and .resource_url != "")] | length' "$json_file")"
  first_name="$(jq -r '.items[]? | select(.resource_name != null and .resource_name != "") | .resource_name' "$json_file" | sed -n '1p')"
  if [ -n "$first_name" ]; then
    book_name="$(sanitize_name "$first_name")"
  else
    book_name="book_${book_id}"
  fi

  folder="$output_root/$(printf '%02d' "$line_no") - $book_name"
  mkdir -p "$folder"

  idx=0
  while IFS= read -r item; do
    idx=$((idx + 1))
    resource_name="$(printf '%s' "$item" | base64 --decode | jq -r '.resource_name // "audio"')"
    first_type="$(printf '%s' "$item" | base64 --decode | jq -r '.first_type_name // ""')"
    sec_type="$(printf '%s' "$item" | base64 --decode | jq -r '.sec_type_name // ""')"
    resource_url="$(printf '%s' "$item" | base64 --decode | jq -r '.resource_url // ""')"
    clean_resource_name="$(sanitize_name "$resource_name")"
    clean_first_type="$(sanitize_name "$first_type")"
    clean_sec_type="$(sanitize_name "$sec_type")"
    suffix=""
    [ -n "$clean_first_type" ] && suffix="$suffix - $clean_first_type"
    [ -n "$clean_sec_type" ] && suffix="$suffix $clean_sec_type"
    file="$folder/${idx} - ${clean_resource_name}${suffix}.mp3"

    if [ -s "$file" ]; then
      printf 'skip %s\n' "$file"
      continue
    fi

    tmp_file="${file}.part"
    curl -L --fail --retry 5 --retry-delay 2 --retry-all-errors -C - -sS -o "$tmp_file" "$resource_url"
    mv "$tmp_file" "$file"
    printf 'downloaded %s\n' "$file"
  done < <(jq -r '.items[]? | select(.resource_url != null and .resource_url != "") | @base64' "$json_file")

  printf '%s\t%s\t%s\t%s\tdone\n' "$line_no" "$book_id" "$folder" "$audio_count" >> "$manifest"
done < "$input_file"

printf 'Manifest: %s\n' "$manifest"
