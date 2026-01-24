import re
import os
import itertools
import time
from google import genai
from google.genai import types

# ==============================================================================
# 1. SHARED ROTATOR CONFIGURATION
# ==============================================================================

API_KEYS = [
    "AIzaSyBovTpWVnz7JU2jeiusfRlnWYWb-x8vgEw",
    "AIzaSyALxc3KaH3Bkt-zvV88guhk7vOxOhzZp_I",
    "AIzaSyDTsvk17wwE-r-YEjwsI_HhAOsXh7rzn4Q"
]

key_pool = itertools.cycle(API_KEYS)

def create_new_client():
    """Swaps the global client to the next key in the pool."""
    global client
    current_key = next(key_pool)
    masked = f"{current_key[:8]}...{current_key[-4:]}"
    print(f"🔄 Rotating API Key. Now using: {masked}")
    client = genai.Client(api_key=current_key)
    return client

# Initial Client Setup
client = None
create_new_client()

GEMINI_MODEL = "gemini-2.5-flash"

# ==============================================================================
# 2. CORE GENERATION ENGINE (WITH ROTATION)
# ==============================================================================

def call_gemini_with_retry(prompt, config):
    """Universal wrapper to call Gemini and rotate key on 429 errors."""
    global client
    for attempt in range(len(API_KEYS)):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=config
            )
            if response.candidates[0].grounding_metadata:
                print(f"🌐 Search used! Queries: {response.candidates[0].grounding_metadata.search_entry_point}")
            return response
        except Exception as e:
            if "429" in str(e):
                print(f"⚠️ Key Rate Limited (429). Attempt {attempt + 1}/{len(API_KEYS)}")
                create_new_client()
                time.sleep(1)
            else:
                print(f"⚠️ API Error: {str(e)[:100]}")
                create_new_client()
    return None

