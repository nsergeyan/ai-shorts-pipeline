"""Upload finished shorts to YouTube (Data API v3) and TikTok (Content Posting API).

One-time login per account, saved under tokens/ (paths come from schedule.json):
    python -m modules.uploader login youtube anime
    python -m modules.uploader login youtube sports
    python -m modules.uploader login tiktok anime

Until Google audits the Cloud project, YouTube keeps API uploads private. Until TikTok
audits the app, only SELF_ONLY (private) posts are allowed.
"""
import json
import os
import secrets
import sys
import time
import urllib.parse

import requests

from config import (BASE_DIR, YOUTUBE_CLIENT_SECRET, TIKTOK_CLIENT_KEY,
                    TIKTOK_CLIENT_SECRET, TIKTOK_REDIRECT_URI)

SCHEDULE_PATH = os.path.join(BASE_DIR, "schedule.json")

# readonly is only there to print which channel a login belongs to
YT_SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
             "https://www.googleapis.com/auth/youtube.readonly"]

YT_PROCESSING_WAIT = 15 * 60  # thumbnails.set only works once YouTube has processed the video

TIKTOK_API = "https://open.tiktokapis.com/v2"
TIKTOK_SINGLE_CHUNK_MAX = 64 * 1024 * 1024  # TikTok accepts one chunk up to 64MB
TIKTOK_CHUNK = 10 * 1024 * 1024
TIKTOK_STATUS_WAIT = 300


def load_schedule():
    with open(SCHEDULE_PATH) as f:
        return json.load(f)


def _token_path(rel):
    return os.path.join(BASE_DIR, rel)


def _save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------- YouTube

def _youtube_client(token_path, interactive=False):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, YT_SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif not creds or not creds.valid:
        if not interactive:
            raise RuntimeError(f"No YouTube login at {token_path}, run: python -m modules.uploader login youtube <channel>")
        flow = InstalledAppFlow.from_client_secrets_file(YOUTUBE_CLIENT_SECRET, YT_SCOPES)
        # select_account shows the account/channel picker every time, so each channel gets its own token
        creds = flow.run_local_server(port=0, prompt="select_account consent")
    os.makedirs(os.path.dirname(token_path), exist_ok=True)
    with open(token_path, "w") as f:
        f.write(creds.to_json())
    return build("youtube", "v3", credentials=creds)


def upload_youtube(video_path, title, description, tags, cfg, thumbnail_path=None):
    """Upload one video, set its thumbnail when given, and return its YouTube id."""
    from googleapiclient.http import MediaFileUpload

    yt = _youtube_client(_token_path(cfg["token"]))
    body = {
        # YouTube rejects a tag list over 500 characters in total
        "snippet": {"title": title[:100], "description": description[:5000], "categoryId": cfg.get("category_id", "24"),
                    "tags": _fit_tags(tags, 500)},
        "status": {"privacyStatus": cfg.get("privacy", "private"), "selfDeclaredMadeForKids": False},
    }
    request = yt.videos().insert(
        part="snippet,status", body=body,
        media_body=MediaFileUpload(video_path, mimetype="video/mp4", chunksize=-1, resumable=True),
    )
    response = None
    while response is None:
        _, response = request.next_chunk()
    video_id = response["id"]
    print(f"  YouTube: uploaded https://youtube.com/shorts/{video_id}")
    if thumbnail_path and os.path.exists(thumbnail_path):
        # A thumbnail failure must not fail the upload, or the retry would post the video twice
        try:
            _set_youtube_thumbnail(yt, video_id, thumbnail_path)
        except Exception as e:
            print(f"  YouTube: thumbnail not set ({e}). Set it in Studio by hand")
    return video_id


def _set_youtube_thumbnail(yt, video_id, thumbnail_path):
    from googleapiclient.http import MediaFileUpload

    deadline = time.time() + YT_PROCESSING_WAIT
    while True:
        items = yt.videos().list(part="status", id=video_id).execute().get("items", [])
        status = items[0]["status"]["uploadStatus"] if items else "missing"
        if status == "processed":
            break
        if status in ("failed", "rejected", "deleted", "missing"):
            raise RuntimeError(f"video is {status}")
        if time.time() > deadline:
            raise RuntimeError("still processing after 15 minutes")
        time.sleep(20)
    # 403 here usually means the channel is not phone-verified for custom thumbnails
    yt.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(thumbnail_path, mimetype="image/png")).execute()
    print("  YouTube: thumbnail set")


def _fit_tags(tags, limit):
    fitted, total = [], 0
    for tag in tags or []:
        tag = tag.strip().replace("<", "").replace(">", "")
        # Tags with a space count as quoted, two characters extra
        cost = len(tag) + (2 if " " in tag else 0) + 1
        if tag and total + cost <= limit:
            fitted.append(tag)
            total += cost
    return fitted


def login_youtube(cfg):
    yt = _youtube_client(_token_path(cfg["token"]), interactive=True)
    channels = yt.channels().list(part="snippet", mine=True).execute().get("items", [])
    name = channels[0]["snippet"]["title"] if channels else "(no channel found)"
    print(f"Logged in to YouTube channel: {name}\nSaved to {cfg['token']}")


# ---------------------------------------------------------------- TikTok

def _tiktok_token_request(data):
    r = requests.post(f"{TIKTOK_API}/oauth/token/", timeout=30, data={
        "client_key": TIKTOK_CLIENT_KEY, "client_secret": TIKTOK_CLIENT_SECRET, **data,
    })
    token = r.json()
    if "access_token" not in token:
        raise RuntimeError(f"TikTok token error: {token}")
    # Access tokens last a day, refresh tokens a year: store when each runs out
    token["expires_at"] = time.time() + token["expires_in"]
    token["refresh_expires_at"] = time.time() + token["refresh_expires_in"]
    return token


