#!/usr/bin/env python3
"""Paired benchmark for semver.Version.compare: upstream body vs patched body.

Both implementations run on the same Version instances.  ``baseline`` is a
verbatim copy of the upstream compare() body; ``optimized`` calls the patched
method shipped in ../src.  This isolates the patched code path instead of
comparing two different libraries.

Usage:
  PYTHONPATH=src python benchmark/bench.py --impl baseline  --out benchmark/baseline.json
  PYTHONPATH=src python benchmark/bench.py --impl optimized --out benchmark/optimized.json
"""
import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from semver import Version  # noqa: E402

SEED = 4321
WARMUP = 3
REPS = 5


def _cmp(a, b):
    return (a > b) - (a < b)


def baseline_compare(self, other):
    """Byte-for-byte copy of upstream semver 3.1.2 Version.compare()."""
    cls = type(self)
    String = (str, bytes)
    if isinstance(other, String):
        other = cls.parse(other)
    elif isinstance(other, dict):
        other = cls(**other)
    elif isinstance(other, (tuple, list)):
        other = cls(*other)
    elif not isinstance(other, cls):
        raise TypeError("unexpected comparison operand")

    v1 = self.to_tuple()[:3]
    v2 = other.to_tuple()[:3]
    x = _cmp(v1, v2)
    if x:
        return x

    rc1, rc2 = self.prerelease, other.prerelease
    if rc1 == rc2:
        return 0
    if not rc1:
        return 1 if rc2 else 0
    elif not rc2:
        return -1
    return self._nat_cmp(rc1, rc2)


def make_versions(n):
    """Deterministic, distinct-enough versions: no RNG state involved."""
    out = []
    for i in range(n):
        pre = None
        if i % 3 == 0:
            pre = "rc.%d" % (i % 7)
        elif i % 7 == 0:
            pre = "alpha"
        build = "build.%d" % (i % 11) if i % 5 == 0 else None
        out.append(Version(i, (i * 7) % 97, (i * 13) % 89, pre, build))
    return out


SCALES = {"1k": 1000, "10k": 10000, "100k": 100000}


def run_scale(fn, versions, scale, impl):
    n_ops = len(versions) - 1
    for _ in range(WARMUP):
        for i in range(n_ops):
            fn(versions[i], versions[i + 1])

    raw_dir = ROOT / "benchmark" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    samples = []
    for rep in range(REPS):
        t0 = time.perf_counter()
        acc = 0
        for i in range(n_ops):
            acc += fn(versions[i], versions[i + 1])
        dt = time.perf_counter() - t0
        samples.append(dt)
        (raw_dir / f"{impl}-{scale}-{rep}.json").write_text(
            json.dumps({"impl": impl, "scale": scale, "rep": rep, "n_ops": n_ops,
                        "seconds": dt, "acc": acc, "seed": SEED})
        )
    q = statistics.quantiles(samples, n=4)
    return {
        "n_ops": n_ops,
        "samples_seconds": samples,
        "median": statistics.median(samples),
        "p25": q[0],
        "p75": q[2],
        "stdev": statistics.pstdev(samples),
        "rel_stdev": statistics.pstdev(samples) / statistics.median(samples),
        "ns_per_op": statistics.median(samples) / n_ops * 1e9,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--impl", choices=["baseline", "optimized"], required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    fn = baseline_compare if args.impl == "baseline" else (
        lambda a, b: a.compare(b))
    result = {
        "impl": args.impl,
        "seed": SEED,
        "warmup": WARMUP,
        "reps": REPS,
        "timer": "time.perf_counter",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu": platform.processor() or "unknown",
        "scales": {},
        # Real corpus: every adjacent pair of the 212 versions extracted from
        # upstream tests + installed package metadata, repeated 500x.
        "real_corpus": {},
    }
    for label, n in SCALES.items():
        result["scales"][label] = run_scale(fn, make_versions(n + 1), label, args.impl)

    real = json.loads((ROOT / "benchmark" / "corpus_real.json").read_text())["versions"]
    corpus = [Version.parse(v) for v in real]
    pairs = []
    for _ in range(500):
        pairs.extend(zip(corpus, corpus[1:]))
    # Reuse the same timed loop shape for a stable per-op number.
    for _ in range(WARMUP):
        for a, b in pairs:
            fn(a, b)
    samples = []
    for rep in range(REPS):
        t0 = time.perf_counter()
        acc = 0
        for a, b in pairs:
            acc += fn(a, b)
        dt = time.perf_counter() - t0
        samples.append(dt)
        (ROOT / "benchmark" / "raw" / f"{args.impl}-real-{rep}.json").write_text(
            json.dumps({"impl": args.impl, "scale": "real", "rep": rep,
                        "n_ops": len(pairs), "seconds": dt, "acc": acc, "seed": SEED}))
    q = statistics.quantiles(samples, n=4)
    result["real_corpus"] = {
        "versions": len(corpus), "pairs": len(pairs), "n_ops": len(pairs),
        "samples_seconds": samples, "median": statistics.median(samples),
        "p25": q[0], "p75": q[2],
        "rel_stdev": statistics.pstdev(samples) / statistics.median(samples),
        "ns_per_op": statistics.median(samples) / len(pairs) * 1e9,
    }
    Path(args.out).write_text(json.dumps(result, indent=1))
    print(json.dumps({k: v["median"] for k, v in result["scales"].items()}))


if __name__ == "__main__":
    main()