# test_validator.py
import requests
import re

from config import OLLAMA_MODEL


def validate_script_format(script: str, language: str) -> tuple[bool, str]:
    """
    Check if script follows basic formatting rules based on language
    """

    if not script or len(script.strip()) == 0:
        return False, "Script is empty"

    # Word count check
    word_count = len(script.split())

    if language == "ru":
        if not (100 <= word_count <= 130):
            return False, f"Russian script should be 100-130 words, got {word_count}"

        # For Russian: Check for Arabic numerals (0-9) - THESE BREAK ELEVENLABS
        if re.search(r'\d', script):
            return False, "Russian script contains Arabic numerals (0-9) which break ElevenLabs"

    elif language == "es":
        if not (120 <= word_count <= 140):
            return False, f"Spanish script should be 120-140 words, got {word_count}"

    else:  # English
        if not (90 <= word_count <= 130):
            return False, f"English script should be 100-130 words, got {word_count}"

    # General checks for all languages
    if script.count('***') > 0 or script.count('###') > 0:
        return False, "Script contains markdown formatting"

    return True, f"Valid format: {word_count} words"


def validate_script_context(script: str, topic: str, context_summary: str) -> tuple[bool, str]:
    print(f"🔍 Validator AI: Checking alignment between script and '{topic}'...")

    validation_prompt = f"""
    ROLE: Quality Assurance Editor for AI-generated video narration.

    CONTEXT SUMMARY:
    "{context_summary}"

    GENERATED SCRIPT:
    "{script}"

    TASK:
    Does the SCRIPT accurately reflect the TOPIC and CONTEXT above?

    Criteria:
    - Is the main focus clearly on "{topic}"?
    - Are there no major factual contradictions?
    - Is it not too generic or unrelated?

    RESPOND IN THIS FORMAT ONLY:

    RESULT: YES/NO
    FEEDBACK: One-sentence explanation if NO, otherwise say "Valid and aligned."
    """

    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": validation_prompt,
                "stream": False,
                "options": {"temperature": 0.5, "num_ctx": 2048}
            },
            timeout=60
        )
        raw_response = response.json().get("response", "").strip()
        print("RAW AI RESPONSE:")
        print(raw_response)
        print("-" * 50)

        # Parse result
        result_line = next((line for line in raw_response.splitlines() if line.startswith("RESULT:")), "")
        feedback_line = next((line for line in raw_response.splitlines() if line.startswith("FEEDBACK:")), "")

        is_valid = "YES" in result_line.upper()
        feedback = feedback_line.replace("FEEDBACK:", "").strip() if feedback_line else "No feedback provided."

        return is_valid, feedback

    except Exception as e:
        print(f"⚠️ Validation failed due to error: {e}")
        return False, f"Validation error: {str(e)}"


def validate_script_complete(script: str, topic: str, context_summary: str, language: str) -> tuple[bool, str]:
    """
    Run both format and content validation
    Returns: (is_valid, feedback_message)
    """

    # First: Format validation
    format_valid, format_feedback = validate_script_format(script, language)
    if not format_valid:
        return False, f"FORMAT ERROR: {format_feedback}"

    # Second: Content validation
    content_valid, content_feedback = validate_script_context(script, topic, context_summary)
    if not content_valid:
        return False, f"CONTENT ERROR: {content_feedback}"

    return True, "Script passed all validations"


# Test the combined function
if __name__ == "__main__":
    print("🧪 TESTING COMBINED VALIDATOR SYSTEM")
    print("=" * 50)

    # Test Case 1: Everything correct
    print("\n📝 TEST 1: Everything correct")
    script1 = "Serpent's Hand is a loosely organized group of hackers and activists who believe SCP objects should remain free rather than contained. They oppose the Foundation's authoritarian approach and frequently assist anomalies in escaping containment. Their symbol features a green serpent and they're known for chaotic but often benevolent operations."
    topic1 = "Serpent's Hand"
    context1 = "Serpent's Hand is a loosely-organized group of hackers, activists, and chaos worshippers who believe that SCPs should not be contained."

    valid1, feedback1 = validate_script_complete(script1, topic1, context1, "en")
    print(f"Result: {valid1}")
    print(f"Feedback: {feedback1}")

    # Test Case 2: Format error (Russian with numbers)
    print("\n📝 TEST 2: Russian format error (numbers)")
    script2 = "Родился в 1991 году в Ереване."
    topic2 = "Narek"
    context2 = "Narek родился в тысяча девятьсот девяносто первом году в Ереване."

    valid2, feedback2 = validate_script_complete(script2, topic2, context2, "ru")
    print(f"Result: {valid2}")
    print(f"Feedback: {feedback2}")

    # Test Case 3: Content error (off-topic)
    print("\n📝 TEST 3: Content error (off-topic)")
    script3 = "La tinta del grimorio temblaba bajo la luz tenue de la luna..."
    topic3 = "Serpent's Hand"
    context3 = "Serpent's Hand is a group that supports SCPs and opposes containment."

    valid3, feedback3 = validate_script_complete(script3, topic3, context3, "es")
    print(f"Result: {valid3}")
    print(f"Feedback: {feedback3}")

    print("\n🏁 TEST COMPLETE")