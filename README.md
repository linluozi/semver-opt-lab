# semver-opt-lab

`python-semver` 3.1.2 的 `Version.compare()` 每次比较都通过 `to_tuple()` 重建两个三元组、调用 6 次 property 描述符，而这三个数本来就存在 `__slots__` 里。本仓库改为在“两个操作数都恰好是 `Version`”时直读 slot 并逐段短路；子类可能覆写 `major/minor/patch/prerelease`，因此子类仍走原来的属性访问路径。不改公共 API、不引入缓存、不增加实例内存。

Upstream: https://github.com/python-semver/python-semver

- 基线提交：`a4b7d337b1eb699ad4bad532a4b3fc68f8ec2408`（`python-semver` 3.1.2）
- 补丁：`patch.diff`，`src/semver/version.py`，24 行（17+/7-），只动 `compare()` 一个函数
- 许可证：上游 BSD-3-Clause 原文见 `LICENSE`，文末注明来源与改动范围

## 结果

同一份 `benchmark/bench.py`、同一批 `Version` 对象、同一环境；基线实现是上游 `compare()` 的逐字副本，优化实现调用打完补丁的 `src/semver`。每规模 warmup 3 次、计时 5 次，原始样本在 `benchmark/raw/`。

| 规模（比较次数） | 基线中位 | 优化后中位 | 加速比 |
| --- | --- | --- | --- |
| 1,000 | 1.132 ms | 0.519 ms | **2.18x** |
| 10,000 | 11.135 ms | 4.977 ms | **2.24x** |
| 100,000 | 111.814 ms | 49.598 ms | **2.25x** |
| 真实语料 98,970（6,598 个相邻对 × 15 轮） | 104.494 ms | 45.053 ms | **2.32x** |

上表是第 1 轮，`benchmark/baseline.json` / `optimized.json` / `raw/` 就是这一轮。另跑两轮完整基准，三轮所有规模的加速比区间是：1k **1.873–2.182**、10k **2.182–2.258**、100k **2.185–2.254**、真实语料 **2.226–2.333**；每轮的完整中位数、p25/p75、相对标准差见 `benchmark/replication.json`。三轮“三个合成规模的轮中位”分别是 **2.237 / 2.185 / 2.182**。

真实语料是 PyPI JSON API 上 35 个广泛使用包（boto3、botocore、awscli、numpy、django、pytest 等）的**全部** SemVer 合规发行版本，去重并过滤后 6,599 条（`benchmark/corpus_real.json` 含包清单与来源），没有人工合成条目。因此 G3b 的 2.32x 不是自造重复负载。

**收益来自哪一行（成本分解）**：`benchmark/decompose.py` 在同一份语料上把三种写法拆开测（98,970 次/轮，5 轮中位）：上游 `to_tuple()` 写法 **836.1 ns/op**；只把 tuple 换成直读 slot（仍构造 tuple）**368.5 ns/op**（2.27x）；再对三段数字短路比较 **208.1 ns/op**（4.02x）。仓库里发布的补丁是第三种写法加上 `type is Version` 守卫，经公开入口实测 455.2 ns/op；基线的公开入口是 1,055.8 ns/op。两者与裸函数之差（220–247 ns）是方法调用 + `isinstance` 类型派发，不是自然序比较本身——这是下一步唯一还有空间的地方，本轮只改一处，没有动它。

**噪声披露**：1k 单次采样窗口只有约 1.1 ms，三轮基线相对标准差为 2.2% / 10.9% / 1.4%，优化后为 2.4% / 6.9% / 9.0%，轮间中位加速比 1.873–2.182，仍远高于 1.15x 门槛。10k / 100k 的三轮（两实现）相对标准差最大 1.43%；真实语料基线三轮 ≤0.80%，优化后为 0.71% / 3.63% / 0.98%（第 2 轮 3.63% 是唯一超过 1.5% 的组，该轮真实语料加速比仍为 2.226x）。逐轮数值见 `replication.json`。另在干净 `git clone --depth=1` 中独立跑一对完整基准（`benchmark/clean_clone_repro.json`）：1k 2.07x / 10k 2.19x / 100k 2.22x / 真实语料 2.35x，与仓库内数值一致（1k 因窗口最短，跨进程波动最大）。所有结论取 5 次中位数，不取最快值；warmup 不计入计时。

## 差分与闸门

差分不循环同一输入：构造 1,620 个**互不相同**的版本（5 个 major × 3 minor × 3 patch × 9 prerelease × 4 build，含 `10**20` 与 40 位数字 prerelease），按 sha256 去重后确定性抽 5,000 个**互不相同**的 `(a,b)` 对，逐对比较 `compare()` 返回值与 `< <= == != > >=` 六个运算符，全部要求整数/布尔**精确相等**；另做 464 次 `str` / `bytes` 操作数路径核对，以及 6 个覆写 `major`/`prerelease` 的子类对（验证回落分支）。结果：**0 差异**。

