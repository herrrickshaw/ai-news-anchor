import subprocess, json

def duration(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", p],
                       capture_output=True, text=True)
    return float(json.loads(r.stdout)["format"]["duration"])

def compose(audio, overlay, ticker, ticker_w, out, avatar_video=None, portrait=None, size=(1080, 1920)):
    W, H = size; dur = duration(audio)
    if avatar_video:   # talking-head clip from the Colab notebook, cropped to fill the frame
        base = ["-stream_loop", "-1", "-i", avatar_video]
        bg = f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1[bg]"
    else:              # stand-in: portrait with a slow push-in so the pipeline is testable without a GPU
        base = ["-loop", "1", "-t", f"{dur:.2f}", "-i", portrait]
        bg = (f"[0:v]scale={W*2}:{H*2}:force_original_aspect_ratio=increase,crop={W*2}:{H*2},"
              f"zoompan=z='1+0.0004*on':d=1:s={W}x{H}:fps=25,setsar=1[bg]")
    speed = 140  # px/s
    fc = (f"{bg};[bg][2:v]overlay=0:0[a];"
          f"[a][3:v]overlay=x='-mod(t*{speed},{ticker_w//4})':y={H-110}[v]")
    cmd = ["ffmpeg", "-y", *base, "-i", audio, "-i", overlay, "-loop", "1", "-i", ticker,
           "-filter_complex", fc, "-map", "[v]", "-map", "1:a", "-t", f"{dur:.2f}",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "25", "-c:a", "aac", "-shortest", out]
    subprocess.run(cmd, check=True, capture_output=True)
    return out
