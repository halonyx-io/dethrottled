#!/bin/sh
# Optional local ONNX cross-encoder for Dethrottled's opt-in reranker.
#
# GTE-reranker-modernbert-base is Apache-2.0, English, 149M parameters and
# scored best among the models tested on the SciFact reranking check. It is not
# bundled in the API image; this only fetches the files into a local directory.
#
#   ./scripts/fetch-rerank-model.sh
#   DETHROTTLED_RERANK=1 DETHROTTLED_RERANK_MODEL=<dir> ...
set -eu

REPO="Alibaba-NLP/gte-reranker-modernbert-base"
REVISION="f7481e6055501a30fb19d090657df9ec1f79ab2c"
TARGET="${DETHROTTLED_RERANK_MODEL:-${DETHROTTLED_MODEL_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/dethrottled/models}/rerank-gte}"
mkdir -p "$TARGET"
for file in model.onnx tokenizer.json config.json; do
    case "$file" in
        model.onnx) source="onnx/model_quantized.onnx" ;;
        *) source="$file" ;;
    esac
    url="https://huggingface.co/$REPO/resolve/$REVISION/$source"
    echo "fetching $file from $REPO@$REVISION"
    curl -fsSL --retry 3 -o "$TARGET/$file" "$url"
done
echo "rerank model: $TARGET"
echo "set DETHROTTLED_RERANK=1 DETHROTTLED_RERANK_MODEL=$TARGET"
