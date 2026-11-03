"""Embed generated public dashboard data so Pages does not depend on fetch."""
import json
from pathlib import Path
def main():
    path=Path("dashboard/index.html")
    html=path.read_text(encoding="utf-8")
    data=json.loads(Path("dashboard/data.json").read_text(encoding="utf-8"))
    safe=json.dumps(data,ensure_ascii=False,separators=(",",":")).replace("<","\\u003c")
    marker="<!-- DASHBOARD_DATA -->"
    if marker not in html:
        raise RuntimeError("Missing dashboard embed marker")
    html=html.replace(marker,'<script id="dashboard-data" type="application/json">'+safe+'</script>')
    path.write_text(html,encoding="utf-8")
    print("DASHBOARD_EMBED",len(data.get("signals",[])),"signals")
if __name__=="__main__":main()
