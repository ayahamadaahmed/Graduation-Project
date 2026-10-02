import wave
from pathlib import Path


root = Path(__file__).resolve().parents[1]

input_file = root / "artifacts/voice_audio/tts/elevenlabs_test_24k.pcm"
output_file = root / "artifacts/voice_audio/tts/elevenlabs_test_24k.wav"

pcm = input_file.read_bytes()

with wave.open(str(output_file), "wb") as wav:
    wav.setnchannels(1)
    wav.setsampwidth(2)
    wav.setframerate(24000)
    wav.writeframes(pcm)

print("Saved:", output_file)