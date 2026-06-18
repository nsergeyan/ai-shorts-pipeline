# AI Shorts Pipeline

An automated end-to-end pipeline that produces YouTube Shorts and TikTok videos from a single structured prompt. The system chains together five AI services — script generation, video sourcing, scene detection, voice synthesis, and music composition — then assembles and edits the final vertical video without any manual intervention.

---

## How It Works

```
Prompt → Script → YouTube Search → AI Video Evaluation → Voice (ElevenLabs v3)
       → Transcription (Whisper) → Multi-Scene Detection (Gemini)
       → Music (ElevenLabs) → Remotion Render + FFmpeg CTA → Final Short (.mp4)
```

Each stage passes structured data to the next. If the AI rejects a video (bad quality, wrong scene), the pipeline retries automatically with the next YouTube query.

---

## Features

- **Structured prompt system** — A detailed prompt template enforces word count, fact-checking tiers, duplicate avoidance, and topic category rotation for consistent, non-repetitive content
- **AI video evaluation** — Gemini 2.5 Flash scores every downloaded clip on relevance, hook potential, and technical quality before it's used; only high-relevance clips with the subject visually confirmed are accepted
- **Multi-scene editing** — Gemini watches the full video and decides between two modes: *multi* (diverse scenes → one clip per sentence, stitched together) or *continuous* (single action sequence → best start point, plays uncut); clips are zone-distributed across the video to avoid repetition
- **ElevenLabs v3 voice** — English narration uses the `text_to_dialogue` endpoint with full support for bracketed emotion and performance tags (`[excited]`, `[whispers]`, `[sighs]`, etc.); output is speed-boosted via FFmpeg `atempo`
- **Script-specific music** — The music prompt is custom-generated per script (genre, tempo, instruments, emotional arc) rather than a fixed preset, so the background music matches the tone of each individual video
- **Remotion rendering** — Video is composed and rendered in React/TypeScript via Remotion (Chrome Headless Shell). Each frame is pixel-accurate, fully programmable, and GPU-accelerated
- **Blurred letterbox layout** — Landscape source footage is displayed at its native aspect ratio (nothing cropped) with a blurred, darkened copy filling the top and bottom bars. Subtitles sit in the top bar, CTA in the bottom bar
- **Word-level subtitles** — Whisper `large-v3` transcribes narration at the word level; each spoken word highlights in yellow with a spring-animated pop, 3 words per line, inside a semi-transparent pill
- **Flash cut transitions** — Hard cuts everywhere for a clean, fast-paced feel; every 3rd cut fires a 2-frame white flash for punctuation without being distracting
- **Zoom punch** — Optional scale burst at key narration moments (fact reveal, twist) triggered by passing timestamps
- **FFmpeg chroma key CTA** — Green screen call-to-action video is keyed out via FFmpeg `chromakey` filter and composited over the final 8 seconds of the video
- **Multi-method YouTube download** — Three fallback download strategies (Android client, no-cookies, CLI) to handle YouTube's bot detection
- **Multi-language support** — English, Russian, and Spanish voice generation with language-specific ElevenLabs model settings

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
| Video rendering | Remotion 4.0 (React/TypeScript, Chrome Headless Shell) |
| CTA compositing | FFmpeg `chromakey` + `overlay` filter |
| Subtitle rendering | Remotion `interpolate()` + `spring()` — word-level highlight with pill background |

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

### 6. Video Rendering (Remotion)
`merge_audio_video` in `modules/video_editor.py` orchestrates the render:

1. Starts a local HTTP server to serve project files (Remotion requires `http://` URLs)
2. Writes a `props.json` with clip paths, audio paths, word timestamps, and timing data
3. Calls `npx remotion render ShortVideo` — Remotion composes the scene in React, renders frame-by-frame via Chrome Headless Shell, and encodes to H.264

The Remotion composition (`remotion/src/compositions/ShortVideo.tsx`) handles:
- **Blurred background layer** — each clip renders twice: once at `objectFit: cover` + heavy blur for the bars, once at `objectFit: contain` for the full visible video
- **Word-highlight subtitles** — positioned in the top blur bar, spring-animated per word with yellow highlight and pill background
- **Flash cuts** — hard cuts between all clips; every 3rd cut fires a 2-frame white flash overlay
- **Zoom punch** — optional scale burst at caller-specified timestamps
- **Progress bar** — thin yellow bar along the bottom edge of the video panel
- **Audio mix** — narration + background music via Remotion `<Audio>` components

