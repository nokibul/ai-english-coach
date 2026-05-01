#!/usr/bin/env bash
set -euo pipefail

repo="Qwen/Qwen2.5-VL-7B-Instruct-AWQ"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
model_dir="${MODEL_STORAGE_DIR:-$root/models}"
dest="${1:-$model_dir/Qwen2.5-VL-7B-Instruct-AWQ}"
base_url="https://huggingface.co/${repo}/resolve/main"
segment_size=$((64 * 1024 * 1024))
parallel_jobs="${QWEN25_DOWNLOAD_JOBS:-4}"
hf_token="${HF_TOKEN:-${HUGGING_FACE_HUB_TOKEN:-}}"
curl_auth=()
if [[ -n "$hf_token" ]]; then
  curl_auth=(-H "Authorization: Bearer $hf_token")
fi

mkdir -p "$dest"

small_files=(
  ".gitattributes"
  "LICENSE"
  "README.md"
  "added_tokens.json"
  "chat_template.json"
  "config.json"
  "generation_config.json"
  "merges.txt"
  "model.safetensors.index.json"
  "preprocessor_config.json"
  "special_tokens_map.json"
  "tokenizer.json"
  "tokenizer_config.json"
  "vocab.json"
)

shards=(
  "model-00001-of-00002.safetensors"
  "model-00002-of-00002.safetensors"
)

download_file() {
  local name="$1"
  local out="$dest/$name"
  if [[ -s "$out" ]]; then
    return
  fi
  echo "Downloading $name"
  curl -fsSL "${curl_auth[@]}" --retry 8 --retry-delay 5 --connect-timeout 30 \
    -o "$out" "$base_url/$name"
}

remote_size() {
  local name="$1"
  curl -fLsI "${curl_auth[@]}" "$base_url/$name" \
    | awk 'BEGIN{IGNORECASE=1} /^x-linked-size:/ {gsub("\r","",$2); print $2; found=1} /^content-length:/ {gsub("\r","",$2); last=$2} END{if (!found && last) print last}'
}

download_range() {
  local name="$1"
  local start="$2"
  local end="$3"
  local part="$4"
  local expected=$((end - start + 1))

  if [[ -s "$part" ]]; then
    local actual
    actual=$(stat -c '%s' "$part")
    if [[ "$actual" -eq "$expected" ]]; then
      return
    fi
  fi

  curl -fsSL "${curl_auth[@]}" --retry 8 --retry-delay 5 --connect-timeout 30 \
    -r "${start}-${end}" -o "$part" "$base_url/$name"

  local actual
  actual=$(stat -c '%s' "$part")
  if [[ "$actual" -ne "$expected" ]]; then
    echo "Bad segment size for $part: got $actual, expected $expected" >&2
    return 1
  fi
}

download_shard() {
  local name="$1"
  local out="$dest/$name"
  local size
  size="$(remote_size "$name")"
  if [[ -z "$size" ]]; then
    echo "Could not determine remote size for $name" >&2
    return 1
  fi

  if [[ -s "$out" ]]; then
    local actual
    actual=$(stat -c '%s' "$out")
    if [[ "$actual" -eq "$size" ]]; then
      echo "$name already complete"
      return
    fi
  fi

  echo "Downloading $name ($size bytes)"
  local part_dir="$dest/.parts/$name"
  mkdir -p "$part_dir"

  local active=0
  local part_index=0
  local start=0
  local part
  while [[ "$start" -lt "$size" ]]; do
    local end=$((start + segment_size - 1))
    if [[ "$end" -ge "$size" ]]; then
      end=$((size - 1))
    fi
    printf -v part "%s/%05d.part" "$part_dir" "$part_index"
    download_range "$name" "$start" "$end" "$part" &
    active=$((active + 1))
    part_index=$((part_index + 1))
    start=$((end + 1))

    if [[ "$active" -ge "$parallel_jobs" ]]; then
      wait -n
      active=$((active - 1))
    fi
  done
  wait

  : > "$out.tmp"
  for part in "$part_dir"/*.part; do
    cat "$part" >> "$out.tmp"
  done

  local actual
  actual=$(stat -c '%s' "$out.tmp")
  if [[ "$actual" -ne "$size" ]]; then
    echo "Bad shard size for $name: got $actual, expected $size" >&2
    return 1
  fi
  mv "$out.tmp" "$out"
  rm -rf "$part_dir"
}

for file in "${small_files[@]}"; do
  download_file "$file"
done

for shard in "${shards[@]}"; do
  download_shard "$shard"
done

echo "Qwen2.5-VL-7B-Instruct-AWQ is downloaded to $dest"
