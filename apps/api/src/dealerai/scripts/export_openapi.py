"""Write the API's OpenAPI document where the web app generates its types from.

Sorted keys and a fixed indent make the output deterministic, so
`npm run check:openapi` can fail on any diff: a route or model that changed
without regenerating the frontend types is drift, and drift is how a field
quietly disappears from a screen.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..main import app

OUT = Path(__file__).resolve().parents[4] / "web" / "lib" / "api" / "openapi.json"


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    document = json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False)
    OUT.write_text(document + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
