# Blume Event Bus

**Specification v1.2** · `blume-events`

The common event fabric shared by all Blume municipal systems. This document is
normative: a system is BEB-conformant if it satisfies every MUST in this
specification and passes the conformance suite in `conformance/`.

### Changes in v1.2

- §14 added: `identity-gateway` becomes the tenant's OAuth 2.1 authorisation
  server and OpenID Provider. The OIDC `sub` and the bus `pid` are separate
  identifiers under separate keys, neither derivable from the other.
- Aggregates name a disjoint bucket rather than a start and an end, so a
  k-anonymity floor cannot be defeated by differencing. `aggregate` joins the
  common types. §5, §7.
- Common types are effectively immutable: they accept additive-optional changes
  only, and a narrowing need creates a new type rather than a coordinated major
  bump across every event that references the old one. §9.
- `identity.pseudonym-issued` is replaced by `identity.pseudonym-issuance-recorded`,
  an hourly `audit` aggregate. A per-issuance event left a timing channel even
  without the pseudonym. §6.

### Changes in v1.1

Substantive:

- `vision` carries no `subject_ref`, and uses a stream- and hour-scoped
  `track_ref` instead. §6.
- `traffic` and `telemetry` are anonymous domains. `transit-core` is the only
  subject-linked producer outside `identity-gateway`. §6, §13.
- Neither `audit` nor `analytical` may carry a pseudonym. A pseudonym is
  personal data. §7.
- `envelope`, `sealed` and `track_ref` join the common types. §5.
- Canonical JSON is RFC 8785, and enums are open with an explicit marker. §9.

Errata against v1.0:

- §4's example omitted `provenance`, which is now REQUIRED on every event, and
  located `observed_at` directly in `data` rather than in `provenance`.
- §5's `subject_ref` example used a domain that can no longer carry a pseudonym
  and a string that is not valid RFC 4648 base32.
- §11's catalog example named schema `2.1.0.json` under a type ending `.v1`. The
  schema major and the type major are the same number by construction; it should
  have read `1.2.0.json`.
- §13 described `signal-broker` as a subject-linked producer. It is not.

---

## 1. Scope

Five system families publish to and consume from the bus:

| Domain | Repository | Emits |
|---|---|---|
| `traffic` | `signal-broker` | Signal state, demand, incidents, plan changes |
| `telemetry` | `utility-telemetry` | Meter reads, substation load, pressure, outages |
| `transit` | `transit-core` | Vehicle positions, stop events, load estimates |
| `vision` | `mca-ingest` | Stream health, detections, classifications, retention |
| `identity` | `identity-gateway` | Pseudonym lifecycle, authentication, consent, erasure, OAuth and OIDC (§14) |

### Goals

- One envelope, one addressing scheme, one schema registry across all domains.
- Domain systems remain independently deployable and independently contracted.
- Cross-domain correlation of a natural person is **cryptographically prevented**
  by default, and possible only through an audited, purpose-bound resolution
  service.
- Site deployments survive WAN loss without data loss.

### Non-goals

- Request/response RPC. The bus carries facts, not commands. Command APIs are
  per-system and out of scope.
- A shared database. Systems own their state; the bus carries notifications of
  change.
- Sub-millisecond control loops. Signal timing safety loops stay local to the
  controller.

---

## 2. Transport

**NATS JetStream**, with a leaf-node-per-site topology.

Chosen over Kafka for operational weight (a site deployment is a single ~15 MB
binary, not a JVM and a coordination service) and over raw MQTT for the lack of
native persistence, replay, and subject-scoped authorisation. Field devices that
can only speak MQTT connect through the NATS MQTT gateway at the site node and
are mapped onto the subject taxonomy in §3.

```mermaid
flowchart LR
  subgraph SITE["Site — municipal cabinet / depot"]
    DEV["Field devices<br/>MQTT / Modbus / ONVIF"] --> LEAF["NATS leaf node<br/>local JetStream<br/>store-and-forward"]
  end
  subgraph REGION["Region"]
    RC["NATS cluster<br/>3 nodes"]
  end
  subgraph CORE["bus.blume.systems"]
    CC["Core cluster"]
    SR["schemas.blume.systems"]
    IG["id.blume.systems"]
  end
  LEAF -->|mTLS, resumable| RC
  RC -->|stream mirror| CC
  CC -.->|schema fetch| SR
  CC -.->|pseudonym resolve| IG
```

Site nodes MUST retain locally for at least 72 hours so that a WAN outage is a
delivery delay rather than a data loss event. Reconnection replays from the last
acknowledged sequence.

---

## 3. Subject taxonomy

```
beb.<env>.<tenant>.<domain>.<event-name>.<major>
```

| Token | Rule |
|---|---|
| `env` | `prod` \| `stage` \| `dev` |
| `tenant` | Deployment identifier, lowercase, 2–12 chars. One per contract. |
| `domain` | One of the five in §1 |
| `event-name` | `kebab-case`, past tense, no domain prefix |
| `major` | `v1`, `v2` — major schema version only |

```
beb.prod.mcr.traffic.signal-phase-changed.v1
beb.prod.mcr.vision.object-classified.v1
beb.prod.mcr.identity.pseudonym-epoch-rotated.v1
```

