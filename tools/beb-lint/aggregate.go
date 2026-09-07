package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// asInt coerces a JSON number to an int. jsonschema.UnmarshalJSON preserves
// numbers as json.Number so that canonical serialisation is lossless, so a
// plain float64 assertion silently reads every number as zero.
func asInt(v any) (int, bool) {
	switch n := v.(type) {
	case json.Number:
		i, err := n.Int64()
		return int(i), err == nil
	case float64:
		return int(n), true
	case int:
		return n, true
	}
	return 0, false
}

type enumSite struct {
	path   string
	marked bool
}

func findEnums(node any) []enumSite {
	var out []enumSite
	var walk func(any, string)
	walk = func(n any, path string) {
		switch v := n.(type) {
		case map[string]any:
			if _, ok := v["enum"]; ok {
				_, marked := v["x-beb-enum"]
				out = append(out, enumSite{path, marked})
			}
			keys := make([]string, 0, len(v))
			for k := range v {
				keys = append(keys, k)
			}
			sort.Strings(keys)
			for _, k := range keys {
				walk(v[k], path+"/"+k)
			}
		case []any:
			for i, val := range v {
				walk(val, fmt.Sprintf("%s/%d", path, i))
			}
		}
	}
	walk(node, "")
	return out
}

// checkAggregate enforces the disjoint-window construction.
//
// A k-anonymity floor protects each published figure and does nothing about the
// arithmetic between them: two aggregates over 14:00-15:00 and 14:00-14:30, both
// above the floor, subtract to a bucket that may hold one person. The floor is
// therefore paired with windows that cannot overlap, which is why an aggregate
// names a bucket rather than a start and an end.
//
// R19: an analytical event is an aggregate and declares itself one.
// R20: the declaration is coherent and leaves no differencing channel.
func (l *linter) checkAggregate(e Entry, doc, props map[string]any, required map[string]bool, graph map[string]bool) {
	decl, declared := obj(doc["x-beb-aggregate"])

	if e.Retention == "analytical" {
		if !declared {
			l.add("R19", e.Type, "analytical events are aggregates and must declare x-beb-aggregate")
		}
		if !graph[aggregateID] {
			l.add("R19", e.Type, "analytical events must reference common/aggregate.json")
		}
	}
	if !declared {
		return
	}

	if !graph[aggregateID] {
		l.add("R20", e.Type, "declares x-beb-aggregate but does not reference common/aggregate.json")
	}
	if _, ok := props["aggregate"]; !ok {
		l.add("R20", e.Type, "declares x-beb-aggregate but has no aggregate property")
	} else if !required["aggregate"] {
		l.add("R20", e.Type, "does not require the aggregate property")
	}

	window, _ := decl["window"].(string)
	switch window {
	case "PT1H", "P1D":
	default:
		l.add("R20", e.Type, "x-beb-aggregate.window %q is not a supported bucket duration", window)
	}

	floor, hasFloor := asInt(decl["k_floor"])
	if !hasFloor || floor < 5 {
		l.add("R20", e.Type, "x-beb-aggregate.k_floor is %d; the floor is 5", floor)
	}

	countField, _ := decl["count_field"].(string)
	if countField == "" {
		l.add("R20", e.Type, "x-beb-aggregate declares no count_field")
	} else if cf, ok := obj(props[countField]); !ok {
		l.add("R20", e.Type, "count_field %q is not a declared property", countField)
	} else {
		if !required[countField] {
			l.add("R20", e.Type, "count_field %q is not required", countField)
		}
		min, has := asInt(cf["minimum"])
		if !has || min < floor {
			l.add("R20", e.Type, "count_field %q must set minimum >= %d so a below-floor bucket cannot be published", countField, floor)
		}
	}

	// An aggregate names a bucket. An author-chosen endpoint pair would permit
	// the overlapping windows the bucket exists to prevent.
	for name := range props {
		if endpointPair.MatchString(name) {
			l.add("R20", e.Type, "aggregate declares endpoint %q; a window is a bucket, and endpoints permit the overlap the bucket prevents", name)
		}
		// A suppressed bucket and an empty bucket must be indistinguishable.
		if suppressionMarker.MatchString(name) {
			l.add("R20", e.Type, "aggregate declares %q; a suppressed bucket is absent, not marked", name)
		}
	}
}

