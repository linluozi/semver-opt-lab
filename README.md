# semver-opt-lab

`python-semver` 3.1.2 的 `Version.compare()` 在每次比较时都通过 `to_tuple()` 重建两个三元组、并调用 6 次 property 描述符，而这三个数就存在 `__slots__` 里。本仓库把该路径改为直接读 slot 并逐段短路比较：不改公共 API、不引入缓存、不增加实例内存，在 212 个真实版本串上中位 **1.61x**，三个合成规模中位 **2.39x**。

Upstream: https://github.com/python-semver/python-semver

- 基线提交：`a4b7d337b1eb699ad4bad532a4b3fc68f8ec2408`（`python-semver` 3.1.2）
- 补丁：`patch.diff`，`src/semver/version.py`，18 行（11+/7-），只动 `compare()` 一个函数
- 许可证：上游 BSD-3-Clause 原文见 `LICENSE`，文末注明来源与改动范围

## 结果

同一份 `benchmark/bench.py`、同一批 `Version` 对象、同一环境，基线实现是上游 `compare()` 的逐字副本，优化实现调用打完补丁的 `src/semver`。每规模 warmup 3 次、计时 5 次，原始样本在 `benchmark/raw/`。

| 规模（比较次数） | 基线中位 | 优化后中位 | 加速比 |
| --- | --- | --- | --- |
| 1,000 | 1.226 ms | 0.520 ms | **2.36x** |
| 10,000 | 13.937 ms | 4.728 ms | **2.95x** |
| 100,000 | 110.615 ms | 46.357 ms | **2.39x** |
| 真实语料 105,500（212 个版本 × 500 轮相邻对） | 185.921 ms | 115.185 ms | **1.61x** |

三个合成规模加速比的中位数 = **2.388x**。真实语料由上游 `tests/*.py` 中抽出的版本串 + 本机已安装包的 `dist-info/METADATA` 版本号组成（`benchmark/corpus_real.json`，212 条，无人工合成条目），所以 G3b 的 1.61x 不是自造重复负载。

**噪声披露**：1k 规模基线相对标准差 **11.6%**（优化后 5.4%），因为单次采样窗口只有约 1.2 ms，受调度器和计时器粒度影响；10k/100k 分别为 9.1%/4.6% 与 4.6%/1.4%，真实语料 1.6%/0.5%。所有结论取 5 次中位数，不取最快值；warmup 不计入计时。

## 差分与闸门

差分不循环同一输入：构造 1,620 个**互不相同**的版本（5 个 major × 3 minor × 3 patch × 9 prerelease × 4 build，含 `10**20`、40 位数字 prerelease），按 sha256 去重后确定性抽 5,000 个**互不相同**的 `(a,b)` 对，逐对比较 `compare()` 返回值与 `< <= == != > >=` 六个运算符，全部要求整数/布尔**精确相等**；另做 464 次 `str` / `bytes` 操作数路径核对。结果：**0 差异**。

```
$ PYTHONPATH=src python tests/test_diff.py
{"distinct_versions": 1620, "distinct_pairs": 5000, "compare_calls": 5000,
 "str_bytes_operand_checks": 464, "mismatches": 0}
```

| 闸门 | 结论 | 可复现命令 |
| --- | --- | --- |
| G1 上游测试全绿 | ✅ 553 passed, 1 skipped, 34 warnings in 1.40s（打补丁后重跑原命令） | 见下方“G1 复现” |
| G2 差分一致 | ✅ 5,000 个独立对 / 1,620 个独立版本，0 差异 | `PYTHONPATH=src python tests/test_diff.py` |
| G3 中位加速 ≥1.15x | ✅ 2.388x（2.36 / 2.95 / 2.39） | `PYTHONPATH=src python benchmark/bench.py --impl baseline --out benchmark/baseline.json` 与 `--impl optimized ...` |
| G3b 真实语料 ≥1.15x | ✅ 1.614x（212 个真实版本串） | 同上，读两份 JSON 的 `real_corpus.median` |
| G4 最大规模不退化 | ✅ 100k 为 2.386x（≥0.95x） | 同上，读 `scales.100k` |
| G5 峰值 RSS ≤1.10x | ✅ 16,896 KB → 16,640 KB（0.985x，同一 100 万次比较负载，独立进程） | `PYTHONPATH=src python benchmark/memcheck.py baseline` / `... optimized` |

**G1 复现**（在 `/tmp` 下，不改本仓库）：

```bash
git clone --depth=1 git@github-linluozi:python-semver/python-semver.git /tmp/semver-up
cd /tmp/semver-up && git fetch --depth=1 origin a4b7d337b1eb699ad4bad532a4b3fc68f8ec2408 && git checkout -q FETCH_HEAD
git apply /path/to/semver-opt-lab/patch.diff
python3 -m venv .venv && .venv/bin/pip -q install -e . pytest pytest-cov
.venv/bin/pytest -q   # 553 passed, 1 skipped
```

## 复现（三条命令）

```bash
PYTHONPATH=src python tests/test_diff.py
PYTHONPATH=src python benchmark/bench.py --impl baseline  --out benchmark/baseline.json
PYTHONPATH=src python benchmark/bench.py --impl optimized --out benchmark/optimized.json
```

只需要 CPython 3.12 标准库；`src/` 是打完补丁的 `python-semver` 包本身，`tests/` 只用 stdlib。`pytest` 是可选的（`pytest -q tests` 亦可）。

## 本轮创新

**B 档**：不是给 semver 加缓存，而是把 `compare()` 的成本拆开——每次比较重建 2 个 tuple、读 6 个 property，而值本来就在 `__slots__` 里——并用“1,620 个独立版本 × 5,000 个独立对”的逐字节差分证明：直读 slot 后排序语义与六种运算符完全不变，真实语料仍有 1.61x。与台账里 `lunar-python-opt-lab`（缓存整年表）、`jsonschema-opt-lab`（缓存 `descend`）不同，本改动**不引入任何缓存或新状态**，内存反而略降（0.985x）。

## 环境

- CPU：AMD EPYC 7K62 48-Core Processor（4 vCPU）/ 内存 3,812,564 kB
- 运行时：CPython 3.12.3（`/usr/bin/python3`），pytest 9.2.0
- 计时：`time.perf_counter()`；种子 4321（版本构造确定性，无 RNG 状态）
- 基线 / 优化样本：`benchmark/baseline.json`、`benchmark/optimized.json`、`benchmark/raw/*.json`（每份含 `n_ops`、`seconds`、`acc`、`seed`）