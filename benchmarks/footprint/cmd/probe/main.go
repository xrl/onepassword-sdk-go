//go:build footprint

// probe runs only fixed, credential-free malformed JSON. It never accepts payloads.
package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"runtime"
	"runtime/debug"
	"strings"
	"time"

	"github.com/1password/onepassword-sdk-go/internal"
)

type options struct {
	Cache        string        `json:"cache"`
	Calls        int           `json:"calls"`
	InputBytes   int           `json:"input_bytes"`
	Acquisitions int           `json:"acquisitions"`
	Settle       time.Duration `json:"settle_ns"`
	Diagnostic   string        `json:"diagnostic"`
	MemoryPages  uint          `json:"memory_limit_pages"`
	Idle         bool          `json:"idle"`
}
type goStats struct {
	HeapAlloc, HeapInuse, HeapIdle, HeapReleased, HeapSys, Sys, TotalAlloc, Mallocs, Frees, PauseTotalNs uint64
	NumGC                                                                                                uint32
}
type sample struct {
	Dependencies     map[string]string `json:"dependencies,omitempty"`
	Stage            string            `json:"stage"`
	ElapsedNS        int64             `json:"elapsed_ns"`
	OperationNS      int64             `json:"operation_ns,omitempty"`
	Go               goStats           `json:"go"`
	Process          map[string]any    `json:"process"`
	Cgroup           map[string]string `json:"cgroup,omitempty"`
	MainPages        uint32            `json:"main_pages"`
	KernelPages      uint32            `json:"kernel_pages"`
	LoadAttempts     uint32            `json:"load_attempts"`
	Identities       []string          `json:"identities"`
	Digest           string            `json:"embedded_sha256,omitempty"`
	ExpectedErrors   int               `json:"expected_errors"`
	UnexpectedErrors int               `json:"unexpected_errors"`
	ErrorSHA256      string            `json:"error_sha256,omitempty"`
	Options          *options          `json:"options,omitempty"`
}

