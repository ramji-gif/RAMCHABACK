import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from gtts import gTTS
from googletrans import Translator
import speech_recognition as sr
import io
import os
from pydub import AudioSegment
import tempfile
import asyncio

app = FastAPI()
translator = Translator()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"message": "Voice Translator backend is running."}

# Language map for TTS and STT

language_map = {
    "Hindi": ("hi-IN", "hi", "hi"),
    "English": ("en-IN", "en", "en"),
    "Tamil": ("ta-IN", "ta", "ta"),
    "Telugu": ("te-IN", "te", "te"),
    "Bengali": ("bn-IN", "bn", "bn"),
    "Urdu": ("ur-IN", "ur", "ur"),
    "Marathi": ("mr-IN", "mr", "mr"),
    "Gujarati": ("gu-IN", "gu", "gu"),
    "Kannada": ("kn-IN", "kn", "kn"),
    "Malayalam": ("ml-IN", "ml", "ml"),
    "Punjabi": ("pa-IN", "pa", "pa"),
    "Assamese": ("as-IN", "hi", "as"),
    "Odia": ("or-IN", "hi", "or"),
    "Bhojpuri": ("hi-IN", "hi", "bho"),
    "Maithili": ("hi-IN", "hi", "mai"),
    "Chhattisgarhi": ("hi-IN", "hi", "hne"),
    "Rajasthani": ("hi-IN", "hi", "raj"),
    "Konkani": ("hi-IN", "hi", "kok"),
    "Dogri": ("hi-IN", "hi", "doi"),
    "Kashmiri": ("hi-IN", "hi", "ks"),
    "Santhali": ("hi-IN", "hi", "sat"),
    "Sindhi": ("hi-IN", "hi", "sd"),
    "Manipuri": ("hi-IN", "hi", "mni"),
    "Bodo": ("hi-IN", "hi", "brx"),
    "Sanskrit": ("sa-IN", "hi", "sa")
}

# Store WebSocket connections by device ID
connected_devices = {}

@app.websocket("/ws/{src}/{tgt}/{device_id}")
async def translate_ws(websocket: WebSocket, src: str, tgt: str, device_id: str):
    print(f"🔌 WebSocket connection opened for {device_id} - {src} → {tgt}")
    await websocket.accept()
    recognizer = sr.Recognizer()

    src_locale, src_tts_lang, src_code = language_map.get(src, ("hi-IN", "hi-IN", "hi"))
    _, tgt_tts_lang, tgt_code = language_map.get(tgt, ("hi-IN", "hi-IN", "hi"))

    # Store the device connection
    connected_devices[device_id] = websocket

    try:
        while True:
            # Wait for audio input from this device
            audio_chunk = await websocket.receive_bytes()
            print(f"📥 Received audio blob of size {len(audio_chunk)} bytes")

            # Convert audio to wav format for recognition
            audio = AudioSegment.from_file(io.BytesIO(audio_chunk), format="mp3")
            wav_io = io.BytesIO()
            audio.export(wav_io, format="wav")
            wav_io.seek(0)

            # Use SpeechRecognition to get text from the audio
            with sr.AudioFile(wav_io) as source:
                audio_data = recognizer.record(source)
                try:
                    # Recognize speech using Google Speech Recognition
                    text = recognizer.recognize_google(audio_data, language=src_code)
                    print(f"🎤 Recognized text: {text}")

                    # Translate the recognized text
                    translated = translator.translate(text, src=src_code, dest=tgt_code).text
                    print(f"🌐 Translated text: {translated}")

                    # Convert translated text to speech (TTS)
                    tts = gTTS(translated, lang=tgt_tts_lang)
                    tts_io = io.BytesIO()
                    tts.save(tts_io)
                    tts_io.seek(0)

                    # Send back translated speech to the client
                    await websocket.send_bytes(tts_io.read())

                except sr.UnknownValueError:
                    print("❌ Could not understand audio")
                    await websocket.send_text("❌ Could not understand the speech.")
                except sr.RequestError as e:
                    print(f"❌ Error with the recognition service: {e}")
                    await websocket.send_text("❌ Error with the recognition service.")
                except Exception as e:
                    print(f"❌ Error: {e}")
                    await websocket.send_text(f"❌ Error: {e}")

    except WebSocketDisconnect:
        print(f"❌ WebSocket disconnected for device: {device_id}.")
        del connected_devices[device_id]


@app.post("/translate/")
async def translate_text(src: str, tgt: str, text: str):
    try:
        # Perform translation using googletrans
        translated = translator.translate(text, src=src, dest=tgt).text
        print(f"🌐 Translated text: {translated}")
        return {"translated_text": translated}
         # Generate TTS for translated text using gTTS
        tts = gTTS(text=translated, lang=tgt)
        with tempfile.NamedTemporaryFile(delete=False) as tmp_audio:
            tmp_audio_name = tmp_audio.name
            tts.save(tmp_audio_name)
            tmp_audio.close()

            # Return audio as response
            with open(tmp_audio_name, "rb") as audio_file:
                audio_data = audio_file.read()
                os.remove(tmp_audio_name)
                return {"translated_text": translated, "audio_data": audio_data}

    except Exception as e:
        return {"error": str(e)}


# Helper function to get available languages for translation
@app.get("/languages/")
def get_languages():
    return {"languages": list(language_map.keys())}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
