# NN_DaVinci 下一轮实施 Prompt：0.2.2

以下内容可直接复制到新的 Codex 对话：

---

你现在接手工作区中的 `NN_DaVinci`。请直接实施 **NN_DaVinci 0.2.2：Verification Closure & Adversarial Geometry**，持续完成到本轮 release gate 真正通过。

本轮不开发五级语义浏览、惰性画布、异步任务中心等 0.3 大功能。0.2.2 的唯一目标是闭环 0.2.1 的发布证明系统、最坏情况性能和最终 SVG 对抗验收，并完成少量与这些问题直接相关的 CLI、依赖锁和 publication export 修复。

版本政策：0.2.x 只允许向后兼容的缺陷修复，以及让既有功能可恢复、可验证所必需的小型选项。CLI focus/summary 参数和 publication layer 分离用于修复 0.2.1 已存在的缺陷；其他产品能力必须留到 0.3。

不要只改文档、数字或状态字段。不要读取旧 `artifacts/` 作为通过输入，不要把布局器自报 metadata 当作独立真值，不要通过删测试、改固定 fixture、放宽阈值、隐藏必显边/文字或批量赋值 `passed` 获得成功。

## 开始前

完整阅读：

- `README.md`
- `docs/ACCEPTANCE.md`
- `docs/KNOWN_LIMITATIONS.md`
- `docs/RELEASE_NOTES_0.2.1.md`
- `docs/INDEPENDENT_AUDIT_0.2.1_2026-08-25.md`
- `docs/ROADMAP_AFTER_0.2.1.md`
- `docs/TRUST_ANCHOR_0.2.2.json`
- `verification/acceptance-matrix-0.2.1.json`
- `scripts/verify-quick.sh`
- `scripts/verify-full.sh`
- `scripts/verify-nightly.sh`
- `scripts/finalize_verification.py`
- `scripts/svg_quality_oracle.mjs`
- 与 layout、scaling、labels、verification、SVG render 及 E2E 有关的源码和测试

`docs/TRUST_ANCHOR_0.2.2.json` 是本轮开始前由独立审计生成的外置输入，不是实现过程产生的 evidence。其 mode 必须保持 `0444`，SHA-256 必须始终为：

```text
10979b1d7112b7639207405dffe23f534762a02fb047b61540c5e04c955a3224
```

验证器必须从命令行接收这个预期 SHA，先核对 anchor，再读取其中的固定值。不得修改该文件、从新报告反向学习阈值，或把预期 hash 只存放在可与 anchor 同时改写的配置中。若确需改变 anchor，停止任务并请求用户批准；不能自行生成“新锚点”。

先原样执行并记录基线：

```bash
cd '/home/wangrj/桌面/KMH/神经网络绘图工具/NN_DaVinci'
./scripts/verify-quick.sh
./scripts/verify-full.sh
```

若真实 Chrome 仅因受限沙箱权限失败，应在取得对应执行授权后重跑同一命令，并同时记录第一次失败原因；不能把 Chrome 场景跳过。

基线 full 的准确解释应记录为 `runner_result=PASS`、`release_audit=FAIL`：前者只表示现有脚本退出成功，后者源于已确认的矩阵 false-pass、stale checksum 和对抗 oracle 缺口。

当前独立复验基线是：

```text
Python collected/passed = 89/89
failed/errors/skipped/deselected = 0/0/0/0
冻结的 0.2.0 test IDs = 73/73
core line = 1893/2076 = 91.18497%
core branch = 648/778 = 83.29049%
all-package line = 3926/4716 = 83.24852%
all-package branch = 1264/1690 = 74.79290%
Chrome E2E scenarios = 10/10
```

冻结 test-ID 文件当前应为 mode `0444`、73 行，SHA-256：

```text
bd53e5272703b7d79399830ee146db8362c1e5f1e58798ecb95a731c695af838
```

先核对这些事实；若不同，查明原因并报告，不能直接更新基线来掩盖回退。