Consumers subscribe with wildcards: `beb.prod.mcr.traffic.>` for a whole domain,
`beb.prod.*.telemetry.outage-declared.v1` for one event across tenants where the
consumer holds multi-tenant authorisation.

One JetStream stream per `<env>.<tenant>.<domain>` triple. Streams MUST NOT span
tenants — tenant isolation is enforced at the account boundary, not by filtering.

---

## 4. Envelope

CloudEvents 1.0, JSON mode, with four Blume extension attributes. Publishers MUST
NOT define additional extensions without registry approval.

```json
{
  "specversion": "1.0",
  "id": "01K4ZQ9F2X8H3N7VBM0T6Y5RJD",
  "source": "//blume.systems/mcr/traffic/controller/A41-0271",
  "type": "systems.blume.traffic.signal-phase-changed.v1",
  "subject": "asset:signal:A41-0271",
  "time": "2026-09-07T14:02:11.417Z",
  "datacontenttype": "application/json",
  "dataschema": "https://schemas.blume.systems/traffic/signal-phase-changed/1.4.0.json",
  "blumetenant": "mcr",
  "blumeretention": "operational",
  "blumetrace": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
  "blumeseq": 88213,
  "data": {
    "intersection_id": "A41-0271",
    "approach": "NB",
    "phase_from": "green",
    "phase_to": "amber",
    "dwell_ms": 42000,
    "plan_id": "peak-am-v7",
    "actuated": true,
    "provenance": {
      "producer": "signal-broker/1.0.0",
      "node": "site-mcr-north-02",
      "observed_at": "2026-09-07T14:02:11.912Z"
    }
  }
}
```

| Attribute | Requirement |
|---|---|
| `id` | ULID. Monotonic within a source. The idempotency key. |
| `source` | `//blume.systems/<tenant>/<domain>/<asset-class>/<asset-id>` |
| `type` | `systems.blume.<domain>.<event-name>.<major>` — reverse-DNS, mirrors §3 |
| `time` | RFC 3339, UTC, millisecond precision. Time the fact occurred, not the time it was published. |
| `dataschema` | Absolute registry URI including full semver |
| `blumetenant` | Duplicates the subject token so the envelope is self-describing off-bus |
| `blumeretention` | Retention class, §7 |
| `blumetrace` | W3C `traceparent` |
| `blumeseq` | Per-source monotonic counter. Gaps indicate loss. |

Where publication time differs materially from occurrence time (store-and-forward
after a site outage), publishers MUST set `data.provenance.observed_at` to the
observation time and leave `time` as the occurrence time. `provenance` is
REQUIRED on every event in every domain, so the field is always available and
there is no second location for it.

---

## 5. Common types

Defined once in `schemas/common/`, referenced by `$ref` from every domain schema.
Domain schemas MUST NOT redefine these shapes. Eight files: `envelope`, `geo`,
`asset_ref`, `subject_ref`, `provenance`, `sealed`, `track_ref`, `aggregate`.

A domain schema MAY narrow a common type at its own reference site — restricting
`asset_ref.class` to `substation`, or adding `confidence` to the required set of
`provenance`. Under 2020-12 a sibling keyword applies to the same instance as
`$ref`, so this constrains without redefining.

Common value types are closed: `additionalProperties: false`, so a member
smuggled in beside a pseudonym fails validation rather than riding along. Event
data schemas are open, because closing them would make adding an optional field
break every consumer pinned to an older minor, and §9 promises the opposite.
`beb-lint` enforces both directions.

### `geo.json`

```json
{
  "lat": 53.6097,
  "lon": -2.1561,
  "accuracy_m": 4.5,
  "cell": "MCR-0742-19"
}
```

WGS84. `cell` is the municipal grid reference, coarse enough (≈250 m) to be
usable in analytical retention where exact coordinates are stripped.

### `asset_ref.json`

```json
{ "class": "signal", "id": "A41-0271", "tenant": "mcr" }
```

Asset classes are registered centrally: `signal`, `camera`, `meter`,
`substation`, `vehicle`, `stop`, `gateway`, `controller`.

### `subject_ref.json`

The only permitted way to reference a natural person. See §6.

```json
{ "pid": "sub:transit:e3:7F3QK2NDMXAWB4PY", "epoch": 3 }
```

Only `transit` and `identity` may carry one. `traffic` and `telemetry` are
anonymous domains and `vision` uses `track_ref`, so the domain token is
constrained to those two: a `sub:vision:` pseudonym fails at the schema layer as
well as in `beb-lint`. The `epoch` member MUST equal the epoch encoded in `pid`.
JSON Schema cannot express that equality, so the SDKs and `beb-lint` enforce it.

### `provenance.json`

```json
{
  "producer": "mca-ingest/2.11.3",
  "node": "site-mcr-north-02",
  "observed_at": "2026-09-07T14:02:11.912Z",
  "confidence": 0.94,
  "method": "onvif-analytics"
}
```

`provenance` is REQUIRED on every event in every domain.

