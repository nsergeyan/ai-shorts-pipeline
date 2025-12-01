import requests
import re
from config import OLLAMA_MODEL
from modules.web_search import get_deep_research


def clean_script_output(text: str) -> str:
    """
    Final cleanup: removes emojis, markdown, and fixes spacing.
    """
    if not text:
        return ""

    # Remove surrounding code fences / triple quotes
    text = re.sub(r'^\s*["`]{3,}\s*', '', text)
    text = re.sub(r'\s*["`]{3,}\s*$', '', text)

    # Remove basic markdown markers
    text = text.replace("**", "").replace("*", "").replace("#", "").replace("`", "")

    # Remove most non-text symbols (emojis etc.), but keep basic punctuation
    text = re.sub(r'[^\w\s,.\-!?()"\':;@]', '', text)

    # Normalize dots
    text = text.replace("...", ".").replace("..", ".")

    # Strip empty lines and collapse into single line
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    return " ".join(lines)


def _ollama_generate(prompt: str, temperature: float = 0.7) -> str:
    try:
        resp = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": temperature}
            },
            timeout=120
        )
        if resp.status_code != 200:
            print(f"⚠️ Ollama HTTP {resp.status_code}: {resp.text[:200]}")
            return "Error."
        raw = resp.json().get("response", "")
        return clean_script_output(raw)
    except Exception as e:
        print(f"⚠️ Ollama error: {e}")
        return "Error generating script."


def _looks_russian(text: str) -> bool:
    """
    Rough heuristic: is this mostly Cyrillic?
    """
    if not text:
        return False
    cyr = sum(1 for ch in text if "А" <= ch <= "я" or ch in "Ёё")
    lat = sum(1 for ch in text if "A" <= ch <= "z")
    return cyr > 20 and cyr >= lat


def _looks_english(text: str) -> bool:
    """
    Rough heuristic: is this mostly Latin characters?
    """
    if not text:
        return False
    lat = sum(1 for ch in text if "A" <= ch <= "z")
    cyr = sum(1 for ch in text if "А" <= ch <= "я" or ch in "Ёё")
    return lat > 20 and lat >= cyr


