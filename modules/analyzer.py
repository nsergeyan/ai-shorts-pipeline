import time

from google import genai

client = genai.Client(api_key="AIzaSyBovTpWVnz7JU2jeiusfRlnWYWb-x8vgEw")

# Upload the video file
uploaded_file = client.files.upload(
    file="/Users/nareksergeyan/YOutuber/data/final/Short_Drones_have_a_built-in_trauma_warning_system_called_PRIOR_HAZARD_18.mp4"
)
script_text = "Gege Akutami is the king of writing out of pure spite. Originally Gege wanted Yuji to visit a Japanese gambling parlor but the Shonen Jump editors shut it down because they said gambling was a bad influence for a kids magazine. So what did Gege do? He did not just drop it, he leveled up. He created Kinji Hakari, a character whose entire power is literally a rigged slot machine. His Domain Expansion forces his opponents to sit through a literal gambling mini game and if he hits the Jackpot he gets infinite cursed energy and becomes immortal for four minutes. The editors could not ban it this time because the gambling was the plot. Gege basically said you will not let me show a casino? Fine, I will make gambling the strongest power in the entire series. Absolute madman behavior. Follow for more JJK secrets!"

print(f"Uploaded file: {uploaded_file.name}")
# Step 2: Wait for the file to become ACTIVE
file_info = client.files.get(name=uploaded_file.name)
while file_info.state != "ACTIVE":  # <-- changed from .status to .state
    print(f"File state: {file_info.state}, waiting...")
    time.sleep(2)
    file_info = client.files.get(name=uploaded_file.name)

print("File is ACTIVE ✅")
prompt = f"""
You are acting as a strict short-form content editor.

You ONLY judge what is clearly visible in the video.
Do NOT assume, infer, or creatively interpret missing visuals.
If something is not explicitly shown on screen, treat it as NOT present.

Script excerpt:
\"\"\"{script_text}\"\"\"

Evaluation Rules:

1. Core Visual Proof Check
- Identify the PRIMARY visual claim in the script.
- If the video does NOT clearly show that claim, the relevance_score MUST be 5 or lower.

2. Visual-Script Alignment (1–10)
- 1 = visuals contradict or fail to show the script’s key claim
- 5 = loosely related but missing core visual proof
- 10 = directly and clearly demonstrates the exact concept being discussed

3. First 2-Second Hook (1–10)
- Judge only what visually happens in the first 2 seconds.
- Motion, contrast, surprise, intensity.
- Do NOT reward narration alone.

4. Technical Quality (1–10)
- Framing, lighting, clarity, pacing, visual polish.
- Score lower if visuals are repetitive, generic, or misleading.

5. Posting Decision
- "post" ONLY if:
  - relevance_score >= 8
  - hook_score >= 7
  - technical_score >= 8
- Otherwise:
  - "revise" if fixable
  - "reject" if fundamentally misaligned

Respond ONLY with valid JSON:

{{
  "relevance_score": <1-10>,
  "hook_score": <1-10>,
  "technical_score": <1-10>,
  "decision": "post" | "revise" | "reject"
}}
"""

# Step 3: Use the file in your generation request
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=[
        uploaded_file,
        prompt,
    ]
)

# Step 4: Print AI response
print(response.text)



