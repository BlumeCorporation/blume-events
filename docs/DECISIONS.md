# Decision records

Appended, never rewritten. When a decision is overturned, a new record
supersedes it and the original stays in place.

`docs/SPEC.md` is normative. This file records why it says what it says, and what
each choice cost.

D-001 to D-021 were backfilled on 2026-09-07 from M1 work that predates this
file. They record decisions as made, not as they would be written now.

---

## D-001 — Schema versions live in the path and are retained permanently
Date: 2026-09-07 · Milestone: M1 · Status: accepted

Context: §4 and §11 show schema paths carrying a full semantic version. §9 says
the registry is "a static artifact built from the repo" and `beb-lint` diffs
against "the last published version", but neither says where old versions live.

Decision: `schemas/<domain>/<event>/<semver>.json`, one file per published
version, all retained. `catalog.yaml` names the current one.

Reasoning: a `dataschema` URI that resolved once must resolve forever, or a
consumer pinned to an old minor cannot fetch the schema it validates against.
Keeping every version on disk also gives `beb-lint` its diff corpus without
reaching into git history, which would make the gate depend on repository
topology.

Cost: the tree grows monotonically and never sheds a version, including versions
nothing uses any more. Deleting one is a breaking change to an unknown set of
consumers, so in practice they are permanent.

## D-002 — Schema major MUST equal the type major token
Date: 2026-09-07 · Milestone: M1 · Status: accepted

Context: §11's catalog example paired `...object-classified.v1` with schema
`2.1.0.json`. §4's example was consistent the other way.

Decision: the majors are the same number, enforced as `beb-lint` R04. §11's
example was an erratum and now reads `1.2.0.json`.

Reasoning: §9 treats "a major version" and "a new subject" as the same event.
That identity only holds if the two numbers agree; otherwise "which major is
this" has two answers.

Cost: a schema cannot be restructured into a new major without also moving the
subject and dual-writing, even when no consumer would have noticed. That is the
intended friction, but it is friction.

## D-003 — Examples are complete envelopes, not bare payloads
Date: 2026-09-07 · Milestone: M1 · Status: accepted

Context: §7 requires CI to reject "a schema whose examples use a class
inconsistent with its field classifications". Retention class lives on the
envelope; a bare `data` payload has no class to check.

Decision: `examples/minimal.json` and `examples/full.json` are whole CloudEvents
envelopes. `beb-lint` validates the envelope against `envelope.json`, the `data`
member against the event's own schema, and cross-checks `type`, `dataschema` and
`blumeretention` against the catalog.

Reasoning: it is the only reading of §7 that is mechanically checkable, and it
makes the examples usable directly as conformance input in M5.

Cost: every example repeats twelve envelope attributes, so the examples are
verbose and a change to envelope structure touches 98 files.

## D-004 — `envelope.json` is added as a common type
Date: 2026-09-07 · Milestone: M1 · Status: accepted

Context: §5 lists four common types and the envelope is not among them, but §12
requires conformance checks that need a machine-readable envelope definition.

Decision: added, and closed (`additionalProperties: false`).

Reasoning: §4 says publishers MUST NOT define additional extension attributes
without registry approval. Closing the envelope turns that MUST into a validation
failure rather than a review comment.

Cost: adding a genuinely approved extension attribute requires a coordinated
change to a common type, which under D-018 is deliberately hard.

## D-005 — `sealed.json`: opaque key handle, envelope-bound AAD, three outcomes
Date: 2026-09-07 · Milestone: M1 · Status: accepted

Context: §6 requires subject-linked fields encrypted at publish time and says
consumers "MUST handle undecryptable payloads as a normal condition". No wire
format was defined.

Decision: a closed common type carrying `alg`, `key_id`, `epoch`, `ct`, `iv`.
`key_id` is opaque with no derivable relation to the subject. AAD is the JCS
serialisation of `{blumetenant, id, path, type}`. Decoding yields `Opened`,
`Shredded` or `Unavailable`.

