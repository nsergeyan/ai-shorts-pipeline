# AI Shorts Pipeline

An automated end-to-end pipeline that produces YouTube Shorts and TikTok videos from a single structured prompt. The system chains together five AI services — script generation, video sourcing, scene detection, voice synthesis, and music — then assembles and edits the final vertical video without any manual intervention.

---

## How It Works

```
Prompt → Script → YouTube Search → AI Video Evaluation → Voice (ElevenLabs v3)
       → Transcription (Whisper) → Multi-Scene Detection (Gemini)
       → Music (ElevenLabs) → Remotion Render + FFmpeg CTA → Final Short (.mp4)
                                          ↘ Thumbnail Pick (Gemini) → Thumbnail (.png)
```

Each stage passes structured data to the next. If the AI rejects a video (bad quality, wrong scene), the pipeline retries automatically with the next YouTube query.

---

## Features

- **Structured prompt system** — Three prompt templates: `prompts/manualprompt.txt` (auto-picks a trending anime/cartoon), `specifixprompt` (targets a specific pre-chosen series), and `sportsPrompt` (sports). All enforce a hype-check step, mandatory live-search fact verification, a footage reality check (GREEN/YELLOW/RED), natural YouTube query generation, word count, fact-checking tiers, duplicate avoidance, and the punch marker rule
- **AI video evaluation with reasons** — Gemini 2.5 Flash scores every downloaded clip on relevance, hook potential, and technical quality. Returns a `reason` field explaining each accept/reject decision (e.g. "subject not present — footage shows generic octagon with no visible Charles Oliveira"), making it easy to debug and improve queries
- **Multi-source editing** — The pipeline downloads up to six videos across six query strategies and collects up to three approved clips. All approved videos are uploaded to Gemini in a single call; Gemini watches all of them together and assigns the best (video, timestamp) pair to each narration segment, pulling from whichever source has the strongest matching moment
- **ElevenLabs v3 voice** — English narration uses the `text_to_dialogue` endpoint with full support for bracketed emotion and performance tags (`[excited]`, `[whispers]`, `[sighs]`, etc.); output is speed-boosted via FFmpeg `atempo`
- **Smart music sourcing** — The prompt system generates both a `music_query` (YouTube search for an official OST/instrumental) and a `music_prompt` (ElevenLabs generation spec). The pipeline tries YouTube first; if Gemini approves the track (no lyrics, topic-relevant, voice-compatible) it uses it for free. If the track is rejected or no query is provided, ElevenLabs composes a custom 90-second instrumental instead
- **Remotion rendering** — Video is composed and rendered in React/TypeScript via Remotion (Chrome Headless Shell). Each frame is pixel-accurate, fully programmable, and GPU-accelerated
- **Smart per-shot layout** - Gemini tags every shot it picks as `full` or `framed`. Steady close-ups of one subject are cropped to fill the whole 9:16 screen around the subject (`focus_x`); wide shots stay framed (full picture in the middle, blurred copy above and below) so nobody gets cut off. ffmpeg checks each clip for hard cuts and keeps full screen only until the first one, then switches to framed. Anything unclear falls back to framed, so the worst case is the classic look. Subtitles drop lower during full-screen shots so they never cover faces
- **Narration graphic cards** - Remotion draws cards in the lower part of the screen that show what the voice is saying: `stat` (a number counting up), `versus` (two values with bars), `list` (items popping in) and `quote` (revealed word by word). Gemini places them on exact words across the narration; the code drops any card whose number isn't actually spoken, keeps the first 3 seconds clean, spaces cards at least 6 seconds apart and ends them before the follow button
- **Channel configs** - `channels/<name>.json` sets each channel's accent colour, card panel colour, voice, background style and which features are on. Pick one with `"channel": "sports"` in `MANUAL_DATA`; the same engine gives each channel its own look
- **Clean clip starts** - Clip starts snap to the nearest hard cut so a clip never opens on the tail of the previous shot, and baked-in black bars (letterbox/pillarbox) are detected with `cropdetect` and cropped out
- **Word-level subtitles** — Whisper `large-v3` transcribes narration at the word level; each spoken word highlights in yellow with a spring-animated pop, 3 words per line, with a bold black-stroke text shadow
- **Whip pan transitions** — Every cut slides clips in/out with a directional translateX + motion blur over 4 frames, alternating left/right direction per clip for a dynamic feel
- **Chromatic glitch** — On every 3rd cut a red/blue RGB split overlay with a horizontal tear line fires alongside the flash, adding visual impact without being distracting
- **Flash cut transitions** — Hard cuts between all clips; every 3rd cut fires a 2-frame white flash overlay for extra punctuation
- **SFX audio** — Whoosh sounds play on every regular cut; a camera-flash SFX plays on every 3rd cut. Events are computed from clip timestamps and passed to Remotion as `sfxEvents`, rendered as `<Sequence><Audio>` components
- **Audio-driven punch SFX** — Script authors mark 1–3 high-impact pivot words with `*WORD!*` markers (e.g. `*BUT!*`, `*WAIT!*`). Markers are stripped before TTS so ElevenLabs receives clean text; after Whisper transcription the marked words are matched to their timestamps. At render time a random impact SFX fires at each matched moment via Remotion `<Sequence><Audio>`
- **Controlled pacing** - Narration sentences are merged into groups of at least 6 seconds (`MIN_SEGMENT_DURATION`) before scene detection, with a hard cap of 5 clips per video (`MAX_CLIPS`), so a 30-second video gets about 4 to 5 cuts. Individual clips have a 3-second floor so no clip is shorter than a single cut
- **FFmpeg chroma key CTA** - Green screen call-to-action video is keyed out via FFmpeg `chromakey` filter and composited over the final 4.6 seconds of the video (the 8-second clip with its static middle removed, so the full animation still plays)
- **Ranked 1080p YouTube download** - 15 search results are scored by title (query match, commentary/reaction words penalised, "official"/"4K" boosted) and views before anything is downloaded. Downloads try HD streams up to 1080p first, then three fallbacks (Android client, no-cookies, CLI)
- **Automatic thumbnail generation** — Alongside the video, the pipeline produces a matching 1080×1920 thumbnail image. Gemini reuses the footage it already uploaded for scene detection to pick the single most scroll-stopping frame (with crop-safety and intro/outro/watermark bans), then writes a short comic-style hook split into 1–3 lines, each colored white, yellow, or red for emphasis. FFmpeg extracts the chosen frame and Remotion renders the final PNG with a bold display font. This is a deterministic composite (real frame + styled text), not a generative image model — so it costs nothing extra and never hallucinates the subject. Output lands in `data/thumbnails/`, named to match the final video
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
`fetch_video_material_by_search` queries YouTube with up to six queries and filters out livestreams, Shorts, and videos outside the 1 to 120 minute window. The remaining results are ranked by title and views (reaction, review and podcast uploads sink to the bottom) and downloaded best-first: HD streams up to 1080p, then three fallback methods. Each download is trimmed to 5 minutes and gets a `.meta.json` sidecar with the original length, so the "skip the outro" rule is only applied to videos that really end on one. Queries are written as natural fan searches (short, casual phrasing matching real upload titles) across six angles: direct moment, emotional/viral framing, edit pool, episode/arc pool, dub vs sub pool, official clip pool.