`confidence` is REQUIRED on any event produced by inference rather than direct
measurement — every `vision` detection, every `transit` passenger estimate.
Consumers MUST NOT treat an inferred event as a measured one. The catalog's
`inferred` flag is the machine-readable form of this rule: `beb-lint` requires
that an event declaring `inferred: true` adds `confidence` to the required set of
`provenance` at its own reference site, and that one declaring `inferred: false`
does not.

### `sealed.json`

```json
{
  "alg": "AES-256-GCM",
  "key_id": "dk_01K4ZQ9F2X8H3N7VBM0T6Y5RJD",
  "epoch": 3,
  "ct": "<base64>",
  "iv": "<base64>"
}
```

A `data` field classified as subject-linked, encrypted at publish time under a
per-subject data key. A `$ref` to this type *is* the classification marker for a
field; there is no separate annotation to keep in sync.

`key_id` is opaque and carries no derivable relation to the subject. A sealed
blob travels wherever its event travels, so a pseudonym embedded in the key
handle would sit in cleartext beside the ciphertext it protects and defeat the
sealing. The gateway alone holds the mapping.

Additional authenticated data is the JCS serialisation of `{"blumetenant", "id",
"path", "type"}`, where `path` is the JSON Pointer of the sealed field within the
event. A blob lifted from one event and pasted into another fails authentication
rather than decrypting cleanly into the wrong context.

### `track_ref.json`

```json
{ "stream_id": "cam-mcr-0742-03", "track_id": "9f2c1a7be4d05836", "window": "2026-09-07T14Z" }
```

A visual track, scoped to exactly one stream and one wall-clock UTC hour. The
`vision` domain's substitute for a subject reference. `track_id` is a random
64-bit value which MUST NOT be reused, MUST NOT be shared between streams, and
MUST NOT cross the window boundary.

The window is wall-clock, not rolling. A person walking through 14:59:59 into
15:00:00 receives two unrelated tracks. That truncation is the bound, not a
defect: a rolling one-hour lifetime would track better and prove less, and any
analysis needing continuity across the seam is an analysis this system declines
to support.

Banned in `analytical` retention — an hour-scoped per-person handle in a 90-day
store reconstructs exactly what the scoping prevents. Permitted in `evidential`,
which `footage-sealed` requires.

### `aggregate.json`

```json
{ "aggregate_id": "cnt-MCR-0742-19-person", "window": "2026-09-07T14Z", "revision": 0 }
```

Carried by every `analytical` event and by the aggregate events in `audit`.

**The window is a bucket, not a pair of endpoints.** Two buckets denote either the
same period or disjoint periods; overlap is unrepresentable. This is what makes
the k-anonymity floor in §7 mean anything. A floor protects each published
figure and says nothing about the arithmetic between them: aggregates over
14:00–15:00 and 14:00–14:30, both comfortably above the floor, subtract to a
14:30–15:00 bucket that may contain one person. A schema that let a producer
choose its own endpoints would be a differencing oracle with a floor bolted on.

A corrected figure is republished with the same `aggregate_id` and a higher
`revision`; consumers take the highest revision seen. The earlier figure is not
withdrawn. Both remaining visible is the price of not reopening the same
differencing channel through revision history.

Buckets below the floor are suppressed entirely. A suppressed bucket and an empty
bucket MUST be indistinguishable, which means absence — never a zero, a null, or
a marker field. There is deliberately nowhere in this type to record that
suppression occurred.

Each aggregate schema declares its bucket duration:

```json
"x-beb-aggregate": { "window": "PT1H", "count_field": "count", "k_floor": 5 }
```

`beb-lint` checks that the named count field requires a minimum of at least the
floor, that the schema declares no endpoint pair, that it declares no suppression
marker, and that every example's bucket matches the declared duration.

### `envelope.json`

The §4 envelope as a schema, so that it is checkable rather than merely
described. Closed: publishers MUST NOT define additional extension attributes
without registry approval, so an unrecognised attribute is a validation failure.
The `data` member is validated separately against the schema named by
`dataschema`.

---

## 6. Subject pseudonymisation

**The root identifier for a natural person exists only inside
`identity-gateway`. No other system holds it, and no event on the bus carries
it.**

### Which domains carry pseudonyms

**A domain may carry `subject_ref` only where honouring the event requires
per-person state. Where an entitlement class suffices, the event MUST carry the
class and no subject reference.**

| Case | Per-person state? | Verdict |
|---|---|---|
| Boarding assistance | A registered needs profile must be looked up | Pseudonym |
| Fare cap, concessionary settlement | A sum over that person's journeys | Pseudonym |
| Accessible crossing request | Extend the green. Nothing to look up. | Class only |

Applied to the five domains:

| Domain | Carries | Why |
|---|---|---|
| `transit` | `subject_ref` | Fare caps and assistance profiles are per-person state |
| `identity` | `subject_ref` | It is the domain that issues them |
| `traffic` | nothing | A controller does not need to know who presented the fob to give them longer to cross |
| `telemetry` | nothing | Assets, not people |
| `vision` | `track_ref` | See below |

`transit-core` is therefore the only subject-linked producer outside
`identity-gateway`.

### Why `vision` carries no pseudonym

