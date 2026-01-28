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
                You are a viral short-form scriptwriter for TikTok/Reels.
                Your niche is explaining hidden lore, backstory, or theories about movies, anime, games, or pop culture.

                TOPIC: {topic}

                YOUR GOAL:
                Use your Google Search tool to find ONE specific, interesting detail or "hidden truth" about this topic.
                Then, explain it to the audience like you are talking to a friend at a lunch table.

                CRITICAL TONE RULES (ANTI-POETRY):
                1. NO "flowery" writing. Do not use words like: "profound," "tapestry," "symphony," "realm," "testament," "burden," "essence," "dance," or "mere."
                2. If a sentence sounds dramatic or like a movie trailer, DELETE IT.
                3. Use CONTRACTIONS. (Say "didn't" instead of "did not", "it's" instead of "it is").
                4. Write exactly how people speak. Use connectors like: "actually," "turns out," "basically," "so," "and that's why."
                5. Keep sentences simple (B1 English level). If an 11-year-old wouldn't understand it, rewrite it.

                FORMATTING RULES:
                - Total Length: 90 to 110 words.
                - No emojis. No hashtags. No scene descriptions.
                
                DO NOT MAKE A VIDEO ABOUT OBVIOUS FACTS THAT EVERY FAN KNOWS! People will hate me because i do useless videos...
                STRUCTURE:
                1. The Hook: A direct question or statement challenging what people usually think.
                2. The "Why": Explain the logic or the cause using the fact you found via Google Search.
                3. The Proof: Mention a specific scene, chapter, or event as evidence.
                4. The Shift: How this changes the way we see the character/story.
                5. Outro: A casual closing line + "Follow for more."

                STYLE REFERENCE (Use this tone, do not copy the text):
                "Everyone thinks Batman doesn't kill just because of his moral code. But actually, there's a darker reason. In the comics, Bruce admits that if he starts, he won't be able to stop. He knows he's just as crazy as the Joker, he just focuses it differently. That one time he almost killed the Joker, he was terrified of himself, not the clown. So his rule isn't about being a hero; it's a safety mechanism for everyone else. Basically, he's protecting the world from himself. Follow for more deep dives."

                NOW, generate the script for: {topic}
                """


    google_search_tool = types.Tool(google_search=types.GoogleSearch())
    config = types.GenerateContentConfig(
        temperature=0.3,
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