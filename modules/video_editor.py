import http.server
import json
import math
import os
import random
import socket
import subprocess
import threading
import urllib.parse
import zlib
from typing import List, Optional, Union

import config
from config import DATA_DIR, CTA_PATH, FINAL_DIR, THUMBNAIL_DIR

SFX_DIR = os.path.join(DATA_DIR, "sfx")
_WHOOSH_FILES = ["1 - Whoosh.MP3", "2 - Whoosh 2.MP3", "3 - Whoosh 3.MP3"]
_FLASH_SFX = "21 - Camera Flash.MP3"
_AUDIO_SUFFIXES = (".mp3", ".wav", ".m4a", ".aac", ".flac")


def sfx_library() -> dict:
    """Every tag folder under SFX_LIBRARY_DIR, with its audio files (absolute paths)."""
    if not os.path.isdir(config.SFX_LIBRARY_DIR):
        return {}
    library = {}
    for name in sorted(os.listdir(config.SFX_LIBRARY_DIR)):
        folder = os.path.join(config.SFX_LIBRARY_DIR, name)
        if name.startswith((".", "_")) or not os.path.isdir(folder):
            continue
        library[name] = sorted(
            os.path.join(folder, f) for f in os.listdir(folder)
            if os.path.splitext(f)[1].lower() in _AUDIO_SUFFIXES
        )
    return library


def pick_sfx(files: List[str], seed: str, tag: str, occurrence: int) -> str:
    """
    The file for the Nth use of a tag in one video.

    Starts at a per-video offset and then rotates, so the same tag twice in a
    row never plays the same file (while the folder has more than one), and
    re-rendering the same video picks the same files. zlib.crc32, not hash():
    Python randomizes hash() for strings in every new process.
    """
    return files[(zlib.crc32(f"{seed}:{tag}".encode()) + occurrence) % len(files)]


def sfx_play_seconds(path: str) -> float:
    """How long an effect actually plays: its length, cut to SFX_MAX_SECONDS."""
    return min(_probe_duration(path), config.SFX_MAX_SECONDS)


def peak_loudness(path: str) -> Optional[float]:
    """
    The loudest 400ms of a sound (ebur128 momentary max), in LUFS.

    Integrated loudness is meaningless for a 0.3s click (it needs seconds of
    audio and mostly measures the silence around it), so effects are matched
    on their loudest moment instead, the part that actually gets heard.
    """
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", path, "-af", "apad=pad_dur=0.5,ebur128",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )
    loudest = None
    for line in result.stderr.splitlines():
        if " M:" in line:
            try:
                m = float(line.split(" M:")[1].split()[0])
            except (ValueError, IndexError):
                continue
            loudest = m if loudest is None else max(loudest, m)
    return loudest


def find_silences(audio_path: str, noise_db: float = -40.0, min_seconds: float = 0.1) -> List[tuple]:
    """(start, end) of every pause in a narration file, from ffmpeg silencedetect."""
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", audio_path,
         "-af", f"silencedetect=noise={noise_db}dB:d={min_seconds}", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    silences, start = [], None
    for line in result.stderr.splitlines():
        if "silence_start:" in line:
            start = float(line.split("silence_start:")[1].split()[0])
        elif "silence_end:" in line and start is not None:
            silences.append((start, float(line.split("silence_end:")[1].split()[0])))
            start = None
    return silences


