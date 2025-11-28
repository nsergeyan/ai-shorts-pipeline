import whisper
import os
import warnings

warnings.filterwarnings("ignore")
print("⏳ Loading Whisper...")
model = whisper.load_model("base")


def transcribe_audio_to_groups(audio_path, words_per_group=2):
    if not os.path.exists(audio_path): return []

    result = model.transcribe(audio_path, word_timestamps=True)
    final_groups = []
    current_words = []
    group_start = 0.0

    all_words = [w for s in result['segments'] for w in s['words']]

    for i, word in enumerate(all_words):
        if not current_words: group_start = word['start']
        current_words.append(word['word'].strip())

        is_end = (i == len(all_words) - 1)
        dist = 0 if is_end else all_words[i + 1]['start'] - word['end']

        if len(current_words) >= words_per_group or is_end or dist > 0.5:
            txt = " ".join(current_words).replace(" ,", ",").replace(" .", ".")
            final_groups.append((group_start, word['end'], txt))
            current_words = []

    return final_groups