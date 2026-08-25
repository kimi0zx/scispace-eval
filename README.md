# scispace-eval

A hallucination eval for SciSpace Agent's Report Writing. Takes a thread ID, returns a
scored verdict on every checkable claim the report makes.

## Setup

```bash
uv venv && uv pip install -r requirements.txt
cp .env.example .env      # fill in SCISPACE_COOKIE
export PYTHONPATH=src
```

`SCISPACE_COOKIE` is the only credential. Get it from a logged-in browser: DevTools →
Network → any `/api/scispace-agent/*` request → Copy as cURL → take the `Cookie` header.

Nothing else to configure. The two agents run through the Claude Code CLI, which uses its
own auth, so if `claude` works in your shell this works.

## Run

```bash
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

`--stop-after extract|claims` to run part way. `--force` to ignore the cache.
`--model` to change the model.

Output lands in `data/pipeline/<thread-id>/`: `claims.md`, `verdicts.md`,
`summary.json`.

## How it works

Two agents. The **extractor** reads only the report and splits it into atomic
checkable claims. The **verifier** reads only the claims and the papers, and rules on
each one.

Neither sees what the other sees. An agent that reads the report and the sources
together skips claims it can tell are unprovable, which shrinks the denominator instead
of raising the failure count.

## Verdicts

| | |
|---|---|
| `verified` | a source backs the claim |
| `unfounded` | the claim appears nowhere |
| `miscited` | the number is real, the source measured something else |
| `overstated` | the claim reaches past its evidence |
| `unverifiable` | nothing speaks to it either way |

## Severity and the gate

**P0** a reader who acts on this acts wrongly · **P1** one sub-area wrong ·
**P2** nothing a reader concludes changes.

The gate blocks on **P0 `unfounded` or `miscited`**.

`overstated` is tracked, not gated — over-generalisation is endemic to summarisation.
`unverifiable` is our evidence limit, not a product defect, and never counts as a
failure.

## Three rules in the scorer

- **No receipt, no verdict.** Every verdict quotes the evidence character for character,
  checked as a literal substring. A paraphrase is void.
- **Restatements collapse.** A figure repeated in four sections is one assertion. When
  collapsing, the failing instance wins so dedup can't hide an error.
- **Extracted cells aren't evidence.** They're LLM summaries of full text we never see. A
  failure resting only on sources with no abstract is downgraded to `unverifiable`.

## Layout

```
src/scispace_eval/
  cli.py            the verify command
  config.py         credentials and paths
  endpoints.py      the two API surfaces
  http.py           session, backoff, cache
  pipeline/
    report.py       run artefacts -> report + evidence
    render.py       prompt assembly
    agent.py        runs a prompt through the Claude CLI
    score.py        receipts, dedup, the gate
    run.py          the five stages
    prompts/        extractor.md, verifier.md
```

## Limitations

- Abstracts only, not full text. The agent's own extraction had more than this can reach.
- No human-labelled ground truth. A model checking a model.
- Citation binding untestable — the reports ship no bibliography.
- Small n: ~18 P0 assertions per run, so one claim moves the rate several points.
