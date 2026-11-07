import difflib
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


def _core(token: str) -> str:
    """A token without the punctuation around it: '"Avada?' -> 'Avada'."""
    return re.sub(r"^[^\w]+|[^\w]+$", "", token)


def _script_punctuation(token: str, is_last: bool) -> str:
    """The punctuation after a script word. A "..." is the script's dramatic beat, usually
    inside a sentence ("it was... Gojo"), so it becomes "…", which nothing treats as a
    sentence end. A capital letter after it can't tell the two apart: names are capitalized."""
    trail = re.search(r"[^\w]*$", token).group()
    if trail.startswith(("...", "…")) and not is_last:
        return "…"
    return trail


def _match_script(words: list[dict], script_text: str) -> list[dict]:
    """
    Give Whisper's words the script's spelling and punctuation wherever they line up.

    The narration is TTS reading the script, so the script is what was said.
    - Spelling: Whisper writes names it has never heard as words it knows ("Avida" became
      "Avada" in the subtitles). A word is respelled only in a same-length block of
      differences and when it is spelled close to its script word. Digits stay as
      Whisper wrote them: the graphic cards match numbers as digits.
    - Punctuation: Whisper writes a period wherever the voice pauses, and the "..." the
      script uses for a dramatic beat also ends in a period, so a reaction sound played in
      the middle of a sentence. The script's punctuation decides instead, and every "..."
      becomes "…" (at worst a sound waits one sentence longer, never cuts one in half).
    Words are lined up with difflib. Timing never changes.
    """
    spoken = re.sub(r"\[[^\]]*\]", " ", script_text)   # [curious] etc. are not spoken
    script_words = [t for t in re.findall(r"\S+", spoken) if _core(t)]
    a = [_core(w["word"]).lower() for w in words]
    b = [_core(t).lower() for t in script_words]
    fixed = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag not in ("equal", "replace") or i2 - i1 != j2 - j1:
            continue
        for i, j in zip(range(i1, i2), range(j1, j2)):
            old = words[i]["word"]
            core = _core(old)
            if not core:
                continue
            if (tag == "replace" and not any(ch.isdigit() for ch in a[i] + b[j])
                    and difflib.SequenceMatcher(None, a[i], b[j]).ratio() >= 0.6):
                fixed.append(f"{core} -> {_core(script_words[j])}")
                core = _core(script_words[j])
            lead = old[:old.find(_core(old))]
            words[i]["word"] = lead + core + _script_punctuation(script_words[j], j == len(script_words) - 1)
    if fixed:
        print(f"Respelled to match the script: {', '.join(fixed)}")
    return words


def _join_split_tokens(words: list[dict]) -> list[dict]:
    """Glue back what Whisper splits off a word: '10' + '-episode', and '£50' + ',000'
    (left split, the £50,000 stat card and its sound effect both missed the number)."""
    joined = []
    for w in words:
        tail = w["word"]
        split_dash = tail.startswith("-") and len(tail) > 1
        split_number = bool(re.match(r"^[,.]\d", tail)) and joined and joined[-1]["word"][-1:].isdigit()
        if joined and (split_dash or split_number):
            joined[-1] = {**joined[-1], "word": joined[-1]["word"] + w["word"], "end": w["end"]}
        else:
            joined.append(w)
    return joined


def transcribe_audio_to_words(
    audio_path: str,
    language: str | None = None,
    script_text: str | None = None,
):
    """Transcribe audio into word-level timestamps: a list of (WORD, start, end).

    Pass the script the audio was generated from: its spelling and punctuation replace
    Whisper's, which misspells names and ends sentences at every pause."""
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
    if script_text:
        words = _match_script(words, script_text)
    words = _join_split_tokens(words)

    output = [
        (w["word"].strip().upper(), float(w["start"]), float(w["end"]))
        for w in words if w["word"].strip()
    ]
    print(f"Word-level transcription done: {len(output)} words.")
    return output