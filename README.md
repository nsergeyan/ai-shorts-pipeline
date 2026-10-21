# AI Shorts Pipeline

Turns one structured JSON script into a finished 1080x1920 YouTube Short / TikTok, with no manual editing. It finds and vets footage on YouTube, generates narration and music, cuts the clips to the narration, adds word-level subtitles and on-screen graphics, and renders the result with Remotion and FFmpeg. A matching thumbnail comes out alongside the video.

```
script JSON
  -> YouTube search + download (yt-dlp)  -> footage check (Gemini)
  -> narration (ElevenLabs)              -> word timestamps (Whisper)
  -> edit plan: clips, layout, graphics (Gemini)
  -> music: YouTube track vetted by Gemini, ElevenLabs as fallback
  -> render (Remotion) -> follow-button overlay (FFmpeg) -> data/final/*.mp4
  -> thumbnail frame + hook text (Gemini + Remotion)    -> data/thumbnails/*.png
```

## Quick start

**Requirements:** macOS (the pipeline uses `caffeinate` to keep the machine awake), Python 3.11+, Node.js 18+, FFmpeg.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -U "yt-dlp[default]"   # latest yt-dlp + its JS challenge solver; YouTube breaks old builds
cd remotion && npm install && cd ..
cp .env.example .env               # then fill in your keys
```

`.env`:

```
GEMINI_API_KEYS=key1,key2          # comma-separated, rotated on quota errors
ELEVENLABS_API_KEY=...             # account needs music generation enabled
```

Then:

1. Run one of the prompt templates in `prompts/` through a chatbot with web search. `specifixprompt` covers a specific anime, series or movie. `testsport.txt` covers F1, UFC and soccer.
2. Paste the JSON it returns into `MANUAL_DATA` at the top of `main.py`.
3. Run `python main.py`.

The finished video lands in `data/final/` and the thumbnail in `data/thumbnails/`. Whisper `large-v3` (~3 GB) and Chrome Headless Shell download automatically on the first run.

**Optional assets:**
- **Sound effects:** cut whooshes and the camera flash go in `data/sfx/` (filenames are in `modules/video_editor.py`); any missing file is skipped. Tagged effects go in `data/sfx_library/<tag>/`, one folder per tag, copied from the animationer library. Files must be trimmed (no silence before or after the sound).
- **YouTube cookies:** once YouTube shows its "confirm you're not a bot" check, downloads switch to the cookies of a signed-in Chrome profile (`BROWSER` / `PROFILE` in `modules/video_material_fetcher.py`). Use a spare Google account for this, not the one that owns your channel.

## What it does

**Footage**
- Searches YouTube with up to six queries from the script. Before downloading anything, it ranks 15 results by title and views, pushing reaction, review and podcast uploads to the bottom.
- Downloads up to 1080p and falls back through several methods when YouTube blocks a request. It goes over IPv4 with rate limits, tries at most 3 results per query, and stops sending cookie-less requests after the first bot check.
- Gemini scores each download on relevance, hook potential and technical quality, and gives a reason for every accept or reject. It keeps up to 3 approved videos and deletes the rejected ones straight away.

**Edit**
- Whisper sentences are merged into segments of at least 6 s, with at most 5 clips per video. All approved videos and segments go to Gemini in a single call, which picks a `(video, timestamp)` for each segment.
- Clip starts snap to the nearest hard cut, and baked-in black bars are cropped out with `cropdetect`.
- **Per-shot layout:** steady close-ups are cropped to fill the 9:16 screen around the subject (`full`). Everything else shows the whole picture with a blurred backdrop (`framed`). Full screen only lasts until the first hard cut inside the clip, and anything uncertain falls back to framed.
- **Graphic cards:** `stat`, `versus`, `list` and `quote` cards appear on the exact word that triggers them. A card is dropped if its number is not actually spoken (spelled-out numbers like "one point two million" count). No cards appear in the first 3 s, cards are at least 6 s apart, and all of them end before the follow button.

**Look and sound**
- Word-by-word subtitles in the channel's accent colour, 3 words per line, shrunk to fit the width. They move lower during full-screen shots so they don't cover faces.
- Whip-pan transitions on every cut. Every 3rd cut also gets a white flash and a chromatic glitch.
- Whoosh and camera-flash sound effects on cuts.
- Tagged sound effects: `*word:tag*` (for example `*sprayed:sad*`) names a sound from `data/sfx_library/`. Picture tags (`pop`, `hit`, `money`...) play on the word. Reaction tags (`shock`, `sad`, `dumb`...) play after the sentence, in a pause spliced into the narration, and every later timestamp shifts to match. The pause goes into the real gap in the audio (`silencedetect`), not at Whisper's end time, which can run early, and the shot holds until the reaction ends. A plain `*word*` makes no sound. Each effect is levelled against the narration by its loudest moment, and the music dips under it. Unknown tags or going over the limits in `config.py` stop the run before any download or API call.
- Narration uses ElevenLabs `eleven_v4` through `text_to_dialogue`, so emotion tags like `[sarcastic]` work, and is sped up 1.1x. Russian and Spanish use `eleven_multilingual_v2`.
- Music is normalised to -34 LUFS under the voice.
- The green-screen follow button is chroma-keyed over the last 4.6 s. The 8 s clip has its static middle cut out.

**Channels**
- Each file in `channels/<name>.json` sets one channel's accent and panel colour, voice, backdrop style (`blur` / `dark`), whether full-screen crops are allowed, and which card types to use. Select a channel with `"channel"` in `MANUAL_DATA`.

## Project structure

```
main.py                     pipeline entry point, Gemini calls, edit planning
config.py                   paths and API keys from .env
channels/                   per-channel look and voice
prompts/                    script prompt templates
modules/
  video_material_fetcher.py YouTube search, ranking, download fallbacks
  newvoice.py               ElevenLabs narration
  music_generator.py        YouTube music fetch + ElevenLabs music fallback
  transcriber.py            Whisper word timestamps
  video_editor.py           Remotion render, CTA composite, thumbnail render
  clipmaker.py              second entry point: promo clip from your own video
  competitor_analyzer.py    pulls a channel's top/bottom Shorts transcripts
  tiktok_checker.py         lists a TikTok account's captions (duplicate-topic check)
