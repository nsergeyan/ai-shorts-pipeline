import os
import re
import warnings
import whisper

warnings.filterwarnings("ignore")

MODEL_NAME = os.getenv("WHISPER_MODEL", "large-v3")

_model = None


def _get_model():
    global _model
    if _model is None:
        print(f"Loading Whisper model ({MODEL_NAME})...")
        _model = whisper.load_model(MODEL_NAME)
    return _model


def _build_word_list_from_result(result: dict) -> list[dict]:
    """Collect words with timestamps from Whisper result if available."""
    all_words = []
    segments = result.get("segments", []) or []
    for seg in segments:
        words = seg.get("words", []) or []
        for w in words:
            if "start" in w and "end" in w:
                try:
                    w_start = float(w["start"])
                    w_end = float(w["end"])
                except (TypeError, ValueError):
                    continue
                text = (w.get("word") or "").strip()
                if text:
                    all_words.append({"word": text, "start": w_start, "end": w_end})
    return all_words


def _fallback_words_from_segments(segments: list[dict]) -> list[dict]:
    """Build pseudo word timestamps by spreading each segment's time across its tokens.

    Used when Whisper returns no per-word timing (happens with some languages/models).
    """
    all_words = []
    for seg in segments:
        seg_text = (seg.get("text") or "").strip()
        if not seg_text:
            continue
        tokens = re.findall(r"\S+", seg_text)
        seg_start = float(seg.get("start") or 0.0)
        seg_end = float(seg.get("end") or seg_start)
        seg_dur = max(0.0, seg_end - seg_start)

        if not tokens:
            continue

        if seg_dur <= 0:
            all_words.append(
                {"word": seg_text, "start": seg_start, "end": seg_start + 0.2}
            )
            continue

        word_dur = seg_dur / len(tokens)
        t = seg_start
        for tok in tokens:
            tok = tok.strip()
            if not tok:
                continue
            start = t
            end = min(seg_end, t + word_dur)
            all_words.append({"word": tok, "start": start, "end": end})
            t = end

    return all_words


def transcribe_audio_to_words(
    audio_path: str,
    language: str | None = None,
):
    """Transcribe audio into word-level timestamps: a list of (WORD, start, end)."""
    if not os.path.exists(audio_path):
        print(f"Audio file not found: {audio_path}")
        return []

    print(f"Transcribing audio for word-level sync: {os.path.basename(audio_path)}...")

    transcribe_kwargs = {
        "word_timestamps": True,
        "task": "transcribe",
        "verbose": False,
        "temperature": 0.0,
        "beam_size": 5,
        "best_of": 5,
    }
    if language:
        transcribe_kwargs["language"] = language

    result = _get_model().transcribe(audio_path, **transcribe_kwargs)

    words = _build_word_list_from_result(result)
    if not words:
        words = _fallback_words_from_segments(result.get("segments", []))

    output = [
        (w["word"].strip().upper(), float(w["start"]), float(w["end"]))
        for w in words if w["word"].strip()
    ]
    print(f"Word-level transcription done: {len(output)} words.")
    return output