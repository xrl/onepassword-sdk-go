#!/usr/bin/env python3
"""Build genuinely re-embedded candidates; never edit module cache or shipping WASM."""
import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
EXTISM_MODULE_SHA = '32dc5975297e2714f06c703afed6d2267b1c457ccbd6e03489677292bcf8d039'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def output(*args):
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def build(artifact, directory, goos, goarch):
    artifact, directory = Path(artifact).resolve(), Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    # Keep generated mixed-package overlay sources out of default `go test ./...`.
    (directory / 'go.mod').write_text('module footprint.generated\n\ngo 1.24.0\n')
    if output('go', 'version') != 'go version go1.27.1 darwin/arm64':
        raise RuntimeError('build host must use pinned Go 1.27.1 darwin/arm64')
    extism = Path(output('go', 'list', '-m', '-f', '{{.Dir}}', 'github.com/extism/go-sdk'))
    original = extism / 'module.go'
    if digest(original) != EXTISM_MODULE_SHA:
        raise RuntimeError('Extism module.go digest mismatch')
    module_source = original.read_text() + '''
// FootprintMemoryPages is a benchmark-only accessor; Grow(0) also handles 4 GiB.
func (m *Module) FootprintMemoryPages() uint32 {
    pages, _ := m.inner.Memory().Grow(0)
    return pages
}
'''
    (directory / 'module.go').write_text(module_source)
    dependency_copy = directory / 'extism'
    shutil.copytree(extism, dependency_copy)
    dependency_digests = {str(p.relative_to(extism)): digest(p) for p in sorted(extism.rglob('*')) if p.is_file()}
    (directory / 'dependency-digests.json').write_text(json.dumps(dependency_digests, indent=2) + '\n')
    modfile = directory / 'bench.mod'
    modfile.write_text((ROOT / 'go.mod').read_text() + '\nreplace github.com/extism/go-sdk => ' + str(dependency_copy) + '\n')
    (directory / 'bench.sum').write_bytes((ROOT / 'go.sum').read_bytes())
    source = ROOT / 'internal/extism_core.go'
    text = source.read_text()
    changes = {
        'p, err := loadWASM(runtimeCtx)': 'footprintLoads.Add(1)\n\t\tp, err := loadWASM(runtimeCtx)',
        'extismConfig := extism.PluginConfig{}': 'extismConfig := footprintConfig(&manifest)',
    }
    for old, new in changes.items():
        if text.count(old) != 1:
            raise RuntimeError('SDK loader anchor mismatch')
        text = text.replace(old, new)
    (directory / 'extism_core.go').write_text(text)
    # Go embed reads the overlay replacement, not an external module loaded at runtime.
    overlay = {'Replace': {
        str(dependency_copy / 'module.go'): str(directory / 'module.go'),
        str(source): str(directory / 'extism_core.go'),
        str(ROOT / 'internal/wasm/core.wasm'): str(artifact),
    }}
    (directory / 'overlay.json').write_text(json.dumps(overlay, indent=2) + '\n')
    command = ['go', 'build', '-modfile=' + str(modfile), '-trimpath', '-pgo=off', '-tags=footprint', '-overlay=' + str(directory / 'overlay.json'),
               '-o', str(directory / 'probe'), './benchmarks/footprint/cmd/probe']
    env = dict(os.environ, CGO_ENABLED='0', GOOS=goos, GOARCH=goarch, GOPROXY='off', GOTOOLCHAIN='local', GOFLAGS='', GOMEMLIMIT='off', GOAMD64='v1', GOARM64='v8.0', GOEXPERIMENT='')
    subprocess.run(command, cwd=ROOT, env=env, check=True)
    manifest = dict(source_sha256={str(p.relative_to(ROOT)): digest(p) for p in [ROOT / 'go.mod', ROOT / 'go.sum', ROOT / 'internal/footprint_benchmark.go', ROOT / 'benchmarks/footprint/build.py', *sorted((ROOT / 'benchmarks/footprint/cmd/probe').glob('*.go'))]}, command=command, environment={k: env[k] for k in ['CGO_ENABLED', 'GOOS', 'GOARCH', 'GOPROXY', 'GOTOOLCHAIN', 'GOFLAGS', 'GOAMD64', 'GOARM64', 'GOEXPERIMENT']},
                    go=output('go', 'version'), commit=output('git', 'rev-parse', 'HEAD'), dirty=output('git', 'status', '--porcelain'),
                    artifact_sha256=digest(artifact), artifact_bytes=artifact.stat().st_size,
                    binary_sha256=digest(directory / 'probe'), extism_module_original_sha256=digest(original),
                    sdk_loader_original_sha256=digest(source),
                    overlay_sources={p: digest(directory / p) for p in ['module.go', 'extism_core.go', 'overlay.json', 'bench.mod', 'bench.sum', 'dependency-digests.json']},
                    dependencies=output('go', 'list', '-m', 'all'), build_info=output('go', 'version', '-m', str(directory / 'probe')))
    (directory / 'build.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--artifact', default=str(ROOT / 'internal/wasm/core.wasm'))
    p.add_argument('--out', required=True)
    p.add_argument('--goos', default='darwin', choices=['darwin', 'linux'])
    p.add_argument('--goarch', default='arm64', choices=['arm64', 'amd64'])
    a = p.parse_args()
    build(a.artifact, a.out, a.goos, a.goarch)