权威 0.2.2 full 必须从随机路径的 clean source snapshot 运行。快照使用显式 source allowlist，不包含旧 `artifacts/`、`build/`、`dist/`、cache 或 `node_modules/`；Node 依赖在快照的临时目录 clean 安装。记录 consumed-input lineage，任何旧 artifact 路径或 digest 被作为通过输入都必须失败。旧产物只允许在非权威诊断中人工比较。

## 已知必须复现的 0.2.1 缺口

编码前为以下问题建立失败测试，证明它们在旧实现上能失败：

1. 将 fresh evidence 副本中的 `temporary-files.json` 改为 `passed=false`，旧 finalizer 仍会报告矩阵 48/48 和 bundle passed。
2. 对 fresh evidence manifest 重新计算，`logs/full.log` 与 `logs/finalize.log` 会在封口后 hash mismatch。
3. 10,000 个 x 区间全部重合、y 区间互不相交的矩形，当前 `_node_overlap_pairs` 返回 0 pairs 但约耗时 10.30 秒。
4. required text 位于 `transform="scale(0.5 1)"` 时，当前 oracle 错报 `minimum_horizontal_scale=1` 并通过。
5. annotation 大矩形覆盖 node 时，当前 oracle 错报零冲突并通过。
6. 权威模式下缺失 metadata 的 SVG 当前也会通过。

所有篡改都在新临时副本中进行，不得破坏原证据、固定 fixture 或用户文件。

## P0-A：将验收矩阵变成真实可执行门禁

当前 48 是矩阵行数，不是 48 个独立谓词。必须重构为逐行验证系统。

### 数据模型

版本化 0.2.2 matrix schema，每个 blocker 至少包含：

```text
requirement_id
title
validator_id
inputs
evidence_path + JSON Pointer
observed_value_type
comparison/predicate
expected_value/threshold
command_provenance
release_blocker
```

要求：

1. 保留并迁移现有 48 个 requirement ID；如拆分或新增，记录映射和理由，不能静默删除。
2. `validator_id` 映射到代码中 allowlist 的 Python/Node validator；不要从 JSON 任意执行 shell。
3. 启动时验证所有 command/oracle 引用真实存在，修正当前错误或不存在的脚本名。
4. 使用标准 JSON Pointer 解析器检查指针确实存在，验证最终值类型；不能只检查 `#` 前面的文件存在。
5. evidence path 必须规范化并限制在本轮 evidence root 内，拒绝路径穿越和 symlink 逃逸。
6. 每行实际保存 `started_at`、`duration_ms`、`status`、`observed`、`expected`、`evidence_digest` 和失败原因。
7. finalizer 只能汇总逐行结果；禁止用一个全局布尔值批量给所有行赋 `passed`。
8. `release_blocker_checks` 只统计实际执行且有独立结果的 blocker。文件数、诊断 assertions、矩阵行数本身不能算通过次数。
9. 禁止 `always_true`、只读现成 `status`、只检查文件存在等通用 validator。validator registry 要声明支持的 requirement class；同类行可以共享实现，但每行必须使用自己的 inputs/predicate/expected 并产生不同 evidence digest。
10. schema gate 要拒绝所有 blocker 映射到同一永真 validator，并用代码 mutation（让 validator 恒真/跳过谓词）证明测试会失败。
11. P0 和 P1 的全部条目都是 release blockers；任何 `failed`、`error`、`skipped` 或 `not-run` 都使本地 release audit 失败。

新增 `scripts/validate_acceptance_matrix.py`（当前矩阵引用它但文件不存在），并修正至少这些错误引用：

```text
scripts/summarize_verification.py        # 当前不存在
scripts/benchmark_large_graphs.py        # 当前实际文件为单数
scripts/svg_quality_oracle               # 当前实际文件带 .mjs
```

修复当前无法解析的证据指针，包括但不限于：

```text
SVG-02  visual/oracle-fixtures.json#/nested_transform
TEXT-01 visual/seven-architecture-metrics.json#/text
TEXT-04 visual/seven-architecture-metrics.json#/text_measurement
```

### Mutation gate

在 evidence 临时副本上至少逐项执行以下 mutation：