Each downloaded video is uploaded to Gemini, which returns `relevance_score`, `hook_score`, `technical_score` (1–10 each), and a `reason` string explaining the decision. The evaluator checks for the character or show by name regardless of their specific state (e.g. normal form, abstracted form, different costume all count). Only a `post` decision passes. Approved videos are collected until three are found or all queries are exhausted; rejected videos are deleted immediately.

### 3. Voice & Transcription
ElevenLabs generates the narration MP3. English uses the `text_to_dialogue` endpoint (ElevenLabs v3) which natively processes bracketed performance tags for natural delivery. Russian and Spanish use `eleven_multilingual_v2`. The narration is transcribed by Whisper with `word_timestamps=True` immediately after, producing per-word `(word, start, end)` tuples used for both subtitle rendering and scene segmentation.

### 4. Multi-Source Scene Detection
Whisper sentence segments are first merged into groups of at least 6 seconds (`MIN_SEGMENT_DURATION`), and if there are still more than 5 (`MAX_CLIPS`) the shortest neighbours are merged until 5 remain. A 30-second video gets about 4 to 5 clips instead of one per sentence, keeping transitions at a watchable pace. All approved videos and the merged segments are sent to Gemini in a single call. Gemini watches every video and returns an edit plan: for each segment it picks the best `(video_index, start)` pair. Gemini is required to use every available source video at least once and never use the same video more than 2 segments in a row. Each clip is trimmed to at least `MIN_CLIP_DURATION` (3 seconds) so very short final sentences don't produce sub-second clips.

In the same call Gemini also returns:
- a `layout` (`full` or `framed`) and `focus_x` per scene. Python validates both, and `_clip_layout()` limits full screen to the first hard cut inside the clip
- a `graphics` list of cards anchored to words. `_validate_graphic()` rejects invented numbers (spelled-out numbers like "fifty-two" or "one point two million" are understood), `_time_graphic()` starts each card on its anchor word, and `_fit_graphic_windows()` enforces the spacing rules

