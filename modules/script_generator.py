# modules/script_generator.py

import requests
import json
from config import OLLAMA_MODEL, DEFAULT_GAME

def generate_script(game=DEFAULT_GAME):
    prompt = f"""
    Write a 60-second YouTube narration for gameplay from {game}.
    Make it exciting, punchy, and natural.
    """

    response = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": True
        },
        stream=True
    )

    full_text = ""

    for line in response.iter_lines():
        if not line:
            continue
        try:
            obj = json.loads(line.decode("utf-8"))
        except:
            continue

        if "response" in obj and obj["response"]:
            full_text += obj["response"]

        if obj.get("done", False):
            break

    return full_text.strip()