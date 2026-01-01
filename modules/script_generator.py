import re
import os
from google import genai
from google.genai import types

# ==============================================================================
# 1. CONFIGURATION
# ==============================================================================

GEMINI_API_KEY = "AIzaSyALxc3KaH3Bkt-zvV88guhk7vOxOhzZp_I"
#all keys
#AIzaSyBovTpWVnz7JU2jeiusfRlnWYWb-x8vgEw
#AIzaSyDTsvk17wwE-r-YEjwsI_HhAOsXh7rzn4Q
#AIzaSyALxc3KaH3Bkt-zvV88guhk7vOxOhzZp_I


# SWITCH TO 2.5 FLASH: High quota, very stable
GEMINI_MODEL = "gemini-2.5-flash"

client = genai.Client(api_key=GEMINI_API_KEY)

def clean_script_output(text: str) -> str:
    """Clean and format the script output for text-to-speech."""
    if not text:
        return ""
    text = re.sub(r'^\s*["`]{3,}\s*', '', text)
    text = re.sub(r'\s*["`]{3,}\s*$', '', text)
    text = text.replace("**", "").replace("##", "").replace("Title:", "")
    text = re.sub(r'^(Here is|Sure,|In this video|Based on|Narrative script|According to).*?(\n|$)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'[^\w\s,.\-!?()"\':;@%]', '', text)
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    return " ".join(lines)

def _gemini_generate(prompt: str, temperature: float = 0.7) -> str:
    """Calls Gemini 2.5 Flash with Grounding to fix 'Invisible Watcher' knowledge."""
    try:
        google_search_tool = types.Tool(
            google_search =types.GoogleSearch()
        )

        config = types.GenerateContentConfig(
            temperature=temperature,
            tools=[google_search_tool],
            max_output_tokens=5000,
        )

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=config
        )

        if response and response.text:
            return clean_script_output(response.text)
        else:
            return ""

    except Exception as e:
        if "429" in str(e):
            print("⚠️ Rate Limit Hit! Wait a moment and try again.")
        else:
            print(f"⚠️ Gemini API Error: {e}")
        return ""


def generate_dynamic_script(topic: str, language: str = "en") -> str:
    """
    Injected with your detailed prompts for Russian, Spanish, and English.
    """
    print(f"✍️ Writing Narrative Script for '{topic}' ({language})...")

    # ======================= RUSSIAN MODE (DETAILED) ==========================
    if language == "ru":
        prompt = f"""
        КОНТЕКСТ: Ты — аналитик лора. Твой стиль — логика, факты и разоблачение мифов. Ты не кричишь, ты объясняешь суть.
        ТЕМА: {topic}

        ЗАДАЧА: Написать текст сценария СТРОГО от ста тридцати до ста сорока пяти слов. (Это пятьдесят пять секунд речи).

        ПЛАН СЦЕНАРИЯ (ОБЯЗАТЕЛЬНО):
        1. ЛОГИЧЕСКИЙ КРЮЧОК: Начни с вопроса "Почему персонаж не сделал [действие]?" или "А вы знали настоящий смысл [события]?". Никаких "Йо" и "Всем привет".
        2. ПЕРВЫЙ АРГУМЕНТ: Дай глубокий факт из сюжета, который всё объясняет.
        3. ИРОНИЯ ИЛИ ДЕТАЛЬ: Расскажи о моменте, который фанаты обычно пропускают (используй имена!). 
        4. ФИНАЛЬНАЯ УГРОЗА: Закончи фразой о последствиях или силе героя.

        СТРОГИЕ ПРАВИЛА:
        - НИКАКИХ ЦИФР: Пиши всё только буквами (вместо "100" пиши "сотня", вместо "2000" пиши "две тысячи").
        - ДЛИНА СЛОВ: Не более двенадцати символов.
        - СТИЛЬ: Трезвый, аналитический, энергичный. Без "кринжа" и пустых восторгов.
        - ФОРМАТ: Один сплошной текст без списков.

        ПРИМЕР ДЛЯ ПОДРАЖАНИЯ:
        "Почему Марлия не отправила весь флот на Парадиз? Казалось бы, один удар и война окончена. Но авторы продумали всё до мелочей. Во-первых, остров защищали тысячи спящих титанов. Ирония в том, что Марлия сама их создала, чтобы запереть врагов. В итоге эти монстры стали живым щитом для Элдийцев. Корабли просто не смогли бы подойти близко. Многие считают это ляпом, но это был холодный расчет Зика. Он знал, что прямая атака раскроет их планы всему миру. К тому же, никто не понимал истинной мощи короля стен. Один неверный шаг и начался бы великий гул земли. Марлия не могла так рисковать своей репутацией и флотом. А как бы поступили вы на месте их генералов?"

        Напиши Текст сценария (На русском языке):
        """
        return _gemini_generate(prompt, temperature=0.7)

    # ======================= SPANISH MODE (DETAILED) ==========================
    elif language == "es":
        prompt = f"""
        OBJETIVO: Narrar una historia inmersiva y oscura sobre: {topic}.

        REGLAS ANTI-CLICHÉ:
        1. **NO USES FRASES DE RELLENO:** - PROHIBIDO empezar con "¿Sabías que...?", "Mucha gente ignora...".
           - Empieza DIRECTAMENTE con la acción, la atmósfera o el dato crudo.
        2. **EJEMPLO DE ESTILO:**
           - *Bien:* "Creado con el único propósito de eliminar a los supervivientes, Nemesis representa la cúspide del armamento bioorgánico..."
        3. **TONO:** Narrador de misterio o terror. Serio, profundo y elegante.
        4. **LONGITUD:** ESTRICTAMENTE 110-140 PALABRAS.
        5. **FORMATO:** Un solo párrafo.

        Guion (Español):
        """
        return _gemini_generate(prompt, temperature=0.6)

    # ======================= ENGLISH MODE (DETAILED) ==========================
    else:
        prompt = f"""
        CONTEXT: You are a lore analyst. Your style is logic, facts, and debunking myths. You don’t shout; you explain the core essence.
        TOPIC: {topic}

        TASK: Write a script text STRICTLY between one hundred thirty and one hundred forty-five words. (This equals fifty-five seconds of speech).

        SCRIPT PLAN (MANDATORY):
        1. LOGICAL HOOK: Start with the question "Why didn't the character do [action]?" or "Did you know the real meaning of [event]?". No "Yo" or "Hello everyone."
        2. FIRST ARGUMENT: Provide a deep plot-based fact that explains everything.
        3. IRONY OR DETAIL: Mention a moment fans usually overlook (use names!). 
        4. FINAL THREAT: End with a phrase about the consequences or the hero's power.

        STRICT RULES:
        - NO NUMERALS: Write everything only in letters (instead of "100" write "one hundred", instead of "2000" write "two thousand").
        - WORD LENGTH: No more than twelve characters per word.
        - STYLE: Sober, analytical, energetic. No "cringe" or empty excitement.
        - FORMAT: One continuous block of text without lists.

        ROLE MODEL EXAMPLE:
        "Why did Marley not send the entire fleet to Paradis? It would seem one strike and the war is over. But the authors thought through every detail. First, the island was guarded by thousands of sleeping titans. The irony is that Marley created them to lock the enemies away. In the end, these monsters became a living shield for Eldians. Ships simply could not get close. Many consider this a plot hole, but it was Zeke's cold calculation. He knew a direct attack would reveal their plans to the world. Besides, no one understood the true power of the wall king. One wrong step and the great rumbling would begin. Marley could not risk their reputation and fleet like that. How would you have acted in place of their generals?"

        Write the script text (In English):
        """
        return _gemini_generate(prompt, temperature=0.6)

if __name__ == "__main__":
    print("\n--- RUNNING STABLE 2.5 FLASH GENERATOR ---")
    # This topic will now work because of Grounding
    test_topic = "Invisible Watchers in Metro 2035, who is their leader?"
    result = generate_dynamic_script(test_topic, "en")

    if result:
        print("-" * 30)
        print(f"✅ Final Script:\n{result}")
        print("-" * 30)
    else:
        print("❌ Failed to generate script.")