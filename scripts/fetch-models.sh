#!/usr/bin/env bash
# Download pinned ONNX embedding models for the semantic corpus.
#
# Weights and tokenizer stay out of git. The image build bakes in the same
# pinned revision; this script supports source installs.
#
#     ./scripts/fetch-models.sh            # embeddings (needed for the corpus)
#     ./scripts/fetch-models.sh --multilingual  # + multilingual E5
#     ./scripts/fetch-models.sh --all      # + E5 and OCR language data
#
# These are corpus models, not live-web rerankers.
set -euo pipefail

MODELS="${DETHROTTLED_MODEL_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/dethrottled/models}"
WITH_OCR=0
WITH_MULTILINGUAL=0
for arg in "$@"; do
    case "$arg" in
        --all) WITH_OCR=1; WITH_MULTILINGUAL=1 ;;
        --multilingual) WITH_MULTILINGUAL=1 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

mkdir -p "$MODELS"
echo "model directory: $MODELS"

# The runtime needs model.onnx and tokenizer.json from the same revision.
MINILM_REVISION=1110a243fdf4706b3f48f1d95db1a4f5529b4d41
fetch_model() {
    local dir="$1" repo="$2" onnx_path="$3" revision="$4"
    if [ -s "$MODELS/$dir/model.onnx" ] && [ -s "$MODELS/$dir/tokenizer.json" ]; then
        echo "  $dir already present, skipping"
        return
    fi
    echo "  fetching $dir from $repo"
    mkdir -p "$MODELS/$dir"
    local base="https://huggingface.co/$repo/resolve/$revision"
    curl -fsSL -o "$MODELS/$dir/model.onnx" "$base/$onnx_path"
    curl -fsSL -o "$MODELS/$dir/tokenizer.json" "$base/tokenizer.json"
}

echo
echo "embedding model:"
# MiniLM remains the original English index; E5 has a separate version/floor.
fetch_model emb-minilm sentence-transformers/all-MiniLM-L6-v2 onnx/model.onnx "$MINILM_REVISION"
if [ "$WITH_MULTILINGUAL" = "1" ]; then
    E5_REVISION=614241f622f53c4eeff9890bdc4f31cfecc418b3
    fetch_model emb-e5 intfloat/multilingual-e5-small onnx/model.onnx "$E5_REVISION"
    echo "  set DETHROTTLED_MULTILINGUAL_CORPUS=1 DETHROTTLED_E5_REVISION=$E5_REVISION"
fi

if [ "$WITH_OCR" = "1" ]; then
    echo
    echo "OCR language data:"
    # Tesseract reads TESSDATA_PREFIX, and that REPLACES the system directory
    # rather than adding to it -- so a user directory holding only fra would
    # advertise English and then fail every page trying to load it. Hence the
    # symlinks.
    TESS="$MODELS/tessdata"
    mkdir -p "$TESS"
    for lang in fra ara deu spa; do
        if [ ! -f "$TESS/$lang.traineddata" ]; then
            echo "  fetching $lang"
            curl -fsSL -o "$TESS/$lang.traineddata" \
                "https://github.com/tesseract-ocr/tessdata_fast/raw/main/$lang.traineddata"
        fi
    done
    # tessdata_fast, not tessdata_best: on a real Arabic document both recovered
    # exactly 80.5% of tokens and `best` took 88% longer. It does not earn the
    # extra 12.6MB.
    for sys in /usr/share/tesseract-ocr/*/tessdata /usr/share/tessdata; do
        for lang in eng osd; do
            [ -f "$sys/$lang.traineddata" ] && ln -sf "$sys/$lang.traineddata" "$TESS/$lang.traineddata"
        done
    done
    echo "  set TESSDATA_PREFIX=$TESS"
fi

echo
echo "done. total size:"
du -sh "$MODELS"
