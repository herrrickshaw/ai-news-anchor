# AI news anchor ("Sana"-style) for blog posts

blog post -> news script (Claude) -> voice (edge-tts, en-IN-NeerjaNeural) -> talking head (SadTalker on Colab) -> news overlay + scrolling ticker (ffmpeg) -> vertical 1080x1920 MP4.

## Run
    python3 -m venv .venv && .venv/bin/pip install edge-tts beautifulsoup4 pillow
    claude auth login                       # script step needs the claude CLI
    .venv/bin/python run.py --n 1           # stand-in mode: still portrait + slow push-in
    # real talking head:
    # 1. upload episodes/<slug>/audio.mp3 + portrait.png to colab/avatar_colab.ipynb, download anchor_raw.mp4
    # 2. .venv/bin/python run.py --n 1 --avatar anchor_raw.mp4

Replace `portrait.png` (currently a flat placeholder) with a front-facing AI-generated anchor face.
Label published videos as AI-generated.