- `temporary-files.passed: true -> false`；
- core line 或 branch 降到阈值以下；
- 一个七架构 collision/crossing 改为非零；
- 一个 E2E scenario 改为 failed；
- 删除或改错一个 JSON Pointer；
- 改动冻结 test-ID 基线或其 hash；
- 删除一个被 matrix 引用的证据文件；
- 将一个值从 number 改成 string，验证 schema/type failure。

每次 mutation 必须满足：对应 requirement 明确失败、bundle 失败、错误信息指出 requirement ID 和实际差异；没有被篡改且不依赖该值的行不应被无差别标成失败。保存机器可读 mutation 报告。

## P0-B：证据包在所有写入结束后原子封口

重新设计 full 收尾流程：

```text
run commands into staging root
→ close every retained log/file descriptor
→ generate final reports and verification.json
→ close finalizer output
→ generate detached SHA256SUMS
→ copy sealed bundle to a second temp directory
→ independent verifier recomputes hashes and semantically replays blockers without writing back
→ atomic rename into local artifacts/v0.2.2/<run_id>
→ verify the final path again without writing back
```

要求：

1. `SHA256SUMS` 覆盖 evidence root 中全部保留的普通文件，包括 `verification.json`、matrix results 和所有日志；只排除 checksum 文件自身，并在 schema 中明确该规则。
2. 生成 checksum 后不得继续写入已登记文件。最后打印到终端的短摘要不得再 `tee` 回已封口日志。
3. finalizer 自身日志先写 staging 外的临时文件，关闭后再作为普通文件加入 bundle；解决当前自我哈希时仍增长的问题。
4. 独立 verifier 不导入 finalizer 或 matrix evaluator 的内部帮助函数，从复制后的目录重算相对路径、size 和 SHA-256；要求 missing/extra/mismatch 全为 0。它还必须独立解析 trust anchor 与 matrix、重新求 coverage/压力阈值、校验 raw test/E2E 状态，并对保留的最终 SVG 重跑 strict oracle。不得只相信矩阵中的 `status`。
5. 如需长期保存 seal attestation，将它作为 bundle 外的 sibling 文件，并用单独的外层 checksum 覆盖；不能一边声称内层已封口，一边把 attestation 追加进去。post-seal verifier 是 matrix 之外的最终外层 release gate，不能伪装成封口前已经完成的矩阵行。
6. `verification.json` 显式包含 schema version、`run_id`、最终相对 evidence root、开始/结束 UTC、命令与退出码、source tree digest、matrix digest 和 checksum 策略。source tree manifest 明确定义源码/配置/文档范围并排除 `artifacts/`、cache 和运行时临时文件，避免自包含摘要。
7. 对 `logs/full.log`、`logs/finalize.log` 写专门回归测试；篡改任意 sealed 文件必须失败。
8. 文档中的最终数字由已封口的 `verification.json` 生成或校验，不能在封口后手工改写 evidence。
9. 不把 SHA 清单描述成 Git 历史。项目仍不是 Git 仓库；未经用户明确授权不得初始化、提交或创建远端。
10. 本地 atomic rename 后从最终路径再做一次 hash/semantic replay；seal 成功前不得出现最终目录，失败 staging 要明确标为 non-authoritative。这里的 promote 只指本地证据目录，不是上传或发布软件包。
11. 保存 consumed-input manifest，列出每个输入的规范路径、来源类别和 digest。权威输入只能来自 clean snapshot、trust anchor、固定 fixture 或本轮临时生成目录；任何旧 `artifacts/`、build/dist/cache 路径命中都失败。

## P0-C：消除零输出情况下的 O(N²) 空间查询

当前 x-sweep active list 不是足够鲁棒的二维索引。请实现二维 interval index、R-tree、层次网格或其他有明确最坏情况策略的方案。

要求：

