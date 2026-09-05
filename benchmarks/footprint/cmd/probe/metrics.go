//go:build footprint

package main

import (
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"

	"golang.org/x/sys/unix"
)

func cgroupStats() map[string]string {
	if runtime.GOOS != "linux" {
		return nil
	}
	b, err := os.ReadFile("/proc/self/cgroup")
	if err != nil {
		return map[string]string{"error": err.Error()}
	}
	for _, line := range strings.Split(string(b), "\n") {
		if strings.HasPrefix(line, "0::") {
			dir := filepath.Join("/sys/fs/cgroup", strings.TrimPrefix(line, "0::"))
			result := map[string]string{"path": dir}
			for _, name := range []string{"memory.current", "memory.peak", "memory.events", "memory.stat"} {
				b, err := os.ReadFile(filepath.Join(dir, name))
				if err != nil {
					result[name] = "ERROR: " + err.Error()
				} else {
					result[name] = string(b)
				}
			}
			return result
		}
	}
	return map[string]string{"error": "cgroup v2 not found"}
}
func processStats() map[string]any {
	r := map[string]any{"pid": os.Getpid(), "os": runtime.GOOS, "arch": runtime.GOARCH, "os_page_bytes": os.Getpagesize(), "go_version": runtime.Version(), "gomaxprocs": runtime.GOMAXPROCS(0), "gomemlimit": os.Getenv("GOMEMLIMIT"), "gogc": os.Getenv("GOGC")}
	var usage unix.Rusage
	if err := unix.Getrusage(unix.RUSAGE_SELF, &usage); err == nil {
		peak := usage.Maxrss
		if runtime.GOOS == "linux" {
			peak *= 1024
		}
		r["peak_rss_bytes"] = peak
		r["user_cpu_us"] = usage.Utime.Sec*1000000 + int64(usage.Utime.Usec)
		r["system_cpu_us"] = usage.Stime.Sec*1000000 + int64(usage.Stime.Usec)
	}
	if runtime.GOOS != "linux" {
		darwinRSS(r)
		return r
	}
	for _, name := range []string{"status", "smaps_rollup"} {
		b, err := os.ReadFile("/proc/self/" + name)
		if err != nil {
			r[name+"_error"] = err.Error()
			continue
		}
		for _, line := range strings.Split(string(b), "\n") {
			fields := strings.Fields(line)
			if len(fields) == 3 && fields[2] == "kB" {
				v, _ := strconv.ParseUint(fields[1], 10, 64)
				r[name+"_"+strings.TrimSuffix(fields[0], ":")+"_bytes"] = v * 1024
			}
		}
	}
	// RSS categories are disjoint. Go heap and both WASM memories are subsets of
	// anonymous non-executable RSS, NOT extra buckets to add to these totals.
	b, err := os.ReadFile("/proc/self/smaps")
	if err != nil {
		r["smaps_error"] = err.Error()
		return r
	}
	category := "other"
	totals := map[string]uint64{}
	for _, line := range strings.Split(string(b), "\n") {
		fields := strings.Fields(line)
		if len(fields) >= 5 && strings.Contains(fields[0], "-") {
			category = "anonymous_nonexec"
			file := len(fields) >= 6 && strings.HasPrefix(fields[5], "/")
			if file {
				category = "file"
			} else if strings.Contains(fields[1], "x") {
				category = "anonymous_exec"
			}
		} else if len(fields) == 3 && fields[0] == "Rss:" {
			v, _ := strconv.ParseUint(fields[1], 10, 64)
			totals[category] += v * 1024
		}
	}
	r["mapping_rss_bytes"] = totals
	return r
}
