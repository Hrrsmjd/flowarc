"""Stage 1: propose objects that fill gaps in the dataset, with flow conditions."""

import math
import random

import numpy as np

from flowarc import gemini, sample

TAXONOMY = [
    "animals and organic forms",
    "vehicles (land, air, sea, fictional, any era)",
    "buildings and structures",
    "furniture and everyday objects",
    "sports gear and tools",
    "plants",
    "abstract or parametric shapes",
    "machines and industrial equipment",
    "aircraft, rockets and drones",
    "musical instruments",
    "electronics and appliances",
    "toys and games",
    "food",
    "insects and small creatures",
    "rocks, ice and natural formations",
    "bones, shells and fossils",
    "sculpture and art",
]

RE_RANGE = (1e2, 1e5)  # where the solver checks pass; above this Re is nominal (no wall model)
RE_TURBULENT, TURBULENT_SHARE = 1e4, 0.8
# Max cosine similarity to any existing sample or batch-mate. To be tuned on real
# gemini-embedding-2 output once the first batch exists.
NOVELTY = 0.88

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
- holes: how many through-holes the solid has (a mug handle is 1, a ring is 1, a shark is 0)

Before you settle on an object, call search_registry with a short description of it (and its bucket) to see the closest samples we already have. Drop or change ideas that are already covered."""


def search_registry(query: str, bucket: str = "") -> list[dict]:
    return sample.find_similar(query, k=5, bucket=bucket or None)


SEARCH_TOOL = gemini.tool(
    search_registry,
    "Search the dataset for existing samples similar to an object idea (hybrid keyword and"
    " semantic search). Returns up to 5 matches with name, bucket and description.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "the object idea, shape words only"},
            "bucket": {"type": "string", "enum": TAXONOMY + [""]},
        },
        "required": ["query"],
    },
)


def coverage() -> dict[str, int]:
    """Samples per bucket, including empty ones (Atlas aggregation when connected)."""
    c = sample.coverage()
    return {b: c.get(b, 0) for b in TAXONOMY}


def propose(n: int) -> list[dict]:
    """Ask Argon for n new concepts aimed at under-covered buckets."""
    names = [s.concept["name"] for s in sample.all_samples() if s.concept.get("name")][-300:]
    prompt = PROMPT.format(
        coverage="\n".join(f"- {b}: {k}" for b, k in coverage().items()),
        existing=", ".join(names) or "none yet",
        n=n,
    )
    return gemini.argon(prompt, schema=SCHEMA, thinking="medium", tools=[SEARCH_TOOL])["concepts"]


def flow_conditions(rng: random.Random) -> dict:
    """Most samples are turbulent (Re 1e4 and up, more to see in the wake); a fifth are laminar."""
    lo, mid, hi = math.log10(RE_RANGE[0]), math.log10(RE_TURBULENT), math.log10(RE_RANGE[1])
    lo = mid if rng.random() < TURBULENT_SHARE else lo
    hi = hi if lo == mid else mid
    return {
        "reynolds": round(10 ** rng.uniform(lo, hi), -1),
        "yaw_deg": rng.choice([0, 0, 0, 10, 20]),
    }


def describe(concept: dict) -> str:
    """The text that gets embedded for the novelty check."""
    return f"{concept.get('name', '')}: {concept.get('description', '')}".strip(": ")


def similarity(a: list[float], others: list[list[float]]) -> float:
    if not others:
        return 0.0
    a, b = np.asarray(a), np.asarray(others)
    return float((b @ a / (np.linalg.norm(b, axis=1) * np.linalg.norm(a))).max())


def is_novel(
    embedding: list[float], existing: list[list[float]], threshold: float = NOVELTY
) -> bool:
    """Reject concepts whose description embedding is too close to an existing one."""
    return similarity(embedding, existing) < threshold


def registry_similarity(embedding: list[float]) -> float:
    """Cosine similarity to the closest sample in the registry (Atlas Vector Search)."""
    near = sample.nearest(embedding, k=1)
    return near[0]["similarity"] if near else 0.0


def select(n: int, seed: int | None = None, threshold: float = NOVELTY) -> list[dict]:
    """Propose twice as many as needed and keep the n most novel, with flow conditions.

    Each candidate is checked against the registry and against the ones already picked in
    this batch. Returned concepts carry `embedding` and `similarity`; the caller moves the
    embedding onto `Sample.embedding`.
    """
    rng = random.Random(seed)
    cands = propose(2 * n)
    embs = gemini.embed([describe(c) for c in cands])
    scored = sorted(
        ((registry_similarity(e), c, e) for c, e in zip(cands, embs)), key=lambda t: t[0]
    )
    picked, batch = [], []
    for sim, c, e in scored:
        if len(picked) == n:
            break
        if sim < threshold and is_novel(e, batch, threshold):
            batch.append(e)
            sim = max(sim, similarity(e, batch[:-1]))
            picked.append({**c, **flow_conditions(rng), "embedding": e, "similarity": sim})
    return picked


def check_novelty(s: sample.Sample, threshold: float = NOVELTY) -> bool:
    """Embed the concept and fail it if it is too close to an existing sample.

    Stores the embedding on the sample (the caller saves it), so later concepts are checked
    against this one through Atlas Vector Search.
    """
    s.embedding = gemini.embed([describe(s.concept)])[0]
    near = sample.nearest(s.embedding, k=3, exclude=s.id)
    top = near[0]["similarity"] if near else 0.0
    return s.record_check(
        "novelty",
        top < threshold,
        similarity=round(top, 4),
        nearest=[{"id": r["id"], "name": r["name"]} for r in near],
    )
