"""Stage 1: propose objects that fill gaps in the dataset, with flow conditions."""

from flowarc import gemini
from flowarc.sample import Sample, nearest

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

RE_RANGE = (1e1, 1e7)  # upper end to be set by solver validation

# Cosine similarity above which a concept counts as a near-duplicate. To be tuned on real
# gemini-embedding-2 output once the first batch exists.
NOVELTY_THRESHOLD = 0.92


def propose(registry, n: int) -> list[dict]:
    """Ask Argon for n new concepts aimed at under-covered buckets."""
    raise NotImplementedError


def describe(concept: dict) -> str:
    """The text that gets embedded for the novelty check."""
    return f"{concept.get('name', '')}: {concept.get('description', '')}".strip(": ")


def check_novelty(sample: Sample, threshold: float = NOVELTY_THRESHOLD) -> bool:
    """Embed the concept and fail it if it is too close to an existing sample.

    Stores the embedding on the sample (the caller saves it), so later concepts are checked
    against this one through Atlas Vector Search.
    """
    sample.embedding = gemini.embed([describe(sample.concept)])[0]
    near = nearest(sample.embedding, k=3, exclude=sample.id)
    top = near[0]["similarity"] if near else 0.0
    return sample.record_check(
        "novelty",
        top < threshold,
        similarity=round(top, 4),
        nearest=[{"id": n["id"], "name": n["name"]} for n in near],
    )