A pseudonym is only obtainable if the producer can ask the gateway *who is
this*, and it can only ask if it holds a persistent biometric template. That
template is `root_subject_id` under another name, accumulating in the one domain
this construction exists to keep it out of. The cryptography would then be
protecting the bus while the actual identifier sat on the node: a consumer
holding every stream still could not join `vision` to `transit`, and
`mca-ingest` would hold a face database of everyone who walked past a camera.

`vision` uses `track_ref` (§5) instead: one stream, one wall-clock hour, no
persistence beyond it.

Two consequences, chosen rather than overlooked:

- **Cross-camera journey times are not possible from `vision` alone.** Corridor
  travel time comes from `traffic` detectors and `transit` vehicle positions,
  which measure it directly under an ordinary basis.
- **`vision` cannot participate in `/v1/correlate` at all.** A court order
  reaches the evidential footage store under a legal basis — see
  `vision.footage-sealed` — not the bus and not the resolution endpoint.

Anyone arriving here wanting cross-camera analytics is reading a refusal, not an
oversight. The distinction to hold on to is `transit.assistance-requested`, which
does keep a pseudonym because staff must retrieve a profile to honour it. That is
what per-person state looks like; a longer green phase is not.

### Derivation

Every domain that carries pseudonyms receives a distinct pairwise one:

```
pid(domain, epoch, subject) =
    "sub:" ‖ domain ‖ ":e" ‖ epoch ‖ ":" ‖
    base32(HMAC-SHA256(K_domain_epoch, root_subject_id)[0..10])
    -- ten bytes, RFC 4648 base32, sixteen characters, no padding

K_domain_epoch = HKDF(K_tenant_root, info = domain ‖ epoch)
```

`K_tenant_root` is held in the tenant's KMS and is never exported. Domain keys
are derived at the gateway and never leave it.

The consequence is the important part: the pseudonym a person carries in
`traffic` and the pseudonym they carry in `vision` are unlinkable without
`K_tenant_root`. A consumer holding a full copy of every stream on the bus cannot
join them. This is a property of the construction, not a policy.

### Epoch rotation

`epoch` increments every 90 days per tenant. Pseudonyms from different epochs are
unlinkable by the same argument, which caps the window over which any single
domain can build a longitudinal profile. Rotation is announced on
`identity.pseudonym-epoch-rotated.v1`; systems MUST NOT attempt to bridge epochs
locally.

### Issuance is not announced per subject

The gateway publishes `identity.pseudonym-issuance-recorded.v1`: an hourly count
by domain and epoch, `audit` class, carrying no pseudonym and no issuance
identifier.

A per-issuance event would defeat the construction above even with the pseudonym
stripped. In a small tenant at low volume, two issuance events for different
domains seconds apart are one person with high probability. That is weaker than a
join, but this section makes unlinkability a property of the construction, and a
channel whose strength depends on how busy the council is would demote it to a
policy. Per-issuance audit stays in the gateway's own internal log, where it has
a reader. Nothing without a bus consumer belongs on the bus.

### Resolution

Cross-domain correlation is possible, deliberately, through one endpoint:

```
POST https://id.blume.systems/v1/correlate
```

It requires a purpose code, an expiry, two distinct authorised principals, and a
legal basis reference. It emits `identity.correlation-performed.v1` to the
`audit` retention class before returning a result. There is no configuration in
which it is silent, and there is no bulk mode.

### Erasure

Event logs are append-only, which makes deletion by rewrite impractical. BEB uses
crypto-shredding instead.

Any `data` field classified as subject-linked is encrypted at publish time with a
per-subject data key wrapped by `K_tenant_root` — a `$ref` to `sealed.json` is
that classification. On `identity.erasure-requested.v1`, the gateway destroys the
data key and emits `identity.erasure-completed.v1`. Ciphertext remains in the log
and is permanently unrecoverable. Systems MUST handle undecryptable payloads as a
normal condition, not an error.

Decoding a sealed field yields exactly three outcomes, and an SDK MUST
distinguish all three:

| Outcome | Meaning | Consumer |
|---|---|---|
| `Opened` | Key fetched, authentication passed | Proceed |
| `Shredded` | The gateway confirmed key destruction | Terminal. Drop the record. |
| `Unavailable` | Key could not be fetched, or the caller is not authorised | Transient. `nak` and retry. |

Collapsing `Shredded` into `Unavailable` makes an authorisation failure look like
an erasure, which is the shape of bug that silently deletes data.

### Where erasure records live

`audit` carries no personal data, pseudonyms included (§7), but proof that an
erasure was performed must outlive the record naming whom it was performed on.
The two requirements are met by splitting the pair, and the same split applies to
correlation:

| Event | Class | Carries |
|---|---|---|
| `correlation-performed` | `audit` | `correlation_id`, both domains, purpose code, both principals, legal basis, expiry. No pids. |
| `correlation-detail-recorded` | `evidential` | `correlation_id`, both pids, read logged |
| `erasure-requested` | `evidential` | `erasure_id`, `subject_ref` |
| `erasure-completed` | `evidential` | `erasure_id`, `subject_ref`, key destruction attestation |
| `erasure-attested` | `audit` | `erasure_id`, outcome, timestamp, principal. No subject reference. |

