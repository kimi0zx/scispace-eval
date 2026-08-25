# Example records

Three claims from the run in `summary.json`, each with the verdict it received. The full
ledgers are not committed: they quote the generated report and the source abstracts at
length, and it is the schema that matters here.

## c133 — `overstated`

The claim states more than the source supports. `source_measured` and `claim_presents_as` diverge, and that divergence is what forces the verdict rather than leaving the model to notice it.

**claims.md**

```json
{
  "id": "c133",
  "claim": "Wearable devices have demonstrated measurable impacts on long-term health outcomes across multiple chronic disease domains.",
  "verbatim": "Wearable devices have demonstrated measurable impacts on long-term health outcomes across multiple chronic disease domains.",
  "section": "5.1 Clinical Outcomes and Healthcare Utilization",
  "type": "synthesis",
  "severity": "P0",
  "restates": null
}
```

**verdicts.md**

```json
{
  "id": "c133",
  "verdict": "overstated",
  "evidence_ids": [
    "P61"
  ],
  "quote": "Despite the perceived benefits of wearables in improving chronic disease self-management, their influence on health care outcomes remains poorly understood.",
  "quote_field": "abstract",
  "source_measured": "P61: mixed 50/50 results, influence poorly understood",
  "claim_presents_as": "demonstrated measurable long-term impacts across domains",
  "value_check": "not_applicable",
  "reason": "The systematic review evidence supports mixed, poorly understood effects, not demonstrated long-term impacts.",
  "search_note": null
}
```

## c9 — `overstated`

A range assembled from two separate sources. Each endpoint verifies on its own, so checking the components tells you nothing.

**claims.md**

```json
{
  "id": "c9",
  "claim": "Wearables can reduce hospitalizations by 20\u201325% when integrated with appropriate clinical support.",
  "verbatim": "Key findings indicate that wearables can increase physical activity by approximately 1,519 steps per day, improve treatment adherence by 20\u201330%, and reduce hospitalizations by 20\u201325% when integrated with appropriate clinical support.",
  "section": "Executive Summary",
  "type": "numeric",
  "severity": "P0",
  "restates": null
}
```

**verdicts.md**

```json
{
  "id": "c9",
  "verdict": "overstated",
  "evidence_ids": [
    "P16",
    "P17"
  ],
  "quote": "Analysis is carried out on the outcomes which reveals a 25 percent decrease in hospitalization incidences per early diagnosis of chronic diseases",
  "quote_field": "abstract",
  "source_measured": "P16: 25% hospitalization decrease from one AI-wearable analysis; P17 data cell 20% admissions (uncorroborated)",
  "claim_presents_as": "general 20\u201325% hospitalization reduction when integrated with clinical support",
  "value_check": "exact",
  "reason": "Range stitched from two separate studies and given a clinical-support condition no source states.",
  "search_note": null
}
```

## c3 — `miscited`

Scored `miscited` by the verifier, then downgraded to `unverifiable` by the scorer because its only source carries no text of its own. It appears under `integrity.downgraded_unauditable_source` in `summary.json`.

**claims.md**

```json
{
  "id": "c3",
  "claim": "Continuous glucose monitors achieve 85\u201395% accuracy.",
  "verbatim": "The evidence reveals that wearable devices demonstrate moderate to high effectiveness in managing chronic conditions, with continuous glucose monitors achieving 85\u201395% accuracy and activity trackers showing significant behavioral improvements.",
  "section": "Executive Summary",
  "type": "numeric",
  "severity": "P0",
  "restates": null
}
```

**verdicts.md**

```json
{
  "id": "c3",
  "verdict": "miscited",
  "evidence_ids": [
    "P5"
  ],
  "quote": "Wearable technologies offer 85\u201395% accuracy of vitals.",
  "quote_field": "data_cell",
  "source_measured": "P5 data cell: accuracy of vital-sign monitoring by wearables in chronic disease generally",
  "claim_presents_as": "accuracy of continuous glucose monitors",
  "value_check": "exact",
  "reason": "The only source with 85\u201395% attributes it to vital-sign accuracy, not CGM; the report itself (c32) uses the figure for vital signs.",
  "search_note": "Scanned all sources for CGM accuracy percentages; P5 is the only 85\u201395% and refers to vitals."
}
```
