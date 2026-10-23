"""One sample's record: its state, check results and log.

The set of these records is the dataset registry. It lives in MongoDB Atlas when MONGODB_URI
is set (see store.py), otherwise as JSON in each sample folder. Every write is persisted, so a
crashed run can resume from the last finished stage.
"""

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from flowarc import config, store

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
    embedding: list[float] = field(default_factory=list)  # concept description embedding

    @property
    def dir(self) -> Path:
        """Where this sample's files (images, mesh, simulation output) go."""
        return config.DATA / "samples" / self.id

    def save(self) -> None:
        if (d := store.db()) is not None:
            d.samples.replace_one({"_id": self.id}, {"_id": self.id, **asdict(self)}, upsert=True)
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / "sample.json.tmp"
        tmp.write_text(json.dumps(asdict(self), indent=2))
        tmp.replace(self.dir / "sample.json")

    def log(self, msg: str, **data) -> None:
        entry = {"t": time.time(), "stage": self.stage, "msg": msg, **data}
        if (d := store.db()) is not None:
            d.logs.insert_one({"sample": self.id, **entry})
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.dir / "log.jsonl", "a") as f:
            f.write(json.dumps(entry) + "\n")

    def record_check(self, name: str, passed: bool, **values) -> bool:
        self.checks.setdefault(self.stage, []).append({"name": name, "passed": passed, **values})
        self.log(f"check {name}: {'pass' if passed else 'FAIL'}", **values)
        return passed

    @classmethod
    def load(cls, sample_id: str) -> "Sample":
        if (d := store.db()) is not None:
            doc = d.samples.find_one({"_id": sample_id})
            if doc is None:
                raise KeyError(sample_id)
            doc.pop("_id")
            return cls(**doc)
        path = config.DATA / "samples" / sample_id / "sample.json"
        return cls(**json.loads(path.read_text()))


def all_samples() -> list[Sample]:
    if (d := store.db()) is not None:
        return [
            Sample(**{k: v for k, v in doc.items() if k != "_id"})
            for doc in d.samples.find().sort("_id")
        ]
    root = config.DATA / "samples"
    if not root.exists():
        return []
    return [Sample.load(p.name) for p in sorted(root.iterdir()) if (p / "sample.json").exists()]


def nearest(vector: list[float], k: int = 5, exclude: str | None = None) -> list[dict]:
    """Closest non-failed samples to an embedding: [{id, name, similarity}], best first."""
    if store.db() is not None:
        return [r for r in store.nearest(vector, k + 1) if r["id"] != exclude][:k]
    v = np.asarray(vector, float)
    rows = []
    for s in all_samples():
        if s.id == exclude or not s.embedding or s.status == "failed":
            continue
        e = np.asarray(s.embedding, float)
        sim = float(v @ e / (np.linalg.norm(v) * np.linalg.norm(e)))
        rows.append({"id": s.id, "name": s.concept.get("name"), "similarity": sim})
    return sorted(rows, key=lambda r: -r["similarity"])[:k]


def coverage() -> dict[str, int]:
    """Non-failed samples per taxonomy bucket."""
    if store.db() is not None:
        return store.coverage()
    counts = {}
    for s in all_samples():
        if s.status != "failed":
            b = s.concept.get("bucket")
            counts[b] = counts.get(b, 0) + 1
    return counts
