# NN_DaVinci 0.2.1 独立复验报告

复验日期：2026-08-25  
对象：当前工作区 `NN_DaVinci` 0.2.1  
复验原则：重新运行门禁、读取新一轮原始证据、审查关键实现，并使用故意构造的反例检查门禁是否会“错误通过”。旧 `artifacts/` 仅用于核对历史声明，不作为本轮成功输入。

## 结论

0.2.1 是一次有实质内容的质量修复。迭代 SCC、大图预检、七架构路由、标签密度、TikZ 文本、10 个 Chrome E2E 场景、准确覆盖率统计、打包和七格式导出均有真实实现；独立 fresh full 也成功完成。用户反馈中的测试数、覆盖率、性能表和七架构当前样例指标，绝大多数可以从新证据中复算得到。

但是，当前不能把“48/48 release blocker checks”理解成 48 个需求被逐条独立证明，也不能把证据目录称为哈希闭合的权威归档。独立审查发现四个发布可信度缺口：

1. 验收矩阵的 48 行没有逐行执行谓词；最终脚本把一个全局状态批量写给所有行。
2. 权威证据清单中的 `logs/full.log` 和 `logs/finalize.log` 哈希在归档完成后失效。
3. 节点碰撞 sweep-line 在同一横向区间、纵向分离的 10k 矩形上仍退化到约 10.30 秒和 O(N²) 比较。
4. SVG oracle 会让 50% 横向压缩文字和覆盖节点的 annotation 错误通过，而且没有强制权威 SVG 提供可比对的 metadata。

因此应把两个结果明确分开：

```text
runner_result = PASS       # 当前 verify-full.sh 按自身规则退出成功
release_audit = FAIL       # 矩阵语义、证据封口和对抗 oracle 未闭环
```

当前版本可定性为：**核心功能与当前样例通过，但发布审计失败的 0.2.1 Beta**。下一轮应先做范围严格的 **0.2.2 Verification Closure & Adversarial Geometry**，通过后再进入 0.3 产品功能扩张。

## 独立执行结果

### Quick

本机重新执行 `./scripts/verify-quick.sh` 成功：

```text
Python collected/passed: 89/89
failed/errors/skipped/deselected: 0/0/0/0
冻结的 0.2.0 test IDs: 73/73
core line:     1893/2076 = 91.18497%
core branch:    648/778  = 83.29049%
core combined: 2541/2854 = 89.03294%
all line:      3926/4716 = 83.24852%
all branch:    1264/1690 = 74.79290%
all combined:  5190/6406 = 81.01780%
elapsed: 约 25.08 秒
```

覆盖率门槛使用未四舍五入值，反馈中的分子、分母和百分比均可复算。

### Full

受限沙箱内第一次启动 Chrome 时，Chrome crashpad 因 `setsockopt: Operation not permitted` 退出；这是执行沙箱限制，不是应用断言失败。用允许真实 Chrome 的同一命令重新执行后，`./scripts/verify-full.sh` 成功，生成新的证据目录：

```text
artifacts/v0.2.1/20260825T133517Z-282930
elapsed: 54.603 秒
Python: 89/89
artifact assertions: 20
font/TikZ checks: 14
packaging checks: 8
E2E scenarios: 10/10
E2E diagnostic assertions: 63
```

本轮确实从新临时目录生成并检查 SVG、PDF、PNG、TikZ、EPS、PPTX、HTML、wheel 和 sdist；真实 Chrome 完成了 10 个独立初始化的场景。没有读取旧 `artifacts/` 作为通过条件。

这里的“成功”只表示 runner 退出码和现有脚本内断言通过。下文的 false-pass 与 stale hash 使独立 release audit 仍为失败，不能把 fresh full 的成功外推为证据系统已经可信。

`verify-nightly.sh` 当前只是通过 `exec` 调用 `verify-full.sh` 的两行稳定入口，不是一套额外 nightly 负载。因此 fresh full 已覆盖它的实际行为，但不能把 nightly 另算成一组独立检查。

## 反馈逐项核验

