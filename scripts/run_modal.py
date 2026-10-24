"""Run chosen samples with sims on Modal H100s (FLOWARC_SOLVER=modal). Images, mesh, render and
package run here; Hunyuan runs on --mesh-gpu, at most --mesh-slots at a time.
Pick samples the main pool won't reach for a while; it skips them once they are done.
Usage: python scripts/run_modal.py --ids s00102-s00121 [--workers 10] [--mesh-gpu 3] [--mesh-slots 2]"""

import argparse
import multiprocessing as mp
import os

os.environ["FLOWARC_SOLVER"] = "modal"

from flowarc.mesh import generators
from flowarc.pipeline import run_sample
from flowarc.sample import Sample


def ids(spec: str) -> list[str]:
    out = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        out += [f"s{i:05d}" for i in range(int(a[1:]), int((b or a)[1:]) + 1)]
    return out


def worker(queue, gpu: int, slots):
    generate = generators.Hunyuan21.generate

    def limited(self, *a, **k):
        with slots:
            return generate(self, *a, **k)

    generators.Hunyuan21.generate = limited
    while (sid := queue.get()) is not None:
        try:
            s = run_sample(Sample.load(sid), gpu)
            print(f"modal: {sid} {s.status}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"modal: {sid} crashed {e!r}", flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ids", required=True, help="e.g. s00102-s00121 or s00001,s00005")
    p.add_argument("--workers", type=int, default=10, help="samples at once (= Modal GPUs)")
    p.add_argument("--mesh-gpu", type=int, default=3)
    p.add_argument("--mesh-slots", type=int, default=2)
    a = p.parse_args()
    todo = [i for i in ids(a.ids) if Sample.load(i).status not in ("done", "flagged", "failed")]
    print(f"modal: {len(todo)} samples: {' '.join(todo)}", flush=True)
    queue, slots = mp.Queue(), mp.Semaphore(a.mesh_slots)
    for sid in todo + [None] * a.workers:
        queue.put(sid)
    procs = [mp.Process(target=worker, args=(queue, a.mesh_gpu, slots)) for _ in range(a.workers)]
    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join()


if __name__ == "__main__":
    main()
