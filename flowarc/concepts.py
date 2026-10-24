"""Stage 1: propose objects that fill gaps in the dataset, with flow conditions."""

import math
import random
from collections import Counter

import numpy as np

from flowarc import gemini

TAXONOMY = [
    "animals and organic forms",
    "vehicles (land, air, sea, fictional, any era)",
    "buildings and structures",
    "furniture and everyday objects",
    "sports gear and tools",
    "plants",
    "abstract or parametric shapes",
    "combinations of the above",
]

RE_RANGE = (1e2, 1e5)  # where the solver checks pass; above this Re is nominal (no wall model)
RE_TURBULENT, TURBULENT_SHARE = 1e4, 0.8
NOVELTY = 0.88  # max cosine similarity to any existing description

SCHEMA = {
    "type": "object",
    "properties": {
        "concepts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "bucket": {"type": "string", "enum": TAXONOMY},
                    "description": {"type": "string"},
                    "ground": {"type": "boolean"},
                    "facing": {"type": "string"},
                    "symmetric": {"type": "boolean"},
                    "holes": {"type": "integer"},
                },
                "required": [
                    "name",
                    "bucket",
                    "description",
                    "ground",
                    "facing",
                    "symmetric",
                    "holes",
                ],
            },
        }
    },
    "required": ["concepts"],
}

PROMPT = """You pick objects for a CFD dataset that trains neural flow models. We want the widest spread of shapes and topologies: holes, thin parts, many parts, blunt and streamlined, tiny and huge features.

Buckets and how many samples each has so far:
{coverage}

Objects already in the dataset (do not repeat these or close variants):
{existing}

Propose {n} new objects, mostly from the least-covered buckets. For each give:
- name: a short name
- bucket: one of the buckets above
- description: 1-3 sentences on shape only (parts, proportions, holes), no colours or textures. It must be one solid, connected object with no loose parts and no part thinner than 1% of its length.
- ground: true if it rests on the ground (car, building), false if it is in free flow (bird, ball)
- facing: which side of the object faces into the wind, e.g. "nose first" or "broadside"
- symmetric: true if it has a left-right mirror plane
- holes: how many through-holes the solid has (a mug handle is 1, a ring is 1, a shark is 0)"""


def coverage(samples) -> dict[str, int]:
    c = Counter(s.concept.get("bucket") for s in samples)
    return {b: c.get(b, 0) for b in TAXONOMY}


def propose(samples, n: int) -> list[dict]:
    """Ask Argon for n new concepts aimed at under-covered buckets."""
    cov = coverage(samples)
    names = [s.concept["name"] for s in samples if s.concept.get("name")][-300:]
    prompt = PROMPT.format(
        coverage="\n".join(f"- {b}: {k}" for b, k in cov.items()),
        existing=", ".join(names) or "none yet",
        n=n,
    )
    return gemini.argon(prompt, schema=SCHEMA, thinking="medium")["concepts"]


def flow_conditions(rng: random.Random) -> dict:
    """Most samples are turbulent (Re 1e4 and up, more to see in the wake); a fifth are laminar."""
    lo, mid, hi = math.log10(RE_RANGE[0]), math.log10(RE_TURBULENT), math.log10(RE_RANGE[1])
    lo = mid if rng.random() < TURBULENT_SHARE else lo
    hi = hi if lo == mid else mid
    return {
        "reynolds": round(10 ** rng.uniform(lo, hi), -1),
        "yaw_deg": rng.choice([0, 0, 0, 10, 20]),
    }


def similarity(a: list[float], others: list[list[float]]) -> float:
    if not others:
        return 0.0
    a, b = np.asarray(a), np.asarray(others)
    return float((b @ a / (np.linalg.norm(b, axis=1) * np.linalg.norm(a))).max())


def is_novel(
    embedding: list[float], existing: list[list[float]], threshold: float = NOVELTY
) -> bool:
    """Reject concepts whose description embedding is too close to an existing sample."""
    return similarity(embedding, existing) < threshold


def select(samples, n: int, seed: int | None = None) -> list[dict]:
    """Propose twice as many as needed and keep the n most novel, with flow conditions."""
    rng = random.Random(seed)
    cands = propose(samples, 2 * n)
    embs = gemini.embed([c["description"] for c in cands])
    existing = [s.meta["embedding"] for s in samples if "embedding" in s.meta]
    picked = []
    for c, e in sorted(zip(cands, embs), key=lambda ce: similarity(ce[1], existing)):
        if len(picked) == n:
            break
        if is_novel(e, existing):
            existing.append(e)
            picked.append({**c, **flow_conditions(rng), "embedding": e})
    return picked
