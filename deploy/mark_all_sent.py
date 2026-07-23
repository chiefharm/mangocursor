#!/usr/bin/env python3
"""One-off: mark all existing HTML transcripts as already sent to Telegram."""
import json
from pathlib import Path

base = Path("/opt/mango-pipeline")
state_path = base / "data" / "sent_calls.json"
state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
for p in base.glob("*.html"):
    if p.name.lower() == "index.html":
        continue
    state[p.name] = f"{p.name}:{p.stat().st_mtime_ns}"
state_path.parent.mkdir(parents=True, exist_ok=True)
state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"marked {len(state)} files")
