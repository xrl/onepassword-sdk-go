package onepassword

import (
	"context"
	"fmt"

	"github.com/1password/onepassword-sdk-go/internal"
)

// ErrRuntimeClosed is returned by operations on a closed owned runtime.
var ErrRuntimeClosed = internal.ErrRuntimeClosed

// CompilationCacheMode controls persistent executable compilation artifacts,
// not credentials, sessions or secret values.
type CompilationCacheMode uint8

const (
	// CompilationCacheReadWrite deliberately populates or repairs a trusted cache.
	CompilationCacheReadWrite CompilationCacheMode = iota + 1
	// CompilationCacheRequireHit forbids guest compilation and cache mutation.
	// Missing, stale or corrupt entries fail without a read-write fallback.
	CompilationCacheRequireHit
)

type runtimeOptions struct {
	directory string
	mode      CompilationCacheMode
}

// RuntimeOption configures an owned runtime without exposing backend types.
type RuntimeOption func(*runtimeOptions) error

// WithCompilationCache selects a trusted persistent executable cache directory.
// Require-hit requires existing directories; read-write may create them.
func WithCompilationCache(directory string, mode CompilationCacheMode) RuntimeOption {
	return func(options *runtimeOptions) error {
		if directory == "" {
			return fmt.Errorf("compilation cache directory must not be empty")
		}
		if mode != CompilationCacheReadWrite && mode != CompilationCacheRequireHit {
			return fmt.Errorf("invalid compilation cache mode: %d", mode)
		}
		options.directory, options.mode = directory, mode
		return nil
	}
}

// Runtime owns one serialized service-account core and its compilation cache.
// Create it with NewRuntime, do not copy it, and close it after all clients are
// finished. Clients retain this owner; finalizers never access a closed plugin.
type Runtime struct{ core *internal.OwnedRuntime }

// NewRuntime configures a lazy owned runtime. Without options, compilation uses
// an in-memory cache. It neither loads the core nor authenticates a client.
func NewRuntime(options ...RuntimeOption) (*Runtime, error) {
	config := runtimeOptions{}
	for _, option := range options {
		if option == nil {
			return nil, fmt.Errorf("nil runtime option")
		}
		if err := option(&config); err != nil {
			return nil, err
		}
	}
	return &Runtime{core: internal.NewOwnedRuntime(config.directory, config.mode == CompilationCacheRequireHit)}, nil
}

// Prepare loads and instantiates the shipping core without authentication or
// network requests. Failed loads may be retried; no partial core is published.
func (r *Runtime) Prepare(ctx context.Context) error { return r.core.Prepare(ctx) }

// NewClient authenticates a service-account client using only this runtime.
// Desktop authentication is unsupported; package NewClient remains unchanged.
func (r *Runtime) NewClient(ctx context.Context, options ...ClientOption) (*Client, error) {
	client := Client{config: internal.NewDefaultConfig()}
	for _, option := range options {
		if err := option(&client); err != nil {
			return nil, err
		}
	}
	if client.config.AccountName != nil {
		return nil, fmt.Errorf("owned runtimes support only service-account authentication")
	}
	if err := r.Prepare(ctx); err != nil {
		return nil, err
	}
	return initClient(ctx, internal.CoreWrapper{InnerCore: r.core}, client)
}

// Close waits for active operations instead of cancelling them, then permanently
// closes the plugin and cache. Repeated calls return the original cleanup error.
// Later client calls return ErrRuntimeClosed; late finalizer releases are no-ops.
func (r *Runtime) Close(ctx context.Context) error { return r.core.Close(ctx) }
