"""Run samples, one per GPU. Resumes unfinished samples first.
Usage: python scripts/run_pool.py [--new N] [--gpus 0,1,...] [--budget GPU_HOURS]"""

import argparse
import multiprocessing as mp

from flowarc import config
from flowarc.pipeline import BudgetExceeded, new_samples, run_sample
from flowarc.sample import Sample, all_samples


def worker(gpu: int, queue, budget: float):
    while True:
        sid = queue.get()
        if sid is None:
            return
        try:
            s = run_sample(Sample.load(sid), gpu, budget)
            print(f"gpu {gpu}: {sid} {s.status}", flush=True)
        except BudgetExceeded as e:
            print(f"gpu {gpu}: stopped, {e}", flush=True)
            return


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--new", type=int, default=0, help="propose this many new samples first")
    p.add_argument("--gpus", default=",".join(map(str, config.GPUS)))
    p.add_argument("--budget", type=float, default=config.PHASE_GPU_HOURS, help="GPU hours")
    p.add_argument("--seed", type=int)
    a = p.parse_args()
    if a.new:
        new_samples(a.new, a.seed)
    todo = [s.id for s in all_samples() if s.status not in ("done", "flagged", "failed")]
    gpus = [int(g) for g in a.gpus.split(",")]
    queue = mp.Queue()
    for sid in todo + [None] * len(gpus):
        queue.put(sid)
    procs = [mp.Process(target=worker, args=(g, queue, a.budget)) for g in gpus]
    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join()


if __name__ == "__main__":
    main()
