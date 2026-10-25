import subprocess

from flowarc import render


def test_frames_clamp_to_a_short_video(tmp_path):
    video = tmp_path / "v.mp4"
    cmd = ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=navy:s=64x64:r=30:d=2"]
    subprocess.run([*cmd, "-pix_fmt", "yuv420p", str(video)], check=True)
    out = render.frames(video, times=(0.5, 1.0, 9.5))
    assert len(out) == 3 and all(len(f) > 100 for f in out)
