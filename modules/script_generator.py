import requests
import re
from modules.web_search import get_deep_research

# MODEL
OLLAMA_MODEL = "gemma2:27b"


def clean_script_output(text: str) -> str:
    if not text: return ""
    text = re.sub(r'^\s*["`]{3,}\s*', '', text)
    text = re.sub(r'\s*["`]{3,}\s*$', '', text)
    text = text.replace("**", "").replace("##", "").replace("Title:", "")
    text = re.sub(r'^(Here is|Sure,|In this video|Based on).*?(\n|$)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'[^\w\s,.\-!?()"\':;@%]', '', text)
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    return " ".join(lines)


def _ollama_generate(prompt: str, temperature: float) -> str:
    try:
        resp = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_ctx": 8192
                }
            },
            timeout=120
        )
        return clean_script_output(resp.json().get("response", ""))
    except Exception as e:
        print(f"⚠️ Error: {e}")
        return ""


def generate_dynamic_script(topic: str, research_query: str, language: str = "en") -> str:
    print(f"🧠 Researching '{research_query}'...")
    context = get_deep_research(research_query, lang="en", max_results=2)
    if not context or len(context) < 100:
        context = "No details found."

    print(f"✍️ Writing Narrative Script for '{topic}' ({language})...")

    # ======================= RUSSIAN MODE (DIRECT STORYTELLING) ==========================
    if language == "ru":
        prompt = f"""
        ТВОЯ ЦЕЛЬ: Рассказать историю или психологический факт про: {topic}.

        ДАННЫЕ:
        {context[:8000]}

        РОЛЬ:
        Ты рассказчик (Narrator). Ты не блогер, ты не хайпишь. Ты просто рассказываешь суть.

        ГЛАВНОЕ ПРАВИЛО:
        **ГОВОРИ ТОЛЬКО О: {topic}.**

        СТИЛЬ (NO CRINGE, NO CLICHÉS):
        1. **ЗАПРЕТ НА КЛИШЕ:** 
           - ЗАПРЕЩЕНО начинать с "Многие не знают", "А вы знали?", "Интересный факт", "Давайте разберем".
           - ЗАПРЕЩЕНО говорить очевидные вещи с пафосом.
        2. **НАЧАЛО:** Начни сразу с утверждения или описания характера. 
           - *Плохо:* "Многие не знают, что Сэр Пенциос одинок."
           - *Хорошо:* "За маской безумного изобретателя Сэра Пенциоса скрывается глубокое человеческое одиночество."
        3. **ТОН:** Спокойный, аналитический,  но не скучный.
        4. **ФОРМАТ:** Один сплошной абзац.

        Текст сценария (Русский):
        """
        # Slightly higher temp allows for better sentence structure diversity
        script = _ollama_generate(prompt, temperature=0.75)

    # ======================= SPANISH MODE (DIRECT STORYTELLING) ==========================
    elif language == "es":
        prompt = f"""
        OBJETIVO: Narrar una historia profunda sobre: {topic}.

        DATOS:
        {context[:8000]}

        REGLAS ANTI-CLICHÉ:
        1. **NO USES FRASES DE RELLENO:** 
           - PROHIBIDO empezar con "¿Sabías que...?", "Mucha gente ignora...", "Aquí hay un dato curioso".
           - Empieza DIRECTAMENTE con la narrativa.
        2. **EJEMPLO:**
           - *Mal:* "¿Sabías que Alastor era un asesino?"
           - *Bien:* "Antes de convertirse en el Demonio de la Radio, Alastor ya aterrorizaba las calles de Nueva Orleans..."
        3. **TONO:** Narrativo, serio, elegante.
        4. **FORMATO:** Un solo párrafo.

        Guion (Español):
        """
        script = _ollama_generate(prompt, temperature=0.75)

    # ======================= ENGLISH MODE (DIRECT STORYTELLING) ==========================
    else:
        prompt = f"""
        TARGET: Tell a compelling narrative about {topic}.

        DATA:
        {context[:8000]}

        STYLE RULES (NO CLICKBAIT):
        1. **BAN THE HOOKS:** 
           - DO NOT start with "Did you know", "Most people miss", "Here is a fact".
           - Just start telling the story immediately.
        2. **DIRECT NARRATIVE:** 
           - *Bad:* "Let me tell you about Artyom's childhood."
           - *Good:* "Artyom was born just days before the bombs fell, making him one of the last children of the old world."
        3. **TONE:** Storyteller / Lore Keeper. Not a YouTuber.
        4. **FORMAT:** One single paragraph block.

        Script:
        """
        script = _ollama_generate(prompt, temperature=0.75)

    return script