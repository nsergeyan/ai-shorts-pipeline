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
        ТВОЯ ЦЕЛЬ: Рассказать историю или факт про: {topic}.
        
        ВАЖНЕЙШЕЕ ПРАВИЛО - ЗАПРЕТ НА ЦИФРЫ:
    НИ ОДНОЙ АРАБСКОЙ ЦИФРЫ (0-9) НИКОГДА!
    Все числа ТОЛЬКО словами по-русски!
    
    Примеры ПРАВИЛЬНО:
    - "Эс Си Пи сто семьдесят три" 
    - "тысяча девятьсот девяносто первый"
    
    Примеры НЕПРАВИЛЬНО:
    - "Эс Си Пи 173" 
    - "1991 год" 
        ДАННЫЕ:
        {context[:10000]}

        РОЛЬ:
        Ты — профессиональный диктор TikTok-роликов для русскоязычной аудитории.
        **ОБЪЕМ: СТРОГО 130-160 СЛОВ**

        ВАЖНО - ПЕРЕВОД И ТРАНСЛИТЕРАЦИЯ:
        - Все английские названия переводи или транслитерируй на русский:
          * "Vault 108" → «Бункер сто восемь» или «Волт сто восемь»
          * "SCP-173" → «Эс Си Пи сто семьдесят три»
          * "Monolith" → «Монолит»
          * "Stalker" → «Сталкер»
          * "Foundation" → «Фонд»
        - Все числа пиши словами по-русски:
          * 1991 → «тысяча девятьсот девяносто первый»
          * 2077 → «две тысячи семьдесят седьмой»

        ОСНОВНЫЕ ПРАВИЛА:
        1. **ГОВОРИ ТОЛЬКО О: {topic}**
        2. **Без клише и вступлений**
        3. **Один сплошной абзац**
        4. **Если в данных нет информации о "{topic}" - СКАЖИ ЭТО ЧЕТКО**
        5. СЛОВАРНЫЙ ЗАПАС (VOCABULARY):
            Длина слов: Старайтесь избегать слов длиннее 3–4 слогов. Длинные причастия (например, «приближающийся») часто вызывают цифровой шум или «заикание».
            
            Уровень сложности: Ориентируйтесь на уровень 5–6 класса.
            Атмосфера: Вместо сложных терминов используйте базовые, «первобытные» слова: кровь, прах, тень, страх, кость, тьма, жар.
            
            Примеры адаптации:
            Плохо (Слишком сложно): «От колоссального гиганта исходило невыносимое тепловое излучение». (Слишком много слогов, ИИ может запнуться).
            
            Хорошо (Просто и мрачно): «Жар от гиганта был таким сильным, что плавил

        Пример правильного формата:
        ПЛОХО: "В бункере сто восемь скрывался жуткий секрет..."
        ХОРОШО: "В подземном комплексе под номером сто восемь проводились мрачные эксперименты..."
        
        **ОБЪЕМ: СТРОГО 130-160 СЛОВ**
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
        4. **LONGITUD:** ESTRICTAMENTE 110-140 PALABRAS.
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
        4. **LENGTH:** STRICTLY 90-100 WORDS.
        5. **FORMAT:** One single paragraph block.
        6. **VOCABULARY:** Use "Simple but Dark" language. 
           - Avoid words with more than 3 syllables where possible. 
           - Aim for a 7th-grade reading level, but keep the atmosphere heavy and serious.
           - *Bad:* "The heat was emanating from the giant."
           - *Good:* "The heat coming off the giant was enough to melt stone."

        Script:
        """
        script = _ollama_generate(prompt, temperature=0.75)

    return script, context[:20000]