`evidential` retention is per tenant policy, so an erasure record can itself
expire. The `erasure_id` is the join between the two, and it resolves to a person
only for as long as the evidential record survives — which is the correct decay.

---

## 7. Retention classes

`blumeretention` selects the stream policy. Publishers MUST set it correctly;
CI rejects a schema whose examples use a class inconsistent with its field
classifications.

| Class | Duration | Contents |
|---|---|---|
| `operational` | 7 days | Live system state. May contain `subject_ref`. |
| `analytical` | 90 days | Aggregates and coarsened geo. `subject_ref` stripped, not pseudonymised further. |
| `evidential` | Per tenant policy | Encrypted, legal-hold capable, access logged per read. |
| `audit` | 7 years | Append-only, no personal data **including pseudonyms**, no erasure path. |

An event MUST carry exactly one class. Where a producer needs both an operational
and an analytical view, it emits two events, and the analytical one carries no
`subject_ref`.

A pseudonym is personal data: pseudonymisation is not anonymisation. `beb-lint`
MUST therefore fail any schema in the `audit` or `analytical` class that
transitively `$ref`s `subject_ref.json`, and any `analytical` schema that
transitively `$ref`s `track_ref.json`.

Two further structural rules follow from the same reasoning, both enforced by
`beb-lint` rather than by review:

- An `analytical` schema in `telemetry` MUST NOT admit an `asset_ref` of class
  `meter`. A 30-minute domestic read keyed by meter identifier is personal data
  whether or not it carries a pseudonym, so analytical aggregates key on `cell`.
- An `analytical` schema MUST reference `geo.json#/$defs/coarse` rather than the
  root or `#/$defs/precise`, so that exact coordinates are unrepresentable rather
  than merely stripped by convention.
- Every published aggregate figure MUST be over at least **k = 5** contributors,
  and every `analytical` event MUST carry `aggregate` (§5) so that its window is
  a disjoint bucket. A count of one in a cell and an hour describes a person.

---

## 8. Delivery semantics

- **At-least-once.** Consumers MUST be idempotent on `id`.
- **Ordering** is guaranteed per `source`, not globally. Consumers requiring
  order MUST partition by `source` and MUST NOT assume cross-source ordering.
- **Deduplication** — publishers set `Nats-Msg-Id` to `id`; the stream dedup
  window is 2 minutes.
- **Backpressure** — pull consumers only. Push consumers are prohibited; a slow
  consumer must not become a producer's problem.
- **Poison messages** — after 5 delivery attempts a message moves to
  `beb.<env>.<tenant>.dlq.<domain>` with the failure reason in headers. The DLQ
  is monitored, not ignored.

---

## 9. Schema registry and evolution

JSON Schema 2020-12, served from `schemas.blume.systems`, source of truth in
`blume-events/schemas/`. The registry is a static artifact built from the repo —
there is no runtime schema service to fail.

Within a major version, changes MUST be backward compatible:

- Adding an optional field is allowed.
- Adding an enum value is allowed **only** if consumers are specified to ignore
  unknown values. Every BEB enum carries that clause.
- Removing a field, narrowing a type, making an optional field required, or
  changing units is a **major** version and a new subject.

Schema semantic version major MUST equal the `major` token in `type` and in the
subject. §9's identity of "a major version" and "a new subject" holds only if
they are the same number, and `beb-lint` enforces the equality.

Every published version stays on disk under `schemas/<domain>/<event>/<semver>.json`
permanently. The registry is a static artifact built from the repo, so a
`dataschema` URI that resolved once resolves forever, and `beb-lint` has the
previous version to diff against without reaching into git history.

### Closed common types, open event schemas

`schemas/common/*.json` set `additionalProperties: false`. Event data schemas
deliberately do not. The asymmetry reads as an oversight to anyone meeting the
schemas cold, so the reasoning is recorded here.

Closing an event schema would make a consumer pinned to `1.0.0` reject a valid
`1.1.0` event that added an optional field — which contradicts the first rule in
this section outright. Opening `subject_ref.json` would let a raw identifier ride
along beside the pseudonym that replaced it, which is the hole §6 exists to
close. Closed where the value shape *is* the contract; open where evolution is
the contract. `beb-lint` enforces both directions, so neither can drift into the
other.

### Narrowing

A **reference site** may narrow a common type and may never widen one. An event
schema writing `properties: { class: { enum: ["substation"] } }` beside a `$ref`
to `asset_ref.json` narrows that type for that event alone; compatibility is
assessed against the previous version of that event, and no other event is
affected.

"Widen" is not decidable in general, so `beb-lint` enforces an allow-list: only
keywords that cannot widen may appear beside a `$ref` to a common type, and any
property named at a reference site MUST already exist in the type referenced. An
`allOf` that re-opens a closed type or adds a member to one is a build error
regardless of whether it is otherwise compatible.

**A common type itself may not narrow at all.** Narrowing `geo.json` is breaking
for every event that references it, which under this section means a major bump
and a new subject for all of them at once. A 41-event fan-out major is not a
migration any operator survives, and offering it as a supported path guarantees
someone attempts it. Common types therefore accept additive-optional changes
only.

