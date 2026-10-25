"""Fill the `baseline` collection with DrivAerNet++ car concepts for the diversity map.

Usage: python scripts/seed_baseline.py [n]   (needs MONGODB_URI and GEMINI_API_KEY; n defaults to 80)

DrivAerNet++ varies one car (the DrivAer model) along a fixed design space: three rear styles,
smooth or detailed underbody, open or closed rims, with or without mirrors, and morphs of its
proportions. Each baseline entry is a text description of one such variant, embedded with the
same model and `name: description` format as our concepts, so both sit in one embedding space.
These are descriptions of the dataset's variants, not its meshes. Replaces the collection.
"""

import itertools
import random
import sys

from pymongo import ReplaceOne

from flowarc import config, gemini, store
from flowarc.concepts import describe

REARS = {
    "fastback": "a fastback rear where the roof slopes in one long line down to the tail",
    "notchback": "a notchback rear with a short separate boot behind a steep rear window",
    "estateback": "an estate rear where the roof runs flat to a near-vertical tailgate",
}
UNDERBODY = [
    "a smooth flat underbody",
    "a detailed underbody with exhaust, suspension and floor parts",
]
WHEELS = ["open five-spoke rims", "closed flat wheel covers"]
MIRRORS = ["side mirrors on the doors", "no side mirrors"]
MORPHS = [
    "a slightly lower roof",
    "a slightly higher roof",
    "a longer bonnet",
    "a shorter front overhang",
    "a steeper windscreen",
    "a shallower windscreen",
    "a raised ride height",
    "a lowered ride height",
    "a wider track",
    "a more tapered rear",
    "a longer wheelbase",
    "a rounder nose",
]


def concepts(n: int, seed: int = 0) -> list[dict]:
    """n distinct variants, drawn without replacement from every combination."""
    combos = list(
        itertools.product(REARS, UNDERBODY, WHEELS, MIRRORS, itertools.combinations(MORPHS, 2))
    )
    if n > len(combos):
        raise SystemExit(f"at most {len(combos)} distinct variants")
    out = []
    for k, (rear, under, wheels, mirrors, morph) in enumerate(
        random.Random(seed).sample(combos, n)
    ):
        desc = (
            f"A four-door mid-size passenger saloon car body with {REARS[rear]}, "
            f"{under}, {wheels} and {mirrors}; this variant has {' and '.join(morph)}."
        )
        out.append({"_id": f"car{k + 1:04d}", "name": f"DrivAer {rear} car", "description": desc})
    return out


def main():
    if store.db() is None:
        raise SystemExit("set MONGODB_URI in .env")
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 80
    cars = concepts(n)
    vectors = gemini.embed([describe(c) for c in cars])
    coll = store.db()["baseline"]
    # Upsert first, then drop leftovers, so a failed write never leaves the map without cars.
    coll.bulk_write(
        [
            ReplaceOne({"_id": c["_id"]}, {**c, "embedding": v}, upsert=True)
            for c, v in zip(cars, vectors)
        ]
    )
    coll.delete_many({"_id": {"$nin": [c["_id"] for c in cars]}})
    print(f"wrote {len(cars)} car concepts to {config.MONGODB_DB}.baseline ({config.EMBED_MODEL})")


if __name__ == "__main__":
    main()
