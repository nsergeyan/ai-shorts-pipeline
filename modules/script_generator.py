import requests
import re
from config import OLLAMA_MODEL
from modules.web_search import get_deep_research

def clean_for_audio(text: str) -> str:
    text = text.replace("\n", " ").replace("*", "").replace("#", "")
    text = text.replace("...", ".").replace("..", ".")
    return re.sub(r'\s+', ' ', text).strip()

def _ollama_generate(prompt: str, temperature: float = 0.7) -> str:
    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": temperature}
            },
            timeout=120
        )
        if response.status_code != 200: return "Error."
        return clean_for_audio(response.json()["response"])
    except Exception as e:
        print(f"⚠️ Ollama error: {e}")
        return "Error generating script."

def generate_dynamic_script(topic: str, research_query: str, language: str = "en") -> str:
    print(f"🧠 Researching '{research_query}'...")
    context = get_deep_research(research_query, max_results=3)

    if language == "ru":
        prompt = f"""
You are a Russian YouTube Shorts narrator.
TOPIC: {topic}
SOURCE MATERIAL:
{context}

TASK: Write a viral script in RUSSIAN (на русском языке).
STRUCTURE:
1. Hook: Start with "А ты знал, что..." or "Это просто ЖЕСТЬ...".
2. Body: Explain the facts from the research. Use energetic, casual Russian.
3. Climax: The most shocking detail.
4. Outro: "Подпишись!"

RULES:
- Write ONLY in Cyrillic (Russian).
- No English words unless proper names.
- Keep it under 150 words.
- One single paragraph.
"""
    else:
        prompt = f"""
You are a YouTube Shorts narrator.
TOPIC: {topic}
SOURCE MATERIAL:
{context}

TASK: Write a high-energy viral script (140-160 words).
STRUCTURE:
1. Hook: "Did you know that..." or "This is INSANE."
2. Body: Explain the facts/lore.
3. Climax: The most shocking detail.
4. Outro: "Subscribe for more!"

RULES:
- Natural spoken English.
- One single paragraph.
"""

    return _ollama_generate(prompt, temperature=0.7)