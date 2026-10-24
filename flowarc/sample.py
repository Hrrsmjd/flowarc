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
        """Atlas when set, and always the RDS copy, so losing Atlas never loses the run."""
        if (d := store.db()) is not None:
            d.samples.replace_one({"_id": self.id}, {"_id": self.id, **asdict(self)}, upsert=True)
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / "sample.json.tmp"
        tmp.write_text(json.dumps(asdict(self), indent=2))
        tmp.replace(self.dir / "sample.json")

    def log(self, msg: str, **data) -> None:
        entry = {"t": time.time(), "stage": self.stage, "msg": msg, **data}
        if (d := store.db()) is not None:
            d.logs.insert_one({"sample": self.id, **entry})
            entry.pop("_id", None)
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.dir / "log.jsonl", "a") as f:
            f.write(json.dumps(entry) + "\n")

    def record_repair(self, diagnosis: str, action: str) -> str:
        """Note Argon's diagnosis and chosen fix for a failure at the current stage.

        Call `repair_outcome` once the stage is re-checked; fixes that worked are what
        `past_fixes` returns for later failures.
        """
        entry = {"sample": self.id, "stage": self.stage, "diagnosis": diagnosis, "action": action}
        self.log(f"repair: {action}", diagnosis=diagnosis)
        if (d := store.db()) is not None:
            return str(d.repairs.insert_one({**entry, "fixed": None, "t": time.time()}).inserted_id)
        rid = f"{self.id}-{time.time_ns()}"
        _append_repair({"id": rid, **entry, "fixed": None})
        return rid

    def repair_outcome(self, repair_id: str, fixed: bool) -> None:
        if (d := store.db()) is not None:
            from bson import ObjectId

            d.repairs.update_one({"_id": ObjectId(repair_id)}, {"$set": {"fixed": fixed}})
            return
        _append_repair({"id": repair_id, "fixed": fixed})

    def record_check(self, name: str, passed: bool, **values) -> bool:
        self.checks.setdefault(self.stage, []).append({"name": name, "passed": passed, **values})
        self.log(
            f"check {name}: {'pass' if passed else 'FAIL'}", check=name, passed=passed, **values
        )
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


def find_similar(text: str, k: int = 8, bucket: str | None = None) -> list[dict]:
    """Samples like `text`: Atlas hybrid search, or word overlap when offline."""
    if store.db() is not None:
        return store.hybrid(text, k, bucket)
    words = set(text.lower().split())
    rows = []
    for s in all_samples():
        c = s.concept
        if s.status == "failed" or (bucket and c.get("bucket") != bucket):
            continue
        hits = len(words & set(f"{c.get('name', '')} {c.get('description', '')}".lower().split()))
        if hits:
            rows.append(
                {"id": s.id, "name": c.get("name"), "bucket": c.get("bucket"), "score": hits}
            )
    return sorted(rows, key=lambda r: -r["score"])[:k]


def _append_repair(entry: dict) -> None:
    config.DATA.mkdir(parents=True, exist_ok=True)
    with open(config.DATA / "repairs.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")


def past_fixes(diagnosis: str, stage: str, k: int = 5) -> list[dict]:
    """Fixes that worked for similar failures: Atlas hybrid search, or word overlap offline."""
    if store.db() is not None:
        return store.past_fixes(diagnosis, stage, k)
    path = config.DATA / "repairs.jsonl"
    repairs = {}
    for line in path.read_text().splitlines() if path.exists() else []:
        e = json.loads(line)
        repairs.setdefault(e["id"], {}).update(e)
    words = set(diagnosis.lower().split())
    rows = [
        (len(words & set(r["diagnosis"].lower().split())), r)
        for r in repairs.values()
        if r.get("stage") == stage and r.get("fixed") is True
    ]
    rows = sorted((t for t in rows if t[0]), key=lambda t: -t[0])[:k]
    return [
        {"sample": r["sample"], "diagnosis": r["diagnosis"], "action": r["action"]} for _, r in rows
    ]


def repair_context(diagnosis: str, stage: str, k: int = 3) -> str:
    """Past fixes as prompt text for Argon's repair decision ('' when there are none)."""
    fixes = past_fixes(diagnosis, stage, k)
    if not fixes:
        return ""
    lines = [f"- {f['diagnosis']} -> fixed by: {f['action']}" for f in fixes]
    return "Similar failures that were fixed before:\n" + "\n".join(lines)