Reasoning: a first draft used `key_id: "sub:transit:e3:...:dk7"`, which puts the
pseudonym in cleartext beside the ciphertext protecting it — a sealed blob
travels wherever its event travels. Binding AAD to the envelope rather than to a
path pointer means a blob lifted into another event fails authentication instead
of decrypting into the wrong context. Three outcomes rather than two because
`Shredded` (erased, drop the record) and `Unavailable` (cannot fetch the key,
retry) demand opposite responses; collapsing them makes an authorisation failure
look like an erasure and silently discards data.

Cost: consumers must handle a three-way branch on every sealed field, and
`Unavailable` means a sealed field can block progress on an otherwise valid
event.

## D-006 — `vision` carries no `subject_ref`; `track_ref` instead
Date: 2026-09-07 · Milestone: M1 · Status: accepted

Context: §6 builds pairwise pseudonyms and does not say which domains use them.

Decision: no pseudonym in `vision`. A `track_ref` scoped to one stream and one
wall-clock UTC hour, banned in `analytical` and permitted in `evidential`.
`beb-lint` R07 refuses any `subject_ref` under `schemas/vision/`.

Reasoning: a pseudonym is only obtainable if the producer can ask the gateway who
a person is, and it can only ask if it holds a persistent biometric template —
which is `root_subject_id` under another name, accumulating in the domain §6
exists to keep it out of. The cryptography would protect the bus while the real
identifier sat on the node. The window is wall-clock rather than rolling because
a rolling lifetime tracks better and proves less.

Cost: cross-camera journey times are impossible from `vision` alone, and `vision`
cannot participate in `/v1/correlate` at all. A court order reaches the evidential
footage store instead.

## D-007 — `transit` carries pseudonyms; `traffic` and `telemetry` do not
Date: 2026-09-07 · Milestone: M1 · Status: accepted

Context: §1 describes transit as emitting vehicle positions and load estimates,
all anonymous; §13 called both `signal-broker` and `transit-core` subject-linked.

Decision: a pseudonym only where honouring the event requires per-person state.
`transit` carries them on fare, entitlement, assistance and journey events and
nowhere else. `traffic` and `telemetry` are anonymous domains, enforced by R07.
`priority-request-received` carries `entitlement_class` and no subject.

Reasoning: boarding assistance requires retrieving a registered needs profile and
a fare cap requires summing that person's journeys — neither is expressible as a
class. Extending a green phase requires nothing to be looked up; recording who
crossed which road, for seven days, to lengthen a phase buys a surveillance
capability with no operational return.

Cost: no per-person traffic analytics of any kind, including ones that would be
legitimate. Priority-request abuse must be handled locally at the controller.

## D-008 — Neither `analytical` nor `audit` may reach a pseudonym
Date: 2026-09-07 · Milestone: M1 · Status: accepted

Context: §7 said `audit` holds "no personal data" while §6 routed
`correlation-performed` — inherently about two pseudonyms — to `audit`.

Decision: pseudonymised data is personal data. R08 fails any `analytical` or
`audit` schema whose `$ref` graph reaches `subject_ref.json`. Correlation and
erasure are each split: the `audit` half carries an id and no subject, the
`evidential` half carries the subject.

Reasoning: pseudonymisation is not anonymisation, and a seven-year append-only
store with no erasure path is the worst place to put a person. `erasure-attested`
exists because `evidential` retention is per-tenant policy, so the record naming
the subject can expire while proof the erasure happened must not.

Cost: two events where an author would write one, joined by an id that resolves
to a person only while the evidential half survives.

## D-009 — Common types closed, event data schemas open
Date: 2026-09-07 · Milestone: M1 · Status: accepted

Context: `additionalProperties` was unspecified everywhere.

Decision: `schemas/common/*.json` set `additionalProperties: false`. Event data
schemas do not. R15 and R16 enforce both directions.