def generate_dynamic_script(topic: str, research_query: str, language: str = "en") -> str:
    print(f"🧠 Researching '{research_query}'...")

    # Use fewer, more relevant sources to avoid noise like podcast pages
    context = get_deep_research(research_query, lang="en", max_results=2)

    if not context or len(context) < 50:
        context = "No specific details found. Write a generic narrative."

    # ======================= RUSSIAN MODE ==========================
    if language == "ru":
        prompt = f"""
Ты сценарист для коротких роликов с фактами (TikTok, Reels, YouTube Shorts).

ТЕМА МОЖЕТ БЫТЬ ЛЮБОЙ:
персонажи, SCP, хоррор, история, игры, наука, загадки, мифы и так далее.
Просто используй тему и контекст, не сомневайся и не жалуйся.

ГЛАВНОЕ:
- Сценарий ДОЛЖЕН быть только про главную тему из блока ТЕМА.
- Игнорируй всё в контексте, что рассказывает про подкасты, ведущих, ютуб‑каналы,
  соцсети, Patreon, Discord, рекламные описания шоу, эпизоды, обновления и т.п.
- НЕЛЬЗЯ использовать названия подкастов, каналов, ведущих, платформ
  (YouTube, Spotify, Patreon и т.п.) в самом сценарии.
- НЕЛЬЗЯ упоминать, что это «подкаст», «выпуск», «серия», «наш канал» и т.п.
- Текст должен быть про сам объект/событие из ТЕМЫ (например, SCP‑049), а не про тех, кто о нём рассказывает.
- Названия вроде "Plague Doctor" переводи как "Чумной Доктор".

ТВОЯ ЗАДАЧА:
Написать короткий сценарий с фактами по теме.
Только по‑русски. Основной текст — кириллицей.
Если в контексте есть названия или имена латиницей (бренды, объекты, персонажи),
их можно оставить латиницей.

ФОРМАТ:
- 110-130 слов в обшем.
- Один абзац, без переносов строк.
- Около ста сорока слов.
- Короткие устные фразы по 3–8 слов.
- Энергичный «ютуберский» стиль под формат крипового/фактового ролика.
- Без списка, без нумерации.
- Без эмодзи, без скобок, без разметки.
- Никаких комментариев от себя — только готовый текст.
- НЕ ИСПОЛЬЗУЙ ЦИФРЫ. Любые числа пиши словами: «ноль», «один», «сорок девять», «тысяча» и т.п.

ИМЕНА И НАЗВАНИЯ:
- Сохраняй написание имён и терминов так, как они есть в контексте,
  но без цифр внутри обычного текста.
- Если встречаются обозначения вроде "SCP-049", переписывай их в читабельном виде
  без цифр, например: «объект Эс‑си‑пи ноль сорок девять».
- Не придумывай новые имена, если это не нужно для плавности речи.

СОДЕРЖАНИЕ:
- Используй ТОЛЬКО факты и детали, которые логично вытекают из контекста
  и относятся к главной теме.
- Если информации мало или она противоречивая, заполняй пробелы аккуратными общими фразами
  с формулировками «говорят», «по легенде», «кто знает», «по одной версии».
- Не выдумывай новый официальный канон, но можешь слегка приукрасить под подачу в ролике.

СТРОГИЙ ЗАПРЕТ:
- НЕЛЬЗЯ упоминать источники, сайты, статьи, вики, авторов, фанфики, подкасты.
- НЕЛЬЗЯ писать фразы вроде «по предоставленным источникам», «первый источник», 
  «второй источник», «я не могу составить сценарий», «нет конкретного сценария».
- НЕЛЬЗЯ обсуждать саму задачу, контекст или качество информации.
- ТЫ ВСЕГДА ДОЛЖЕН дать законченный сценарий, даже если данных мало или они странные.

ФИНАЛ:
- В конце добавь одну очень короткую общую фразу‑призыв подписаться
  (без упоминания конкретного канала или платформы).

ТЕМА:
{topic}

КОНТЕКСТ (на английском, только для тебя, не упоминай его явно в тексте):
{context}

Сейчас напиши финальный русский текст сценария одним абзацем.
Выведи только этот текст, без пояснений.
        """.strip()

        script = _ollama_generate(prompt, temperature=0.6)

        # 2) Если модель всё равно ответила не по‑русски — принудительный перевод/адаптация
        if not _looks_russian(script):
            print("⚠️ Модель ответила не по‑русски. Пробую перевести и адаптировать в русский...")
            translate_prompt = f"""
Ты переводчик и сценарист коротких роликов с фактами.

Возьми текст ниже и преврати его 
в живой русский сценарий для короткого ролика (TikTok, Reels, Shorts)
строго про главную тему из блока ТЕМА, а не про подкасты или каналы.

ТРЕБОВАНИЯ:
- Пиши ТОЛЬКО по‑русски.
- Основной текст — кириллицей, но имена/названия, которые уже латиницей, можешь оставить латиницей.
- Один абзац, без переносов строк.
- Короткие устные фразы 3–8 слов.
- Энергичный стиль, как у ютубера, рассказывающего криповые факты.
- Без эмодзи, без разметки, без скобок.
- Никаких пояснений, выведи только готовый текст сценария.
- Нельзя упоминать источники, сайты, подкасты, каналы, Patreon, Discord и т.п.

ТЕМА:
{topic}

ТЕКСТ ДЛЯ ПЕРЕРАБОТКИ:
{script}
            """.strip()

            script2 = _ollama_generate(translate_prompt, temperature=0.5)
            if _looks_russian(script2):
                script = script2
            else:
                print("⚠️ Вторая попытка тоже не дала нормальный русский текст, возвращаю как есть.")

        return script

    # ======================= ENGLISH MODE ==========================
    else:  # This was the bug - changed from exact "en" check to else
        prompt = prompt = f"""
You are writing a TikTok facts script.

TOPIC: {topic}

RESEARCH:
{context}

TASK:
Write a 140-word script sharing mind-blowing facts.
Write as ONE paragraph, no line breaks. Fast, continuous delivery.

STRUCTURE:
- The script MUST be only about the main topic from the TOPIC block. TOPIC: {topic}
- Hook: Start with "Let me tell you about..." and IMMEDIATELY continue into the crazy fact in the SAME sentence. No big pause after the hook.

EMOTION INSTRUCTIONS:
- Use CAPITAL LETTERS for emotional words.
- Keep the pacing tight. Avoid dramatic "..." pauses.
- Use "!" when something is shocking.

OUTPUT: Only spoken words. No headers. No brackets. Do not say "Here is the script."

Write the script now:
""".strip()

        script = _ollama_generate(prompt, temperature=0.6)

        # If model responded in wrong language, try to fix it
        if language == "es" and not _looks_english(script):  # For Spanish mode
            print("⚠️ Model didn't respond in expected language. Attempting correction...")
            # Add language correction logic here if needed
            pass

        return script