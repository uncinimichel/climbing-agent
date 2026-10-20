# experimental/ontology — the climbing corpus as an RDF ontology

An experiment (2026-09-06) answering: *is it worth modelling the crag / place /
route record as a proper ontology, and could that stack be the final one?*
Three crags from the record and four ingest runs are converted into RDF with
an OWL ontology, SKOS vocabularies, SHACL rules and per-source named graphs,
then validated and queried. Nothing in `corpus/record`, the Studio or the
site is touched. Delete this folder and nothing else changes.

## The stack (chosen to be the last one, not just the first)

| Layer | Here | Final |
|---|---|---|
| Model | `climb.ttl` (OWL classes + properties, with `climb:level` / `climb:bucket` / `climb:evidenceRequired` field metadata) | same file |
| Code lists | `vocab.ttl`, **generated** from `corpus/record/taxonomies.json` + `grades.json` by `tools/vocab.py` (SKOS; 12 schemes, 147 concepts, 49 with `skos:exactMatch`/`closeMatch` to OSM `climbing:*`, OpenBeta, theCrag) | same generator |
| Rules | `shapes.ttl` (SHACL: closed enums, evidence on safety-critical hazards, publish ⇒ human, grade value matches its system, *no place facts on a route or crag header*) | same file, loaded into GraphDB's SHACL graph |
| Data | `data/generated/*.trig` (git-ignored — carries UKC/theCrag prose), `data/curated/*.ttl` (hand-written places) | GraphDB repository; nightly TriG export to git/S3 |
| Store / query / validate | rdflib + pySHACL in the venv | GraphDB Free (Desktop on the Mac, same server distribution on a VM later); Workbench for SPARQL + visual graph |
| Explore | `data/generated/viz.html` (vis-network page from `tools/viz.py`) | GraphDB Workbench visual graph, or this page |

Turtle rule learnt the hard way: `/` is not allowed inside a prefixed local
name, so scheme prefixes are `rock:`, `disc:`, `gsys:` … and ids are written
as full IRIs. rdflib tolerates the slash; GraphDB will not.

## Run

```bash
PY=agent/.venv/bin/python                      # rdflib 7.6 + pyshacl 0.40 already installed
$PY experimental/ontology/tools/vocab.py       # taxonomies.json -> vocab.ttl
$PY experimental/ontology/tools/json2rdf.py    # record + ingest runs -> data/generated/*.trig + report.json
$PY experimental/ontology/tools/run.py         # SHACL, 10 queries, injected-error test
$PY experimental/ontology/tools/run.py query q02
$PY experimental/ontology/tools/viz.py         # -> data/generated/viz.html (open in a browser)
```

Loading into GraphDB when installed: create a repository (ruleset: none),
Import → server files → every `data/generated/*.trig` and `data/curated/*.ttl`
(the latter into graph `https://climbing-agent.dev/graph/curated`), then import
`shapes.ttl` into the graph `http://rdf4j.org/schema/rdf4j#SHACLShapeGraph`
and `climb.ttl` + `vocab.ttl` as plain data. Validation then runs at commit.

## The model in one paragraph

`climb:Crag` is a **grouping header** (name, intro, guidebooks, external
refs). `climb:Place` is the **unit of curation** — the smallest physically
coherent piece of rock (a sector at Fair Head, the whole crag at Pigeon
Rock) — with its own *complete, independent* fact record: rock, aspect,
approach, parking, descent, tide, access, climate. **Nothing is inherited**
from crag to place (Michel, 2026-09-06). `climb:Route` sits on exactly one
Place and carries route facts only; SHACL rejects a route or crag header
carrying `aspect`, `approachTimeMin`, `parking` or `sunWindow`.
`climb:SourceRecord` is a crag/route **as one source describes it**; identity
between source records is `climb:candidateSameAs` with a confidence — a
statement, never a merge. Every fact lives in a **named graph** per source
run, attributed with PROV-O, so "who says what" is a one-line query.

## What was converted

| Graph | Triples | Content |
|---|---|---|
| `record` | 4,552 | Fair Head (163 routes → 19 places), Pigeon Rock (1), Vajolet Towers (1, with pitches + guidebooks) |
| `src/ukc/…635a` | 6,869 | UKC Fair Head, 460 routes |
| `src/ukc/…18f6`, `src/irishwiki/…18f6`, `src/thecrag/…f886` | 1,054 / 809 / 526 | Pigeon Rock from three sources |
| `enrich/…` ×3 | ~90 each | Open-Meteo normals + dry-warm months |
| `llm/…635a` | 237 | 40 LLM-tagged UKC routes with evidence spans |
| `link` | 705 | 117 candidate route identities, 1 crag cluster |
| `curated` | 80 | hand-written: Fair Head header, 2 parkings, 6 places |
| total | **16,690** | 13 graphs; load 0.8 s |