Reasoning: closing an event schema makes a consumer pinned to `1.0.0` reject a
valid `1.1.0` event that added an optional field, contradicting §9. Opening
`subject_ref.json` lets a raw identifier ride alongside the pseudonym that
replaced it, contradicting §6. Closed where the value shape is the contract, open
where evolution is the contract.

Cost: an open event schema cannot reject an unexpected member, so a producer
emitting a stray field passes validation. Structural bans (R07 to R09) are
schema-level and do not catch a runtime payload that carries what its schema
never declared.

## D-010 — Open enums carry an explicit marker
Date: 2026-09-07 · Milestone: M1 · Status: accepted

Context: §9 permits additive enum changes "only if consumers are specified to
ignore unknown values" — a promise about consumers that a bare `enum` contradicts,
since a pinned validator rejects the new value.

Decision: every `enum` carries `"x-beb-enum": "open"` and the ignore clause in its
description. R17 requires the marker. `beb-gen` emits an `Unknown` variant that
retains the original string and re-emits it verbatim.

Reasoning: without the marker the compatibility promise is unenforceable and
untestable. Retaining the string matters because a decoder that renders
`"adaptive-fallback"` back out as `"unknown"` breaks §12's byte-identical
round-trip; `conformance/golden/unknown-enum-value.json` pins it.

Cost: a vendor keyword that JSON Schema tooling outside this repository ignores,
so an external validator applies the strict enum and rejects forward-compatible
events.

## D-011 — Canonical JSON is RFC 8785
Date: 2026-09-07 · Milestone: M1 · Status: accepted

Context: §12 requires byte-identical round-trip "after canonical JSON ordering"
and never defines the term.

Decision: RFC 8785 (JCS). No `NaN`, `Infinity` or `-0`, rejected at validation.
Integers outside ±2^53 are strings. `confidence` is not rounded.

Reasoning: an undefined term carrying a MUST is unenforceable, and two SDKs must
agree on number formatting or conformance fails on floating point rather than on
anything meaningful.

Cost: JCS number serialisation is a real implementation burden in both languages,
and the Go and Rust defaults do not match it.

## D-012 — `provenance` is required on every event
Date: 2026-09-07 · Milestone: M1 · Status: accepted

Context: §4 said store-and-forward publishers "MUST include `observed_at` in
`data`"; §5 already defined `observed_at` inside `provenance`.

Decision: `data.provenance.observed_at` is the only location, and `provenance` is
required everywhere (R11). §4's wording was an erratum.

Reasoning: two locations for one field means consumers check both or read the
wrong one. Requiring `provenance` universally means the field always exists.

Cost: every event pays three mandatory members, including events where the
producer and node are obvious from the source attribute.

## D-013 — The catalog gains an `inferred` flag
Date: 2026-09-07 · Milestone: M1 · Status: accepted

Context: §5 requires `confidence` on inferred events, with no machine-readable
statement of which events those are.

Decision: `inferred: true|false` per catalog entry. R12 requires it to agree with
whether `confidence` is in the required set at the event's own `provenance`
reference site.

Reasoning: §5's rule was unenforceable as written.

Cost: a field that can be set wrong. R12 catches disagreement with the schema but
cannot tell whether the event is genuinely inferred.

## D-014 — Aggregates name a bucket, not an endpoint pair
Date: 2026-09-07 · Milestone: M1 · Status: accepted

Context: a k-anonymity floor was adopted for aggregate counts.

Decision: common type `aggregate.json` carrying `aggregate_id`, a bucket
`window`, and a `revision`. Schemas declare `x-beb-aggregate` with a duration,
count field and floor. R19 and R20 enforce the shape, the floor, the absence of an
endpoint pair, and the absence of any suppression marker.

Reasoning: a floor protects each published figure and says nothing about the
arithmetic between them — 14:00–15:00 minus 14:00–14:30 is a bucket that may hold
one person. Author-chosen endpoints make that representable; a bucket does not.
Corrections republish under the same `aggregate_id` with a higher `revision`
rather than withdrawing, because withdrawal reopens the same channel through
revision history. Suppression is absence, because a marker distinguishes a
suppressed bucket from an empty one.

