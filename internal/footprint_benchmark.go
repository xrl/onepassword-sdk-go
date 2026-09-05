//go:build footprint

package internal

// This seam is compiled only by the footprint lab. Its two loader hooks and the
// Extism accessor are supplied by a digest-pinned Go overlay, never in shipping builds.
import (
	"context"
	"crypto/sha256"
	"fmt"
	"sync"
	"sync/atomic"

	extism "github.com/extism/go-sdk"
	"github.com/tetratelabs/wazero"
)

var footprintLoads atomic.Uint32
var footprintRuntime wazero.RuntimeConfig

func footprintConfig(manifest *extism.Manifest) extism.PluginConfig {
	// Credential-free probes cannot contact even the SDK's normal allowed hosts.
	manifest.AllowedHosts = nil
	return extism.PluginConfig{RuntimeConfig: footprintRuntime}
}

type FootprintOptions struct {
	CacheDirectory   string
	MemoryLimitPages uint32
}

type FootprintCore struct {
	mu    sync.Mutex
	core  *ExtismCore
	cache wazero.CompilationCache
}

func FootprintConfigure(ctx context.Context, options FootprintOptions) (*FootprintCore, error) {
	f := &FootprintCore{}
	footprintRuntime = wazero.NewRuntimeConfig()
	if options.MemoryLimitPages != 0 {
		footprintRuntime = footprintRuntime.WithMemoryLimitPages(options.MemoryLimitPages)
	}
	if options.CacheDirectory != "" {
		cache, err := wazero.NewCompilationCacheWithDir(options.CacheDirectory)
		if err != nil {
			return nil, err
		}
		f.cache = cache
		footprintRuntime = footprintRuntime.WithCompilationCache(cache)
	}
	return f, nil
}

// Acquire exercises the shipping P0 path. The caller checks every returned identity.
func (f *FootprintCore) Acquire() (string, error) {
	w, err := GetExtismCore()
	if err != nil {
		return "", err
	}
	c := w.InnerCore.(*ExtismCore)
	f.mu.Lock()
	f.core = c
	f.mu.Unlock()
	return fmt.Sprintf("%p", c), nil
}
func (f *FootprintCore) Pages() (main, kernel uint32) {
	if f.core == nil {
		return
	}
	main = f.core.plugin.Module().FootprintMemoryPages()
	kernel, _ = f.core.plugin.Memory().Grow(0)
	return
}
func (f *FootprintCore) Invalid(ctx context.Context, function string, input []byte) ([]byte, error) {
	switch function {
	case "init_client":
		return f.core.InitClient(ctx, input)
	case "invoke":
		return f.core.Invoke(ctx, input)
	default:
		return nil, fmt.Errorf("unsupported footprint function")
	}
}
func (f *FootprintCore) Close(ctx context.Context) error {
	if f.core != nil {
		if err := f.core.plugin.Close(ctx); err != nil {
			return err
		}
		ReleaseCore()
		f.core = nil
	}
	if f.cache != nil {
		return f.cache.Close(ctx)
	}
	return nil
}
func FootprintLoadCount() uint32 { return footprintLoads.Load() }
func FootprintDigest() string    { return fmt.Sprintf("%x", sha256.Sum256(coreWASM)) }
