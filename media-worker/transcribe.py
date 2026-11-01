import io
import json
import os
import sys
import threading

import av
import numpy as np
from faster_whisper import WhisperModel

lock = threading.Lock()
model = None


def transcribe(data):
    global model
    # Decode incrementally, enforcing duration before allocating an unbounded waveform.
    samples, count = [], 0
    ceiling = int(os.getenv("MEDIA_MAX_SECONDS", "1800")) * 16000
    with av.open(io.BytesIO(data)) as container:
        if not container.streams.audio:
            raise ValueError("no_audio_stream")
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        for frame in container.decode(audio=0):
            for audio in resampler.resample(frame):
                chunk = audio.to_ndarray().flatten()
                count += chunk.size
                if count > ceiling:
                    raise ValueError("media_duration_limit")
                samples.append(chunk)
    if not samples:
        raise ValueError("no_audio_stream")
    waveform = np.concatenate(samples).astype(np.float32) / 32768
    with lock:
        if model is None:
            model = WhisperModel(
                os.getenv("WHISPER_MODEL", "small"),
                device="cpu",
                compute_type="int8",
                download_root="/models",
            )
        segments, info = model.transcribe(waveform, beam_size=5, vad_filter=True)
        result = [
            {"start_seconds": s.start, "end_seconds": s.end, "text": s.text.strip()}
            for s in segments
            if s.text.strip()
        ]
    return {
        "segments": result,
        "language": info.language,
        "duration_seconds": len(waveform) / 16000,
    }


if __name__ == "__main__":
    with open(sys.argv[1], "rb") as source:
        data = source.read()
    json.dump(transcribe(data), sys.stdout)
