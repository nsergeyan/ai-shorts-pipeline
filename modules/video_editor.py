import http.server
import json
import math
import os
import random
import socket
import subprocess
import tempfile
import threading
import urllib.parse
from typing import List, Optional, Union

from config import DATA_DIR, CTA_PATH, THUMBNAIL_DIR

SFX_DIR = os.path.join(DATA_DIR, "sfx")
_WHOOSH_FILES = ["1 - Whoosh.MP3", "2 - Whoosh 2.MP3", "3 - Whoosh 3.MP3"]
_FLASH_SFX = "21 - Camera Flash.MP3"
_PUNCH_SFX_FILES = ["awkward_moment.mp3", "radio_peep.mp3"]
_PUNCH_SFX_STATE_FILE = os.path.join(DATA_DIR, "_punch_sfx_state.json")


def _next_punch_sfx() -> str:
    """Alternate strictly between punch SFX files across runs (persisted to disk)."""
    last_index = -1
    try:
        with open(_PUNCH_SFX_STATE_FILE) as f:
            last_index = json.load(f).get("last_index", -1)
    except Exception:
        pass
    next_index = (last_index + 1) % len(_PUNCH_SFX_FILES)
    try:
        with open(_PUNCH_SFX_STATE_FILE, "w") as f:
            json.dump({"last_index": next_index}, f)
    except Exception:
        pass
    return _PUNCH_SFX_FILES[next_index]

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FINAL_DIR = os.path.join(DATA_DIR, "final")
REMOTION_DIR = os.path.join(PROJECT_ROOT, "remotion")
os.makedirs(FINAL_DIR, exist_ok=True)


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


def _prepare_cta_transparent(cta_path: str) -> Optional[str]:
    """Convert green-screen CTA to transparent WebM, stored inside DATA_DIR."""
    out_path = os.path.join(DATA_DIR, "cta_transparent.webm")
    if os.path.exists(out_path):
        return out_path
    if not cta_path or not os.path.exists(cta_path):
        return None
    try:
        subprocess.run([
            "ffmpeg", "-y",
            "-i", cta_path,
            "-vf", "chromakey=color=0x00FF00:similarity=0.35:blend=0.05",
            "-pix_fmt", "yuva420p",
            "-c:v", "libvpx-vp9",
            "-b:v", "2M",
            "-an",
            out_path
        ], check=True, capture_output=True)
        print(f"✅ CTA transparent: {out_path}")
        return out_path
    except subprocess.CalledProcessError as e:
        print(f"⚠️ CTA chromakey failed, using original: {e.stderr.decode()[-200:]}")
        return cta_path


def _prepare_music(music_path: str, target_dur: float) -> Optional[str]:
    """Trim or loop music to exactly target_dur seconds."""
    if not music_path or not os.path.exists(music_path):
        return None
    try:
        music_dur = _probe_duration(music_path)
    except Exception:
        return None

    out_path = music_path + "_final.mp3"
    try:
        if music_dur >= target_dur:
            start = random.uniform(0, music_dur - target_dur)
            subprocess.run([
                "ffmpeg", "-y",
                "-ss", str(start), "-t", str(target_dur),
                "-i", music_path,
                "-c", "copy",
                out_path
            ], check=True, capture_output=True)
        else:
            loops = math.ceil(target_dur / music_dur)
            subprocess.run([
                "ffmpeg", "-y",
                "-stream_loop", str(loops),
                "-i", music_path,
                "-t", str(target_dur),
                "-c", "copy",
                out_path
            ], check=True, capture_output=True)
        return out_path
    except subprocess.CalledProcessError as e:
        print(f"⚠️ Music prep failed: {e}")
        return music_path


def _build_clips(video_paths: List[str], target_dur: float, base_url: str) -> List[dict]:
    """
    Build {path (http URL), duration} dicts summing to target_dur.
    Paths are served via the local asset HTTP server.
    """
    clips = []
    remaining = target_dur

    for vp in video_paths:
        if remaining <= 0:
            break
        try:
            dur = _probe_duration(vp)
        except Exception:
            dur = target_dur
        take = min(dur, remaining)
        rel = os.path.relpath(os.path.abspath(vp), PROJECT_ROOT)
        clips.append({"path": f"{base_url}/{rel}", "duration": round(take, 3)})
        remaining -= take

    if remaining > 0.05 and clips:
        last = clips[-1]
        abs_path = os.path.join(PROJECT_ROOT,
                                last["path"].split(base_url + "/", 1)[1])
        while remaining > 0.05:
            dur = _probe_duration(abs_path)
            take = min(dur, remaining)
            clips.append({"path": last["path"], "duration": round(take, 3)})
            remaining -= take

    return clips


