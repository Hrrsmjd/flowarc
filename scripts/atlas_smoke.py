"""Run every Atlas query once against the real cluster, on throwaway samples.

Usage: python scripts/atlas_smoke.py   (after setup_atlas.py; needs MONGODB_URI, GEMINI_API_KEY)
Inserts three `smoke-*` samples and a repair, waits for the search indexes to catch up,
prints each result, then deletes what it inserted.
"""

import time

from flowarc import concepts, store
from flowarc.sample import Sample

SAMPLES = [
    ("heron", "animals and organic forms", "A wading bird with long thin legs and a long neck."),
    (
        "teapot",
        "furniture and everyday objects",
        "A round pot with a curved spout and a handle loop.",
    ),
    ("pagoda", "buildings and structures", "A five-tier tower with flared eaves on every level."),
]


def step(name, fn):
    try:
        print(f"ok   {name}: {fn()}")
    except Exception as e:  # noqa: BLE001 -- report every query, not just the first failure
        print(f"FAIL {name}: {type(e).__name__}: {e}")


INDEXES = {
    "samples": [store.VECTOR_INDEX, store.SEMANTIC_INDEX, store.TEXT_INDEX],
    "repairs": [store.REPAIR_SEMANTIC_INDEX, store.REPAIR_TEXT_INDEX],
    "logs": [store.LOG_INDEX],
}


def wait_for_indexes(d, minutes: int = 15) -> None:
    """Search indexes build in the background (the first one also starts Atlas's search
    process), and queries fail until they are READY."""
    for _ in range(minutes * 4):
        state = {
            name: i.get("status", "?")
            for coll in INDEXES
            for i in d[coll].list_search_indexes()
            if (name := i["name"]) in INDEXES[coll]
        }
        missing = [n for names in INDEXES.values() for n in names if n not in state]
        if missing:
            raise SystemExit(f"missing indexes {missing}: run scripts/setup_atlas.py first")
        if all(v == "READY" for v in state.values()):
            return
        print("waiting for indexes:", ", ".join(f"{k} {v}" for k, v in state.items()))
        time.sleep(15)
    raise SystemExit(f"indexes not READY after {minutes} min; check Atlas Search in the UI")


def main():
    d = store.db()
    if d is None:
        raise SystemExit("set MONGODB_URI in .env")
    wait_for_indexes(d)
    for i, (name, bucket, desc) in enumerate(SAMPLES):
        s = Sample(id=f"smoke-{i}", concept={"name": name, "bucket": bucket, "description": desc})
        concepts.check_novelty(s)
        s.save()
    s = Sample(id="smoke-0", stage="mesh")
    rid = s.record_repair("mesh has two holes in the tail", "voxel remesh at 256")
    s.repair_outcome(rid, True)
    print("waiting 30 s for search indexes and Automated Embedding...")
    time.sleep(30)
    try:
        step("vector novelty", lambda: store.nearest(d.samples.find_one()["embedding"], 2))
        step("facets", store.facets)
        step("text search", lambda: store.search("bird legs"))
        step("autocomplete", lambda: store.autocomplete("her"))
        step("semantic (voyage)", lambda: store.semantic("a tall building", 2))
        step("hybrid", lambda: store.hybrid("long legged bird", 2))
        step("failure memory", lambda: store.past_fixes("holes in the wing", "mesh"))
        step("log search", lambda: store.search_log("watertight novelty"))
        step("metrics", lambda: store.metrics(10))
    finally:
        d.samples.delete_many({"_id": {"$regex": "^smoke-"}})
        d.logs.delete_many({"sample": {"$regex": "^smoke-"}})
        d.repairs.delete_many({"sample": {"$regex": "^smoke-"}})


if __name__ == "__main__":
    main()
