import runpy
import sys
import types
import wave

import pytest


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


@pytest.fixture
def gem(monkeypatch, tmp_path):
    """Import anchor.gemini against a fake google.genai."""
    calls = {"clients": [], "sleeps": []}
    genai = types.ModuleType("google.genai")
    types_m = types.ModuleType("google.genai.types")
    errors = types.ModuleType("google.genai.errors")

    class ServerError(Exception):
        pass

    errors.ServerError = ServerError
    for n in ("GenerateContentConfig", "GenerateImagesConfig", "SpeechConfig", "VoiceConfig",
              "PrebuiltVoiceConfig", "GenerateVideosSource", "GenerateVideosConfig"):
        setattr(types_m, n, (lambda n: lambda **kw: Obj(_n=n, **kw))(n))
    types_m.Image = Obj(from_file=lambda location: ("img", location))

    class Client:
        def __init__(self, api_key):
            calls["clients"].append(api_key)
            self.models = Obj()

    genai.Client = Client
    genai.types, genai.errors = types_m, errors
    google = types.ModuleType("google")
    google.genai = genai
    for k, v in {"google": google, "google.genai": genai, "google.genai.types": types_m,
                 "google.genai.errors": errors}.items():
        monkeypatch.setitem(sys.modules, k, v)
    sys.modules.pop("anchor.gemini", None)
    import anchor
    monkeypatch.delattr(anchor, "gemini", raising=False)
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    import importlib
    gemini = importlib.import_module("anchor.gemini")
    monkeypatch.setattr(gemini.pathlib.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(gemini.time, "sleep", lambda s: calls["sleeps"].append(s))
    monkeypatch.setattr(gemini, "_C", None)
    gemini.calls, gemini.ServerError = calls, ServerError
    yield gemini
    sys.modules.pop("anchor.gemini", None)


def test_key_env_priority(gem, monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "g")
    assert gem._key() == "g"
    monkeypatch.setenv("GEMINI_API_KEY", "m")
    assert gem._key() == "m"


def test_key_from_file(gem, tmp_path):
    f = tmp_path / ".config/market-secrets/credentials.env"
    f.parent.mkdir(parents=True)
    f.write_text("OTHER=1\n  export GOOGLE_API_KEY = 'abc123'\n")
    assert gem._key() == "abc123"


def test_key_missing_exits(gem):
    with pytest.raises(SystemExit):
        gem._key()
    f = gem.pathlib.Path.home() / ".config/market-secrets/credentials.env"
    f.parent.mkdir(parents=True)
    f.write_text("NOTHING=here\n")
    with pytest.raises(SystemExit):
        gem._key()


def test_client_cached(gem, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    a, b = gem.client(), gem.client()
    assert a is b and gem.calls["clients"] == ["k"]


def test_retry_backoff_and_giveup(gem):
    n = {"i": 0}

    def flaky():
        n["i"] += 1
        if n["i"] < 4:
            raise gem.ServerError()
        return "ok"

    assert gem._retry(flaky) == "ok"
    assert gem.calls["sleeps"] == [5, 10, 20]

    def always():
        raise gem.ServerError("down")

    gem.calls["sleeps"].clear()
    with pytest.raises(gem.ServerError):
        gem._retry(always, tries=3)
    assert gem.calls["sleeps"] == [5, 10]


def test_retry_does_not_swallow_other_errors(gem):
    def bad():
        raise KeyError("k")

    with pytest.raises(KeyError):
        gem._retry(bad)


def _client(gem, monkeypatch, **models):
    monkeypatch.setattr(gem, "_C", Obj(models=Obj(**models), files=Obj(), operations=Obj()))
    return gem._C


def test_write_script(gem, monkeypatch):
    seen = {}

    def gen(model, contents, config):
        seen.update(model=model, contents=contents, mime=config.response_mime_type)
        return Obj(text='{"script": "s"}')

    _client(gem, monkeypatch, generate_content=gen)
    assert gem.write_script("PROMPT") == {"script": "s"}
    assert seen == {"model": gem.MODELS["text"], "contents": "PROMPT", "mime": "application/json"}


def test_portrait_writes_bytes(gem, monkeypatch, tmp_path):
    seen = {}

    def gen(model, prompt, config):
        seen.update(prompt=prompt, n=config.number_of_images, ar=config.aspect_ratio)
        return Obj(generated_images=[Obj(image=Obj(image_bytes=b"PNG"))])

    _client(gem, monkeypatch, generate_images=gen)
    out = tmp_path / "p.png"
    assert gem.portrait(str(out), desc="DESC") == str(out)
    assert out.read_bytes() == b"PNG"
    assert "DESC" in seen["prompt"] and seen["n"] == 1 and seen["ar"] == "9:16"


def test_tts_writes_wav_skipping_non_audio_parts(gem, monkeypatch, tmp_path):
    pcm = b"\x01\x00" * 100

    def gen(model, contents, config):
        assert contents.endswith("hello") and config.response_modalities == ["AUDIO"]
        vc = config.speech_config.voice_config.prebuilt_voice_config
        assert vc.voice_name == "Zephyr"
        return Obj(parts=[Obj(inline_data=None), Obj(inline_data=Obj(data=pcm))])

    _client(gem, monkeypatch, generate_content=gen)
    out = tmp_path / "a.wav"
    gem.tts("hello", str(out), voice="Zephyr")
    seen_voice = []
    gem._C.models.generate_content = lambda model, contents, config: (
        seen_voice.append(config.speech_config.voice_config.prebuilt_voice_config.voice_name),
        Obj(parts=[Obj(inline_data=Obj(data=pcm))]))[1]
    gem.tts("hello", str(out))
    assert seen_voice == ["Aoede"]
    with wave.open(str(out)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (1, 2, 24000, 100)


def test_veo_polls_until_done(gem, monkeypatch, tmp_path):
    saved = {}

    class Video:
        def save(self, out):
            saved["out"] = out

    state = {"n": 0}

    def get(op):
        state["n"] += 1
        return Obj(done=state["n"] >= 2, response=Obj(generated_videos=[Obj(video=Video())]))

    c = _client(gem, monkeypatch, generate_videos=lambda model, source, config: Obj(done=False))
    c.operations.get = get
    c.files.download = lambda file: saved.setdefault("dl", file)
    assert gem.veo_idle_clip("p.png", out="o.mp4") == "o.mp4"
    assert saved["out"] == "o.mp4" and isinstance(saved["dl"], Video)
    assert gem.calls["sleeps"] == [15, 15]


def test_veo_already_done_no_sleep(gem, monkeypatch):
    class Video:
        def save(self, out):
            pass

    c = _client(gem, monkeypatch, generate_videos=lambda model, source, config: Obj(
        done=True, response=Obj(generated_videos=[Obj(video=Video())])))
    c.files.download = lambda file: None
    gem.veo_idle_clip("p.png")
    assert gem.calls["sleeps"] == []


# ---------- run.py ----------
@pytest.fixture
def runenv(monkeypatch, tmp_path):
    log = []
    fetch = types.ModuleType("anchor.fetch")
    fetch.fetch_posts = lambda blog, n: (log.append(("fetch", blog, n)),
                                         [{"title": "Hello, World! 2026", "text": "t"}])[1]
    scr = types.ModuleType("anchor.script")
    scr.write_script = lambda post, name, engine: (log.append(("script", name, engine)),
                                                   {"headline": "H", "ticker": "T", "script": "SCRIPT"})[1]
    tts = types.ModuleType("anchor.tts")
    tts.speak = lambda text, out, voice: (log.append(("speak", out.split("/")[-1], voice)), out)[1]
    ov = types.ModuleType("anchor.overlay")
    ov.make_overlay = lambda h, ch, date, path: log.append(("overlay", h, ch, path.split("/")[-1]))
    ov.make_ticker = lambda t, path: (path, 777)
    comp = types.ModuleType("anchor.compose")
    comp.compose = lambda audio, ovp, tp, tw, out, avatar_video, portrait: (
        log.append(("compose", audio.split("/")[-1], tw, avatar_video, portrait)), out)[1]
    gem = types.ModuleType("anchor.gemini")
    gem.portrait = lambda p: log.append(("g-portrait", p))
    gem.veo_idle_clip = lambda p: (log.append(("veo", p)), "veo.mp4")[1]

    def gtts(text, out):
        log.append(("g-tts", out.split("/")[-1]))
        return out

    gem.tts = gtts
    for m in (fetch, scr, tts, ov, comp, gem):
        monkeypatch.setitem(sys.modules, m.__name__, m)
    import anchor
    for m in (fetch, scr, tts, ov, comp, gem):
        monkeypatch.setattr(anchor, m.__name__.split(".")[1], m, raising=False)
    return log, gem, tts


def run_main(args, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run.py", "--out", str(tmp_path / "eps"), *args])
    import pathlib
    monkeypatch.chdir(pathlib.Path(__file__).resolve().parents[1])
    runpy.run_path("run.py", run_name="__main__")


def test_run_default_pipeline(runenv, tmp_path, monkeypatch, capsys):
    log, _, _ = runenv
    run_main([], tmp_path, monkeypatch)
    d = tmp_path / "eps" / "hello-world-2026"
    assert (d / "script.txt").read_text() == "SCRIPT"
    kinds = [x[0] for x in log]
    assert kinds == ["fetch", "script", "speak", "overlay", "compose"]
    assert log[0] == ("fetch", "https://masaladeutsch.blogspot.com", 1)
    assert log[1] == ("script", "Sana", "claude")
    assert log[2] == ("speak", "audio.mp3", "en-IN-NeerjaNeural")
    assert log[3] == ("overlay", "H", "SANA", "overlay.png")
    assert log[4] == ("compose", "audio.mp3", 777, None, "portrait.png")
    assert capsys.readouterr().out.strip().endswith("episode.mp4")


def test_run_gemini_tts_success_and_failure(runenv, tmp_path, monkeypatch, capsys):
    log, gem, _ = runenv
    run_main(["--tts", "gemini", "--script", "gemini", "--name", "Mia"], tmp_path, monkeypatch)
    assert ("g-tts", "audio.wav") in log and not any(x[0] == "speak" for x in log)
    assert ("script", "Mia", "gemini") in log and ("overlay", "H", "MIA", "overlay.png") in log
    log.clear()

    def boom(text, out):
        raise RuntimeError

    gem.tts = boom
    run_main(["--tts", "gemini"], tmp_path, monkeypatch)
    assert ("speak", "audio.mp3", "en-IN-NeerjaNeural") in log
    assert "Gemini TTS failed (RuntimeError), using edge-tts" in capsys.readouterr().out


def test_run_gemini_portrait_and_veo(runenv, tmp_path, monkeypatch):
    log, _, _ = runenv
    run_main(["--gemini-portrait", "--veo", "--portrait", "x.png"], tmp_path, monkeypatch)
    assert log[0] == ("g-portrait", "x.png") and log[1] == ("veo", "x.png")
    assert log[-1] == ("compose", "audio.mp3", 777, "veo.mp4", "x.png")


def test_run_veo_skipped_when_avatar_given(runenv, tmp_path, monkeypatch):
    log, _, _ = runenv
    run_main(["--veo", "--avatar", "mine.mp4"], tmp_path, monkeypatch)
    assert not any(x[0] == "veo" for x in log)
    assert log[-1][3] == "mine.mp4"


def test_run_slug_truncated_to_50(runenv, tmp_path, monkeypatch):
    log, _, _ = runenv
    sys.modules["anchor.fetch"].fetch_posts = lambda blog, n: [{"title": "ab " * 40, "text": "t"}]
    run_main([], tmp_path, monkeypatch)
    names = [p.name for p in (tmp_path / "eps").iterdir()]
    assert len(names) == 1 and len(names[0]) <= 50 and not names[0].endswith("-")


def test_run_slug_exactly_50(runenv, tmp_path, monkeypatch):
    sys.modules["anchor.fetch"].fetch_posts = lambda blog, n: [{"title": "a" * 60, "text": "t"}]
    run_main([], tmp_path, monkeypatch)
    assert [p.name for p in (tmp_path / "eps").iterdir()] == ["a" * 50]
