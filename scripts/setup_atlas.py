"""Create every Atlas index the registry uses (idempotent).

Usage: python scripts/setup_atlas.py   (needs MONGODB_URI and GEMINI_API_KEY in .env)

- concept_vectors   Vector Search on Gemini embeddings (novelty)
- concept_semantic  Automated Embedding of descriptions with Voyage AI (hybrid search)
- samples_text      Atlas Search: text, autocomplete, facets
- logs_text         Atlas Search over the agent log
- repairs_semantic  Automated Embedding of failure diagnoses (failure memory)
- repairs_text      Atlas Search over diagnoses and fixes

The Gemini vector size is read from one probe embedding, so it follows FLOWARC_EMBED_MODEL.
Search indexes build in the background; check with scripts/atlas_smoke.py after a minute.
"""

from flowarc import config, gemini, store


def main():
    if store.db() is None:
        raise SystemExit("set MONGODB_URI in .env")
    dims = len(gemini.embed(["a probe concept"])[0])
    store.ensure_indexes(dims)
    for coll in ("samples", "repairs", "logs"):
        for i in store.db()[coll].list_search_indexes():
            print(f"{coll:8} {i['name']:18} {i.get('status', '?')}")
    print(
        f"ready on {config.MONGODB_DB} ({config.EMBED_MODEL} {dims} dims, {store.AUTO_EMBED_MODEL})"
    )


if __name__ == "__main__":
    main()