// checkExamples validates both examples of an event against the envelope and
// against the event's own data schema, and holds the minimal example to being
// minimal.
func (l *linter) checkExamples(e Entry, id, rel string) {
	env := l.compiled[envelopeID]
	data := l.compiled[id]
	if env == nil || data == nil {
		return
	}
	dir := filepath.Join(l.root, filepath.Dir(rel), "examples")
	for _, kind := range []string{"minimal", "full"} {
		p := filepath.Join(dir, kind+".json")
		short := filepath.Join(filepath.Dir(rel), "examples", kind+".json")
		inst, err := loadJSON(p)
		if err != nil {
			l.add("R21", short, "%v", err)
			continue
		}
		if err := env.Validate(inst); err != nil {
			l.add("R21", short, "does not validate against the envelope: %v", err)
			continue
		}
		m, _ := obj(inst)
		if m["type"] != e.Type {
			l.add("R21", short, "envelope type %v does not match catalog type %s", m["type"], e.Type)
		}
		if m["dataschema"] != id {
			l.add("R21", short, "dataschema %v does not match %s", m["dataschema"], id)
		}
		if m["blumeretention"] != e.Retention {
			l.add("R21", short, "blumeretention %v does not match catalog retention %s", m["blumeretention"], e.Retention)
		}
		if err := data.Validate(m["data"]); err != nil {
			l.add("R21", short, "data does not validate: %v", err)
			continue
		}
		// The bucket in the example must match the declared duration.
		if doc, ok := obj(l.docs[id]); ok {
			if decl, declared := obj(doc["x-beb-aggregate"]); declared {
				if d, ok := obj(m["data"]); ok {
					if aggv, ok := obj(d["aggregate"]); ok {
						w, _ := aggv["window"].(string)
						dur, _ := decl["window"].(string)
						hourly := strings.Contains(w, "T")
						if (dur == "PT1H") != hourly {
							l.add("R20", short, "window %q is not the %s bucket form", w, dur)
						}
					}
				}
			}
		}
		// R22: a minimal example carries required members only. Because data
		// schemas are open and changes are additive, an example minimal at
		// 1.0.0 stays minimal at 1.1.0, so this does not fight evolution.
		if kind != "minimal" {
			continue
		}
		d, ok := obj(m["data"])
		if !ok {
			continue
		}
		for k := range d {
			if k == "provenance" {
				continue
			}
			clone := map[string]any{}
			for kk, vv := range d {
				if kk != k {
					clone[kk] = vv
				}
			}
			if data.Validate(clone) == nil {
				l.add("R22", short, "carries optional member %q; a minimal example is minimal", k)
			}
		}
	}
}

// R23: SPEC section 12 - no example carries a field matching a known
// root-identifier pattern.
func (l *linter) checkExampleFields() {
	filepath.Walk(filepath.Join(l.root, "schemas"), func(p string, info os.FileInfo, err error) error {
		if err != nil || info.IsDir() || !strings.HasSuffix(p, ".json") {
			return err
		}
		if !strings.Contains(p, string(filepath.Separator)+"examples"+string(filepath.Separator)) {
			return nil
		}
		rel, _ := filepath.Rel(l.root, p)
		d, err := loadJSON(p)
		if err != nil {
			return nil
		}
		m, ok := obj(d)
		if !ok {
			return nil
		}
		var scan func(any, string)
		scan = func(n any, path string) {
			switch v := n.(type) {
			case map[string]any:
				keys := make([]string, 0, len(v))
				for k := range v {
					keys = append(keys, k)
				}
				sort.Strings(keys)
				for _, k := range keys {
					if rootIdentifier.MatchString(k) {
						l.add("R23", rel, "field %q at %s matches a root-identifier pattern", k, path+"/"+k)
					}
					scan(v[k], path+"/"+k)
				}
			case []any:
				for i, val := range v {
					scan(val, fmt.Sprintf("%s/%d", path, i))
				}
			}
		}
		scan(m["data"], "/data")
		return nil
	})
}
