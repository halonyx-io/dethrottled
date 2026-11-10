#!/bin/sh
# Optional local Ettin 68M fp32 ONNX reranker for Dethrottled.
#
# cross-encoder/ettin-reranker-68m-v1 is Apache-2.0, English, 68M parameters.
# This fetches the universal fp32 ONNX export plus the sentence-transformers
# post-processing modules. It does not bundle anything in the API image.
#
#   ./scripts/fetch-rerank-model.sh
#   DETHROTTLED_RERANK=1 DETHROTTLED_RERANK_MODEL=<dir> ...
set -eu

REPO="cross-encoder/ettin-reranker-68m-v1"
REVISION="d166fa88ddde3c42bc3ee92f7df476d941c8204a"
TARGET="${DETHROTTLED_RERANK_MODEL:-${DETHROTTLED_MODEL_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/dethrottled/models}/rerank-ettin-68m}"
mkdir -p "$TARGET/2_Dense" "$TARGET/3_LayerNorm" "$TARGET/4_Dense"

fetch() {
    source="$1"
    target="$2"
    url="https://huggingface.co/$REPO/resolve/$REVISION/$source"
    echo "fetching $target from $REPO@$REVISION"
    curl -fsSL --retry 3 -o "$TARGET/$target" "$url"
}

fetch onnx/model.onnx model.onnx
fetch tokenizer.json tokenizer.json
fetch config.json config.json
fetch 2_Dense/model.safetensors 2_Dense/model.safetensors
fetch 3_LayerNorm/model.safetensors 3_LayerNorm/model.safetensors
fetch 4_Dense/model.safetensors 4_Dense/model.safetensors

echo "rerank model: $TARGET"
echo "set DETHROTTLED_RERANK=1 DETHROTTLED_RERANK_MODEL=$TARGET"
