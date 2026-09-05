//go:build footprint

package internal

import (
	"context"
	"strings"
	"sync"
	"testing"
)

func TestFootprintLoaderPagesAndInvalidCalls(t *testing.T) {
	ReleaseCore()
	footprintLoads.Store(0)
	f, err := FootprintConfigure(context.Background(), FootprintOptions{})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := f.Close(context.Background()); err != nil {
			t.Error(err)
		}
	})
	var wg sync.WaitGroup
	identities := make(chan string, 8)
	for range 8 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			id, err := f.Acquire()
			if err != nil {
				t.Error(err)
				return
			}
			identities <- id
		}()
	}
	wg.Wait()
	close(identities)
	unique := map[string]bool{}
	for id := range identities {
		unique[id] = true
	}
	if len(unique) != 1 || FootprintLoadCount() != 1 {
		t.Fatalf("identities=%v attempts=%d", unique, FootprintLoadCount())
	}
	main, kernel := f.Pages()
	if main != 62 || kernel != 16 {
		t.Fatalf("main=%d kernel=%d", main, kernel)
	}
	if len(f.core.plugin.AllowedHosts) != 0 {
		t.Fatal("benchmark must deny HTTP hosts")
	}
	for _, function := range []string{"init_client", "invoke"} {
		response, err := f.Invalid(context.Background(), function, []byte("{"))
		if len(response) != 0 || err == nil || !strings.Contains(err.Error(), "EOF while parsing an object") {
			t.Fatalf("unexpected outcome for %s", function)
		}
	}
	if FootprintDigest() != "23d115f4ac7519b48172df3e8615945572dbda7033d51b44c9490fd533ae0f23" {
		t.Fatal("original test must embed pinned original artifact")
	}
}

func TestFootprintRetriesRealLoadFailure(t *testing.T) {
	ReleaseCore()
	footprintLoads.Store(0)
	ctx := context.Background()
	failed, err := FootprintConfigure(ctx, FootprintOptions{MemoryLimitPages: 1})
	if err != nil {
		t.Fatal(err)
	}
	if id, err := failed.Acquire(); err == nil || id != "" {
		t.Fatal("one-page limit must reject load without identity")
	}
	if FootprintLoadCount() != 1 {
		t.Fatalf("failed load attempts=%d", FootprintLoadCount())
	}
	recovered, err := FootprintConfigure(ctx, FootprintOptions{})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := recovered.Close(ctx); err != nil {
			t.Error(err)
		}
	})
	first, err := recovered.Acquire()
	if err != nil {
		t.Fatal(err)
	}
	second, err := recovered.Acquire()
	if err != nil {
		t.Fatal(err)
	}
	if first == "" || first != second || FootprintLoadCount() != 2 {
		t.Fatalf("identities %q %q attempts=%d", first, second, FootprintLoadCount())
	}
}
