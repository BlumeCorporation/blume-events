// Package main implements beb-lint, the schema compatibility gate.
//
// This file holds the structural rules: every schema parses and resolves, every
// catalog entry agrees with the schema it names, retention class agrees with the
// $ref graph rather than with the author's intent, and every example validates
// against both the envelope and its own data schema.
//
// Backward compatibility diffing against the previous published version on the
// same major (SPEC section 9) is M2 and is not implemented here. `beb-lint`
// reports the rules it ran, so a caller can see what was and was not checked.
package main

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"

	"github.com/goccy/go-yaml"
	"github.com/santhosh-tekuri/jsonschema/v6"
)

const (
	commonPrefix = "https://schemas.blume.systems/common/"
	schemaPrefix = "https://schemas.blume.systems/"
	envelopeID   = commonPrefix + "envelope.json"
	subjectRefID = commonPrefix + "subject_ref.json"
	trackRefID   = commonPrefix + "track_ref.json"
	assetRefID   = commonPrefix + "asset_ref.json"
	aggregateID  = commonPrefix + "aggregate.json"
	geoID        = commonPrefix + "geo.json"
)

// Finding is one rule violation. Rule is the stable identifier the table tests
// assert against; changing one is a breaking change to the test corpus.
type Finding struct {
	Rule    string
	Target  string
	Message string
}

func (f Finding) String() string {
	return fmt.Sprintf("%s %s: %s", f.Rule, f.Target, f.Message)
}

// Entry is one catalog.yaml record.
type Entry struct {
	Type          string   `yaml:"type"`
	Domain        string   `yaml:"domain"`
	Schema        string   `yaml:"schema"`
	Retention     string   `yaml:"retention"`
	SubjectLinked bool     `yaml:"subject_linked"`
	Inferred      bool     `yaml:"inferred"`
	Description   string   `yaml:"description"`
	Producers     []string `yaml:"producers"`
}

type linter struct {
	root     string
	docs     map[string]any
	paths    map[string]string
	compiled map[string]*jsonschema.Schema
	entries  []Entry
	findings []Finding
}

func (l *linter) add(rule, target, format string, a ...any) {
	l.findings = append(l.findings, Finding{rule, target, fmt.Sprintf(format, a...)})
}

// anonymousDomains carry no subject reference under any retention class.
var anonymousDomains = map[string]bool{"traffic": true, "telemetry": true, "vision": true}

var (
	semverInPath = regexp.MustCompile(`/([0-9]+)\.[0-9]+\.[0-9]+\.json$`)
	majorInType  = regexp.MustCompile(`\.v([0-9]+)$`)
	// SPEC section 12: no golden event carries a field matching a known
	// root-identifier pattern.
	rootIdentifier = regexp.MustCompile(`(?i)(^|_)(nhs|nino|passport|ssn|dob|email|phone|msisdn|imei|imsi|mac|name|surname|forename|address|postcode|plate|vrm|vrn|face|biometric|fingerprint|root_subject|subject_id|client_id|sector_id)($|_)`)
	// A suppressed bucket and an empty bucket must be indistinguishable, so an
	// aggregate has nowhere to record that suppression happened.
	suppressionMarker = regexp.MustCompile(`(?i)(suppress|redact|censor|masked|below_floor|withheld)`)
	// An aggregate window is a bucket, never an author-chosen endpoint pair.
	endpointPair = regexp.MustCompile(`^(period|window|range|interval)_(start|end|from|to)$`)
)

// narrowingKeywords may appear beside a $ref to a common type. Everything else
// is refused: SPEC section 9 permits a reference site to narrow a common type
// and never to widen one, and "widen" is not decidable in general, so the rule
// is an allow-list of keywords that cannot widen.
var narrowingKeywords = map[string]bool{
	"$ref": true, "description": true, "title": true, "required": true,
	"properties": true, "enum": true, "const": true, "x-beb-enum": true,
	"minimum": true, "maximum": true, "exclusiveMinimum": true, "exclusiveMaximum": true,
	"minLength": true, "maxLength": true, "pattern": true,
	"minItems": true, "maxItems": true, "multipleOf": true,
	"deprecated": true, "readOnly": true, "default": true, "examples": true,
}

func loadJSON(path string) (any, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	return jsonschema.UnmarshalJSON(strings.NewReader(string(b)))
}

func obj(v any) (map[string]any, bool) {
	m, ok := v.(map[string]any)
	return m, ok
}