1. 保持返回 pair 的确定性排序和现有边界接触语义。
2. 小图上继续与朴素 O(N²) oracle 完全一致：至少 100 个固定种子随机语料，并加入零宽高、相同边界、负坐标、嵌套和重复矩形。
3. 新增以下 10k 对抗语料，每项三次执行并报告每次/中位数/最大值：
   - same-x、y-disjoint，期望 0 pairs；
   - same-y、x-disjoint，期望 0 pairs；
   - 嵌套但可由过滤条件排除的矩形；
   - 小规模真实稠密输出，用朴素 oracle 核对 pair 集。
4. 在 Intel i9-10900X、Python 3.13.5 基准机上，10k same-x/y-disjoint 和 same-y/x-disjoint 每次均 ≤2.0 秒；不能只用中位数过线。
5. 对理论输出本身为 O(N²) 的情况提供显式 `max_pairs`、count-only 或 short-circuit API。默认 `max_pairs=1,000,000`；超过预算返回 `complete=false`、`truncated=true`、`lower_bound>=1,000,001`，不得把部分 pair list 当成完整结果。权威 full-geometry 检查遇到 incomplete 必须失败，只有明确的 summary 路径可以降级。
6. 记录 wall time、CPU time、peak RSS、输入规模、输出 pair 数、算法/降级模式；性能测试必须有硬判定。
7. 除点名语料外，加入至少 20 个固定 seed 的 striped、clustered、轴交换、极端 aspect-ratio 和坐标置换分布；1k 规模与朴素 oracle 比对，10k 规模执行性能/内存门禁，防止只为四个名字写特判。
8. 100/1k/10k deep chain 继续通过；wide DAG、SCC、sparse skip、locally dense 语料必须真正执行 layout/summary，而不只是生成并哈希。≤1k 的 full layout+SVG 每次 ≤5 秒、RSS ≤1 GiB、SVG ≤20 MiB；10k focus 每次 ≤20 秒、RSS ≤2 GiB、rendered nodes ≤500、SVG ≤10 MiB。
9. 每个命名语料还要有结构正确性判定：wide DAG 的拓扑/层级与边集合、SCC 的单 component、sparse skip 的全部边与 rank 单调性、locally dense 的节点边集合及 pair-budget 状态均与固定输入相符；“执行过且没抛异常”不算通过。
10. SCC 增加至少 100 个固定种子随机小图，与独立简单参考实现比较 component partition 和 condensation DAG；另保留 10k 深链无递归测试。

不要用提高 recursion limit 或专门识别测试数据的分支过关。

## P0-D：修复 SVG oracle 的 transform、annotation、metadata 和 marker 盲区

oracle 仍须是独立 Node/Chrome 进程，直接读取最终落盘 SVG；不得导入或复制调用 Python layout/quality 的结果。

### 字体和 transform

1. 对累计 screen CTM 的线性部分 `A`，定义 `sx=||A·(1,0)||`、`sy=||A·(0,1)||`、`ctm_horizontal=min(1,sx/sy)`；`sy<=epsilon` 直接失败。另计算 `transform_shape=σ_min(A)/σ_max(A)`，奇异矩阵失败。这样 uniform scale/rotation 为 1，`scale(0.5,1)` 的 horizontal 为 0.5，shear/任一方向严重非均匀也会由 shape ratio 捕获。
2. 在移除 `textLength/lengthAdjust`、CSS/SVG stretch 且保持同字体、字号、字重、字距的离屏 reference clone 上测 natural advance；定义 `glyph_advance=min(1,actual_advance/reference_advance)`，并令 `effective_horizontal=min(ctm_horizontal,glyph_advance)`。不能让 natural 和 actual 同时乘同一个各向异性因子后相除。
3. 覆盖祖先/自身 SVG transform、CSS transform、`font-stretch`、`textLength/lengthAdjust`。用 DOMMatrix/getScreenCTM 与最终 screen-space quad 交叉校验；正常 uniform scale 和 rotation 不得误报。
4. 权威正文/统计文字必须同时满足 `effective_horizontal >= 0.85`、`transform_shape >= 0.85`、字号 ≥7 pt，使用未四舍五入值判定。

### 完整对象几何

