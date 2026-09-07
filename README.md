# blume-events

Shared event schemas and SDKs for the Blume municipal event bus. Five systems
depend on this repository: `signal-broker`, `utility-telemetry`, `transit-core`,
`mca-ingest` and `identity-gateway`. They pin a version of it and test their
emitted events against the schemas here in their own CI, so a change that lands
in this repository reaches all five.

**`SPEC.md` is normative. This README is not.** Where they disagree, the spec is
right and this file is stale — say so rather than following it. `REVIEW.md`
records how changes here are reviewed and the standing rules that are easiest to
erode by accident.

## Layout

| Path | What it holds |
|---|---|
| `catalog.yaml` | Every registered event, one entry each. The index, and the input to codegen. |
| `schemas/common/` | The eight shared types. Referenced by `$ref`, never redefined. |
| `schemas/<domain>/` | One directory per event, one file per published version, plus two examples. |
| `conformance/golden/` | Events every SDK must round-trip byte-identically. |
| `conformance/invalid/` | Events every SDK must reject, each annotated with its error class. |
| `tools/beb-lint/` | The schema gate. Run it before pushing. |
| `tools/schema-authoring/` | Bulk authoring aid for the corpus. Not a gate, not authoritative — see D-018. |

## Adding an event

1. Write `schemas/<domain>/<event-name>/1.0.0.json`. Reference the common types;
   do not restate their shapes.
2. Write `examples/minimal.json` and `examples/full.json`. Both are **complete
   envelopes**, not bare payloads — the retention class lives on the envelope and
   the lint rules check it there. The minimal one carries required members only;
   `beb-lint` verifies that dropping any of them breaks validation.
3. Add a `catalog.yaml` entry. `subject_linked` and `inferred` are checked
   against the schema, not taken on trust, so getting them wrong is a build error
   rather than a documentation defect.
4. Run `go run ./tools/beb-lint -root .` and `go test ./tools/beb-lint/`.

## Changing an event

Within a major version, adding an optional field or an enum value is allowed and
nothing else is. Publish the new version as a **new file** — `1.1.0.json` beside
`1.0.0.json` — and repoint `catalog.yaml`. Never edit a published version: the
registry is a static artifact built from this tree, and a `dataschema` URI that
resolved once must resolve forever. `beb-lint` still requires superseded versions
to parse and resolve; it does not apply newer structural rules to them.

Removing a field, narrowing a type, promoting an optional field to required, or
changing units is a major version, a new subject, and a dual-write migration. See
`SPEC.md` §9.

## Two conventions that look like mistakes

**Common types are closed; event data schemas are open.** `schemas/common/*.json`
set `additionalProperties: false`. The event schemas deliberately do not. This
asymmetry is not an oversight:

- Closing an event schema would make a consumer pinned to `1.0.0` reject a valid
  `1.1.0` event that added an optional field, which contradicts the compatibility
  promise the versioning scheme is built on.
- Opening `subject_ref.json` would let a raw identifier ride along beside the
  pseudonym that replaced it, which is the exact hole the pseudonymisation
  construction exists to close.

Closed where the value shape *is* the contract; open where evolution is the
contract. `beb-lint` enforces both directions, so neither can drift.

**Every `enum` carries `"x-beb-enum": "open"`.** An additive enum change is only
backward compatible because consumers ignore unknown values — a promise about
consumers that a bare `enum` keyword flatly contradicts, since a pinned validator
would reject the new value. The marker is the contract:

- `beb-gen` emits an `Unknown` variant for every open enum in Go and Rust.
- The `Unknown` variant **retains the original string and re-emits it verbatim**.
  A decoder that renders an unrecognised `"adaptive-fallback"` back out as
  `"unknown"` is not byte-identical, and `conformance/golden/unknown-enum-value.json`
  exists to catch exactly that.
- Consumer-side validation relaxes `enum` on marked sites. Producers keep the
  strict form, so a misspelling still fails a contract test.

## Running the gate

```
go run ./tools/beb-lint -root .    # check the tree
go test ./tools/beb-lint/          # the rules, each with a passing and a failing case
```

Every rule has a fixture in `tools/beb-lint/testdata/cases.yaml` that mutates the
real tree and names the rule that must fire. Adding a rule without adding its
failing case is how a rule silently stops working.

Structural rules run against the version `catalog.yaml` names. Superseded
versions must still parse and resolve — a `dataschema` URI that resolved once
resolves forever — but a rule tightened today does not retroactively fail a
schema that was correct when it shipped.
