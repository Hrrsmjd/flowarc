"""One sample's record: its state, check results and log, saved as JSON in its folder.

The set of these folders is the dataset registry. Every write goes to disk, so a crashed
run can resume from the last finished stage.
"""

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from flowarc import config

STAGES = ["concept", "images", "mesh", "sim", "render", "package"]


@dataclass
class Sample:
    id: str
    stage: str = "concept"  # next stage to run
    status: str = "pending"  # pending | running | done | failed | flagged
    concept: dict = field(default_factory=dict)
    checks: dict = field(default_factory=dict)  # stage -> list of check results
    attempts: dict = field(default_factory=dict)  # stage -> tries so far
    meta: dict = field(default_factory=dict)  # solver config, costs, justification, ...

    @property
    def dir(self) -> Path:
        return config.DATA / "samples" / self.id

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / "sample.json.tmp"
        tmp.write_text(json.dumps(asdict(self), indent=2))
        tmp.replace(self.dir / "sample.json")

    def log(self, msg: str, **data) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.dir / "log.jsonl", "a") as f:
            f.write(json.dumps({"t": time.time(), "stage": self.stage, "msg": msg, **data}) + "\n")

    def record_check(self, name: str, passed: bool, **values) -> bool:
        self.checks.setdefault(self.stage, []).append({"name": name, "passed": passed, **values})
        self.log(f"check {name}: {'pass' if passed else 'FAIL'}", **values)
        return passed

    @classmethod
    def load(cls, sample_id: str) -> "Sample":
        path = config.DATA / "samples" / sample_id / "sample.json"
        return cls(**json.loads(path.read_text()))


def all_samples() -> list[Sample]:
    root = config.DATA / "samples"
    if not root.exists():
        return []
    return [Sample.load(p.name) for p in sorted(root.iterdir()) if (p / "sample.json").exists()]
