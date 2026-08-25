# scispace-eval

Hallucination evaluation harness for SciSpace Agent's Report Writing output.

Phase 0 (evidence acquisition) is implemented. The claim extractor, verifier and
metrics rollup build on the canonical schema this phase produces.

## Why acquisition is its own phase

Report Writing is not a single generation step. Every figure in a report has
travelled two hops:

```
paper abstract  ──hop 1──►  table cell  ──hop 2──►  report sentence
                (extraction)             (generation)
```

A wrong number can be introduced at either hop, and the fixes are owned by
different components. Telling them apart requires the **enriched paper table** —
the intermediate representation the agent actually wrote from. An output-only
evaluation does not have it, and so can produce a hallucination rate but cannot
attribute it. Everything downstream depends on capturing that artefact.

## Pipeline stages recovered from a run

Stage boundaries are inferred from the tool-call sequence, since the pipeline is
observable but not instrumentable:

| Stage | Tool | Artefact |
|---|---|---|
| 1 Retrieval | six parallel `*_search` calls | per-source paper tables |
| 2 Consolidation | `rerank_and_combine_paper_tables` | one ranked table |
| 3 Criteria | `add_column_to_search_results_using_llm` | criterion name + extraction prompt |
| 4 Extraction | same call, per cell | table cells |
| 5 Generation | `filesystem_file_write` | the report |

`read_paper_table` is called twice, bare and then with `columns`. Only the
second carries cell data, so the parser takes the last such call.

## Install

```bash
uv venv && uv pip install -r requirements.txt
cp .env.example .env    # then fill in SCISPACE_COOKIE
```

Auth: the API needs a logged-in session. In a browser with SciSpace open,
DevTools > Network > any `/api/scispace-agent/*` request > Copy as cURL, and put
the `Cookie` header value into `SCISPACE_COOKIE`. Unauthenticated calls return
`401 user_not_in_request`.

## Use

```bash
export PYTHONPATH=src

# confirm which undocumented endpoint paths actually work, against a known thread
python -m scispace_eval probe <thread-id>

# enumerate runs -> data/raw/threads_index.json
python -m scispace_eval list

# pull raw state + artefacts for every listed thread -> data/raw/<thread>.json
python -m scispace_eval fetch --from-index

# parse into canonical runs -> data/runs/<thread>.json
python -m scispace_eval normalize

# resolve cited DOIs against two registries, fetch abstracts -> data/out/sources.json
python -m scispace_eval ground-truth
```

Raw responses are always written before parsing. The parser will change as the
eval grows; re-collecting is rate-limited and expensive.

## Design decisions worth knowing

**Ground truth comes from outside the pipeline under test.** If stage 4
mis-extracts a value from an abstract and the eval re-reads that abstract
through SciSpace's own retrieval layer, the error is invisible — the evaluation
inherits the bug it is looking for. Sources are resolved via Crossref, OpenAlex
and Semantic Scholar.

**A citation is invalid only if both registries fail it.** On the pilot run, two
DOIs resolve in OpenAlex but not Crossref. Crossref-only validation would report
them as fabricated. Publishers register with different agencies; single-registry
validation over-reports fabrication.

**Existence checks and abstract fetching are separate passes.** Semantic Scholar
is limited to roughly 1 req/s without a key. Coupling it to the existence check
makes the whole batch run at S2 speed.

**Runs are filtered on completeness, and drops are counted.** A report without
its table, or a table without identifiers, cannot be attributed. It is excluded
and reported, never silently included with partial evidence.

**Built-in table columns are not criteria.** `Relevance` and `Abstract` ship
with every table. Only agent-derived columns represent the comparison the user
asked for, so the criteria-fidelity eval must not credit the built-ins.

## Pilot run findings

Thread `4e23468e`, query: AI-based early cancer detection, comparing performance
across imaging, genomics and multimodal approaches using AUC, sensitivity and
specificity.

- 129 papers retrieved, top 30 read into the report.
- **2 criteria columns derived** — *AI Methodology and Modality* and
  *Performance Metrics* — for a query naming three metrics across three approach
  types. All three metrics were collapsed into one free-text column, so the
  comparison the user asked for was structurally discarded before extraction
  began. Upstream of every hallucination check.
- Both extraction prompts ran with `use_full_text: true`. The agent had more
  evidence than this harness can independently obtain, which sets the ceiling on
  external verifiability.
- **29/29 DOIs resolve.** No fabricated citations in this run.
- **2 of 29 are not peer reviewed**: one Zenodo upload, one Research Square
  preprint. Legitimate records, but a material distinction for a research
  audience that the report does not surface.
- 28/29 abstracts obtained. The one gap is a Nature paper with no abstract in
  any registry — a concrete driver of the unverifiable rate, not a product
  failure.

A first pass over this run reported one DOI as malformed and unresolvable. That
was a parser bug in this harness truncating `10.21103/Article13(1)_RA1` at the
parenthesis, not a SciSpace failure. It is the same false-positive class the
dual-registry rule exists to prevent, and the reason `probe`, raw-response
persistence and completeness accounting are in the design rather than bolted on.

## Layout

```
src/scispace_eval/
  config.py              credentials, paths, .env loading
  http.py                browser-shaped session, backoff on 429/5xx, disk cache
  schema.py              canonical models: Run, PaperRow, Criterion, SourceRecord
  collect/
    threads.py           enumerate runs, probe endpoint paths, fetch raw
    normalize.py         LangGraph state -> canonical Run
    groundtruth.py       Crossref + OpenAlex + Semantic Scholar
    cli.py               probe / list / fetch / normalize / ground-truth
data/
  raw/                   raw API responses, one file per thread
  runs/                  canonical runs
  out/                   sources.json and eval outputs
  labels/                hand labels for judge calibration
```
