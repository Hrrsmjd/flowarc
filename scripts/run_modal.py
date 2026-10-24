"""Run chosen samples with Hunyuan and the sim on Modal GPUs (flowarc/sim/modal_app.py).
Gemini calls, mesh checks, render review and packaging run here, with no local GPU.
Pick samples the main pool won't reach for a while; it skips them once they are done.
Usage: python scripts/run_modal.py --ids s00102-s00121 [--workers 10]"""

import argparse
import multiprocessing as mp
import os

os.environ["FLOWARC_SOLVER"] = "modal"
os.environ["FLOWARC_MESH_HOST"] = "modal"

from flowarc.pipeline import run_sample
from flowarc.sample import Sample


def ids(spec: str) -> list[str]:
    out = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        out += [f"s{i:05d}" for i in range(int(a[1:]), int((b or a)[1:]) + 1)]
    return out


def worker(queue):
    while (sid := queue.get()) is not None:
        try:
            s = run_sample(Sample.load(sid), gpu=-1)
            print(f"modal: {sid} {s.status}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"modal: {sid} crashed {e!r}", flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ids", required=True, help="e.g. s00102-s00121 or s00001,s00005")
    p.add_argument("--workers", type=int, default=10, help="samples at once (= Modal GPUs)")
    a = p.parse_args()
    todo = [i for i in ids(a.ids) if Sample.load(i).status not in ("done", "flagged", "failed")]
    print(f"modal: {len(todo)} samples: {' '.join(todo)}", flush=True)
    queue = mp.Queue()
    for sid in todo + [None] * a.workers:
        queue.put(sid)
    procs = [mp.Process(target=worker, args=(queue,)) for _ in range(a.workers)]
    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join()


if __name__ == "__main__":
    main()
