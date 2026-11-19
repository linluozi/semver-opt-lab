"""Differential test: upstream compare() body vs the patched compare().

Every sample pair is a distinct (version_a, version_b) tuple.  Deduplication is
by sha256 of the two full constructors, so cycling one input cannot inflate the
count.  Results are exact integers / booleans; no tolerance is used.
"""
import hashlib
import itertools
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from semver import Version  # noqa: E402


def _cmp(a, b):
    return (a > b) - (a < b)


def reference_compare(self, other):
    """Verbatim upstream 3.1.2 body (the code removed by patch.diff)."""
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


def build_versions():
    majors = [0, 1, 2, 10, 10 ** 20]
    minors = [0, 3, 99]
    patches = [0, 1, 7]
    pres = [None, "alpha", "alpha.1", "alpha.beta", "beta.11", "rc.1",
            "0", "1", "9" * 40]
    builds = [None, "build.1", "001", "exp.sha.5114f85"]
    seen, out = set(), []
    for major, minor, patch, pre, build in itertools.product(
            majors, minors, patches, pres, builds):
        key = (major, minor, patch, pre, build)
        digest = hashlib.sha256(repr(key).encode()).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        out.append(Version(major, minor, patch, pre, build))
    return out, len(seen)


def main():
    versions, distinct_versions = build_versions()
    rng = random.Random(4321)
    pairs, pair_seen = [], set()
    # Deterministic sampling over the cross product; keep only distinct pairs.
    for _ in range(40000):
        a = rng.randrange(len(versions))
        b = rng.randrange(len(versions))
        if a == b:
            continue
        key = (a, b) if a < b else (b, a)
        if key in pair_seen:
            continue
        pair_seen.add(key)
        pairs.append((versions[a], versions[b]))
        if len(pairs) >= 5000:
            break

    mismatches = []
    checked = 0
    for a, b in pairs:
        expected = reference_compare(a, b)
        got = a.compare(b)
        ops = (got, a < b, a <= b, a == b, a != b, a > b, a >= b)
        ref_ops = (expected, expected < 0, expected <= 0, expected == 0,
                   expected != 0, expected > 0, expected >= 0)
        if ops != ref_ops:
            mismatches.append([str(a), str(b), expected, got, list(ops), list(ref_ops)])
        checked += 1

    # Operand-coercion paths: str and bytes must go through parse identically.
    str_checks = 0
    for i in range(0, len(versions), 7):
        raw = str(versions[i])
        if reference_compare(versions[i], Version.parse(raw)) != versions[i].compare(raw):
            mismatches.append(["str-operand", raw])
        if reference_compare(versions[i], Version.parse(raw)) != versions[i].compare(raw.encode()):
            mismatches.append(["bytes-operand", raw])
        str_checks += 2

    result = {
        "distinct_versions": distinct_versions,
        "distinct_pairs": len(pair_seen),
        "compare_calls": checked,
        "str_bytes_operand_checks": str_checks,
        "mismatches": len(mismatches),
        "first_mismatches": mismatches[:5],
    }
    print(json.dumps(result, indent=1))
    assert distinct_versions >= 1000, distinct_versions
    assert len(pair_seen) >= 1000, len(pair_seen)
    assert not mismatches, mismatches[:3]


def test_differential_exact():
    main()


if __name__ == "__main__":
    main()