| 声明 | 结论 | 独立核验 |
| --- | --- | --- |
| 迭代 Kosaraju 替换递归 Tarjan | 已核实 | `_component_ranks()` 使用显式栈完成两遍遍历；10k 深链相关测试通过，没有提高 recursion limit。 |
| 碰撞查询改为 sweep-line | 已核实但不充分 | 实现与 100 个小随机朴素语料交叉验证；仍存在可构造的 O(N²) 退化，见“问题 3”。 |
| API、CLI、Web 统一大图预检 | 部分核实 | API/Web/CLI render 共用预检并能拒绝超大完整图；CLI 没有 `--focus`/`--focus-hops`，所以提示中的恢复路径不能直接从 CLI 执行。 |
| 独立 Node/Chrome SVG oracle | 已核实但有盲区 | 独立进程直接读落盘 SVG，未导入 Python 布局质量实现；transform、annotation、metadata 和箭头检查仍不完整。 |
| 修复七架构路由且保持结构 provenance | 已核实 | 七个输入 SHA、源/处理后节点边集合、关键边、RNN 展开和 MoE `×4` provenance 与固定 manifest 一致。 |
| 移除 `textLength/lengthAdjust` | 已核实 | 最终 SVG 不再使用字形压缩属性，`compact/paper/detailed` 标签密度有实际代码和测试。 |
| TikZ `×` 文本一致 | 已核实 | 映射使用 `\\times`；SVG、PDF、TikZ 及独立编译 PDF 的文本检查通过。 |
| coverage line/branch/combined 已修正 | 已核实 | 原始分子分母和打印值一致，门槛没有用 combined 冒充分支覆盖率。 |
| 10 个独立 Chrome E2E 场景 | 已核实 | 场景间重新创建 context/page，并直接断言坐标、路由控制点、历史状态和持久化；63 仅作为诊断断言数。 |
| 89 个 Python tests，旧 73 ID 保留 | 已核实 | fresh quick/full 均为 89/89；只读基线文件 73 行且当前 SHA 与反馈一致。 |
| 48/48 release blocker checks | 错误通过（FALSE PASS） | 48 是矩阵行数；篡改 TEMP-01 后仍全绿，已证明状态可错误通过，见“问题 1”。 |
| 122 个已登记源码条目的哈希 | 已核实其登记集合 | fresh run 时逐条重算均匹配；这不证明清单覆盖了所有可能影响运行的文件，也不等同于 Git 历史。 |
| 权威证据包哈希闭合 | 失败 | 两个独立 run 均有 `full.log`、`finalize.log` 两项 stale hash，见“问题 2”。 |
| 压力数据 | 已复现其主路径 | 100/1k full、10k focus、Web 422 与随机空间查询均在相近范围；其他命名语料并未全部实际 layout/benchmark。 |
| 七架构最终 SVG 指标 | 已核实当前产物 | 当前七图均为 clipping=0、node overlap=0、edge-node=0、unrelated crossing=0，字号和 occupancy 与反馈一致。该结论不代表 oracle 没有盲区。 |
| 完整可重建环境 | 部分核实 | 版本记录明确，但 Python 文件不是带完整传递依赖/哈希的平台锁；Node full 依赖已有 `node_modules`，没有从 lock 做 fresh `npm ci`。 |

## 已确认问题

### P0-1：验收矩阵没有逐项执行

`verification/acceptance-matrix-0.2.1.json` 有 48 行，但当前测试只检查行数、ID 唯一性和字段非空。`scripts/finalize_verification.py` 主要检查证据文件是否存在和少数顶层报告是否成功，然后把同一个全局 `passed` 状态写给全部矩阵行。

这会导致三个问题：

- 矩阵中的 command、oracle、threshold 没有被逐行解析和执行；
- `evidence_path` 中的 JSON Pointer 只剥掉后缀检查文件存在，不检查指针和值；
- `passed=48` 表示 48 行被统一标记，不等于 48 个 release blocker 分别通过。

矩阵还引用了不存在或名称错误的入口，例如：

```text
scripts/validate_acceptance_matrix.py       # 不存在
scripts/summarize_verification.py           # 不存在
scripts/benchmark_large_graphs.py           # 实际是 benchmark_large_graph.py
scripts/svg_quality_oracle                   # 实际是 svg_quality_oracle.mjs
```

至少三个证据 JSON Pointer 无法解析：

```text
SVG-02  visual/oracle-fixtures.json#/nested_transform
TEXT-01 visual/seven-architecture-metrics.json#/text
TEXT-04 visual/seven-architecture-metrics.json#/text_measurement
```

独立篡改实验进一步证明了这一点：复制 fresh evidence，将 `temporary-files.json` 改为 `passed=false` 并加入 stale cache 后，重新执行 finalizer，最终仍得到全局 `passed=true` 和 matrix `48 passed`。因此 TEMP-01 当前不是实际 blocker。

### P0-2：证据包哈希没有在日志关闭后封口

对反馈指定的证据目录和本次 fresh full 目录重新计算 manifest，两个目录都恰有两个不匹配项：

```text
logs/finalize.log
logs/full.log
```

原因是 finalizer 在自己的输出仍被 `tee` 写入日志时计算哈希，随后两个日志继续增长。当前 manifest 因而描述的是“归档过程中的中间状态”，不是最终落盘状态。`verification.json` 也没有显式的顶层 `run_id` 和 `evidence_root`。

下一版需要将测试执行、日志关闭、最终汇总和 detached checksum 分阶段完成，并从复制后的目录做一次完全独立的重算。

### P0-3：sweep-line 仍有最坏情况平方退化

当前碰撞查询按 x 轴维护 active list，再与 active 中每个矩形比较。当所有矩形的 x 区间重合但 y 区间互不重合时，输出为 0，比较次数仍为 N²。

独立反例：10,000 个 `x=0, width=1`、y 方向互不相交的矩形：

```text
returned_pairs=0
elapsed=10.2993 秒
```

现有约 0.016 秒的随机语料没有覆盖该分布。下一版应使用同时索引另一维的 interval tree、R-tree、层次网格或等价结构，并对稠密输出采用显式 pair budget/short-circuit，避免把“输出本身 O(N²)”与“零输出仍 O(N²)”混为一谈。