Cost: aggregates are locked to whole hours or whole days. An ad-hoc window is not
expressible, and a producer needing one must publish hourly buckets and let the
consumer sum them. Both figures of a correction stay visible, which will be
reported as a bug.

## D-015 — Structural rules apply only to the catalogued version
Date: 2026-09-07 · Milestone: M1 · Status: accepted

Context: publishing `signal-plan-activated/1.1.0.json` left `1.0.0.json` on disk,
and a rule fixture silently stopped firing because it targeted the superseded
file.

Decision: R01 and R02 (parse, resolve) apply to every version on disk. Every other
rule applies only to the version `catalog.yaml` names.

Reasoning: a published schema cannot be edited, so a rule tightened today would
otherwise retroactively fail a schema that was correct when it shipped, and the
only fix would be violating D-001.

Cost: a superseded version can hold a construct a current rule forbids, and
consumers pinned to it validate against it. The rules therefore describe the
current tree, not everything the registry serves.

## D-016 — `pseudonym-issued` becomes an hourly aggregate
Date: 2026-09-07 · Milestone: M1 · Status: accepted
Supersedes: the per-issuance event shipped in the first M1 commit.

Context: `pseudonym-issued` carried one pseudonym and the domain it was issued
for, published on the identity stream.

Decision: replaced by `pseudonym-issuance-recorded` — hourly count by domain and
epoch, `audit` class, no subject reference and no issuance identifier.

Reasoning: two issuance events for different domains, seconds apart in a
low-volume tenant, are one person with high probability. §6 claims unlinkability
as a property of the construction; a channel whose strength depends on how busy
the council is makes it a policy. Stripping the pseudonym alone would not have
closed it — timing survives field deletion. Per-issuance audit has no bus
consumer and stays in the gateway's internal log.

Cost: no bus consumer can observe individual issuance, so a system wanting to
react to a specific pseudonym being minted must ask the gateway directly.

## D-017 — Reference sites may narrow; common types never do
Date: 2026-09-07 · Milestone: M1 · Status: accepted

Context: how to assess compatibility when an event narrows a shared type at its
own reference site.

Decision: narrowing at a reference site is local and permitted, checked by R18
against an allow-list of keywords that cannot widen, with any named property
required to exist in the referenced type. A common type itself accepts
additive-optional changes only; a genuine narrowing creates a successor
(`geo2.json`) that events migrate to individually.

Reasoning: "widen" is not decidable in general, so an allow-list is the only
enforceable form. Narrowing a common type would be breaking for every event
referencing it, requiring a synchronised major bump across 41 — now 49 — events.
That is not a migration anyone survives, and offering it guarantees an attempt.

Cost: superseded common types stay in the tree permanently, and a shared-type
mistake is close to unfixable — it can only be succeeded, never corrected. This
is why the common types were worth more care than anything else in M1.

## D-018 — The authoring script is retained
Date: 2026-09-07 · Milestone: M1 · Status: accepted

Context: the 49 event schemas and their 98 examples were generated from a script
so that envelope, provenance and enum handling stayed consistent across them.

Decision: committed as `tools/schema-authoring/author.py`. The JSON is the source
of truth; the script is not run in CI and does not gate anything.

Reasoning: `docs/REVIEW.md` pass F — a generator that produced the corpus is a
deliverable.
Regenerating from a summary would lose the consistency it enforced.

Cost: two representations of the same corpus, and nothing detects divergence. A
hand-edited schema plus a later regeneration silently reverts the edit. Not
locking them together is deliberate: the alternative makes adding an event
require editing Python, which is worse for the five repositories that will do it.

## D-019 — No event carries both a subject reference and a domain reference
Date: 2026-09-07 · Milestone: M1 · Status: accepted
Supersedes: the `scope` arrays shipped on `erasure-requested` and
`consent-granted` in the first M1 commit.

