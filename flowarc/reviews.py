"""A person's calls from the dashboard on flagged or failed samples (`reviews` in Atlas).

The dashboard writes {sample, decision, note, by, t, status: "new"}. `take` claims each new
review, applies it and sets status "done":
- accept: the sample is done as it is
- retry: the sample goes back to the stage that failed (or, if flagged, the first stage with a
  soft failure) with fresh attempts; the note joins the repair history Argon reads
- drop: the sample is failed for good
"""

from flowarc import store
from flowarc.sample import STAGES, Sample


def retry_stage(s: Sample) -> str:
    """Where a retry starts: the failed stage, or the earliest stage with a failed soft check."""
    if s.status == "failed":
        return s.stage
    for stage in STAGES:
        if any(not c["passed"] and c.get("hard") is False for c in s.checks.get(stage, [])):
            return stage
    return "mesh"


def apply(s: Sample, decision: str, note: str = "") -> bool:
    """Apply one decision. True when the sample should be queued to run again."""
    if s.status not in ("flagged", "failed"):
        s.log(f"review {decision} ignored: the sample is {s.status}")
        return False
    if decision == "accept":
        s.status = "done"
        s.log("review accept: marked done as it is")
    elif decision == "drop":
        s.status = "failed"
        s.meta["dropped"] = True
        s.log("review drop: marked failed")
    else:
        s.stage = retry_stage(s)
        s.attempts[s.stage] = 0
        s.status = "pending"
        if note:
            s.meta.setdefault("repairs", []).append(f"{s.stage}: a person asked to retry: {note}")
        s.log(f"review retry: queued again from {s.stage}" + (f" ({note})" if note else ""))
    s.save()
    return s.status == "pending"


def take(skip: set[str] = frozenset()) -> list[str]:
    """Apply every new review; returns the samples to run again. No Atlas: nothing to do."""
    d = store.db()
    if d is None:
        return []
    requeue = []
    query = {"status": "new", "sample": {"$nin": sorted(skip)}}
    while r := d.reviews.find_one_and_update(query, {"$set": {"status": "done"}}, sort=[("t", 1)]):
        try:
            s = Sample.load(r["sample"])
        except KeyError:
            continue
        if apply(s, r["decision"], r.get("note", "")) and s.id not in requeue:
            requeue.append(s.id)
    return requeue
