# CLAUDE.md

Standing instructions for this repository. Read before starting work in any
session.

`docs/SPEC.md` is normative. This file governs *how you work on it*, including
when to decide something yourself and when to escalate.

---

## 1. Authority

You have authority to decide and proceed. Escalate rarely and with a
recommendation attached.

**Decide it yourself, record it, keep going** when the question has a defensible
technical answer — even if it means overruling something in the spec or in a
previous instruction. A wrong instruction faithfully implemented is worse than a
correction with reasoning attached.

**Escalate** only when one of these holds:

- The choice trades off two things that are both legitimate and the tradeoff is
  a matter of policy, not engineering.
- The correct answer permanently removes a capability someone might want. State
  the cost so it is chosen rather than discovered later.
- Two spec sections conflict and both readings are defensible.

Everything else is yours. "I need a wire format for X and the spec defines none"
is not an escalation; it is a decision with a `docs/DECISIONS.md` entry.

**When you do escalate**, lead with your recommendation and the reasoning, then
the alternative and its cost. Never present an open question with no position —
if you have thought about it enough to raise it, you have thought about it enough
to have a view.

## 2. Decision records

Every decision you make that is not already in the spec goes in
`docs/DECISIONS.md`, appended, never rewritten:

```
## D-014 — sealed.json key_id is an opaque handle
Date: 2026-09-07 · Milestone: M1 · Status: accepted

Context: §6 requires subject-linked fields sealed at publish time. No wire
format was defined.

Decision: <what>

Reasoning: <why, including what you rejected and why>

Cost: <what this makes impossible or harder>
```

`Cost` is not optional and is not "none". If you cannot name a cost you have not
finished thinking. When a decision is later overturned, append a new record
superseding it; leave the original in place.

## 3. Review passes

Run these against your own output before reporting a milestone complete, and
against any spec text before implementing it. They exist because each one has
already caught a real defect in this project.

### A. Identifier and linkage

For every identifier in a design, answer: what is its scope, what is its
lifetime, who can hold it, and **what travels beside it**.

The third question is the one that gets missed. A protected payload is worth
nothing if its key id, filename, log line, header, or error message contains the
thing it protects. *Real case: a proposed `sealed.json` used
`key_id: "sub:transit:e3:7F3Q...:dk7"` — the pseudonym in cleartext, riding
alongside the ciphertext that existed to hide it.*

Then: after removing an identifier from an event, **what channel remains**?
Timing, ordering, volume, and presence/absence all survive field deletion.
*Real case: stripping `subject_ref` from a per-issuance event left two events
seconds apart in a low-volume tenant correlatable by adjacency alone. The fix was
aggregation, not field removal.*

### B. Composition

Individual outputs can be safe while the set is not. Check what is derivable from
combinations, differences, and intersections — not just from each output alone.

*Real case: a k≥5 floor protects each published aggregate and does nothing about
subtracting a nested window from an enclosing one to reach a bucket of one.*

Also count **fan-out**: for any change, how many separately-versioned things must
move simultaneously? If the answer is more than one, it is not a supported
migration path and the design needs a different shape. *Real case: narrowing a
common type would require a synchronised major bump across 41 events; the
resolution was that common types never narrow, they get successors.*

### C. Collapsed states

Any branch that means "this did not work" — is it actually two or more branches
with different correct responses?

*Real case: `Sealed<T>` decoding to `Opened | Shredded` collapsed "the key was
destroyed by erasure" and "I could not fetch the key". The first should drop the
record, the second should retry. Collapsing them silently discards data on an
authorisation failure.*

Absence has the same problem: a suppressed value and an empty value must be
indistinguishable if suppression is meant to protect anything.

### D. Necessity

Two questions, asked of everything:

- **Who consumes this?** If nothing does, it should not exist. An event with no
  consumer is a data channel with no benefit, and it will be consumed eventually
  by something you did not design for.