Context: R24 originally covered client and sector references only. An audit found
two shipped schemas carrying an array of domain names beside a `subject_ref`.

Decision: the rule covers domain terms too. `erasure-requested` loses `scope` for
a boolean `erase_all_domains`; `consent-granted` loses `scope` and keeps
`purpose_code`. A field that `$ref`s `sealed.json` is exempt, because ciphertext
is not a reference. R25 additionally allows only one subject reference per event,
excepting `correlation-detail-recorded`.

Reasoning: `scope: ["transit", "identity"]` beside an identity pseudonym states
that this person exists in transit. That is a cross-domain link by inference,
which is the thing §6 exists to prevent, arrived at by a different route than a
computable join. Neither field had a bus consumer: crypto-shredding means domain
systems take no action on erasure.

Cost: a consumer cannot tell from the bus which domains an erasure covered or a
consent applied to. Residual and unenforceable: `purpose_code` and Blume scope
names can themselves be domain-shaped — `blume.assistance` implies transit — and
no lint rule can see that. Scopes are sealed for this reason; purpose codes are
not, because a consent record without a purpose is not evidence of anything.

## D-020 — No per-authentication event
Date: 2026-09-07 · Milestone: M1 · Status: accepted
Supersedes: `authentication-evaluated`, shipped in the first M1 commit.

Context: §14.7 introduced an hourly authentication aggregate keyed by client,
while `authentication-evaluated` already existed keyed by subject.

Decision: `authentication-evaluated` is removed. `authentication-aggregated`
absorbs it. The name drops the `oauth-` prefix the brief used, because it covers
federated staff authentication, which is OIDC upstream rather than OAuth issuance.

Reasoning: nothing consumed it — domain systems learn what they need from
`oauth-grant-authorised`, and gateway security monitoring reads its own log
faster than a bus round trip. Decisively, the two events are individually
compliant and jointly not: joined on timestamp, a subject-keyed event and a
client-keyed aggregate reconstruct the `(subject, client)` pair §14.7 forbids.
Authentication anomalies remain on the bus as `oauth-refresh-reuse-detected` and
`oauth-session-terminated`, which have consumers and actions attached.

Cost: no bus-visible record of an individual authentication, so a consumer
wanting per-login history must ask the gateway. Routine success is no longer
observable off-bus at all.

Residual, accepted: `oauth-grant-authorised` is precisely timestamped and
subject-linked, and `authentication-aggregated` is keyed by client. In a tenant
quiet enough that one client has the only non-suppressed bucket in an hour, the
pair narrows subject to client. This is far weaker than what it replaces — the
join is against an hourly bucket floored at five rather than a precise
per-authentication timestamp, and it yields a candidate set rather than a link —
and removing `client_id` from the aggregate would destroy its only purpose.

## D-021 — `service_class` is three values, and scopes are sealed
Date: 2026-09-07 · Milestone: M1 · Status: accepted

Context: `oauth-grant-authorised` must be useful for fraud and support without
carrying a client or sector reference.

Decision: `service_class` is `self-service` | `assisted` | `machine`. Granted
scopes are a `sealed` field. A class may not be used on a subject-linked event
until at least two sectors have clients in it.

Reasoning: the fraud- and support-relevant axis is whether a human intermediary
was involved, not which service was used — assisted grants are where social
engineering happens, and the resident tells support which service. A vocabulary
as fine as the sector would be the sector, and sectors follow domain boundaries.
An `unattended-device` class was rejected for exactly that: with D-022 in place,
ticket machines would be the only resident-facing device clients, so the value
would mean `transit`. Scopes are sealed because a scope name can be domain-shaped
and places the subject in a small, special-category-adjacent population.

Cost: `service_class` is nearly binary on subject-linked events, so it supports
little analysis. Reading which scopes were granted requires key access, and after
erasure that detail is gone permanently while the proof of the grant remains.

## D-022 — No device grant for resident subjects
Date: 2026-09-07 · Milestone: M1 · Status: accepted

