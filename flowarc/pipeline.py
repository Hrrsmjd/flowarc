"""Runs samples through the stages. Each stage checks its output; failures go to Argon."""

from flowarc.sample import STAGES, Sample


def advance(sample: Sample) -> None:
    """Move the sample to the next stage after its current one passes."""
    i = STAGES.index(sample.stage)
    sample.stage = STAGES[i + 1] if i + 1 < len(STAGES) else "done"
    sample.save()
