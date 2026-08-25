"""Full-scope variant of the verifier input pack.

Identical task, schema and rules to the section-scoped build. The only change is
the evidence available per claim: all 351 papers from the filtered table the
section writers had, instead of that section's 20-paper subset. Holding
everything else fixed makes the scope the single variable.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path("/Users/abishek/personal/scispace-eval")
DUMP = ROOT / "data/dump"

claims = json.loads(
    re.search(r"```json\s*(\[.*?\])\s*```", (DUMP / "claims_cea2bed8.md").read_text(), re.S).group(1)
)
pack = (DUMP / "adjudication_pack_cea2bed8.md").read_text()
# Drop the adjudication pack's own preamble; this file supplies its own.
evidence = pack.split("---\n", 1)[1].strip()

out: list[str] = []
w = out.append

w("# Claim Verifier — Input Pack (FULL SCOPE)")
w("")
w("**Claims to verify:** 137  ")
w("**Evidence papers:** 351 — the complete filtered paper table the report's section")
w("writers had access to. No section restriction.")
w("")
w("---")
w("")
w("## Your task")
w("")
w("For each claim below, decide whether the evidence in this pack supports it.")
w("You are verifying groundedness, not writing prose. One verdict record per claim.")
w("")
w("### Hard rules")
w("")
w("1. **Use only the evidence in this file.** No web, no other files, no background")
w("   knowledge of the literature. If this pack does not contain the evidence, the verdict")
w("   is `insufficient_evidence` — a real and expected answer, not a failure.")
w("2. **Quote or it did not happen.** Every verdict carries `evidence_quote`: the exact")
w("   substring you relied on. A verdict with no quote is a guess.")
w("3. **Strict default.** Ambiguous or partial support is `unsupported`.")
w("4. **Do not judge writing quality**, hedging, tone or completeness. Only groundedness.")
w("")
w("### Scope — read this, it differs from earlier runs")
w("")
w("**Every claim is checked against all 351 papers.** There is no per-section evidence")
w("restriction. A claim in the Conclusion may be supported by any paper in the pack.")
w("")
w("Papers carry `P` ids. Where a paper also appeared in a section's relevant subset it")
w("shows an `E` id too; ignore that unless it is convenient.")
w("")
w("### Universal negatives — the discipline this run requires")
w("")
w("With 351 papers you cannot honestly claim to have read every one for every claim. So")
w("when your verdict rests on absence of evidence, **do not assert that no paper supports")
w("the claim.** Instead:")
w("")
w("- State what you actually searched for: the terms, metrics or concepts you scanned on.")
w("- Report it as a bounded negative in `search_note`, e.g. \"scanned for 'early fusion',")
w("  'late fusion', 'feature-level', 'decision-level' — 6 papers matched, 1 favours early\".")
w("- If you cannot bound it, the verdict is `insufficient_evidence`, not `unsupported`.")
w("")
w("An unfalsifiable \"nothing supports this\" is worse than an honest \"I could not confirm\".")
w("")
w("### The citation problem")
w("")
w("The report prints `[1]`–`[29]` but ships no bibliography, and the key-to-paper mapping")
w("is not recoverable. Treat `cited_papers` as uninterpretable metadata, never mark a claim")
w("unsupported because of its citation key, and set `citation_checkable: false` throughout.")
w("")
w("### Bundled claims")
w("")
w("Some claims assert two things at once (a hierarchy *and* consistency; maturity *and*")
w("study volume). If the two halves have different answers, set `verdict` for the claim as a")
w("whole to the weaker of the two and use `bundled_split` to record each half separately.")
w("")
w("### Verdict schema — one JSON object per claim")
w("")
w("```json")
w(json.dumps(
    {
        "id": "c17",
        "verdict": "supported | unsupported | insufficient_evidence",
        "supporting_evidence_ids": ["P12"],
        "evidence_quote": "exact substring from the pack",
        "evidence_field": "abstract | criteria_cell",
        "severity": "fabricated | distorted | overreach | none",
        "citation_checkable": False,
        "reason": "one sentence naming the exact match or mismatch",
        "numeric_delta": "report value vs source value, or null",
        "search_note": "what you scanned for and how many papers matched, when the verdict rests on absence",
        "bundled_split": [
            {"assertion": "first half restated", "verdict": "supported"},
            {"assertion": "second half restated", "verdict": "unsupported"},
        ],
    },
    indent=2,
))
w("```")
w("")
w("`bundled_split` is `null` for single-assertion claims. `search_note` is `null` when the")
w("verdict rests on positive evidence rather than absence.")
w("")
w("**`verdict`**")
w("")
w("- `supported` — a paper states this and you can quote it.")
w("- `unsupported` — the evidence contradicts the claim or states a materially different")
w("  value, or the claim's strength words outrun what you found.")
w("- `insufficient_evidence` — nothing you found speaks to the claim. Common for figures")
w("  that live in a paper's results tables rather than its abstract. Not a hallucination.")
w("")
w("**`severity`** — only when `unsupported`:")
w("")
w("- `fabricated` — the value or finding appears nowhere.")
w("- `distorted` — right study and metric, wrong value, or right value on the wrong cohort,")
w("  dataset or condition (validation reported as test).")
w("- `overreach` — evidence points this way but is weaker than the claim states.")
w("")
w("**For `type: synthesis` claims**, say in `reason` how many papers you checked and how")
w("many actually supported the claim.")
w("")
w("### Output")
w("")
w("Write to `/Users/abishek/personal/scispace-eval/data/dump/verdicts_fullscope_cea2bed8.md`:")
w("")
w("1. Summary tables: counts by verdict, severity, claim `type`, `materiality`")
w("2. Per-section breakdown table")
w("3. `## Full records` — complete JSON array of all 137 verdicts in a ```json block")
w("4. `## Notes` — hardest calls, and any claim where wider scope changed what you could find")
w("")
w("Every id `c1`–`c137` must appear exactly once.")
w("")
w("---")
w("")
w("## Claims to verify")
w("")

by_section: dict[str, list[dict]] = {}
for c in claims:
    by_section.setdefault(c["section"], []).append(c)

for section, cs in by_section.items():
    w(f"### {section}")
    w("")
    for c in cs:
        w(f"**{c['id']}** · `{c['type']}` · `{c['materiality']}` · cited: {c['cited_papers'] or 'none'}")
        w("")
        w(f"- **Claim:** {c['claim']}")
        w(f"- **Verbatim:** \"{c['verbatim']}\"")
        w("")

w("---")
w("")
w("## Evidence set — all 351 papers")
w("")
w(evidence)

text = "\n".join(out)
dest = DUMP / "verifier_input_fullscope_cea2bed8.md"
dest.write_text(text)
print(f"{dest}  {len(text):,} chars  ~{len(text)//4:,} tokens")
print(f"claims {len(claims)}  sections {len(by_section)}")
