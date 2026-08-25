# scispace-eval

A hallucination eval for SciSpace Agent's Report Writing output. Takes a thread ID,
returns a scored verdict on every checkable claim the report makes.

```bash
uv venv && uv pip install -r requirements.txt
cp .env.example .env          # then fill in SCISPACE_COOKIE
export PYTHONPATH=src

python -m scispace_eval verify <thread-id>
```

```
202 claims -> 156 distinct assertions

        total  verified  blocking  quality  unverifiable
 P0        18        10         0        5             3
 P1        67        61         0        2             4
 P2        71        62         0        1             8
 all      156       133         0        8            15

GATE PASS   no P0 unfounded or miscited claims
```

Auth: the API needs a logged-in session. In a browser with SciSpace open, DevTools →
Network → any `/api/scispace-agent/*` request → Copy as cURL, and put the `Cookie`
header value into `SCISPACE_COOKIE`. Unauthenticated calls return
`401 user_not_in_request`. A real environment variable overrides `.env`.

The two agents run through the Claude Code CLI in print mode, so there is no separate
API key: if `claude` works in your shell, this works.

## What it does

Five stages, each cached under `data/pipeline/<thread-id>/` so a rerun resumes rather
than repeats.

| Stage | Output | What it is |
|---|---|---|
| collect | `bundle.json` | thread state, artefact list, artefact contents |
| extract | `report_clean.md`, `evidence.json` | the report and the evidence set, recovered from the run |
| claims | `claims.md` | agent 1 — every checkable claim, with severity |
| verify | `verdicts.md` | agent 2 — one verdict per claim, each with a quote |
| score | `summary.json` | rates, the gate, and integrity checks |

`--stop-after extract` or `--stop-after claims` to run part way, `--force` to ignore the
cache, `--model` to change the model the agents run on.

## Why two agents

The **extractor** sees only the report. The **verifier** sees only the claims and the
evidence.

That split is not tidiness. A single agent reading the report and the sources together
quietly skips claims it can already tell are unprovable, which shrinks the denominator
rather than raising the failure count — the result looks better while measuring less.
Splitting the work means the extractor's only job is completeness and the verifier's
only job is judgement, and neither can trade one against the other.

The same logic runs the other way: a verifier that could see the surrounding narrative
would start assessing whether a claim fits the argument instead of whether the evidence
supports it.

## Verdicts

| Label | Meaning |
|---|---|
| `verified` | A source backs the claim: the value matches and the source measured the same thing |
| `unfounded` | The claim as stated appears nowhere, including a figure assembled from parts of different sources |
| `miscited` | The number is real and correctly copied, but the source measured something else |
| `overstated` | The evidence points the same way but supports less than the claim says |
| `unverifiable` | Nothing in the evidence speaks to it either way |

`miscited` is the label that carries the most weight. A figure can match to the last
digit and still be cited for the wrong outcome, population or model variant, so a
harness without this distinction records the entire class as passing.

## Severity, and the gate

Severity is assigned from consequence, not from where a claim sits in the document.

- **P0** — a reader who acts on this acts wrongly. Headline findings, summary figures, the thesis.
- **P1** — one sub-area is wrong, the report's conclusion still stands.
- **P2** — nothing a reader concludes changes.

The gate blocks on **P0 `unfounded` or `miscited`**: the report states something
factually wrong where a reader acts on it.

`overstated` is tracked, never gated. Over-generalisation is endemic to summarisation,
so gating on it would block every release; it belongs in a quality metric rather than a
correctness one. `unverifiable` is an evidence-access limit on our side, not a product
defect, and is never counted as a failure — pooling it either way would misstate both
the product's quality and the evaluation's own confidence.

## What the code refuses to trust

Most of the design exists because an earlier version of this harness got these wrong.

**A verdict without a receipt is void.** Every verdict must quote the evidence character
for character, and `score.py` checks that the quote is a literal span of the pack. A
paraphrased quote cannot be audited, so counting it asserts something unfalsifiable.

**Restatements collapse.** Reports state a headline figure in the introduction, again in
the body, again in the conclusion. Each instance is a real claim, but they are one
assertion, and counting four turns one error into four. Rates are per distinct assertion,
and when collapsing a group the scorer keeps the *failing* instance so deduplication can
never hide an error behind a pass.

