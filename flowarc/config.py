"""Paths and per-phase settings."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Phase:
    name: str
    cells_per_length: tuple[int, ...]  # grid ladder, coarse to fine; the last one records frames
    max_samples: int


PHASES = {
    "pilot": Phase("pilot", (64, 96), 100),
    "first": Phase("first", (80, 120), 100),
    "reference": Phase("reference", (170, 256), 20),
}

DATA = Path(os.environ.get("FLOWARC_DATA", "data")).resolve()
PHASE = PHASES[os.environ.get("FLOWARC_PHASE", "pilot")]
GPUS = [int(g) for g in os.environ.get("FLOWARC_GPUS", "0").split(",") if g]

LEAD_MODEL = os.environ.get("FLOWARC_LEAD_MODEL", "gemini-4-argon")
FAST_MODEL = os.environ.get("FLOWARC_FAST_MODEL", "gemini-3.8-flash")
IMAGE_MODEL = os.environ.get("FLOWARC_IMAGE_MODEL", "gemini-nano-banana-2.1")
EMBED_MODEL = os.environ.get("FLOWARC_EMBED_MODEL", "gemini-embedding-2")

# MongoDB Atlas registry; empty URI = JSON files under DATA (see store.py).
MONGODB_URI = os.environ.get("MONGODB_URI", "")
MONGODB_DB = os.environ.get("MONGODB_DB", "flowarc")
HF_REPO = os.environ.get("FLOWARC_HF_REPO", "")  # private dataset for sample files
# Voyage AI model Atlas uses for Automated Embedding (search side; novelty uses EMBED_MODEL).
AUTO_EMBED_MODEL = os.environ.get("FLOWARC_AUTO_EMBED_MODEL", "voyage-4")

# Time in convective units (body length / free-stream speed).
STARTUP_TIME = 10.0
RECORD_TIME = 30.0
FRAME_INTERVAL = 0.1

# Runs stop here until Harris approves more (--budget).
PHASE_GPU_HOURS = float(os.environ.get("FLOWARC_GPU_HOURS", "5"))
MAX_ATTEMPTS = {"concept": 3, "images": 3, "mesh": 4, "sim": 3, "render": 2}