def splice_silence(audio_path: str, inserts: List[tuple]) -> None:
    """
    Insert silence into a narration file, in place. `inserts` is a list of
    (time, seconds) on the ORIGINAL timeline. One ffmpeg call: the narration
    is cut (atrim) at every insert time, a silent piece (anullsrc) goes
    between the cuts, and concat joins them back up.
    """
    inserts = sorted(inserts)
    info = json.loads(subprocess.run(
        ["ffprobe", "-v", "quiet", "-select_streams", "a:0",
         "-show_entries", "stream=sample_rate,channels", "-of", "json", audio_path],
        capture_output=True, text=True, check=True,
    ).stdout)["streams"][0]
    rate, layout = info["sample_rate"], "mono" if info["channels"] == 1 else "stereo"

    chains, labels, prev = [], [], 0.0
    for k, (when, seconds) in enumerate(inserts):
        chains.append(f"[0:a]atrim=start={prev:.3f}:end={when:.3f},asetpts=PTS-STARTPTS[a{k}]")
        chains.append(f"anullsrc=r={rate}:cl={layout},atrim=duration={seconds:.3f}[z{k}]")
        labels += [f"[a{k}]", f"[z{k}]"]
        prev = when
    chains.append(f"[0:a]atrim=start={prev:.3f},asetpts=PTS-STARTPTS[tail]")
    labels.append("[tail]")
    filters = ";".join(chains) + f";{''.join(labels)}concat=n={len(labels)}:v=0:a=1[out]"

    # 192k: a lower bitrate is what made narration sound muffled before
    tmp = audio_path + ".spliced.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-i", audio_path, "-filter_complex", filters, "-map", "[out]",
         "-c:a", "libmp3lame", "-b:a", "192k", tmp],
        check=True, capture_output=True,
    )
    os.replace(tmp, audio_path)


SHORTS_CAP_SECONDS = 82   # narration past this is cut when shorts_cap is on

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REMOTION_DIR = os.path.join(PROJECT_ROOT, "remotion")


class _SilentFileServer(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


def _start_asset_server(serve_dir: str):
    """Start a local HTTP server to serve project files to Remotion. Returns (httpd, port)."""
    s = socket.socket()
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()

    def handler(*args, **kwargs):
        return _SilentFileServer(*args, directory=serve_dir, **kwargs)

    httpd = http.server.HTTPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, port


def _probe_duration(path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "json", path],
        capture_output=True, text=True, check=True
    )
    return float(json.loads(result.stdout)["format"]["duration"])


def _measure_lufs(path: str) -> Optional[float]:
    """Measure integrated loudness (LUFS) of an audio file."""
    try:
        proc = subprocess.run([
            "ffmpeg", "-hide_banner", "-nostats", "-i", path,
            "-af", "loudnorm=print_format=summary", "-f", "null", "-",
        ], capture_output=True, text=True)
        for line in proc.stderr.splitlines():
            if "Input Integrated:" in line:
                return float(line.split(":")[1].strip().split()[0])
    except Exception:
        pass
    return None


def _prepare_music(music_path: str, target_dur: float,
                   target_lufs: float = -34.0) -> Optional[str]:
    """Trim or loop music to target_dur seconds and normalize it to target_lufs."""
    if not music_path or not os.path.exists(music_path):
        return None
    try:
        music_dur = _probe_duration(music_path)
    except Exception:
        return None

    measured = _measure_lufs(music_path)
    gain_db = max(-40.0, min(20.0, target_lufs - measured)) if measured is not None else 0.0
    encode = ["-af", f"volume={gain_db:.1f}dB", "-c:a", "libmp3lame", "-b:a", "192k"]
    print(f"Music {measured} LUFS -> {target_lufs} LUFS ({gain_db:+.1f} dB)")

    out_path = music_path + "_final.mp3"
    try:
        if music_dur >= target_dur:
            start = random.uniform(0, music_dur - target_dur)
            subprocess.run([
                "ffmpeg", "-y",
                "-ss", str(start), "-t", str(target_dur),
                "-i", music_path,
                *encode,
                out_path
            ], check=True, capture_output=True)
        else:
            loops = math.ceil(target_dur / music_dur)
            subprocess.run([
                "ffmpeg", "-y",
                "-stream_loop", str(loops),
                "-i", music_path,
                "-t", str(target_dur),
                *encode,
                out_path
            ], check=True, capture_output=True)
        return out_path
    except subprocess.CalledProcessError as e:
        print(f"Music prep failed: {e}")
        return music_path


