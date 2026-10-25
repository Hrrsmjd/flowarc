"""Fill the `baseline` collection with DrivAerNet++ car concepts for the diversity map.

Usage: python scripts/seed_baseline.py [k]   (needs MONGODB_URI and GEMINI_API_KEY; k defaults to 4)

DrivAerNet++ varies one car (the DrivAer model) along a fixed design space: three rear styles,
smooth or detailed underbody, open or closed rims, with or without mirrors, and morphs of its
proportions. Every one of the 24 discrete combinations gets k variants, each with a different
pair of morphs on two separate axes (never a roof both lower and higher), so coverage is
complete and the output is the same on every run. Each entry is embedded with the same model
and `name: description` format as our concepts, so both sit in one embedding space.
These are descriptions of the dataset's design space, not its meshes, and the morphs carry no
magnitudes. Replaces the collection.
"""

import itertools
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
# Proportion morphs by axis; a variant never takes two morphs on the same axis.
MORPHS = {
    "roof": ["a slightly lower roof", "a slightly higher roof"],
    "windscreen": ["a steeper windscreen", "a shallower windscreen"],
    "ride": ["a raised ride height", "a lowered ride height"],
    "bonnet": ["a longer bonnet"],
    "overhang": ["a shorter front overhang"],
    "track": ["a wider track"],
    "tail": ["a more tapered rear"],
    "wheelbase": ["a longer wheelbase"],
    "nose": ["a rounder nose"],
}
PAIRS = [
    (a, b)
    for (ax, a), (bx, b) in itertools.combinations(
        [(axis, m) for axis, ms in MORPHS.items() for m in ms], 2
    )
    if ax != bx
]


def concepts(k: int = 4) -> list[dict]:
    """k variants for each of the 24 discrete combinations, cycling through the morph pairs."""
    combos = list(itertools.product(REARS, UNDERBODY, WHEELS, MIRRORS))
    if not 1 <= k <= len(PAIRS):
        raise SystemExit(f"k must be 1 to {len(PAIRS)}")
    out = []
    for i, (rear, under, wheels, mirrors) in enumerate(combos):
        for j in range(k):
            a, b = PAIRS[(i * k + j) % len(PAIRS)]
            desc = (
                f"A four-door mid-size passenger saloon car body with {REARS[rear]}, "
                f"{under}, {wheels} and {mirrors}; this variant has {a} and {b}."
            )
            out.append(
                {
                    "_id": f"car{len(out) + 1:04d}",
                    "name": f"DrivAer {rear} car",
                    "description": desc,
                }
            )
    return out


def main():
    if store.db() is None:
        raise SystemExit("set MONGODB_URI in .env")
    cars = concepts(int(sys.argv[1]) if len(sys.argv) > 1 else 4)
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
