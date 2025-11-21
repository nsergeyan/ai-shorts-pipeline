# main.py
import os
import argparse
from modules.script_generator import generate_script
from modules.gameplay_fetcher import fetch_random_gameplay
from modules.voice_generator import generate_voice
from modules.video_editor import merge_audio_video

def parse_args():
    p = argparse.ArgumentParser(description="AI YouTuber pipeline")
    p.add_argument("--offline", action="store_true", help="Do not download; reuse existing local .mp4")
    p.add_argument("--reuse-video", type=str, default=None, help="Path to a local gameplay .mp4 to use")
    p.add_argument("--channel", type=str, default="https://www.youtube.com/@RamenStyle/videos", help="Channel URL")
    p.add_argument("--keyword", type=str, default="ARC Raiders", help="Keyword to filter channel videos")
    p.add_argument("--no-voice", action="store_true", help="Skip voice generation (use existing narration.wav if present)")
    p.add_argument("--no-merge", action="store_true", help="Skip final video merge")
    p.add_argument("--speaker", type=str, default="Damien Black", help="XTTS speaker name")
    p.add_argument("--output", type=str, default="short_arcraiders.mp4", help="Final video filename")
    return p.parse_args()

def main():
    args = parse_args()

    print("\n🎙️  Generating narration script...")
    script = generate_script()
    print(script)

    print("\n🎮  Fetching gameplay clip...")
    video_path = fetch_random_gameplay(
        channel_url=args.channel,
        keyword=args.keyword,
        offline=args.offline,
        reuse_path=args.reuse_video,
    )
    if not os.path.exists(video_path):
        print(f"❌ Gameplay file not found: {video_path}")
        return

    if args.no_voice:
        audio_path = os.path.join("data", "audio", "narration.wav")
        print("\n🗣️  Voice generation skipped (--no-voice).")
        if not os.path.exists(audio_path):
            print(f"❌ No narration file at {audio_path}. Remove --no-voice or generate one first.")
            return
    else:
        print(f"\n🗣️  Generating voice with speaker: {args.speaker}")
        audio_path = generate_voice(script, speaker=args.speaker)

    if args.no_merge:
        print("\n⏭️  Merge skipped (--no-merge).")
        print("Video:", video_path)
        print("Audio:", audio_path)
        return

    print("\n🎬  Building final short...")
    final_path = merge_audio_video(video_path, audio_path, output_name=args.output)
    print(f"\n✨  Done! Final: {os.path.abspath(final_path)}")

if __name__ == "__main__":
    main()