import json
import re
import requests
from config import OLLAMA_MODEL, DEFAULT_GAME
from modules.web_search import get_deep_research

# ------------------------------------------------------------
# CLEANER FOR TTS — ELEVENLABS OPTIMIZED (FAST TIKTOK STYLE)
# ------------------------------------------------------------
def clean_for_audio(text: str) -> str:
    """
    Final Polish for ElevenLabs:
    - Removes formatting
    - Normalizes punctuation
    - Avoids long dramatic pauses (no real ellipses)
    """
    # 0. Normalize newlines
    text = text.replace("\n", " ")

    # 1. Standardize dashes / ellipses to SHORT pauses
    text = text.replace("—", ", ")
    text = text.replace("–", ", ")
    # Ellipses create huge pauses in TTS; convert to comma (short pause)
    text = text.replace("…", ", ")
    text = text.replace("...", ", ")

    # 2. Remove / simplify formatting (keep words)
    # **bold** -> bold
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    # [label](url) -> label
    text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text)
    # [note] -> ""
    text = re.sub(r'\[.*?\]', '', text)
    # #tags -> ""
    text = re.sub(r'#\w+', '', text)

    # 3. Fix double punctuation that can confuse prosody
    text = text.replace("!.", "!")
    text = text.replace("?.", "?")
    text = re.sub(r'\.{2,}', '.', text)   # any remaining "...." -> "."
    text = re.sub(r',,+', ',', text)

    # 4. Ensure space after punctuation (avoids "ROUND!Tsarukyan")
    text = re.sub(r'([.!?])([A-Za-z])', r'\1 \2', text)

    # 5. Capitalize sentence starts after punctuation if lowercase
    def capitalize_match(m: re.Match) -> str:
        return m.group(0).upper()

    text = re.sub(r'(?<=[.!?]\s)[a-z]', capitalize_match, text)

    # 6. Final whitespace cleanup
    text = re.sub(r'\s+', ' ', text).strip()

    return text


# ------------------------------------------------------------
# OLLAMA HANDLER
# ------------------------------------------------------------
def _ollama_generate(prompt: str) -> str:
    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": True},
            stream=True,
            timeout=90,
        )
        response.raise_for_status()
    except Exception as e:
        print(f"⚠️ Ollama request failed: {e}")
        return "Oops, I couldn't generate content right now."

    output = ""

    for line in response.iter_lines():
        if not line:
            continue
        try:
            obj = json.loads(line.decode("utf-8"))
        except:
            continue

        if "response" in obj:
            output += obj["response"]

        if obj.get("done"):
            break

    # Clean here so TTS gets a TikTok‑optimized line
    return clean_for_audio(output)


# ------------------------------------------------------------
# PROMPT: GAME SCRIPT
# ------------------------------------------------------------
def generate_script(game: str = DEFAULT_GAME) -> str:
    prompt = f"""
You are writing a TikTok voiceover script.

TOPIC: {game}

TASK:
Write a high-energy script. Target length: 160-180 words.
Write it as ONE paragraph, no line breaks. Keep the pacing fast.

STRUCTURE:
1. Hook: Start with "Bro, this game is INSANE." and add 1 more hook sentence.
2. The Detail: Explain exactly ONE mechanic or story beat in depth. (4-5 short sentences)
3. The Reaction: Why is this so cool or scary? (3 punchy sentences)
4. Conclusion: End with "You have to play this."

RULES:
1. Use casual spoken English.
2. Use contractions: you're, it's, can't, won't, didn't.
3. No fancy vocabulary.

EMOTION INSTRUCTIONS (CRITICAL):
- Do NOT use brackets like [excited].
- Use CAPITAL LETTERS to emphasize hype words (e.g., "This is INSANE").
- Keep the pacing FAST. Avoid long dramatic pauses.
- Use "..." only very rarely and NEVER at the end of a sentence.
- Use "!" when shouting.

BANNED WORDS:
- "in this video", "we're going to", "let me tell you", "without further ado"

OUTPUT: Only spoken words. No headers. No brackets. Do not say "Here is the script."

Write the script now:
"""
    return _ollama_generate(prompt)


# ------------------------------------------------------------
# PROMPT: BIO SCRIPT
# ------------------------------------------------------------
def generate_bio_script(name: str) -> str:
    context = get_deep_research(f"{name} shocking facts records", max_results=3)

    prompt = f"""
You are writing a TikTok voiceover about a person.

PERSON: {name}

RESEARCH:
{context}

TASK:
Write a detailed, 140-word storytelling script.
Do not write a short summary. Tell a full story.
Write as ONE paragraph, no line breaks, fast pacing.

STRUCTURE:
1. The Hook (2 sentences): Start with a shocking statement.
2. The Struggle (3-4 sentences): Give context. Explain why it was hard.
3. The Climax (3-4 sentences): Reveal the crazy detail or achievement using CAPITAL LETTERS.
4. The Outro (2 sentences): A final mind-blowing thought.

EMOTION INSTRUCTIONS:
- Use CAPITAL LETTERS to emphasize shocking words.
- Avoid long dramatic pauses. Use "..." very rarely and keep talking after it.
- Use "!" for energetic moments.

BANNED:
- "was born in", "he/she is known for", "dates", "timelines"

GOOD OPENERS:
- "{name} did something nobody expected."
- "You probably know {name}, but not this."

OUTPUT: Only spoken words. No headers. No brackets. Do not say "Here is the script."

Write the script now:
"""
    return _ollama_generate(prompt)


# ------------------------------------------------------------
# PROMPT: FACTS SCRIPT
# ------------------------------------------------------------
def generate_facts_script(topic: str) -> str:
    context = get_deep_research(f"{topic} mind blowing unknown facts", max_results=3)

    prompt = f"""
You are writing a TikTok facts script.

TOPIC: {topic}

RESEARCH:
{context}

TASK:
Write a 140-word script sharing mind-blowing facts.
Write as ONE paragraph, no line breaks. Fast, continuous delivery.

STRUCTURE:
- Hook: Start with "Did you know that..." and IMMEDIATELY continue into the crazy fact in the SAME sentence. No big pause after the hook.

EMOTION INSTRUCTIONS:
- Use CAPITAL LETTERS for mind-blowing words (e.g., "It was HUGE").
- Keep the pacing tight. Avoid dramatic "..." pauses.
- Use "!" when something is shocking.

OUTPUT: Only spoken words. No headers. No brackets. Do not say "Here is the script."

Write the script now:
"""
    return _ollama_generate(prompt)


# ------------------------------------------------------------
# TEST
# ------------------------------------------------------------
if __name__ == "__main__":
    print("=== TESTING BIO SCRIPT ===")
    script = generate_bio_script("Lamine Yamal")
    print(script)
    print(f"\nWord count: {len(script.split())}")