## Results against the five questions

**1. Can SHACL carry the governance?** Yes, completely. Every lint/Studio
rule restated once in `shapes.ttl`. The injected-error test plants 8 bad
facts (aspect on a route, aspect on the crag header, off-vocabulary
discipline, publish without human tags, stars = 5, French value under a
British system, tidal hazard without evidence) — all 8 fire with readable
messages. Cost: pySHACL takes **27 s** on 16k triples, which is too slow
for a save path. GraphDB validates incrementally at commit; that is the
production answer, not pySHACL.

**2. Can SPARQL answer a planner question with provenance?** Yes.
`q01`: trad E1–E3 on places with afternoon sun near Belfast → five routes on
The Prow, and the column `sunGraph` says the sun fact came from `curated`.
Every query runs in ≤ 1.2 s in rdflib.

**3. Per-source provenance vs the record's empty `provenance: []`.** This is
where the graph earns its keep. `q02` for *The Fly* at Pigeon Rock:

| graph | grade | system | pitches |
|---|---|---|---|
| Irish wiki | E1 4a | BAS | – |
| theCrag | E1 5b | – | 3 |
| UKC | E2 5b | BAS | 3 |

Three sources, three grades, side by side, without anyone having merged
them. `q06` lists 30 such disagreements at Pigeon Rock — the exact
adjudication queue the LLM phase needs.

**4. Is Turtle editable by hand / by an LLM?** `data/curated/fair-head.ttl`
was written by hand: six places, two parkings, cited sources, blanks left
blank. It reads at least as well as the JSON; the prefix rule above is the
one trap. Git diffs of Turtle are line-oriented and readable.

**5. Scale.** 16.7k triples for ~800 routes ≈ 21 triples/route. The full
record + Mournes + Marche (~12k routes) ≈ 250k triples; the 100k-route
horizon ≈ 2M triples. Trivial for GraphDB, fine for rdflib-in-memory up to
a few hundred thousand.

## Findings about the *record*, surfaced by the conversion

These are real data problems the shape of the graph made visible:

- **`areas.json` has Fair Head twice**: id 20 (`kind: sector`, under
  Antrim) and id 257 (`kind: crag`, "Fair Head, NI", under Northern Ireland
  directly). Routes point at sector ids only.
- **Crag-level aspect `N` / rock `dolerite` have no place to go** on a
  19-place crag once inheritance is gone — they need per-place curation
  (6 of 19 done in `curated/fair-head.ttl`; 13 places have nothing).
- **A dev fixture is live in the record**: `fair-head/girona.json`
  (`status: publish`, source `dev-fixtures`, no sector) — and it is the
  *only* Fair Head route carrying approach time, sun window and elevation,
  so today the site's Fair Head "facts" come from a fixture.
- **Sector names include junk**: `"Login to join in | theCrag"` is a sector
  in `areas.json`.
- **UKC adapter**: two Font boulder grades (`f6A+`, `f6C+`) at Pigeon Rock
  are tagged `uk_adjectival_tech`; one route has the literal string
  `"None"` as its grade.
- **Irish wiki adapter loses the tech grade** on 35 of 56 routes (parses
  `E1 4a, 4b, 5b` as `E1 4a`; `VS` alone) — which is why 30 of the 38
  cross-source matches at Pigeon Rock "disagree" on grade.
- theCrag emits grades with **no system** (146 warnings) — resolvable via a
  regional `gradeContext`, which the record sets on only one area row.
- `pigeon-rock/ukc-routes.json` is a crawl dump, not a route, sitting in a
  route folder.

## Verdict, for now

The ontology is not big: one class file, one generated vocabulary, one
shapes file. What it buys that JSON Schema does not: per-fact provenance by
named graph, identity-as-statement across sources, vocabulary mappings to
OSM/OpenBeta/theCrag, and one rule file that is both the validator and the
documentation. What it costs: the Studio's write path would talk SPARQL
Update to a store instead of writing files, and the store is a server
(GraphDB) rather than a bucket. Next step is Michel's: install GraphDB
Desktop, load this folder, and see whether the Workbench is something you
open every week.
