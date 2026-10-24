"""Fill the `baseline` collection with DrivAerNet++ car concepts for the diversity map.

Usage: python scripts/seed_baseline.py [n]   (needs MONGODB_URI and GEMINI_API_KEY; n defaults to 80)

DrivAerNet++ varies one car (the DrivAer model) along a fixed design space: three rear styles,
smooth or detailed underbody, open or closed rims, with or without mirrors, and morphs of its
proportions. Each baseline entry is a text description of one such variant, embedded with the
same model and `name: description` format as our concepts, so both sit in one embedding space.
These are descriptions of the dataset's variants, not its meshes. Replaces the collection.
"""

import random
import sys

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
    rng = random.Random(seed)
    out, seen = [], set()
    while len(out) < n:
        rear = list(REARS)[len(out) % len(REARS)]
        morph = " and ".join(rng.sample(MORPHS, 2))
        desc = (
            f"A four-door mid-size passenger saloon car body with {REARS[rear]}, "
            f"{rng.choice(UNDERBODY)}, {rng.choice(WHEELS)} and {rng.choice(MIRRORS)}; "
            f"this variant has {morph}."
        )
        if desc in seen:
            continue
        seen.add(desc)
        out.append(
            {"_id": f"car{len(out) + 1:04d}", "name": f"DrivAer {rear} car", "description": desc}
        )
    return out


def main():
    if store.db() is None:
        raise SystemExit("set MONGODB_URI in .env")
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 80
    cars = concepts(n)
    vectors = gemini.embed([describe(c) for c in cars])
    coll = store.db()["baseline"]
    coll.delete_many({})
    coll.insert_many([{**c, "embedding": v} for c, v in zip(cars, vectors)])
    print(f"wrote {len(cars)} car concepts to {config.MONGODB_DB}.baseline ({config.EMBED_MODEL})")


if __name__ == "__main__":
    main()
