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
        КОНТЕКСТ: Ты — аналитик лора. Твой стиль — логика, факты и разоблачение мифов. Ты не кричишь, ты объясняешь суть.
        ТЕМА: {topic}

        ЗАДАЧА: Написать текст сценария СТРОГО от ста тридцати до ста сорока пяти слов. (Это пятьдесят пять секунд речи).

        ПЛАН СЦЕНАРИЯ (ОБЯЗАТЕЛЬНО):
        1. ЛОГИЧЕСКИЙ КРЮЧОК: Начни с вопроса "Почему персонаж не сделал [действие]?" или "А вы знали настоящий смысл [события]?". Никаких "Йо" и "Всем привет".
        2. ПЕРВЫЙ АРГУМЕНТ: Дай глубокий факт из сюжета, который всё объясняет.
        3. ИРОНИЯ ИЛИ ДЕТАЛЬ: Расскажи о моменте, который фанаты обычно пропускают (используй имена!). 
        4. ФИНАЛЬНАЯ УГРОЗА: Закончи фразой о последствиях или силе героя.

        ПРАВИЛА ДЛЯ ОЗВУЧКИ:
        1. Текст будет читать робот. Пиши "для ушей", а не для глаз.
        2. МИНИМУМ ЗАПЯТЫХ: Запятые заставляют робота делать неестественные паузы. Разбвай сложные предложения на два простых.
        3. Избегай деепричастных оборотов (не пиши "делая это", пиши "он сделал это").
        4. Вместо перечислений через запятую используй союз "и".

        СТРОГИЕ ПРАВИЛА:
        - НИКАКИХ ЦИФР: Пиши всё только буквами (вместо "100" пиши "сотня", вместо "2000" пиши "две тысячи").
        - для сцп говори не сто один а один нол один.
        - ДЛИНА СЛОВ: Не более двенадцати символов.
        - СТИЛЬ: Трезвый, аналитический, энергичный. Без "кринжа" и пустых восторгов.
        - ФОРМАТ: Один сплошной текст без списков.
        
        СПЕЦИАЛЬНОЕ УСЛОВИЕ: Если тема касается 'Ancient History', финал должен содержать нативную интеграцию. Твоя задача — убедить зрителя, что изучать историю скучно, лучше в ней жить. Пригласи их на уникальный RP-сервер DayZ в сеттинге Античности, ссылка в описани.
        
        ПРИМЕР (ИДЕАЛЬНЫЙ ПОТОК РЕЧИ):
        "Почему Марлия не отправила весь флот на Парадиз? Казалось что один удар закончит войну. Но авторы продумали всё до мелочей. Остров защищали тысячи спящих титанов. Ирония в том что Марлия сама их создала чтобы запереть врагов. В итоге эти монстры стали живым щитом для Элдийцев и корабли просто не смогли бы подойти близко. Многие считают это ляпом но это был холодный расчет Зика. Он знал что прямая атака раскроет их планы всему миру. Никто не понимал истинной мощи короля стен и один неверный шаг начал бы великий гул земли. Марлия не могла так рисковать своей репутацией и флотом. А как бы поступили вы на месте их генералов?"
        Напиши Текст сценария (На русском языке) 90-140 слов:
        """

    # ======================= SPANISH MODE (DETAILED) ==========================
    elif language == "es":
        prompt = f"""
        CONTEXTO: Eres un analista de lore. Tu estilo es lógica, hechos y desmontar mitos. No gritas, explicas la esencia.
        TEMA: {topic}

        TAREA: Escribir texto de guión ESTRICTAMENTE entre ciento treinta y ciento cuarenta y cinco palabras. (Cincuenta y cinco segundos de audio).

        PLAN DEL GUIÓN (OBLIGATORIO):
        1. GANCHO LÓGICO: Comienza con "¿Por qué el personaje no hizo [acción]?" o "¿Sabías el verdadero significado de [evento]?". Sin "Hola" ni "Buenas".
        2. PRIMER ARGUMENTO: Da un hecho profundo del argumento que lo explica todo.
        3. IRONÍA O DETALLE: Menciona un momento que los fans suelen pasar por alto (¡usa nombres!).
        4. AMENAZA FINAL: Termina con frase sobre consecuencias o poder del héroe.

         REGLAS DE AUDIO (MUY IMPORTANTE):
        1. Escribe para ser escuchado y no leido.
        2. EVITA LAS COMAS: Las comas hacen que la voz suene robótica y entrecortada.
        3. Usa frases cortas y directas.
        4. Sustituye las comas por la palabra "y" o pon un punto y seguido.
        5. No uses oraciones subordinadas complejas (como "lo cual hizo que..."). Sé directo.

        REGLAS ESTRICTAS:
        - SIN NÚMEROS: Escribe todo en letras (en vez de "100" escribe "cien", en vez de "2000" escribe "dos mil").
        - LONGITUD PALABRAS: Máximo doce caracteres por palabra.
        - ESTILO: Sobrio, analítico, enérgico. Sin "cringe" ni entusiasmos vacíos.
        - FORMATO: Un bloque continuo sin listas.

        MODELO A SEGUIR (FLUJO PERFECTO):
        "¿Por qué Marley no envió toda la flota a Paradis? Parecía que un golpe acabaría la guerra pero los autores pensaron cada detalle. Primero la isla estaba guardada por miles de titanes dormidos. La gran ironía es que Marley los creó para encerrar a sus enemigos y al final esos monstruos fueron un escudo viviente para los eldianos. Los barcos no podían acercarse. Muchos ven un error de trama pero fue un cálculo frío de Zeke. Él sabía que un ataque directo revelaría planes al mundo. Además nadie entendió el poder real del rey de los muros. Un paso equivocado desataba el retumbar de la tierra. Marley no podía arriesgar su reputación ni su flota de esa manera. ¿Cómo actuarías tú en lugar de los generales?"

        Escribe Texto guión (En español):
        """

    # ======================= ENGLISH MODE (DETAILED) ==========================
    else:
        prompt = f"""
        CONTEXT: You are a lore analyst. Your style is logic, facts, and debunking myths. You don’t shout; you explain the core essence.
        TOPIC: {topic}

        TASK: Write a script text STRICTLY between 100- 120 words.

        SCRIPT PLAN (MANDATORY):
        1. LOGICAL HOOK: Start with the question "Why didn't the character do [action]?" Or other.... No "Yo" or "Hello everyone."
        2. FIRST ARGUMENT: Provide a deep plot-based fact that explains everything.
        3. IRONY OR DETAIL: Mention a moment fans usually overlook (use names!). 
        4. FINAL THREAT: End with a phrase about the consequences or the hero's power.

        AUDIO FLOW RULES (CRITICAL):
        1. Write for the ear, not the eye.
        2. MINIMIZE COMMAS: Commas cause unnatural robotic pauses.
        3. Use short sentences.
        4. Instead of complex clauses using commas, use "and" or start a new sentence.
        5. Keep the language simple (B2 level).

        STRICT RULES:
        - NO NUMERALS: Write everything only in letters (instead of "100" write "one hundred", instead of "2000" write "two thousand").
        - WORD LENGTH: No more than twelve characters per word.
        - STYLE: Sober, analytical, energetic. No "cringe" or empty excitement.
        - FORMAT: One continuous block of text without lists.

         ROLE MODEL EXAMPLE (GOOD FLOW):
        "Why did Marley not send the entire fleet to Paradis? It seems like one strike would end the war. But the authors thought through every detail. First the island was guarded by thousands of sleeping titans. The irony is that Marley created them to lock the enemies away but in the end these monsters became a living shield for Eldians. Ships simply could not get close. Many consider this a plot hole but it was Zeke's cold calculation. He knew a direct attack would reveal their plans to the world. One wrong step and the great rumbling would begin. Marley could not risk their reputation and fleet like that. How would you have acted in place of their generals?"

        Write the script text (In English) Use simple english so people with B2 would understand or 10 year old children.
        """


    google_search_tool = types.Tool(google_search=types.GoogleSearch())
    config = types.GenerateContentConfig(
        temperature=0.7,
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