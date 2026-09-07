package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// R16: common value types are closed. A member smuggled in beside a pseudonym
// must fail validation rather than ride along. geo.json is exempt at the root
// because it composes two closed $defs.
func (l *linter) checkCommonTypes() {
	for id, d := range l.docs {
		if !strings.HasPrefix(id, commonPrefix) || id == geoID {
			continue
		}
		m, _ := obj(d)
		if ap, ok := m["additionalProperties"]; !ok || ap != false {
			l.add("R16", l.paths[id], "common value type must set additionalProperties: false")
		}
	}
	if g, ok := obj(l.docs[geoID]); ok {
		defs, _ := obj(g["$defs"])
		for _, name := range []string{"precise", "coarse"} {
			d, ok := obj(defs[name])
			if !ok {
				l.add("R16", l.paths[geoID], "missing $defs/%s", name)
				continue
			}
			if ap, ok := d["additionalProperties"]; !ok || ap != false {
				l.add("R16", l.paths[geoID], "$defs/%s must set additionalProperties: false", name)
			}
		}
	}
}

// R18: a reference site may narrow a common type and may never widen one.
// "Widen" is not decidable in general, so the rule is an allow-list: only
// keywords that cannot widen may sit beside a $ref, and any property named at a
// reference site must already exist in the type being referenced.
func (l *linter) checkNarrowing() {
	for id, d := range l.docs {
		if strings.HasPrefix(id, commonPrefix) {
			continue
		}
		target := l.paths[id]
		var walk func(node any, path string)
		check := func(site map[string]any, refID, path string) {
			for k := range site {
				if !narrowingKeywords[k] {
					l.add("R18", target, "at %s: %q may not appear beside a $ref to %s; a reference site narrows and never widens",
						path, k, strings.TrimPrefix(refID, commonPrefix))
				}
			}
			props, _ := obj(site["properties"])
			if len(props) == 0 {
				return
			}
			refDoc, ok := obj(l.docs[refID])
			if !ok {
				return
			}
			refProps, _ := obj(refDoc["properties"])
			for name := range props {
				if _, exists := refProps[name]; !exists {
					l.add("R18", target, "at %s: property %q is not declared by %s; a reference site cannot add members to a closed type",
						path, name, strings.TrimPrefix(refID, commonPrefix))
				}
			}
		}
		walk = func(node any, path string) {
			switch v := node.(type) {
			case map[string]any:
				if ref, ok := v["$ref"].(string); ok {
					base := ref
					if i := strings.Index(base, "#"); i >= 0 {
						base = base[:i]
					}
					if strings.HasPrefix(base, commonPrefix) {
						check(v, base, path)
					}
				}
				// allOf: [{$ref: common}, {constraints}] is the other spelling
				// of the same thing, and gets the same treatment.
				if members, ok := v["allOf"].([]any); ok {
					refID := ""
					for _, m := range members {
						if mm, ok := obj(m); ok {
							if r, ok := mm["$ref"].(string); ok {
								base := r
								if i := strings.Index(base, "#"); i >= 0 {
									base = base[:i]
								}
								if strings.HasPrefix(base, commonPrefix) {
									refID = base
								}
							}
						}
					}
					if refID != "" {
						for i, m := range members {
							mm, ok := obj(m)
							if !ok {
								continue
							}
							if _, isRef := mm["$ref"]; isRef {
								continue
							}
							check(mm, refID, fmt.Sprintf("%s/allOf/%d", path, i))
						}
					}
				}
				for k, val := range v {
					walk(val, path+"/"+k)
				}
			case []any:
				for i, val := range v {
					walk(val, fmt.Sprintf("%s/%d", path, i))
				}
			}
		}
		walk(d, "")
	}
}

