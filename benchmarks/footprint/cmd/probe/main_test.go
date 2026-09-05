//go:build footprint

package main

import (
	"errors"
	"testing"
)

func TestExpectedInvalidOutcome(t *testing.T) {
	for _, tc := range []struct {
		name     string
		response []byte
		err      error
		want     bool
	}{
		{"parser rejection", nil, errors.New("EOF while parsing an object at line 1 column 64"), true},
		{"success", nil, nil, false},
		{"trap", nil, errors.New("wasm trap: out of bounds memory access"), false},
		{"response despite error", []byte("unexpected"), errors.New("EOF while parsing an object"), false},
		{"network error", nil, errors.New("http request denied"), false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if got := expectedInvalidOutcome(tc.response, tc.err); got != tc.want {
				t.Fatalf("got %v want %v", got, tc.want)
			}
		})
	}
}
