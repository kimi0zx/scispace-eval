"""Fetch and persist everything scrapable for one thread, then render it as HTML."""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from scispace_eval import config
from scispace_eval.http import Client

TID = sys.argv[1] if len(sys.argv) > 1 else "cea2bed8-15aa-409a-b3f3-fcf4285cd6c9"
OUT = config.DATA_DIR / "dump" / TID
OUT.mkdir(parents=True, exist_ok=True)


def fetch_all() -> dict:
    c = Client(headers=config.credentials().headers(), min_interval=0.2)
    bundle: dict = {"thread_id": TID}
    bundle["thread"] = c.get_json(f"{config.API_BASE}/threads/{TID}", allow_404=True)
    bundle["state"] = c.get_json(f"{config.LANGGRAPH_BASE}/threads/{TID}/state", allow_404=True)
    bundle["thread_lg"] = c.get_json(f"{config.LANGGRAPH_BASE}/threads/{TID}", allow_404=True)
    arts = c.get_json(f"{config.API_BASE}/threads/{TID}/artifacts", allow_404=True) or {}
    bundle["artifacts"] = arts

    files: dict[str, dict] = {}
    for a in arts.get("data", []):
        path = a["sandbox_path"]
        try:
            r = c.session.get(a["serve_url"], timeout=120)
            files[path] = {
                "status": r.status_code,
                "bytes": len(r.content),
                "mime": a.get("mime_type"),
                "text": r.text if r.status_code == 200 else r.text[:500],
            }
        except Exception as exc:  # noqa: BLE001
            files[path] = {"status": "ERR", "bytes": 0, "mime": a.get("mime_type"), "text": str(exc)}
        print(f"  {files[path]['status']}  {files[path]['bytes']:>9}  {path}", flush=True)
    bundle["files"] = files
    return bundle


def esc(x) -> str:
    return html.escape(x if isinstance(x, str) else json.dumps(x, indent=2, ensure_ascii=False))


