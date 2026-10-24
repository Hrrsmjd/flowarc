"""Play the mock batch into MongoDB Atlas in real time, so the deployed dashboard runs on Atlas.

The dashboard reads Atlas the same way whether this script or the real pipeline writes it.
It writes to its own database (default `flowarc_demo`) so it never touches the real registry;
point the dashboard at it with MONGODB_DB=flowarc_demo.

    python scripts/demo_feed.py                 # reset the demo database and play once
    python scripts/demo_feed.py --loop          # replay until stopped
    python scripts/demo_feed.py --speed 2       # twice as fast

The publish request at the end is a real approval: the script waits until someone presses
Approve or Reject on the dashboard, then logs what it did.
"""

import argparse
import os
import time
from pathlib import Path

from dotenv import load_dotenv

from flowarc import media, mock

WEB = Path(__file__).resolve().parent.parent / "web" / "public"  # the mock views and meshes

load_dotenv()


def connect(db_name: str):
    from pymongo import MongoClient

    uri = os.environ.get("MONGODB_URI")
    if not uri:
        raise SystemExit("set MONGODB_URI (see .env.example)")
    return MongoClient(uri, appname="flowarc-demo-feed")[db_name]


def reset(db, batch: dict, t0: float) -> None:
    """History (events before t=0) is written at once; samples still to come start pending."""
    for coll in ("samples", "logs", "approvals", "baseline", "runs", "media.files", "media.chunks"):
        db[coll].delete_many({})
    for m in batch.get("media", []):
        if m["t"] <= 0:
            upload(db, m)
    started = {e["sample"] for e in batch["logs"] if e["t"] <= 0}
    has_log = {e["sample"] for e in batch["logs"]}
    for s in batch["samples"]:
        if s["_id"] in has_log and s["_id"] not in started:
            s = {**s, "stage": "concept", "status": "pending", "embedding": []}
        elif s["_id"] in has_log and any(
            e["t"] > 0 for e in batch["logs"] if e["sample"] == s["_id"]
        ):
            s = {**s, **progress(batch, s["_id"], 0)}
        db.samples.insert_one(s)
    history = [{**e, "t": t0 + e["t"]} for e in batch["logs"] if e["t"] <= 0]
    if history:
        db.logs.insert_many(history)
    db.baseline.insert_many(batch["baseline"])
    db.runs.insert_one({"_id": "current", **batch["run"]})
    for a in batch["approvals"]:
        if a["t"] <= 0:
            db.approvals.insert_one({**a, "t": t0 + a["t"]})


def upload(db, m: dict) -> None:
    """Copy one mock view or mesh into the GridFS bucket the dashboard reads."""
    ctype = "image/jpeg" if m["kind"] == "view" else "model/gltf-binary"
    data = (WEB / m["url"]).read_bytes()
    media.publish(
        db, m["sample"], m["kind"], m["name"], m["attempt"], data, ctype, f"demo:{m['url']}"
    )


def progress(batch: dict, sid: str, rel: float) -> dict:
    """Stage and status of a sample `rel` seconds into the live part."""
    seen = [e for e in batch["logs"] if e["sample"] == sid and e["t"] <= rel]
    moved = [e for e in seen if e["msg"] == "advanced"]
    tries = sum(
        1 for e in seen if e["stage"] == "mesh" and (" built" in e["msg"] or " rebuilt" in e["msg"])
    )
    return {
        "stage": mock.stage_after(moved[-1]["stage"]) if moved else "concept",
        "status": "running",
        "attempts": {"mesh": tries} if tries > 1 else {},
    }


def play(db, batch: dict, speed: float) -> None:
    t0 = time.time()
    reset(db, batch, t0)
    final = {s["_id"]: s for s in batch["samples"]}
    live = [e for e in batch["logs"] if e["t"] > 0]
    approvals = [a for a in batch["approvals"] if a["t"] > 0]
    files = sorted((m for m in batch.get("media", []) if m["t"] > 0), key=lambda m: m["t"])
    print(f"playing {len(live)} events over {live[-1]['t'] / speed:.0f} s")
    for e in live:
        time.sleep(max(0.0, t0 + e["t"] / speed - time.time()))
        sid = e["sample"]
        while files and files[0]["t"] <= e["t"]:
            upload(db, files.pop(0))
        db.logs.insert_one({**e, "t": time.time()})
        last = e is [x for x in batch["logs"] if x["sample"] == sid][-1]
        if last:
            s = final[sid]
            db.samples.update_one(
                {"_id": sid},
                {"$set": {k: s[k] for k in ("stage", "status", "attempts", "embedding", "meta")}},
            )
        else:
            db.samples.update_one(
                {"_id": sid},
                {"$set": {**progress(batch, sid, e["t"]), "embedding": final[sid]["embedding"]}},
            )
        print(f"{sid} {e['stage']:<8} {e['msg'][:70]}")
    for a in approvals:
        db.approvals.insert_one({**a, "t": time.time()})
        print(f"waiting for approval: {a['title']}")
        while (doc := db.approvals.find_one({"_id": a["_id"]}))["status"] == "pending":
            time.sleep(1)
        msg = (
            "published the pilot batch to the private Hugging Face dataset"
            if doc["status"] == "approved"
            else "publish rejected; nothing uploaded"
        )
        db.logs.insert_one(
            {"sample": batch["run"]["live"], "t": time.time(), "stage": "package", "msg": msg}
        )
        print(msg)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--db", default=os.environ.get("FLOWARC_DEMO_DB", "flowarc_demo"))
    p.add_argument("--speed", type=float, default=1.0)
    p.add_argument("--loop", action="store_true")
    args = p.parse_args()
    if "demo" not in args.db:  # it wipes the database first, so never a real registry
        raise SystemExit(
            f"refusing to wipe {args.db!r}: the demo feed only writes to a *demo* database"
        )
    db = connect(args.db)
    while True:
        play(db, mock.batch(), args.speed)
        if not args.loop:
            break
        time.sleep(20)


if __name__ == "__main__":
    main()
