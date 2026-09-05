//go:build footprint && darwin

package main

import (
	"os"
	"os/exec"
	"strconv"
	"strings"
)

// ps reports current RSS without cgo; its subprocess is outside probe rusage.
// This is developer-only signal, not the Linux cgroup measurement lane.
func darwinRSS(r map[string]any) {
	b, err := exec.Command("/bin/ps", "-o", "rss=", "-p", strconv.Itoa(os.Getpid())).Output()
	if err != nil {
		r["rss_error"] = err.Error()
		return
	}
	v, err := strconv.ParseUint(strings.TrimSpace(string(b)), 10, 64)
	if err != nil {
		r["rss_error"] = err.Error()
		return
	}
	r["rss_bytes"] = v * 1024
}