### P0-4：SVG oracle 存在可复现的错误通过

#### 横向压缩

构造一个 required text 位于 `transform="scale(0.5 1)"` 的 SVG。浏览器中字体被横向压缩 50%，oracle 却报告：

```text
minimum_horizontal_scale=1
passed=true
```

当前实现让 natural/actual text width 同时乘相同的 CTM 横向量，因此二者比值仍为 1，没有比较横向与纵向有效缩放。它也没有覆盖 CSS `font-stretch` 或未来重新出现的 `textLength`。

#### Annotation/legend 与 metadata

构造一个大 annotation 矩形覆盖节点的 SVG，oracle 仍报告零冲突并通过。当前主要枚举 nodes、texts 和 edge paths，没有完整检查 annotation/legend 与节点、文字和页面边界的关系。

此外，缺失 metadata 时 `metadata_delta=null` 也可以通过，与“从最终几何交叉核对 metadata”的门禁声明不一致。权威样例应强制存在 schema 合法、run/fixture 对应且数值未过期的 metadata。

#### 其他边界

- 箭头检查主要验证 path endpoint，没有按 marker 实际几何验证箭头体；
- 路径采样步长来自局部 path length，在较大 transform 下不一定约等于 1 CSS px；
- group label 有部分检查，但 annotation/legend 的相互遮挡和文本越界不完整。

当前七个 SVG 使用近似均匀 scale，且肉眼抽查与当前指标一致。因此这里否定的是 oracle 的完备性，不是声称当前七张图已经横向压缩。

## 次要但应在 0.2.2 收紧的事项

1. **基线哈希未成为门禁。** `python-test-ids-0.2.0.txt` 当前 mode 444、73 行，SHA-256 确为 `bd53e5272703b7d79399830ee146db8362c1e5f1e58798ecb95a731c695af838`，但脚本没有验证 sidecar 或独立固定锚点；两者可一起被修改。
2. **压力语料名不等于执行覆盖。** wide DAG、SCC、sparse skip、locally dense 已生成并哈希，但 full 没有全部实际 layout/summary。SCC 也缺少随机图与简单参考实现的 differential test。
3. **核心覆盖范围漏掉新关键模块。** `labels.py`、`scaling.py`、`verification.py` 不在 core manifest，虽然当前全包覆盖数据并不差；0.2.2 应把它们加入核心门槛并建立新分母。
4. **CLI 恢复建议不可直接执行。** CLI render 能拒绝大图，却没有 `--focus`、`--focus-hops` 或明确 summary 命令参数。
5. **可复现依赖仍是约束清单，不是完整锁。** 缺少全部传递依赖、哈希、平台/index 元数据以及从空 Node 安装的 release gate。
6. **出版导出泄露编辑控件。** MoE 权威 PNG/SVG 的 `Expert ×4` 节点右上方包含折叠控件字符 `⊞`，在 PNG 中接近小方框/tofu。编辑器可保留控件，但论文导出应移除编辑 affordance，或使用明确的出版语义符号。
7. **项目仍不是 Git 仓库。** 当前源码 SHA 可证明同一次运行中的一致性，但不能替代不可变提交、diff 审查和回滚。是否初始化 Git 需要用户单独授权。

## 发布判断与下一步

建议采用以下准确口径：

> NN_DaVinci 0.2.1 Beta 的 89 个 Python 测试、10 个真实 Chrome E2E 场景、七格式导出、打包、覆盖率、主压力路径和七个当前权威样例已独立复验通过。48 行验收矩阵尚未逐行执行，证据 manifest 有两个收尾后哈希不一致，空间查询与 SVG oracle 存在可复现的对抗盲区，因此发布证明系统仍需在 0.2.2 闭环。

实施顺序：

1. 0.2.2：真实矩阵谓词、证据包封口、最坏情况空间索引、对抗 SVG oracle、CLI/锁文件/出版导出小修。
2. 0.3.0：五级语义浏览、惰性画布、异步取消、导入向导和真实世界模型工作流。
3. 1.0 前：真实论文重画与未参与开发者的可用性验收。

详细路线见 `docs/ROADMAP_AFTER_0.2.1.md`，可直接执行的下一轮任务见 `docs/NEXT_ROUND_PROMPT_0.2.2.md`。下一轮固定阈值与历史基线另存为只读 `docs/TRUST_ANCHOR_0.2.2.json`；其 SHA-256 为 `10979b1d7112b7639207405dffe23f534762a02fb047b61540c5e04c955a3224`，实施者不得同时改写锚点和验证逻辑。

## 复验边界

- 本报告只证明本机、当前依赖和给定语料上的结果，不外推为跨平台结论。
- Chrome 沙箱失败与允许真实 Chrome 后的成功均如实记录。
- 本报告和后续两个规划文档是在 fresh full 完成后新增，不属于该次 0.2.1 source manifest；不能倒填进旧证据包。
- 复验没有初始化 Git、发布包、上传文件或修改产品源码。