1. 以明确 `data-nndv-role` schema 枚举 node、group/container、group-label、annotation、legend、edge、edge-label、marker、required-text 和 decoration。strict publication layer 中未知或缺 role 的图形对象直接失败；不能靠不标 role 逃避检查。
2. 固定默认碰撞矩阵：node-node、edge/marker 与非端点 node、annotation/legend 与 node、group-label/edge-label 与 node、annotation/legend/text 与页面边界均禁止。group container 包含其 member node、端点 path 在 1 CSS px port radius 内连接是允许项。其他例外必须来自渲染前 input-side presentation manifest 的对象 ID 白名单，不能由 SVG 或 oracle 运行时自行声明。
3. crossing 只有在 input-side manifest 中以两条 edge ID 明确登记并带理由时才可称为 explained；七个权威 fixture 的 exception list 必须为空，bridge/junction 仍禁止。unknown/ambiguous exception 失败。
4. 从 marker 定义、`markerUnits`、orient、refX/refY、viewBox 和 CTM 计算实际箭头几何，检查箭头体而非只有 path endpoint。
5. 在 screen space 自适应 flatten 贝塞尔/弧线，最大几何误差 ≤0.25 CSS px；大比例 transform fixture 也要满足，不能把 local path unit 当作 CSS px。
6. bbox/裁切容差固定 0.5 CSS px，edge-node 安全间隙固定 1 CSS px；保持现有 edge-node、unrelated crossing、clipping、node overlap、文本越界和 occupancy 门禁。改变这些值必须先请求用户修改 trust anchor。

### Metadata strict mode

1. publication/full 验收使用 `--require-metadata` strict mode。
2. metadata 必须 schema 合法并匹配 fixture ID、input hash、run ID、节点/边数量及指标版本；缺失、malformed、stale 或来自另一 fixture 均失败。
3. expected fixture/input/run/node/edge 数据来自渲染前生成并单独哈希的 input-side manifest；oracle 不能以同一个 SVG 内的 metadata 同自己比较。
4. oracle 独立重算几何值，再与 metadata 在固定容差内比较；metadata 不能决定 oracle 的实际观测值。

### 必须新增的已知真值 fixtures

每类至少一个 pass 和一个 fail；以下 fail 必须被识别：

- required text 的 `scale(0.5 1)`；
- CSS `font-stretch` 或等价横向压缩；
- annotation 覆盖 node；
- legend 覆盖 node 或出页面；
- 缺失 metadata；
- fixture/input hash 不匹配的 stale metadata；
- marker 箭头体进入非端点 node；
- 大 transform 下曲线穿过 node；
- nested transform 后裁切或文字越界。

同时证明正常 uniform scale、合法 annotation 区域、正确 marker 连接和匹配 metadata 不会被误杀。

## P1：直接相关的收口工作

### 基线与覆盖率

1. full 先用 Prompt 提供的预期 SHA 检查只读 trust anchor，再从 anchor 校验 test-ID 内容、mode 和 hash。mutation test 必须证明 baseline 与 sidecar 一起篡改也会失败；验证器不能从被测文件学习预期值。
2. 保留原 0.2.1 old-core manifest 的独立统计，要求 line 不低于 `1893/2076 = 91.18497110%`、branch 不低于 `648/778 = 83.29048843%`。
3. 另建 expanded-core manifest，至少加入 `src/nn_davinci/labels.py`、`scaling.py`、`verification.py`；expanded-core line ≥88.5%、branch ≥80%。两套统计都必须通过，不能用扩大集合后的较低门槛遮蔽旧 core 回退。
4. all-package line 不低于 `3926/4716 = 83.24851569%`、branch 不低于 `1264/1690 = 74.79289941%`。合法分母变化必须提供逐文件 diff，并按未四舍五入比例判定。
5. 不得通过新增 exclusions、`pragma: no cover`、移除模块或改变发现规则过线。

### CLI 大图恢复路径

1. CLI render 增加 `--focus NODE_ID`、`--focus-hops N`，并提供明确的 summary 命令或 `--summary`。
2. API/CLI/Web 对同一规模限制、错误码和提示使用共享结构；CLI 拒绝消息给出的恢复命令必须可复制执行。
3. 加入 subprocess 级测试：10k 无 focus 快速拒绝，focus 输出 ≤500 节点，summary 成功且结构信息正确。