def _build_clips(video_paths: List[str], target_dur: float, base_url: str,
                 clip_meta: Optional[List[dict]] = None) -> List[dict]:
    """
    Build {path (http URL), duration, layout...} dicts summing to target_dur.
    Paths are served via the local asset HTTP server. clip_meta (aligned with
    video_paths) carries each clip's layout; looped filler clips are always framed.
    """
    clips = []
    remaining = target_dur
    clip_meta = clip_meta or []

    for i, vp in enumerate(video_paths):
        if remaining <= 0:
            break
        try:
            dur = _probe_duration(vp)
        except Exception:
            dur = target_dur
        take = min(dur, remaining)
        rel = os.path.relpath(os.path.abspath(vp), PROJECT_ROOT)
        meta = clip_meta[i] if i < len(clip_meta) else {}
        clips.append({"path": f"{base_url}/{rel}", "duration": round(take, 3), **meta})
        remaining -= take

    if remaining > 0.05 and clips:
        last = clips[-1]
        abs_path = os.path.join(PROJECT_ROOT,
                                last["path"].split(base_url + "/", 1)[1])
        while remaining > 0.05:
            dur = _probe_duration(abs_path)
            take = min(dur, remaining)
            clips.append({"path": last["path"], "duration": round(take, 3), "layout": "framed"})
            remaining -= take

    return clips


def _asset_url(abs_path: str, base_url: str) -> str:
    rel = os.path.relpath(os.path.abspath(abs_path), PROJECT_ROOT)
    return f"{base_url}/{rel}"


# The CTA clip is 8s, but 3.2s-6.6s is just "FOLLOWING" held still. Keeping the
# intro + click and the exit animation gives the same effect in 4.6s, which
# leaves more of the video free for narration graphic cards.
CTA_KEEP = [(0.0, 3.2), (6.6, 8.0)]
CTA_DURATION = sum(b - a for a, b in CTA_KEEP)


def _composite_cta(base_video: str, cta_path: str, cta_start: float, out_path: str):
    """Overlay green-screen CTA (shortened to CTA_KEEP) onto base_video from cta_start using FFmpeg chromakey."""
    (a0, a1), (b0, b1) = CTA_KEEP
    subprocess.run([
        "ffmpeg", "-y",
        "-i", base_video,
        "-i", cta_path,
        "-filter_complex",
        f"[1:v]split[ca][cb];"
        f"[ca]trim={a0}:{a1},setpts=PTS-STARTPTS[c1];"
        f"[cb]trim={b0}:{b1},setpts=PTS-STARTPTS[c2];"
        f"[c1][c2]concat=n=2:v=1:a=0,setpts=PTS-STARTPTS+{cta_start}/TB,"
        f"chromakey=color=0x00FF00:similarity=0.35:blend=0.1[ck];"
        f"[0:v][ck]overlay=0:500[v]",
        "-map", "[v]", "-map", "0:a",
        "-c:v", "libx264", "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        out_path,
    ], check=True, capture_output=True)


def _graphics_before_cta(graphics: List[dict], cutoff: float) -> List[dict]:
    """Keep graphic cards out of the follow-button window: the CTA is composited
    over the same lower zone, so a card still on screen there gets covered.
    Cards are cut to end before `cutoff`; ones left with under 1s are dropped."""
    kept = []
    for g in graphics:
        end = min(g["end"], cutoff - 0.2)
        if end - g["start"] >= 1.0:
            kept.append({**g, "end": round(end, 3)})
        else:
            print(f"Dropped {g['type']} card at {g['start']:.1f}s (overlaps follow button)")
    return kept


def _build_sfx_events(clips: List[dict], base_url: str) -> List[dict]:
    """Assign a whoosh or camera flash SFX to each cut point."""
    events = []
    accumulated = 0.0
    for i, clip in enumerate(clips[:-1]):
        accumulated += clip["duration"]
        is_flash_cut = (i % 3 == 1)
        sfx_file = _FLASH_SFX if is_flash_cut else random.choice(_WHOOSH_FILES)
        volume = 0.12 if is_flash_cut else 0.28
        abs_path = os.path.join(SFX_DIR, sfx_file)
        if os.path.exists(abs_path):
            rel = os.path.relpath(abs_path, PROJECT_ROOT)
            encoded = urllib.parse.quote(rel, safe="/")
            events.append({"time": round(accumulated, 3), "file": f"{base_url}/{encoded}", "volume": volume})
    return events