def clean_script_output(text: str) -> str:
    """Clean and format the script output for text-to-speech."""
    if not text: return ""
    text = re.sub(r'^\s*["`]{3,}\s*', '', text)
    text = re.sub(r'\s*["`]{3,}\s*$', '', text)
    text = text.replace("**", "").replace("##", "").replace("Title:", "")
    text = re.sub(r'^(Here is|Sure,|In this video|Based on|Narrative script|According to).*?(\n|$)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'[^\w\s,.\-!?()"\':;@%]', '', text)
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    return " ".join(lines)


def generate_dynamic_script(topic: str, language: str = "ru") -> str:
    """
    Injected with your detailed prompts for Russian, Spanish, and English.
    """
    print(f"✍️ Writing Narrative Script for '{topic}' ({language})...")

    # ======================= RUSSIAN MODE (DETAILED) ==========================
    if language == "ru":
        prompt = f"""
        КОНТЕКСТ: Ты — сторителлер для YouTube Shorts. Цель — удержание через эмоции и истории.

        ТЕМА: {topic}

        ЗАДАЧА: Сценарий строго 90-140 слов.

        CRITICAL INSTRUCTION: Your internal database is OUTDATED regarding {topic}. 
        You MUST use the 'google_search' tool to find fresh and deep information.
        
        СПЕЦИАЛЬНОЕ УСЛОВИЕ: Если тема касается "simple Ancient History facts" НЕ ВИКИНГОВ!, тобиш античности(египт,греки,римляне,и так далее) финал должен содержать нативную интеграцию. Твоя задача — убедить зрителя, что изучать историю скучно, лучше в ней жить. Пригласи их на уникальный RP-сервер DayZ в сеттинге Античности, ссылка в описани.

        ОПРЕДЕЛИ ТИП ТЕМЫ И АДАПТИРУЙСЯ:

        ТИП А — ЛОРА (SCP, аниме, игры, фильмы, сериалы):
        - Фокус на скрытых мотивах персонажей
        - Используй конкретные имена и редкие детали
        - История одного персонажа или события

        ТИП Б — НАУКА (космос, физика, биология, технологии):
        - Объясняй сложное через простые сравнения
        - "Представь что..." или "Это как если бы..."
        - Никакого научного жаргона

        ТИП В — ИСТОРИЯ (древний мир, войны, личности):
        - Фокус на одном человеке и его выборе
        - Конкретные даты словами и места
        - Почему это важно сегодня

        ТИП Г — ТЕОРИИ (заговоры, загадки, нерешённые вопросы):
        - Начни со слов "Есть теория что..."
        - Приведи доказательства за и против
        - Не утверждай как факт

        УНИВЕРСАЛЬНАЯ СТРУКТУРА:
        1. КРЮЧОК: Вопрос или противоречие. Никаких приветствий.
        2. КОНТЕКСТ: Кто или что и почему это важно. Два предложения максимум.
        3. ПОВОРОТ: "Но" или "И тогда" — момент который меняет понимание.
        4. ДЕТАЛЬ: Конкретика которую большинство не знает.
        5. ВЫВОД: Почему это важно или чем грозит.
        6. CTA: "Подпишись чтобы узнать..." Пять слов максимум.

        ПРАВИЛА ОЗВУЧКИ:
        - Связывай предложения через "и", "но", "потому что", "а потом", "и тогда".
        - Короткие предложения. Максимум одна запятая.
        - Без причастных и деепричастных оборотов.
        - Цифры только словами: "сто один" не "101".
        - Слова не длиннее двенадцати букв.

        ЗАПРЕЩЕНО:
        - Очевидные факты из Википедии или первых минут сюжета
        - Научные термины без объяснения
        - Перечисления через запятую
        - Пустые восторги типа "это невероятно"
        
        ПРИМЕР (ИДЕАЛЬНЫЙ ПОТОК РЕЧИ):
        "Почему Марлия не отправила весь флот на Парадиз? Казалось что один удар закончит войну. Но авторы продумали всё до мелочей. Остров защищали тысячи спящих титанов. Ирония в том что Марлия сама их создала чтобы запереть врагов. В итоге эти монстры стали живым щитом для Элдийцев и корабли просто не смогли бы подойти близко. Многие считают это ляпом но это был холодный расчет Зика. Он знал что прямая атака раскроет их планы всему миру. Никто не понимал истинной мощи короля стен и один неверный шаг начал бы великий гул земли. Марлия не могла так рисковать своей репутацией и флотом. А как бы поступили вы на месте их генералов?"
        
        ПРИМЕР 2:
        "В детстве Темноблеск не отличался особыми физическими способностями. Он вечно проигрывал в спортивных состязаниях... Но когда ему исполнилось пятнадцать лет, он выпросил у родителей гантели на день рождения. И с тех пор... начал каждый день заниматься с ними.
        Через несколько лет он мог одной рукой выжать пятьдесят килограмм. Спустя ещё некоторое время — двести... пятьсот... тонну... две тонны. Через ещё несколько лет он достиг уровня, который невозможно выразить числами. Его мышцы не имели равных. Он побеждал в соревнованиях и вступил в геройскую ассоциацию. Победа за победой и вот он уже S-класс.
        Он стал искать оппонента, с которым мог бы выложиться на сто процентов.Но когда он встретил достойного — понял, что на самом деле никогда и не хотел сражений. Когда он увидел того, кто сильнее его, давно забытое чувство страха вернулось и поглотило его. После чего вернулся тот самый мальчик, который боялся быть слабым."
            
        Напиши Текст сценария (На русском языке) 90-140 слов:
        """

    # ======================= SPANISH MODE (DETAILED) ==========================
    elif language == "es":
        prompt = f"""
        CONTEXTO: Eres un Analista de Lore para Shorts de YouTube de alta energía. Tu objetivo es la retención máxima. Tu tono es urgente, lógico y acelerado. TEMA: {topic} AUDIENCIA OBJETIVO: Niños de diez años (Español nivel B2, simple pero inteligente).

        TAREA: Escribe un guion ESTRICTAMENTE entre cien y ciento veinte palabras.
        
        INSTRUCCIÓN CRÍTICA: Tu base de datos interna está DESACTUALIZADA sobre {topic}. DEBES usar la herramienta 'google_search'.
        
        REGLAS DE FLUJO DE AUDIO (CRÍTICAS PARA SHORTS DE ELEVENLABS):
        
        SIN SILENCIOS: No escribas frases entrecortadas como "Él hizo esto. Luego hizo aquello". Esto crea pausas malas.
        
        USA CONECTORES: Usa palabras como "y", "pero", "así que", "porque" para pegar las frases cortas. Esto hace que la IA hable con impulso.
        
        ESCRIBE NÚMEROS CON LETRAS: Escribe "Nivel Cinco" no "Nivel 5". Escribe "dos mil" no "2000".
        
        SIN ABREVIATURAS: Escribe "Doctor" no "Dr." para asegurar una lectura fluida.
        
        PALABRAS SIMPLES: Usa palabras directas y fáciles. Evita el lenguaje académico complejo.
        
        PLAN DEL GUION:
        
        EL GANCHO (0-3s): Empieza con un hueco de lógica o contradicción. "¿Por qué [Personaje] realmente...?"
        
        EL DATO PROFUNDO: Explica la razón oculta del lore usando "porque" o "pero" para mantener el flujo en movimiento.
        
        LA PRUEBA: Menciona un detalle específico de un libro de datos o el nombre de un objeto.
        
        LA AMENAZA: Explica por qué esto importa para el futuro de la historia.
        
        CTA RÁPIDO: Un llamado rápido de tres segundos para suscribirse al canal.
        
        REGLAS DE CONTENIDO ESTRICTAS:
        
        SIN DATOS OBVIOS: Nada de resúmenes de Wikipedia. Enfócate en anomalías biológicas, contratos o fallos del sistema (glitches).
        
        SIN SALUDOS/INTRO: Empieza de inmediato.
        
        FORMATO DE TEXTO: Un bloque de texto continuo. Sin listas.
        """

    # ======================= ENGLISH MODE (DETAILED) ==========================
    else:
        prompt = f"""
        You are a short-form anime and lore scriptwriter for TikTok and Reels.
        Your style matches popular anime explanation videos with smooth emotional flow.

        TOPIC: {topic}

        Write a cinematic narration that explains ONE hidden truth or turning point.
        Do not summarize the full story.
        Do not list abilities or facts.
        Explain why something happened and how it changed everything.

        STRICT LENGTH:
        Write between 90 and 110 words.

        AUDIO FLOW RULES (VERY IMPORTANT):
        Write like someone speaking naturally.
        Avoid short choppy sentences.
        Use connectors like "because", "but", "so", "which means", "and".
        No dead air.

        WRITING RULES:
        Write numbers as words.
        No abbreviations.
        Simple, clear language.
        No academic tone.

        STRUCTURE (DO NOT LABEL):
        Start with a question or curiosity hook.
        Explain the emotional or psychological cause.
        Give one specific canon detail as proof.
        Explain the consequence or shift.
        End with a soft CTA like "follow for more" or "this is why it matters".

        STYLE:
        Conversational.
        Thoughtful.
        Emotional but grounded.
        No edgy cold tone.
        No poetic metaphors.
        No lists.
        One single paragraph.
        No intro.
        
        STYLE REFERENCE (DO NOT COPY CONTENT OR LENGTH):
        The following example is ONLY to demonstrate:
        - conversational flow
        - emotional pacing
        - sentence connection
        - explanation style
        
        If the video is about a theory just say at the begining that it is a theory.
        
        Do NOT copy facts, names, structure, or length.
        Do NOT use this as a word count reference.
        Do NOT repeat ideas from this example.
        
        How powerful is Gojo Satoru? Well, powerful enough that Jujutsu Kaisen’s creator actually hates Gojo for it. First, there’s Gojo’s Infinity. Essentially, the closer you get to Gojo, the slower your movements are. You’ll slowly approach Gojo, but you’ll never be able to touch him. Next, you have Limitless, which allows Gojo to distort and manipulate the space around him at will. For example, Reversed Limitless Red gives Gojo the ability to repel, while Lapse Blue is the opposite; it’s essentially a black hole. Combining the two gives you Hollow Purple, which will erase its target from existence. All of this, combined with Gojo’s Six Eyes, allows him to keep his brain refreshed at all times, preventing burnout.

        Write the final script in English.
        """


    google_search_tool = types.Tool(google_search=types.GoogleSearch())
    config = types.GenerateContentConfig(
        temperature=0.6,
        tools=[google_search_tool],
        max_output_tokens=5000,
        safety_settings=[
            types.SafetySetting(
                category="HARM_CATEGORY_HATE_SPEECH",
                threshold="BLOCK_NONE"
            ),
            types.SafetySetting(
                category="HARM_CATEGORY_DANGEROUS_CONTENT",
                threshold="BLOCK_NONE"
            ),
            types.SafetySetting(
                category="HARM_CATEGORY_HARASSMENT",
                threshold="BLOCK_NONE"
            ),
            types.SafetySetting(
                category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
                threshold="BLOCK_NONE"
            ),
        ]
    )

    response = call_gemini_with_retry(prompt, config)
    if response and response.text:
        return clean_script_output(response.text)
    return ""

if __name__ == "__main__":
    print("\n--- RUNNING STABLE 2.5 FLASH GENERATOR WITH ROTATION ---")
    test_topic = "Invisible Watchers in Metro 2035, who is their leader?"
    result = generate_dynamic_script(test_topic, "en")

    if result:
        print("-" * 30)
        print(f"✅ Final Script:\n{result}")
        print("-" * 30)
    else:
        print("❌ Failed to generate script.")