// checkEntry runs every per-event rule for one catalog record.
func (l *linter) checkEntry(e Entry) {
	id := schemaPrefix + e.Schema
	rel := filepath.Join("schemas", e.Schema)

	// R04: schema semver major equals the type major token. SPEC section 9's
	// identity of "a major version" and "a new subject" holds only if they are
	// the same number.
	sm := semverInPath.FindStringSubmatch(e.Schema)
	tm := majorInType.FindStringSubmatch(e.Type)
	switch {
	case sm == nil:
		l.add("R04", e.Type, "schema path %s carries no semantic version", e.Schema)
	case tm == nil:
		l.add("R04", e.Type, "type carries no major token")
	case sm[1] != tm[1]:
		l.add("R04", e.Type, "type major v%s does not equal schema major %s", tm[1], sm[1])
	}

	// R05: type and schema path both name the catalogued domain.
	if !strings.HasPrefix(e.Type, "systems.blume."+e.Domain+".") {
		l.add("R05", e.Type, "type does not name domain %q", e.Domain)
	}
	if !strings.HasPrefix(e.Schema, e.Domain+"/") {
		l.add("R05", e.Type, "schema path is not under domain %q", e.Domain)
	}

	// R03: the entry resolves to a schema on disk.
	if _, ok := l.docs[id]; ok {
		if _, err := os.Stat(filepath.Join(l.root, rel)); err != nil {
			l.add("R03", e.Type, "schema %s: %v", e.Schema, err)
			return
		}
	} else {
		l.add("R03", e.Type, "schema %s does not resolve to a document on disk", e.Schema)
		return
	}

	graph := l.refGraph(id)
	hasSubject := graph[subjectRefID]

	// R06: subject_linked reflects the $ref graph, not the author's intent.
	if hasSubject != e.SubjectLinked {
		l.add("R06", e.Type, "subject_linked is %v but subject_ref in the $ref graph is %v", e.SubjectLinked, hasSubject)
	}
	// R07: anonymous domains.
	if hasSubject && anonymousDomains[e.Domain] {
		l.add("R07", e.Type, "subject_ref is banned in domain %s", e.Domain)
	}
	// R08: a pseudonym is personal data, so neither long-lived class may hold one.
	if hasSubject && (e.Retention == "analytical" || e.Retention == "audit") {
		l.add("R08", e.Type, "subject_ref is banned in retention class %s", e.Retention)
	}
	// R09: an hour-scoped per-person handle in a 90-day store reconstructs what
	// the hour scoping prevents.
	if graph[trackRefID] && e.Retention == "analytical" {
		l.add("R09", e.Type, "track_ref is banned in analytical retention")
	}
	// R10: the entry is well formed.
	switch e.Retention {
	case "operational", "analytical", "evidential", "audit":
	default:
		l.add("R10", e.Type, "unknown retention class %q", e.Retention)
	}
	if len(e.Producers) == 0 {
		l.add("R10", e.Type, "declares no producers")
	}
	if strings.TrimSpace(e.Description) == "" {
		l.add("R10", e.Type, "has an empty description")
	}

	doc, _ := obj(l.docs[id])
	props, _ := obj(doc["properties"])
	required := map[string]bool{}
	for _, r := range strs(doc["required"]) {
		required[r] = true
	}

	// R11: provenance is required on every event in every domain.
	if _, ok := props["provenance"]; !ok {
		l.add("R11", e.Type, "declares no provenance property")
	} else if !required["provenance"] {
		l.add("R11", e.Type, "does not require provenance")
	}

	// R12: inferred implies confidence is required at the reference site.
	if pv, ok := obj(props["provenance"]); ok {
		confidenceRequired := false
		for _, r := range strs(pv["required"]) {
			if r == "confidence" {
				confidenceRequired = true
			}
		}
		if e.Inferred != confidenceRequired {
			l.add("R12", e.Type, "inferred is %v but provenance requires confidence: %v", e.Inferred, confidenceRequired)
		}
	}

	// R13: a 30-minute domestic read keyed by meter identifier is personal data
	// whether or not it carries a pseudonym.
	if e.Domain == "telemetry" && e.Retention == "analytical" && graph[assetRefID] {
		narrowed := false
		if ar, ok := obj(props["asset_ref"]); ok {
			if p, ok := obj(ar["properties"]); ok {
				if cl, ok := obj(p["class"]); ok {
					if classes := strs(cl["enum"]); len(classes) > 0 {
						narrowed = true
						for _, c := range classes {
							if c == "meter" {
								narrowed = false
							}
						}
					}
				}
			}
		}
		if !narrowed {
			l.add("R13", e.Type, "analytical telemetry admits an asset_ref of class meter; narrow the class or key on cell")
		}
	}

	// R14: analytical schemas reference coarse geo only, so exact coordinates
	// are unrepresentable rather than stripped by convention.
	if e.Retention == "analytical" {
		raw, _ := os.ReadFile(filepath.Join(l.root, rel))
		for _, bad := range []string{`"` + geoID + `"`, `"` + geoID + `#/$defs/precise"`} {
			if strings.Contains(string(raw), bad) {
				l.add("R14", e.Type, "analytical schema references %s; use geo.json#/$defs/coarse", bad)
			}
		}
	}

	// R15: event data schemas stay open, so that adding an optional field stays
	// backward compatible for a consumer pinned to an older minor.
	if _, closed := doc["additionalProperties"]; closed {
		l.add("R15", e.Type, "event data schema sets additionalProperties; adding an optional field would then break a pinned consumer")
	}

	// R17: every enum carries the open marker required by SPEC section 9.
	for _, p := range findEnums(doc) {
		if !p.marked {
			l.add("R17", e.Type, "enum at %s has no x-beb-enum marker", p.path)
		}
	}

	l.checkAggregate(e, doc, props, required, graph)
	l.checkExamples(e, id, rel)
}
