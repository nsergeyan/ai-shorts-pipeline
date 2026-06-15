# AI Shorts Pipeline

An automated end-to-end pipeline that produces YouTube Shorts and TikTok videos from a single structured prompt. The system chains together five AI services — script generation, video sourcing, scene detection, voice synthesis, and music composition — then assembles and edits the final vertical video without any manual intervention.

---

## How It Works

```
Prompt → Script → YouTube Search → AI Video Evaluation → Scene Detection
       → Voice (ElevenLabs) → Transcription (Whisper) → Music (ElevenLabs)
       → Video Editor (MoviePy + FFmpeg) → Final Short (.mp4)
```

Each stage passes structured data to the next. If the AI rejects a video (bad quality, wrong scene), the pipeline retries automatically with the next YouTube query.

---

## Features

- **Structured prompt system** — A detailed prompt template enforces word count, fact-checking tiers, duplicate avoidance, and topic category rotation for consistent, non-repetitive content
- **AI video evaluation** — Gemini 2.5 Flash scores every downloaded clip on relevance, hook potential, and technical quality before it's used
- **AI scene detection** — Gemini analyzes the full video and returns the exact timestamp of the most relevant moment for the script
- **Word-level subtitles** — Whisper `large-v3` transcribes the narration at the word level; each spoken word is highlighted in yellow in real time as the narrator speaks it
- **AI music evaluation** — Generated music is scored against the script for mood match, energy, and voice compatibility before being mixed in
- **Chroma key compositing** — Green screen call-to-action overlays are keyed out with a NumPy-based green-dominance algorithm and composited over the final frame
- **Multi-method YouTube download** — Three fallback download strategies (Android client, no-cookies, CLI) to handle YouTube's bot detection
- **Multi-language support** — English, Russian, and Spanish voice and subtitle generation with language-specific ElevenLabs model settings

---

## Tech Stack

| Layer | Tool |
|---|---|
| Script generation | Structured prompt → Google Gemini / Claude |
| Video sourcing | `yt-dlp` with Android client + fallbacks |
| Video evaluation & scene detection | Google Gemini 2.5 Flash (multimodal) |
| Voice synthesis | ElevenLabs `eleven_multilingual_v2` |
| Music composition | ElevenLabs Generative Music API |
| Audio transcription | OpenAI Whisper `large-v3` |
| Video editing | MoviePy + FFmpeg |
| Subtitle rendering | Pillow (PIL) with custom word-highlight renderer |
| Chroma keying | NumPy per-frame green-dominance mask |

---

## Pipeline Stages

### 1. Script (Prompt Engineering)
The prompt template enforces a multi-step structure: category selection, ranked candidate table with rarity and viral-curiosity scores, a fact-verification box with confidence tiers, and a quality checklist. The script field must hit exactly 90–100 words. The output is a JSON object consumed directly by the pipeline.

### 2. Video Sourcing & Evaluation
`fetch_gameplay_by_search` queries YouTube with up to three ranked queries, filters out livestreams, Shorts, and videos outside the 1–120 minute window, then downloads using three fallback methods in order. The downloaded video is uploaded to Gemini, which returns `relevance_score`, `hook_score`, and `technical_score` (1–10 each). A `reject` decision triggers a retry with the next query.

### 3. Scene Detection
The accepted video is re-uploaded to Gemini with the script and a `twelvelabs_query` describing the target visual moment. Gemini returns a `{ start, end }` timestamp. FFmpeg trims the video starting at that timestamp.

### 4. Voice & Music Generation
ElevenLabs generates the narration MP3 with per-language stability and style settings. In parallel, ElevenLabs Generative Music composes 90 seconds of instrumental audio from a mood/genre prompt derived from the script's emotional tone.

### 5. Transcription
Whisper `large-v3` transcribes the narration with `word_timestamps=True`, returning per-word `(word, start, end)` tuples used for the subtitle renderer.

### 6. Video Assembly
`merge_audio_video` in `modules/video_editor.py`:
- Converts any source resolution to 1080×1920 (9:16) with letterboxing
- Randomly selects a segment from long source videos
- Composites word-highlight subtitle frames as `ImageClip` overlays timed to Whisper output
- Composites a chroma-keyed CTA clip over the final 8 seconds
- Mixes voice and background music with configurable volume ratio
- Exports via `libx264` / `aac` at 30 fps

---

## Project Structure

```
YOutuber/
├── mainmanualnewvoice.py   # Main pipeline entrypoint
├── manualprompt.txt        # Structured script prompt template
├── config.py               # Directory and API configuration
└── modules/
    ├── gameplay_fetcher.py  # YouTube search and download
    ├── video_editor.py      # MoviePy assembly, subtitles, chroma key
    ├── voice_generator.py   # ElevenLabs TTS
    ├── music_generator.py   # ElevenLabs generative music
    ├── transcriber.py       # Whisper word-level transcription
    ├── youtube_uploader.py  # YouTube Data API v3 upload
    └── tiktok_checker.py    # TikTok duplicate detection
```

---

## Setup

**Requirements:** Python 3.11+, FFmpeg, ImageMagick

```bash
pip install yt-dlp moviepy pillow numpy openai-whisper elevenlabs google-genai ffmpeg-python
```

Set your API keys in `config.py` (or export as environment variables):

```
ELEVENLABS_API_KEY
GEMINI_API_KEY
```

---

## Usage

Paste a completed JSON script object into `MANUAL_DATA` in `mainmanualnewvoice.py`, then run:

```bash
python mainmanualnewvoice.py
```

The pipeline runs fully automatically and saves the final `.mp4` to `data/final/`.

---

## Example Output

Input: a 90-word script about a hidden lore mechanic in *Jujutsu Kaisen*

Output: a 1080×1920 vertical video with synchronized word-highlight subtitles, AI-composed suspenseful orchestral music, ElevenLabs narration, and a chroma-keyed follow-button CTA — ready to upload.