def _build_tagged_sfx_events(tagged_sfx: List[dict], base_url: str, speech_lufs: float) -> List[dict]:
    """
    Remotion events for the tagged effects (placed by main.py _place_tagged_sfx).
    Each sits SFX_UNDER_DB[kind] below the narration, measured by its loudest
    moment, and carries its play length so Remotion can cut it with a fade.
    """
    events = []
    for s in tagged_sfx:
        level = peak_loudness(s["path"])
        if level is None:
            print(f"  [sfx] unreadable {os.path.basename(s['path'])}, skipped")
            continue
        gain_db = (speech_lufs - config.SFX_UNDER_DB[s["kind"]]) - level
        volume = 10 ** (gain_db / 20)
        if volume > 1.0:
            # Remotion's volume tops out at 1 (the file's own level)
            print(f"  [sfx] {os.path.basename(s['path'])} wants {gain_db:+.1f} dB, capped at 0 dB")
            volume = 1.0
        events.append({
            "time": round(s["time"], 3),
            # quoted: library names have spaces and brackets ("Angel - Sound Effect (HD).mp3")
            "file": f"{base_url}/{urllib.parse.quote(os.path.relpath(s['path'], PROJECT_ROOT), safe='/')}",
            "volume": round(volume, 4),
            "duration": round(s["duration"], 3),
            "fade": config.SFX_FADE_SECONDS,
        })
        print(f"  [sfx] {s['time']:6.1f}s  {s['kind']:8} {s['tag']:10} "
              f"{os.path.basename(s['path'])}  ({gain_db:+.1f} dB)")
    return events


def merge_audio_video(
    video_paths: Union[str, List[str]],
    audio_path: str,
    output_name: str = "final_short.mp4",
    target_w: int = 1080,
    target_h: int = 1920,
    shorts_cap: bool = True,
    cap_seconds: float = SHORTS_CAP_SECONDS,
    music_path: Optional[str] = None,
    music_lufs: float = -34.0,
    words_data: Optional[list] = None,
    cta_path: str = CTA_PATH,
    clip_meta: Optional[List[dict]] = None,
    graphics: Optional[List[dict]] = None,
    tagged_sfx: Optional[List[dict]] = None,
    theme: Optional[dict] = None,
    frame_background: str = "blur",
    hook_text: str = "",
) -> str:
    """Render final Short via Remotion (background + audio + subtitles), then composite CTA via FFmpeg."""
    print("\nStarting Remotion render...")

    if isinstance(video_paths, str):
        video_paths = [video_paths]

    httpd, port = _start_asset_server(PROJECT_ROOT)
    base_url = f"http://127.0.0.1:{port}"
    print(f"Asset server: {base_url}")

    out_path = os.path.join(FINAL_DIR, output_name)
    prepared_music = None

    try:
        audio_dur = _probe_duration(audio_path)

        voice_dur = min(audio_dur, cap_seconds) if shorts_cap else audio_dur
        total_dur = voice_dur
        cta_start = max(0.0, voice_dur - CTA_DURATION)
        has_cta = cta_path and os.path.exists(cta_path)

        clips = _build_clips(video_paths, total_dur, base_url, clip_meta)
        prepared_music = _prepare_music(music_path, total_dur, music_lufs) if music_path else None

        sfx_events = _build_sfx_events(clips, base_url)
        tagged_events = []
        if tagged_sfx:
            speech_lufs = _measure_lufs(audio_path)
            if speech_lufs is None:
                print("Could not measure narration loudness, skipping tagged sound effects")
            else:
                print(f"Tagged sound effects (narration {speech_lufs:.1f} LUFS):")
                tagged_events = _build_tagged_sfx_events(
                    [s for s in tagged_sfx if s["time"] < total_dur], base_url, speech_lufs)
        sfx_events += tagged_events

        words_dicts: List[dict] = []
        if words_data:
            words_dicts = [
                {"word": w, "start": round(s, 3), "end": round(e, 3)}
                for w, s, e in words_data
            ]

        props = {
            "clips": clips,
            "audioPath": _asset_url(audio_path, base_url),
            "musicPath": _asset_url(prepared_music, base_url) if prepared_music else None,
            "musicVolume": 1.0,
            "wordsData": words_dicts,
            "sfxEvents": sfx_events,
            # the music dips under tagged effects only, not under the cut whooshes
            "sfxWindows": [[e["time"], e["time"] + e["duration"]] for e in tagged_events],
            "duckDb": config.SFX_MUSIC_DUCK_DB,
            "duckRampSec": config.SFX_DUCK_RAMP_SECONDS,
            "graphics": _graphics_before_cta(graphics or [], cta_start if has_cta else total_dur),
            "theme": theme or {},
            "frameBackground": frame_background,
            "hookText": hook_text,
            "totalDurationSec": round(total_dur, 3),
        }

        props_path = os.path.join(REMOTION_DIR, "props.json")
        with open(props_path, "w") as f:
            json.dump(props, f, indent=2)

        remotion_out = out_path + "_base.mp4" if has_cta else out_path

        print(f"Rendering {total_dur:.1f}s @ 1080×1920 via Remotion...")
        subprocess.run(
            [
                "npx", "remotion", "render",
                "ShortVideo",
                "--props", props_path,
                "--output", remotion_out,
                "--width", str(target_w),
                "--height", str(target_h),
                "--fps", "30",
                "--codec", "h264",
                "--jpeg-quality", "95",
                "--concurrency", "4",
            ],
            check=True,
            cwd=REMOTION_DIR,
        )
    finally:
        httpd.shutdown()
        if prepared_music and prepared_music != music_path and os.path.exists(prepared_music):
            try:
                os.remove(prepared_music)
            except Exception:
                pass

    if has_cta:
        print(f"Compositing CTA (starts at {cta_start:.1f}s)...")
        try:
            _composite_cta(remotion_out, cta_path, cta_start, out_path)
            os.remove(remotion_out)
        except subprocess.CalledProcessError as e:
            print(f"CTA composite failed, using base render: {e.stderr.decode()[-300:]}")
            os.rename(remotion_out, out_path)

    print(f"Saved: {out_path}")
    return out_path


