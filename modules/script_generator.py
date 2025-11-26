import json
import re
import requests
from config import OLLAMA_MODEL, DEFAULT_GAME
from modules.web_search import get_deep_research

# ------------------------------------------------------------
# CLEANER FOR TTS — ELEVENLABS OPTIMIZED
# ------------------------------------------------------------
def clean_for_audio(text: str) -> str:
    """
    Final Polish: Removes specific characters that confuse ElevenLabs.
    """
    # 1. Standardize Dashes/Ellipses
    text = text.replace("—", ", ")
    text = text.replace("–", ", ")
    text = text.replace("…", ".")  # <--- Fixes the "Then…" issue
    text = text.replace("...", ".")

    # 2. Remove formatting
    text = re.sub(r'\*\*.*?\*\*', '', text)
    text = re.sub(r'\[.*?\]', '', text)
    text = re.sub(r'#\w+', '', text)

    # 3. Fix Double Punctuation (The "ROUND!.Tsarukyan" fix)
    text = text.replace("!.", "!")
    text = text.replace("?.", "?")
    text = text.replace("..", ".")

    # 4. Fix missing spaces after punctuation
    # This turns "ROUND!Tsarukyan" into "ROUND! Tsarukyan"
    text = re.sub(r'([.!?])([A-Z])', r'\1 \2', text)

    # 5. Fix "electric. can" (Lowercase start sentences)
    # Finds a period followed by space and lowercase, makes it uppercase
    def capitalize_match(m): return m.group(0).upper()

    text = re.sub(r'(?<=[.!?]\s)[a-z]', capitalize_match, text)

    # 6. Final Cleanup
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

STRUCTURE:
1. **Hook:** "Bro, this game is INSANE." (2 sentences)
2. **The Detail:** Explain exactly ONE mechanic or story beat in depth. (4-5 sentences)
3. **The Reaction:** Why is this so cool or scary? (3 sentences)
4. **Conclusion:** "You have to play this."

RULES:
1. Use casual spoken English.
2. Use contractions: you're, it's, can't, won't, didn't.
3. No fancy vocabulary.

EMOTION INSTRUCTIONS (CRITICAL):
- Do NOT use brackets like [excited].
- To show excitement, use CAPITAL LETTERS for the emphasized word (e.g., "This is INSANE").
- To show suspense, use "..." (e.g., "But then... it happened").
- To show shouting, use an exclamation mark !

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

STRUCTURE:
1. **The Hook (2 sentences):** Start with a shocking statement.
2. **The Struggle (3-4 sentences):** Give context. Explain why it was hard.
3. **The Climax (3-4 sentences):** Reveal the crazy detail or achievement using CAPITAL LETTERS.
4. **The Outro (2 sentences):** A final mind-blowing thought.

EMOTION INSTRUCTIONS:
- Use CAPITAL LETTERS to emphasize shocking words.
- Use "..." for dramatic pauses.
- Use "!" for energetic moments.

BANNED:
- "was born in", "he/she is known for", "dates", "timelines"

GOOD OPENERS:
- "[Name] did something nobody expected."
- "You probably know [Name], but not this."

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

STRUCTURE:
- **Hook:** "Did you know..."

EMOTION INSTRUCTIONS:
- Use CAPITAL LETTERS for mind-blowing words (e.g., "It was HUGE").
- Use "..." before revealing a fact.

OUTPUT: Only spoken words. No headers. No brackets. Do not say "Here is the script."

Write the script now:
"""
    return _ollama_generate(prompt)


# ------------------------------------------------------------
# TEST
# ------------------------------------------------------------
if __name__ == "__main__":
    print("=== TESTING BIO SCRIPT ===")
    # Example call
    script = generate_bio_script("Lamine Yamal")
    print(script)
    print(f"\nWord count: {len(script.split())}")