A genuinely necessary narrowing creates a **new common type** — `geo2.json` —
and events migrate to it individually, each as an ordinary major bump of one
event, at their own pace. The cost is a permanent `geo.json` in the tree. The
benefit is that no change to a shared type can ever require a coordinated release
across every producing repository. This makes the common types close to immutable
in practice, which is the correct incentive: they are the part of this repository
that is expensive to get wrong.

### Open enums

An additive enum change is compatible only because consumers ignore unknown
values — which is a promise about consumers, not a property of the schema. A
consumer validating a `1.1.0` event against a pinned `1.0.0` schema would reject
the new value and the promise would be worthless.

So every `enum` in a BEB schema carries the marker `"x-beb-enum": "open"` and the
clause *Consumers MUST ignore unknown values* in its description. `beb-lint`
requires the marker on every enum. `beb-gen` emits an `Unknown` variant for every
open enum in both languages, and consumer-side validation in the SDKs relaxes the
`enum` constraint on them. The strict form is retained for producers, so a
misspelled value still fails a contract test.

The `Unknown` variant MUST retain the original string and re-emit it verbatim on
encode. A decoder that reads `"adaptive-fallback"` as `Unknown` and writes it
back out as `"unknown"` is not byte-identical, and §12's round-trip requirement
fails on it. `conformance/golden/unknown-enum-value.json` pins this.

### Canonical JSON

RFC 8785 (JCS): object keys sorted by UTF-16 code unit, no insignificant
whitespace, ECMAScript number serialisation. Both SDKs MUST agree byte for byte.

- `NaN`, `Infinity` and `-0` are rejected at validation, not at serialisation.
- An integer outside ±2^53 MUST be carried as a string. `blumeseq` is within
  range and stays a number.
- `confidence` is a double in [0,1]. It is not rounded to fixed precision: a
  lossy round-trip is worse than a long decimal.

`tools/beb-lint` enforces this in CI by diffing against the previous published
schema. A non-compatible change on the same major fails the build.

Both major versions run in parallel during migration. The publisher dual-writes;
the old subject is removed only once consumer lag on it reaches zero and stays
there for 14 days.

---

## 10. Security

- **Transport** — mTLS everywhere. Site nodes hold per-node certificates issued
  by the tenant CA, 90-day lifetime, automated renewal.
- **Authorisation** — NATS accounts per `<env>.<tenant>`. Within an account, each
  service holds a JWT with explicit publish and subscribe subject permissions.
  `signal-broker` can publish `beb.prod.mcr.traffic.>` and nothing else. A
  compromised traffic controller cannot forge a vision detection.
- **Cross-tenant** — no account trusts another. Multi-tenant consumers hold
  separate credentials per tenant and join outside the bus.
- **Key custody** — `K_tenant_root` lives in the tenant's KMS. Blume operates the
  software; the council holds the key. Erasure and correlation are therefore
  capabilities the tenant can revoke unilaterally.

---

## 11. Repository layout

```
blume-events/
├── catalog.yaml              # every registered event, one entry each
├── schemas/
│   ├── common/               # envelope, geo, asset_ref, subject_ref,
│   │                         #   provenance, sealed, track_ref, aggregate
│   ├── traffic/
│   ├── telemetry/
│   ├── transit/
│   ├── vision/
│   └── identity/
├── gen/
│   ├── go/                   # generated, committed, never hand-edited
│   └── rust/
├── conformance/
│   ├── golden/               # canonical events every SDK must round-trip
│   └── invalid/              # events every SDK must reject, with reasons
├── tools/
│   ├── beb-lint/             # schema compatibility gate
│   ├── beb-gen/              # codegen
│   └── beb-replay/           # replay a window into a local consumer
└── docs/
```

`catalog.yaml` is the human-readable index and the input to codegen. `beb-lint`
checks that every entry resolves to a schema on disk, that the majors agree, that
`subject_linked` matches the schema's transitive `$ref` graph rather than the
author's intent, that `retention` is consistent with that graph, and that
`inferred` matches whether `confidence` is required at the event's own
`provenance` reference site:

```yaml
- type: systems.blume.vision.object-classified.v1
  domain: vision
  schema: vision/object-classified/1.2.0.json
  retention: operational
  subject_linked: false
  inferred: true
  description: >
    A tracked object in a registered stream was assigned a class by
    on-node analytics. Inferred; carries confidence.
  producers: [mca-ingest]
```

### SDK surface

Go and Rust are first-class and generated from the same schemas. Rust:

```rust
use blume_events::{Bus, vision::ObjectClassified};

let bus = Bus::connect("nats://bus.blume.systems:4222")
    .tenant("mcr")
    .credentials(creds)
    .await?;

let mut sub = bus
    .subscribe::<ObjectClassified>("analytics-worker")
    .durable()
    .await?;

while let Some(msg) = sub.next().await {
    let ev = msg.event();
    if ev.data.confidence < 0.85 {
        msg.ack().await?;      // inferred and weak — drop, don't escalate
        continue;
    }
    handle(&ev).await?;
    msg.ack().await?;
}
```

