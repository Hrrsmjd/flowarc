"""Stage 2: four near-orthographic reference views on white, each conditioned on the first."""

from flowarc import gemini

VIEWS = ["three-quarter", "front", "side", "top"]

CAMERA = {
    "three-quarter": "three-quarter view from the front left and slightly above",
    "front": "straight-on front view, orthographic",
    "side": "straight-on left side view, orthographic",
    "top": "straight-down top view, orthographic",
}

BASE = (
    "Product photo of {description} One single solid object, whole and centred, filling most of the frame. "
    "Plain pure white background, no ground, no shadow, no text, no other objects. Matte grey clay material. {camera}."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "consistent": {"type": "boolean"},
        "bad_views": {"type": "array", "items": {"type": "string", "enum": VIEWS}},
        "reason": {"type": "string"},
    },
    "required": ["consistent", "bad_views", "reason"],
}


def generate_view(concept: dict, view: str, ref: bytes | None = None) -> bytes:
    prompt = BASE.format(description=concept["description"], camera=CAMERA[view])
    if ref:
        prompt += " Show exactly the same object as the reference image, same parts and proportions, from this new camera."
    return gemini.generate_image(prompt, refs=[ref] if ref else [])


def generate_views(concept: dict) -> dict[str, bytes]:
    first = generate_view(concept, VIEWS[0])
    return {VIEWS[0]: first, **{v: generate_view(concept, v, first) for v in VIEWS[1:]}}


def check_consistency(concept: dict, views: dict[str, bytes]) -> dict:
    """Flash compares the views: same object, part count and proportions."""
    parts = [
        {
            "type": "text",
            "text": f"These are {', '.join(views)} views of: {concept['description']}\n"
            "Check that every view shows the same single object with the same parts and proportions, "
            "on a plain white background, from the named camera. List the views that are wrong.",
        }
    ]
    for v, img in views.items():
        parts += [{"type": "text", "text": f"{v} view:"}, gemini.image_part(img)]
    return gemini.argon(parts, schema=SCHEMA)


def make_views(concept: dict, attempts: int = 3) -> tuple[dict[str, bytes], dict]:
    """Generate the four views, then redo the ones the check flags, up to `attempts` checks."""
    views = generate_views(concept)
    for _ in range(attempts):
        review = check_consistency(concept, views)
        bad = [v for v in review["bad_views"] if v != VIEWS[0]]
        if review["consistent"] or not bad:
            break
        for v in bad:
            views[v] = generate_view(concept, v, views[VIEWS[0]])
    return views, review
