"""Argon decides what to do when a stage fails its checks.

It sees the failed checks (with Flash's summary where there is one), the error if the stage
crashed, this sample's earlier repairs and similar failures fixed before (Atlas hybrid search
over the `repairs` collection), then picks one of the stage's actions. The choice is logged
with `record_repair`, and its outcome once the stage is re-checked, so later failures can
learn from it. If Argon can't be reached, the fixed policy from before is used.
"""

import json
from pathlib import Path

from flowarc import config, gemini
from flowarc.sample import Sample, repair_context

# action -> what it does; "back_to" sends the sample to an earlier stage
ACTIONS = {
    "retry": "run the stage again as it is (the mesh gets a new seed)",
    "repair_mesh": "reuse the last raw mesh, remesh it watertight and re-check, no new generation",
    "redraw_views": "redraw the four reference views, optionally from a revised description",
    "redo_mesh": "generate a new mesh from the same views",
    "give_up": "stop: this concept won't make a usable sample",
}
STAGE_ACTIONS = {
    "mesh": ["retry", "repair_mesh", "redraw_views", "give_up"],
    "sim": ["retry", "redo_mesh", "give_up"],
}
BACK_TO = {"redraw_views": "images", "redo_mesh": "mesh"}

PROMPT = """You run a pipeline that turns invented shapes into flow simulations.
Sample {id}, concept "{name}": {description}
Stage "{stage}" failed (attempt {attempt} of {max_attempts}).

Checks from this attempt:
{checks}
{error}
Earlier repairs on this sample:
{history}
{past}
Attempts used per stage: {attempts}; limits: {limits}.

Diagnose the failure in one or two sentences, then choose one action:
{actions}
If you redraw the views you may give a revised description (a simpler or sturdier version of the
same idea, e.g. thicker fins); leave it empty to keep the current one. Give up only when the
concept can't work or the attempts left can't fix it."""


def schema(actions: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "diagnosis": {"type": "string"},
            "action": {"type": "string", "enum": actions},
            "fix": {"type": "string", "description": "the change, in a few words"},
            "description": {"type": "string"},
        },
        "required": ["diagnosis", "action", "fix"],
    }


def evidence(checks: list[dict], error: str | None) -> str:
    """The failure as text: failed checks first, then the error. Also the past-fixes query."""
    failed = [c for c in checks if not c["passed"]]
    parts = [f"{c['name']}: {c.get('summary') or ''}".strip() for c in failed]
    return "; ".join(parts + ([error] if error else [])) or "stage failed without a check"


def decide(s: Sample, stage: str, checks: list[dict], error: str | None) -> dict:
    actions = STAGE_ACTIONS.get(stage, ["retry", "give_up"])
    past = repair_context(evidence(checks, error), stage)
    prompt = PROMPT.format(
        id=s.id,
        name=s.concept.get("name"),
        description=s.concept.get("description"),
        stage=stage,
        attempt=s.attempts.get(stage, 0),
        max_attempts=config.MAX_ATTEMPTS.get(stage, 1),
        checks=json.dumps(checks, default=str, indent=1) if checks else "(none recorded)",
        error=f"The stage crashed: {error}\n" if error else "",
        history="\n".join(f"- {r}" for r in s.meta.get("repairs", [])) or "(none)",
        past=past or "No similar failures have been fixed before.",
        attempts=json.dumps(s.attempts),
        limits=json.dumps(config.MAX_ATTEMPTS),
        actions="\n".join(f"- {a}: {ACTIONS[a]}" for a in actions),
    )
    return gemini.argon(prompt, schema=schema(actions))


MESH_CALLS = {
    "accept": "keep this mesh as it is",
    "thicken": "thicken the thin parts by about one grid cell, on this same mesh",
    "new_mesh": "make a new mesh",
}