### 可重建验证环境

1. 保留 library extras 的合理范围，另生成平台明确的 0.2.2 verification lock，至少列出全部实际传递依赖、精确版本、Python/平台/index 来源；能获得 wheel 时记录 hash。
2. full 检查环境与 lock 的差异并运行 `pip check`。在临时 venv 中安装新 wheel/sdist 并验证依赖声明；不能只 `--no-deps` 后宣称完整可重建。
3. Node 在项目临时副本或独立临时目录中从 `package-lock.json` 执行 clean `npm ci` 后运行 E2E/语法检查。不得破坏用户现有 `node_modules`。若本机缓存不足且需要联网，先请求下载权限，并如实记录 offline 边界。
4. 不要把平台 lock 宣称为所有 OS 的通用锁。

### Publication export

1. editor-only 控件与 publication layer 分离；SVG/PDF/PNG/TikZ/EPS/PPTX 的论文导出不得包含折叠按钮 `⊞`、resize handle、selection box 等编辑 affordance。
2. 编辑器交互仍可显示控件；项目 round trip 不丢失 collapse 状态。
3. 为 MoE `Expert ×4` 添加 SVG/PNG 文本与 DOM 回归测试，确保 `×4` provenance 保留而 `⊞` 不出现在 publication export。

### Nightly 语义

当前 `verify-nightly.sh` 只是 full alias。二选一：

- 将 nightly 变为真正额外执行 mutation、property/random differential、对抗性能和 clean dependency rebuild 的门禁，并报告独立 workload；或
- 保持 alias，但在脚本、文档和最终回复中明确它没有新增检查，不把它另计为覆盖。

优先建议第一种，但不得为了名字制造重复计数。

## 固定结构与现有能力不得回退

七个权威输入 SHA 必须保持：

| fixture | SHA-256 |
| --- | --- |
| ResNet | `e0a48b8d3a648732faff89e189d382c436e1a2d2c27cdbb08d2501cfce3e8cf0` |
| Transformer | `bbf22af958c770054980b3ca893ea193afec1eb6fea0de50fb9ff74bdb8897e4` |
| U-Net | `970b9c3abc1b07313ed19bd65c3940e855def73d11ff5925160b75e580631156` |
| RNN | `3b287b1b1b4a1cc1ffcfb9e2020e13db0dfdf98b528234cfbc06376922a1e384` |
| MoE | `634075642c90e34baadb395b340d582764cf804cec2f3de7f0a32a190038661d` |
| Multimodal | `d38061f1c103f4ec654e1778661751e3985c69b8a1e25958addae4da1fc27b83` |
| Diffusion | `c81c2babf0e77e6564b5887e846b2587bb2119c0a2745b9f32773213748dc2e7` |

保持源/预处理后 node ID、edge ID、关键边、RNN `steps=3` provenance 和 MoE `×4` provenance。不得修改输入、删除/隐藏边、加入虚假 bridge/junction 或仅改 metadata 来获得零冲突。

以下能力必须继续从 fresh 临时目录通过：

- 89 个现有 Python tests 与冻结 73 IDs；
- 10 个真实 Chrome E2E 场景；
- SVG/PDF/PNG/TikZ/EPS/PPTX/HTML；
- PDF 字体、TikZ 独立编译、PPTX 可编辑性；
- wheel/sdist 隔离安装与 CLI smoke；
- PyTorch、TorchScript、state_dict、ONNX、Keras、TensorFlow、JAX、MLIR 兼容语料；
- 16 MiB、格式白名单、深层/畸形输入、路径穿越、CSP 和 DOM XSS；
- 当前七架构零 clipping、零 node overlap、零 edge-node collision、零未解释 crossing 及 ≥7 pt 字号。

## 完成标准

只有以下全部满足才可回复“完成”：