remotion/src/
  compositions/             ShortVideo, Thumbnail, SubtitlePreview (dev preview)
  components/               WordHighlight, ProgressBar, graphics/
```

Settings such as `LANGUAGE`, `MUSIC_LUFS`, `MAX_CLIPS` and the thumbnail-frame options are at the top of `main.py`.

## Other tools

**Promo clip maker** cuts a teaser out of a video you already have. It keeps the video's original audio and uses no narration or music. Set `source_video_path` in `CLIP_MAKER_DATA`, then run:

```bash
python -m modules.clipmaker
```

Gemini proposes three continuous moments that open on a hook and end before the answer (`payoff_at`). The code picks the best one that both has the right length and stops before its payoff, then renders it with the same layout, subtitles and follow button as `main.py`.

**Competitor research** saves the captions of a channel's 15 most viewed and 5 least viewed Shorts, with an analysis prompt on top, to `data/research/<handle>_transcripts.txt`:

```bash
python modules/competitor_analyzer.py <channel_handle>
```

Only compare top vs bottom within one channel, and run one channel at a time to avoid YouTube's rate limit.

**TikTok checker** prints the captions of a TikTok account's recent videos, so you can see which topics are already posted before writing a new prompt. Set `username` at the bottom of the file, then run:

```bash
python modules/tiktok_checker.py
```

## Design decisions

- **Remotion over MoviePy.** MoviePy baked subtitles in as Pillow images, which was slow and looked worse. Remotion renders each frame in a real browser engine, which gives CSS, spring animations and exact compositing.
- **Per-shot layout.** Cropping every shot to 9:16 cuts people off in wide shots. Letterboxing every shot leaves two thirds of the screen as filler. Deciding per shot, with framed as the safe default, gets close-ups that fill the screen without ever breaking a wide shot.
- **Cards only show what the narration says.** The number check runs in code, so a made-up stat can never reach the screen.
- **FFmpeg chromakey for the CTA.** Remotion's `OffthreadVideo` does not reliably handle VP9 alpha in Chrome Headless Shell, while FFmpeg keys the green screen cleanly as a post-process.
- **Effects only on every 3rd cut.** The flash and glitch stay punctuation, not wallpaper.
- **Sounds instead of zoom punches.** A sound on the spoken word draws attention to the narration without moving the picture.
- **Voice before scene finding.** Gemini gets real sentence timings from Whisper, so cuts follow the narration rhythm.
- **Whisper `large-v3`.** Smaller models gave word timestamps too loose for word-level subtitles.
- **`text_to_dialogue` for English.** The plain text-to-speech endpoint ignores bracketed emotion tags.
