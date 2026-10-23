"""Stage 1: propose objects that fill gaps in the dataset, with flow conditions."""

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


def propose(registry, n: int) -> list[dict]:
    """Ask Argon for n new concepts aimed at under-covered buckets."""
    raise NotImplementedError


def is_novel(concept: dict, registry, threshold: float) -> bool:
    """Reject concepts whose description embedding is too close to an existing sample."""
    raise NotImplementedError
