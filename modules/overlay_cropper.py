"""Find burned-in text and logos (news banners, channel bugs, watermarks) and crop them out.

Uses Apple's Vision OCR through `ocrmac`, so it runs locally and costs no API calls.
Text that stays in the same place across many frames is an overlay; text that moves
(shirt numbers, stadium boards) is part of the scene and is left alone. The video is
cropped to the biggest rectangle without overlays, so Gemini, the frame checks and the
render all see the clean picture. Text in the middle of the frame can't be cropped
away, so those videos are left as they are and Gemini judges them.
"""
import glob
import os
import shutil
import subprocess
import tempfile

import numpy as np
from ocrmac import ocrmac

SAMPLE_FPS = 0.5          # one frame every 2 seconds
GRID_COLS, GRID_ROWS = 48, 27
PERSISTENT_SHARE = 0.2    # text in a cell in at least this share of frames is an overlay
MIN_KEEP_AREA = 0.5       # never keep less than half of the picture
MIN_ASPECT, MAX_ASPECT = 1.0, 2.6   # kept width / height in pixels


def _video_size(video_path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
         "-of", "csv=p=0", video_path], capture_output=True, text=True, timeout=30,
    ).stdout.strip()
    w, h = out.split(",")[:2]
    return int(w), int(h)


def _overlay_map(video_path):
    """Share of sampled frames with text in each grid cell, plus the number of frames read."""
    tmp = tempfile.mkdtemp(prefix="ocr_")
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-i", video_path, "-vf", f"fps={SAMPLE_FPS},scale=640:-2",
                        os.path.join(tmp, "f%04d.jpg")], timeout=300, check=True)
        frames = sorted(glob.glob(os.path.join(tmp, "*.jpg")))
        counts = np.zeros((GRID_ROWS, GRID_COLS))
        for f in frames:
            hit = np.zeros((GRID_ROWS, GRID_COLS), dtype=bool)
            for text, _conf, (x, y, w, h) in ocrmac.OCR(f, recognition_level="fast").recognize():
                if len(text.strip()) < 2:
                    continue
                top = 1 - y - h   # Vision measures y from the bottom
                c0, c1 = int(x * GRID_COLS), int(np.ceil((x + w) * GRID_COLS))
                r0, r1 = int(top * GRID_ROWS), int(np.ceil((top + h) * GRID_ROWS))
                hit[max(r0, 0):min(r1, GRID_ROWS), max(c0, 0):min(c1, GRID_COLS)] = True
            counts += hit
        return counts / max(len(frames), 1), len(frames)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _best_rect(blocked, width, height):
    """Biggest grid rectangle with no blocked cell, as (left, top, right, bottom) in cells."""
    sums = np.pad(blocked.astype(int).cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    cell_w, cell_h = width / GRID_COLS, height / GRID_ROWS
    best, best_area = None, MIN_KEEP_AREA * GRID_COLS * GRID_ROWS - 1e-9
    for t in range(GRID_ROWS):
        for b in range(GRID_ROWS, t, -1):
            if (b - t) * GRID_COLS <= best_area:
                break
            for l in range(GRID_COLS):
                for r in range(GRID_COLS, l, -1):
                    area = (b - t) * (r - l)
                    if area <= best_area:
                        break
                    if not MIN_ASPECT <= (r - l) * cell_w / ((b - t) * cell_h) <= MAX_ASPECT:
                        continue
                    if sums[b, r] - sums[t, r] - sums[b, l] + sums[t, l] == 0:
                        best, best_area = (l, t, r, b), area
                        break
    return best


def crop_overlays(video_path):
    """Crop persistent text and logos out of the video in place. Returns the path."""
    try:
        width, height = _video_size(video_path)
        share, n_frames = _overlay_map(video_path)
    except Exception as e:
        print(f"   Overlay scan failed: {e}")
        return video_path

    blocked = share >= PERSISTENT_SHARE
    if n_frames == 0 or not blocked.any():
        print("   Overlay scan: no fixed text or logos")
        return video_path

    rect = _best_rect(blocked, width, height)
    if rect is None:
        print("   Overlay scan: fixed text in the middle of the picture, can't crop it out")
        return video_path

    l, t, r, b = rect
    x, y = int(l * width / GRID_COLS) // 2 * 2, int(t * height / GRID_ROWS) // 2 * 2
    w = int(r * width / GRID_COLS) // 2 * 2 - x
    h = int(b * height / GRID_ROWS) // 2 * 2 - y
    print(f"   Overlay scan: cropping fixed text/logos away, keeping {w}x{h} of {width}x{height} "
          f"(cut left {l / GRID_COLS:.0%}, right {1 - r / GRID_COLS:.0%}, "
          f"top {t / GRID_ROWS:.0%}, bottom {1 - b / GRID_ROWS:.0%})")

    base, ext = os.path.splitext(video_path)
    cropped = f"{base}_cropped{ext}"
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", video_path, "-vf", f"crop={w}:{h}:{x}:{y}",
                        "-c:v", "h264_videotoolbox", "-b:v", "8M", "-c:a", "copy", cropped],
                       timeout=600, check=True)
        os.replace(cropped, video_path)
    except Exception as e:
        print(f"   Overlay crop failed, keeping the original: {e}")
        if os.path.exists(cropped):
            os.remove(cropped)
    return video_path


if __name__ == "__main__":
    import sys
    for path in sys.argv[1:]:
        share, n = _overlay_map(path)
        print(path, n, "frames")
        for row in share:
            print("".join("#" if v >= PERSISTENT_SHARE else ("+" if v > 0.05 else ".") for v in row))
        print(_best_rect(share >= PERSISTENT_SHARE, *_video_size(path)))
