"""MongoDB Atlas: the dataset registry and the concept vector index.

With MONGODB_URI set, Atlas is the source of truth. Samples, their logs and their concept
embeddings live there, so every GPU worker and the dashboard share one registry. Without it
(tests, offline work) the registry falls back to JSON files in each sample folder.

Collections: `samples` (one document per sample, _id = sample id) and `logs` (one per event).
"""

from functools import cache

from flowarc import config

VECTOR_INDEX = "concept_vectors"


@cache
def db():
    """The Atlas database, or None when MONGODB_URI is not set."""
    if not config.MONGODB_URI:
        return None
    from pymongo import MongoClient

    return MongoClient(config.MONGODB_URI, appname="flowarc")[config.MONGODB_DB]


def ensure_indexes(dims: int) -> None:
    """Create the query indexes and the vector search index (idempotent)."""
    from pymongo.operations import SearchIndexModel

    d = db()
    d.samples.create_index([("stage", 1), ("status", 1)])
    d.samples.create_index("concept.bucket")
    d.logs.create_index([("sample", 1), ("t", 1)])
    if VECTOR_INDEX in {i["name"] for i in d.samples.list_search_indexes()}:
        return
    fields = [
        {"type": "vector", "path": "embedding", "numDimensions": dims, "similarity": "cosine"}
    ]
    fields += [{"type": "filter", "path": p} for p in ("status", "concept.bucket")]
    d.samples.create_search_index(
        SearchIndexModel(name=VECTOR_INDEX, type="vectorSearch", definition={"fields": fields})
    )


def nearest(vector: list[float], k: int = 5, bucket: str | None = None) -> list[dict]:
    """Closest non-failed samples by cosine similarity, using Atlas Vector Search."""
    flt = {"status": {"$ne": "failed"}}
    if bucket:
        flt["concept.bucket"] = bucket
    search = {
        "index": VECTOR_INDEX,
        "path": "embedding",
        "queryVector": list(vector),
        "numCandidates": max(100, 20 * k),
        "limit": k,
        "filter": flt,
    }
    project = {"name": "$concept.name", "score": {"$meta": "vectorSearchScore"}}
    rows = db().samples.aggregate([{"$vectorSearch": search}, {"$project": project}])
    # Atlas reports cosine as (1 + cos) / 2; convert back to cos.
    return [{"id": r["_id"], "name": r.get("name"), "similarity": 2 * r["score"] - 1} for r in rows]


def coverage() -> dict[str, int]:
    """Non-failed samples per taxonomy bucket."""
    pipeline = [
        {"$match": {"status": {"$ne": "failed"}}},
        {"$group": {"_id": "$concept.bucket", "n": {"$sum": 1}}},
    ]
    return {r["_id"]: r["n"] for r in db().samples.aggregate(pipeline)}