### 7. CTA Compositing (FFmpeg)
After Remotion outputs the base video, FFmpeg overlays the green-screen CTA for the final 8 seconds:
```
ffmpeg -i base.mp4 -i CTA.mp4 \
  -filter_complex "[1:v]trim,setpts,chromakey=color=0x00FF00:similarity=0.35:blend=0.1[ck]; [0:v][ck]overlay=0:500[v]" \
  -map [v] -map 0:a final.mp4
```
The CTA overlaps the last 8 seconds of the narration (not appended after).

---

## Project Structure

```
YOutuber/
├── main.py                    # Main pipeline entrypoint
├── config.py                  # Directory and API configuration
├── manualprompt.txt           # Structured script prompt template
├── modules/
│   ├── video_editor.py        # Remotion render orchestration + FFmpeg CTA composite
│   ├── gameplay_fetcher.py    # YouTube search and download
│   ├── newvoice.py            # ElevenLabs TTS (v3 dialogue + multilingual)
│   ├── music_generator.py     # ElevenLabs generative music
│   ├── transcriber.py         # Whisper word-level transcription
│   ├── youtube_uploader.py    # YouTube Data API v3 upload
│   └── tiktok_checker.py      # TikTok duplicate detection
└── remotion/
    ├── package.json           # Remotion + React dependencies
    ├── remotion.config.ts     # Codec and quality settings
    └── src/
        ├── index.ts           # Entry point (registerRoot)
        ├── Root.tsx           # Composition registration + calculateMetadata
        ├── compositions/
        │   └── ShortVideo.tsx # Main composition (clips, audio, subtitles, transitions)
        └── components/
            ├── WordHighlight.tsx  # Word-level subtitle with spring animation
            ├── ProgressBar.tsx    # Playback progress bar
            └── HookCard.tsx       # Optional hook text overlay (unused by default)
```

---

## Design Decisions

- **Remotion over MoviePy** — MoviePy renders subtitles by baking Pillow images into video frames, which is slow, inflexible, and produces lower quality output. Remotion renders the entire composition in a real browser engine, giving access to CSS animations, spring physics, and pixel-accurate compositing at full resolution.
- **Blurred letterbox over cropped 9:16** — Cropping landscape footage to fill 9:16 often cuts off characters or key visuals. The blurred letterbox approach displays the full video at its native aspect ratio while using the empty bars for subtitles and CTA, so nothing important is cropped.
- **FFmpeg chromakey for CTA over Remotion transparency** — Remotion's `OffthreadVideo` does not reliably support alpha channel from VP9 WebM in Chrome Headless Shell. FFmpeg's native `chromakey` filter produces cleaner keying and compositing as a post-process step.
- **Hard cuts + flash mix** — Continuous visual transitions (dissolves, slides) feel repetitive and slow when every clip change uses the same effect. Hard cuts are invisible when the narration carries the edit; a 2-frame white flash on every 3rd cut adds punctuation without becoming a pattern.
- **Gemini 2.5 Flash over local models** — Ollama (Gemma 27B) was tested for script generation but response quality and speed weren't consistent enough for production. Gemini 2.5 Flash with Google Search grounding produces more accurate, fact-checked scripts.
- **ElevenLabs v3 `text_to_dialogue` for English** — The standard TTS endpoint ignores bracketed emotion tags. `text_to_dialogue` was purpose-built for performance-directed narration and produces noticeably more natural delivery for Shorts content.
- **Whisper before scene detection** — Voice is generated and transcribed first so that Gemini receives sentence-level timing data when choosing scenes. This lets multi-scene clips align with the actual narration rhythm rather than being arbitrarily split.
- **Whisper `large-v3` over smaller models** — Smaller Whisper models produced inaccurate word timestamps, breaking the word-level subtitle sync. The accuracy of `large-v3` justifies the slower load time.

---

## Setup

**Requirements:** Python 3.11+, Node.js 18+, FFmpeg

```bash
# Python dependencies
pip install yt-dlp openai-whisper elevenlabs google-genai ffmpeg-python

# Remotion
cd remotion && npm install
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

To trigger a zoom punch at specific moments, pass timestamps to `merge_audio_video`:

```python
merge_audio_video(..., punch_times=[12.5, 28.0])
```

---

## Example Output

Input: a 90-word script about a hidden lore mechanic in *Jujutsu Kaisen*

Output: a 1080×1920 vertical video with multi-scene cuts synced to the narration, word-highlight subtitles with spring animation, AI-composed script-matched music, ElevenLabs v3 narration with emotion tags, flash cut transitions, and a chroma-keyed follow-button CTA — ready to upload.
