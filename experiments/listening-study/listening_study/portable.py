"""Self-contained synthetic demo, including the actual UI and generated WAV bytes."""
import base64
import hashlib
import json
from pathlib import Path
from .common import digest, require
from .design import public_bundle, validate_study


def export_demo(study, out, *, slot=0, prompt="next"):
    require(study["demo"] is True, "Portable audio export is limited to synthetic demo")
    validate_study(study, audio=True)
    bundle = public_bundle(study, slot, prompt)
    audio = {"/audio/" + digest({"study": study["sha256"], "track": tid})[:32]:
             "data:audio/wav;base64," + base64.b64encode(Path(t["clip"]).read_bytes()).decode()
             for tid, t in study["tracks"].items()}
    for trial in bundle["trials"]:
        for key in ("source", "left", "right"):
            trial[key] = audio[trial[key]]
    web = Path(__file__).parent / "web"
    css, js = (web / "style.css").read_text(), (web / "app.js").read_text()
    def csp_hash(text):
        return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode()).digest()).decode() + "'"
    csp = f"default-src 'none'; img-src data:; media-src data:; style-src {csp_hash(css)}; script-src {csp_hash(js)}; base-uri 'none'; form-action 'none'"
    html = (web / "index.html").read_text()
    html = html.replace('<link rel="stylesheet" href="/style.css">', f'<meta http-equiv="Content-Security-Policy" content="{csp}"><style>{css}</style>')
    html = html.replace('<script src="/app.js" defer></script>', '')
    html = html.replace('href="/"', 'href=""')
    data = json.dumps(bundle, ensure_ascii=False).replace("<", "\\u003c")
    html = html.replace("</body>", f'<script id="embedded-study" type="application/json">{data}</script><script>{js}</script></body>')
    with Path(out).open("x", encoding="utf-8") as f:
        f.write(html)
