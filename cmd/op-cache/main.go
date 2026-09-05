// op-cache prepares the embedded SDK core without credentials or authentication.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"os"

	onepassword "github.com/1password/onepassword-sdk-go"
)

func run() error {
	directory := flag.String("directory", "", "trusted executable compilation cache directory (required)")
	mode := flag.String("mode", "verify", "verify (require hit) or populate (read-write)")
	flag.Parse()
	if flag.NArg() != 0 {
		return errors.New("unexpected positional arguments")
	}
	cacheMode := onepassword.CompilationCacheRequireHit
	switch *mode {
	case "verify":
	case "populate":
		cacheMode = onepassword.CompilationCacheReadWrite
	default:
		return errors.New("mode must be verify or populate")
	}
	r, err := onepassword.NewRuntime(onepassword.WithCompilationCache(*directory, cacheMode))
	if err != nil {
		return err
	}
	ctx := context.Background()
	return errors.Join(r.Prepare(ctx), r.Close(ctx))
}

func main() {
	if err := run(); err != nil {
		// Deliberately do not print backend errors or arbitrary guest payloads.
		fmt.Fprintln(os.Stderr, "core cache preparation failed; check mode, trusted directory, and build compatibility")
		os.Exit(1)
	}
	fmt.Println("core cache preparation succeeded")
}
