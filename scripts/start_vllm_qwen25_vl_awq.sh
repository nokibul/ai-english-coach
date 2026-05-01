#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
app_data_dir="${APP_DATA_DIR:-$root/app_data}"
model_storage_dir="${MODEL_STORAGE_DIR:-$root/models}"
model_path="${VLLM_MODEL_PATH:-$model_storage_dir/Qwen2.5-VL-7B-Instruct-AWQ}"
served_model_name="${VLLM_MODEL:-Qwen/Qwen2.5-VL-7B-Instruct-AWQ}"
uploads_path="${VLLM_ALLOWED_MEDIA_PATH:-${UPLOADS_DIR:-$app_data_dir/uploads}}"
quantization="${VLLM_QUANTIZATION:-awq_marlin}"

if [[ "$uploads_path" != /* ]]; then
  uploads_path="$root/$uploads_path"
fi

exec "$root/.venv/bin/vllm" serve "$model_path" \
  --host "${VLLM_HOST:-127.0.0.1}" \
  --port "${VLLM_PORT:-8000}" \
  --api-key "${VLLM_API_KEY:-local-dev}" \
  --served-model-name "$served_model_name" \
  --allowed-local-media-path "$uploads_path" \
  --quantization "$quantization" \
  --dtype half \
  --max-model-len "${VLLM_MAX_MODEL_LEN:-4096}" \
  --gpu-memory-utilization "${VLLM_GPU_MEMORY_UTILIZATION:-0.9}"