1. 外置 trust anchor 保持 mode `0444` 和指定 SHA；现有 89 个 Python test 全部收集并通过；冻结 73 ID 内容、mode 和锚定 hash 通过；failed/errors/skipped/deselected 均为 0。
2. 0.2.2 matrix 的每个 P0/P1 release blocker 实际执行非永真的语义 validator，command/oracle 有效、JSON Pointer 可解析、类型正确；没有 blanket/status-only validator。
3. 所有 mutation cases 正确使对应 requirement 和 bundle 失败，并留下机器可读证据。
4. 所有日志关闭后再封口；复制和最终 atomic-rename 路径都由独立 post-seal verifier 重算并语义重放，missing/extra/hash mismatch 均为 0，所有 blocker 均为 passed。
5. consumed-input lineage 证明权威 run 没有把旧 artifacts/build/dist/cache 当输入；clean source snapshot 的 source/input/output digest 和 run ID 完整。
6. 10k same-x/y-disjoint 与 same-y/x-disjoint 三次均 ≤2 秒；20-seed 分布和随机 differential 通过；默认 million-pair budget 与 incomplete 语义被直接测试。
7. 随机 SCC differential、wide DAG、SCC、sparse skip、locally dense 的结构正确性及时间/RSS/输出门禁通过。
8. 对抗 SVG fixtures 全部正确分类；50% 各向异性文字、annotation 覆盖、缺失/过期 metadata、marker 穿节点和大 transform 曲线必须失败；strict mode 的 unknown role 也必须失败。
9. 七个固定架构在 strict oracle 下继续通过，结构/provenance 不变、crossing exception list 为空，且 publication export 不含编辑控件。
10. old-core line ≥91.18497110%、branch ≥83.29048843%；expanded-core line ≥88.5%、branch ≥80%；all-package line ≥83.24851569%、branch ≥74.79289941%。合法分母变化按未四舍五入比例比较并报告逐文件 diff。
11. API/CLI/Web 大图策略一致，CLI 的 focus/summary 建议可复制执行。
12. Python lock/环境差异、`pip check`、临时 clean Node install、七格式、打包、安全和 Chrome E2E 全部通过；若外部下载是唯一阻塞，先请求权限，不能 skip。
13. README、ACCEPTANCE、KNOWN_LIMITATIONS、0.2.2 release notes 与 sealed `verification.json` 自动校验一致；全部门禁通过后再把包与项目版本统一更新为 0.2.2。

## 权威执行与最终回复

至少提供：

```bash
cd '/home/wangrj/桌面/KMH/神经网络绘图工具/NN_DaVinci'
./scripts/verify-quick.sh
./scripts/verify-full.sh
./scripts/verify-nightly.sh
```

权威 full 必须使用本轮 clean snapshot 和新 staging/root，并只把本轮 sealed evidence 原子提升到本地 `artifacts/v0.2.2/`。这不是外部上传或包发布。成功后最终回复必须列出：

- 修改文件和关键设计选择；
- Python collected/passed/failed/errors/skipped/deselected 与冻结 ID 数；
- 实际执行的 matrix blocker 数及 passed/failed/skipped/not-run，不得只报矩阵行数；
- trust anchor 的期望/实际 SHA、mode，以及 `runner_result` 与独立 `release_audit`；
- mutation tests 的逐类结果；
- core/all-package line、branch、combined 的原始分子、分母和未四舍五入百分比；
- 10k 对抗空间语料三次耗时、peak RSS、pair 数和阈值判定；
- SCC/宽图/稀疏/局部稠密的实际执行结果；
- SVG 对抗 fixture 与七架构 strict oracle 表；
- fresh Python/Node、七格式、E2E、打包和安全结果；
- clean snapshot 与 consumed-input lineage 摘要；
- sealed evidence 路径、run ID、`verification.json`、`SHA256SUMS` 自身 SHA-256，以及复制后和最终路径的独立 hash/semantic replay 结果；
- nightly 是新增 workload 还是 full alias；
- 仍存在的真实限制和可复制命令。

不要初始化 Git、创建提交、上传或发布，除非用户另行明确授权。若在完成上述门禁之前仍有失败，应继续诊断修复，而不是把 warning、known limitation、旧 artifact 或“主功能可用”当成完成。

---
