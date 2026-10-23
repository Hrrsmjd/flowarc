"""Stage 2: four near-orthographic reference views on white, each conditioned on the first."""

VIEWS = ["three-quarter", "front", "side", "top"]


def generate_views(sample) -> dict[str, bytes]:
    raise NotImplementedError


def check_consistency(sample, views: dict[str, bytes]) -> dict:
    """Flash compares the views: same object, part count and proportions."""
    raise NotImplementedError
