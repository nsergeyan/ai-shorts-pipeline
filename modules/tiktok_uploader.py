"""Post videos to TikTok by driving TikTok Studio in a real Chrome window (Playwright).

One-time login, kept in tokens/tiktok_browser/ (a Chrome profile only this tool uses):
    python -m modules.tiktok_uploader login

A second account gets its own profile folder (schedule.json "profile" of that channel):
    python -m modules.tiktok_uploader login tokens/tiktok_browser_sports

Test post of any file:
    python -m modules.tiktok_uploader post <video.mp4> "caption #tags" [public|private] [cover.png] [2026-11-22T15:00]

TikTok changes its page now and then. When a step fails, a screenshot of the page is saved
to data/jobs/logs/ so the selector below can be fixed.
"""
import datetime
import os
import sys

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from config import BASE_DIR, DATA_DIR

PROFILE_DIR = os.path.join(BASE_DIR, "tokens", "tiktok_browser")
SHOT_DIR = os.path.join(DATA_DIR, "jobs", "logs")
UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload"
UPLOAD_WAIT_MS = 10 * 60 * 1000  # processing a 40MB short can take a few minutes

# Text TikTok shows in the "Who can watch this video" menu
PRIVACY_LABELS = {"public": "Everyone", "friends": "Friends", "private": "Only you"}


def _open(p, profile=None):
    # Real Chrome (channel="chrome") and a visible window: TikTok blocks headless browsers more often
    return p.chromium.launch_persistent_context(
        os.path.join(BASE_DIR, profile) if profile else PROFILE_DIR, channel="chrome", headless=False,
        viewport={"width": 1400, "height": 900}, args=["--disable-blink-features=AutomationControlled"],
    )


def _screenshot(page, name):
    os.makedirs(SHOT_DIR, exist_ok=True)
    path = os.path.join(SHOT_DIR, f"tiktok_{name}_{datetime.datetime.now():%Y%m%d_%H%M%S}.png")
    try:
        page.screenshot(path=path, full_page=True)
        print(f"  TikTok: screenshot saved to {path}")
    except Exception:
        pass


def login(profile=None):
    with sync_playwright() as p:
        ctx = _open(p, profile)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.tiktok.com/login")
        input("Log in to the TikTok account in the Chrome window, then press Enter here...")
        page.goto(UPLOAD_URL)
        page.wait_for_timeout(3000)
        ok = "login" not in page.url
        print("Logged in, session saved." if ok else f"Still not logged in (at {page.url}), try again.")
        ctx.close()


# Popups that cover the form: the feature tour and the cookie banner
POPUP_BUTTONS = ["Got it", "Decline optional cookies", "Not now", "Skip"]


def _dismiss_popups(page):
    for name in POPUP_BUTTONS:
        button = page.get_by_role("button", name=name, exact=True)
        try:
            if button.first.is_visible():
                button.first.click(timeout=3000)
                page.wait_for_timeout(500)
        except Exception:
            pass
    # A tour overlay without a button still blocks clicks, so take it off the page
    page.evaluate("document.querySelector('#react-joyride-portal')?.remove()")


def _set_caption(page, caption):
    editor = page.locator('div[contenteditable="true"]').first
    editor.wait_for(timeout=60_000)
    editor.click()
    # TikTok pre-fills the file name: select all and replace it
    page.keyboard.press("Meta+A")
    page.keyboard.press("Backspace")
    for word in caption.split(" "):
        page.keyboard.type(word, delay=20)
        if word.startswith("#"):
            # Let the hashtag suggestion box open, then close it so it doesn't swallow the next word
            page.wait_for_timeout(800)
            page.keyboard.press("Escape")
        page.keyboard.type(" ")


def _set_privacy(page, privacy):
    label = PRIVACY_LABELS[privacy]
    # The menu shows the current choice ("Everyone" by default); open it and pick ours
    current = page.get_by_text(PRIVACY_LABELS["public"], exact=True).first
    if privacy == "public" and current.is_visible():
        return
    current.click()
    page.get_by_text(label, exact=True).last.click()
    page.wait_for_timeout(500)


def _set_cover(page, image_path):
    """Edit cover -> Upload cover -> Save. A failure keeps TikTok's own cover instead of stopping the post."""
    try:
        page.get_by_text("Edit cover", exact=True).first.click(timeout=30_000)
        page.wait_for_timeout(2000)
        # The "Upload cover" button opens a hidden image input inside the cover editor
        page.locator('input[type="file"][accept*="image"]').first.set_input_files(image_path)
        page.wait_for_timeout(4000)
        page.get_by_role("button", name="Save", exact=True).click(timeout=15_000)
        page.get_by_text("Edit cover", exact=True).first.wait_for(timeout=30_000)
        print("  TikTok: cover set")
    except Exception as e:
        print(f"  TikTok: cover not set ({e.__class__.__name__}), keeping TikTok's own cover")
        _screenshot(page, "cover")
        # Leave the editor without saving so the post can go on
        try:
            page.get_by_role("button", name="Cancel", exact=True).first.click(timeout=3000)
        except Exception:
            pass


