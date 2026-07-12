# AI Shorts Pipeline

An automated end-to-end pipeline that produces YouTube Shorts and TikTok videos from a single structured prompt. The system chains together five AI services — script generation, video sourcing, scene detection, voice synthesis, and music — then assembles and edits the final vertical video without any manual intervention.

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

- **Structured prompt system** — Three prompt templates: `manualprompt.txt` (auto-picks a trending anime/cartoon), `specifixprompt` (targets a specific pre-chosen series), and `sportsPrompt` (sports). All enforce a hype-check step, mandatory live-search fact verification, a footage reality check (GREEN/YELLOW/RED), natural YouTube query generation, word count, fact-checking tiers, duplicate avoidance, and the punch marker rule
- **AI video evaluation with reasons** — Gemini 2.5 Flash scores every downloaded clip on relevance, hook potential, and technical quality. Returns a `reason` field explaining each accept/reject decision (e.g. "subject not present — footage shows generic octagon with no visible Charles Oliveira"), making it easy to debug and improve queries
- **Multi-source editing** — The pipeline downloads up to six videos across six query strategies and collects up to three approved clips. All approved videos are uploaded to Gemini in a single call; Gemini watches all of them together and assigns the best (video, timestamp) pair to each narration segment, pulling from whichever source has the strongest matching moment
- **ElevenLabs v3 voice** — English narration uses the `text_to_dialogue` endpoint with full support for bracketed emotion and performance tags (`[excited]`, `[whispers]`, `[sighs]`, etc.); output is speed-boosted via FFmpeg `atempo`
- **Smart music sourcing** — The prompt system generates both a `music_query` (YouTube search for an official OST/instrumental) and a `music_prompt` (ElevenLabs generation spec). The pipeline tries YouTube first; if Gemini approves the track (no lyrics, topic-relevant, voice-compatible) it uses it for free. If the track is rejected or no query is provided, ElevenLabs composes a custom 90-second instrumental instead
- **Remotion rendering** — Video is composed and rendered in React/TypeScript via Remotion (Chrome Headless Shell). Each frame is pixel-accurate, fully programmable, and GPU-accelerated
- **Blurred letterbox layout** — Landscape source footage is displayed at its native aspect ratio (nothing cropped) with a blurred, darkened copy filling the top and bottom bars. Subtitles sit in the top bar, CTA in the bottom bar
- **Word-level subtitles** — Whisper `large-v3` transcribes narration at the word level; each spoken word highlights in yellow with a spring-animated pop, 3 words per line, inside a semi-transparent pill
- **Whip pan transitions** — Every cut slides clips in/out with a directional translateX + motion blur over 4 frames, alternating left/right direction per clip for a dynamic feel
- **Chromatic glitch** — On every 3rd cut a red/blue RGB split overlay with a horizontal tear line fires alongside the flash, adding visual impact without being distracting
- **Flash cut transitions** — Hard cuts between all clips; every 3rd cut fires a 2-frame white flash overlay for extra punctuation
- **SFX audio** — Whoosh sounds play on every regular cut; a camera-flash SFX plays on every 3rd cut. Events are computed from clip timestamps and passed to Remotion as `sfxEvents`, rendered as `<Sequence><Audio>` components
- **Audio-driven punch SFX** — Script authors mark 1–3 high-impact pivot words with `*WORD!*` markers (e.g. `*BUT!*`, `*WAIT!*`). Markers are stripped before TTS so ElevenLabs receives clean text; after Whisper transcription the marked words are matched to their timestamps. At render time a random impact SFX fires at each matched moment via Remotion `<Sequence><Audio>`
- **Controlled pacing** — Narration sentences are merged into groups of at least 7 seconds before scene detection, keeping transitions to ~3–4 per 30-second video. Individual clips have a 3-second floor so no clip is shorter than a single cut
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
| Music | YouTube (yt-dlp audio-only) evaluated by Gemini, with ElevenLabs Generative Music as fallback |
| Audio transcription | OpenAI Whisper `large-v3` |
| Video rendering | Remotion 4.0 (React/TypeScript, Chrome Headless Shell) |
| CTA compositing | FFmpeg `chromakey` + `overlay` filter |
| Subtitle rendering | Remotion `interpolate()` + `spring()` — word-level highlight with pill background |

---

## Pipeline Stages

### 1. Script (Prompt Engineering)
The prompt template enforces a multi-step structure: category selection, ranked candidate table with rarity and viral-curiosity scores, a fact-verification box with confidence tiers, and a quality checklist. The script field must hit exactly 90–100 words. The output is a JSON object consumed directly by the pipeline.

### 2. Video Sourcing & Evaluation
`fetch_gameplay_by_search` queries YouTube with up to six queries, filters out livestreams, Shorts, and videos outside the 1–120 minute window, then downloads using three fallback methods in order. Queries are written as natural fan searches (short, casual phrasing matching real upload titles) across six angles: direct moment, emotional/viral framing, edit pool, episode/arc pool, dub vs sub pool, official clip pool.

Each downloaded video is uploaded to Gemini, which returns `relevance_score`, `hook_score`, `technical_score` (1–10 each), and a `reason` string explaining the decision. The evaluator checks for the character or show by name regardless of their specific state (e.g. normal form, abstracted form, different costume all count). Only a `post` decision passes. Approved videos are collected until three are found or all queries are exhausted; rejected videos are deleted immediately.

### 3. Voice & Transcription
ElevenLabs generates the narration MP3. English uses the `text_to_dialogue` endpoint (ElevenLabs v3) which natively processes bracketed performance tags for natural delivery. Russian and Spanish use `eleven_multilingual_v2`. The narration is transcribed by Whisper with `word_timestamps=True` immediately after, producing per-word `(word, start, end)` tuples used for both subtitle rendering and scene segmentation.