- **Does a class suffice?** Where a category, entitlement, or type answers the
  operational need, carrying an identity instead is a capability bought for
  nothing. *Real case: an accessible-crossing request needs "an entitled fob was
  presented", not who presented it — the controller extends the green either way.*

### E. Spec integrity

When reading spec text before implementing it, look for:

- **Internal contradictions.** Two sections that cannot both be satisfied.
- **Undefined terms doing normative work.** "Canonical ordering", "personal
  data", "compatible" — if a MUST depends on a term the spec never defines, the
  MUST is unenforceable.
- **MUSTs that no test can catch.** Every MUST should map to a lint rule, a
  type-system constraint, or a test. If it maps to none of those, say so
  explicitly and propose the mechanism, or downgrade it to a SHOULD and be honest
  that it is a convention. *A MUST nothing enforces is a comment.*
- **Rules that are weaker than their stated goal.** If a section claims a
  property "of the construction, not a policy", check that it actually is. Any
  point where correctness depends on someone behaving well is a policy wearing a
  construction's clothes.
- **Legal terms used loosely.** "Anonymous", "personal data", "consent" have
  specific meanings. Pseudonymised data is personal data; treat it accordingly
  wherever a rule says otherwise.

### F. Artifacts

If you built something to verify your work — a harness, a fixture corpus, a
generator, a scratch script that caught real bugs — it is a deliverable, not
scaffolding. Commit it in the milestone that produced it.

The test: would reconstructing this from a summary produce something weaker?
Almost always yes, because the summary loses the cases you found by accident.

## 4. Milestone protocol

1. **Read** the relevant spec sections in full. Run pass E over them.
2. **Report** conflicts, undefined terms, and unenforceable MUSTs before writing
   code — with rulings where you have authority, escalations where you do not.
3. **Plan**, briefly, if the milestone contains a design decision the spec does
   not pin down.
4. **Build.** No stubs, no `TODO`, no `unimplemented!()`. If a milestone is too
   large to finish, stop and say so rather than committing placeholders.
5. **Run passes A–D** over what you built.
6. **Commit** per milestone, conventional messages, with `docs/DECISIONS.md`
   updated in the same commit.
7. **Report**: what exists, what you decided and why, what you escalate, what the
   next milestone's hard part is.

Every rule you add to `beb-lint` needs a passing and a failing table case. Every
violation class you find by hand becomes a fixture in
`tools/beb-lint/testdata/`.

## 5. Standing rules already ruled

Do not relitigate these without new information. They are in the spec; they are
repeated here because they are the ones most likely to be eroded by a convenient
local decision.

- **Generated code is generated.** `gen/` is never hand-edited. CI regenerates
  and fails on diff.
- **`SubjectRef` is not constructible from a string** outside deserialisation of
  a valid pseudonym and a test-only constructor. Enforce in the type system, not
  in documentation.
- **Common types are closed; event data schemas are open.** Closed where the
  value shape is the contract, open where evolution is the contract.
- **Common types never narrow.** Additive-optional only; a narrowing need creates
  a successor type.
- **No event carries both a subject reference and a domain, client, or sector
  reference.** That is a cross-domain link by inference.
- **`analytical` and `audit` classes never reference `subject_ref` or
  `track_ref`.** Pseudonyms are personal data.
- **Aggregates: k≥5, disjoint windows, suppression by absence.**
- **Pseudonyms only where honouring the event requires per-person state.**
  Otherwise an entitlement class.
- **Library code returns typed errors and does not panic.** No `unwrap()` outside
  tests, no `log.Fatal` outside `main`.
- **Unknown enum values are ignored by consumers**, and the generated `Unknown`
  variant retains and re-emits the original string verbatim.

## 6. Tone of reports

Report what you decided, not what you would like permission to decide. Flag
defects in instructions you were given — including ones I wrote — plainly and
without hedging. If you implemented something you believe is wrong because it was
ruled, say so in the same breath as reporting it done.

Do not pad reports with what went smoothly. The interesting content is
conflicts, decisions, costs, and what you are unsure about.