Before trimming, `_snap_to_shot_cut()` moves each start onto a nearby hard cut, and `_detect_crop()` removes baked-in black bars.

### 5. Music
The pipeline resolves music in two stages. First it checks for a `music_query` field in the script JSON. If present, yt-dlp searches YouTube and downloads the first result as audio-only MP3. That track is uploaded to Gemini, which scores it on three criteria: no vocals/lyrics, topic relevance (≥7/10), and voice compatibility (≥6/10). If all three pass, the track is used as-is — free. If the track is rejected, the download fails, or no query was provided, ElevenLabs Generative Music composes a custom 90-second instrumental from the `music_prompt` field, which is written per script by the prompt system specifying genre, tempo, instruments, and emotional arc.

### 6. Video Rendering (Remotion)
`merge_audio_video` in `modules/video_editor.py` orchestrates the render:

1. Starts a local HTTP server to serve project files (Remotion requires `http://` URLs)
2. Writes a `props.json` with clip paths, audio paths, word timestamps, and timing data
3. Calls `npx remotion render ShortVideo` — Remotion composes the scene in React, renders frame-by-frame via Chrome Headless Shell, and encodes to H.264

The Remotion composition (`remotion/src/compositions/ShortVideo.tsx`) handles:
- **Two layout modes per clip** - `full` renders the clip once at `objectFit: cover` positioned on `focusX` until `fullUntil`; `framed` renders it twice (blurred cover copy for the bars, or a dark backdrop if the channel sets `frame_background: "dark"`, plus `objectFit: contain` for the full picture)
- **Graphic cards** - `components/graphics/` (`StatGraphic`, `VersusGraphic`, `ListGraphic`, `QuoteGraphic`) placed on the timeline by `GraphicLayer`, all in the channel's accent colour
- **Word-highlight subtitles** - in the top bar for framed shots, lower (58%) during full-screen shots; spring-animated per word with the channel's accent colour and a bold black-stroke shadow
- **Whip pan** — every clip slides in/out with translateX + motion blur over 4 frames, alternating direction per clip
- **Flash cuts** — every 3rd cut fires a 2-frame white flash overlay
- **Chromatic glitch** — red/blue RGB split + horizontal tear line fires on the same cuts as the flash
- **SFX** — whoosh `<Audio>` on every cut, camera-flash SFX on every 3rd cut via `sfxEvents` prop; impact SFX at punch-word timestamps
- **Progress bar** - thin bar in the channel's accent colour along the bottom edge of the video panel
- **Audio mix** — narration + background music + SFX via Remotion `<Audio>` components

### 7. CTA Compositing (FFmpeg)
After Remotion outputs the base video, FFmpeg overlays the green-screen CTA for the final 4.6 seconds. The 8-second CTA clip is shortened by keeping only its intro + click (0 to 3.2s) and its exit (6.6 to 8.0s), see `CTA_KEEP` in `video_editor.py`:
```
ffmpeg -i base.mp4 -i CTA.mp4 \
  -filter_complex "[1:v]split[ca][cb]; [ca]trim=0:3.2[c1]; [cb]trim=6.6:8.0[c2]; [c1][c2]concat,setpts,chromakey=color=0x00FF00:similarity=0.35:blend=0.1[ck]; [0:v][ck]overlay=0:500[v]" \
  -map [v] -map 0:a final.mp4
```
The CTA overlaps the end of the narration (not appended after). Graphic cards are cut to end before it starts, because both use the lower part of the screen.

### 8. Thumbnail Generation
After the video is saved, the pipeline builds a matching thumbnail image. `find_thumbnail_with_gemini` reuses the same footage files already uploaded to Gemini during scene detection (no extra upload cost) and asks for one JSON object: the single best `(video_index, start)` frame and a `hook_lines` array of 1–3 short colored lines. The prompt enforces crop-safety (the frame is cropped to 9:16, so the subject must be centered and large) and bans watermarks, baked-in text, reactors, and intro/outro frames. FFmpeg extracts that exact frame as a JPG, then `render_thumbnail` in `modules/video_editor.py` renders it through the Remotion `Thumbnail` composition (`npx remotion still`) — the real frame as a background with the styled hook text on top — and writes a `1080×1920` PNG to `data/thumbnails/`. It is a deterministic image composite, not a generative image model, so it is free and always shows the actual footage.

---

## Project Structure

