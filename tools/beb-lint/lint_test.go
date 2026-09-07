// SPDX-License-Identifier: Apache-2.0

package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/goccy/go-yaml"
)

// repoRoot is the tree under test. beb-lint checks the repository it ships in.
const repoRoot = "../.."

type mutation struct {
	File    string `yaml:"file"`
	Op      string `yaml:"op"`
	Pointer string `yaml:"pointer"`
	Value   string `yaml:"value"`
	Old     string `yaml:"old"`
	New     string `yaml:"new"`
}

type ruleCase struct {
	Name      string     `yaml:"name"`
	Rule      string     `yaml:"rule"`
	Why       string     `yaml:"why"`
	Mutations []mutation `yaml:"mutations"`
	Expect    string     `yaml:"expect"`
}

// TestCleanRepositoryIsClean is the passing half of every rule below. A rule
// that fires on the shipped tree is a rule that is wrong.
func TestCleanRepositoryIsClean(t *testing.T) {
	findings, err := Check(repoRoot)
	if err != nil {
		t.Fatalf("Check: %v", err)
	}
	for _, f := range findings {
		t.Errorf("unexpected finding: %s", f)
	}
}

// TestEveryCatalogedEventHasBothExamples guards the property that makes the
// example rules meaningful: they only check files that exist.
func TestEveryCatalogedEventHasBothExamples(t *testing.T) {
	b, err := os.ReadFile(filepath.Join(repoRoot, "catalog.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	var entries []Entry
	if err := yaml.Unmarshal(b, &entries); err != nil {
		t.Fatal(err)
	}
	if len(entries) == 0 {
		t.Fatal("catalog is empty")
	}
	for _, e := range entries {
		dir := filepath.Join(repoRoot, "schemas", filepath.Dir(e.Schema), "examples")
		for _, kind := range []string{"minimal", "full"} {
			if _, err := os.Stat(filepath.Join(dir, kind+".json")); err != nil {
				t.Errorf("%s: %v", e.Type, err)
			}
		}
	}
}

// TestRuleFixtures is the failing half. Each case mutates a copy of the real
// tree and asserts that the named rule fires with the expected message.
func TestRuleFixtures(t *testing.T) {
	b, err := os.ReadFile(filepath.Join("testdata", "cases.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	var cases []ruleCase
	if err := yaml.Unmarshal(b, &cases); err != nil {
		t.Fatal(err)
	}
	if len(cases) == 0 {
		t.Fatal("no cases")
	}

	seen := map[string]bool{}
	for _, c := range cases {
		if seen[c.Name] {
			t.Fatalf("duplicate case name %q", c.Name)
		}
		seen[c.Name] = true

		t.Run(c.Name, func(t *testing.T) {
			root := t.TempDir()
			if err := copyTree(repoRoot, root); err != nil {
				t.Fatal(err)
			}
			for _, m := range c.Mutations {
				if err := apply(root, m); err != nil {
					t.Fatalf("mutation %s %s: %v", m.Op, m.File, err)
				}
			}
			findings, err := Check(root)
			if err != nil {
				t.Fatalf("Check: %v", err)
			}
			for _, f := range findings {
				if f.Rule == c.Rule && strings.Contains(f.Message, c.Expect) {
					return
				}
			}
			t.Errorf("no %s finding containing %q. why: %s\ngot %d finding(s):",
				c.Rule, c.Expect, strings.TrimSpace(c.Why), len(findings))
			for _, f := range findings {
				t.Errorf("  %s", f)
			}
		})
	}
}

// copyTree copies the inputs beb-lint reads: the schema tree and the catalog.
func copyTree(src, dst string) error {
	if err := copyFile(filepath.Join(src, "catalog.yaml"), filepath.Join(dst, "catalog.yaml")); err != nil {
		return err
	}
	return filepath.Walk(filepath.Join(src, "schemas"), func(p string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(src, p)
		if err != nil {
			return err
		}
		target := filepath.Join(dst, rel)
		if info.IsDir() {
			return os.MkdirAll(target, 0o755)
		}
		return copyFile(p, target)
	})
}

func copyFile(src, dst string) error {
	b, err := os.ReadFile(src)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		return err
	}
	return os.WriteFile(dst, b, 0o644)
}

func apply(root string, m mutation) error {
	p := filepath.Join(root, m.File)
	b, err := os.ReadFile(p)
	if err != nil {
		return err
	}
	switch m.Op {
	case "text_replace":
		s := string(b)
		if !strings.Contains(s, m.Old) {
			return fmtErr("old text not present: %q", m.Old)
		}
		return os.WriteFile(p, []byte(strings.Replace(s, m.Old, m.New, 1)), 0o644)
	case "json_set", "json_delete":
		var doc any
		dec := json.NewDecoder(strings.NewReader(string(b)))
		dec.UseNumber()
		if err := dec.Decode(&doc); err != nil {
			return err
		}
		var val any
		if m.Op == "json_set" {
			d := json.NewDecoder(strings.NewReader(m.Value))
			d.UseNumber()
			if err := d.Decode(&val); err != nil {
				return err
			}
		}
		if err := pointerApply(doc, m.Pointer, val, m.Op == "json_delete"); err != nil {
			return err
		}
		out, err := json.MarshalIndent(doc, "", "  ")
		if err != nil {
			return err
		}
		return os.WriteFile(p, append(out, '\n'), 0o644)
	}
	return fmtErr("unknown op %q", m.Op)
}

// pointerApply sets or deletes the member named by a JSON Pointer. Intermediate
// objects must already exist; a fixture that has to create a path is a fixture
// aimed at something that moved.
func pointerApply(doc any, pointer string, value any, del bool) error {
	if !strings.HasPrefix(pointer, "/") {
		return fmtErr("pointer %q must start with /", pointer)
	}
	parts := strings.Split(pointer[1:], "/")
	for i := range parts {
		parts[i] = strings.ReplaceAll(strings.ReplaceAll(parts[i], "~1", "/"), "~0", "~")
	}
	cur := doc
	for _, p := range parts[:len(parts)-1] {
		m, ok := cur.(map[string]any)
		if !ok {
			return fmtErr("pointer %q: %q is not an object", pointer, p)
		}
		next, ok := m[p]
		if !ok {
			return fmtErr("pointer %q: %q does not exist", pointer, p)
		}
		cur = next
	}
	m, ok := cur.(map[string]any)
	if !ok {
		return fmtErr("pointer %q: parent is not an object", pointer)
	}
	last := parts[len(parts)-1]
	if del {
		if _, ok := m[last]; !ok {
			return fmtErr("pointer %q: %q does not exist to delete", pointer, last)
		}
		delete(m, last)
		return nil
	}
	m[last] = value
	return nil
}

func fmtErr(format string, a ...any) error {
	return fmt.Errorf(format, a...)
}