The SDK MUST reject at compile time any attempt to place a raw identifier in a
`subject_ref` — the type is constructible only from a gateway-issued pseudonym.
Making the wrong thing impossible beats documenting that it is forbidden.

Concretely, `SubjectRef` has exactly two constructors: deserialisation of a value
matching the `sub:<domain>:e<n>:<base32>` grammar, and a test-only constructor
behind a build tag in Go and a feature flag in Rust. There is no
`SubjectRef::new(String)`. Note that the CloudEvents `subject` attribute is an
unrelated thing — it names an asset — and is never typed as a `SubjectRef`.

---

## 12. Testing

- **Conformance** — every SDK runs `conformance/golden/` end to end and MUST
  round-trip byte-identically after canonical JSON ordering. Every file in
  `conformance/invalid/` MUST be rejected with the stated error class.
- **Contract tests** — each producing repo pins a `blume-events` version and
  tests its emitted events against the schema in CI. A producer cannot merge an
  event that does not validate.
- **Compatibility** — `beb-lint` diffs every schema against the last published
  version on every PR.
- **Soak** — a site node is partitioned from the WAN for 4 hours under synthetic
  load; the test asserts zero loss and correct ordering on reconnect.
- **Privacy** — a test asserts that no golden event in any domain contains a
  field matching known root-identifier patterns, and that two pseudonyms for the
  same synthetic subject in different domains have no computable relation without
  the tenant key.

---

## 13. Implementation order

1. `blume-events` — common schemas, envelope, `beb-lint`, Go and Rust SDKs,
   conformance suite. Nothing else starts until the envelope is frozen.
2. `identity-gateway` — pseudonym derivation, epoch rotation, erasure. It is the
   dependency for every subject-linked event elsewhere.
3. `utility-telemetry` — highest event volume, no subject linkage. Proves the
   transport under load without privacy surface.
4. `transit-core` — the first and only subject-linked producer outside
   `identity-gateway`. `signal-broker` — anonymous throughout.
5. `mca-ingest` — last. Highest sensitivity, and it benefits from every lesson
   the other four produce.

---

## 14. Authorisation and identity federation

`identity-gateway` is the tenant's OAuth 2.1 authorisation server and OpenID
Provider, in addition to its role as pseudonym authority under §6. This puts an
HTTP API surface on the most security-critical component in the system.

§2's exclusion of RPC from the bus is unchanged. The gateway's OAuth and OIDC
endpoints are ordinary HTTPS and are not modelled as events. Only the *facts*
those endpoints produce reach the bus, per §14.7.

### 14.1 Relying parties

| Class | Examples | Client type |
|---|---|---|
| Resident-facing | Services portal, transit account, permit applications | Public, browser or native |
| Staff-facing | Traffic operations, depot management, vision review | Confidential, federated per §14.6 |
| Devices | Ticket machines, depot terminals, roadside tablets | Input-constrained, device grant |
| Service-to-service | The five domain systems calling gateway APIs | Confidential, mTLS-bound |

### 14.2 Standards

Implement OAuth 2.1 and the current BCPs, not OAuth 2.0 as commonly deployed.

**Required:**

- **OAuth 2.1** — authorization code with PKCE mandatory for every client,
  public and confidential.
- **RFC 7636** PKCE, `S256` only. `plain` is rejected.
- **RFC 9700** OAuth 2.0 Security Best Current Practice, treated as normative.
- **OpenID Connect Core 1.0**, with **pairwise** subject identifiers (§14.3).
- **OpenID Connect Discovery 1.0** — `/.well-known/openid-configuration`.
- **RFC 9126** Pushed Authorization Requests — required for all confidential
  clients.
- **RFC 9449** DPoP — required for all public clients.
- **RFC 8705** mTLS client authentication and certificate-bound tokens —
  required for service-to-service, reusing the tenant CA from §10.
- **RFC 8628** Device Authorization Grant — ticket machines and depot terminals.
- **RFC 7009** revocation. **RFC 7662** introspection, restricted to
  confidential clients.
- **OpenID Connect Back-Channel Logout 1.0**.
- Refresh token rotation with reuse detection. A replayed refresh token revokes
  the entire grant chain.

**Prohibited.** The implicit grant and ROPC MUST return `unsupported_grant_type`.
Also prohibited: bearer tokens without sender constraint, `none` client
authentication for anything but a public client using both PKCE and DPoP,
unsigned or `alg: none` ID tokens, and wildcard redirect URIs.

### 14.3 The `sub` claim and the bus pid

OIDC requires `sub` to be stable for a given subject and client. §6 requires
domain pseudonyms to rotate every 90 days. One identifier cannot do both:
collapsing them either breaks every relying party's account mapping quarterly or
abandons epoch rotation.

**Two identifiers, two keys, neither derivable from the other.**

```
sub  = base32(HMAC-SHA256(K_oidc_sector, root_subject_id)[0..15])
       K_oidc_sector = HKDF(K_tenant_root, info = "oidc" ‖ sector_id)
       No epoch. Stable for the life of the client relationship.

pid  = base32(HMAC-SHA256(K_domain_epoch, root_subject_id)[0..10])
       K_domain_epoch = HKDF(K_tenant_root, info = domain ‖ epoch)
       Rotates per §6.
```

