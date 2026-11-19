#!/usr/bin/env python3
"""Peak-RSS check for the same 1,000,000-compare workload (fresh process)."""
import resource, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "benchmark"))
from semver import Version
from bench import baseline_compare, make_versions
impl = sys.argv[1]
fn = baseline_compare if impl == "baseline" else (lambda a, b: a.compare(b))
vs = make_versions(10000)
acc = 0
for i in range(1_000_000):
    acc += fn(vs[i % 9999], vs[(i + 7) % 9999])
print(f"{impl} maxrss_kb={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss} acc={acc}")
