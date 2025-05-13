import uvicorn
import os
import io
import json
import tempfile
from contextlib import suppress

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel

import speech_recognition as sr
from googletrans import Translator, LANGUAGES
from gtts import gTTS
from pydub import AudioSegment

# Initialize FastAPI app
app = FastAPI()
translator = Translator()
supported_langs = LANGUAGES.keys()

# Global state
connected_devices = {}

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Validation error handler
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    print(f"⚠️ Validation error: {exc.errors()}")
    return await JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
    )

# Root route
@app.get("/")
def root():
    return {"message": "Swadeshi Voice Translator backend is running."}

# Language map
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

# WebSocket translation route
@app.websocket("/ws/{src}/{tgt}/{device_id}")
async def translate_ws(websocket: WebSocket, src: str, tgt: str, device_id: str):
    print(f"🔌 WebSocket connected: {device_id} ({src} → {tgt})")
    await websocket.accept()
    recognizer = sr.Recognizer()

    src_locale, _, src_code = language_map.get(src, ("hi-IN", "hi", "hi"))
    _, tgt_tts_lang, tgt_code = language_map.get(tgt, ("hi-IN", "hi", "hi"))

    connected_devices[device_id] = websocket

    try:
        while True:
            msg = await websocket.receive()

            # Handle audio blob
            if "bytes" in msg:
                audio_chunk = msg["bytes"]
                print(f"📥 Received audio blob: {len(audio_chunk)} bytes")

                with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as webm_file:
                    webm_file.write(audio_chunk)
                    webm_path = webm_file.name

                wav_path = webm_path.replace(".webm", ".wav")

                try:
                    AudioSegment.from_file(webm_path).export(wav_path, format="wav")
                    print("✅ Converted webm to wav")
                except Exception as e:
                    await websocket.send_text(f"Audio conversion failed: {str(e)}")
                    continue

                try:
                    with sr.AudioFile(wav_path) as source:
                        audio_data = recognizer.record(source)
                    text = recognizer.recognize_google(audio_data, language=src_locale)
                    print(f"🗣 Recognized: {text}")
                except Exception as e:
                    await websocket.send_text(f"STT failed: {str(e)}")
                    continue
                finally:
                    with suppress(Exception):
                        os.remove(webm_path)
                        os.remove(wav_path)

            # Handle text message
            elif "text" in msg:
                try:
                    parsed = json.loads(msg["text"])
                    if parsed.get("type") == "text":
                        text = parsed["data"]
                        print(f"📝 Received text for translation: {text}")
                    else:
                        await websocket.send_text("Unsupported message type.")
                        continue
                except json.JSONDecodeError:
                    await websocket.send_text("Invalid JSON format.")
                    continue

            # Translation fallback
            fallback_used = False
            if src_code not in supported_langs:
                src_code = "hi"
                fallback_used = True
            if tgt_code not in supported_langs:
                tgt_code = "hi"
                tgt_tts_lang = "hi"
                fallback_used = True
            if fallback_used:
                await websocket.send_text("⚠ Fallback to Hindi due to unsupported language.")

            try:
                translated = translator.translate(text, src=src_code, dest=tgt_code).text
                print(f"🌐 Translated: {translated}")
                await websocket.send_text(json.dumps({"type": "text", "data": translated}))
            except Exception as e:
                await websocket.send_text(f"Translation failed: {str(e)}")
                continue

            try:
                tts = gTTS(text=translated, lang=tgt_tts_lang)
                buf = io.BytesIO()
                tts.write_to_fp(buf)
                buf.seek(0)
                for other_id, other_ws in connected_devices.items():
                    if other_ws != websocket:
                        buf.seek(0)
                        await other_ws.send_bytes(buf.read())
                        print(f"🔊 Sent audio to device: {other_id}")
            except Exception as e:
                await websocket.send_text(f"TTS failed: {str(e)}")

    except WebSocketDisconnect:
        print(f"❌ WebSocket disconnected: {device_id}")
        connected_devices.pop(device_id, None)

# REST API for text translation
class TextTranslationRequest(BaseModel):
    text: str
    source_lang: str
    target_lang: str

@app.post("/translate-only/")
async def translate_only(req: TextTranslationRequest):
    _, _, src_code = language_map.get(req.source_lang, ("hi-IN", "hi", "hi"))
    _, tgt_tts_lang, tgt_code = language_map.get(req.target_lang, ("hi-IN", "hi", "hi"))

    if src_code not in supported_langs:
        src_code = "hi"
    if tgt_code not in supported_langs:
        tgt_code = "hi"

    try:
        translated_text = translator.translate(req.text, src=src_code, dest=tgt_code).text
        print(f"📝 Text-only translated: {translated_text}")
        return {"translated_text": translated_text}
    except Exception as e:
        return {"error": f"Translation failed: {str(e)}"}

# Start the server
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=10000)
