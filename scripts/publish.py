"""Upload finished samples' Zarrs to the private HF dataset and check their checksums.

Usage: python scripts/publish.py [--delete] s00001 [s00002 ...] | --all
--delete removes the RDS Zarr once the copy on HF matches. The runner never does this by itself,
and nothing here makes the dataset public.
"""

import argparse

from flowarc import publish
from flowarc.sample import Sample, all_samples


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--all", action="store_true", help="every done or flagged sample")
    ap.add_argument("--delete", action="store_true", help="delete the RDS Zarr once verified")
    a = ap.parse_args()
    samples = [s for s in all_samples() if s.status in ("done", "flagged")] if a.all else []
    for s in samples + [Sample.load(i) for i in a.ids]:
        if s.meta.get("published", {}).get("deleted_from_rds"):
            continue
        r = publish.publish(s, delete=a.delete)
        print(s.id, "verified" if r["verified"] else "MISMATCH", r["url"])


if __name__ == "__main__":
    main()
