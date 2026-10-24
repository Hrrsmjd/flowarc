"""Check the configured Gemini model names against the live model list.

Usage: GEMINI_API_KEY=... uv run python scripts/check_models.py
"""

import sys

from flowarc import config, gemini

WANTED = {
    "FLOWARC_LEAD_MODEL": config.LEAD_MODEL,
    "FLOWARC_FAST_MODEL": config.FAST_MODEL,
    "FLOWARC_IMAGE_MODEL": config.IMAGE_MODEL,
    "FLOWARC_EMBED_MODEL": config.EMBED_MODEL,
    "routing (GOAL.md)": "gemini-3.5-flash-lite",
}


def main():
    live = {m.name.removeprefix("models/"): m for m in gemini.client().models.list()}
    missing = 0
    for var, name in WANTED.items():
        m = live.get(name)
        if m is None:
            missing += 1
            close = sorted(n for n in live if n.split("-")[:2] == name.split("-")[:2])
            print(f"MISSING {var}={name}  similar: {', '.join(close) or '-'}")
        else:
            actions = ",".join(m.supported_actions or [])
            print(f"ok      {var}={name}  [{actions}]")
    print(f"\n{len(live)} models visible to this key")
    sys.exit(1 if missing else 0)


if __name__ == "__main__":
    main()