def _pick_day(page, when):
    """Click the day in the open calendar. It shows six weeks, so the next month's first days are
    there too: the month starts at the first "1", the next month at the second "1"."""
    days = page.locator("button.DatePicker__day")
    labels = [t.strip() for t in days.all_inner_texts()]
    firsts = [i for i, t in enumerate(labels) if t == "1"]
    today = datetime.date.today()
    if (when.year, when.month) == (today.year, today.month):
        start = firsts[0]
    elif len(firsts) > 1:
        start = firsts[1]
    else:
        raise RuntimeError(f"{when:%b %d} is not in the open calendar")
    days.nth(start + when.day - 1).click()


def _set_schedule(page, when):
    """Pick "Schedule" and set date + time, then read both back so a misclick never posts at the wrong time."""
    page.get_by_text("Schedule", exact=True).first.click()
    page.wait_for_timeout(1000)
    _dismiss_popups(page)

    date_box = page.locator('[aria-label="Select date"]')
    date_box.click()
    page.wait_for_timeout(800)
    _pick_day(page, when)
    page.wait_for_timeout(800)

    time_box = page.locator('[aria-label="Select time"]')
    time_box.click()
    page.wait_for_timeout(800)
    columns = page.locator(".TimePicker__column")
    columns.nth(0).locator("button.TimePicker__item", has_text=f"{when.hour:02d}").first.click()
    columns.nth(1).locator("button.TimePicker__item", has_text=f"{when.minute:02d}").first.click()
    page.keyboard.press("Escape")
    page.wait_for_timeout(800)

    shown_date, shown_time = date_box.inner_text().strip(), time_box.inner_text().strip()
    want_date, want_time = f"{when:%b} {when.day}, {when.year}", f"{when:%H:%M}"
    if (shown_date, shown_time) != (want_date, want_time):
        raise RuntimeError(f"schedule shows {shown_date} {shown_time}, wanted {want_date} {want_time}")
    print(f"  TikTok: scheduled for {want_date} {want_time}")


def post(video_path, caption, privacy="public", cover_path=None, schedule_at=None, profile=None):
    """Upload one video and wait until TikTok confirms it. schedule_at (local datetime, 15 min
    to 10 days ahead, minutes in steps of 5) makes TikTok publish it later by itself."""
    with sync_playwright() as p:
        ctx = _open(p, profile)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        step = "open"
        try:
            page.goto(UPLOAD_URL, wait_until="domcontentloaded")
            if "login" in page.url:
                raise RuntimeError("not logged in, run: python -m modules.tiktok_uploader login")

            step = "file"
            page.locator('input[type="file"]').first.set_input_files(video_path)

            step = "caption"
            # The tour opens a moment after the file is added
            page.wait_for_timeout(3000)
            _dismiss_popups(page)
            _set_caption(page, caption[:2200])

            if cover_path and os.path.exists(cover_path):
                step = "cover"
                _dismiss_popups(page)
                _set_cover(page, cover_path)

            if schedule_at:
                step = "schedule"
                _dismiss_popups(page)
                _set_schedule(page, schedule_at)

            step = "privacy"
            _dismiss_popups(page)
            _set_privacy(page, privacy)

            step = "upload"
            # The Post button stays disabled until TikTok has the whole file
            post_button = page.locator('button[data-e2e="post_video_button"]')
            post_button.wait_for(timeout=UPLOAD_WAIT_MS)
            page.wait_for_function(
                "b => b && !b.disabled && b.getAttribute('aria-disabled') !== 'true'",
                arg=post_button.element_handle(), timeout=UPLOAD_WAIT_MS,
            )

            step = "post"
            _dismiss_popups(page)
            post_button.click()
            # Some accounts get a "continue to post?" check dialog first
            try:
                page.get_by_role("button", name="Post now").click(timeout=5000)
            except PlaywrightTimeout:
                pass

            step = "confirm"
            # After posting, TikTok Studio moves on to the content list
            page.wait_for_url("**/tiktokstudio/content**", timeout=120_000)
            print(f"  TikTok: {'scheduled' if schedule_at else 'posted'} ({privacy})")
            return True
        except Exception as e:
            print(f"  TikTok: failed at step '{step}': {e}")
            _screenshot(page, step)
            raise
        finally:
            ctx.close()


if __name__ == "__main__":
    if sys.argv[1:2] == ["login"]:
        # Optional profile folder for a second account, e.g. tokens/tiktok_browser_sports
        login(sys.argv[2] if len(sys.argv) > 2 else None)
    elif sys.argv[1:2] == ["post"] and len(sys.argv) >= 4:
        args = sys.argv[2:] + [None] * 4
        when = datetime.datetime.fromisoformat(args[4]) if args[4] else None
        post(args[0], args[1], args[2] or "private", args[3] or None, when)
    else:
        sys.exit("Usage: python -m modules.tiktok_uploader login [profile_dir] | "
                 "post <video> <caption> [public|private] [cover.png] [2026-11-22T15:00]")