```
YOutuber/
├── main.py                    # Main pipeline entrypoint
├── config.py                  # Directory and API configuration
├── channels/
│   ├── sports.json            # Per-channel look: accent colour, voice, layout + card settings
│   └── anime.json
├── manualprompt.txt           # Structured script prompt template (auto anime/cartoon)
├── specifixprompt             # Structured script prompt template (specific series)
├── sportsPrompt               # Structured script prompt template (sports)
├── modules/
│   ├── clipmaker.py               # Promo clip entrypoint (cuts a teaser out of a video you already have)
│   ├── video_editor.py            # Remotion render orchestration + FFmpeg CTA composite
│   ├── video_material_fetcher.py  # YouTube search and download
│   ├── newvoice.py                # ElevenLabs TTS (v3 dialogue + multilingual)
│   ├── music_generator.py         # YouTube audio fetch + ElevenLabs generative music fallback
│   ├── transcriber.py             # Whisper word-level transcription
│   └── tiktok_checker.py          # TikTok duplicate detection
└── remotion/
    ├── package.json           # Remotion + React dependencies
    ├── remotion.config.ts     # Codec and quality settings
    └── src/
        ├── index.ts           # Entry point (registerRoot)
        ├── Root.tsx           # Composition registration + calculateMetadata
        ├── compositions/
        │   ├── ShortVideo.tsx # Main composition (clips, audio, subtitles, transitions)
        │   └── Thumbnail.tsx  # Static thumbnail still (footage frame + colored hook text)
        └── components/
            ├── graphics/          # Narration cards: Stat, Versus, List, Quote + GraphicLayer + Panel
            ├── WordHighlight.tsx  # Word-level subtitle with spring animation
            ├── ProgressBar.tsx    # Playback progress bar
            ├── CTAOverlay.tsx     # Remotion CTA component (unused — CTA composited via FFmpeg instead)
            └── HookCard.tsx       # Optional hook text overlay (unused by default)
```

---

## Design Decisions

- **Remotion over MoviePy** — MoviePy renders subtitles by baking Pillow images into video frames, which is slow, inflexible, and produces lower quality output. Remotion renders the entire composition in a real browser engine, giving access to CSS animations, spring physics, and pixel-accurate compositing at full resolution.
- **Per-shot layout over always-cropped or always-letterboxed** - Cropping every landscape shot to 9:16 keeps only about a third of the width and cuts people off in wide shots, while a letterbox everywhere leaves two-thirds of the screen as blurred filler that reads as a reupload. Deciding per shot gets the best of both: close-ups fill the screen, wide shots stay whole. Framed is the default whenever anything is uncertain, so the feature can only improve a video, never break it.
- **Graphic cards from the narration only** - Cards may only show values the narration actually says, checked in code, so they make the video look produced without ever putting a made-up stat on screen.
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

Paste a completed JSON script object into `MANUAL_DATA` in `main.py`, add `"channel": "sports"` (or `"anime"`) to pick the channel look, then run:

```bash
python main.py
```

The pipeline runs fully automatically and saves the final `.mp4` to `data/final/`.

To trigger impact SFX at key moments, add `*WORD!*` markers in the script:

```
"He scored 60 goals for Norway. *BUT!* he was born in England."
```

Markers are stripped before voice generation; after Whisper transcription the words are matched to timestamps and a random SFX fires at each moment during the Remotion render.

### Promo Clip Maker

`modules/clipmaker.py` is a second entrypoint for a different job: cutting a short promo clip out of a video you already have, instead of sourcing footage from YouTube. Set `source_video_path` in `CLIP_MAKER_DATA`, then run:

```bash
python -m modules.clipmaker
```

Gemini watches the full video and returns three ranked teaser candidates: continuous moments that open on a cold hook and end before the video gives the answer (`payoff_at`). The code takes the highest-ranked one that both stops before its payoff and matches the target length (`clip_duration`, default 30s), and if it has to stretch the clip it slides the window back so it never swallows the answer. FFmpeg trims to that moment, keeping the video's own original audio, no script, no AI narration, no music. That audio is transcribed by Whisper and the clip is rendered through the same Remotion pipeline as `main.py`, so it gets the same blurred/contained 9:16 layout, the same word-highlighted subtitles, and the same follow-button CTA. Output lands in `data/final/` as `Promo_<filename>_XX.mp4`; the original source video is never deleted.

---

## Example Output

Input: a 90-word script about a hidden lore mechanic in *Jujutsu Kaisen*

Output: a 1080×1920 vertical video with multi-scene cuts synced to the narration, word-highlight subtitles with spring animation, AI-composed script-matched music, ElevenLabs v3 narration with emotion tags, flash cut transitions, and a chroma-keyed follow-button CTA — ready to upload.
