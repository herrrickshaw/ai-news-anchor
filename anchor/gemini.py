"""Gemini backends: script, anchor portrait, voice (TTS), and Veo idle clip.
Key is read from GEMINI_API_KEY / GOOGLE_API_KEY, else from the market-secrets credentials file (never printed).
Model ids can be overridden with env vars because Google renames preview models often."""
import json, os, pathlib, re, time, wave
from google import genai
from google.genai import types

MODELS = {
    "text":  os.getenv("GEMINI_TEXT_MODEL",  "gemini-3.8-flash"),
    "tts":   os.getenv("GEMINI_TTS_MODEL",   "gemini-3.8-flash-tts"),
    "image": os.getenv("GEMINI_IMAGE_MODEL", "imagen-4.0-generate-001"),
    "veo":   os.getenv("GEMINI_VEO_MODEL",   "veo-3.1-generate-001"),
}

def _key():
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        if os.getenv(k): return os.environ[k]
    f = pathlib.Path.home() / ".config/market-secrets/credentials.env"
    if f.exists():
        for line in f.read_text().splitlines():
            m = re.match(r"\s*(?:export\s+)?(GEMINI_API_KEY|GOOGLE_API_KEY)\s*=\s*['\"]?([^'\"\s]+)", line)
            if m: return m.group(2)
    raise SystemExit("No Gemini key found: set GEMINI_API_KEY")

_C = None
def client():
    global _C
    if _C is None: _C = genai.Client(api_key=_key())
    return _C

def _retry(fn, tries=6):
    from google.genai import errors
    for i in range(tries):
        try: return fn()
        except errors.ServerError as e:
            if i == tries - 1: raise
            time.sleep(5 * 2 ** i); print("Gemini busy, retrying...")

def write_script(prompt):
    r = _retry(lambda: client().models.generate_content(model=MODELS["text"], contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json")))
    return json.loads(r.text)

def portrait(out="portrait.png", desc="a poised South Asian woman in her early 30s, TV news anchor, dark blazer"):
    prompt = (f"Photorealistic front-facing studio portrait of a fictional AI news anchor, {desc}, "
              "shoulders-up, looking straight at camera, neutral mouth, soft newsroom lighting, plain navy backdrop. "
              "Not a real person. Vertical 9:16.")
    r = _retry(lambda: client().models.generate_images(model=MODELS["image"], prompt=prompt,
        config=types.GenerateImagesConfig(number_of_images=1, aspect_ratio="9:16")))
    pathlib.Path(out).write_bytes(r.generated_images[0].image.image_bytes)
    return out

def tts(text, out="audio.wav", voice="Aoede"):
    r = _retry(lambda: client().models.generate_content(model=MODELS["tts"],
        contents=f"Read this as a calm, authoritative TV news anchor: {text}",
        config=types.GenerateContentConfig(response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))))))
    pcm = next(p.inline_data.data for p in r.parts if p.inline_data)
    with wave.open(out, "wb") as w:        # Gemini TTS returns 24 kHz mono 16-bit PCM
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(pcm)
    return out

def veo_idle_clip(portrait_path, out="anchor_veo.mp4"):
    """Short clip of the anchor talking to camera. Veo clips are ~8s, so compose.py loops it under the
    real audio. This is NOT lip-synced to the script; use the Colab/SadTalker path for true lip-sync."""
    c = client()
    op = c.models.generate_videos(model=MODELS["veo"],
        source=types.GenerateVideosSource(
            prompt="The news anchor speaks calmly to camera with natural small head movements and blinks, no camera move, no on-screen text.",
            image=types.Image.from_file(location=portrait_path)),
        config=types.GenerateVideosConfig(number_of_videos=1, duration_seconds=8, aspect_ratio="9:16"))
    while not op.done:
        time.sleep(15); op = c.operations.get(op)
    v = op.response.generated_videos[0].video
    c.files.download(file=v); v.save(out)
    return out