var start = time.Now()
var encoder = json.NewEncoder(os.Stdout)

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
func run() error {
	var o options
	flag.StringVar(&o.Cache, "cache", "", "trusted cache directory; no require-hit semantics")
	flag.IntVar(&o.Calls, "calls", 2, "repeated invalid invoke calls (0..1000)")
	flag.IntVar(&o.InputBytes, "input-bytes", 64, "fixed malformed JSON size (1..1048576)")
	flag.IntVar(&o.Acquisitions, "acquisitions", 8, "P0 acquisitions (1..64)")
	flag.DurationVar(&o.Settle, "settle", time.Second, "settle duration, at most 120s")
	flag.StringVar(&o.Diagnostic, "diagnostic", "none", "none, gc, or free-os-memory")
	flag.UintVar(&o.MemoryPages, "memory-pages", 0, "per-memory diagnostic page cap (0 is default)")
	flag.BoolVar(&o.Idle, "idle", false, "baseline only")
	flag.Parse()
	if flag.NArg() != 0 || o.Calls < 0 || o.Calls > 1000 || o.InputBytes < 1 || o.InputBytes > 1048576 || o.Acquisitions < 1 || o.Acquisitions > 64 || o.Settle < 0 || o.Settle > 120*time.Second || o.MemoryPages > 65536 {
		return fmt.Errorf("invalid bounded options")
	}
	if o.Diagnostic != "none" && o.Diagnostic != "gc" && o.Diagnostic != "free-os-memory" {
		return fmt.Errorf("invalid diagnostic")
	}
	var f *internal.FootprintCore
	s := sample{Options: &o, Identities: []string{}, Dependencies: map[string]string{}}
	if info, ok := debug.ReadBuildInfo(); ok {
		for _, dep := range info.Deps {
			if dep.Path == "github.com/extism/go-sdk" || dep.Path == "github.com/tetratelabs/wazero" {
				s.Dependencies[dep.Path] = dep.Version
			}
		}
	}
	emit := func(stage string, duration time.Duration) error {
		s.Stage = stage
		s.ElapsedNS = time.Since(start).Nanoseconds()
		s.OperationNS = duration.Nanoseconds()
		var m runtime.MemStats
		runtime.ReadMemStats(&m)
		s.Go = goStats{m.HeapAlloc, m.HeapInuse, m.HeapIdle, m.HeapReleased, m.HeapSys, m.Sys, m.TotalAlloc, m.Mallocs, m.Frees, m.PauseTotalNs, m.NumGC}
		s.Process = processStats()
		s.Cgroup = cgroupStats()
		s.LoadAttempts = internal.FootprintLoadCount()
		s.MainPages = 0
		s.KernelPages = 0
		if f != nil {
			s.MainPages, s.KernelPages = f.Pages()
		}
		return encoder.Encode(s)
	}
	if err := emit("baseline-ready", 0); err != nil {
		return err
	}
	s.Options = nil
	s.Dependencies = nil
	if o.Idle {
		return emit("idle-complete", 0)
	}
	ctx := context.Background()
	var err error
	f, err = internal.FootprintConfigure(ctx, internal.FootprintOptions{CacheDirectory: o.Cache, MemoryLimitPages: uint32(o.MemoryPages)})
	if err != nil {
		return err
	}
	// Contend on the actual P0 lock; retain and check all identities, not only the last.
	type result struct {
		identity string
		err      error
	}
	results := make(chan result, o.Acquisitions)
	gate := make(chan struct{})
	t := time.Now()
	for i := 0; i < o.Acquisitions; i++ {
		go func() { <-gate; identity, err := f.Acquire(); results <- result{identity, err} }()
	}
	close(gate)
	identities := map[string]bool{}
	for i := 0; i < o.Acquisitions; i++ {
		r := <-results
		if r.err != nil {
			s.UnexpectedErrors++
			_ = emit("load-error", time.Since(t))
			return fmt.Errorf("core load failed: %w", r.err)
		}
		identities[r.identity] = true
	}
	for identity := range identities {
		s.Identities = append(s.Identities, identity)
	}
	s.Digest = internal.FootprintDigest()
	if len(identities) != 1 || internal.FootprintLoadCount() != 1 {
		return fmt.Errorf("P0 invariant failed")
	}
	if err = emit("core-ready", time.Since(t)); err != nil {
		return err
	}
	input := append(bytes.Repeat([]byte(" "), o.InputBytes-1), '{')
	call := func(function, stage string) error {
		t := time.Now()
		response, callErr := f.Invalid(ctx, function, input)
		// Fixed malformed JSON must fail at parsing, before credentials/network/session work.
		// Pinned original smoke confirms this parser error; fingerprints are recorded
		// because the position suffix varies with the bounded input size.
		expected := expectedInvalidOutcome(response, callErr)
		if expected {
			s.ExpectedErrors++
		} else {
			s.UnexpectedErrors++
		}
		if callErr != nil {
			s.ErrorSHA256 = fmt.Sprintf("%x", sha256.Sum256([]byte(callErr.Error())))
		}
		if err := emit(stage, time.Since(t)); err != nil {
			return err
		}
		if !expected {
			return fmt.Errorf("unexpected invalid-call outcome (%s); error hash=%s", function, s.ErrorSHA256)
		}
		return nil
	}
	if err = call("init_client", "invalid-init"); err != nil {
		return err
	}
	for i := 0; i < o.Calls; i++ {
		if err = call("invoke", "invalid-invoke"); err != nil {
			return err
		}
	}
	time.Sleep(o.Settle)
	if err = emit("settled", 0); err != nil {
		return err
	}
	if o.Diagnostic != "none" {
		t = time.Now()
		if o.Diagnostic == "gc" {
			runtime.GC()
		} else {
			debug.FreeOSMemory()
		}
		if err = emit("diagnostic", time.Since(t)); err != nil {
			return err
		}
	}
	t = time.Now()
	if err = f.Close(ctx); err != nil {
		return err
	}
	return emit("closed", time.Since(t))
}

func expectedInvalidOutcome(response []byte, err error) bool {
	return err != nil && strings.Contains(err.Error(), "EOF while parsing an object") && len(response) == 0
}
