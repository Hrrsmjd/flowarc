"""Create the Atlas indexes for the registry, including the concept vector search index.

Usage: python scripts/setup_atlas.py   (needs MONGODB_URI and GEMINI_API_KEY in .env)
The vector size is read from one probe embedding, so it follows FLOWARC_EMBED_MODEL.
"""

from flowarc import config, gemini, store


def main():
    if store.db() is None:
        raise SystemExit("set MONGODB_URI in .env")
    dims = len(gemini.embed(["a probe concept"])[0])
    store.ensure_indexes(dims)
    print(f"indexes ready on {config.MONGODB_DB} ({config.EMBED_MODEL}, {dims} dims)")


if __name__ == "__main__":
    main()
