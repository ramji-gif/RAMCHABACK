import uvicorn
import os
import io
import json
import tempfile
from contextlib import suppress

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, WebSocketException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel

import speech_recognition as sr
from googletrans import Translator, LANGUAGES
from gtts import gTTS
from pydub import AudioSegment

# -----------------------------
# 🔧 App and Globals
# -----------------------------
app = FastAPI()
translator = Translator()
supported_langs = set(LANGUAGES.keys())
connected_devices = {}

# -----------------------------
# 🌐 CORS Configuration
# -----------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------
# 🔠 Language Mapping
# -----------------------------
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
    "Assamese": ("as-IN", "as", "as"),
    "Odia": ("or-IN", "or", "or"),
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

# -----------------------------
# 🚨 Error Handling
# -----------------------------
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": exc.errors()})

# -----------------------------
# ✅ Health Check
# -----------------------------
@app.get("/")
async def root():
    return {"status": "✅ Swadeshi Voice Translator backend is running."}

# -----------------------------
# 🔄 WebSocket Translation
# -----------------------------
@app.websocket("/ws/{src}/{tgt}/{device_id}")
async def translate_ws(websocket: WebSocket, src: str, tgt: str, device_id: str):
    device_id = device_id.replace(" ", "_")
    await websocket.accept()
    print(f"🔌 Connected: {device_id} ({src}→{tgt})")

    src_locale, _, src_code = language_map.get(src, ("hi-IN", "hi", "hi"))
    _, tgt_tts_lang, tgt_code = language_map.get(tgt, ("hi-IN", "hi", "hi"))

    connected_devices[device_id] = websocket
    recognizer = sr.Recognizer()

    try:
        while True:
            try:
                msg = await websocket.receive()
            except WebSocketDisconnect:
                print(f"❌ Disconnected: {device_id}")
                break
            except WebSocketException as e:
                print(f"❌ WS error for {device_id}: {e}")
                break

            if "bytes" in msg:
                audio = msg["bytes"]
                with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as f:
                    f.write(audio)
                    webm_path = f.name
                wav_path = webm_path.replace(".webm", ".wav")

                try:
                    AudioSegment.from_file(webm_path).export(wav_path, format="wav")
                    with sr.AudioFile(wav_path) as src_audio:
                        audio_data = recognizer.record(src_audio)
                    text = recognizer.recognize_google(audio_data, language=src_locale)
                    print(f"🗣 STT: {text}")
                except Exception as e:
                    await websocket.send_text(f"❌ STT failed: {e}")
                    continue
                finally:
                    with suppress(Exception):
                        os.remove(webm_path)
                        os.remove(wav_path)

            elif "text" in msg:
                try:
                    payload = json.loads(msg["text"])
                    if payload.get("type") == "text":
                        text = payload["data"]
                        print(f"📝 Text: {text}")
                    else:
                        await websocket.send_text("❌ Unsupported message type")
                        continue
                except json.JSONDecodeError:
                    await websocket.send_text("❌ Invalid JSON")
                    continue
            else:
                await websocket.send_text("❌ Unknown message format")
                continue

            if src_code not in supported_langs:
                src_code = "hi"
            if tgt_code not in supported_langs:
                tgt_code, tgt_tts_lang = "hi", "hi"
                await websocket.send_text("⚠️ Fallback to Hindi")

            try:
                translated = translator.translate(text, src=src_code, dest=tgt_code).text
                print(f"🌍 Translated: {translated}")
                await websocket.send_text(json.dumps({"type":"text","data":translated}))
            except Exception as e:
                await websocket.send_text(f"❌ Translation failed: {e}")
                continue

            try:
                tts = gTTS(text=translated, lang=tgt_tts_lang)
                buf = io.BytesIO()
                tts.write_to_fp(buf)
                buf.seek(0)
                await websocket.send_bytes(buf.read())
                print(f"🔊 TTS sent to {device_id}")
            except Exception as e:
                await websocket.send_text(f"❌ TTS failed: {e}")

    finally:
        connected_devices.pop(device_id, None)
        print(f"🧹 Cleaned up: {device_id}")

# -----------------------------
# Catch-all WebSocket route for debugging
# -----------------------------
@app.websocket("/ws/{path:path}")
async def catch_all_ws(websocket: WebSocket, path: str):
    await websocket.accept()
    print(f"🧪 Catch-all WS connected: {path}")
    await websocket.send_text(f"Hello from catch-all WS route: {path}")
    await websocket.close()

# -----------------------------
# 📝 REST Translation
# -----------------------------
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
        result = translator.translate(req.text, src=src_code, dest=tgt_code).text
        print(f"✅ REST Translated: {result}")
        return {"translated_text": result}
    except Exception as e:
        return {"error": f"Translation failed: {e}"}

# -----------------------------
# Startup Event
# -----------------------------
@app.on_event("startup")
async def startup_event():
    print("🚀 FastAPI app started.")
    print(f"Listening on port: {os.environ.get('PORT', '10000')}")

# -----------------------------
# ▶️ Run Server (Dev & Deploy)
# -----------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
