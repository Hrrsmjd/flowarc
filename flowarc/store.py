"""MongoDB Atlas: the dataset registry and the concept vector index.

With MONGODB_URI set, Atlas is the source of truth. Samples, their logs and their concept
embeddings live there, so every GPU worker and the dashboard share one registry. Without it
(tests, offline work) the registry falls back to JSON files in each sample folder.

Collections: `samples` (one document per sample, _id = sample id) and `logs` (one per event).
"""

from functools import cache

from flowarc import config

VECTOR_INDEX = "concept_vectors"
TEXT_INDEX = "samples_text"  # Atlas Search: names, descriptions, facets
LOG_INDEX = "logs_text"  # Atlas Search: the agent's log
SEMANTIC_INDEX = "concept_voyage"  # Automated Embedding (Voyage AI) of descriptions
OLD_INDEXES = {"samples": ["concept_semantic"]}  # replaced; dropped by ensure_indexes
REPAIR_TEXT_INDEX = "repairs_text"  # Atlas Search over Argon's diagnoses and fixes
REPAIR_SEMANTIC_INDEX = "repairs_semantic"  # Automated Embedding of diagnoses
AUTO_EMBED_MODEL = config.AUTO_EMBED_MODEL

# Atlas Search definitions. `token` fields can be faceted and matched exactly.
TEXT_FIELDS = {
    "concept": {
        "type": "document",
        "fields": {
            "name": [{"type": "string"}, {"type": "autocomplete"}],
            "description": {"type": "string"},
            "facing": {"type": "string"},
            "bucket": {"type": "token"},
            "ground": {"type": "boolean"},
            "reynolds": {"type": "number"},
        },
    },
    "status": {"type": "token"},
    "stage": {"type": "token"},
}
LOG_FIELDS = {
    "msg": {"type": "string"},
    "stage": {"type": "token"},
    "sample": {"type": "token"},
    "passed": {"type": "boolean"},
}
RE_BANDS = [1e1, 1e2, 1e3, 1e4, 1e5, 1e6, 1e7, 1e8]


@cache
def db():
    """The Atlas database, or None when MONGODB_URI is not set."""
    if not config.MONGODB_URI:
        return None
    from pymongo import MongoClient

    return MongoClient(config.MONGODB_URI, appname="flowarc")[config.MONGODB_DB]


def _search_index(coll, name: str, kind: str, definition: dict) -> None:
    """Create a search index unless it exists. The listing can lag behind creation, so an
    "already exists" error also counts as done."""
    from pymongo.errors import OperationFailure
    from pymongo.operations import SearchIndexModel

    existing = {i["name"]: i for i in coll.list_search_indexes()}
    if name in existing:
        have = existing[name].get("latestDefinition", {}).get("fields", [])
        need = definition.get("fields", [])  # vector indexes; search mappings are left alone
        if any(not any(f.items() <= h.items() for h in have) for f in need):
            coll.update_search_index(name, definition)  # e.g. a filter field was added
        return
    try:
        coll.create_search_index(SearchIndexModel(name=name, type=kind, definition=definition))
    except OperationFailure as e:
        if "already exists" not in str(e) and e.code != 68:  # 68: IndexAlreadyExists
            raise


