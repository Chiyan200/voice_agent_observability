import io
import os
from gtts import gTTS
import soundfile as sf

def generate_speech_wav(text: str, output_path: str):
    print(f"Generating audio for: '{text}' -> {output_path}")
    # 1. Generate speech using gTTS
    tts = gTTS(text=text, lang='en', slow=False)
    
    # 2. Save MP3 bytes in memory
    mp3_fp = io.BytesIO()
    tts.write_to_fp(mp3_fp)
    mp3_fp.seek(0)
    
    # 3. Read MP3 bytes using soundfile
    data, samplerate = sf.read(mp3_fp)
    
    # 4. Resample to 16000Hz if it's not 16000Hz (for consistent 16kHz PCM testing)
    if samplerate != 16000:
        import numpy as np
        duration = len(data) / samplerate
        num_samples = int(duration * 16000)
        src_indices = np.linspace(0, len(data) - 1, len(data))
        target_indices = np.linspace(0, len(data) - 1, num_samples)
        data = np.interp(target_indices, src_indices, data)
        samplerate = 16000
        
    # 5. Write as WAV file
    sf.write(output_path, data, samplerate, subtype='PCM_16')
    print(f"Successfully generated: {output_path}")

if __name__ == "__main__":
    os.makedirs("utils", exist_ok=True)
    generate_speech_wav("Can you check my balance for account 12345?", "utils/check_balance_success.wav")
    generate_speech_wav("Can you check my balance for account 99999?", "utils/check_balance_failure.wav")
