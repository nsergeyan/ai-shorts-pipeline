# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## What This Project Does

An automated pipeline that produces YouTube Shorts and TikTok videos. Given a structured script prompt, it downloads relevant footage from YouTube, generates narration (ElevenLabs), composes background music (ElevenLabs), transcribes for word-level subtitles (Whisper), and renders the final 1080×1920 vertical video via Remotion + FFmpeg. Finished videos go to `data/final/`.

## Running the Pipeline

```bash
source .venv/bin/activate
python main.py
```

Edit `MANUAL_DATA` at the top of `main.py` to set the topic, script, YouTube queries, and voice settings before running.

There are no automated tests or linters configured.

## Architecture

### Entry point

- **`main.py`** — manual pipeline. You supply `MANUAL_DATA` (topic, script, queries, music prompt, voice name). Gemini evaluates downloaded videos and finds the best scene before editing.

### Module responsibilities (`modules/`)

| Module | Purpose |
|---|---|
| `gameplay_fetcher.py` | YouTube search + download via yt-dlp; 3-method fallback chain (android → no-cookie → CLI); trims to 300s |
| `newvoice.py` | ElevenLabs TTS using `eleven_v3` (EN) or `eleven_multilingual_v2` (RU/ES); applies ffmpeg `atempo=1.1` speed boost |
| `music_generator.py` | ElevenLabs `music.compose()` — generates 90s instrumental from a mood/genre prompt |
| `transcriber.py` | OpenAI Whisper `large-v3` lazy-loaded on first call; returns word-level `(word, start, end)` tuples |
| `video_editor.py` | Remotion render orchestration + FFmpeg CTA composite (see below) |
| `tiktok_checker.py` | Fetches TikTok captions via yt-dlp to detect duplicate topics |

### Video editor (`modules/video_editor.py`)

The editor no longer uses MoviePy. It runs in two stages:

**Stage 1 — Remotion render:**
1. Starts a local HTTP server (Python `http.server`) to serve project files — Remotion requires `http://` URLs
2. Writes `remotion/props.json` with clip paths, audio paths, word timestamps, timing data
3. Calls `npx remotion render ShortVideo` inside `remotion/` — Chrome Headless Shell renders each frame

**Stage 2 — FFmpeg CTA composite:**
After Remotion outputs a base MP4, FFmpeg overlays the green-screen CTA for the last 8 seconds using `chromakey` filter. The CTA overlaps the narration (not appended after).

Key function: `merge_audio_video(video_paths, audio_path, ..., words_data, cta_path, punch_times)`

### Remotion composition (`remotion/src/`)

| File | Purpose |
|---|---|
| `Root.tsx` | Registers `ShortVideo` composition; `calculateMetadata` sets duration from `totalDurationSec` prop |
| `compositions/ShortVideo.tsx` | Main composition: blurred background + contained foreground per clip, audio mix, subtitles, flash cuts, zoom punch, progress bar |
| `components/WordHighlight.tsx` | Word-level subtitles: 3 words/line, active word yellow (#FFE000), spring pop, semi-transparent pill background, positioned at `top: 25%` |
| `components/ProgressBar.tsx` | Thin yellow bar at the bottom edge of the video zone (~66% from top) |
| `components/HookCard.tsx` | Optional hook text overlay — not used in pipeline by default |

### Video layout (9:16 / 1080×1920)

```
top ~34%    → blurred background bar  → SUBTITLES (top: 25%)
middle ~32% → full landscape video    → objectFit: contain, nothing cropped
bottom ~34% → blurred background bar  → CTA overlay (FFmpeg, last 8s, y-offset 500px)
```

### Transitions

- **Hard cuts** everywhere between clips (no dissolve, no slide)
- **Flash cuts** — every 3rd transition fires a 2-frame white flash (opacity 0.5), index pattern `i % 3 === 1`
- **Zoom punch** — optional `punch_times: number[]` prop triggers a quick scale burst (1.0→1.06, spring back) at specific narration timestamps

### Configuration (`config.py`)

Central path definitions and API key loading from `.env`. All modules import paths from here. `CTA_PATH` points to the green-screen follow-button video at the project root.

### Key settings in `main.py` (top of file)

```python
LANGUAGE = "en"              # "en", "ru", or "es"
MUSIC_VOLUME = 0.07
CLEANUP_FILES = True         # deletes intermediates after render
CLIP_DURATION = 60.0
SLEEP_INTERVAL = 5
```

### Data directories (`data/`)

- `data/gameplay/` — downloaded background videos (deleted after render if `CLEANUP_FILES`)
- `data/music/` — generated music MP3s (deleted after render)
- `data/audio/` — ElevenLabs narration MP3s (deleted after render)
- `data/final/` — finished shorts (kept)

### Voice names (`modules/newvoice.py`)

```python
VOICES = {
    "hamid": "yr43K8H5LoTp6S1QFSGg",   # English
    "Molodoy": "YjESejviApN7SHrbfnA2",  # Russian
    "spanish_guy": "nR2KQXVwn2zMK8FALNCh",  # Spanish
}
```

### Multi-source clip selection (`main.py`)

The pipeline tries up to 6 YouTube queries per run (official, creditless, AMV, episode/arc, tribute, 4K remaster) and collects up to `MAX_SOURCE_VIDEOS = 3` approved clips. Rejected videos are deleted immediately.

All approved videos are uploaded to Gemini in a single call via `find_scenes_with_gemini(video_paths, script_segments)`. Gemini watches all of them and returns an edit plan: `{index, video_index, start}` per narration segment. Each clip is trimmed from its assigned source video.

### Performance notes (`main.py`, `modules/transcriber.py`)

- **Music runs in background** — `generate_music()` is submitted to a `ThreadPoolExecutor` immediately after videos are approved, overlapping with voice generation, Whisper, and scene detection. `music_future.result()` is called just before render.
- **Whisper is lazy-loaded** — `large-v3` only loads when `transcribe_audio_to_words()` is first called, not at import time. Spanish runs never load the model.
- **Gemini ACTIVE polling is parallel** — after uploading multiple files, all pending files are checked in each sleep cycle instead of sequentially.

### Gemini usage (`main.py`)

Four functions call Gemini 2.5 Flash:
- `evaluate_video_with_genai()` — scores downloaded footage (relevance, hook, technical); retries on 503/429 up to 5 attempts
- `find_scenes_with_gemini()` — uploads all approved videos, returns multi-source edit plan; retries on 503/429 up to 5 attempts
- `find_scene_with_gemini()` — fallback single-video scene finder (used for Spanish or transcription failure)
- `evaluate_music_with_genai()` — scores generated music for mood/energy/voice fit (called optionally)

### External dependencies

- **Gemini** (`google-genai`): keys in `.env` as `GEMINI_API_KEYS` (comma-separated for rotation)
- **ElevenLabs**: key in `.env` as `ELEVENLABS_API_KEY`; account needs `music_generation` permission enabled
- **yt-dlp**: keep updated (`pip install -U yt-dlp`) — YouTube breaks it regularly
- **Whisper**: `large-v3` model (~3GB) downloads automatically on first run
- **FFmpeg**: install via Homebrew (`brew install ffmpeg`) — ImageMagick no longer required
- **Node.js + Remotion**: `cd remotion && npm install` — Chrome Headless Shell downloads automatically on first render
