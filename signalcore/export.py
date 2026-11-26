"""Build the standalone, single-file HTML version of the app (data embedded, no server needed).

    python -m signalcore.export [--out signalcore-standalone.html]
"""
import argparse
import json
import re
from pathlib import Path

from .db import DEFAULT_DB
from .state import build_state

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def export(out, run_id=None):
    st = build_state(DEFAULT_DB, run_id) | {"llm_mode": "snapshot"}
    html = (WEB / "index.html").read_text()
    css = (WEB / "app.css").read_text()
    js = (WEB / "app.js").read_text()
    data = json.dumps({"state": st}, default=str, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = html.replace('<link rel="stylesheet" href="/static/app.css" data-inline>', f"<style>\n{css}\n</style>")
    html = html.replace('<script src="/static/app.js" data-inline></script>',
                        f"<script>window.SNAPSHOT = {data};</script>\n<script>\n{js}\n</script>")
    assert "/static/" not in html
    Path(out).write_text(html)
    return out, len(html)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "signalcore-standalone.html"))
    ap.add_argument("--run", default=None)
    a = ap.parse_args()
    p, n = export(a.out, a.run)
    print(f"wrote {p} ({n // 1024} KB)")
