import asyncio, edge_tts

async def _go(text, out, voice, rate):
    await edge_tts.Communicate(text, voice, rate=rate).save(out)

def speak(text, out="audio.mp3", voice="en-IN-NeerjaNeural", rate="+0%"):
    asyncio.run(_go(text, out, voice, rate))
    return out
