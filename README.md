# AI Shorts Pipeline

An automated end-to-end pipeline that produces YouTube Shorts and TikTok videos from a single structured prompt. The system chains together five AI services — script generation, video sourcing, scene detection, voice synthesis, and music composition — then assembles and edits the final vertical video without any manual intervention.

---

## How It Works

```
Prompt → Script → YouTube Search → AI Video Evaluation → Voice (ElevenLabs v3)
       → Transcription (Whisper) → Multi-Scene Detection (Gemini)
       → Music (ElevenLabs) → Video Editor (MoviePy + FFmpeg) → Final Short (.mp4)
```

Each stage passes structured data to the next. If the AI rejects a video (bad quality, wrong scene), the pipeline retries automatically with the next YouTube query.

---

## Features

- **Structured prompt system** — A detailed prompt template enforces word count, fact-checking tiers, duplicate avoidance, and topic category rotation for consistent, non-repetitive content
- **AI video evaluation** — Gemini 2.5 Flash scores every downloaded clip on relevance, hook potential, and technical quality before it's used; only high-relevance clips with the subject visually confirmed are accepted
- **Multi-scene editing** — Gemini watches the full video and decides between two modes: *multi* (diverse scenes → one clip per sentence, stitched together) or *continuous* (single action sequence → best start point, plays uncut); clips are zone-distributed across the video to avoid repetition
- **ElevenLabs v3 voice** — English narration uses the `text_to_dialogue` endpoint with full support for bracketed emotion and performance tags (`[excited]`, `[whispers]`, `[sighs]`, etc.); output is speed-boosted via FFmpeg `atempo`
- **Script-specific music** — The music prompt is custom-generated per script (genre, tempo, instruments, emotional arc) rather than a fixed preset, so the background music matches the tone of each individual video
- **Word-level subtitles** — Whisper `large-v3` transcribes narration at the word level; each spoken word highlights in yellow in real time, 3 words per line
- **Chroma key compositing** — Green screen call-to-action overlays are keyed out with a NumPy-based green-dominance algorithm and composited over the final frame
- **Multi-method YouTube download** — Three fallback download strategies (Android client, no-cookies, CLI) to handle YouTube's bot detection
- **Multi-language support** — English, Russian, and Spanish voice generation with language-specific ElevenLabs model settings; word-level subtitles for English and Russian

---

## Tech Stack

| Layer | Tool |
|---|---|
| Script generation | Structured prompt → Google Gemini / Claude |
| Video sourcing | `yt-dlp` with Android client + fallbacks |
| Video evaluation & scene detection | Google Gemini 2.5 Flash (multimodal) |
| Voice synthesis | ElevenLabs `eleven_v3` (`text_to_dialogue`) for English; `eleven_multilingual_v2` for RU/ES |
| Music composition | ElevenLabs Generative Music API with script-derived custom prompt |
| Audio transcription | OpenAI Whisper `large-v3` |
| Video editing | MoviePy + FFmpeg |
| Subtitle rendering | Pillow (PIL) with custom word-highlight renderer |
| Chroma keying | NumPy per-frame green-dominance mask |

---

## Pipeline Stages

### 1. Script (Prompt Engineering)
The prompt template enforces a multi-step structure: category selection, ranked candidate table with rarity and viral-curiosity scores, a fact-verification box with confidence tiers, and a quality checklist. The script field must hit exactly 90–100 words. The output is a JSON object consumed directly by the pipeline.

### 2. Video Sourcing & Evaluation
`fetch_gameplay_by_search` queries YouTube with up to three ranked queries, filters out livestreams, Shorts, and videos outside the 1–120 minute window, then downloads using three fallback methods in order. The downloaded video is uploaded to Gemini, which returns `relevance_score`, `hook_score`, and `technical_score` (1–10 each). Only a `post` decision with `relevance_score >= 7` and confirmed subject presence passes. Anything else triggers a retry with the next query.

### 3. Voice & Transcription
ElevenLabs generates the narration MP3. English uses the `text_to_dialogue` endpoint (ElevenLabs v3) which natively processes bracketed performance tags for natural delivery. Russian and Spanish use `eleven_multilingual_v2`. The narration is transcribed by Whisper with `word_timestamps=True` immediately after, producing per-word `(word, start, end)` tuples used for both subtitle rendering and scene segmentation.