**Extracted cells are not evidence.** The paper table's criteria cells are LLM summaries
of full text this harness never sees, and they demonstrably drop context — on one run an
imaging cell omitted the genomics and clinical inputs that the multimodal cell listed for
the same paper. A verdict resting on a cell must be confirmed against the source
abstract, and a failure asserted only against sources that have no abstract is downgraded
to `unverifiable` rather than counted.

**A reason may not contradict its verdict.** An earlier version wrote that a source
measured recurrence and then marked the detection claim supported. The scorer flags any
failure verdict whose reason contains "cannot be confirmed", "no abstract" and similar,
because those phrases belong only to `unverifiable`.

**Relevance scores never reach the verifier.** They are the pipeline's own inclusion
verdict, so showing them means inheriting the filtering decision the eval exists to
audit. On one run every relevance cell was stamped `0/100 "Not Relevant"` while its own
reasoning said the paper strongly supported the section.

## What the collector handles

**Two report-writing pipelines.** `standard` builds criteria columns on one shared table
and writes the report into a tool argument. `verified` writes each section through a
sub-agent whose text never enters the message list, so the report has to be recovered
from the artefact store. The mode is detected from the tool census rather than from thread
metadata, which is often absent.

**Report filenames are not stable.** A report may be `final_report.md` or named after the
query topic, and sections may sit in a `sections/` directory or as flat `section_NN_*`
files. Candidates are ranked rather than looked up, and the plan and summary files are
excluded explicitly because both sit next to the report.

**Retrieval tables are excluded from the evidence set.** Each source query writes its own
table before consolidation, holding papers that never survived reranking. Including them
would evaluate the report against material it could not have drawn on.

**Citation markers are stripped from the report.** The reports ship no bibliography, so
`[7]` resolves to nothing. Left in, a marker makes a claim look attributed and biases both
the severity call and the reader's trust.

**Self-verification is captured.** `verified`-mode runs report their own per-section
verification cycles and corrections, including sections that exit at `max_threshold` —
the verifier hit its cycle cap without converging and the section shipped anyway.

## Two API surfaces

Confirmed with `probe`. They are separate services and the split is not obvious:

| Data | Endpoint |
|---|---|
| Thread list | `GET /api/scispace-agent/threads` |
| Artefacts | `GET /api/scispace-agent/threads/{id}/artifacts` |
| Run state | `GET /langgraph/threads/{id}/state` |

Run state is the artefact that matters and it is not under `/api/`. The agent runtime is
LangGraph, reverse-proxied at `/langgraph` — the web bundle reads
`NEXT_PUBLIC_LANGGRAPH_API_URL` and falls back to `${origin}/langgraph`.
`/api/scispace-agent/threads/{id}/state` returns 404, which is why `probe` exists:
guessing one surface from the other silently loses the entire message history.

## Layout

```
src/scispace_eval/
  config.py              credentials, paths, .env loading
  http.py                browser-shaped session, backoff on 429/5xx, disk cache
  collect/
    threads.py           enumerate runs, probe endpoint paths, fetch raw
    cli.py               probe / list / fetch / verify
  pipeline/
    report.py            run artefacts -> the report and the evidence set
    render.py            prompt assembly from templates
    agent.py             runs a prompt through the Claude Code CLI
    score.py             receipts, deduplication, the gate, integrity checks
    run.py               the five stages
    prompts/
      extractor.md       agent 1
      verifier.md        agent 2
data/
  raw/                   thread listings
  pipeline/<thread-id>/  one directory per scored run
```

## Limitations

- **Abstracts, not full text.** The harness reads abstracts and the pipeline's extracted
  cells; the agent's own extraction ran on full text, so it worked from evidence this
  evaluation cannot reach. On one run only 49 of 351 sources were open access with
  structured full text.
- **No human-labelled ground truth.** This is a model checking a model. Judge TPR/TNR
  against hand labels is the missing piece, and nothing else substitutes for it.
- **Citation binding is untestable.** With no bibliography and no recoverable key mapping,
  whether a claim cites the *right* paper cannot be checked.
- **Small n.** Around eighteen distinct assertions at P0 in a single run, so one claim
  moves the rate by several points. The counts carry the meaning; the percentages need
  more runs behind them.
