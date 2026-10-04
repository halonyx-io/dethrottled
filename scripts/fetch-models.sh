#!/usr/bin/env bash
# Download the one ONNX embedding model used by the semantic corpus.
#
# Weights and tokenizer stay out of git. The image build bakes in the same
# pinned revision; this script supports source installs.
#
#     ./scripts/fetch-models.sh            # embeddings (needed for the corpus)
#     ./scripts/fetch-models.sh --all      # + OCR language data
#
# Only the corpus embedding model is used by Dethrottled.
set -euo pipefail

MODELS="${DETHROTTLED_MODEL_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/dethrottled/models}"
WITH_OCR=0
[ "${1:-}" = "--all" ] && WITH_OCR=1

mkdir -p "$MODELS"
echo "model directory: $MODELS"

# The runtime needs model.onnx and tokenizer.json from the same revision.
MINILM_REVISION=1110a243fdf4706b3f48f1d95db1a4f5529b4d41
fetch_model() {
    local dir="$1" repo="$2" onnx_path="$3"
    if [ -s "$MODELS/$dir/model.onnx" ] && [ -s "$MODELS/$dir/tokenizer.json" ]; then
        echo "  $dir already present, skipping"
        return
    fi
    echo "  fetching $dir from $repo"
    mkdir -p "$MODELS/$dir"
    local base="https://huggingface.co/$repo/resolve/$MINILM_REVISION"
    curl -fsSL -o "$MODELS/$dir/model.onnx" "$base/$onnx_path"
    curl -fsSL -o "$MODELS/$dir/tokenizer.json" "$base/tokenizer.json"
}

echo
echo "embedding model:"
# 87MB, 384 dimensions, and the only embedding model this uses.
#
# multilingual-e5-small was dropped after measurement: on ten documents with
# ten known-answer queries both scored 1.00 accuracy and 1.000 MRR, but MiniLM
# separated the right answer from the best wrong one by 0.242 against e5's
# 0.037 -- six times the headroom for setting a relevance floor -- at a fifth
# of the size. Cross-language retrieval is what that trade gives up.
fetch_model emb-minilm sentence-transformers/all-MiniLM-L6-v2 onnx/model.onnx

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
