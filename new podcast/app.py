from __future__ import annotations

import os
import re
import tempfile
import math
from collections import Counter
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder=".", static_url_path="")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "tiny")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE", "int8")
WHISPER_LANG = os.getenv("WHISPER_LANG", "en")

STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "is", "are",
    "was", "were", "be", "been", "it", "that", "this", "as", "at", "by", "from", "we",
    "you", "i", "they", "he", "she", "but", "if", "so", "not", "do", "does", "did", "your",
    "our", "their", "about", "into", "out", "up", "down", "can", "could", "will", "would"
}

def _load_model():
    """Loads the Whisper model into memory when the application starts."""
    from faster_whisper import WhisperModel
    print(f"Loading transcription model ({WHISPER_MODEL}, {WHISPER_DEVICE}, {WHISPER_COMPUTE})...")
    model = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE)
    print("Model loaded.")
    return model

# Load the model once at startup
MODEL = _load_model()
@app.after_request
def add_cors_headers(response):
    # Allow frontend opened via file:// or different localhost port to call this API.
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return response


@app.get("/")
def home():
    return send_from_directory(".", "index.html")


@app.get("/<path:path>")
def static_files(path: str):
    return send_from_directory(".", path)


@app.route("/process", methods=["OPTIONS"])
def process_options():
    return ("", 204)


def words(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z][a-zA-Z'-]{1,}", text.lower())


def extract_keywords(text: str, top_k: int = 5) -> list[str]:
    toks = [w for w in words(text) if w not in STOPWORDS]
    return [w for w, _ in Counter(toks).most_common(top_k)]


def summarize(text: str) -> str:
    clean = " ".join(text.split())
    if not clean:
        return "No summary available."
    if len(clean) <= 220:
        return clean
    return clean[:220].rsplit(" ", 1)[0] + "..."


def segment_chunks(chunks: list[dict], target_segments: int = 5) -> list[dict]:
    if not chunks:
        return []

    target_segments = max(1, target_segments)
    duration_start = chunks[0]["start"]
    duration_end = chunks[-1]["end"]
    total_duration = max(0.1, duration_end - duration_start)
    step = total_duration / target_segments

    buckets: list[list[dict]] = [[] for _ in range(target_segments)]

    for c in chunks:
        midpoint = (c["start"] + c["end"]) / 2
        idx = int((midpoint - duration_start) / step) if step > 0 else 0
        idx = min(max(idx, 0), target_segments - 1)
        buckets[idx].append(c)

    out = []
    last_end = duration_start
    for i, group in enumerate(buckets):
        if group:
            seg_start = group[0]["start"]
            seg_end = group[-1]["end"]
            exact = " ".join(c["text"] for c in group).strip()
        else:
            # Keep exactly 5 segments even if speech is sparse.
            seg_start = duration_start + (i * step)
            seg_end = seg_start + step
            exact = ""

        keys = extract_keywords(exact, 6)
        title = f"Topic {i + 1}: {keys[0].title()}" if keys else f"Topic {i + 1}"
        summary_text = summarize(exact) if exact else "No transcript text in this interval."

        seg_start = max(seg_start, last_end)
        seg_end = max(seg_end, seg_start)
        last_end = seg_end

        out.append(
            {
                "title": title,
                "start": round(seg_start, 2),
                "end": round(seg_end, 2),
                "keywords": keys,
                "summary": summary_text,
                "exactWords": exact,
            }
        )

    return out


def infer_target_segments(chunks: list[dict], max_segments: int = 8) -> int:
    """Infer topic count from audio/transcript density, capped by max_segments."""
    if not chunks:
        return 1

    start = chunks[0]["start"]
    end = chunks[-1]["end"]
    duration_sec = max(1.0, end - start)
    duration_min = duration_sec / 60.0

    # Heuristic 1: roughly one topic per ~4 minutes of audio.
    duration_based = math.ceil(duration_min / 4.0)
    # Heuristic 2: enough buckets to avoid overpacking chunk text.
    chunk_based = math.ceil(len(chunks) / 8.0)

    inferred = max(1, max(duration_based, chunk_based))
    return min(max_segments, inferred)


def transcribe(audio_path: str) -> tuple[list[dict], str]:
    model = MODEL
    segments, _ = model.transcribe(
        audio_path,
        beam_size=1,
        best_of=1,
        temperature=0,
        vad_filter=False,
        condition_on_previous_text=False,
        language=WHISPER_LANG if WHISPER_LANG else None,
    )

    chunks = []
    full_text_parts = []
    for seg in segments:
        text = (seg.text or "").strip()
        if not text:
            continue
        chunks.append({"start": float(seg.start), "end": float(seg.end), "text": text})
        full_text_parts.append(text)

    return chunks, " ".join(full_text_parts)


@app.post("/process")
def process_audio():
    if "audio" not in request.files:
        return jsonify({"error": "No audio file sent"}), 400

    upload = request.files["audio"]
    if not upload.filename:
        return jsonify({"error": "Empty filename"}), 400

    suffix = Path(upload.filename).suffix or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        temp_path = tmp.name
        upload.save(temp_path)

    try:
        chunks, full_transcript = transcribe(temp_path)
        if not chunks:
            return jsonify({"error": "No speech detected in this file"}), 422

        target = 5
        segments = segment_chunks(chunks, target_segments=target)
        return jsonify(
            {
                "segments": segments,
                "fullTranscript": full_transcript,
                "meta": {
                    "engine": f"faster-whisper-{WHISPER_MODEL}",
                    "targetSegments": target,
                    "note": "Transcription is model output from your audio.",
                },
            }
        )
    except Exception as exc:
        return jsonify({"error": f"Transcription failed: {exc}"}), 500
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=5000)
