import os
import re
import warnings
import whisper

# Keep console clean
warnings.filterwarnings("ignore")

MODEL_NAME = os.getenv("WHISPER_MODEL", "large-v3")

print(f"⏳ Loading Whisper AI model ({MODEL_NAME}) once...")
model = whisper.load_model(MODEL_NAME)


def _cleanup_text(text: str) -> str:
    """Normalize spaces and punctuation spacing."""
    t = re.sub(r"\s+", " ", text).strip()
    # Remove space before punctuation: , . ! ? : ;
    t = re.sub(r"\s+([,\.!\?:;])", r"\1", t)
    return t


def _build_word_list_from_result(result: dict) -> list[dict]:
    """Collect words with timestamps from Whisper result if available."""
    all_words = []
    segments = result.get("segments", []) or []
    for seg in segments:
        words = seg.get("words", []) or []
        for w in words:
            # Ensure timestamps exist and are numeric
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
    """
    If 'words' are missing (common for some languages/models), build
    pseudo word-level timestamps by distributing segment time across tokens.
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
            # No timing info; put everything in one tiny block
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


def transcribe_audio_to_groups(
    audio_path: str,
    words_per_group: int = 2,
    language: str | None = None,      # Pass "ru" to force Russian; None = auto-detect
    pause_threshold: float = 0.45      # Break group if next word starts later than this (seconds)
):
    """
    Transcribe audio and group words with exact timestamps.
    Returns: List of (start, end, text)

    - language: set to "ru" to force Russian; None lets Whisper auto-detect.
    - words_per_group: typical 2–3 feels natural for fast delivery.
    - pause_threshold: break a chunk on pauses longer than this.
    """
    if not os.path.exists(audio_path):
        print(f"❌ Audio file not found: {audio_path}")
        return []

    print(f"👂 Transcribing audio for perfect sync: {os.path.basename(audio_path)}...")

    transcribe_kwargs = {
        "word_timestamps": True,
        "task": "transcribe",  # keep original language; do not translate
        "verbose": False,
        "temperature": 0.0,
        "beam_size": 5,  # better decoding
        "best_of": 5,
    }
    if language:
        transcribe_kwargs["language"] = language  # e.g., "ru"

    result = model.transcribe(audio_path, **transcribe_kwargs)
    segments = result.get("segments", []) or []

    # Try true word-level timestamps first
    all_words = _build_word_list_from_result(result)

    # Fallback if 'words' missing (some Whisper builds/languages)
    if not all_words:
        all_words = _fallback_words_from_segments(segments)

    final_groups = []
    current_group_words = []
    group_start = 0.0

    for i, word in enumerate(all_words):
        if not current_group_words:
            group_start = float(max(0.0, word["start"]))

        current_group_words.append((word["word"] or "").strip())

        is_last_word = (i == len(all_words) - 1)
        is_full = (len(current_group_words) >= words_per_group)

        next_word_dist = 0.0
        if not is_last_word:
            next_start = float(all_words[i + 1]["start"])
            this_end = float(word["end"])
            next_word_dist = max(0.0, next_start - this_end)

        if is_full or is_last_word or next_word_dist > pause_threshold:
            group_end = float(max(group_start + 0.01, word["end"]))
            text = " ".join(current_group_words)
            text = _cleanup_text(text)
            final_groups.append((group_start, group_end, text))
            current_group_words = []

    print(f"✅ Transcription done: {len(final_groups)} subtitle chunks generated.")
    return final_groups


def transcribe_audio_to_words(
    audio_path: str,
    language: str | None = None,
):
    """
    Transcribe audio and return word-level timestamps for word-by-word highlighting.
    Returns: List of (word, start, end)
    """
    if not os.path.exists(audio_path):
        print(f"❌ Audio file not found: {audio_path}")
        return []

    print(f"👂 Transcribing audio for word-level sync: {os.path.basename(audio_path)}...")

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

    result = model.transcribe(audio_path, **transcribe_kwargs)

    words = _build_word_list_from_result(result)
    if not words:
        words = _fallback_words_from_segments(result.get("segments", []))

    output = [
        (w["word"].strip().upper(), float(w["start"]), float(w["end"]))
        for w in words if w["word"].strip()
    ]
    print(f"✅ Word-level transcription done: {len(output)} words.")
    return output