def pretty(text: str) -> str:
    t = text.strip()
    if t[:1] in "{[":
        try:
            return json.dumps(json.loads(t), indent=2, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            pass
    return text


def msg_rows(messages: list[dict]) -> str:
    out = []
    for i, m in enumerate(messages):
        calls = m.get("tool_calls") or []
        content = m.get("content")
        ctext = content if isinstance(content, str) else json.dumps(content, indent=2, ensure_ascii=False) if content else ""
        kind = m.get("type") or "?"
        name = m.get("name") or ""
        label = ", ".join(c.get("name", "?") for c in calls) or name or kind
        size = len(ctext)
        body = []
        if ctext:
            body.append(f"<div class=lbl>content <span class=sz>{size:,} chars</span></div><pre>{esc(pretty(ctext))}</pre>")
        for c in calls:
            body.append(
                f"<div class=lbl>tool_call <code>{esc(c.get('name'))}</code> args</div>"
                f"<pre>{esc(c.get('args'))}</pre>"
            )
        extra = {k: v for k, v in m.items() if k not in {"content", "tool_calls", "type", "name"}}
        if extra:
            body.append(f"<div class=lbl>other fields</div><pre>{esc(extra)}</pre>")
        out.append(
            f"<details class='msg {kind}'><summary>"
            f"<span class=idx>{i}</span><span class='tag {kind}'>{esc(kind)}</span>"
            f"<span class=nm>{esc(label)}</span>"
            f"<span class=meta>{esc(name)}</span><span class=sz>{size:,}</span>"
            f"</summary>{''.join(body)}</details>"
        )
    return "\n".join(out)


def file_blocks(files: dict) -> str:
    out = []
    for path, f in sorted(files.items()):
        text = f.get("text") or ""
        out.append(
            f"<details class=file><summary><span class=nm>{esc(path)}</span>"
            f"<span class=meta>{esc(f.get('mime') or '')}</span>"
            f"<span class=sz>{f.get('bytes', 0):,} B</span>"
            f"<span class='tag {'ok' if f.get('status') == 200 else 'bad'}'>{esc(str(f.get('status')))}</span>"
            f"</summary><pre>{esc(pretty(text))}</pre></details>"
        )
    return "\n".join(out)


CSS = """
:root{--bg:#0f1115;--card:#171a21;--card2:#1d212a;--fg:#e6e8ee;--dim:#9aa3b2;
--line:#2a2f3a;--acc:#7aa2f7;--ok:#7bc86c;--bad:#e5787d;--warn:#e0af68;--mono:ui-monospace,SFMono-Regular,Menlo,monospace}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
header{position:sticky;top:0;z-index:10;background:#0f1115f2;backdrop-filter:blur(8px);
border-bottom:1px solid var(--line);padding:14px 22px}
h1{margin:0 0 4px;font-size:17px;letter-spacing:.2px}
.sub{color:var(--dim);font-size:12px;font-family:var(--mono)}
nav{display:flex;gap:14px;flex-wrap:wrap;margin-top:10px}
nav a{color:var(--acc);text-decoration:none;font-size:12px;border:1px solid var(--line);
padding:3px 9px;border-radius:5px}
nav a:hover{background:var(--card2)}
main{padding:22px;max-width:1500px;margin:0 auto}
section{margin:0 0 34px}
h2{font-size:14px;text-transform:uppercase;letter-spacing:.09em;color:var(--dim);
border-bottom:1px solid var(--line);padding-bottom:7px;margin:0 0 14px}
.stats{display:grid;grid-template-columns:repeat(auto-fill,minmax(165px,1fr));gap:9px;margin-bottom:16px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:7px;padding:10px 12px}
.stat b{display:block;font-size:19px;font-family:var(--mono)}
.stat span{color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:.06em}
details{background:var(--card);border:1px solid var(--line);border-radius:7px;margin-bottom:6px;overflow:hidden}
details[open]{background:var(--card2)}
summary{cursor:pointer;padding:8px 12px;display:flex;gap:10px;align-items:center;
font-family:var(--mono);font-size:12px;list-style:none}
summary::-webkit-details-marker{display:none}
summary:hover{background:#222735}
.idx{color:var(--dim);min-width:30px;text-align:right}
.tag{font-size:10px;padding:1px 6px;border-radius:4px;background:#252b38;color:var(--dim);text-transform:uppercase}
.tag.ai{background:#1e3a5f;color:#9ec5fe}.tag.tool{background:#3a2f1e;color:var(--warn)}
.tag.human{background:#1e3f2f;color:var(--ok)}.tag.ok{background:#1e3f2f;color:var(--ok)}
.tag.bad{background:#4a1f22;color:var(--bad)}
.nm{color:var(--fg);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.meta{color:var(--dim);font-size:11px}
.sz{color:var(--dim);font-size:11px;font-variant-numeric:tabular-nums}
pre{margin:0;padding:12px 14px;overflow-x:auto;font-family:var(--mono);font-size:11.5px;
line-height:1.5;background:#0c0e13;border-top:1px solid var(--line);white-space:pre-wrap;
word-break:break-word;max-height:620px;overflow-y:auto}
.lbl{padding:7px 14px 0;font-size:10px;text-transform:uppercase;letter-spacing:.07em;color:var(--dim)}
.lbl code{color:var(--acc);text-transform:none;letter-spacing:0}
.bar{display:flex;gap:8px;margin-bottom:12px}
button{background:var(--card2);color:var(--fg);border:1px solid var(--line);border-radius:5px;
padding:5px 11px;font-size:12px;cursor:pointer;font-family:inherit}
button:hover{border-color:var(--acc)}
table{width:100%;border-collapse:collapse;font-size:12px;font-family:var(--mono)}
th,td{text-align:left;padding:6px 10px;border-bottom:1px solid var(--line)}
th{color:var(--dim);font-weight:500;font-size:11px;text-transform:uppercase}
td.n{text-align:right;font-variant-numeric:tabular-nums}
"""

JS = """
function setAll(open){document.querySelectorAll('details').forEach(d=>d.open=open)}
function setIn(sel,open){document.querySelectorAll(sel+' details').forEach(d=>d.open=open)}
"""


def render(b: dict) -> str:
    state = b.get("state") or {}
    messages = ((state.get("values") or {}).get("messages")) or []
    files = b.get("files") or {}
    arts = (b.get("artifacts") or {}).get("data") or []
    thread = b.get("thread") or {}

    tools = [c.get("name") for m in messages for c in (m.get("tool_calls") or [])]
    ok_files = sum(1 for f in files.values() if f.get("status") == 200)
    fbytes = sum(f.get("bytes", 0) for f in files.values())
    state_bytes = len(json.dumps(state))

    verif = []
    for m in messages:
        if m.get("type") == "tool" and m.get("name") == "write_section_with_verification":
            try:
                verif.append(json.loads(m["content"]))
            except Exception:  # noqa: BLE001
                pass
    vrows = "".join(
        f"<tr><td>{esc(v.get('section_name'))}</td><td class=n>{v.get('verification_cycle_count')}</td>"
        f"<td>{v.get('corrections_applied')}</td>"
        f"<td><span class='tag {'ok' if v.get('status') == 'approved' else 'bad'}'>{esc(v.get('status'))}</span></td></tr>"
        for v in verif
    )
    vtable = (
        f"<table><tr><th>section</th><th>cycles</th><th>corrected</th><th>status</th></tr>{vrows}</table>"
        if verif else "<p class=sub>no self-verification calls in this thread</p>"
    )

    edits = [c["args"] for m in messages for c in (m.get("tool_calls") or [])
             if c.get("name") == "filesystem_replace_text_in_file"]
    erows = "".join(
        f"<details><summary><span class=idx>{i}</span><span class=nm>{esc((e.get('path') or '').split('/')[-1])}</span>"
        f"<span class=sz>{len(e.get('old_string') or '')} &rarr; {len(e.get('new_string') or '')}</span></summary>"
        f"<div class=lbl>old</div><pre>{esc(e.get('old_string') or '')}</pre>"
        f"<div class=lbl>new</div><pre>{esc(e.get('new_string') or '')}</pre></details>"
        for i, e in enumerate(edits)
    ) or "<p class=sub>none</p>"

    tool_counts: dict[str, int] = {}
    for t in tools:
        tool_counts[t] = tool_counts.get(t, 0) + 1
    trows = "".join(
        f"<tr><td>{esc(k)}</td><td class=n>{v}</td></tr>"
        for k, v in sorted(tool_counts.items(), key=lambda x: -x[1])
    )

    return f"""<!doctype html><html><head><meta charset=utf-8>
<title>SciSpace raw dump — {esc(TID[:8])}</title><style>{CSS}</style></head><body>
<header>
  <h1>SciSpace thread — everything scrapable</h1>
  <div class=sub>{esc(TID)} &nbsp;·&nbsp; {esc(str(thread.get('title')))} &nbsp;·&nbsp;
  report_mode: {esc(str((thread.get('active_filters') or {}).get('report_mode')))} &nbsp;·&nbsp;
  created {esc(str(thread.get('created_at')))}</div>
  <nav>
    <a href=#overview>overview</a><a href=#verify>self-verification</a>
    <a href=#edits>corrections ({len(edits)})</a><a href=#messages>messages ({len(messages)})</a>
    <a href=#files>artifact files ({len(files)})</a><a href=#tools>tool census</a>
    <a href=#thread>thread meta</a><a href=#artmeta>artifact metadata</a>
  </nav>
</header>
<main>
<section id=overview><h2>Overview</h2>
<div class=stats>
  <div class=stat><b>{len(messages)}</b><span>messages</span></div>
  <div class=stat><b>{len(tools)}</b><span>tool calls</span></div>
  <div class=stat><b>{len(set(tools))}</b><span>distinct tools</span></div>
  <div class=stat><b>{len(arts)}</b><span>artifacts listed</span></div>
  <div class=stat><b>{ok_files}/{len(files)}</b><span>files fetched</span></div>
  <div class=stat><b>{state_bytes / 1024:,.0f} KB</b><span>state json</span></div>
  <div class=stat><b>{fbytes / 1024:,.0f} KB</b><span>artifact bytes</span></div>
  <div class=stat><b>{len(edits)}</b><span>in-place corrections</span></div>
</div>
<div class=bar>
  <button onclick="setAll(true)">expand all</button>
  <button onclick="setAll(false)">collapse all</button>
</div></section>

<section id=verify><h2>Self-verification outcomes</h2>{vtable}</section>
<section id=edits><h2>In-place corrections its own verifier applied</h2>{erows}</section>
<section id=messages><h2>Messages &amp; tool calls</h2>
<div class=bar><button onclick="setIn('#messages',true)">expand</button>
<button onclick="setIn('#messages',false)">collapse</button></div>
{msg_rows(messages)}</section>
<section id=files><h2>Artifact file contents</h2>
<div class=bar><button onclick="setIn('#files',true)">expand</button>
<button onclick="setIn('#files',false)">collapse</button></div>
{file_blocks(files)}</section>
<section id=tools><h2>Tool census</h2><table><tr><th>tool</th><th>calls</th></tr>{trows}</table></section>
<section id=thread><h2>Thread metadata</h2>
<details open><summary><span class=nm>/api/scispace-agent/threads/{{id}}</span></summary>
<pre>{esc(thread)}</pre></details>
<details><summary><span class=nm>/langgraph/threads/{{id}}</span></summary>
<pre>{esc({k: v for k, v in (b.get('thread_lg') or {}).items() if k != 'values'})}</pre></details>
<details><summary><span class=nm>state.metadata + checkpoint</span></summary>
<pre>{esc({k: v for k, v in state.items() if k != 'values'})}</pre></details></section>
<section id=artmeta><h2>Artifact metadata (listing)</h2>
<details><summary><span class=nm>{len(arts)} entries</span></summary><pre>{esc(arts)}</pre></details></section>
</main><script>{JS}</script></body></html>"""


print(f"fetching {TID} ...")
bundle = fetch_all()
(OUT / "bundle.json").write_text(json.dumps(bundle, indent=2, ensure_ascii=False))
out_html = OUT / "index.html"
out_html.write_text(render(bundle))
print(f"\nbundle -> {OUT / 'bundle.json'}")
print(f"html   -> {out_html}  ({out_html.stat().st_size / 1024:,.0f} KB)")
