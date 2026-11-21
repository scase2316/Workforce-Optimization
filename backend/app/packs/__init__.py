"""Scenario packs: rules + vocabulary + synthetic-data scenario per use case."""
import json
from pathlib import Path

PACKS_DIR = Path(__file__).parent


def list_pack_ids() -> list[str]:
    return sorted(p.name for p in PACKS_DIR.iterdir() if (p / "rules.json").exists())


def load_pack(pack_id: str) -> dict:
    d = PACKS_DIR / pack_id
    if not (d / "rules.json").exists():
        raise KeyError(f"unknown pack: {pack_id}")
    load = lambda n: json.loads((d / n).read_text())
    return {"id": pack_id, "vocabulary": load("vocabulary.json"),
            "rules": load("rules.json"), "scenario": load("scenario.json")}
