package internal

import (
	"context"
	"crypto/sha256"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/require"
	"github.com/tetratelabs/wazero"
)

type rejectPrepareNetwork struct{ t *testing.T }

func (r rejectPrepareNetwork) RoundTrip(*http.Request) (*http.Response, error) {
	r.t.Error("Prepare attempted a network request")
	return nil, fmt.Errorf("network disabled in credential-free test")
}

func TestOwnedRuntimeRealCoreCache(t *testing.T) {
	require.Equal(t, "23d115f4ac7519b48172df3e8615945572dbda7033d51b44c9490fd533ae0f23", fmt.Sprintf("%x", sha256.Sum256(coreWASM)))
	originalTransport := http.DefaultTransport
	http.DefaultTransport = rejectPrepareNetwork{t}
	defer func() { http.DefaultTransport = originalTransport }()
	ctx := context.Background()
	dir := t.TempDir()
	beforeGlobal := core
	rw := NewOwnedRuntime(dir, false)
	require.NoError(t, rw.Prepare(ctx))
	loaded := rw.plugin.(*compiledCore)
	require.Equal(t, allowed1PHosts(), loaded.plugin.AllowedHosts)
	for _, name := range []string{initClientFuncName, invokeFuncName, releaseClientFuncName} {
		require.True(t, loaded.plugin.FunctionExists(name))
	}
	require.NoError(t, rw.Close(ctx))
	require.Same(t, beforeGlobal, core, "owned load must not publish global core")
	entries := map[string][]byte{}
	require.NoError(t, filepath.WalkDir(dir, func(path string, entry os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if entry.IsDir() {
			return nil
		}
		data, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		entries[path] = data
		return nil
	}))
	require.NotEmpty(t, entries)
	verify := func(want error) {
		ro := NewOwnedRuntime(dir, true)
		err := ro.Prepare(ctx)
		if want == nil {
			require.NoError(t, err)
		} else {
			require.ErrorIs(t, err, want)
		}
		require.NoError(t, ro.Close(ctx))
	}
	verify(nil)
	for path, data := range entries {
		got, err := os.ReadFile(path)
		require.NoError(t, err)
		require.Equal(t, data, got)
	}
	// Mutate all entries so the first guest (including Extism's kernel) fails.
	for _, tc := range []struct {
		name   string
		want   error
		mutate func(string, []byte) error
	}{
		{"missing", wazero.ErrCompilationCacheMiss, func(path string, _ []byte) error { return os.Remove(path) }},
		{"stale", wazero.ErrCompilationCacheStale, func(path string, data []byte) error {
			data = append([]byte(nil), data...)
			require.Greater(t, len(data), 7)
			data[7] ^= 1
			return os.WriteFile(path, data, 0600)
		}},
		{"corrupt", wazero.ErrCompilationCacheCorrupt, func(path string, _ []byte) error { return os.WriteFile(path, []byte("corrupt"), 0600) }},
	} {
		t.Run(tc.name, func(t *testing.T) {
			for path, data := range entries {
				require.NoError(t, tc.mutate(path, data))
			}
			verify(tc.want)
			for path, data := range entries {
				got, err := os.ReadFile(path)
				if tc.name == "missing" {
					require.True(t, os.IsNotExist(err))
				} else {
					require.NoError(t, err)
					if tc.name == "corrupt" {
						require.Equal(t, []byte("corrupt"), got)
					} else {
						expected := append([]byte(nil), data...)
						expected[7] ^= 1
						require.Equal(t, expected, got)
					}
				}
				require.NoError(t, os.WriteFile(path, data, 0600))
			}
		})
	}
	verify(nil)
	missingDir := filepath.Join(t.TempDir(), "absent")
	missing := NewOwnedRuntime(missingDir, true)
	require.ErrorIs(t, missing.Prepare(ctx), wazero.ErrCompilationCacheIO)
	_, err := os.Stat(missingDir)
	require.True(t, os.IsNotExist(err))
	require.NoError(t, missing.Close(ctx))
}