Context: §14.1 lists ticket machines as device-grant clients, and whether the
device grant preserves §14.3's guarantees was raised as an open question.

Decision: the device grant is available to staff and service principals on
council-controlled hardware only. Resident subjects never use it.

Reasoning: the guarantee at risk is not key separation, which holds regardless,
but that the grant belongs to the person who approved it. An attacker starts a
device flow, obtains a `user_code`, and puts it on a council-branded sticker on
the machine; a resident approves it on their own authenticated phone and the
gateway issues a correct, correctly-pseudonymised token to the attacker. Short
code lifetimes and typed entry do nothing against a sticker refreshed on a
schedule. Meanwhile §6's test says a ticket machine needs a fare and a valid
entitlement, which are transit events, not a grant — and RFC 8628's premise is a
device where the user has no better option, while this user holds the phone the
flow requires.

Cost: no account self-service at a ticket machine, at all. Adding it later
requires proximity binding, which is a Blume extension to RFC 8628 with its own
design and review — not a configuration change.

## D-023 — `sub` is derived from a shreddable per-subject secret
Date: 2026-09-07 · Milestone: M1 · Status: accepted
Supersedes: the derivation from `root_subject_id` in the §14.3 brief.

Context: §6 erases by destroying keys. `sub` is a derivation, not a ciphertext,
so destroying a data key leaves a relying party's stored `sub` working.

Decision: `sub = base32(HMAC-SHA256(K_oidc_sector, S_subject)[0..15])` where
`S_subject` is 256 random bits generated at first registration and held wrapped by
`K_tenant_root`. Erasure destroys it. No revocation list is maintained.
Subject-bearing access tokens are capped at five minutes.

Reasoning: this makes `sub` erasable with the same primitive as everything else
rather than a second mechanism. It also closes a defect a revocation list would
not: a deterministic `sub` returns the same value when a person re-registers, so
an erased account reanimates in any relying party that kept its row. A revocation
list was rejected on its own terms as well — a set of erased `sub` values is a
permanent list of everyone who exercised their right to erasure, keyed by an
identifier derived from them. Once `S_subject` is destroyed nothing is needed:
a presented `sub` matches nothing and fails closed.

Cost: the `S_subject` store becomes as critical as the root subject store —
losing it breaks every relying party relationship irrecoverably. `sub` can no
longer be recomputed from the root identifier alone. And the gateway cannot
delete a relying party's row: it can only make it worthless and make deletion a
contractual, tested obligation.

## D-024 — Access tokens are RFC 9068 JWTs validated at the resource server
Date: 2026-09-07 · Milestone: M1 · Status: accepted

Context: §14.2 required introspection but never said whether access tokens are
JWTs validated locally or opaque handles requiring a gateway call. The choice
decides whether every API call costs a round trip.

Decision: JWTs in the RFC 9068 profile, validated at the resource server against
the JWKS. Introspection remains available to confidential clients that need
immediate revocation certainty and is not on the path of an ordinary call.

Reasoning: D-023 already capped subject-bearing access tokens at five minutes,
which is an implicit vote for local validation — under mandatory introspection
the cap would be redundant, because revocation would take effect on the next
call. The cap and local validation are the same decision and the spec should say
so. Opaque tokens were rejected on operational grounds: every domain API call
becoming a gateway dependency makes the gateway a hard availability dependency
for the whole system, which §2's leaf-node design exists to avoid on the bus.

Cost: a revoked or erased subject's access token keeps working for up to five
minutes. Revocation is not immediate, and any requirement for immediacy has to be
met by a resource server choosing to introspect, at its own latency cost.

## D-025 — Tokens are audience-restricted with RFC 8707
Date: 2026-09-07 · Milestone: M1 · Status: accepted

Context: §14 as folded in had no audience restriction. A token obtained for one
domain's API was acceptable at every other.

Decision: `resource` is REQUIRED on every authorization and token request, and
the issued token's `aud` names it.

