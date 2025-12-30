import random
import time

# IMPORT EVERYTHING FROM YOUR MAIN PIPELINE FILE
# If your original file is named main.py, keep this as:
from main import (
    LANGUAGE,
    MODEL_NAME,
    MY_NICHES,
    USE_YOUTUBE_DUPLICATE_CHECK,
    YOUTUBE_CHANNELS,
    generate_idea_from_niche,
    run_pipeline_for_idea,
    get_existing_topics_by_language,
    check_duplicate_topic
)

# ==============================================================================
# 1. MANUAL NICHE SELECTION
# ==============================================================================

# 🎯 CHOOSE YOUR NICHE HERE (EXACT STRING FROM MY_NICHES)
FORCED_NICHE = "Metro 2033 Universe"

# Safety check
if FORCED_NICHE not in MY_NICHES:
    raise ValueError(
        f"❌ Forced niche '{FORCED_NICHE}' is not in MY_NICHES.\n"
        f"Available niches: {MY_NICHES}"
    )

# ==============================================================================
# 2. MAIN EXECUTION
# ==============================================================================

if __name__ == "__main__":
    print("🚀 STARTING SINGLE-NICHE AI STUDIO")
    print(f"🌍 Language: {LANGUAGE.upper()}")
    print(f"🤖 Model: {MODEL_NAME}")
    print(f"🎯 FORCED NICHE: {FORCED_NICHE}")

    # Show YouTube duplicate check status
    if USE_YOUTUBE_DUPLICATE_CHECK:
        current_channel = YOUTUBE_CHANNELS.get(LANGUAGE, {})
        channel_id = current_channel.get("channel_id", "")
        username = current_channel.get("username", "")

        if channel_id or username:
            channel_name = username if username else channel_id
            print(f"📺 YouTube Duplicate Check: ENABLED ({channel_name})")
        else:
            print("⚠️ YouTube Duplicate Check: CONFIG MISSING")
    else:
        print("⏭️ YouTube Duplicate Check: DISABLED")

    # ==============================================================================
    # 3. ATTEMPT LOOP (AI STILL CHOOSES TOPIC)
    # ==============================================================================

    max_attempts = 10
    attempts = 0
    success = False

    while not success and attempts < max_attempts:
        attempts += 1
        print(f"\n=== 🎬 ATTEMPT {attempts}/{max_attempts} ===")

        # 🔮 AI PICKS THE TOPIC (BUT ONLY FROM THIS NICHE)
        plan = generate_idea_from_niche(FORCED_NICHE, LANGUAGE)

        if not plan:
            print("⚠️ AI failed to generate a plan. Retrying...")
            time.sleep(2)
            continue

        # 🛑 EXTRA DUPLICATE SAFETY
        if USE_YOUTUBE_DUPLICATE_CHECK:
            existing_topics = get_existing_topics_by_language(LANGUAGE)
            subject = plan.get("specific_subject", "")

            if check_duplicate_topic(subject, existing_topics):
                print(f"❌ DUPLICATE DETECTED: '{subject}' already exists.")
                print("🔄 Retrying with a new topic...")
                time.sleep(2)
                continue

        # ▶️ RUN FULL PIPELINE
        try:
            success = run_pipeline_for_idea(plan, FORCED_NICHE)

            if success:
                print("\n🎉 SUCCESS! Video created for niche:")
                print(f"🏷️ {FORCED_NICHE}")
            else:
                print("❌ Pipeline failed validation. Retrying...")
                time.sleep(3)

        except Exception as e:
            print(f"❌ Pipeline crashed: {e}")
            print("🔄 Retrying...")
            time.sleep(3)

    # ==============================================================================
    # 4. FINAL STATUS
    # ==============================================================================

    if not success:
        print("\n💥 FAILED! Could not create a video after all attempts.")
        print("💡 Try increasing attempts or checking logs.")