```
$ PYTHONPATH=src python3 tests/test_diff.py
{"distinct_versions": 1620, "subclass_pairs": 6, "distinct_pairs": 5000,
 "str_bytes_operand_checks": 464, "mismatches": 0}
```

| 闸门 | 结论 | 可复现命令 / 产物 |
| --- | --- | --- |
| G1 上游测试全绿 | ✅ 553 passed, 1 skipped, 34 warnings in 0.76s（打补丁后重跑） | `benchmark/upstream_tests.log`，见下方“G1 复现” |
| G2 差分一致 | ✅ 5,000 个独立对 / 1,620 个独立版本 / 6 个子类对，0 差异 | `PYTHONPATH=src python3 tests/test_diff.py` |
| G3 中位加速 ≥1.15x | ✅ **2.237x**（2.182 / 2.237 / 2.254） | 跑 `benchmark/bench.py` 两遍，读 JSON 的 `scales` |
| G3b 真实语料 ≥1.15x | ✅ **2.319x**（三轮 2.226–2.333，6,599 个真实发行版本） | 同上，读 `real_corpus.median` |
| G4 最大规模不退化 | ✅ 100k 为 2.254x（三轮最小 2.185x） | 同上，读 `scales.100k` |
| G5 峰值 RSS ≤1.10x | ✅ 三轮最大比值 **1.0152x**（基线 16,896–17,152 KB，优化后 16,896–17,024 KB） | `benchmark/memcheck.json` |

**G1 复现**（在 `/tmp` 下，不改本仓库）：

```bash
git clone git@github-linluozi:python-semver/python-semver.git /tmp/semver-up
cd /tmp/semver-up && git checkout -q a4b7d337b1eb699ad4bad532a4b3fc68f8ec2408
git apply /path/to/semver-opt-lab/patch.diff
python3 -m venv .venv && .venv/bin/pip -q install -e . pytest pytest-cov
.venv/bin/pytest -q   # 553 passed, 1 skipped
```

`benchmark/upstream_tests.log` 是用等价的、只依赖 pytest 的命令记录的（用 `-o addopts=...` 关掉覆盖率插件）：

```bash
python -m pytest -q -o addopts="--doctest-glob='*.rst' --doctest-modules --doctest-report ndiff"
# 553 passed, 1 skipped, 34 warnings in 0.76s
```

## 复现（三条命令）

```bash
PYTHONPATH=src python3 tests/test_diff.py
PYTHONPATH=src python3 benchmark/bench.py --impl baseline  --out benchmark/baseline.json
PYTHONPATH=src python3 benchmark/bench.py --impl optimized --out benchmark/optimized.json
```

只需要 CPython 3.12 标准库；`src/` 是打完补丁的 `python-semver` 包本身，`tests/` 只用 stdlib。`pytest` 可选。

## 环境

- CPU：AMD EPYC 7K62 48-Core Processor（4 vCPU）/ 内存 3,812,564 kB
- 运行时：CPython 3.12.3（`/usr/bin/python3`），pytest 9.2.0
- 跨解释器：本机只有 CPython 3.12.3，无 3.10/3.11，**未做跨版本交叉**；不编造多版本数据。结论仅限 3.12
- 计时：`time.perf_counter()`；种子 4321（版本构造确定性，无 RNG 状态）
- 分解测量：`benchmark/decompose.py` → `benchmark/decompose.json`
- 基线 / 优化样本：`benchmark/baseline.json`、`benchmark/optimized.json`、`benchmark/raw/*.json`（每份含 `n_ops`、`seconds`、`acc`、`seed`）、`benchmark/replication.json`（三轮汇总）、`benchmark/memcheck.json`（RSS 原始轮次）、`benchmark/clean_clone_repro.json`（干净 clone 独立复跑）

## 本轮创新

**B 档**：不是给 semver 加缓存，而是把 `compare()` 的成本拆开——每次比较重建 2 个 tuple、读 6 个 property，而值本来就在 `__slots__` 里——并用“1,620 个独立版本 × 5,000 个独立对 + 6 个子类对”的逐字节差分证明：直读 slot 后排序语义与六种运算符完全不变，6,599 条真实发行版本上仍有 2.32x（三轮 2.226–2.333）。与台账里 `lunar-python-opt-lab`（缓存整年表）、`jsonschema-opt-lab`（缓存 `descend`）不同，本改动**不引入任何缓存或新状态**，内存不升（三轮最大 1.0152x）。成本分解还给出一个反直觉结论：消掉 tuple/property 重建后，剩余约 220–250 ns/op 主要花在 `compare()` 的 4 次 `isinstance`（覆盖 6 个类型）+ 2 次 `type is` 守卫的类型派发与方法调用上，而不是比较运算。