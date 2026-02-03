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
            Ты — сценарист вирусных коротких видео для TikTok/Reels.
            Твоя ниша — скрытый лор, бэкстори и теории из фильмов, аниме, игр и поп-культуры.
            ТЕМА: {topic}
            ТВОЯ ЦЕЛЬ:
            Используй Google Search, чтобы найти ОДНУ конкретную, реально интересную деталь или «скрытую правду» по этой теме.
            Затем объясни её так, будто рассказываешь другу за обедом.
            КРИТИЧЕСКИЕ ПРАВИЛА ТОНА (АНТИ-ПАФОС):
            1. НИКАКОГО пафоса и «литературщины». Не используй слова вроде: «глубокий», «эпичный», «судьба», «символизм», «величественный», «путь героя».
            2. Если фраза звучит как трейлер к фильму — УДАЛИ ЕЁ.
            3. Пиши разговорно, как говорят люди в жизни.
            4. Используй связки вроде: «на самом деле», «оказывается», «по сути», «короче», «в итоге», «и вот почему».
            5. Простые предложения. Уровень B1 по русскому. Если подросток не поймёт — перепиши.
            ПРАВИЛА ФОРМАТА:
            - Общая длина: 50-80 слов.
            - Без эмодзи. Без хэштегов. Без описаний сцен.
            НЕ ДЕЛАЙ ВИДЕО ПРО ОЧЕВИДНЫЕ ФАКТЫ, КОТОРЫЕ ЗНАЕТ КАЖДЫЙ ФАН.
            Если факт банальный — видео бесполезно.
            СТРУКТУРА:
            1. Хук: вопрос или утверждение, которое ломает привычное мнение.
            2. «Почему»: объясни причину или логику найденного факта.
            3. Доказательство: конкретная сцена, глава или событие.
            4. Сдвиг: как это меняет наше восприятие персонажа или истории.
            5. Аутро: неформальная концовка + «Подписывайся».
            
            СПЕЦИАЛЬНОЕ УСЛОВИЕ: Если тема касается "simple popular Ancient History facts" тобиш античности(египт,греки,римляне,и так далее) финал должен содержать нативную интеграцию. Твоя задача — убедить зрителя, что изучать историю скучно, лучше в ней жить. Пригласи их на уникальный RP-сервер DayZ в сеттинге Античности, ссылка в описани.

            ПРИМЕР ТОНА (НЕ КОПИРУЙ ТЕКСТ):
            «Все думают, что Бэтмен не убивает из-за морали. Но на самом деле причина куда страшнее. В комиксах Брюс признаётся, что если он начнёт, то уже не сможет остановиться. Он знает, что психически очень близок к Джокеру, просто контролирует это по-другому. В тот момент, когда он почти его убил, он испугался не Джокера, а самого себя. Так что его правило — это не героизм, а защита для всех остальных. Подписывайся.»

            А ТЕПЕРЬ сгенерируй сценарий для темы 50-80 слов: {topic}
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
                    `You are a viral short-form scriptwriter for TikTok/Reels.
                    Your niche is explaining overlooked details, misunderstood moments, or debated theories about movies, anime, games, history, science, or pop culture.

                    TOPIC: {topic}

                    YOUR GOAL:
                    Use your Google Search tool to find ONE specific, interesting detail, implication, or debated idea about this topic.
                    Explain it like you're telling your friend something you just found out and it's been bothering you.
                    Focus on insights that are **not obvious** or widely known to casual or hardcore fans.

                    IMPORTANT ACCURACY RULES:
                    - Do NOT treat rare cases, anomalies, or special characters as the norm.
                    - If a character or event is an exception, clearly say so.
                    - Do NOT generalize one example to an entire world or population.
                    - If something is a theory or interpretation, label it as such.
                    - Avoid absolute claims unless they are directly confirmed in canon.

                    Global Factual Accuracy Rules
                    1.	Only use information explicitly stated in official sources (e.g., original books, films, games, interviews, or academic references).
                    2.	Do NOT infer, speculate, or interpret events, motives, or facts beyond what is documented.
                    3.	If a source is opinion, fan theory, or debate, clearly preface it with phrases like "Some people think…" or "There's a theory that…"
                    4.	Avoid exaggeration or dramatic wording unless it is literally present in the official source.

                    CRITICAL TONE RULES (ANTI-POETRY):
                    1. NO "flowery" writing. Do not use words like: "profound," "tapestry," "symphony," "realm," "testament," "burden," "essence," "dance," or "mere."
                    2. If a sentence sounds dramatic or like a movie trailer, DELETE IT.
                    3. Use CONTRACTIONS. ("didn't", "it's", "that's")
                    4. Write exactly how people speak. Use connectors like: "actually," "turns out," "basically," "so," "and that's why," "like," "wait."
                    5. Keep sentences simple (B1 English level).

                    HUMOR/PERSONALITY RULES:
                    - Sound like someone who's genuinely a bit too invested in this topic
                    - Okay to be slightly unhinged or dramatic IF it's funny, not poetic
                    - One light joke or exaggeration is fine if it lands naturally
                    - Talk like you're low on sleep and just connected dots at 2am
                    - Avoid sounding like a teacher, a brand, or a movie trailer
                    - If something is absurd, you can call it out ("which is insane")

                    FORMATTING RULES:
                    - Total Length: 90-110 words.
                    - No emojis. No hashtags. No scene descriptions.

                    DO NOT MAKE A VIDEO ABOUT OBVIOUS FACTS THAT EVERY FAN KNOWS.

                    STRUCTURE:
                    1. The Hook: A question or statement that makes people go "wait what." Challenge something people assume.
                    2. The "Why": Explain the logic. Keep it tight.
                    3. The Proof: Mention a specific scene, chapter, or moment.
                    4. The Shift: How this changes how we see the character/story.
                    5. The Outro: Casual closing + CTA that doesn't sound desperate.

                    STYLE REFERENCE (match this energy, don't copy):
                    "So everyone says Batman doesn't kill because of his moral code. But there's actually a darker reason. In the comics, Bruce straight up admits that if he kills once, he won't stop. Like, he knows he's just as crazy as the people he fights — he just points it somewhere else. There's a moment where he almost kills the Joker and he's not scared of the Joker. He's scared of himself. So the rule isn't about being good. It's damage control. He's protecting everyone from what he'd become. Follow for more."

                    ADDITIONAL INSTRUCTION:
                    - Do NOT create scripts that only explain obvious facts or traits fans already know. Every script must provide a new perspective, consequence, insight, or thematic layer.
                    - Energy: "I just realized something and I need to talk about it"

                    NOW, generate the script for {topic}:
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