func strs(v any) []string {
	arr, ok := v.([]any)
	if !ok {
		return nil
	}
	out := make([]string, 0, len(arr))
	for _, e := range arr {
		if s, ok := e.(string); ok {
			out = append(out, s)
		}
	}
	return out
}

// Check runs every structural rule over a repository root and returns the
// findings. A clean repository returns none.
func Check(root string) ([]Finding, error) {
	l := &linter{
		root:     root,
		docs:     map[string]any{},
		paths:    map[string]string{},
		compiled: map[string]*jsonschema.Schema{},
	}
	if err := l.load(); err != nil {
		return nil, err
	}
	l.compile()
	if err := l.loadCatalog(); err != nil {
		return nil, err
	}
	l.checkCommonTypes()
	l.checkNarrowing()
	for _, e := range l.entries {
		l.checkEntry(e)
	}
	l.checkExampleFields()
	sort.SliceStable(l.findings, func(i, j int) bool {
		if l.findings[i].Rule != l.findings[j].Rule {
			return l.findings[i].Rule < l.findings[j].Rule
		}
		return l.findings[i].Target < l.findings[j].Target
	})
	return l.findings, nil
}

// R01: every schema parses, carries a $id, and no two share one.
//
// Every published version is loaded, because every one must keep resolving: the
// registry is a static artifact and a dataschema URI that resolved once resolves
// forever. Only R01 and R02 apply to a superseded version, though. The
// structural rules run against the version the catalog names, because a
// published schema cannot be edited, and a rule tightened today must not
// retroactively fail a schema that was correct when it shipped.
func (l *linter) load() error {
	return filepath.Walk(filepath.Join(l.root, "schemas"), func(p string, info os.FileInfo, err error) error {
		if err != nil || info.IsDir() || !strings.HasSuffix(p, ".json") {
			return err
		}
		if strings.Contains(p, string(filepath.Separator)+"examples"+string(filepath.Separator)) {
			return nil
		}
		rel, _ := filepath.Rel(l.root, p)
		d, err := loadJSON(p)
		if err != nil {
			l.add("R01", rel, "does not parse: %v", err)
			return nil
		}
		m, ok := obj(d)
		if !ok {
			l.add("R01", rel, "is not a JSON object")
			return nil
		}
		id, _ := m["$id"].(string)
		if id == "" {
			l.add("R01", rel, "has no $id")
			return nil
		}
		if prev, dup := l.paths[id]; dup {
			l.add("R01", rel, "duplicate $id %s, also declared by %s", id, prev)
			return nil
		}
		l.docs[id] = d
		l.paths[id] = rel
		return nil
	})
}

// R02: every $ref resolves from the repository. Compilation is offline, so a
// reference that would need a network fetch is a reference that does not resolve.
func (l *linter) compile() {
	c := jsonschema.NewCompiler()
	c.DefaultDraft(jsonschema.Draft2020)
	for id, d := range l.docs {
		if err := c.AddResource(id, d); err != nil {
			l.add("R02", l.paths[id], "cannot register: %v", err)
		}
	}
	ids := make([]string, 0, len(l.docs))
	for id := range l.docs {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	for _, id := range ids {
		s, err := c.Compile(id)
		if err != nil {
			l.add("R02", l.paths[id], "does not compile: %v", err)
			continue
		}
		l.compiled[id] = s
	}
}

func (l *linter) loadCatalog() error {
	b, err := os.ReadFile(filepath.Join(l.root, "catalog.yaml"))
	if err != nil {
		return err
	}
	return yaml.Unmarshal(b, &l.entries)
}

// refGraph collects every schema reachable from start by following $ref through
// local documents, so that a subject_ref three hops away is still visible.
func (l *linter) refGraph(start string) map[string]bool {
	seen := map[string]bool{}
	var walk func(any)
	var visit func(string)
	visit = func(id string) {
		if seen[id] {
			return
		}
		seen[id] = true
		if d, ok := l.docs[id]; ok {
			walk(d)
		}
	}
	walk = func(node any) {
		switch v := node.(type) {
		case map[string]any:
			for k, val := range v {
				if k == "$ref" {
					if s, ok := val.(string); ok {
						if i := strings.Index(s, "#"); i >= 0 {
							s = s[:i]
						}
						if s != "" {
							visit(s)
						}
					}
					continue
				}
				walk(val)
			}
		case []any:
			for _, val := range v {
				walk(val)
			}
		}
	}
	walk(l.docs[start])
	return seen
}