Consequences, all normative:

- A relying party holding `sub` cannot compute the bus `pid` for the same
  person. A bus consumer holding `pid` cannot compute `sub`. Both directions
  require `K_tenant_root`, which means both require `/v1/correlate` and its
  audit trail.
- `sector_identifier_uri` groups clients. Clients in one sector share a `sub`;
  clients in different sectors do not. **Sector assignment MUST follow domain
  boundaries** — a transit relying party and a vision relying party are never in
  one sector.
- **Tokens MUST NOT carry a bus pid.** Not in the ID token, not in the access
  token, not in an introspection response, not in a userinfo response. No lint
  rule can see inside a token, so this is a MUST with a test in the gateway's own
  suite rather than a schema constraint.
- `sub` is long-lived and therefore a **stronger** identifier than any pid. It
  MUST remain confined to the OIDC surface and MUST NOT reach the bus.

### 14.4 Claims and scopes

Standard OIDC scopes (`openid`, `profile`, `email`, `offline_access`) plus a
Blume set. The subject-linkage test from §6 applies unchanged: **claims carry
entitlement classes, not identity, wherever a class suffices.**

| Scope | Claims | Constraint |
|---|---|---|
| `blume.entitlements` | `entitlement_classes: [...]` | Classes only. Never the basis for an entitlement, never a document reference, never a condition. |
| `blume.assistance` | `assistance_profile_ref` | An opaque handle resolvable only by transit assistance services. Never the profile itself. |
| `blume.council` | `council_roles: [...]` | Staff only, federated per §14.6. |

The pressure on `entitlement_classes` will be to include *why* someone
qualifies. A disability, a benefit status and an age band are all special
category or adjacent, and none of them are needed to open a gate or extend a
green phase. The claim says `concessionary-travel`, and that is all it says.

### 14.5 Consent

An OIDC scope grant is the same fact as `identity.consent-granted.v1`. It MUST
NOT be modelled twice: the consent screen writes through to the same consent
record and emits the same event.

Consent MUST be per-sector, and revocable per-sector from a resident-facing
management surface. Revocation triggers back-channel logout to every client in
that sector and revokes the grant chain.

### 14.6 Staff federation

Councils operate their own staff identity, typically Microsoft Entra ID. The
gateway MUST support upstream OIDC federation for staff principals while
residents authenticate locally.

- Staff subjects are federated, and the gateway does **not** mint pseudonyms for
  them. A staff member is an accountable named principal — which is the entire
  point of the two-principal requirement on `/v1/correlate`.
- Resident subjects are local and pseudonymous.
- The two populations MUST NOT share a client, a sector, or a token audience. A
  token that could be either is a token that defeats the audit trail.
- Federated staff claims map to `council_roles`. The mapping is per-tenant
  configuration, not code.

### 14.7 Events

The rule from §6 applies here in a second form: **no event may carry both a
subject reference and a client or sector reference.** A pseudonymous resident
plus the service they authenticated to is a link between a person and a domain,
inferred rather than computed, and it is the same defect as putting two pids on
one stream.

**`audit`, no subject reference:**

| Event | Carries |
|---|---|
| `oauth-client-registered.v1` | Client id, sector, grant types, principal |
| `oauth-client-updated.v1` | Client id, changed fields, principal |
| `oauth-client-revoked.v1` | Client id, reason, principal |
| `oauth-signing-key-rotated.v1` | `kid`, algorithm, effective time |
| `oauth-authentication-aggregated.v1` | Hourly, by client and outcome, k-floored and bucketed per §5 |

**`evidential`, subject-linked, no client identity:**

| Event | Carries |
|---|---|
| `oauth-grant-authorised.v1` | `subject_ref`, scopes, `service_class`, expiry |
| `oauth-grant-revoked.v1` | `subject_ref`, scopes, reason, whether resident-initiated |
| `oauth-refresh-reuse-detected.v1` | `subject_ref`, inferred with confidence, chain revocation outcome |

**`operational`:**

| Event | Carries |
|---|---|
| `oauth-session-terminated.v1` | `subject_ref`, reason, so relying parties can react to back-channel logout |

`service_class` is a coarse vocabulary, deliberately not the client id and
deliberately not the sector.

### 14.8 Testing

Beyond the bar in §12:

- **Certification** — the gateway MUST pass the OpenID Foundation Basic OP and
  Config OP profiles. The conformance suite runs in CI against a local instance,
  not as a manual gate.
- **`sub`/`pid` isolation** — a test asserting that no token emitted at any
  endpoint, in any grant flow, contains a string matching the
  `sub:<domain>:e<n>:` grammar anywhere in its claims.
- **Sector isolation** — a test asserting that two clients in different sectors
  receive different `sub` values for one synthetic subject, and that no function
  of the two recovers the root or either pid.
- **Refresh reuse** — a replayed refresh token revokes the whole chain and emits
  the event. Table-driven across every grant type.
- **Negative** — every prohibited item in §14.2 has a test asserting rejection.

---

<sub>Blume Event Bus specification · `blume-events` · Questions to the platform
team.</sub>