def render_thumbnail(frame_path: str, hook_lines: List[dict], output_name: str) -> str:
    """Render a static thumbnail: a real footage frame (CSS-enhanced) with multi-color
    hook text on top (e.g. [{"text": "PRIME", "color": "#FFE000"}, ...])."""
    out_path = os.path.join(THUMBNAIL_DIR, output_name)

    httpd, port = _start_asset_server(PROJECT_ROOT)
    base_url = f"http://127.0.0.1:{port}"

    try:
        props = {
            "framePath": _asset_url(frame_path, base_url),
            "hookLines": hook_lines,
        }
        props_path = os.path.join(REMOTION_DIR, "thumbnail_props.json")
        with open(props_path, "w") as f:
            json.dump(props, f, indent=2)

        subprocess.run(
            [
                "npx", "remotion", "still",
                "Thumbnail",
                "--props", props_path,
                "--output", out_path,
                "--width", "1080",
                "--height", "1920",
            ],
            check=True,
            cwd=REMOTION_DIR,
        )
    finally:
        httpd.shutdown()

    print(f"Thumbnail saved: {out_path}")
    return out_path


def append_thumbnail_frame(video_path: str, thumbnail_path: str, duration: float = 0.25,
                           position: str = "start") -> str:
    """Burn a still thumbnail frame into the video so YouTube Shorts can use it as the
    cover. position="start" -> becomes the automatic feed cover; "end" -> pick via
    Edit > Cover slider. Re-encodes to a temp file then replaces the original. Params
    match the main render: 1080x1920, 30fps, yuv420p, AAC 48k stereo, so the concat
    is seamless."""
    tmp_out = video_path + "_thumbed.mp4"
    order = "[tv][a2][v0][a0]" if position == "start" else "[v0][a0][tv][a2]"
    subprocess.run([
        "ffmpeg", "-y",
        "-i", video_path,
        "-loop", "1", "-t", f"{duration}", "-i", thumbnail_path,
        "-f", "lavfi", "-t", f"{duration}", "-i",
        "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-filter_complex",
        "[0:v]setsar=1,fps=30,format=yuv420p[v0];"
        "[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a0];"
        "[1:v]scale=1080:1920,setsar=1,fps=30,format=yuv420p[tv];"
        "[2:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a2];"
        f"{order}concat=n=2:v=1:a=1[v][a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        tmp_out,
    ], check=True, capture_output=True)
    os.replace(tmp_out, video_path)
    print(f"Thumbnail frame added ({duration}s, {position}) to video")
    return video_path
