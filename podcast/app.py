from __future__ import annotations

import os
import re
import tempfile
import math
import json
import shutil
from collections import Counter
from pathlib import Path
from datetime import datetime

from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder=".", static_url_path="")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "tiny")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE", "int8")
WHISPER_LANG = os.getenv("WHISPER_LANG", "en")
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "outputs"))

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


def safe_stem(name: str) -> str:
    stem = Path(name).stem
    clean = re.sub(r"[^a-zA-Z0-9._-]+", "_", stem).strip("._")
    return clean or "audio"


def build_summary_from_segments(segments: list[dict]) -> str:
    lines = []
    for idx, seg in enumerate(segments, start=1):
        title = seg.get("title", f"Topic {idx}")
        start = seg.get("start", 0)
        end = seg.get("end", 0)
        keywords = ", ".join(seg.get("keywords", []))
        summary = seg.get("summary", "")
        lines.append(f"{idx}. {title} ({start:.2f}s - {end:.2f}s)")
        lines.append(f"   Keywords: {keywords}")
        lines.append(f"   Summary: {summary}")
        lines.append("")
    return "\n".join(lines).strip()


def write_artifacts(upload_name: str, temp_audio_path: str, segments: list[dict], full_transcript: str) -> dict:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUT_DIR / f"{safe_stem(upload_name)}_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    audio_ext = Path(upload_name).suffix or ".wav"
    audio_out = run_dir / f"audio{audio_ext}"
    transcript_out = run_dir / "transcript.txt"
    segments_out = run_dir / "topic_segments.json"
    summary_out = run_dir / "summary.txt"

    shutil.copy2(temp_audio_path, audio_out)
    transcript_out.write_text(full_transcript or "", encoding="utf-8")
    segments_out.write_text(json.dumps(segments, indent=2, ensure_ascii=False), encoding="utf-8")
    summary_out.write_text(build_summary_from_segments(segments), encoding="utf-8")

    return {
        "outputDir": str(run_dir),
        "audioFile": str(audio_out),
        "transcriptFile": str(transcript_out),
        "segmentsFile": str(segments_out),
        "summaryFile": str(summary_out),
    }


@app.post("/process")
def process_audio():
    uploads = []
    if "audio" in request.files:
        uploads.extend(request.files.getlist("audio"))
    if "audio_files" in request.files:
        uploads.extend(request.files.getlist("audio_files"))

    # Filter out empty file pickers.
    uploads = [u for u in uploads if u and u.filename]

    if not uploads:
        return jsonify({"error": "No audio file sent"}), 400

    def process_one(upload):
        suffix = Path(upload.filename).suffix or ".wav"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            temp_path = tmp.name
            upload.save(temp_path)

        try:
            chunks, full_transcript = transcribe(temp_path)
            if not chunks:
                return {
                    "fileName": upload.filename,
                    "error": "No speech detected in this file",
                    "segments": [],
                    "fullTranscript": "",
                }

            target = 5
            segments = segment_chunks(chunks, target_segments=target)
            artifacts = write_artifacts(upload.filename, temp_path, segments, full_transcript)
            return {
                "fileName": upload.filename,
                "segments": segments,
                "fullTranscript": full_transcript,
                "artifacts": artifacts,
                "meta": {
                    "engine": f"faster-whisper-{WHISPER_MODEL}",
                    "targetSegments": target,
                    "note": "Transcription is model output from your audio.",
                },
            }
        except Exception as exc:
            return {
                "fileName": upload.filename,
                "error": f"Transcription failed: {exc}",
                "segments": [],
                "fullTranscript": "",
            }
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    results = [process_one(upload) for upload in uploads]

    # Backward-compatible response for single-file callers.
    if len(results) == 1:
        only = results[0]
        if "error" in only and not only.get("segments"):
            return jsonify({"error": only["error"]}), 422
        return jsonify(
            {
                "segments": only.get("segments", []),
                "fullTranscript": only.get("fullTranscript", ""),
                "meta": only.get("meta", {}),
            }
        )

    return jsonify({"results": results, "count": len(results)})


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=5000)