Reasoning: this closes an inconsistency rather than adding a capability. §10
already promises subject-scoped authorisation on the bus, in the specific form
that a compromised traffic controller cannot forge a vision detection. The HTTP
surface carried no equivalent, so a compromised transit client held a token every
domain API would accept. A security property claimed in one section and absent in
another is worse than not claiming it.

Cost: every client must know which resource it is calling and request a token per
resource, so a client spanning two APIs holds two tokens and refreshes both.

## D-026 — No dynamic client registration
Date: 2026-09-07 · Milestone: M1 · Status: accepted

Context: RFC 7591 was neither required nor prohibited, and
`oauth-client-registered` carries a registering `principal`, implying
administrative registration without stating it.

Decision: prohibited. Registration is administrative.

Reasoning: §14.3 requires sector assignment to follow domain boundaries, and
which domain a client belongs to is a judgement about that client made by someone
else. A self-registering client asserting its own sector chooses which residents
it shares a `sub` with, which is the one thing sector assignment exists to
control. Silence read as "maybe", and someone would have enabled it.

Cost: onboarding a relying party is a human step with a lead time. There is no
self-service path for a council team standing up a new service.

## D-027 — Grant chains are capped at 90 days
Date: 2026-09-07 · Milestone: M1 · Status: accepted

Context: D-023 capped access tokens at five minutes and left refresh chains
unbounded.

Decision: refresh tokens rotate on every use with reuse detection, and the grant
chain has an absolute 90-day lifetime.

Reasoning: the erasure story held without this — a refresh after erasure fails
closed — but an unbounded chain is a long-lived credential sitting in a public
client on a resident's device, which is the thing refresh rotation is meant to
bound rather than extend indefinitely. 90 days coincides with the §6 epoch; the
alignment is mnemonic, not cryptographic, since `sub` does not rotate with the
epoch, and it should not be relied on as though it were.

Cost: a resident using a service less than once every 90 days re-authenticates
every time. For infrequent council services — a permit renewal, an annual pass —
that is most visits.

## D-028 — Grant lifecycle joins on `grant_id`, not `subject_ref`
Date: 2026-09-07 · Milestone: M1 · Status: accepted

Context: found while reviewing §14 against §6 rather than by a rule.
`oauth-grant-authorised` carries an identity pseudonym, pseudonyms rotate every
90 days, and a grant chain may span a rotation.

Decision: stated in §14.7 that grant lifecycle events join on `grant_id` and
never on `subject_ref` across an epoch boundary.

Reasoning: a grant authorised in epoch 3 and revoked in epoch 4 carries two
different `subject_ref` values for one person. That is correct — §6 forbids
bridging epochs locally, and it is the behaviour that makes epochs worth having —
but it is invisible until it produces gaps, and the first consumer to match
lifecycle on `subject_ref` will read those gaps as lost events rather than as the
design working. No lint rule can see this; it costs a sentence to prevent.

Cost: none beyond the documentation. Recorded because the absence of a cost here
is itself unusual, and because the finding came from a manual cross-section read
that no rule would have produced.

## D-029 — `CLAUDE.md` is not committed; review standards live in `docs/REVIEW.md`
Date: 2026-09-07 · Milestone: M1 · Status: accepted

Context: `CLAUDE.md` was committed in cfbb53c and D-018 cited it, which would
have left a committed decision record pointing at a file the repository does not
carry.

Decision: `CLAUDE.md` is gitignored and untracked. Its durable content — the
decision-record format, review passes A–F, and the standing rules — is extracted
into `docs/REVIEW.md` as ordinary engineering standards. D-018's reference is
repointed.

Reasoning: the review passes are repository governance and are worth having
regardless of who or what runs them; several encode defects this project has
already shipped and caught. Local tooling configuration is not repository
content. Untracking without extracting would have discarded the governance and
broken a reference in the same move.

Cost: two copies of the same material, one tracked and one not, with nothing
detecting divergence — the same failure mode recorded in D-018. `docs/REVIEW.md`
is the one that governs the repository.