def _tiktok_access_token(token_path):
    if not os.path.exists(token_path):
        raise RuntimeError(f"No TikTok login at {token_path}, run: python -m modules.uploader login tiktok <channel>")
    with open(token_path) as f:
        token = json.load(f)
    if token["expires_at"] - 300 < time.time():
        if token["refresh_expires_at"] < time.time():
            raise RuntimeError("TikTok login expired, run the login again")
        token = _tiktok_token_request({"grant_type": "refresh_token", "refresh_token": token["refresh_token"]})
        _save_json(token_path, token)
    return token["access_token"]


def _tiktok_call(path, access_token, body):
    r = requests.post(f"{TIKTOK_API}{path}", json=body, timeout=60, headers={
        "Authorization": f"Bearer {access_token}", "Content-Type": "application/json; charset=UTF-8",
    })
    reply = r.json()
    if reply.get("error", {}).get("code") != "ok":
        raise RuntimeError(f"TikTok {path} failed: {reply.get('error')}")
    return reply["data"]


def upload_tiktok(video_path, caption, cfg, cover_ms=None):
    """Direct-post one video and return its publish_id. cover_ms picks the cover frame."""
    access_token = _tiktok_access_token(_token_path(cfg["token"]))
    privacy = cfg.get("privacy", "SELF_ONLY")
    # TikTok requires reading the creator's allowed privacy levels before every post
    creator = _tiktok_call("/post/publish/creator_info/query/", access_token, {})
    if privacy not in creator.get("privacy_level_options", []):
        raise RuntimeError(f"TikTok does not allow privacy {privacy} here, options: {creator.get('privacy_level_options')}")

    size = os.path.getsize(video_path)
    if size <= TIKTOK_SINGLE_CHUNK_MAX:
        chunk_size, chunk_count = size, 1
    else:
        # The last chunk absorbs the remainder, so the count rounds down
        chunk_size, chunk_count = TIKTOK_CHUNK, size // TIKTOK_CHUNK
    post_info = {"title": caption[:2200], "privacy_level": privacy,
                 "disable_duet": False, "disable_comment": False, "disable_stitch": False}
    if cover_ms is not None:
        post_info["video_cover_timestamp_ms"] = cover_ms
    init = _tiktok_call("/post/publish/video/init/", access_token, {
        "post_info": post_info,
        "source_info": {"source": "FILE_UPLOAD", "video_size": size,
                        "chunk_size": chunk_size, "total_chunk_count": chunk_count},
    })

    with open(video_path, "rb") as f:
        for i in range(chunk_count):
            start = i * chunk_size
            end = size - 1 if i == chunk_count - 1 else start + chunk_size - 1
            f.seek(start)
            data = f.read(end - start + 1)
            r = requests.put(init["upload_url"], data=data, timeout=300, headers={
                "Content-Type": "video/mp4", "Content-Length": str(len(data)),
                "Content-Range": f"bytes {start}-{end}/{size}",
            })
            r.raise_for_status()

    publish_id = init["publish_id"]
    deadline = time.time() + TIKTOK_STATUS_WAIT
    status = "PROCESSING_UPLOAD"
    while time.time() < deadline:
        status = _tiktok_call("/post/publish/status/fetch/", access_token, {"publish_id": publish_id})["status"]
        if status == "FAILED":
            raise RuntimeError(f"TikTok rejected the post {publish_id}")
        if status == "PUBLISH_COMPLETE":
            break
        time.sleep(10)
    # Still processing after the wait counts as posted: retrying would post it twice
    print(f"  TikTok: {status} ({publish_id})")
    return publish_id


def login_tiktok(cfg):
    if not (TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET and TIKTOK_REDIRECT_URI):
        sys.exit("Set TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET and TIKTOK_REDIRECT_URI in .env first")
    state = secrets.token_urlsafe(16)
    url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
        "client_key": TIKTOK_CLIENT_KEY, "scope": "user.info.basic,video.publish",
        "response_type": "code", "redirect_uri": TIKTOK_REDIRECT_URI, "state": state,
    })
    print(f"Open this link, log in to the TikTok account and approve:\n\n{url}\n")
    redirected = input("Paste the full URL your browser landed on: ").strip()
    params = urllib.parse.parse_qs(urllib.parse.urlparse(redirected).query)
    if params.get("state", [""])[0] != state or "code" not in params:
        sys.exit(f"That URL has no valid code: {params}")
    token = _tiktok_token_request({"grant_type": "authorization_code", "code": params["code"][0],
                                   "redirect_uri": TIKTOK_REDIRECT_URI})
    _save_json(_token_path(cfg["token"]), token)
    print(f"Logged in to TikTok. Saved to {cfg['token']}")


if __name__ == "__main__":
    schedule = load_schedule()
    if len(sys.argv) != 4 or sys.argv[1] != "login" or sys.argv[2] not in ("youtube", "tiktok"):
        sys.exit("Usage: python -m modules.uploader login [youtube|tiktok] <channel>")
    platform, channel = sys.argv[2], sys.argv[3]
    cfg = schedule.get(channel, {}).get(platform)
    if not cfg:
        sys.exit(f"schedule.json has no {platform} account for '{channel}'")
    login_youtube(cfg) if platform == "youtube" else login_tiktok(cfg)
