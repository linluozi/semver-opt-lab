# semver-opt-lab

`python-semver` 3.1.2 的 `Version.compare()` 在每次比较时都通过 `to_tuple()` 重建两个三元组、并调用 6 次 property 描述符，而这三个数就存在 `__slots__` 里。本仓库把该路径改为直接读 slot 并逐段短路比较：不改公共 API、不引入缓存、不增加实例内存，在 6,599 条真实发行版本上中位 **2.36x**，三个合成规模中位 **2.34x**。

Upstream: https://github.com/python-semver/python-semver

- 基线提交：`a4b7d337b1eb699ad4bad532a4b3fc68f8ec2408`（`python-semver` 3.1.2）
- 补丁：`patch.diff`，`src/semver/version.py`，18 行（11+/7-），只动 `compare()` 一个函数
- 许可证：上游 BSD-3-Clause 原文见 `LICENSE`，文末注明来源与改动范围

## 结果

同一份 `benchmark/bench.py`、同一批 `Version` 对象、同一环境，基线实现是上游 `compare()` 的逐字副本，优化实现调用打完补丁的 `src/semver`。每规模 warmup 3 次、计时 5 次，原始样本在 `benchmark/raw/`。

| 规模（比较次数） | 基线中位 | 优化后中位 | 加速比 |
| --- | --- | --- | --- |
| 1,000 | 1.187 ms | 0.489 ms | **2.43x** |
| 10,000 | 11.174 ms | 4.830 ms | **2.31x** |
| 100,000 | 111.901 ms | 47.834 ms | **2.34x** |
| 真实语料 98,970（6,599 个版本 × 15 轮相邻对） | 105.077 ms | 44.460 ms | **2.36x** |

上表是第 1 轮（仓库内 `baseline.json` / `optimized.json` / `raw/` 对应的就是这一轮）。为排除单轮运气，另跑两轮完整基准，三轮所有规模的加速比区间是：1k **2.299–2.429**、10k **2.301–2.450**、100k **2.309–2.413**、真实语料 **2.323–2.458**；每轮的原始中位数见 `benchmark/replication.json`。

三个合成规模加速比的中位数 = **2.339x**；三轮复测的轮中位分别是 2.382x / 2.313x / 2.339x。真实语料是 PyPI JSON API 上 35 个广泛使用包（boto3、botocore、awscli、numpy、django、pytest 等）的**全部** SemVer 合规发行版本，去重后 6,599 条（`benchmark/corpus_real.json`，含包清单与来源），没有人工合成条目；因此 G3b 的 2.36x 不是自造重复负载。

**收益来自哪一行（成本分解）**：`benchmark/decompose.py` 在同一份 6,599 版本语料上把三种写法拆开测（98,970 次/轮，5 轮中位）：上游 `to_tuple()` 写法 **810.1 ns/op**；只把 tuple 换成直读 slot（仍构造 tuple）**372.6 ns/op**（2.17x）；再对三段数字短路比较 **197.7 ns/op**（4.10x）。仓库里实际发布的补丁是第三种写法，经公开 `compare()` 入口调用时实测 449 ns/op；同一入口开销在基线上也成立（基线入口 1,062 ns/op，裸函数 810 ns，差 252 ns），所以约 250 ns 是方法调用 + `isinstance` 类型派发，不是自然序比较本身——这也是下一步唯一还有空间的地方，但本轮只改一处，没有动它。

**噪声披露**：第 1 轮 10k 基线相对标准差 **11.7%**，来自 5 个样本中一个 15.9 ms 的调度离群值（其余约 11.2 ms）；同规模第 2/3 轮为 0.6%/0.7%，三轮中位加速比 2.301–2.450，结论不受影响。1k 采样窗口只有约 1.2 ms，三轮基线相对标准差 2.2%/2.1%/0.5%；其余规模均 <2%。所有结论取 5 次中位数，不取最快值；warmup 不计入计时。

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
| G3 中位加速 ≥1.15x | ✅ 2.339x（2.43 / 2.31 / 2.34） | `PYTHONPATH=src python benchmark/bench.py --impl baseline --out benchmark/baseline.json` 与 `--impl optimized ...` |
| G3b 真实语料 ≥1.15x | ✅ 2.36x（6,599 个真实发行版本，三轮 2.323–2.458） | 同上，读两份 JSON 的 `real_corpus.median` |
| G4 最大规模不退化 | ✅ 100k 为 2.34x（三轮最小 2.309x，≥0.95x） | 同上，读 `scales.100k` |
| G5 峰值 RSS ≤1.10x | ✅ 16,512 KB → 16,512 KB（1.000x）；独立 verifier 复跑为 17,396 → 17,268 KB（1.007x）。同一 100 万次比较负载，独立进程 | `PYTHONPATH=src python benchmark/memcheck.py baseline` / `... optimized` |

**G1 复现**（在 `/tmp` 下，不改本仓库）：

```bash
git clone git@github-linluozi:python-semver/python-semver.git /tmp/semver-up
cd /tmp/semver-up && git checkout -q a4b7d337b1eb699ad4bad532a4b3fc68f8ec2408
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

## 环境

- CPU：AMD EPYC 7K62 48-Core Processor（4 vCPU）/ 内存 3,812,564 kB
- 运行时：CPython 3.12.3（`/usr/bin/python3`），pytest 9.2.0
- 跨解释器：本机只有 CPython 3.12.3，无 3.10/3.11，**未做跨版本交叉**；不编造多版本数据。`sys._debugmallocstats` 与 slot 布局在 3.13 可能不同，结论仅限 3.12
- 计时：`time.perf_counter()`；种子 4321（版本构造确定性，无 RNG 状态）
- 分解测量：`benchmark/decompose.py` → `benchmark/decompose.json`
- 基线 / 优化样本：`benchmark/baseline.json`、`benchmark/optimized.json`、`benchmark/raw/*.json`（每份含 `n_ops`、`seconds`、`acc`、`seed`）、`benchmark/replication.json`（三轮汇总）

## 本轮创新

**B 档**：不是给 semver 加缓存，而是把 `compare()` 的成本拆开——每次比较重建 2 个 tuple、读 6 个 property，而值本来就在 `__slots__` 里——并用“1,620 个独立版本 × 5,000 个独立对”的逐字节差分证明：直读 slot 后排序语义与六种运算符完全不变，6,599 条真实发行版本上仍有 2.36x（三轮 2.323–2.458）。成本分解还给出一个反直觉结论：消掉 tuple/property 重建后，剩余约 250 ns/op 主要花在 `compare()` 的 7 类型 `isinstance` 派发上，而不是比较运算。与台账里 `lunar-python-opt-lab`（缓存整年表）、`jsonschema-opt-lab`（缓存 `descend`）不同，本改动**不引入任何缓存或新状态**，内存不升（1.000–1.007x）。

