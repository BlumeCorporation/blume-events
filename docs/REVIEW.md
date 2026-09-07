# Review standards

How work on this repository is checked before it lands. `docs/SPEC.md` is
normative about *what* the system is; this file is about *how* changes to it are
reviewed.

Five systems pin a version of this repository. A defect here reaches all of them,
and several of the defects that matter most are invisible to ordinary code
review — they are properties of a set of schemas rather than of any one schema.
The passes below exist because each has already caught a real defect in this
project. The examples are the actual cases, not illustrations.

---

## 1. Decision records

Every decision not already settled by the spec goes in the team's decision
record, appended, never rewritten. That record is kept outside this repository —
five repositories pin this one and none of them need our deliberation — and
anything that binds an implementer belongs in `docs/SPEC.md` instead:

```
## D-014 — Aggregates name a bucket, not an endpoint pair
Date: 2026-09-07 · Milestone: M1 · Status: accepted

Context: <what forced the decision>
Decision: <what>
Reasoning: <why, including what was rejected and why>
Cost: <what this makes impossible or harder>
```

`Cost` is not optional and is not "none". If you cannot name a cost you have not
finished thinking about it. When a decision is overturned, append a new record
that supersedes it and leave the original in place — the reasoning that turned
out to be wrong is the most useful part of the file.

## 2. Review passes

Run these before opening a change, and over any spec text before implementing it.

### A. Identifier and linkage

For every identifier in a design, answer: what is its scope, what is its
lifetime, who can hold it, and **what travels beside it**.

The last question is the one that gets missed. A protected payload is worth
nothing if its key id, filename, log line, header, or error message contains the
thing it protects. *A draft `sealed.json` used
`key_id: "sub:transit:e3:7F3Q...:dk7"` — the pseudonym in cleartext, riding
alongside the ciphertext that existed to hide it.*

Then: after removing an identifier from an event, **what channel remains?**
Timing, ordering, volume, and presence or absence all survive field deletion.
*Stripping `subject_ref` from a per-issuance event left two events seconds apart
in a low-volume tenant correlatable by adjacency alone. The fix was aggregation,
not field removal.*

### B. Composition

Individual outputs can be safe while the set is not. Check what is derivable from
combinations, differences, and intersections — not from each output alone.

*A k≥5 floor protects each published aggregate and does nothing about subtracting
a nested window from an enclosing one to reach a bucket of one. Separately, a
subject-keyed authentication event and a client-keyed aggregate were each
compliant, and joined on timestamp they reconstructed the pair both were written
to prevent.*

Also count **fan-out**: for any change, how many separately-versioned things must
move at once? If the answer is more than one it is not a supported migration path
and the design needs a different shape. *Narrowing a common type would require a
synchronised major bump across every event referencing it; the resolution was
that common types never narrow, they get successors.*

### C. Collapsed states

Any branch meaning "this did not work" — is it actually two or more branches with
different correct responses?

*`Sealed<T>` decoding to `Opened | Shredded` collapsed "the key was destroyed by
erasure" with "I could not fetch the key". The first should drop the record, the
second should retry. Collapsing them silently discards data on an authorisation
failure.*

Absence has the same problem: a suppressed value and an empty value must be
indistinguishable if suppression is meant to protect anything.

### D. Necessity

- **Who consumes this?** If nothing does, it should not exist. An event with no
  consumer is a data channel with no benefit, and something will eventually
  consume it in a way nobody designed for.
- **Does a class suffice?** Where a category, entitlement, or type answers the
  operational need, carrying an identity instead is a capability bought for
  nothing. *An accessible-crossing request needs "an entitled fob was presented",
  not who presented it — the controller extends the green either way.*

### E. Spec integrity

When reading spec text before implementing it, look for:

- **Internal contradictions.** Two sections that cannot both be satisfied.
- **Undefined terms doing normative work.** "Canonical ordering", "personal
  data", "compatible" — a MUST that depends on a term the spec never defines is
  unenforceable.
- **MUSTs no test can catch.** Every MUST should map to a lint rule, a
  type-system constraint, or a test. If it maps to none, say so explicitly and
  propose a mechanism, or downgrade it to a SHOULD and be honest that it is a
  convention. *A MUST nothing enforces is a comment.*
- **Rules weaker than their stated goal.** If a section claims a property "of the
  construction, not a policy", check that it is. Any point where correctness
  depends on someone behaving well is a policy wearing a construction's clothes.
- **Legal terms used loosely.** "Anonymous", "personal data" and "consent" have
  specific meanings. Pseudonymised data is personal data; treat it accordingly
  wherever a rule says otherwise.

### F. Artifacts

If you built something to verify your work — a harness, a fixture corpus, a
generator, a throwaway script that caught real bugs — it is a deliverable, not
scaffolding. Commit it with the change that produced it.

The test: would reconstructing this from a summary produce something weaker?
Almost always yes, because a summary loses the cases you found by accident.

## 3. Standing rules

Settled, and not to be relitigated without new information. They are all in
`docs/SPEC.md`; they are repeated here because they are the ones most easily
eroded by a convenient local decision.

- **Generated code is generated.** `gen/` is never hand-edited. CI regenerates
  and fails on any diff.
- **`SubjectRef` is not constructible from a string**, outside deserialisation of
  a valid pseudonym and a test-only constructor. Enforced in the type system, not
  in documentation.
- **Common types are closed; event data schemas are open.** Closed where the
  value shape is the contract, open where evolution is the contract.
- **Common types never narrow.** Additive-optional only; a narrowing need creates
  a successor type.
- **No event carries both a subject reference and a domain, client, or sector
  reference.** That is a cross-domain link by inference.
- **`analytical` and `audit` never reference `subject_ref` or `track_ref`.**
  Pseudonyms are personal data.
- **Aggregates: k≥5, disjoint windows, suppression by absence.**
- **Pseudonyms only where honouring the event requires per-person state.**
  Otherwise an entitlement class.
- **Library code returns typed errors and does not panic.** No `unwrap()` outside
  tests, no `log.Fatal` outside `main`.
- **Unknown enum values are ignored by consumers**, and the generated `Unknown`
  variant retains and re-emits the original string verbatim.

## 4. Change protocol

1. Read the relevant spec sections in full and run pass E over them.
2. Report contradictions, undefined terms and unenforceable MUSTs before writing
   code.
3. Build. No stubs, no `TODO`, no `unimplemented!()`. If the work is too large to
   finish, say so rather than committing placeholders.
4. Run passes A–D over what you built.
5. Commit, with the decision record updated at the same time.

Every rule added to `beb-lint` needs a passing and a failing table case. Every
violation class found by hand becomes a fixture in `tools/beb-lint/testdata/`.
