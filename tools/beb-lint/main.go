// SPDX-License-Identifier: Apache-2.0

package main

import (
	"flag"
	"fmt"
	"os"
)

func main() {
	root := flag.String("root", ".", "repository root to check")
	flag.Parse()

	findings, err := Check(*root)
	if err != nil {
		fmt.Fprintln(os.Stderr, "beb-lint:", err)
		os.Exit(2)
	}
	for _, f := range findings {
		fmt.Println(f)
	}
	if len(findings) > 0 {
		fmt.Fprintf(os.Stderr, "\n%d finding(s)\n", len(findings))
		os.Exit(1)
	}
	fmt.Println("beb-lint: clean")
}