### 4. Multi-Source Scene Detection
Whisper sentence segments are first merged into groups of at least 7 seconds (`MIN_SEGMENT_DURATION`) so a 30-second video produces ~4 clips instead of 8 — keeping transitions to a watchable pace. All approved videos and the merged segments are sent to Gemini in a single call. Gemini watches every video and returns an edit plan: for each segment it picks the best `(video_index, start)` pair. Gemini is required to use every available source video at least once and never use the same video more than 2 segments in a row. Each clip is trimmed to at least `MIN_CLIP_DURATION` (3 seconds) so very short final sentences don't produce sub-second clips.

### 5. Music
The pipeline resolves music in two stages. First it checks for a `music_query` field in the script JSON. If present, yt-dlp searches YouTube and downloads the first result as audio-only MP3. That track is uploaded to Gemini, which scores it on three criteria: no vocals/lyrics, topic relevance (≥7/10), and voice compatibility (≥6/10). If all three pass, the track is used as-is — free. If the track is rejected, the download fails, or no query was provided, ElevenLabs Generative Music composes a custom 90-second instrumental from the `music_prompt` field, which is written per script by the prompt system specifying genre, tempo, instruments, and emotional arc.

### 6. Video Rendering (Remotion)
`merge_audio_video` in `modules/video_editor.py` orchestrates the render:

1. Starts a local HTTP server to serve project files (Remotion requires `http://` URLs)
2. Writes a `props.json` with clip paths, audio paths, word timestamps, and timing data
3. Calls `npx remotion render ShortVideo` — Remotion composes the scene in React, renders frame-by-frame via Chrome Headless Shell, and encodes to H.264

The Remotion composition (`remotion/src/compositions/ShortVideo.tsx`) handles:
- **Blurred background layer** — each clip renders twice: once at `objectFit: cover` + heavy blur for the bars, once at `objectFit: contain` for the full visible video
- **Word-highlight subtitles** — positioned in the top blur bar, spring-animated per word with yellow highlight and pill background
- **Whip pan** — every clip slides in/out with translateX + motion blur over 4 frames, alternating direction per clip
- **Flash cuts** — every 3rd cut fires a 2-frame white flash overlay
- **Chromatic glitch** — red/blue RGB split + horizontal tear line fires on the same cuts as the flash
- **SFX** — whoosh `<Audio>` on every cut, camera-flash SFX on every 3rd cut via `sfxEvents` prop; impact SFX at punch-word timestamps
- **Progress bar** — thin yellow bar along the bottom edge of the video panel
- **Audio mix** — narration + background music + SFX via Remotion `<Audio>` components

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
├── manualprompt.txt           # Structured script prompt template (auto anime/cartoon)
├── specifixprompt             # Structured script prompt template (specific series)
├── sportsPrompt               # Structured script prompt template (sports)
├── modules/
│   ├── video_editor.py        # Remotion render orchestration + FFmpeg CTA composite
│   ├── gameplay_fetcher.py    # YouTube search and download
│   ├── newvoice.py            # ElevenLabs TTS (v3 dialogue + multilingual)
│   ├── music_generator.py     # YouTube audio fetch + ElevenLabs generative music fallback
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
- **Whip pan + flash + glitch stack** — Hard cuts alone feel flat at short durations. Whip pan adds kinetic energy without covering the actual content (4-frame translateX + blur, not a wipe). The chromatic glitch and white flash fire only on every 3rd cut so the effect stays punctuation, not wallpaper. SFX (whoosh/camera-flash) reinforce each cut at the audio layer, making transitions feel intentional even on small screens with no headphones context.
- **Audio punch SFX over video zoom** — A scale-burst zoom on punch words draws attention to the video layer, not the narration. An audio hit at the exact spoken word is more precise and feels more natural — the viewer hears the impact at the moment the word lands, without the video layout shifting or distracting from the subject on screen.
- **Gemini 2.5 Flash over local models** — Ollama (Gemma 27B) was tested for script generation but response quality and speed weren't consistent enough for production. Gemini 2.5 Flash with Google Search grounding produces more accurate, fact-checked scripts.
- **ElevenLabs v3 `text_to_dialogue` for English** — The standard TTS endpoint ignores bracketed emotion tags. `text_to_dialogue` was purpose-built for performance-directed narration and produces noticeably more natural delivery for Shorts content.
- **Whisper before scene detection** — Voice is generated and transcribed first so that Gemini receives sentence-level timing data when choosing scenes. This lets multi-scene clips align with the actual narration rhythm rather than being arbitrarily split.
- **Whisper `large-v3` over smaller models** — Smaller Whisper models produced inaccurate word timestamps, breaking the word-level subtitle sync. The accuracy of `large-v3` justifies the slower load time.

---

## Setup

**Requirements:** Python 3.11+, Node.js 18+, FFmpeg

```bash
# Python dependencies
pip install -r requirements.txt

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

To trigger impact SFX at key moments, add `*WORD!*` markers in the script:

```
"He scored 60 goals for Norway. *BUT!* he was born in England."
```

Markers are stripped before voice generation; after Whisper transcription the words are matched to timestamps and a random SFX fires at each moment during the Remotion render.

---

## Example Output

Input: a 90-word script about a hidden lore mechanic in *Jujutsu Kaisen*

Output: a 1080×1920 vertical video with multi-scene cuts synced to the narration, word-highlight subtitles with spring animation, AI-composed script-matched music, ElevenLabs v3 narration with emotion tags, flash cut transitions, and a chroma-keyed follow-button CTA — ready to upload.
