"""Stage 5: 10 s, 30 fps, 1080p loop of Q-criterion vortex surfaces; Flash reviews it."""

import subprocess
from pathlib import Path

from flowarc import gemini

ITEMS = ["body_framed", "flow_visible", "no_artifacts"]
_ITEM = {
    "type": "object",
    "properties": {"passed": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["passed", "reason"],
}
SCHEMA = {
    "type": "object",
    "properties": {**{k: _ITEM for k in ITEMS}, "summary": {"type": "string"}},
    "required": [*ITEMS, "summary"],
}
PROMPT = """These are 3 frames (start, middle, end) of a CFD video: air flowing past a {name} \
(dark grey), with vortex surfaces in teal (red where the flow is fast). The Reynolds number is \
{re:g}. Check each item and give a short reason:
- body_framed: the whole object is in frame, not cut off, and takes up at least a fifth of the width.
- flow_visible: vortex surfaces show around or behind the object. Below Re 1000 a smooth thin \
shell and a short wake are normal; fail only if almost nothing shows.
- no_artifacts: no blank frames, no noise filling the box, no surfaces stuck to the box edges, no stripes."""


def frames(video: Path, times=(1.0, 5.0, 9.5)) -> list[bytes]:
    cmd = ["ffmpeg", "-v", "error", "-ss", "", "-i", str(video), "-frames:v", "1"]
    cmd += ["-vf", "scale=960:-1", "-f", "image2pipe", "-vcodec", "mjpeg", "-"]
    out = []
    for t in times:
        cmd[4] = str(t)
        out.append(subprocess.run(cmd, check=True, capture_output=True).stdout)
    return out


def review(video: Path, concept: dict) -> dict:
    parts = [{"type": "text", "text": PROMPT.format(name=concept["name"], re=concept["reynolds"])}]
    parts += [gemini.image_part(f) for f in frames(video)]
    out = gemini.ask(parts, schema=SCHEMA)
    failed = [k for k in ITEMS if not out[k]["passed"]]
    return {"passed": not failed, "failed": failed, "summary": out["summary"], "items": out}
