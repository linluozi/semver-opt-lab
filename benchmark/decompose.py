#!/usr/bin/env python3
"""Attribute compare() cost: tuple rebuild vs slot reads vs short-circuit.

All three variants return the same integer on every corpus pair; this script
only measures where the time goes.  Output: benchmark/decompose.json.
"""
import json, statistics, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from semver import Version

versions = [Version.parse(v) for v in json.loads((ROOT / "benchmark" / "corpus_real.json").read_text())["versions"]]
pairs = list(zip(versions, versions[1:])) * 15

def old_tuple(a, b):
    x = a.to_tuple()[:3]; y = b.to_tuple()[:3]
    c = (x > y) - (x < y)
    if c: return c
    r1, r2 = a.prerelease, b.prerelease
    if r1 == r2: return 0
    if not r1: return 1 if r2 else 0
    if not r2: return -1
    return a._nat_cmp(r1, r2)

def slots_tuple(a, b):
    x = (a._major, a._minor, a._patch); y = (b._major, b._minor, b._patch)
    c = (x > y) - (x < y)
    if c: return c
    r1, r2 = a._prerelease, b._prerelease
    if r1 == r2: return 0
    if not r1: return 1 if r2 else 0
    if not r2: return -1
    return a._nat_cmp(r1, r2)

def slots_short(a, b):
    if a._major != b._major: return -1 if a._major < b._major else 1
    if a._minor != b._minor: return -1 if a._minor < b._minor else 1
    if a._patch != b._patch: return -1 if a._patch < b._patch else 1
    r1, r2 = a._prerelease, b._prerelease
    if r1 == r2: return 0
    if not r1: return 1 if r2 else 0
    if not r2: return -1
    return a._nat_cmp(r1, r2)

ref = [old_tuple(a, b) for a, b in pairs]
assert ref == [slots_tuple(a, b) for a, b in pairs] == [slots_short(a, b) for a, b in pairs]
out = {"n_ops_per_rep": len(pairs), "reps": 5, "warmup": 3, "timer": "time.perf_counter", "variants": {}}
for name, fn in (("upstream_to_tuple", old_tuple), ("slots_tuple", slots_tuple), ("slots_short_circuit", slots_short)):
    for _ in range(3):
        for a, b in pairs: fn(a, b)
    samples = []
    for _ in range(5):
        t0 = time.perf_counter(); acc = 0
        for a, b in pairs: acc += fn(a, b)
        samples.append(time.perf_counter() - t0)
    out["variants"][name] = {"median_s": statistics.median(samples), "samples_s": samples, "ns_per_op": statistics.median(samples) / len(pairs) * 1e9}
base = out["variants"]["upstream_to_tuple"]["median_s"]
for v in out["variants"].values(): v["speedup_vs_upstream"] = base / v["median_s"]
(ROOT / "benchmark" / "decompose.json").write_text(json.dumps(out, indent=1))
print(json.dumps({k: round(v["ns_per_op"], 1) for k, v in out["variants"].items()}))