def _asset_url(abs_path: str, base_url: str) -> str:
    rel = os.path.relpath(os.path.abspath(abs_path), PROJECT_ROOT)
    return f"{base_url}/{rel}"


def _composite_cta(base_video: str, cta_path: str, cta_start: float, cta_duration: float, out_path: str):
    """Overlay green-screen CTA onto base_video starting at cta_start using FFmpeg chromakey."""
    subprocess.run([
        "ffmpeg", "-y",
        "-i", base_video,
        "-i", cta_path,
        "-filter_complex",
        f"[1:v]trim=duration={cta_duration},setpts=PTS-STARTPTS+{cta_start}/TB,"
        f"chromakey=color=0x00FF00:similarity=0.35:blend=0.1[ck];"
        f"[0:v][ck]overlay=0:500[v]",
        "-map", "[v]", "-map", "0:a",
        "-c:v", "libx264", "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        out_path,
    ], check=True, capture_output=True)


def _build_sfx_events(clips: List[dict], base_url: str, punch_times: List[float] = None) -> List[dict]:
    """Assign SFX to each cut point and punch word timestamps."""
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

    for pt in (punch_times or []):
        sfx_file = _next_punch_sfx()
        abs_path = os.path.join(SFX_DIR, sfx_file)
        if os.path.exists(abs_path):
            rel = os.path.relpath(abs_path, PROJECT_ROOT)
            encoded = urllib.parse.quote(rel, safe="/")
            events.append({"time": round(pt, 3), "file": f"{base_url}/{encoded}", "volume": 0.4})

    return events


def merge_audio_video(
    video_paths: Union[str, List[str]],
    audio_path: str,
    output_name: str = "final_short.mp4",
    vertical: bool = False,
    target_w: int = 1080,
    target_h: int = 1920,
    shorts_cap: bool = True,
    cap_seconds: float = 82,
    music_path: Optional[str] = None,
    music_volume: float = 0.07,
    subtitles_data: Optional[list] = None,
    subtitles_position: str = "top",
    words_data: Optional[list] = None,
    cta_path: str = CTA_PATH,
    subtitles_text: Optional[str] = None,
    hook_text: Optional[str] = None,
    punch_times: Optional[List[float]] = None,
) -> str:
    """Render final Short via Remotion (background + audio + subtitles), then composite CTA via FFmpeg."""
    print("\n🎬  Starting Remotion render...")

    if isinstance(video_paths, str):
        video_paths = [video_paths]

    httpd, port = _start_asset_server(PROJECT_ROOT)
    base_url = f"http://127.0.0.1:{port}"
    print(f"📡 Asset server: {base_url}")

    out_path = os.path.join(FINAL_DIR, output_name)
    prepared_music = None

    try:
        audio_dur = _probe_duration(audio_path)

        CTA_DURATION = 8.0
        voice_dur = min(audio_dur, cap_seconds) if shorts_cap else audio_dur
        total_dur = voice_dur
        cta_start = max(0.0, voice_dur - CTA_DURATION)

        clips = _build_clips(video_paths, total_dur, base_url)
        prepared_music = _prepare_music(music_path, total_dur) if music_path else None

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
            "musicVolume": music_volume,
            "wordsData": words_dicts,
            "punchTimes": punch_times or [],
            "sfxEvents": _build_sfx_events(clips, base_url, punch_times),
            "totalDurationSec": round(total_dur, 3),
        }

        props_path = os.path.join(REMOTION_DIR, "props.json")
        with open(props_path, "w") as f:
            json.dump(props, f, indent=2)

        has_cta = cta_path and os.path.exists(cta_path)
        remotion_out = out_path + "_base.mp4" if has_cta else out_path

        print(f"🎞️  Rendering {total_dur:.1f}s @ 1080×1920 via Remotion...")
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
        print(f"🎭  Compositing CTA (starts at {cta_start:.1f}s)...")
        try:
            _composite_cta(remotion_out, cta_path, cta_start, CTA_DURATION, out_path)
            os.remove(remotion_out)
        except subprocess.CalledProcessError as e:
            print(f"⚠️  CTA composite failed, using base render: {e.stderr.decode()[-300:]}")
            os.rename(remotion_out, out_path)

    print(f"✅  Saved: {out_path}")
    return out_path


def render_thumbnail(frame_path: str, hook_lines: List[dict], output_name: str) -> str:
    """Render a static thumbnail: a real footage frame (CSS-enhanced) + brand-styled,
    multi-color hook text (e.g. [{"text": "PRIME", "color": "#FFE000"}, ...]).
    No generative AI involved — deterministic and free."""
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

    print(f"🖼️  Thumbnail saved: {out_path}")
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
    print(f"🖼️  Thumbnail frame added ({duration}s, {position}) to video")
    return video_path
