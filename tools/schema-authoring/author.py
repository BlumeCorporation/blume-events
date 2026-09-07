#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Bulk authoring aid for the M1 schema corpus.

Emits schemas/<domain>/<name>/<version>.json, both envelope examples, and
catalog.yaml, from the event definitions below. It exists so that envelope
shape, provenance handling and enum markers stay identical across 49 schemas.

STATUS, so nobody has to guess:

  - The committed JSON is the source of truth. Hand-editing a schema is the
    normal way to change one; see README.md.
  - This script is NOT run in CI and gates nothing. `beb-lint` is the gate.
  - Nothing detects divergence between this script and the tree. If you hand-edit
    a schema, either mirror the change here or delete this file. A stale
    generator that silently reverts an edit is worse than no generator.
  - Run with: REPO=. python3 tools/schema-authoring/author.py
  - It does NOT own schemas/common/ (hand-written) or superseded versions such
    as traffic/signal-plan-activated/1.0.0.json (retained per D-001). It
    reproduces every other file byte for byte.

It is retained because regenerating it from a description would lose the
consistency it enforces, not because it is authoritative.
"""
import hashlib, json, os, collections

OD = collections.OrderedDict
ROOT = os.environ.get("REPO", ".")
COMMON = "https://schemas.blume.systems/common/"
CROCK = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

# ---------------------------------------------------------------- primitives
def ulid(seed):
    n = int.from_bytes(hashlib.sha256(("ulid:" + seed).encode()).digest()[:16], "big")
    out = []
    for _ in range(26):
        out.append(CROCK[n & 31]); n >>= 5
    return "".join(reversed(out))

def trace(seed):
    h = hashlib.sha256(("tp:" + seed).encode()).hexdigest()
    return "00-%s-%s-01" % (h[:32], h[32:48])

TS_PAT = "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$"
ID_PAT = "^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"

def ts(desc):
    return OD([("type", "string"), ("pattern", TS_PAT), ("description", desc)])

def sid(desc, pat=ID_PAT):
    return OD([("type", "string"), ("pattern", pat), ("description", desc)])

def num(desc, **kw):
    d = OD([("type", "number")]); d.update(kw); d["description"] = desc; return d

def integer(desc, **kw):
    d = OD([("type", "integer")]); d.update(kw); d["description"] = desc; return d

def boolean(desc):
    return OD([("type", "boolean"), ("description", desc)])

def oe(values, desc):
    """Open enum. Section 9: additive enum changes are compatible only because
    consumers ignore unknown values, so every enum carries the marker and clause."""
    return OD([("type", "string"), ("enum", values), ("x-beb-enum", "open"),
               ("description", desc + " Consumers MUST ignore unknown values.")])

def arr(items, desc, **kw):
    d = OD([("type", "array"), ("items", items)]); d.update(kw)
    d["description"] = desc; return d

def ref(name, frag=""):
    return OD([("$ref", COMMON + name + ".json" + frag)])

def asset(classes, desc):
    """asset_ref narrowed to a class subset. The sibling `properties` applies to
    the same instance as `$ref` under 2020-12, which is how a schema states
    'this is a substation, not a meter' without redefining the common shape."""
    d = OD([("$ref", COMMON + "asset_ref.json")])
    if classes:
        d["properties"] = OD([("class", OD([("enum", classes), ("x-beb-enum", "open")]))])
    d["description"] = desc
    return d

def prov(desc, confidence=False):
    d = OD([("$ref", COMMON + "provenance.json")])
    if confidence:
        d["required"] = ["confidence"]
    d["description"] = desc
    return d

def sealed(desc):
    d = OD([("$ref", COMMON + "sealed.json")]); d["description"] = desc; return d

def subject(desc):
    d = OD([("$ref", COMMON + "subject_ref.json")]); d["description"] = desc; return d

def track(desc):
    d = OD([("$ref", COMMON + "track_ref.json")]); d["description"] = desc; return d
def agg(desc):
    d = OD([("$ref", COMMON + "aggregate.json")]); d["description"] = desc; return d

def xagg(count_field, window="PT1H", k=5):
    return OD([("window", window), ("count_field", count_field), ("k_floor", k)])

# ---------------------------------------------------------------- event model
EVENTS = []

def E(domain, name, retention, subject_linked, inferred, description, producers,
      props, required, src_class, src_id, ce_subject, minimal, full, xagg=None):
    EVENTS.append(OD([
        ("xagg", xagg),
        ("domain", domain), ("name", name), ("retention", retention),
        ("subject_linked", subject_linked), ("inferred", inferred),
        ("description", description.strip()), ("producers", producers),
        ("props", props), ("required", required),
        ("src_class", src_class), ("src_id", src_id), ("ce_subject", ce_subject),
        ("minimal", minimal), ("full", full),
    ]))

CELL = ref("geo", "#/$defs/cell_id")
APPROACH = lambda: oe(["NB", "SB", "EB", "WB", "NE", "NW", "SE", "SW"],
                      "Cardinal approach to the intersection.")
SEVERITY = lambda: oe(["low", "medium", "high", "critical"], "Operational severity.")
UTILITY = lambda: oe(["electricity", "gas", "water", "heat"], "Utility network.")
PROV = lambda: prov("How the fact was produced. Required on every event.")
PROV_INF = lambda: prov("How the fact was inferred. `confidence` is required: this event is "
                        "produced by inference, and consumers MUST NOT treat it as measured.", True)

# ============================================================ traffic (7)
# Anonymous domain. `beb-lint` bans any transitive $ref to subject_ref.json under
# schemas/traffic/.

E("traffic", "signal-phase-changed", "operational", False, False,
  "A signal group at an intersection transitioned between phases. Emitted by the "
  "controller on every transition, including transitions the plan did not schedule.",
  ["signal-broker"],
  OD([
    ("asset_ref", asset(["signal", "controller"], "The signal or controller that changed phase.")),
    ("intersection_id", sid("Intersection the signal group belongs to.")),
    ("approach", APPROACH()),
    ("phase_from", oe(["green", "amber", "red", "red-amber", "flashing-amber", "dark"], "Phase before the transition.")),
    ("phase_to", oe(["green", "amber", "red", "red-amber", "flashing-amber", "dark"], "Phase after the transition.")),
    ("dwell_ms", integer("Time held in `phase_from` before the transition, milliseconds.", minimum=0)),
    ("plan_id", sid("Timing plan in force. Absent when the controller is running fallback.")),
    ("actuated", boolean("True if the transition was demand-actuated rather than fixed-time.")),
    ("provenance", PROV()),
  ]),
  ["asset_ref", "intersection_id", "approach", "phase_from", "phase_to", "dwell_ms", "actuated", "provenance"],
  "controller", "A41-0271", "asset:signal:A41-0271",
  {"asset_ref": {"class": "signal", "id": "A41-0271", "tenant": "xmpl"},
   "intersection_id": "A41-0271", "approach": "NB", "phase_from": "green", "phase_to": "amber",
   "dwell_ms": 42000, "actuated": True,
   "provenance": {"producer": "signal-broker/1.0.0", "node": "site-xmpl-north-02",
                  "observed_at": "2026-09-07T14:02:11.417Z"}},
  {"asset_ref": {"class": "signal", "id": "A41-0271", "tenant": "xmpl"},
   "intersection_id": "A41-0271", "approach": "NB", "phase_from": "green", "phase_to": "amber",
   "dwell_ms": 42000, "plan_id": "peak-am-v7", "actuated": True,
   "provenance": {"producer": "signal-broker/1.0.0", "node": "site-xmpl-north-02",
                  "observed_at": "2026-09-07T14:02:11.912Z", "method": "controller-poll"}})

E("traffic", "detector-demand-reported", "operational", False, False,
  "A loop or radar detector reported demand on an approach over a sampling window. "
  "Measured, not inferred: the detector reports occupancy directly.",
  ["signal-broker"],
  OD([
    ("asset_ref", asset(["controller", "signal"], "Controller owning the detector.")),
    ("detector_id", sid("Detector identifier, unique within the controller.")),
    ("approach", APPROACH()),
    ("occupancy_pct", num("Fraction of the window the detector was occupied, percent.", minimum=0, maximum=100)),
    ("volume_vph", integer("Flow across the detector, vehicles per hour, extrapolated from the window.", minimum=0)),
    ("window_s", integer("Sampling window length, seconds.", minimum=1)),
    ("provenance", PROV()),
  ]),
  ["asset_ref", "detector_id", "approach", "occupancy_pct", "window_s", "provenance"],
  "controller", "A41-0271", "asset:controller:A41-0271",
  {"asset_ref": {"class": "controller", "id": "A41-0271", "tenant": "xmpl"},
   "detector_id": "D-NB-2", "approach": "NB", "occupancy_pct": 31.4, "window_s": 60,
   "provenance": {"producer": "signal-broker/1.0.0", "node": "site-xmpl-north-02",
                  "observed_at": "2026-09-07T14:03:00.000Z"}},
  {"asset_ref": {"class": "controller", "id": "A41-0271", "tenant": "xmpl"},
   "detector_id": "D-NB-2", "approach": "NB", "occupancy_pct": 31.4, "volume_vph": 742,
   "window_s": 60,
   "provenance": {"producer": "signal-broker/1.0.0", "node": "site-xmpl-north-02",
                  "observed_at": "2026-09-07T14:03:00.114Z", "method": "loop-count"}})

E("traffic", "signal-plan-activated", "operational", False, False,
  "A controller began running a different timing plan. Covers scheduled changes, "
  "operator overrides, adaptive selection, and falls back.",
  ["signal-broker"],
  OD([
    ("asset_ref", asset(["controller"], "Controller whose plan changed.")),
    ("plan_id", sid("Timing plan now in force.")),
    ("previous_plan_id", sid("Plan that was in force. Absent on cold start.")),
    ("reason", oe(["scheduled", "operator", "adaptive", "fallback", "recovery"],
                  "Why the plan changed.")),
    ("effective_at", ts("When the new plan took effect.")),
    ("provenance", PROV()),
  ]),
  ["asset_ref", "plan_id", "reason", "effective_at", "provenance"],
  "controller", "A41-0271", "asset:controller:A41-0271",
  {"asset_ref": {"class": "controller", "id": "A41-0271", "tenant": "xmpl"},
   "plan_id": "peak-am-v7", "reason": "scheduled", "effective_at": "2026-09-07T07:00:00.000Z",
   "provenance": {"producer": "signal-broker/1.0.0", "node": "site-xmpl-north-02",
                  "observed_at": "2026-09-07T07:00:00.031Z"}},
  {"asset_ref": {"class": "controller", "id": "A41-0271", "tenant": "xmpl"},
   "plan_id": "peak-am-v7", "previous_plan_id": "offpeak-v3", "reason": "scheduled",
   "effective_at": "2026-09-07T07:00:00.000Z",
   "provenance": {"producer": "signal-broker/1.0.0", "node": "site-xmpl-north-02",
                  "observed_at": "2026-09-07T07:00:00.031Z", "method": "scheduler"}})

E("traffic", "incident-declared", "operational", False, False,
  "An incident affecting the carriageway was declared. Declared by an operator or "
  "by an automated source; `reported_by` distinguishes them and analytics-sourced "
  "declarations carry confidence in provenance.",
  ["signal-broker"],
  OD([
    ("incident_id", sid("Incident identifier, stable across declare and clear.")),
    ("kind", oe(["collision", "breakdown", "obstruction", "flooding", "signal-fault",
                 "roadworks", "protest", "spillage"], "What kind of incident.")),
    ("severity", SEVERITY()),
    ("geo", ref("geo", "#/$defs/precise")),
    ("asset_ref", asset(["signal", "controller"], "Nearest signalled asset, where one applies.")),
    ("lanes_blocked", integer("Number of lanes blocked.", minimum=0)),
    ("reported_by", oe(["operator", "detector", "public", "partner-agency", "analytics"],
                       "Source of the declaration.")),
    ("declared_at", ts("When the incident was declared.")),
    ("provenance", PROV()),
  ]),
  ["incident_id", "kind", "severity", "geo", "reported_by", "declared_at", "provenance"],
  "controller", "A41-0271", None,
  {"incident_id": "INC-2026-09-07-0114", "kind": "collision", "severity": "high",
   "geo": {"lat": 53.6097, "lon": -2.1561}, "reported_by": "operator",
   "declared_at": "2026-09-07T14:05:02.000Z",
   "provenance": {"producer": "signal-broker/1.0.0", "node": "core-xmpl-01",
                  "observed_at": "2026-09-07T14:05:02.480Z"}},
  {"incident_id": "INC-2026-09-07-0114", "kind": "collision", "severity": "high",
   "geo": {"lat": 53.6097, "lon": -2.1561, "accuracy_m": 4.5, "cell": "XMPL-0742-19"},
   "asset_ref": {"class": "signal", "id": "A41-0271", "tenant": "xmpl"},
   "lanes_blocked": 2, "reported_by": "operator", "declared_at": "2026-09-07T14:05:02.000Z",
   "provenance": {"producer": "signal-broker/1.0.0", "node": "core-xmpl-01",
                  "observed_at": "2026-09-07T14:05:02.480Z", "method": "operator-console"}})

E("traffic", "incident-cleared", "operational", False, False,
  "A previously declared incident was cleared. Terminal for the `incident_id`.",
  ["signal-broker"],
  OD([
    ("incident_id", sid("Incident being cleared. Matches a prior incident-declared.")),
    ("cleared_at", ts("When the incident was cleared.")),
    ("duration_s", integer("Seconds between declaration and clearance.", minimum=0)),
    ("resolution", oe(["resolved", "referred", "false-positive", "superseded"],
                      "How the incident ended.")),
    ("provenance", PROV()),
  ]),
  ["incident_id", "cleared_at", "resolution", "provenance"],
  "controller", "A41-0271", None,
  {"incident_id": "INC-2026-09-07-0114", "cleared_at": "2026-09-07T15:11:40.000Z",
   "resolution": "resolved",
   "provenance": {"producer": "signal-broker/1.0.0", "node": "core-xmpl-01",
                  "observed_at": "2026-09-07T15:11:40.220Z"}},
  {"incident_id": "INC-2026-09-07-0114", "cleared_at": "2026-09-07T15:11:40.000Z",
   "duration_s": 3998, "resolution": "resolved",
   "provenance": {"producer": "signal-broker/1.0.0", "node": "core-xmpl-01",
                  "observed_at": "2026-09-07T15:11:40.220Z", "method": "operator-console"}})

E("traffic", "controller-fault-raised", "operational", False, False,
  "A controller self-reported a fault. Raised once per fault occurrence; a "
  "persisting fault is not re-raised until it clears and recurs.",
  ["signal-broker"],
  OD([
    ("asset_ref", asset(["controller"], "Faulting controller.")),
    ("fault_code", sid("Vendor fault code.")),
    ("fault_class", oe(["lamp", "detector", "comms", "cabinet", "config", "power", "timing"],
                       "Normalised fault category.")),
    ("severity", SEVERITY()),
    ("first_seen_at", ts("When the fault was first observed.")),
    ("detail", OD([("type", "string"), ("maxLength", 512),
                   ("description", "Vendor fault text, unparsed.")])),
    ("provenance", PROV()),
  ]),
  ["asset_ref", "fault_code", "fault_class", "severity", "first_seen_at", "provenance"],
  "controller", "A41-0271", "asset:controller:A41-0271",
  {"asset_ref": {"class": "controller", "id": "A41-0271", "tenant": "xmpl"},
   "fault_code": "F-217", "fault_class": "lamp", "severity": "medium",
   "first_seen_at": "2026-09-07T09:41:03.000Z",
   "provenance": {"producer": "signal-broker/1.0.0", "node": "site-xmpl-north-02",
                  "observed_at": "2026-09-07T09:41:03.660Z"}},
  {"asset_ref": {"class": "controller", "id": "A41-0271", "tenant": "xmpl"},
   "fault_code": "F-217", "fault_class": "lamp", "severity": "medium",
   "first_seen_at": "2026-09-07T09:41:03.000Z",
   "detail": "NB green aspect 2 drawing 0.0A, expected 0.6A",
   "provenance": {"producer": "signal-broker/1.0.0", "node": "site-xmpl-north-02",
                  "observed_at": "2026-09-07T09:41:03.660Z", "method": "controller-poll"}})

E("traffic", "priority-request-received", "operational", False, False,
  "A priority request was presented at a signalled crossing or junction. Carries "
  "the entitlement class and no subject reference: honouring the request means "
  "extending a green, which needs no per-person state. Recording who crossed which "
  "road when, for seven days, in order to lengthen a phase would buy a surveillance "
  "capability with no operational return. Where abuse must be controlled, the "
  "controller rate-limits on local presence and emits nothing.",
  ["signal-broker"],
  OD([
    ("asset_ref", asset(["signal", "controller"], "Crossing or junction the request was presented at.")),
    ("entitlement_class", oe(["extended-crossing", "transit-priority", "emergency-preemption"],
                             "Class of entitlement presented. Not an identity.")),
    ("request_id", sid("Per-request random identifier, used only to pair a request with its grant. "
                       "Not stable across requests and not derivable from the presenter.")),
    ("granted", boolean("Whether the controller honoured the request.")),
    ("extension_ms", integer("Additional green time granted, milliseconds. Zero when not granted.", minimum=0)),
    ("requested_at", ts("When the request was presented.")),
    ("provenance", PROV()),
  ]),
  ["asset_ref", "entitlement_class", "granted", "requested_at", "provenance"],
  "controller", "A41-0271", "asset:signal:A41-0271",
  {"asset_ref": {"class": "signal", "id": "A41-0271", "tenant": "xmpl"},
   "entitlement_class": "extended-crossing", "granted": True,
   "requested_at": "2026-09-07T14:01:58.000Z",
   "provenance": {"producer": "signal-broker/1.0.0", "node": "site-xmpl-north-02",
                  "observed_at": "2026-09-07T14:01:58.090Z"}},
  {"asset_ref": {"class": "signal", "id": "A41-0271", "tenant": "xmpl"},
   "entitlement_class": "extended-crossing", "request_id": "rq-8f2c1a7b",
   "granted": True, "extension_ms": 7000, "requested_at": "2026-09-07T14:01:58.000Z",
   "provenance": {"producer": "signal-broker/1.0.0", "node": "site-xmpl-north-02",
                  "observed_at": "2026-09-07T14:01:58.090Z", "method": "fob-presence"}})

# ============================================================ telemetry (7)
# Anonymous domain. `beb-lint` bans subject_ref under schemas/telemetry/, and bans
# an asset_ref of class `meter` in any analytical schema in this domain: a
# 30-minute domestic read keyed by meter id is personal data whether or not it
# carries a pseudonym, so analytical aggregates key on `cell` structurally.

E("telemetry", "meter-read-recorded", "operational", False, False,
  "A revenue or interval meter reported a register read. Measured. Domestic reads "
  "at interval granularity are personal data even without a subject reference, "
  "which is why they never reach analytical retention in this form.",
  ["utility-telemetry"],
  OD([
    ("asset_ref", asset(["meter"], "Meter that produced the read.")),
    ("utility", UTILITY()),
    ("register", sid("Register within the meter, e.g. \"import\", \"export\", \"rate-1\".")),
    ("reading", num("Cumulative register value in `unit`.", minimum=0)),
    ("unit", oe(["kWh", "m3", "MJ", "L"], "Unit of `reading`.")),
    ("interval_s", integer("Nominal interval between reads, seconds.", minimum=1)),
    ("quality", oe(["measured", "estimated", "substituted", "suspect"],
                   "Read quality as reported by the head-end.")),
    ("provenance", PROV()),
  ]),
  ["asset_ref", "utility", "reading", "unit", "interval_s", "quality", "provenance"],
  "meter", "M-88213-4", "asset:meter:M-88213-4",
  {"asset_ref": {"class": "meter", "id": "M-88213-4", "tenant": "xmpl"},
   "utility": "electricity", "reading": 148203.412, "unit": "kWh", "interval_s": 1800,
   "quality": "measured",
   "provenance": {"producer": "utility-telemetry/1.0.0", "node": "site-xmpl-east-01",
                  "observed_at": "2026-09-07T14:00:00.000Z"}},
  {"asset_ref": {"class": "meter", "id": "M-88213-4", "tenant": "xmpl"},
   "utility": "electricity", "register": "import", "reading": 148203.412, "unit": "kWh",
   "interval_s": 1800, "quality": "measured",
   "provenance": {"producer": "utility-telemetry/1.0.0", "node": "site-xmpl-east-01",
                  "observed_at": "2026-09-07T14:00:00.412Z", "method": "dlms-pull"}})

E("telemetry", "substation-load-sampled", "operational", False, False,
  "A distribution substation reported an electrical load sample.",
  ["utility-telemetry"],
  OD([
    ("asset_ref", asset(["substation"], "Substation sampled.")),
    ("phase", oe(["a", "b", "c", "aggregate"], "Phase the sample applies to.")),
    ("load_kw", num("Real power, kilowatts. Negative indicates export.")),
    ("voltage_v", num("Line voltage, volts.", minimum=0)),
    ("current_a", num("Line current, amperes.", minimum=0)),
    ("power_factor", num("Power factor in [-1,1].", minimum=-1, maximum=1)),
    ("frequency_hz", num("Supply frequency, hertz.", minimum=0)),
    ("provenance", PROV()),
  ]),
  ["asset_ref", "phase", "load_kw", "provenance"],
  "substation", "SS-XMPL-0742", "asset:substation:SS-XMPL-0742",
  {"asset_ref": {"class": "substation", "id": "SS-XMPL-0742", "tenant": "xmpl"},
   "phase": "aggregate", "load_kw": 412.75,
   "provenance": {"producer": "utility-telemetry/1.0.0", "node": "site-xmpl-east-01",
                  "observed_at": "2026-09-07T14:00:05.000Z"}},
  {"asset_ref": {"class": "substation", "id": "SS-XMPL-0742", "tenant": "xmpl"},
   "phase": "aggregate", "load_kw": 412.75, "voltage_v": 232.1, "current_a": 598.4,
   "power_factor": 0.97, "frequency_hz": 49.98,
   "provenance": {"producer": "utility-telemetry/1.0.0", "node": "site-xmpl-east-01",
                  "observed_at": "2026-09-07T14:00:05.118Z", "method": "modbus-poll"}})

E("telemetry", "pressure-sampled", "operational", False, False,
  "A water or gas network sensor reported a pressure sample.",
  ["utility-telemetry"],
  OD([
    ("asset_ref", asset(["meter", "gateway"], "Sensor or gateway that produced the sample.")),
    ("network", oe(["water", "gas"], "Network sampled.")),
    ("pressure_kpa", num("Gauge pressure, kilopascals.", minimum=0)),
    ("flow_lps", num("Flow at the sensor, litres per second.")),
    ("temperature_c", num("Fluid temperature, degrees Celsius.")),
    ("geo", ref("geo", "#/$defs/precise")),
    ("provenance", PROV()),
  ]),
  ["asset_ref", "network", "pressure_kpa", "provenance"],
  "gateway", "GW-XMPL-E-14", "asset:gateway:GW-XMPL-E-14",
  {"asset_ref": {"class": "gateway", "id": "GW-XMPL-E-14", "tenant": "xmpl"},
   "network": "water", "pressure_kpa": 341.2,
   "provenance": {"producer": "utility-telemetry/1.0.0", "node": "site-xmpl-east-01",
                  "observed_at": "2026-09-07T14:00:10.000Z"}},
  {"asset_ref": {"class": "gateway", "id": "GW-XMPL-E-14", "tenant": "xmpl"},
   "network": "water", "pressure_kpa": 341.2, "flow_lps": 12.44, "temperature_c": 11.3,
   "geo": {"lat": 53.6104, "lon": -2.1588, "accuracy_m": 8.0, "cell": "XMPL-0742-19"},
   "provenance": {"producer": "utility-telemetry/1.0.0", "node": "site-xmpl-east-01",
                  "observed_at": "2026-09-07T14:00:10.077Z", "method": "modbus-poll"}})

E("telemetry", "outage-declared", "operational", False, False,
  "A supply outage was declared on a utility network. Affected extent is reported "
  "as grid cells, never as meter identifiers.",
  ["utility-telemetry"],
  OD([
    ("outage_id", sid("Outage identifier, stable across declare and restore.")),
    ("utility", UTILITY()),
    ("cause", oe(["fault", "planned", "third-party", "weather", "overload", "unknown"],
                 "Cause as understood at declaration time.")),
    ("asset_ref", asset(["substation"], "Substation or feeder at the head of the outage.")),
    ("affected_cells", arr(CELL, "Grid cells losing supply.", minItems=1)),
    ("estimated_customers", integer("Estimated customer connections affected.", minimum=0)),
    ("started_at", ts("When supply was lost.")),
    ("provenance", PROV()),
  ]),
  ["outage_id", "utility", "cause", "started_at", "provenance"],
  "substation", "SS-XMPL-0742", None,
  {"outage_id": "OUT-2026-09-07-0031", "utility": "electricity", "cause": "fault",
   "started_at": "2026-09-07T13:58:44.000Z",
   "provenance": {"producer": "utility-telemetry/1.0.0", "node": "core-xmpl-01",
                  "observed_at": "2026-09-07T13:58:47.000Z"}},
  {"outage_id": "OUT-2026-09-07-0031", "utility": "electricity", "cause": "fault",
   "asset_ref": {"class": "substation", "id": "SS-XMPL-0742", "tenant": "xmpl"},
   "affected_cells": ["XMPL-0742-19", "XMPL-0742-20", "XMPL-0743-01"],
   "estimated_customers": 1840, "started_at": "2026-09-07T13:58:44.000Z",
   "provenance": {"producer": "utility-telemetry/1.0.0", "node": "core-xmpl-01",
                  "observed_at": "2026-09-07T13:58:47.212Z", "method": "scada-alarm"}})

E("telemetry", "outage-restored", "operational", False, False,
  "Supply was restored for a previously declared outage. Terminal for the `outage_id`.",
  ["utility-telemetry"],
  OD([
    ("outage_id", sid("Outage being restored. Matches a prior outage-declared.")),
    ("restored_at", ts("When supply was restored.")),
    ("duration_s", integer("Seconds of lost supply.", minimum=0)),
    ("affected_customers", integer("Confirmed customer connections affected.", minimum=0)),
    ("method", oe(["auto-reclose", "switching", "repair", "external", "unknown"],
                  "How supply was restored.")),
    ("provenance", PROV()),
  ]),
  ["outage_id", "restored_at", "provenance"],
  "substation", "SS-XMPL-0742", None,
  {"outage_id": "OUT-2026-09-07-0031", "restored_at": "2026-09-07T15:22:09.000Z",
   "provenance": {"producer": "utility-telemetry/1.0.0", "node": "core-xmpl-01",
                  "observed_at": "2026-09-07T15:22:09.400Z"}},
  {"outage_id": "OUT-2026-09-07-0031", "restored_at": "2026-09-07T15:22:09.000Z",
   "duration_s": 5005, "affected_customers": 1793, "method": "switching",
   "provenance": {"producer": "utility-telemetry/1.0.0", "node": "core-xmpl-01",
                  "observed_at": "2026-09-07T15:22:09.400Z", "method": "scada-alarm"}})

E("telemetry", "meter-tamper-suspected", "evidential", False, True,
  "On-node analysis suspects interference with a meter. Inferred, so it carries "
  "confidence and MUST NOT be treated as a finding of fact. Evidential retention: "
  "it may become the basis of a prosecution and is read-logged.",
  ["utility-telemetry"],
  OD([
    ("asset_ref", asset(["meter"], "Meter under suspicion.")),
    ("indicators", arr(oe(["magnetic-field", "reverse-flow", "seal-broken",
                           "consumption-anomaly", "comms-spoof", "clock-drift"],
                          "Individual tamper indicator."),
                       "Indicators that fired.", minItems=1)),
    ("score", num("Composite tamper score in [0,1]. Distinct from provenance confidence, "
                  "which describes the reliability of the inference itself.", minimum=0, maximum=1)),
    ("first_seen_at", ts("When the indicators first fired.")),
    ("provenance", PROV_INF()),
  ]),
  ["asset_ref", "indicators", "provenance"],
  "meter", "M-88213-4", "asset:meter:M-88213-4",
  {"asset_ref": {"class": "meter", "id": "M-88213-4", "tenant": "xmpl"},
   "indicators": ["reverse-flow"],
   "provenance": {"producer": "utility-telemetry/1.0.0", "node": "site-xmpl-east-01",
                  "observed_at": "2026-09-07T14:12:00.000Z", "confidence": 0.71}},
  {"asset_ref": {"class": "meter", "id": "M-88213-4", "tenant": "xmpl"},
   "indicators": ["reverse-flow", "consumption-anomaly"], "score": 0.83,
   "first_seen_at": "2026-09-05T02:14:00.000Z",
   "provenance": {"producer": "utility-telemetry/1.0.0", "node": "site-xmpl-east-01",
                  "observed_at": "2026-09-07T14:12:00.336Z", "confidence": 0.71,
                  "method": "load-profile-analysis"}})

E("telemetry", "consumption-aggregated", "analytical", False, False,
  "Total consumption over a grid cell and a period. The analytical counterpart to "
  "meter-read-recorded, per the rule that a producer needing both views emits two "
  "events. Keys on `cell`, never on a meter: an aggregate over a handful of meters "
  "is a household read wearing a hat, which is why `meter_count` has a floor.",
  ["utility-telemetry"],
  OD([
    ("geo", ref("geo", "#/$defs/coarse")),
    ("utility", UTILITY()),
    ("asset_ref", asset(["substation"], "Feeding substation. Class is narrowed to exclude "
                        "`meter`: a meter identifier in a 90-day store re-identifies a household.")),
    ("aggregate", agg("Bucket, identity and revision of this figure.")),
    ("total", num("Total consumption over the period in `unit`.", minimum=0)),
    ("unit", oe(["kWh", "m3", "MJ", "L"], "Unit of `total`.")),
    ("meter_count", integer("Meters contributing to the aggregate. Floored at 5 so that a "
                            "single premises cannot be isolated from the aggregate.", minimum=5)),
    ("provenance", PROV()),
  ]),
  ["geo", "utility", "aggregate", "total", "unit", "meter_count", "provenance"],
  "substation", "SS-XMPL-0742", None,
  {"geo": {"cell": "XMPL-0742-19"}, "utility": "electricity",
   "aggregate": {"aggregate_id": "cons-XMPL-0742-19-elec", "window": "2026-09-07T13Z", "revision": 0},
   "total": 918.4, "unit": "kWh", "meter_count": 214,
   "provenance": {"producer": "utility-telemetry/1.0.0", "node": "core-xmpl-01",
                  "observed_at": "2026-09-07T14:01:00.000Z"}},
  {"geo": {"cell": "XMPL-0742-19"}, "utility": "electricity",
   "asset_ref": {"class": "substation", "id": "SS-XMPL-0742", "tenant": "xmpl"},
   "aggregate": {"aggregate_id": "cons-XMPL-0742-19-elec", "window": "2026-09-07T13Z", "revision": 1},
   "total": 918.4, "unit": "kWh", "meter_count": 214,
   "provenance": {"producer": "utility-telemetry/1.0.0", "node": "core-xmpl-01",
                  "observed_at": "2026-09-07T14:01:00.905Z", "method": "batch-rollup"}},
  xagg=xagg("meter_count"))

import base64
def pid(domain, epoch, seed):
    """A gateway-issued pairwise pseudonym for examples. Ten bytes of HMAC output
    base32-encode to exactly sixteen characters with no padding."""
    h = hashlib.sha256(("pid:%s:%d:%s" % (domain, epoch, seed)).encode()).digest()[:10]
    return "sub:%s:e%d:%s" % (domain, epoch, base64.b32encode(h).decode())

STOP = lambda desc: asset(["stop"], desc)

# ============================================================ transit (11)
# The only subject-linked producer outside identity-gateway, and only where
# honouring the event requires per-person state.

E("transit", "vehicle-position-reported", "operational", False, False,
  "A vehicle reported its position on a trip. Vehicle-scoped and anonymous: "
  "nothing about honouring this event requires knowing who is aboard.",
  ["transit-core"],
  OD([
    ("asset_ref", asset(["vehicle"], "Reporting vehicle.")),
    ("route_id", sid("Route the vehicle is working.")),
    ("trip_id", sid("Scheduled trip the vehicle is working.")),
    ("geo", ref("geo", "#/$defs/precise")),
    ("bearing_deg", num("Heading, degrees clockwise from true north.", minimum=0, maximum=360)),
    ("speed_kph", num("Ground speed, kilometres per hour.", minimum=0)),
    ("odometer_m", integer("Vehicle odometer, metres.", minimum=0)),
    ("provenance", PROV()),
  ]),
  ["asset_ref", "geo", "provenance"],
  "vehicle", "BUS-4471", "asset:vehicle:BUS-4471",
  {"asset_ref": {"class": "vehicle", "id": "BUS-4471", "tenant": "xmpl"},
   "geo": {"lat": 53.6112, "lon": -2.1503},
   "provenance": {"producer": "transit-core/1.0.0", "node": "site-xmpl-depot-01",
                  "observed_at": "2026-09-07T14:02:00.000Z"}},
  {"asset_ref": {"class": "vehicle", "id": "BUS-4471", "tenant": "xmpl"},
   "route_id": "R-142", "trip_id": "T-142-0743",
   "geo": {"lat": 53.6112, "lon": -2.1503, "accuracy_m": 6.0, "cell": "XMPL-0742-19"},
   "bearing_deg": 187.5, "speed_kph": 24.8, "odometer_m": 418223905,
   "provenance": {"producer": "transit-core/1.0.0", "node": "site-xmpl-depot-01",
                  "observed_at": "2026-09-07T14:02:00.310Z", "method": "gnss-fix"}})

E("transit", "stop-arrived", "operational", False, False,
  "A vehicle arrived at a scheduled stop.",
  ["transit-core"],
  OD([
    ("asset_ref", asset(["vehicle"], "Arriving vehicle.")),
    ("stop_ref", STOP("Stop arrived at.")),
    ("route_id", sid("Route being worked.")),
    ("trip_id", sid("Trip being worked.")),
    ("arrived_at", ts("When the vehicle arrived.")),
    ("scheduled_at", ts("Scheduled arrival time.")),
    ("delay_s", integer("Signed seconds late. Negative is early.")),
    ("provenance", PROV()),
  ]),
  ["asset_ref", "stop_ref", "trip_id", "arrived_at", "provenance"],
  "vehicle", "BUS-4471", "asset:stop:S-00912",
  {"asset_ref": {"class": "vehicle", "id": "BUS-4471", "tenant": "xmpl"},
   "stop_ref": {"class": "stop", "id": "S-00912", "tenant": "xmpl"},
   "trip_id": "T-142-0743", "arrived_at": "2026-09-07T14:03:12.000Z",
   "provenance": {"producer": "transit-core/1.0.0", "node": "site-xmpl-depot-01",
                  "observed_at": "2026-09-07T14:03:12.140Z"}},
  {"asset_ref": {"class": "vehicle", "id": "BUS-4471", "tenant": "xmpl"},
   "stop_ref": {"class": "stop", "id": "S-00912", "tenant": "xmpl"},
   "route_id": "R-142", "trip_id": "T-142-0743",
   "arrived_at": "2026-09-07T14:03:12.000Z", "scheduled_at": "2026-09-07T14:02:00.000Z",
   "delay_s": 72,
   "provenance": {"producer": "transit-core/1.0.0", "node": "site-xmpl-depot-01",
                  "observed_at": "2026-09-07T14:03:12.140Z", "method": "geofence"}})

E("transit", "stop-departed", "operational", False, False,
  "A vehicle departed a scheduled stop.",
  ["transit-core"],
  OD([
    ("asset_ref", asset(["vehicle"], "Departing vehicle.")),
    ("stop_ref", STOP("Stop departed from.")),
    ("route_id", sid("Route being worked.")),
    ("trip_id", sid("Trip being worked.")),
    ("departed_at", ts("When the vehicle departed.")),
    ("scheduled_at", ts("Scheduled departure time.")),
    ("dwell_s", integer("Seconds spent at the stop.", minimum=0)),
    ("delay_s", integer("Signed seconds late. Negative is early.")),
    ("provenance", PROV()),
  ]),
  ["asset_ref", "stop_ref", "trip_id", "departed_at", "provenance"],
  "vehicle", "BUS-4471", "asset:stop:S-00912",
  {"asset_ref": {"class": "vehicle", "id": "BUS-4471", "tenant": "xmpl"},
   "stop_ref": {"class": "stop", "id": "S-00912", "tenant": "xmpl"},
   "trip_id": "T-142-0743", "departed_at": "2026-09-07T14:03:41.000Z",
   "provenance": {"producer": "transit-core/1.0.0", "node": "site-xmpl-depot-01",
                  "observed_at": "2026-09-07T14:03:41.220Z"}},
  {"asset_ref": {"class": "vehicle", "id": "BUS-4471", "tenant": "xmpl"},
   "stop_ref": {"class": "stop", "id": "S-00912", "tenant": "xmpl"},
   "route_id": "R-142", "trip_id": "T-142-0743",
   "departed_at": "2026-09-07T14:03:41.000Z", "scheduled_at": "2026-09-07T14:02:30.000Z",
   "dwell_s": 29, "delay_s": 71,
   "provenance": {"producer": "transit-core/1.0.0", "node": "site-xmpl-depot-01",
                  "observed_at": "2026-09-07T14:03:41.220Z", "method": "geofence"}})

E("transit", "load-estimated", "operational", False, True,
  "Estimated passenger load aboard a vehicle. Inferred from APC or weight sensing, "
  "so confidence is required and consumers MUST NOT treat the count as measured.",
  ["transit-core"],
  OD([
    ("asset_ref", asset(["vehicle"], "Vehicle the estimate applies to.")),
    ("trip_id", sid("Trip being worked.")),
    ("stop_ref", STOP("Stop the estimate was taken at, where it was.")),
    ("passenger_count", integer("Estimated passengers aboard.", minimum=0)),
    ("capacity", integer("Rated capacity of the vehicle.", minimum=1)),
    ("load_pct", num("Estimated load as a percentage of capacity.", minimum=0)),
    ("provenance", PROV_INF()),
  ]),
  ["asset_ref", "passenger_count", "provenance"],
  "vehicle", "BUS-4471", "asset:vehicle:BUS-4471",
  {"asset_ref": {"class": "vehicle", "id": "BUS-4471", "tenant": "xmpl"},
   "passenger_count": 34,
   "provenance": {"producer": "transit-core/1.0.0", "node": "site-xmpl-depot-01",
                  "observed_at": "2026-09-07T14:03:45.000Z", "confidence": 0.88}},
  {"asset_ref": {"class": "vehicle", "id": "BUS-4471", "tenant": "xmpl"},
   "trip_id": "T-142-0743", "stop_ref": {"class": "stop", "id": "S-00912", "tenant": "xmpl"},
   "passenger_count": 34, "capacity": 78, "load_pct": 43.6,
   "provenance": {"producer": "transit-core/1.0.0", "node": "site-xmpl-depot-01",
                  "observed_at": "2026-09-07T14:03:45.512Z", "confidence": 0.88,
                  "method": "apc-doorway"}})

E("transit", "headway-deviated", "operational", False, False,
  "Observed headway on a route diverged materially from schedule at a stop. "
  "Bunching and gapping are reported as the same event with opposite direction.",
  ["transit-core"],
  OD([
    ("route_id", sid("Route the deviation was observed on.")),
    ("stop_ref", STOP("Stop where headway was measured.")),
    ("direction", oe(["bunching", "gapping"], "Sign of the deviation.")),
    ("scheduled_headway_s", integer("Scheduled headway, seconds.", minimum=0)),
    ("actual_headway_s", integer("Observed headway, seconds.", minimum=0)),
    ("deviation_s", integer("Signed difference, seconds.")),
    ("observed_at_stop", ts("When the deviation was measured.")),
    ("provenance", PROV()),
  ]),
  ["route_id", "stop_ref", "direction", "scheduled_headway_s", "actual_headway_s", "provenance"],
  "stop", "S-00912", "asset:stop:S-00912",
  {"route_id": "R-142", "stop_ref": {"class": "stop", "id": "S-00912", "tenant": "xmpl"},
   "direction": "bunching", "scheduled_headway_s": 600, "actual_headway_s": 95,
   "provenance": {"producer": "transit-core/1.0.0", "node": "core-xmpl-01",
                  "observed_at": "2026-09-07T14:04:00.000Z"}},
  {"route_id": "R-142", "stop_ref": {"class": "stop", "id": "S-00912", "tenant": "xmpl"},
   "direction": "bunching", "scheduled_headway_s": 600, "actual_headway_s": 95,
   "deviation_s": -505, "observed_at_stop": "2026-09-07T14:04:00.000Z",
   "provenance": {"producer": "transit-core/1.0.0", "node": "core-xmpl-01",
                  "observed_at": "2026-09-07T14:04:00.180Z", "method": "headway-monitor"}})

E("transit", "trip-cancelled", "operational", False, False,
  "A scheduled trip will not run. Anonymous: affected travellers are notified by "
  "the passenger app from the route and time, not from a list of who was aboard.",
  ["transit-core"],
  OD([
    ("trip_id", sid("Trip being cancelled.")),
    ("route_id", sid("Route the trip belongs to.")),
    ("reason", oe(["vehicle-fault", "staff-shortage", "incident", "weather", "planned",
                   "congestion"], "Why the trip was cancelled.")),
    ("cancelled_at", ts("When the cancellation was decided.")),
    ("affected_stops", arr(sid("Stop identifier."), "Stops that will not be served.")),
    ("provenance", PROV()),
  ]),
  ["trip_id", "route_id", "reason", "cancelled_at", "provenance"],
  "vehicle", "BUS-4471", None,
  {"trip_id": "T-142-0801", "route_id": "R-142", "reason": "vehicle-fault",
   "cancelled_at": "2026-09-07T14:10:00.000Z",
   "provenance": {"producer": "transit-core/1.0.0", "node": "core-xmpl-01",
                  "observed_at": "2026-09-07T14:10:00.500Z"}},
  {"trip_id": "T-142-0801", "route_id": "R-142", "reason": "vehicle-fault",
   "cancelled_at": "2026-09-07T14:10:00.000Z",
   "affected_stops": ["S-00912", "S-00913", "S-00915"],
   "provenance": {"producer": "transit-core/1.0.0", "node": "core-xmpl-01",
                  "observed_at": "2026-09-07T14:10:00.500Z", "method": "operations-console"}})

E("transit", "od-flow-aggregated", "analytical", False, False,
  "Journey counts between two grid cells over a period. The analytical counterpart "
  "to journey-completed: linkage is performed inside transit-core before "
  "publication and does not survive into the aggregate. Coarse geo only, and a "
  "floor on `journeys` so a flow cannot describe one traveller.",
  ["transit-core"],
  OD([
    ("origin_cell", CELL),
    ("destination_cell", CELL),
    ("aggregate", agg("Bucket, identity and revision of this figure.")),
    ("journeys", integer("Journeys observed between the two cells. Floored at 5 so an "
                         "origin-destination pair cannot describe a single traveller.", minimum=5)),
    ("median_duration_s", integer("Median journey duration, seconds.", minimum=0)),
    ("mode", oe(["bus", "tram", "rail", "multi"], "Predominant mode of the flow.")),
    ("provenance", PROV()),
  ]),
  ["origin_cell", "destination_cell", "aggregate", "journeys", "provenance"],
  "gateway", "GW-XMPL-TRANSIT-01", None,
  {"origin_cell": "XMPL-0742-19", "destination_cell": "XMPL-0755-04",
   "aggregate": {"aggregate_id": "od-XMPL-0742-19-XMPL-0755-04", "window": "2026-09-07T08Z", "revision": 0},
   "journeys": 428,
   "provenance": {"producer": "transit-core/1.0.0", "node": "core-xmpl-01",
                  "observed_at": "2026-09-07T09:05:00.000Z"}},
  {"origin_cell": "XMPL-0742-19", "destination_cell": "XMPL-0755-04",
   "aggregate": {"aggregate_id": "od-XMPL-0742-19-XMPL-0755-04", "window": "2026-09-07T08Z", "revision": 0},
   "journeys": 428, "median_duration_s": 1420, "mode": "bus",
   "provenance": {"producer": "transit-core/1.0.0", "node": "core-xmpl-01",
                  "observed_at": "2026-09-07T09:05:00.771Z", "method": "batch-rollup"}},
  xagg=xagg("journeys"))

def seal(seed, epoch=3):
    """A sealed field for examples. Ciphertext is 32 bytes plus the 16-byte GCM tag."""
    body = hashlib.sha256(("ct:" + seed).encode()).digest()[:32]
    tag = hashlib.sha256(("tag:" + seed).encode()).digest()[:16]
    iv = hashlib.sha256(("iv:" + seed).encode()).digest()[:12]
    return OD([("alg", "AES-256-GCM"), ("key_id", "dk_" + ulid("dk:" + seed)),
               ("epoch", epoch), ("ct", base64.b64encode(body + tag).decode()),
               ("iv", base64.b64encode(iv).decode())])

CURRENCY = lambda: OD([("type", "string"), ("pattern", "^[A-Z]{3}$"),
                       ("description", "ISO 4217 currency code.")])
SUBJ_T = lambda why: subject("Pairwise pseudonym of the traveller, issued by identity-gateway "
                            "for the `transit` domain. " + why)

E("transit", "fare-validated", "operational", True, False,
  "A fare product was presented and validated. Subject-linked because a fare cap "
  "is a sum over that person's journeys: settling it requires per-person state, "
  "and an entitlement class alone cannot express it.",
  ["transit-core"],
  OD([
    ("subject_ref", SUBJ_T("Required to accumulate a daily or weekly cap.")),
    ("asset_ref", asset(["vehicle"], "Vehicle the validator is mounted in.")),
    ("stop_ref", STOP("Stop the validation occurred at, where the validator is fixed.")),
    ("product", oe(["single", "day-cap", "season", "concessionary", "contactless", "mobile"],
                   "Fare product presented.")),
    ("result", oe(["accepted", "rejected-expired", "rejected-blocked",
                   "rejected-insufficient", "rejected-unknown"], "Outcome of validation.")),
    ("fare_minor", integer("Fare charged in minor currency units. Zero for concessionary travel.", minimum=0)),
    ("currency", CURRENCY()),
    ("cap_reached", boolean("True if this validation brought the traveller to a fare cap.")),
    ("validated_at", ts("When the product was presented.")),
    ("provenance", PROV()),
  ]),
  ["subject_ref", "product", "result", "validated_at", "provenance"],
  "vehicle", "BUS-4471", "asset:vehicle:BUS-4471",
  {"subject_ref": {"pid": pid("transit", 3, "traveller-a"), "epoch": 3},
   "product": "contactless", "result": "accepted", "validated_at": "2026-09-07T14:03:20.000Z",
   "provenance": {"producer": "transit-core/1.0.0", "node": "site-xmpl-depot-01",
                  "observed_at": "2026-09-07T14:03:20.410Z"}},
  {"subject_ref": {"pid": pid("transit", 3, "traveller-a"), "epoch": 3},
   "asset_ref": {"class": "vehicle", "id": "BUS-4471", "tenant": "xmpl"},
   "stop_ref": {"class": "stop", "id": "S-00912", "tenant": "xmpl"},
   "product": "contactless", "result": "accepted", "fare_minor": 210, "currency": "GBP",
   "cap_reached": False, "validated_at": "2026-09-07T14:03:20.000Z",
   "provenance": {"producer": "transit-core/1.0.0", "node": "site-xmpl-depot-01",
                  "observed_at": "2026-09-07T14:03:20.410Z", "method": "emv-validator"}})

E("transit", "entitlement-checked", "operational", True, False,
  "A concessionary or staff entitlement was checked against the register. "
  "Subject-linked because the entitlement is held by a person and the check is a "
  "lookup of whether this person holds it - the class alone answers nothing.",
  ["transit-core"],
  OD([
    ("subject_ref", SUBJ_T("Required to look the entitlement up in the register.")),
    ("entitlement", oe(["concessionary-older", "concessionary-disabled", "student",
                        "staff", "companion", "jobseeker"], "Entitlement checked.")),
    ("valid", boolean("Whether the entitlement was in force at check time.")),
    ("checked_at", ts("When the check was performed.")),
    ("expires_at", ts("When the entitlement expires, if it is valid.")),
    ("asset_ref", asset(["vehicle"], "Vehicle the check was performed on.")),
    ("provenance", PROV()),
  ]),
  ["subject_ref", "entitlement", "valid", "checked_at", "provenance"],
  "vehicle", "BUS-4471", "asset:vehicle:BUS-4471",
  {"subject_ref": {"pid": pid("transit", 3, "traveller-b"), "epoch": 3},
   "entitlement": "concessionary-disabled", "valid": True,
   "checked_at": "2026-09-07T14:03:21.000Z",
   "provenance": {"producer": "transit-core/1.0.0", "node": "site-xmpl-depot-01",
                  "observed_at": "2026-09-07T14:03:21.030Z"}},
  {"subject_ref": {"pid": pid("transit", 3, "traveller-b"), "epoch": 3},
   "entitlement": "concessionary-disabled", "valid": True,
   "checked_at": "2026-09-07T14:03:21.000Z", "expires_at": "2027-03-31T23:59:59.000Z",
   "asset_ref": {"class": "vehicle", "id": "BUS-4471", "tenant": "xmpl"},
   "provenance": {"producer": "transit-core/1.0.0", "node": "site-xmpl-depot-01",
                  "observed_at": "2026-09-07T14:03:21.030Z", "method": "register-lookup"}})

E("transit", "assistance-requested", "operational", True, False,
  "A traveller requested boarding or journey assistance. Subject-linked because "
  "staff must retrieve a registered needs profile to honour it. The profile itself "
  "is sealed: `assistance_type` is enough to dispatch, and the detail is health "
  "information that no consumer of the operational stream needs in clear.",
  ["transit-core"],
  OD([
    ("subject_ref", SUBJ_T("Required to retrieve the registered needs profile.")),
    ("stop_ref", STOP("Stop assistance was requested at.")),
    ("trip_id", sid("Trip assistance is requested for.")),
    ("assistance_type", oe(["ramp", "wheelchair-space", "guide", "boarding-help",
                            "audio-announcement", "priority-seat"],
                           "Assistance requested. Sufficient on its own to dispatch.")),
    ("needs", sealed("Registered needs detail, sealed under a per-subject data key. "
                     "Decodes to Opened, Shredded, or Unavailable; an undecryptable "
                     "payload is a normal condition, not an error.")),
    ("requested_at", ts("When assistance was requested.")),
    ("asset_ref", asset(["vehicle"], "Vehicle assigned to honour the request.")),
    ("provenance", PROV()),
  ]),
  ["subject_ref", "stop_ref", "assistance_type", "requested_at", "provenance"],
  "vehicle", "BUS-4471", "asset:stop:S-00912",
  {"subject_ref": {"pid": pid("transit", 3, "traveller-b"), "epoch": 3},
   "stop_ref": {"class": "stop", "id": "S-00912", "tenant": "xmpl"},
   "assistance_type": "ramp", "requested_at": "2026-09-07T13:55:00.000Z",
   "provenance": {"producer": "transit-core/1.0.0", "node": "core-xmpl-01",
                  "observed_at": "2026-09-07T13:55:00.260Z"}},
  {"subject_ref": {"pid": pid("transit", 3, "traveller-b"), "epoch": 3},
   "stop_ref": {"class": "stop", "id": "S-00912", "tenant": "xmpl"},
   "trip_id": "T-142-0743", "assistance_type": "ramp",
   "needs": seal("traveller-b-needs"),
   "requested_at": "2026-09-07T13:55:00.000Z",
   "asset_ref": {"class": "vehicle", "id": "BUS-4471", "tenant": "xmpl"},
   "provenance": {"producer": "transit-core/1.0.0", "node": "core-xmpl-01",
                  "observed_at": "2026-09-07T13:55:00.260Z", "method": "passenger-app"}})

E("transit", "journey-completed", "operational", True, True,
  "A traveller's multi-leg journey was determined to have ended. Subject-linked "
  "because the legs must be attributed to one traveller to settle a capped fare. "
  "Inferred: journey end is decided by a timeout heuristic, not observed, so it "
  "carries confidence. The analytical view is od-flow-aggregated, which carries "
  "no subject reference.",
  ["transit-core"],
  OD([
    ("subject_ref", SUBJ_T("Required to attribute the legs to one traveller for fare settlement.")),
    ("journey_id", sid("Journey identifier, scoped to the traveller and the epoch.")),
    ("origin_stop", STOP("First boarding stop of the journey.")),
    ("destination_stop", STOP("Last alighting stop of the journey.")),
    ("started_at", ts("First validation of the journey.")),
    ("completed_at", ts("When the journey was determined to have ended.")),
    ("leg_count", integer("Number of legs in the journey.", minimum=1)),
    ("fare_total_minor", integer("Total fare charged in minor currency units.", minimum=0)),
    ("currency", CURRENCY()),
    ("provenance", PROV_INF()),
  ]),
  ["subject_ref", "journey_id", "started_at", "completed_at", "provenance"],
  "gateway", "GW-XMPL-TRANSIT-01", None,
  {"subject_ref": {"pid": pid("transit", 3, "traveller-a"), "epoch": 3},
   "journey_id": "J-3-0f21ab88", "started_at": "2026-09-07T14:03:20.000Z",
   "completed_at": "2026-09-07T14:41:02.000Z",
   "provenance": {"producer": "transit-core/1.0.0", "node": "core-xmpl-01",
                  "observed_at": "2026-09-07T15:11:02.000Z", "confidence": 0.92}},
  {"subject_ref": {"pid": pid("transit", 3, "traveller-a"), "epoch": 3},
   "journey_id": "J-3-0f21ab88",
   "origin_stop": {"class": "stop", "id": "S-00912", "tenant": "xmpl"},
   "destination_stop": {"class": "stop", "id": "S-01044", "tenant": "xmpl"},
   "started_at": "2026-09-07T14:03:20.000Z", "completed_at": "2026-09-07T14:41:02.000Z",
   "leg_count": 2, "fare_total_minor": 320, "currency": "GBP",
   "provenance": {"producer": "transit-core/1.0.0", "node": "core-xmpl-01",
                  "observed_at": "2026-09-07T15:11:02.000Z", "confidence": 0.92,
                  "method": "journey-stitch"}})

# ============================================================ vision (6)
# No subject_ref anywhere, enforced by lint under schemas/vision/. track_ref is
# banned from analytical retention and permitted in evidential.
CAM = lambda desc: asset(["camera"], desc)
OBJ_CLASS = lambda: oe(["person", "cycle", "motorcycle", "car", "taxi", "van", "bus",
                        "lgv", "hgv", "unknown"], "Assigned object class.")
BBOX = OD([
    ("type", "object"),
    ("description", "Bounding box in normalised frame coordinates, origin top-left."),
    ("properties", OD([
        ("x", num("Left edge as a fraction of frame width.", minimum=0, maximum=1)),
        ("y", num("Top edge as a fraction of frame height.", minimum=0, maximum=1)),
        ("w", num("Width as a fraction of frame width.", minimum=0, maximum=1)),
        ("h", num("Height as a fraction of frame height.", minimum=0, maximum=1)),
    ])),
    ("required", ["x", "y", "w", "h"]),
    ("additionalProperties", False),
])
DIGEST = OD([
    ("type", "object"),
    ("description", "Content digest of the sealed material."),
    ("properties", OD([
        ("alg", oe(["sha-256", "sha-512"], "Digest algorithm.")),
        ("value", OD([("type", "string"), ("pattern", "^[0-9a-f]{64,128}$"),
                      ("description", "Lowercase hex digest.")])),
    ])),
    ("required", ["alg", "value"]),
    ("additionalProperties", False),
])

E("vision", "stream-health-changed", "operational", False, False,
  "A registered camera stream changed health state. Carries no track and no "
  "subject: this is an asset fact.",
  ["mca-ingest"],
  OD([
    ("asset_ref", CAM("Camera the stream belongs to.")),
    ("stream_id", sid("Registered stream identifier.", "^[a-z0-9][a-z0-9-]{0,63}$")),
    ("state_from", oe(["healthy", "degraded", "offline", "unauthenticated"], "State before the change.")),
    ("state_to", oe(["healthy", "degraded", "offline", "unauthenticated"], "State after the change.")),
    ("reason", oe(["link-loss", "frame-drop", "cert-expired", "ntp-drift", "restart",
                   "bandwidth", "unknown"], "Why the state changed.")),
    ("fps", num("Observed frame rate.", minimum=0)),
    ("bitrate_kbps", integer("Observed bitrate, kilobits per second.", minimum=0)),
    ("changed_at", ts("When the state change was observed.")),
    ("provenance", PROV()),
  ]),
  ["asset_ref", "stream_id", "state_to", "changed_at", "provenance"],
  "camera", "CAM-0742-03", "asset:camera:CAM-0742-03",
  {"asset_ref": {"class": "camera", "id": "CAM-0742-03", "tenant": "xmpl"},
   "stream_id": "cam-xmpl-0742-03", "state_to": "degraded",
   "changed_at": "2026-09-07T14:00:41.000Z",
   "provenance": {"producer": "mca-ingest/1.0.0", "node": "site-xmpl-north-02",
                  "observed_at": "2026-09-07T14:00:41.180Z"}},
  {"asset_ref": {"class": "camera", "id": "CAM-0742-03", "tenant": "xmpl"},
   "stream_id": "cam-xmpl-0742-03", "state_from": "healthy", "state_to": "degraded",
   "reason": "frame-drop", "fps": 11.4, "bitrate_kbps": 1820,
   "changed_at": "2026-09-07T14:00:41.000Z",
   "provenance": {"producer": "mca-ingest/1.0.0", "node": "site-xmpl-north-02",
                  "observed_at": "2026-09-07T14:00:41.180Z", "method": "onvif-analytics"}})

E("vision", "object-detected", "operational", False, True,
  "On-node analytics detected an object in a registered stream and opened or "
  "continued a track. Inferred, so confidence is required. The track is the only "
  "handle on the object and it dies at the hour boundary.",
  ["mca-ingest"],
  OD([
    ("asset_ref", CAM("Camera that produced the detection.")),
    ("track_ref", track("Track the detection belongs to. Scoped to one stream and one "
                        "wall-clock UTC hour; not a person reference.")),
    ("bbox", BBOX),
    ("geo", ref("geo", "#/$defs/precise")),
    ("detected_at", ts("When the detection was made.")),
    ("provenance", PROV_INF()),
  ]),
  ["asset_ref", "track_ref", "bbox", "detected_at", "provenance"],
  "camera", "CAM-0742-03", "asset:camera:CAM-0742-03",
  {"asset_ref": {"class": "camera", "id": "CAM-0742-03", "tenant": "xmpl"},
   "track_ref": {"stream_id": "cam-xmpl-0742-03", "track_id": "9f2c1a7be4d05836",
                 "window": "2026-09-07T14Z"},
   "bbox": {"x": 0.412, "y": 0.318, "w": 0.061, "h": 0.174},
   "detected_at": "2026-09-07T14:02:09.000Z",
   "provenance": {"producer": "mca-ingest/1.0.0", "node": "site-xmpl-north-02",
                  "observed_at": "2026-09-07T14:02:09.044Z", "confidence": 0.96}},
  {"asset_ref": {"class": "camera", "id": "CAM-0742-03", "tenant": "xmpl"},
   "track_ref": {"stream_id": "cam-xmpl-0742-03", "track_id": "9f2c1a7be4d05836",
                 "window": "2026-09-07T14Z"},
   "bbox": {"x": 0.412, "y": 0.318, "w": 0.061, "h": 0.174},
   "geo": {"lat": 53.6099, "lon": -2.1559, "accuracy_m": 3.2, "cell": "XMPL-0742-19"},
   "detected_at": "2026-09-07T14:02:09.000Z",
   "provenance": {"producer": "mca-ingest/1.0.0", "node": "site-xmpl-north-02",
                  "observed_at": "2026-09-07T14:02:09.044Z", "confidence": 0.96,
                  "method": "onvif-analytics"}})

E("vision", "object-classified", "operational", False, True,
  "A tracked object in a registered stream was assigned a class by on-node "
  "analytics. Inferred; carries confidence.",
  ["mca-ingest"],
  OD([
    ("asset_ref", CAM("Camera that produced the classification.")),
    ("track_ref", track("Track being classified. Scoped to one stream and one wall-clock "
                        "UTC hour; not a person reference.")),
    ("object_class", OBJ_CLASS()),
    ("previous_class", oe(["person", "cycle", "motorcycle", "car", "taxi", "van", "bus",
                           "lgv", "hgv", "unknown"],
                          "Class previously assigned to this track, where it changed.")),
    ("classified_at", ts("When the classification was made.")),
    ("provenance", PROV_INF()),
  ]),
  ["asset_ref", "track_ref", "object_class", "classified_at", "provenance"],
  "camera", "CAM-0742-03", "asset:camera:CAM-0742-03",
  {"asset_ref": {"class": "camera", "id": "CAM-0742-03", "tenant": "xmpl"},
   "track_ref": {"stream_id": "cam-xmpl-0742-03", "track_id": "9f2c1a7be4d05836",
                 "window": "2026-09-07T14Z"},
   "object_class": "person", "classified_at": "2026-09-07T14:02:11.000Z",
   "provenance": {"producer": "mca-ingest/1.0.0", "node": "site-xmpl-north-02",
                  "observed_at": "2026-09-07T14:02:11.417Z", "confidence": 0.94}},
  {"asset_ref": {"class": "camera", "id": "CAM-0742-03", "tenant": "xmpl"},
   "track_ref": {"stream_id": "cam-xmpl-0742-03", "track_id": "9f2c1a7be4d05836",
                 "window": "2026-09-07T14Z"},
   "object_class": "person", "previous_class": "unknown",
   "classified_at": "2026-09-07T14:02:11.000Z",
   "provenance": {"producer": "mca-ingest/1.0.0", "node": "site-xmpl-north-02",
                  "observed_at": "2026-09-07T14:02:11.912Z", "confidence": 0.94,
                  "method": "onvif-analytics"}})

E("vision", "footage-retention-applied", "audit", False, False,
  "A retention policy was applied to a window of stored footage. Audit class: it "
  "records what happened to the material, and carries neither a track nor a "
  "subject so that the seven-year append-only store holds no personal data.",
  ["mca-ingest"],
  OD([
    ("asset_ref", CAM("Camera whose footage the policy was applied to.")),
    ("stream_id", sid("Registered stream identifier.", "^[a-z0-9][a-z0-9-]{0,63}$")),
    ("policy_id", sid("Retention policy applied.")),
    ("action", oe(["retained", "expired", "purged", "extended", "exported"],
                  "What the policy did to the window.")),
    ("window_start", ts("Start of the footage window, inclusive.")),
    ("window_end", ts("End of the footage window, exclusive.")),
    ("bytes", integer("Size of the affected material, bytes.", minimum=0)),
    ("applied_at", ts("When the policy was applied.")),
    ("provenance", PROV()),
  ]),
  ["asset_ref", "stream_id", "policy_id", "action", "window_start", "window_end",
   "applied_at", "provenance"],
  "camera", "CAM-0742-03", "asset:camera:CAM-0742-03",
  {"asset_ref": {"class": "camera", "id": "CAM-0742-03", "tenant": "xmpl"},
   "stream_id": "cam-xmpl-0742-03", "policy_id": "P-STD-31D", "action": "purged",
   "window_start": "2026-08-07T00:00:00.000Z", "window_end": "2026-08-08T00:00:00.000Z",
   "applied_at": "2026-09-07T03:00:00.000Z",
   "provenance": {"producer": "mca-ingest/1.0.0", "node": "site-xmpl-north-02",
                  "observed_at": "2026-09-07T03:00:00.900Z"}},
  {"asset_ref": {"class": "camera", "id": "CAM-0742-03", "tenant": "xmpl"},
   "stream_id": "cam-xmpl-0742-03", "policy_id": "P-STD-31D", "action": "purged",
   "window_start": "2026-08-07T00:00:00.000Z", "window_end": "2026-08-08T00:00:00.000Z",
   "bytes": 48210993152, "applied_at": "2026-09-07T03:00:00.000Z",
   "provenance": {"producer": "mca-ingest/1.0.0", "node": "site-xmpl-north-02",
                  "observed_at": "2026-09-07T03:00:00.900Z", "method": "retention-sweep"}})

E("vision", "footage-sealed", "evidential", False, False,
  "A window of footage was placed under legal hold. Evidential retention, read "
  "logged. This is the path a court order takes: it reaches the footage store "
  "under a legal basis, not the bus and not the correlation endpoint. May carry a "
  "track_ref, which analytical retention may not.",
  ["mca-ingest"],
  OD([
    ("asset_ref", CAM("Camera whose footage was sealed.")),
    ("stream_id", sid("Registered stream identifier.", "^[a-z0-9][a-z0-9-]{0,63}$")),
    ("seal_id", sid("Seal identifier, referenced by subsequent access logs.")),
    ("track_ref", track("Track the seal was requested against, where the request named one. "
                        "Permitted here and banned in analytical retention.")),
    ("window_start", ts("Start of the sealed window, inclusive.")),
    ("window_end", ts("End of the sealed window, exclusive.")),
    ("legal_basis_ref", OD([("type", "string"), ("maxLength", 256),
                            ("description", "Reference to the legal basis for the hold.")])),
    ("hold_until", ts("When the hold expires, if it is time-bounded.")),
    ("digest", DIGEST),
    ("sealed_at", ts("When the seal was applied.")),
    ("provenance", PROV()),
  ]),
  ["asset_ref", "stream_id", "seal_id", "window_start", "window_end", "legal_basis_ref",
   "sealed_at", "provenance"],
  "camera", "CAM-0742-03", "asset:camera:CAM-0742-03",
  {"asset_ref": {"class": "camera", "id": "CAM-0742-03", "tenant": "xmpl"},
   "stream_id": "cam-xmpl-0742-03", "seal_id": "SEAL-2026-0044",
   "window_start": "2026-09-07T13:50:00.000Z", "window_end": "2026-09-07T14:20:00.000Z",
   "legal_basis_ref": "court-order/XMPL-CC-2026-1187", "sealed_at": "2026-09-07T16:02:00.000Z",
   "provenance": {"producer": "mca-ingest/1.0.0", "node": "core-xmpl-01",
                  "observed_at": "2026-09-07T16:02:00.310Z"}},
  {"asset_ref": {"class": "camera", "id": "CAM-0742-03", "tenant": "xmpl"},
   "stream_id": "cam-xmpl-0742-03", "seal_id": "SEAL-2026-0044",
   "track_ref": {"stream_id": "cam-xmpl-0742-03", "track_id": "9f2c1a7be4d05836",
                 "window": "2026-09-07T14Z"},
   "window_start": "2026-09-07T13:50:00.000Z", "window_end": "2026-09-07T14:20:00.000Z",
   "legal_basis_ref": "court-order/XMPL-CC-2026-1187", "hold_until": "2027-09-07T00:00:00.000Z",
   "digest": {"alg": "sha-256",
              "value": "3b1f0c9a77e5d4218a6c0be93f4d271c5580aa9e1d6b3427ff8c0e21b4a97d05"},
   "sealed_at": "2026-09-07T16:02:00.000Z",
   "provenance": {"producer": "mca-ingest/1.0.0", "node": "core-xmpl-01",
                  "observed_at": "2026-09-07T16:02:00.310Z", "method": "evidence-console"}})

E("vision", "count-aggregated", "analytical", False, False,
  "Objects of a class counted in a grid cell over a period. The analytical view of "
  "vision. Carries no track_ref: an hour-scoped per-person handle in a 90-day "
  "store reconstructs exactly what the hour scoping prevents. Coarse geo only, and "
  "buckets below the floor are suppressed rather than published.",
  ["mca-ingest"],
  OD([
    ("geo", ref("geo", "#/$defs/coarse")),
    ("object_class", OBJ_CLASS()),
    ("count", integer("Objects counted. Floored at 5; smaller buckets are suppressed, "
                      "because a count of one in a cell and an hour describes a person.", minimum=5)),
    ("aggregate", agg("Bucket, identity and revision of this figure.")),
    ("asset_ref", CAM("Camera the counts were derived from.")),
    ("provenance", PROV()),
  ]),
  ["geo", "object_class", "count", "aggregate", "provenance"],
  "camera", "CAM-0742-03", None,
  {"geo": {"cell": "XMPL-0742-19"}, "object_class": "person", "count": 1842,
   "aggregate": {"aggregate_id": "cnt-XMPL-0742-19-person", "window": "2026-09-07T14Z", "revision": 0},
   "provenance": {"producer": "mca-ingest/1.0.0", "node": "core-xmpl-01",
                  "observed_at": "2026-09-07T15:01:00.000Z"}},
  {"geo": {"cell": "XMPL-0742-19"}, "object_class": "person", "count": 1842,
   "aggregate": {"aggregate_id": "cnt-XMPL-0742-19-person", "window": "2026-09-07T14Z", "revision": 0},
   "asset_ref": {"class": "camera", "id": "CAM-0742-03", "tenant": "xmpl"},
   "provenance": {"producer": "mca-ingest/1.0.0", "node": "core-xmpl-01",
                  "observed_at": "2026-09-07T15:01:00.442Z", "method": "batch-rollup"}},
  xagg=xagg("count"))

# ============================================================ identity (10)
# The audit/evidential split exists because audit carries no personal data,
# pseudonyms included, while proof of an action must outlive the record naming
# whom it was performed on.
PSEUDO_DOMAIN = lambda desc: oe(["transit", "identity"], desc + " Only domains that carry "
                                "pseudonyms can appear: traffic and telemetry are anonymous "
                                "and vision uses track_ref.")
PRINCIPAL = lambda desc: OD([("type", "string"), ("pattern", "^[a-z0-9][a-z0-9._-]{1,63}$"),
                             ("description", desc)])
PURPOSE = lambda: OD([("type", "string"), ("pattern", "^[A-Z][A-Z0-9-]{2,31}$"),
                      ("description", "Registered purpose code the action was bound to.")])
LEGAL = lambda: OD([("type", "string"), ("maxLength", 256),
                    ("description", "Reference to the legal basis for the action.")])
SUBJ_I = lambda why: subject("Pairwise pseudonym of the data subject. " + why)
ATTEST = OD([
    ("type", "object"),
    ("description", "Signed attestation that the data keys were destroyed."),
    ("properties", OD([
        ("digest_alg", oe(["sha-256", "sha-512"], "Digest algorithm over the destroyed key set.")),
        ("digest", OD([("type", "string"), ("pattern", "^[0-9a-f]{64,128}$"),
                       ("description", "Lowercase hex digest over the destroyed key identifiers.")])),
        ("signer", PRINCIPAL("Key custody principal that signed the attestation.")),
    ])),
    ("required", ["digest_alg", "digest", "signer"]),
    ("additionalProperties", False),
])

E("identity", "pseudonym-issuance-recorded", "audit", False, False,
  "Hourly count of pseudonyms issued for a domain and epoch. An aggregate, and it "
  "carries no subject reference and no issuance identifier. A per-issuance event "
  "would leave a timing channel even after stripping the pseudonym: in a small "
  "tenant at low volume, two issuance events for different domains seconds apart "
  "are one person with high probability. That is weaker than a join, but section 6 "
  "makes unlinkability a property of the construction, and a channel whose strength "
  "depends on how busy the council is would demote it to a policy. Per-issuance "
  "audit stays in the gateway's own internal log, where it has a reader; nothing "
  "without a bus consumer belongs on the bus.",
  ["identity-gateway"],
  OD([
    ("domain", PSEUDO_DOMAIN("Domain the pseudonyms were issued for.")),
    ("epoch", integer("Epoch the pseudonyms were derived under.", minimum=0)),
    ("count", integer("Pseudonyms issued in the window. Floored at 5; a smaller bucket is "
                      "suppressed entirely rather than published as zero, so that a "
                      "suppressed bucket and an empty one are indistinguishable.", minimum=5)),
    ("reason", oe(["new-subject", "epoch-rotation", "re-issuance"],
                  "Restricts the bucket to one issuance reason. Absent means all reasons.")),
    ("aggregate", agg("Bucket, identity and revision of this figure.")),
    ("provenance", PROV()),
  ]),
  ["domain", "epoch", "count", "aggregate", "provenance"],
  "gateway", "GW-XMPL-ID-01", "asset:gateway:GW-XMPL-ID-01",
  {"domain": "transit", "epoch": 3, "count": 1842,
   "aggregate": {"aggregate_id": "psi-transit-e3", "window": "2026-07-01T00Z", "revision": 0},
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-07-01T01:05:00.000Z"}},
  {"domain": "transit", "epoch": 3, "count": 1842, "reason": "epoch-rotation",
   "aggregate": {"aggregate_id": "psi-transit-e3-epoch-rotation", "window": "2026-07-01T00Z", "revision": 0},
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-07-01T01:05:00.220Z", "method": "batch-rollup"}},
  xagg=xagg("count"))

E("identity", "pseudonym-epoch-rotated", "audit", False, False,
  "The pseudonym epoch advanced for a tenant and domain. Pseudonyms from different "
  "epochs are unlinkable by the same argument that makes domains unlinkable, which "
  "caps the window over which any one domain can build a longitudinal profile. "
  "Systems MUST NOT attempt to bridge epochs locally. Carries no pseudonym.",
  ["identity-gateway"],
  OD([
    ("rotation_id", sid("Rotation identifier.")),
    ("tenant", OD([("type", "string"), ("pattern", "^[a-z][a-z0-9-]{1,11}$"),
                   ("description", "Tenant whose epoch advanced.")])),
    ("domain", PSEUDO_DOMAIN("Domain whose keys were re-derived.")),
    ("epoch_from", integer("Epoch that ended.", minimum=0)),
    ("epoch_to", integer("Epoch now in force.", minimum=1)),
    ("effective_at", ts("When the new epoch took effect.")),
    ("pseudonyms_rotated", integer("Count of pseudonyms re-derived. A count, not a list.", minimum=0)),
    ("provenance", PROV()),
  ]),
  ["rotation_id", "tenant", "domain", "epoch_from", "epoch_to", "effective_at", "provenance"],
  "gateway", "GW-XMPL-ID-01", "asset:gateway:GW-XMPL-ID-01",
  {"rotation_id": "ROT-2026-Q3-transit", "tenant": "xmpl", "domain": "transit",
   "epoch_from": 3, "epoch_to": 4, "effective_at": "2026-09-29T00:00:00.000Z",
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-09-29T00:00:00.640Z"}},
  {"rotation_id": "ROT-2026-Q3-transit", "tenant": "xmpl", "domain": "transit",
   "epoch_from": 3, "epoch_to": 4, "effective_at": "2026-09-29T00:00:00.000Z",
   "pseudonyms_rotated": 418223,
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-09-29T00:00:00.640Z", "method": "hkdf-derive"}})

E("identity", "correlation-performed", "audit", False, False,
  "A cross-domain correlation was performed through the resolution endpoint. Audit "
  "class, seven years, append-only, and therefore carries no pseudonym: the pids "
  "correlated are recorded separately by correlation-detail-recorded under "
  "evidential retention and access logging. Emitted before the result is returned. "
  "There is no configuration in which this is silent and there is no bulk mode.",
  ["identity-gateway"],
  OD([
    ("correlation_id", sid("Correlation identifier. The join to the evidential detail record, "
                           "resolvable to a person only while that record survives.")),
    ("domain_a", PSEUDO_DOMAIN("First domain in the correlation.")),
    ("domain_b", PSEUDO_DOMAIN("Second domain in the correlation.")),
    ("purpose_code", PURPOSE()),
    ("principal_a", PRINCIPAL("First authorising principal.")),
    ("principal_b", PRINCIPAL("Second authorising principal. MUST differ from principal_a.")),
    ("legal_basis_ref", LEGAL()),
    ("expires_at", ts("When the authorisation for this correlation expires.")),
    ("outcome", oe(["matched", "no-match", "refused"], "Result of the correlation.")),
    ("performed_at", ts("When the correlation was performed.")),
    ("provenance", PROV()),
  ]),
  ["correlation_id", "domain_a", "domain_b", "purpose_code", "principal_a", "principal_b",
   "legal_basis_ref", "expires_at", "performed_at", "provenance"],
  "gateway", "GW-XMPL-ID-01", "asset:gateway:GW-XMPL-ID-01",
  {"correlation_id": "COR-2026-09-07-0007", "domain_a": "transit", "domain_b": "identity",
   "purpose_code": "SAFEGUARDING", "principal_a": "dpo.xmpl.gov", "principal_b": "head-of-transit.xmpl.gov",
   "legal_basis_ref": "court-order/XMPL-CC-2026-1187", "expires_at": "2026-09-14T00:00:00.000Z",
   "performed_at": "2026-09-07T16:40:00.000Z",
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-09-07T16:40:00.180Z"}},
  {"correlation_id": "COR-2026-09-07-0007", "domain_a": "transit", "domain_b": "identity",
   "purpose_code": "SAFEGUARDING", "principal_a": "dpo.xmpl.gov", "principal_b": "head-of-transit.xmpl.gov",
   "legal_basis_ref": "court-order/XMPL-CC-2026-1187", "expires_at": "2026-09-14T00:00:00.000Z",
   "outcome": "matched", "performed_at": "2026-09-07T16:40:00.000Z",
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-09-07T16:40:00.180Z", "method": "correlate-v1"}})

E("identity", "correlation-detail-recorded", "evidential", True, False,
  "The pseudonyms joined by a correlation. Evidential retention, read logged, and "
  "separated from the audit record so that the seven-year store holds proof the "
  "correlation happened without holding whom it was about.",
  ["identity-gateway"],
  OD([
    ("correlation_id", sid("Correlation this detail belongs to.")),
    ("subject_ref_a", SUBJ_I("Pseudonym in domain_a.")),
    ("subject_ref_b", SUBJ_I("Pseudonym in domain_b.")),
    ("recorded_at", ts("When the detail was recorded.")),
    ("provenance", PROV()),
  ]),
  ["correlation_id", "subject_ref_a", "subject_ref_b", "recorded_at", "provenance"],
  "gateway", "GW-XMPL-ID-01", "asset:gateway:GW-XMPL-ID-01",
  {"correlation_id": "COR-2026-09-07-0007",
   "subject_ref_a": {"pid": pid("transit", 3, "traveller-a"), "epoch": 3},
   "subject_ref_b": {"pid": pid("identity", 3, "traveller-a"), "epoch": 3},
   "recorded_at": "2026-09-07T16:40:00.000Z",
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-09-07T16:40:00.190Z"}},
  {"correlation_id": "COR-2026-09-07-0007",
   "subject_ref_a": {"pid": pid("transit", 3, "traveller-a"), "epoch": 3},
   "subject_ref_b": {"pid": pid("identity", 3, "traveller-a"), "epoch": 3},
   "recorded_at": "2026-09-07T16:40:00.000Z",
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-09-07T16:40:00.190Z", "method": "correlate-v1"}})

E("identity", "erasure-requested", "evidential", True, False,
  "Erasure was requested for a subject. Event logs are append-only, so erasure is "
  "performed by destroying the per-subject data key rather than by rewriting the "
  "log. Evidential rather than audit, because it names the subject.",
  ["identity-gateway"],
  OD([
    ("erasure_id", sid("Erasure identifier. The join to the audit attestation.")),
    ("subject_ref", SUBJ_I("Subject whose data keys are to be destroyed.")),
    ("basis", oe(["data-subject-request", "retention-expiry", "court-order", "contract-end"],
                 "Basis for the erasure.")),
    ("erase_all_domains", boolean("True when the erasure covers every domain the subject "
                                  "appears in. Which domains those are is not published: a "
                                  "domain list beside a pseudonym states that this person "
                                  "exists in that domain, which is the cross-domain link the "
                                  "pseudonymisation construction exists to prevent. The "
                                  "gateway holds the list internally, where it is acted on.")),
    ("requested_at", ts("When erasure was requested.")),
    ("provenance", PROV()),
  ]),
  ["erasure_id", "subject_ref", "basis", "requested_at", "provenance"],
  "gateway", "GW-XMPL-ID-01", "asset:gateway:GW-XMPL-ID-01",
  {"erasure_id": "ERA-2026-09-07-0021",
   "subject_ref": {"pid": pid("identity", 3, "traveller-c"), "epoch": 3},
   "basis": "data-subject-request", "requested_at": "2026-09-07T09:12:00.000Z",
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-09-07T09:12:00.410Z"}},
  {"erasure_id": "ERA-2026-09-07-0021",
   "subject_ref": {"pid": pid("identity", 3, "traveller-c"), "epoch": 3},
   "basis": "data-subject-request", "erase_all_domains": True,
   "requested_at": "2026-09-07T09:12:00.000Z",
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-09-07T09:12:00.410Z", "method": "dsr-console"}})

E("identity", "erasure-completed", "evidential", True, False,
  "The data keys for a subject were destroyed. Ciphertext remains in the log and "
  "is permanently unrecoverable; systems MUST handle undecryptable payloads as a "
  "normal condition rather than an error.",
  ["identity-gateway"],
  OD([
    ("erasure_id", sid("Erasure being completed. Matches a prior erasure-requested.")),
    ("subject_ref", SUBJ_I("Subject whose data keys were destroyed.")),
    ("completed_at", ts("When key destruction completed.")),
    ("keys_destroyed", integer("Number of per-subject data keys destroyed.", minimum=0)),
    ("attestation", ATTEST),
    ("provenance", PROV()),
  ]),
  ["erasure_id", "subject_ref", "completed_at", "keys_destroyed", "attestation", "provenance"],
  "gateway", "GW-XMPL-ID-01", "asset:gateway:GW-XMPL-ID-01",
  {"erasure_id": "ERA-2026-09-07-0021",
   "subject_ref": {"pid": pid("identity", 3, "traveller-c"), "epoch": 3},
   "completed_at": "2026-09-07T09:14:22.000Z", "keys_destroyed": 6,
   "attestation": {"digest_alg": "sha-256",
                   "digest": "c41d8f0a2b7e6539d0148ab3ce9207f61b45de88a3072cc5194ef60b7d2a3841",
                   "signer": "kms.xmpl.gov"},
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-09-07T09:14:22.700Z"}},
  {"erasure_id": "ERA-2026-09-07-0021",
   "subject_ref": {"pid": pid("identity", 3, "traveller-c"), "epoch": 3},
   "completed_at": "2026-09-07T09:14:22.000Z", "keys_destroyed": 6,
   "attestation": {"digest_alg": "sha-256",
                   "digest": "c41d8f0a2b7e6539d0148ab3ce9207f61b45de88a3072cc5194ef60b7d2a3841",
                   "signer": "kms.xmpl.gov"},
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-09-07T09:14:22.700Z", "method": "kms-destroy"}})

E("identity", "erasure-attested", "audit", False, False,
  "Durable proof that an erasure was performed. Audit class, seven years, no "
  "erasure path, and no subject reference. Evidential retention is per tenant "
  "policy, so the erasure record naming the subject can itself expire; proof that "
  "the erasure happened has to outlive it. The erasure_id is the join, and it "
  "resolves to a person only while the evidential record survives - which is the "
  "correct decay.",
  ["identity-gateway"],
  OD([
    ("erasure_id", sid("Erasure being attested. The join to the evidential record.")),
    ("outcome", oe(["completed", "partial", "failed"], "Outcome of the erasure.")),
    ("keys_destroyed", integer("Number of data keys destroyed.", minimum=0)),
    ("attested_at", ts("When the attestation was made.")),
    ("principal", PRINCIPAL("Principal attesting the erasure.")),
    ("provenance", PROV()),
  ]),
  ["erasure_id", "outcome", "attested_at", "principal", "provenance"],
  "gateway", "GW-XMPL-ID-01", "asset:gateway:GW-XMPL-ID-01",
  {"erasure_id": "ERA-2026-09-07-0021", "outcome": "completed",
   "attested_at": "2026-09-07T09:14:23.000Z", "principal": "kms.xmpl.gov",
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-09-07T09:14:23.050Z"}},
  {"erasure_id": "ERA-2026-09-07-0021", "outcome": "completed", "keys_destroyed": 6,
   "attested_at": "2026-09-07T09:14:23.000Z", "principal": "kms.xmpl.gov",
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-09-07T09:14:23.050Z", "method": "kms-destroy"}})

E("identity", "consent-granted", "evidential", True, False,
  "A subject granted consent for a purpose. Evidential rather than operational: a "
  "consent record has to outlive a seven-day window to be evidence of anything.",
  ["identity-gateway"],
  OD([
    ("subject_ref", SUBJ_I("Subject granting consent.")),
    ("consent_id", sid("Consent identifier, stable across grant and withdrawal.")),
    ("purpose_code", PURPOSE()),
    ("granted_at", ts("When consent was given.")),
    ("expires_at", ts("When consent lapses if not renewed.")),
    ("evidence", sealed("Record of how consent was captured, sealed under the subject's data "
                        "key so that erasure reaches it.")),
    ("provenance", PROV()),
  ]),
  ["subject_ref", "consent_id", "purpose_code", "granted_at", "provenance"],
  "gateway", "GW-XMPL-ID-01", "asset:gateway:GW-XMPL-ID-01",
  {"subject_ref": {"pid": pid("identity", 3, "traveller-b"), "epoch": 3},
   "consent_id": "CON-2026-04-02-0918", "purpose_code": "ASSISTED-TRAVEL",
   "granted_at": "2026-04-02T10:31:00.000Z",
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-04-02T10:31:00.220Z"}},
  {"subject_ref": {"pid": pid("identity", 3, "traveller-b"), "epoch": 3},
   "consent_id": "CON-2026-04-02-0918", "purpose_code": "ASSISTED-TRAVEL",
   "granted_at": "2026-04-02T10:31:00.000Z",
   "expires_at": "2027-04-02T00:00:00.000Z", "evidence": seal("consent-b"),
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-04-02T10:31:00.220Z", "method": "consent-portal"}})

E("identity", "consent-withdrawn", "evidential", True, False,
  "A previously granted consent was withdrawn or lapsed. Terminal for the "
  "`consent_id`. Withdrawal does not by itself trigger erasure; that is a separate "
  "request with its own basis.",
  ["identity-gateway"],
  OD([
    ("subject_ref", SUBJ_I("Subject whose consent ended.")),
    ("consent_id", sid("Consent being withdrawn. Matches a prior consent-granted.")),
    ("withdrawn_at", ts("When the consent ended.")),
    ("reason", oe(["data-subject-request", "expiry", "superseded", "purpose-ended"],
                  "Why the consent ended.")),
    ("provenance", PROV()),
  ]),
  ["subject_ref", "consent_id", "withdrawn_at", "provenance"],
  "gateway", "GW-XMPL-ID-01", "asset:gateway:GW-XMPL-ID-01",
  {"subject_ref": {"pid": pid("identity", 3, "traveller-b"), "epoch": 3},
   "consent_id": "CON-2026-04-02-0918", "withdrawn_at": "2026-09-07T11:02:00.000Z",
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-09-07T11:02:00.310Z"}},
  {"subject_ref": {"pid": pid("identity", 3, "traveller-b"), "epoch": 3},
   "consent_id": "CON-2026-04-02-0918", "withdrawn_at": "2026-09-07T11:02:00.000Z",
   "reason": "data-subject-request",
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-09-07T11:02:00.310Z", "method": "consent-portal"}})


# ============================================================ identity: OAuth 2.1 and OIDC (SPEC 14)
# Two rules shape every event here. No event carries both a subject reference and
# a client or sector reference (14.7): sectors follow domain boundaries, so the
# pair links a pseudonymous resident to a service domain by inference. And what
# was granted is sealed rather than published, because a Blume scope name can be
# domain-shaped - `blume.assistance` beside a pseudonym places that person in the
# small, special-category-adjacent population of assistance users.

CLIENT_ID = lambda desc: OD([("type", "string"), ("pattern", "^[a-z0-9][a-z0-9._-]{1,63}$"),
                             ("description", desc)])
REDIRECT_URI = OD([
    ("type", "string"),
    ("pattern", "^(https://[a-zA-Z0-9.-]+(:[0-9]{1,5})?(/[^*\\s]*)?|http://127\\.0\\.0\\.1(:[0-9]{1,5})?(/[^*\\s]*)?)$"),
    ("maxLength", 512),
    ("description", "Registered redirect URI. HTTPS, or loopback for a native client. The "
                    "pattern excludes `*`, which makes SPEC 14.2's prohibition on wildcard "
                    "redirect URIs a validation failure rather than a review comment."),
])
SERVICE_CLASS = lambda: oe(["self-service", "assisted", "machine"],
                           "Whether a human intermediary was involved. Deliberately coarse: a "
                           "vocabulary as fine as the sector would be the sector, and sectors "
                           "follow domain boundaries. Every class MUST appear in at least two "
                           "sectors before it may be used on a subject-linked event.")

E("identity", "oauth-client-registered", "audit", False, False,
  "A relying party was registered with the authorisation server.",
  ["identity-gateway"],
  OD([
    ("client_id", CLIENT_ID("Registered client identifier.")),
    ("sector", sid("Sector the client belongs to. Sector assignment follows domain boundaries: "
                   "a transit relying party and a vision relying party are never in one sector.")),
    ("client_type", oe(["public", "confidential"], "Client type.")),
    ("grant_types", arr(oe(["authorization-code", "client-credentials", "device-code",
                            "refresh-token"],
                           "Grant type. The implicit grant and ROPC are prohibited and are "
                           "therefore not representable."),
                        "Grant types the client is registered for.", minItems=1)),
    ("token_endpoint_auth_method", oe(["private-key-jwt", "tls-client-auth", "client-secret-basic", "none"],
                                      "Client authentication method. `none` is permitted only for a "
                                      "public client using both PKCE and DPoP.")),
    ("redirect_uris", arr(REDIRECT_URI, "Registered redirect URIs.", maxItems=32)),
    ("principal", PRINCIPAL("Principal that performed the registration.")),
    ("registered_at", ts("When the client was registered.")),
    ("provenance", PROV()),
  ]),
  ["client_id", "sector", "client_type", "grant_types", "token_endpoint_auth_method",
   "principal", "registered_at", "provenance"],
  "gateway", "GW-XMPL-ID-01", "asset:gateway:GW-XMPL-ID-01",
  {"client_id": "transit-account-web", "sector": "transit-resident", "client_type": "public",
   "grant_types": ["authorization-code", "refresh-token"], "token_endpoint_auth_method": "none",
   "principal": "platform.xmpl.gov", "registered_at": "2026-05-14T09:20:00.000Z",
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-05-14T09:20:00.310Z"}},
  {"client_id": "transit-account-web", "sector": "transit-resident", "client_type": "public",
   "grant_types": ["authorization-code", "refresh-token"], "token_endpoint_auth_method": "none",
   "redirect_uris": ["https://account.transit.xmpl.gov/callback", "http://127.0.0.1:7890/callback"],
   "principal": "platform.xmpl.gov", "registered_at": "2026-05-14T09:20:00.000Z",
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-05-14T09:20:00.310Z", "method": "registration-console"}})

E("identity", "oauth-client-updated", "audit", False, False,
  "A registered relying party's configuration changed. Names the fields that "
  "changed rather than their values: a redirect URI or an auth method changing is "
  "the auditable fact, and the current values are in the client register.",
  ["identity-gateway"],
  OD([
    ("client_id", CLIENT_ID("Client that was updated.")),
    ("changed_fields", arr(oe(["redirect_uris", "grant_types", "token_endpoint_auth_method",
                               "sector", "scopes", "jwks", "contacts"],
                              "Configuration field that changed."),
                           "Fields that changed.", minItems=1)),
    ("principal", PRINCIPAL("Principal that performed the update.")),
    ("updated_at", ts("When the update took effect.")),
    ("provenance", PROV()),
  ]),
  ["client_id", "changed_fields", "principal", "updated_at", "provenance"],
  "gateway", "GW-XMPL-ID-01", "asset:gateway:GW-XMPL-ID-01",
  {"client_id": "transit-account-web", "changed_fields": ["redirect_uris"],
   "principal": "platform.xmpl.gov", "updated_at": "2026-08-01T11:04:00.000Z",
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-08-01T11:04:00.140Z"}},
  {"client_id": "transit-account-web", "changed_fields": ["redirect_uris", "jwks"],
   "principal": "platform.xmpl.gov", "updated_at": "2026-08-01T11:04:00.000Z",
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-08-01T11:04:00.140Z", "method": "registration-console"}})

E("identity", "oauth-client-revoked", "audit", False, False,
  "A relying party's registration was revoked. Terminal for the client id; "
  "outstanding grants to it are revoked separately and per subject.",
  ["identity-gateway"],
  OD([
    ("client_id", CLIENT_ID("Client that was revoked.")),
    ("reason", oe(["operator", "compromise", "expiry", "superseded", "contract-end"],
                  "Why the registration was revoked.")),
    ("principal", PRINCIPAL("Principal that performed the revocation.")),
    ("revoked_at", ts("When the registration was revoked.")),
    ("provenance", PROV()),
  ]),
  ["client_id", "reason", "principal", "revoked_at", "provenance"],
  "gateway", "GW-XMPL-ID-01", "asset:gateway:GW-XMPL-ID-01",
  {"client_id": "depot-terminal-legacy", "reason": "superseded",
   "principal": "platform.xmpl.gov", "revoked_at": "2026-09-01T00:00:00.000Z",
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-09-01T00:00:00.220Z"}},
  {"client_id": "depot-terminal-legacy", "reason": "superseded",
   "principal": "platform.xmpl.gov", "revoked_at": "2026-09-01T00:00:00.000Z",
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-09-01T00:00:00.220Z", "method": "registration-console"}})

E("identity", "oauth-signing-key-rotated", "audit", False, False,
  "A token signing key was rotated. Relying parties refetch the JWKS; the "
  "retiring key stays published until `retires_at` so tokens in flight verify.",
  ["identity-gateway"],
  OD([
    ("kid", sid("Key identifier now signing.")),
    ("algorithm", oe(["ES256", "ES384", "RS256", "EdDSA"],
                     "Signature algorithm. `none` is prohibited by SPEC 14.2 and is therefore "
                     "not representable here.")),
    ("previous_kid", sid("Key being retired. Absent on first issue.")),
    ("effective_at", ts("When the new key began signing.")),
    ("retires_at", ts("When the previous key stops being published in the JWKS.")),
    ("provenance", PROV()),
  ]),
  ["kid", "algorithm", "effective_at", "provenance"],
  "gateway", "GW-XMPL-ID-01", "asset:gateway:GW-XMPL-ID-01",
  {"kid": "sig-2026-09", "algorithm": "ES256", "effective_at": "2026-09-01T00:00:00.000Z",
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-09-01T00:00:00.080Z"}},
  {"kid": "sig-2026-09", "algorithm": "ES256", "previous_kid": "sig-2026-06",
   "effective_at": "2026-09-01T00:00:00.000Z", "retires_at": "2026-09-08T00:00:00.000Z",
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-09-01T00:00:00.080Z", "method": "kms-rotate"}})

E("identity", "authentication-aggregated", "audit", False, False,
  "Hourly count of authentication outcomes by client. This absorbs what was a "
  "per-authentication event. Nothing consumed the per-event form: domain systems "
  "learn what they need from oauth-grant-authorised, and the gateway's own "
  "security monitoring reads its internal log faster than a bus round trip. Worse, "
  "a per-subject authentication event and an aggregate keyed by client are "
  "individually compliant and jointly not - joined on timestamp they reconstruct "
  "the (subject, client) pair 14.7 forbids. The bus carries authentication "
  "anomalies, oauth-refresh-reuse-detected and oauth-session-terminated; the "
  "aggregate carries the base rate. Not prefixed `oauth-`: it covers federated "
  "staff authentication too, which is OIDC upstream rather than OAuth issuance.",
  ["identity-gateway"],
  OD([
    ("client_id", CLIENT_ID("Client the attempts were made against.")),
    ("outcome", oe(["success", "failure-credentials", "failure-locked", "failure-mfa",
                    "failure-unknown-principal", "failure-expired", "failure-federation"],
                   "Outcome the bucket counts.")),
    ("count", integer("Attempts in the window. Floored at 5; a smaller bucket is suppressed "
                      "entirely, because a client with a single operator makes a count of one "
                      "a record about that person.", minimum=5)),
    ("aggregate", agg("Bucket, identity and revision of this figure.")),
    ("provenance", PROV()),
  ]),
  ["client_id", "outcome", "count", "aggregate", "provenance"],
  "gateway", "GW-XMPL-ID-01", "asset:gateway:GW-XMPL-ID-01",
  {"client_id": "transit-account-web", "outcome": "success", "count": 3412,
   "aggregate": {"aggregate_id": "auth-transit-account-web-success", "window": "2026-09-07T08Z", "revision": 0},
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-09-07T09:05:00.000Z"}},
  {"client_id": "transit-account-web", "outcome": "failure-credentials", "count": 118,
   "aggregate": {"aggregate_id": "auth-transit-account-web-failure-credentials", "window": "2026-09-07T08Z", "revision": 1},
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-09-07T09:05:00.640Z", "method": "batch-rollup"}},
  xagg=xagg("count"))

E("identity", "oauth-grant-authorised", "evidential", True, False,
  "A subject authorised a grant to a relying party. Carries no client id and no "
  "sector: a pseudonymous resident beside the service they authenticated to links "
  "a person to a domain by inference, and sectors follow domain boundaries. "
  "`service_class` carries the fraud- and support-relevant part - whether a human "
  "intermediary was involved - at a granularity that cannot reconstruct the "
  "client. Scopes are sealed rather than published, because a scope name can be "
  "domain-shaped and places the subject in a small population.",
  ["identity-gateway"],
  OD([
    ("subject_ref", SUBJ_I("Subject that authorised the grant.")),
    ("grant_id", sid("Grant identifier. The join to revocation and reuse detection.")),
    ("service_class", SERVICE_CLASS()),
    ("scopes", sealed("Scopes granted, sealed under the subject's data key so that erasure "
                      "reaches them and a passive stream holder cannot read them.")),
    ("authorised_at", ts("When the subject authorised the grant.")),
    ("expires_at", ts("When the grant chain expires if not refreshed.")),
    ("provenance", PROV()),
  ]),
  ["subject_ref", "grant_id", "service_class", "authorised_at", "provenance"],
  "gateway", "GW-XMPL-ID-01", "asset:gateway:GW-XMPL-ID-01",
  {"subject_ref": {"pid": pid("identity", 3, "traveller-b"), "epoch": 3},
   "grant_id": "GR-3-4a1c88f0", "service_class": "self-service",
   "authorised_at": "2026-09-07T08:15:31.000Z",
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-09-07T08:15:31.120Z"}},
  {"subject_ref": {"pid": pid("identity", 3, "traveller-b"), "epoch": 3},
   "grant_id": "GR-3-4a1c88f0", "service_class": "self-service",
   "scopes": seal("grant-4a1c88f0-scopes"),
   "authorised_at": "2026-09-07T08:15:31.000Z", "expires_at": "2027-09-07T08:15:31.000Z",
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-09-07T08:15:31.120Z", "method": "authorization-code"}})

E("identity", "oauth-grant-revoked", "evidential", True, False,
  "A grant chain was revoked. `resident_initiated` is carried explicitly rather "
  "than inferred from `reason`, because whether the data subject asked is the "
  "legally significant fact and should not require reading an enum correctly.",
  ["identity-gateway"],
  OD([
    ("subject_ref", SUBJ_I("Subject whose grant was revoked.")),
    ("grant_id", sid("Grant being revoked. Matches a prior oauth-grant-authorised.")),
    ("reason", oe(["resident-initiated", "operator", "erasure", "expiry", "reuse-detected",
                   "consent-withdrawn", "client-revoked"], "Why the grant was revoked.")),
    ("resident_initiated", boolean("True when the data subject asked. Carried explicitly "
                                   "because it is the legally significant fact.")),
    ("scopes", sealed("Scopes that were revoked, sealed as at authorisation time.")),
    ("revoked_at", ts("When the grant was revoked.")),
    ("provenance", PROV()),
  ]),
  ["subject_ref", "grant_id", "reason", "resident_initiated", "revoked_at", "provenance"],
  "gateway", "GW-XMPL-ID-01", "asset:gateway:GW-XMPL-ID-01",
  {"subject_ref": {"pid": pid("identity", 3, "traveller-b"), "epoch": 3},
   "grant_id": "GR-3-4a1c88f0", "reason": "resident-initiated", "resident_initiated": True,
   "revoked_at": "2026-09-07T11:02:00.000Z",
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-09-07T11:02:00.410Z"}},
  {"subject_ref": {"pid": pid("identity", 3, "traveller-b"), "epoch": 3},
   "grant_id": "GR-3-4a1c88f0", "reason": "resident-initiated", "resident_initiated": True,
   "scopes": seal("grant-4a1c88f0-scopes"), "revoked_at": "2026-09-07T11:02:00.000Z",
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-09-07T11:02:00.410Z", "method": "consent-portal"}})

E("identity", "oauth-refresh-reuse-detected", "evidential", True, True,
  "A refresh token was presented after it had already been redeemed. Inferred, "
  "and it carries confidence: a replay is usually an attack and is sometimes a "
  "client retrying across a dropped connection, and the two are not distinguishable "
  "at the point of detection. The chain is revoked either way - failing closed on "
  "a retry costs a re-authentication, failing open on an attack costs the account.",
  ["identity-gateway"],
  OD([
    ("subject_ref", SUBJ_I("Subject whose grant chain was replayed.")),
    ("grant_id", sid("Grant chain the replayed token belonged to.")),
    ("chain_revoked", boolean("Whether the whole grant chain was revoked in response.")),
    ("tokens_revoked", integer("Tokens invalidated by the chain revocation.", minimum=0)),
    ("detected_at", ts("When the replay was detected.")),
    ("provenance", PROV_INF()),
  ]),
  ["subject_ref", "grant_id", "chain_revoked", "detected_at", "provenance"],
  "gateway", "GW-XMPL-ID-01", "asset:gateway:GW-XMPL-ID-01",
  {"subject_ref": {"pid": pid("identity", 3, "traveller-c"), "epoch": 3},
   "grant_id": "GR-3-9d02be71", "chain_revoked": True,
   "detected_at": "2026-09-07T12:41:09.000Z",
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-09-07T12:41:09.030Z", "confidence": 0.82}},
  {"subject_ref": {"pid": pid("identity", 3, "traveller-c"), "epoch": 3},
   "grant_id": "GR-3-9d02be71", "chain_revoked": True, "tokens_revoked": 4,
   "detected_at": "2026-09-07T12:41:09.000Z",
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-09-07T12:41:09.030Z", "confidence": 0.82,
                  "method": "refresh-rotation"}})

E("identity", "oauth-session-terminated", "operational", True, False,
  "A subject's session ended. Operational because relying parties and domain "
  "systems act on it now, dropping cached state to match the back-channel logout "
  "the gateway delivers over HTTP.",
  ["identity-gateway"],
  OD([
    ("subject_ref", SUBJ_I("Subject whose session ended.")),
    ("session_id", sid("Session that ended. Random, and not derivable from the subject.")),
    ("reason", oe(["resident-initiated", "back-channel-logout", "expiry", "revocation",
                   "erasure", "reauthentication-required"], "Why the session ended.")),
    ("terminated_at", ts("When the session ended.")),
    ("provenance", PROV()),
  ]),
  ["subject_ref", "session_id", "reason", "terminated_at", "provenance"],
  "gateway", "GW-XMPL-ID-01", "asset:gateway:GW-XMPL-ID-01",
  {"subject_ref": {"pid": pid("identity", 3, "traveller-b"), "epoch": 3},
   "session_id": "s-6b1f0c9a77e5d421", "reason": "resident-initiated",
   "terminated_at": "2026-09-07T11:02:01.000Z",
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-09-07T11:02:01.070Z"}},
  {"subject_ref": {"pid": pid("identity", 3, "traveller-b"), "epoch": 3},
   "session_id": "s-6b1f0c9a77e5d421", "reason": "back-channel-logout",
   "terminated_at": "2026-09-07T11:02:01.000Z",
   "provenance": {"producer": "identity-gateway/1.0.0", "node": "core-xmpl-id-01",
                  "observed_at": "2026-09-07T11:02:01.070Z", "method": "logout-dispatch"}})

# ============================================================ emit
OCCURRENCE_KEYS = [
    "changed_at", "detected_at", "classified_at", "validated_at", "checked_at",
    "requested_at", "declared_at", "cleared_at", "cancelled_at", "granted_at",
    "withdrawn_at", "evaluated_at", "issued_at", "applied_at", "sealed_at",
    "performed_at", "recorded_at", "attested_at", "completed_at", "restored_at",
    "arrived_at", "departed_at", "effective_at", "first_seen_at", "started_at",
    "observed_at_stop", "window_start",
]
# The envelope `time` is the time the fact occurred, not the time it was
# published. Where a store-and-forward outage separates the two, `time` stays put
# and provenance.observed_at records the later observation.
VERSION = {("traffic", "signal-plan-activated"): "1.1.0"}
def ver(ev):
    return VERSION.get((ev["domain"], ev["name"]), "1.0.0")
TIME_OVERRIDE = {("traffic", "signal-phase-changed"): "2026-09-07T14:02:11.417Z"}

def occurrence_time(ev, data):
    o = TIME_OVERRIDE.get((ev["domain"], ev["name"]))
    if o:
        return o
    if "aggregate" in data:
        w = data["aggregate"]["window"]
        return (w[:-1] + ":00:00.000Z") if "T" in w else (w[:-1] + "T00:00:00.000Z")
    for k in OCCURRENCE_KEYS:
        if k in data:
            return data[k]
    return data["provenance"]["observed_at"]

def title(name):
    return "".join(p.capitalize() for p in name.split("-"))

def envelope(ev, kind, data):
    seed = "%s/%s/%s" % (ev["domain"], ev["name"], kind)
    e = OD()
    e["specversion"] = "1.0"
    e["id"] = ulid(seed)
    e["source"] = "//blume.systems/xmpl/%s/%s/%s" % (ev["domain"], ev["src_class"], ev["src_id"])
    e["type"] = "systems.blume.%s.%s.v1" % (ev["domain"], ev["name"])
    if kind == "full" and ev["ce_subject"]:
        e["subject"] = ev["ce_subject"]
    e["time"] = occurrence_time(ev, data)
    e["datacontenttype"] = "application/json"
    e["dataschema"] = "https://schemas.blume.systems/%s/%s/%s.json" % (ev["domain"], ev["name"], ver(ev))
    e["blumetenant"] = "xmpl"
    e["blumeretention"] = ev["retention"]
    e["blumetrace"] = trace(seed)
    e["blumeseq"] = 10000 + (int(hashlib.sha256(seed.encode()).hexdigest()[:6], 16) % 90000)
    e["data"] = data
    return e

def write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(json.dumps(obj, indent=2, ensure_ascii=True) + "\n")

import textwrap
DOMAIN_ORDER = ["traffic", "telemetry", "transit", "vision", "identity"]
EVENTS.sort(key=lambda e: (DOMAIN_ORDER.index(e["domain"]), e["name"]))

catalog = [
    "# blume-events catalog",
    "#",
    "# Every registered event, one entry each. The machine-readable index and the",
    "# input to codegen. `beb-lint` requires that every entry resolves to a schema on",
    "# disk, that the major token in `type` equals the major of the schema semantic",
    "# version, that `subject_linked` agrees with the schema's transitive $ref graph,",
    "# that `retention` is consistent with that graph, and that `inferred: true`",
    "# implies provenance.confidence is required at the event's own reference site.",
    "#",
    "# Domains in the order of SPEC section 1. Generated code is derived from this",
    "# file and from the schemas it names; neither is hand-edited downstream.",
    "",
]
cur = None
for ev in EVENTS:
    if ev["domain"] != cur:
        cur = ev["domain"]
        catalog.append("# ---------------------------------------------------------------- %s" % cur)
    body = " ".join(ev["description"].split())
    wrapped = textwrap.fill(body, width=74, initial_indent="    ", subsequent_indent="    ")
    catalog.append("- type: systems.blume.%s.%s.v1" % (ev["domain"], ev["name"]))
    catalog.append("  domain: %s" % ev["domain"])
    catalog.append("  schema: %s/%s/%s.json" % (ev["domain"], ev["name"], ver(ev)))
    catalog.append("  retention: %s" % ev["retention"])
    catalog.append("  subject_linked: %s" % ("true" if ev["subject_linked"] else "false"))
    catalog.append("  inferred: %s" % ("true" if ev["inferred"] else "false"))
    catalog.append("  description: >")
    catalog.append(wrapped)
    catalog.append("  producers: [%s]" % ", ".join(ev["producers"]))
    catalog.append("")

for ev in EVENTS:
    base = os.path.join(ROOT, "schemas", ev["domain"], ev["name"])
    schema = OD([
        ("$schema", "https://json-schema.org/draft/2020-12/schema"),
        ("$id", "https://schemas.blume.systems/%s/%s/%s.json" % (ev["domain"], ev["name"], ver(ev))),
        ("title", title(ev["name"])),
        ("description", " ".join(ev["description"].split())),
        ("type", "object"),
        ("properties", ev["props"]),
        ("required", ev["required"]),
    ])
    if ev["xagg"]:
        schema["x-beb-aggregate"] = ev["xagg"]
    write(os.path.join(base, ver(ev) + ".json"), schema)
    write(os.path.join(base, "examples", "minimal.json"), envelope(ev, "minimal", ev["minimal"]))
    write(os.path.join(base, "examples", "full.json"), envelope(ev, "full", ev["full"]))

with open(os.path.join(ROOT, "catalog.yaml"), "w") as f:
    f.write("\n".join(catalog).rstrip() + "\n")

print("events: %d" % len(EVENTS))
for d in DOMAIN_ORDER:
    print("  %-10s %d" % (d, sum(1 for e in EVENTS if e["domain"] == d)))