JUDGE_PROMPT = """A mesh for a flow simulation passed its other checks. Decide about these:
{issues}
Concept "{name}": {description}
The grey renders of the mesh follow (flow comes from the front).

Say whether this shape is meant to be left-right mirror symmetric, judging from the concept and
the renders (a walrus lying on an ice floe, a twisted pretzel or a spiral are not). Then choose:
{actions}
Thin parts are below {cells:.0f} grid cells: the simulation can't resolve them, so they may leak or
vanish. Thickening them is right when the shape still reads the same (fins, blades, wires);
accept when losing them doesn't matter; ask for a new mesh only if the mesh is wrong."""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "symmetric": {"type": "boolean"},
        "decision": {"type": "string", "enum": list(MESH_CALLS)},
        "reason": {"type": "string"},
    },
    "required": ["symmetric", "decision", "reason"],
}


def judge_mesh(s: Sample, rep: dict, renders: Path, cells_thin: float) -> dict | None:
    """Argon's call on the symmetry and thin-parts checks. None if Argon is off or unreachable."""
    if not config.ARGON_REPAIR:
        return None
    issues = []
    if "symmetry" in rep["judgement"]:
        issues.append(
            f"- symmetry: the concept says symmetric, but the mesh differs from its mirror image by "
            f"{rep['symmetry']['chamfer']:.3f} of its length (the check allows 0.01)"
        )
    if "thin" in rep["judgement"]:
        issues.append(
            f"- thin parts: {rep['geometry']['thin_fraction']:.0%} of the surface is thinner than "
            f"{cells_thin:.0f} grid cells (the check allows 1%)"
        )
    text = JUDGE_PROMPT.format(
        issues="\n".join(issues),
        name=s.concept.get("name"),
        description=s.concept.get("description"),
        actions="\n".join(f"- {a}: {d}" for a, d in MESH_CALLS.items()),
        cells=cells_thin,
    )
    parts = [{"type": "text", "text": text}]
    for f in sorted(renders.glob("*.jpg")):
        parts += [{"type": "text", "text": f"render {f.stem}:"}, gemini.image_part(f.read_bytes())]
    try:
        d = gemini.argon(parts, schema=JUDGE_SCHEMA)
    except Exception as e:  # noqa: BLE001 - Gemini down: the checks stand as they are
        s.log(f"Argon mesh call unavailable: {e!r}", actor="argon")
        return None
    s.log(f"mesh {', '.join(rep['judgement'])}: {d['decision']} ({d['reason']})", actor="argon")
    return d


def fixed_policy(s: Sample, stage: str) -> dict:
    """The rule before Argon: after two failed meshes from the same views, redraw them."""
    redraw = stage == "mesh" and s.attempts.get("mesh", 0) % 2 == 0
    return {"action": "redraw_views" if redraw else "retry"}


def handle(s: Sample, stage: str, checks: list[dict], error: str | None = None) -> bool:
    """Choose and set up the next step after a failed stage. False means Argon gave up."""
    if not config.ARGON_REPAIR:
        return apply(s, stage, fixed_policy(s, stage))
    try:
        d = decide(s, stage, checks, error)
    except Exception as e:  # noqa: BLE001 - Gemini down or over its cap: keep the run going
        s.log(f"Argon repair unavailable, fixed policy: {e!r}", actor="argon")
        return apply(s, stage, fixed_policy(s, stage))
    note = f"{d['action']}: {d['fix']}" if d.get("fix") else d["action"]
    rid = s.record_repair(d["diagnosis"], note)
    s.meta.setdefault("repairs", []).append(f"{stage}: {d['diagnosis']} -> {note}")
    if d["action"] != "give_up":
        s.meta["open_repair"] = {"id": rid, "stage": stage}
    return apply(s, stage, d)


def apply(s: Sample, stage: str, d: dict) -> bool:
    a = d["action"]
    if a == "give_up":
        return False
    if a == "repair_mesh":
        s.meta["remesh"] = True
    if a == "redraw_views" and d.get("description"):
        s.concept.setdefault("original_description", s.concept.get("description"))
        s.concept["description"] = d["description"]
    s.stage = BACK_TO.get(a, stage)
    return True


def close_repair(s: Sample, stage: str, passed: bool) -> None:
    """Record whether the open repair fixed `stage`, once that stage has been re-checked."""
    r = s.meta.get("open_repair")
    if not r or r["stage"] != stage:
        return
    s.repair_outcome(r["id"], passed)
    s.log(f"Argon repair {'fixed' if passed else 'did not fix'} {stage}", actor="argon")
    del s.meta["open_repair"]
