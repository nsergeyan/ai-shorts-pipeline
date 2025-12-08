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
            timeout=240
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
        ТВОЯ ЦЕЛЬ: Рассказать историю или  факт про: {topic}.

        ДАННЫЕ:
        {context[:10000]}

        РОЛЬ:
        Ты — профессиональный диктор TikTok-роликов.  
        Сейчас ты готовишь текст ДЛЯ ОЗВУЧКИ В ELEVENLABS.  
        ElevenLabs полностью ломается и выдаёт роботский голос на любых арабских цифрах 0-9.  
        Поэтому в твоём ответе НЕ ДОЛЖНО БЫТЬ НИ ОДНОЙ ЦИФРЫ — вообще нигде и никогда.  
        Все годы, даты, проценты, номера, этажи, версии, количества — только словами и только по-русски.  
        Примеры:  
        - вместо 1991 → «тысяча девятьсот девяносто первый»  
        - вместо 95% → «девяносто пять процентов»  
        - вместо SCP-096 → «Эс Си Пи ноль девяносто шесть»  
        - вместо 13-й → «тринадцатый»

        ГЛАВНОЕ ПРАВИЛО:
        **ГОВОРИ ТОЛЬКО О: {topic}.**
        **ОБЪЕМ: СТРОГО 100-130 СЛОВ.**

        СТИЛЬ:
        1. **ЗАПРЕТ НА КЛИШЕ:** 
           - ЗАПРЕЩЕНО начинать с "Многие не знают", "А вы знали?", "Интересный факт", "Давайте разберем".
           - ЗАПРЕЩЕНО говорить очевидные вещи с пафосом.
        2. **НАЧАЛО:** Начни сразу с утверждения или описания характера. 
           - *Плохо:* "Многие не знают, что Сэр Пенциос одинок."
           - *Хорошо:* "За маской безумного изобретателя Сэра Пенциоса скрывается глубокое человеческое одиночество."
        3. **ТОН:** в зависимости од темы Спокойный или активный, аналитический,  но не скучный.
        4. **ФОРМАТ:** Один сплошной абзац.

        Текст сценария (Русский):
        """
        # Slightly higher temp allows for better sentence structure diversity
        script = _ollama_generate(prompt, temperature=0.75)

    # ======================= SPANISH MODE (DIRECT STORYTELLING) ==========================
    elif language == "es":
        prompt = f"""
        OBJETIVO: Narrar una historia inmersiva y oscura sobre: {topic}.

        DATOS:
        {context[:20000]}

        REGLAS ANTI-CLICHÉ:
        1. **NO USES FRASES DE RELLENO:** 
           - PROHIBIDO empezar con "¿Sabías que...?", "Mucha gente ignora...", "Te contaré la historia de...".
           - Empieza DIRECTAMENTE con la acción, la atmósfera o el dato crudo.
        2. **EJEMPLO DE ESTILO:**
           - *Mal:* "¿Sabías que Nemesis persigue a los protagonistas?"
           - *Bien:* "Creado con el único propósito de eliminar a los supervivientes, Nemesis representa la cúspide del armamento bioorgánico, una fuerza imparable que no conoce el miedo ni el dolor."
        3. **TONO:** Narrador de misterio o terror. Serio, profundo y elegante.
        4. **LONGITUD:** ESTRICTAMENTE 120-140 PALABRAS.
        5. **FORMATO:** Un solo párrafo.

        Guion (Español):
        """
        script = _ollama_generate(prompt, temperature=0.75)

    # ======================= ENGLISH MODE (DIRECT STORYTELLING) ==========================
    else:
        prompt = f"""
        TARGET: Tell a compelling narrative about {topic}.

        DATA:
        {context[:20000]}

        STYLE RULES (NO CLICKBAIT):
        1. **BAN THE HOOKS:** 
           - DO NOT start with "Did you know", "Most people miss", "Here is a fact".
           - Just start telling the story immediately.
        2. **DIRECT NARRATIVE:** 
           - *Bad:* "Let me tell you about Artyom's childhood."
           - *Good:* "Artyom was born just days before the bombs fell, making him one of the last children of the old world."
        3. **TONE:** Storyteller / Lore Keeper. Not a YouTuber.
        4. **LENGTH:** STRICTLY 90-110 WORDS.
        5. **FORMAT:** One single paragraph block.

        Script:
        """
        script = _ollama_generate(prompt, temperature=0.75)

    return script, context[:20000]