def ensure_indexes(dims: int) -> None:
    """Create the query indexes and the Atlas Search / Vector Search indexes (idempotent)."""
    d = db()
    for coll in ("samples", "logs", "repairs", "metrics"):  # search indexes need the collection
        if coll not in d.list_collection_names():
            d.create_collection(coll)
    for coll, names in OLD_INDEXES.items():
        for i in d[coll].list_search_indexes():
            if i["name"] in names:
                d[coll].drop_search_index(i["name"])
    d.samples.create_index([("stage", 1), ("status", 1)])
    d.samples.create_index("concept.bucket")
    d.logs.create_index([("sample", 1), ("t", 1)])
    fields = [
        {"type": "vector", "path": "embedding", "numDimensions": dims, "similarity": "cosine"}
    ]
    fields += [{"type": "filter", "path": p} for p in ("status", "concept.bucket")]
    _search_index(d.samples, VECTOR_INDEX, "vectorSearch", {"fields": fields})
    _search_index(
        d.samples, TEXT_INDEX, "search", {"mappings": {"dynamic": False, "fields": TEXT_FIELDS}}
    )
    _search_index(
        d.logs, LOG_INDEX, "search", {"mappings": {"dynamic": False, "fields": LOG_FIELDS}}
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


NOT_FAILED = {"compound": {"mustNot": [{"equals": {"path": "status", "value": "failed"}}]}}


def facets(operator: dict = NOT_FAILED) -> dict:
    """Sample counts per bucket, status, stage, Reynolds band and ground/free stream.

    One Atlas Search `$searchMeta` query; it feeds Argon's coverage prompt and the dashboard
    filters. Returns {"total": n, "bucket": {...}, "status": {...}, ...}.
    """
    meta = {
        "index": TEXT_INDEX,
        "facet": {
            "operator": operator,
            "facets": {
                "bucket": {"type": "string", "path": "concept.bucket", "numBuckets": 50},
                "status": {"type": "string", "path": "status"},
                "stage": {"type": "string", "path": "stage"},
                "reynolds": {"type": "number", "path": "concept.reynolds", "boundaries": RE_BANDS},
            },
        },
    }
    rows = list(db().samples.aggregate([{"$searchMeta": meta}]))
    if not rows:
        return {"total": 0}
    out = {"total": rows[0]["count"]["lowerBound"]}
    for name, f in rows[0]["facet"].items():
        out[name] = {str(b["_id"]): b["count"] for b in f["buckets"]}
    return out


def coverage() -> dict[str, int]:
    """Non-failed samples per taxonomy bucket (Atlas Search facets)."""
    return facets().get("bucket", {})


def search(text: str, k: int = 10) -> list[dict]:
    """Full-text search over sample names and descriptions, fuzzy, best first."""
    pipeline = [
        {
            "$search": {
                "index": TEXT_INDEX,
                "text": {
                    "query": text,
                    "path": ["concept.name", "concept.description", "concept.facing"],
                    "fuzzy": {"maxEdits": 1},
                },
            }
        },
        {"$limit": k},
        {"$project": SUMMARY | {"score": {"$meta": "searchScore"}}},
    ]
    return [_row(r) for r in db().samples.aggregate(pipeline)]


def autocomplete(prefix: str, k: int = 8) -> list[str]:
    """Sample names that start like `prefix`, for the dashboard search box."""
    pipeline = [
        {
            "$search": {
                "index": TEXT_INDEX,
                "autocomplete": {"query": prefix, "path": "concept.name"},
            }
        },
        {"$limit": k},
        {"$project": {"name": "$concept.name"}},
    ]
    return [r["name"] for r in db().samples.aggregate(pipeline)]


def search_log(text: str, k: int = 20, failed_only: bool = False) -> list[dict]:
    """Full-text search over the agent log (check results, diagnoses, decisions)."""
    op = {"text": {"query": text, "path": "msg"}}
    if failed_only:
        op = {
            "compound": {"must": [op], "filter": [{"equals": {"path": "passed", "value": False}}]}
        }
    pipeline = [
        {"$search": {"index": LOG_INDEX, **op}},
        {"$limit": k},
        {"$project": {"_id": 0, "sample": 1, "stage": 1, "msg": 1, "t": 1}},
    ]
    return list(db().logs.aggregate(pipeline))


def _semantic(text: str, k: int, flt: dict) -> dict:
    """$vectorSearch on plain text: Atlas embeds the query with the index's Voyage model."""
    return {
        "$vectorSearch": {
            "index": SEMANTIC_INDEX,
            "path": "concept.description",
            "query": text,
            "numCandidates": max(100, 20 * k),
            "limit": k,
            "filter": flt,
        }
    }


def semantic(text: str, k: int = 10) -> list[dict]:
    """Samples whose description means something close to `text` (Automated Embedding)."""
    pipeline = [
        _semantic(text, k, {"status": {"$ne": "failed"}}),
        {"$project": SUMMARY | {"score": {"$meta": "vectorSearchScore"}}},
    ]
    return [_row(r) for r in db().samples.aggregate(pipeline)]


def hybrid(text: str, k: int = 10, bucket: str | None = None) -> list[dict]:
    """Hybrid search: Voyage semantic matches fused with Atlas Search keyword matches.

    `$rankFusion` (reciprocal rank fusion) merges the two ranked lists, so a query like
    "streamlined animal with a hole through it" finds both close meanings and exact words.
    """
    flt = {"status": {"$ne": "failed"}}
    must = [{"text": {"query": text, "path": ["concept.name", "concept.description"]}}]
    filters = [{"equals": {"path": "status", "value": "failed"}}]
    keyword = {"index": TEXT_INDEX, "compound": {"must": must, "mustNot": filters}}
    if bucket:
        flt["concept.bucket"] = bucket
        keyword["compound"]["filter"] = [{"equals": {"path": "concept.bucket", "value": bucket}}]
    fusion = {
        "input": {
            "pipelines": {
                "semantic": [_semantic(text, 2 * k, flt)],
                "keyword": [{"$search": keyword}, {"$limit": 2 * k}],
            }
        },
        "combination": {"weights": {"semantic": 1, "keyword": 1}},
    }
    pipeline = [
        {"$rankFusion": fusion},
        {"$limit": k},
        {"$project": SUMMARY | {"score": {"$meta": "score"}}},
    ]
    return [_row(r) for r in db().samples.aggregate(pipeline)]


def past_fixes(diagnosis: str, stage: str, k: int = 5) -> list[dict]:
    """Repairs that fixed a failure like `diagnosis` at this stage, best match first.

    Hybrid search over the `repairs` collection: Voyage embeddings of past diagnoses fused
    with keyword matches, filtered to repairs that worked.
    """
    flt = {"stage": stage, "fixed": True}
    keyword = {
        "index": REPAIR_TEXT_INDEX,
        "compound": {
            "must": [{"text": {"query": diagnosis, "path": "diagnosis"}}],
            "filter": [
                {"equals": {"path": "stage", "value": stage}},
                {"equals": {"path": "fixed", "value": True}},
            ],
        },
    }
    semantic = {
        "index": REPAIR_SEMANTIC_INDEX,
        "path": "diagnosis",
        "query": diagnosis,
        "numCandidates": max(100, 40 * k),
        "limit": 2 * k,
        "filter": flt,
    }
    fusion = {
        "input": {
            "pipelines": {
                "semantic": [{"$vectorSearch": semantic}],
                "keyword": [{"$search": keyword}, {"$limit": 2 * k}],
            }
        }
    }
    pipeline = [
        {"$rankFusion": fusion},
        {"$limit": k},
        {"$project": {"_id": 0, "sample": 1, "diagnosis": 1, "action": 1}},
    ]
    return list(db().repairs.aggregate(pipeline))


def metrics(minutes: int = 60) -> list[dict]:
    """Per-stage counts per minute, newest first.

    Written by the Atlas Stream Processing job in scripts/stream_metrics.js. When that job
    isn't running, the same counts are computed from the log with one aggregation.
    """
    import datetime as dt

    since = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=minutes)
    rows = list(db().metrics.find({"window": {"$gte": since}}, {"_id": 0}).sort("window", -1))
    return rows or stage_stats(minutes)


def stage_stats(minutes: int = 60) -> list[dict]:
    """Checks, passes, failures and samples moved on per stage over the last `minutes`."""
    import time

    pipeline = [
        {"$match": {"t": {"$gte": time.time() - 60 * minutes}}},
        {
            "$group": {
                "_id": "$stage",
                "events": {"$sum": 1},
                "passed": {"$sum": {"$cond": [{"$eq": ["$passed", True]}, 1, 0]}},
                "failed": {"$sum": {"$cond": [{"$eq": ["$passed", False]}, 1, 0]}},
                "advanced": {"$sum": {"$cond": [{"$eq": ["$msg", "advanced"]}, 1, 0]}},
                "samples": {"$addToSet": "$sample"},
            }
        },
        {
            "$set": {
                "stage": "$_id",
                "samples": {"$size": "$samples"},
                "checks": {"$add": ["$passed", "$failed"]},
            }
        },
        {"$project": {"_id": 0}},
    ]
    return list(db().logs.aggregate(pipeline))


SUMMARY = {
    "name": "$concept.name",
    "bucket": "$concept.bucket",
    "description": "$concept.description",
    "status": 1,
    "stage": 1,
}


def _row(r: dict) -> dict:
    return {"id": r.pop("_id"), **r}
