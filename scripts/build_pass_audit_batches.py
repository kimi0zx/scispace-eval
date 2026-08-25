"""Split the 132 `supported` verdicts into batches for adversarial pass auditing.

The failures were audited hard; the passes never were. This builds one file per
batch carrying the claims and the verdicts that passed them, so an auditor can
attack each pass against the shared 351-paper evidence pack.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path("/Users/abishek/personal/scispace-eval")
DUMP = ROOT / "data/dump"
OUT = DUMP / "pass_audit"
OUT.mkdir(parents=True, exist_ok=True)
BATCH = 10


def load(fn: str) -> dict:
    body = (DUMP / fn).read_text()
    return {x["id"]: x for x in json.loads(re.search(r"```json\s*(\[.*?\])\s*```", body, re.S).group(1))}


claims = load("claims_cea2bed8.md")
verdicts = load("verdicts_fullscope_cea2bed8.md")

passed = [i for i in sorted(claims, key=lambda x: int(x[1:])) if verdicts[i]["verdict"] == "supported"]
batches = [passed[i : i + BATCH] for i in range(0, len(passed), BATCH)]

for n, ids in enumerate(batches, 1):
    out: list[str] = []
    w = out.append
    w(f"# Pass Audit — batch {n} of {len(batches)}")
    w("")
    w(f"**Claims in this batch:** {len(ids)} — {', '.join(ids)}")
    w("")
    w("Each of these was marked `supported` by the verifier. Your job is to attack that.")
    w("")
    w("---")
    w("")
    for i in ids:
        c, v = claims[i], verdicts[i]
        w(f"## {i}")
        w("")
        w(f"- **Section:** {c['section']}")
        w(f"- **Type:** `{c['type']}` · **Materiality:** `{c['materiality']}`")
        w(f"- **Citation keys in report:** {c['cited_papers'] or 'none'}")
        w("")
        w(f"**Claim as extracted:** {c['claim']}")
        w("")
        w(f"**Verbatim from report:** \"{c['verbatim']}\"")
        w("")
        w("**The verdict you are auditing:** `supported`")
        w("")
        w(f"- Evidence cited: {v.get('supporting_evidence_ids')}")
        w(f"- Field: `{v.get('evidence_field')}`")
        w(f"- Quote relied on: \"{v.get('evidence_quote')}\"")
        w(f"- Stated reason: {v.get('reason')}")
        if v.get("numeric_delta"):
            w(f"- Numeric delta recorded: {v['numeric_delta']}")
        w("")
    (OUT / f"batch_{n:02d}.md").write_text("\n".join(out))

print(f"{len(passed)} supported claims -> {len(batches)} batches in {OUT}")
for n, ids in enumerate(batches, 1):
    print(f"  batch_{n:02d}: {len(ids):>2}  {ids[0]}..{ids[-1]}")
