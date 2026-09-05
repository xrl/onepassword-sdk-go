package onepassword

import (
	"context"
	"errors"
	"testing"

	"github.com/1password/onepassword-sdk-go/internal"
	"github.com/stretchr/testify/require"
)

func TestRuntimeOptions(t *testing.T) {
	for _, option := range []RuntimeOption{nil, WithCompilationCache("", CompilationCacheReadWrite), WithCompilationCache("cache", 0)} {
		r, err := NewRuntime(option)
		require.Error(t, err)
		require.Nil(t, r)
	}
	r, err := NewRuntime()
	require.NoError(t, err)
	require.NoError(t, r.Close(context.Background()))
	require.ErrorIs(t, r.Prepare(context.Background()), ErrRuntimeClosed)
	_, err = r.NewClient(context.Background())
	require.ErrorIs(t, err, ErrRuntimeClosed)
}

func TestRuntimeRejectsDesktopBeforeLoading(t *testing.T) {
	r, err := NewRuntime()
	require.NoError(t, err)
	defer r.Close(context.Background())
	_, err = r.NewClient(context.Background(), func(c *Client) error { account := "test"; c.config.AccountName = &account; return nil })
	require.ErrorContains(t, err, "only service-account")
}

func TestDefaultNewClientOptionsRemainUnchanged(t *testing.T) {
	sentinel := errors.New("option failed")
	_, err := NewClient(context.Background(), func(*Client) error { return sentinel })
	require.ErrorIs(t, err, sentinel)
	_, err = NewClient(context.Background(), WithServiceAccountToken("not-a-credential"), func(c *Client) error { account := "test"; c.config.AccountName = &account; return nil })
	require.ErrorContains(t, err, "cannot use both")
}

func TestOwnedClientCallsPreserveClosedError(t *testing.T) {
	r, err := NewRuntime()
	require.NoError(t, err)
	require.NoError(t, r.Close(context.Background()))
	core := internal.CoreWrapper{InnerCore: r.core}
	_, err = initClient(context.Background(), core, Client{})
	require.ErrorIs(t, err, ErrRuntimeClosed)
	_, err = clientInvoke(context.Background(), &internal.InnerClient{Core: core}, "unused", nil)
	require.ErrorIs(t, err, ErrRuntimeClosed)
	// Exactly the wrapper retained by the standard client finalizer: safe after Close.
	core.ReleaseClient(1)
}
