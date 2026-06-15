# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

An automated YouTube/TikTok Shorts factory. Given a content niche, it uses AI to: generate a script (Gemini 2.5 Flash + Google Search grounding), download background video footage (yt-dlp from YouTube), synthesize narration (ElevenLabs), transcribe for subtitles (Whisper), and render the final vertical short (MoviePy + ffmpeg). Finished videos go to `data/final/`.

## Running the Pipelines

```bash
# Activate the virtual environment first
source .venv/bin/activate

# Fully automated pipeline (AI picks topic from MY_NICHES, generates script, edits video)
python main2.py

# Manual pipeline (edit MANUAL_DATA dict in the file to set topic/script/queries)
python mainmanualnewvoice.py

# Run individual modules in isolation (each has an if __name__ == "__main__" block)
python modules/script_generator.py
python modules/gameplay_fetcher.py
python modules/music_fetcher.py
python modules/voice_generator.py
python modules/newvoice.py
python modules/transcriber.py
```

There are no automated tests or linters configured.

## Architecture

### Two entry points, one shared module set

- **`main2.py`** — fully automated: Gemini picks a topic from `MY_NICHES`, checks TikTok/YouTube for duplicates, generates a script, runs the pipeline.
- **`mainmanualnewvoice.py`** — manual: you supply `MANUAL_DATA` (topic, script, queries). It adds Gemini-based video evaluation (`evaluate_video_with_genai`) and scene-finding (`find_scene_with_gemini`) before editing.

### Module responsibilities (`modules/`)

| Module | Purpose |
|---|---|
| `script_generator.py` | Wraps Gemini 2.5 Flash; rotates 3 API keys on 429 errors; has separate prompts per language (ru/es/en) |
| `gameplay_fetcher.py` | yt-dlp YouTube search + download; 4-method fallback chain (no-cookie → android → cookie → CLI); trims to 300s |
| `music_fetcher.py` | Same yt-dlp pattern for audio; scores results by title keywords (ost, instrumental, etc.) |
| `voice_generator.py` | ElevenLabs `eleven_multilingual_v2` with per-language speed/stability settings |
| `newvoice.py` | Newer ElevenLabs wrapper using `eleven_v3`; applies ffmpeg `atempo=1.2` speed boost for the "hamid" voice |
| `transcriber.py` | OpenAI Whisper `large-v3` loaded at import time; returns `[(start, end, text)]` groups for subtitle rendering |
| `video_editor.py` | MoviePy pipeline: 9:16 crop → CTA overlay (green screen keyed) → subtitle burn-in → audio mix → ffmpeg write |
| `youtube_uploader.py` | Google OAuth2 upload via YouTube Data API v3; stores token in `token.json` |
| `tiktok_checker.py` | Fetches TikTok captions via yt-dlp to detect duplicate topics |
| `analyzer.py` | One-off script: uploads a finished video to Gemini Files API and gets a relevance/hook/technical score |

### Configuration (`config.py`)

Central path definitions and `VIDEO_LENGTH_SEC`. All modules import paths from here.

### Key settings in `main2.py` (top of file)

```python
LANGUAGE = "en"          # "en", "ru", or "es" — controls niche list, voice, and script prompt
MUSIC_VOLUME = 0.025
SUBTITLES_POSITION = "top"
CLEANUP_FILES = True     # deletes intermediates after render
USE_TIKTOK_DUPLICATE_CHECK = True
```

### Data directories (`data/`)

- `data/gameplay/` — downloaded background videos (deleted after render if `CLEANUP_FILES`)
- `data/music/` — downloaded audio tracks (same)
- `data/audio/` — ElevenLabs narration MP3s (same)
- `data/final/` — finished shorts (kept)

### Voice names

Voices are keyed by string name:
- `"hamid"` — English voice (ElevenLabs ID `yr43K8H5LoTp6S1QFSGg`); speed-boosted 1.2x in `newvoice.py`
- `"Molodoy"` — Russian voice
- `"spanish_guy"` — Spanish voice
- `"Alexander"` — additional voice (in `newvoice.py` only)

### External API dependencies

- **Gemini** (`google-genai`): keys hardcoded in `modules/script_generator.py`; rotated automatically
- **ElevenLabs**: key hardcoded in `modules/voice_generator.py` and `modules/newvoice.py`
- **YouTube Data API v3**: key hardcoded in `main2.py`; OAuth credentials in `client_secret.json` / `token.json`
- **yt-dlp**: must be installed and up-to-date (`pip install -U yt-dlp`)
- **Whisper**: `large-v3` model downloaded on first run via `openai-whisper`
- **ffmpeg + ImageMagick**: must be installed via Homebrew (`brew install ffmpeg imagemagick`)

### CTA overlay

`video_editor.py` hardcodes a path to a local green-screen follow-button video:
```python
cta_path = "/Users/nareksergeyan/YOutuber/Green_Screen_Footage_for_Follow_Button_Boost_Your_Video_Engagement_1080P.mp4"
```
This path is machine-specific. If the file is missing, the CTA overlay is skipped silently.

### Subtitle rendering

Cyrillic text uses Pillow + DejaVu Sans (Homebrew font path); Latin text uses MoviePy `TextClip` with Helvetica. The font path `/opt/homebrew/share/fonts/dejavu/DejaVuSans.ttf` is macOS-specific.