### 4. Multi-Scene Detection
The accepted video and Whisper-segmented sentences are sent to Gemini. Gemini watches the full video and decides:
- **Multi mode** — video contains visually diverse scenes → returns one timestamp window per sentence segment → each clip is trimmed and zone-clamped to avoid repetition
- **Continuous mode** — video is a single action sequence → returns one best start point → video plays uncut for the full narration duration

### 5. Music Generation
ElevenLabs Generative Music composes 90 seconds of instrumental audio. The music prompt is custom-written per script by the prompt system — specifying genre, tempo, instruments, and emotional arc — so the music actually matches the content of the video.

### 6. Video Assembly
`merge_audio_video` in `modules/video_editor.py`:
- Converts any source resolution to 1080×1920 (9:16) with letterboxing
- Concatenates multiple scene clips or uses a single trimmed clip depending on Gemini's mode decision
- Composites word-highlight subtitle frames as `ImageClip` overlays timed to Whisper output
- Composites a chroma-keyed CTA clip over the final 8 seconds
- Mixes voice and background music with configurable volume ratio
- Exports via `libx264` / `aac` at 30 fps

---

## Project Structure

```
YOutuber/
├── main.py                 # Main pipeline entrypoint
├── manualprompt.txt        # Structured script prompt template
├── config.py               # Directory and API configuration
└── modules/
    ├── gameplay_fetcher.py  # YouTube search and download
    ├── video_editor.py      # MoviePy assembly, subtitles, chroma key
    ├── newvoice.py          # ElevenLabs TTS (v3 dialogue + multilingual)
    ├── music_generator.py   # ElevenLabs generative music
    ├── transcriber.py       # Whisper word-level transcription
    ├── youtube_uploader.py  # YouTube Data API v3 upload
    └── tiktok_checker.py    # TikTok duplicate detection
```

---

## Design Decisions

- **Gemini 2.5 Flash over local models** — Ollama (Gemma 27B) was tested for script generation but response quality and speed weren't consistent enough for production. Gemini 2.5 Flash with Google Search grounding produces more accurate, fact-checked scripts.
- **ElevenLabs v3 `text_to_dialogue` for English** — The standard TTS endpoint ignores bracketed emotion tags. `text_to_dialogue` was purpose-built for performance-directed narration and produces noticeably more natural delivery for Shorts content.
- **Whisper before scene detection** — Voice is generated and transcribed first so that Gemini receives sentence-level timing data when choosing scenes. This lets multi-scene clips align with the actual narration rhythm rather than being arbitrarily split.
- **Script-specific music prompts** — Fixed mood presets (4 generic strings) produced music that didn't match individual scripts. The prompt system now generates a custom music description per script with specific genre, BPM, instruments, and emotional arc.
- **yt-dlp with 3 fallback methods** — YouTube actively blocks bots. A single download strategy failed too often; the fallback chain (Android client → no-cookies → CLI) brings the success rate high enough for production use.
- **Whisper `large-v3` over smaller models** — Smaller Whisper models produced inaccurate word timestamps, breaking the word-level subtitle sync. The accuracy of `large-v3` justifies the slower load time.

---

## Setup

**Requirements:** Python 3.11+, FFmpeg, ImageMagick

```bash
pip install yt-dlp moviepy pillow numpy openai-whisper elevenlabs google-genai ffmpeg-python
```

Set your API keys in `.env`:

```
ELEVENLABS_API_KEY=
GEMINI_API_KEYS=key1,key2
```

---

## Usage

Paste a completed JSON script object into `MANUAL_DATA` in `main.py`, then run:

```bash
python main.py
```

The pipeline runs fully automatically and saves the final `.mp4` to `data/final/`.

---

## Example Output

Input: a 90-word script about a hidden lore mechanic in *Jujutsu Kaisen*

Output: a 1080×1920 vertical video with multi-scene cuts synced to the narration, word-highlight subtitles, AI-composed script-matched music, ElevenLabs v3 narration with emotion tags, and a chroma-keyed follow-button CTA — ready to upload.
