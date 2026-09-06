# NN_DaVinci 下一轮实施 Prompt：0.2.1

下面内容可直接复制到新的 Codex 对话：

---

你现在接手工作区中的 `NN_DaVinci`。请直接实施 **NN_DaVinci 0.2.1：发布可信度、大图稳定性与最终矢量图质量修复**。

本轮不是继续扩张新框架或新导出格式。先把 0.2.0 已发现的统计错误、千节点崩溃和视觉验收盲区真正修完。不要只修改测试数字或文档，不要用布局器自己写入的 metadata 作为唯一验收真值。

### 本轮边界

0.2.1 只交付以下最小修复原语：准确发布统计、迭代图算法、现有 focus/聚合路径的大图规模预检与安全拒绝、落盘 SVG/Chrome 的独立质量 oracle，以及七个固定样例的路由和文字修复。

以下产品能力留给 0.3，不得借本轮无限扩张：完整 model→stage→block→layer→operation 五级浏览、惰性画布、异步任务中心/取消 UI、完整导入向导和高级交互式布局优化器。0.2.1 可以为这些能力建立后端接口，但不把它们作为本轮实现范围。

开始前完整阅读：

- `NN_DaVinci/README.md`
- `NN_DaVinci/docs/ACCEPTANCE.md`
- `NN_DaVinci/docs/VERIFICATION_REPORT_0.2.md`
- `NN_DaVinci/docs/KNOWN_LIMITATIONS.md`
- `NN_DaVinci/docs/INDEPENDENT_AUDIT_0.2.0_2026-08-25.md`
- `NN_DaVinci/docs/ROADMAP_AFTER_0.2.md`
- 现有源码、测试和全部 verify/generation 脚本

先原样运行：

```bash
cd '/home/wangrj/桌面/KMH/神经网络绘图工具/NN_DaVinci'
./scripts/verify-quick.sh
./scripts/verify-full.sh
```

记录基线，但不要把现有 `artifacts/` 当作本轮通过证据。当前已知基线是 73 个 Python test case、0 skip；当前 full 会打印 102，但它是混合 release checks 数而不是 102 个独立 test case。

先用测试加载器导出 73 个完全限定的 Python test ID，保存为只读基线并记录 SHA-256。最终必须报告 collected/passed/failed/skipped/deselected；这 73 个 ID 必须逐一仍被收集和通过，不能靠改发现规则、改名遗漏或拆分计数过关。

七个权威视觉输入固定如下。不得修改这些输入来消除失败；实现前先验证 SHA-256，并把源 Graph IR ID 集、预处理后 ID 集、关键边 ID 与 provenance 写入版本化 fixture manifest：

| fixture ID | 输入 SHA-256 | 源节点/边 | 权威预处理后节点/边 | 关键语义边数 |
| --- | --- | ---: | ---: | ---: |
| `resnet` | `e0a48b8d3a648732faff89e189d382c436e1a2d2c27cdbb08d2501cfce3e8cf0` | 10/10 | 10/10 | 3 |
| `transformer` | `bbf22af958c770054980b3ca893ea193afec1eb6fea0de50fb9ff74bdb8897e4` | 12/15 | 12/15 | 13 |
| `unet` | `970b9c3abc1b07313ed19bd65c3940e855def73d11ff5925160b75e580631156` | 9/11 | 9/11 | 3 |
| `rnn` | `3b287b1b1b4a1cc1ffcfb9e2020e13db0dfdf98b528234cfbc06376922a1e384` | 5/4 | 7/6（固定 `steps=3`） | 2 |
| `moe` | `634075642c90e34baadb395b340d582764cf804cec2f3de7f0a32a190038661d` | 8/10 | 5/4（保留 `×4` provenance） | 4 |
| `multimodal` | `d38061f1c103f4ec654e1778661751e3985c69b8a1e25958addae4da1fc27b83` | 8/7 | 8/7 | 4 |
| `diffusion` | `c81c2babf0e77e6564b5887e846b2587bb2119c0a2745b9f32773213748dc2e7` | 6/6 | 6/6 | 1 |

## P0-A：修正发布统计

当前脚本把 coverage.py JSON 的 `percent_covered=85.96%` 错写成 branch coverage。真实核心数据是：

```text
line:   1736 / 1952 = 88.93%
branch:  573 /  734 = 78.07%
combined:             85.96%
```

必须：

1. 分别用 `covered_lines/num_statements`、`covered_branches/num_branches` 计算 line 和 branch；`percent_covered` 只能命名为 combined。
2. quick/full 输出字段改成语义准确的 `checks`、`python_tests`、`artifact_assertions`、`font_tikz_checks`、`packaging_checks`、`e2e_scenarios`。
3. 使用未四舍五入的分数判定门槛：core line ≥88.5%，core branch ≥80%；不得再用 combined coverage 代替 branch 门槛。若分母仍为 734，80% 至少需要覆盖 588 个分支。
4. 同时打印 all-package line/branch/combined 的原始分子、分母和百分比；core 的文件清单与 coverage exclusions 固定为版本化 manifest。未经逐项说明，不得缩小 core、增加 `pragma: no cover`、删除模块或更改 exclusions 来过线。
5. 更新 README、ACCEPTANCE、VERIFICATION_REPORT 和 release notes，纠正旧的 85.96% branch 声明并解释历史错误。
6. 给统计汇总函数本身写单元测试，使用固定 JSON fixture 防止字段再次错标。
7. 当前 all-package 基线为 line 3621/4430 = 81.74%、branch 1141/1590 = 71.76%、combined 4762/6020 = 79.10%；本轮不得回退。若合法重构改变分母，报告逐文件 diff，并证明不是覆盖率投机。

## P0-B：修复深图递归崩溃并建立性能门禁

当前 1000 节点顺序图会在 `layout/engine.py::_component_ranks()` 的递归 Tarjan DFS 中触发 `RecursionError`。

必须：

1. 用迭代 SCC/DFS 或其他不依赖 Python recursion limit 的正确算法替换；禁止以提高 `sys.setrecursionlimit` 作为修复。
2. 添加确定性压力语料：100、1k、10k 节点深链，宽层 DAG，强连通循环，稀疏 skip，以及局部稠密图。固定生成器版本、随机种子 `20260825` 和每个语料的节点/边哈希。
3. 1000 节点完整布局必须无异常；10k 节点至少能完成结构摘要和 focus 邻域布局，不得构造不可控的单页 SVG。
4. 将 `_node_overlap_pairs` 等 O(N²) 热点改为 sweep-line、网格或空间索引，并用朴素实现对小随机图交叉验证正确性。
5. 使用单进程 `time.perf_counter()` 和 `resource.getrusage().ru_maxrss`（Linux）记录 import/layout/render 时间、峰值 RSS、节点/边数、SVG 大小和降级策略；每项运行 3 次，报告每次结果、中位数和最大值，不能只打印不判定。
6. 本机基准固定为 Intel i9-10900X、Python 3.13.5、CPU 路径：
   - 1k 深链完整 layout+SVG：每次 ≤5 秒、峰值 RSS ≤1 GiB、SVG ≤20 MiB；
   - 10k 深链 summary/focus layout+SVG：每次 ≤20 秒、峰值 RSS ≤2 GiB、最终渲染节点 ≤500、SVG ≤10 MiB；
   - 10k 无 focus 的 Web 完整渲染请求不得进入同步全图布局，应在 2 秒内返回 `graph_too_large`（HTTP 422）及可执行的 focus/summary 建议。
7. 0.2.1 只增加统一的后端/CLI/Web 规模预检和安全拒绝，并复用现有 focus/聚合路径；完整惰性渲染、异步任务和取消 UI 留到 0.3。
8. 为新空间索引添加独立 benchmark：10k 个确定性矩形的碰撞查询 ≤2 秒，并与朴素算法在至少 100 个小随机语料上得到完全相同的 pair 集合。

## P0-C：建立独立的最终 SVG 质量 oracle

现有 `assess_geometry()` 大量读取 `layout.metadata["paper"]`，不能作为布局器的独立证明。请新增一个基于最终 SVG 或真实 Chrome DOM 的验收器：

1. oracle 必须在独立进程中读取已经序列化并落盘的 SVG，不能导入 `nn_davinci.layout`、`nn_davinci.quality` 或复用其 bbox/交叉计算实现；需要字体真值时再由 Chrome 读取该 SVG 的 DOM。
2. 正确应用嵌套 transform，使用最终节点、group、annotation、legend、文字和边的实际几何。
3. 独立重算 clipping、页面边距、节点重叠、group label 冲突、文字越界、实际字号和内容占用率。
4. 检测 edge-node intersection、无共同端点的 edge crossing/overlap、箭头落入节点、edge label/节点冲突。
5. 固定容差：bbox/裁切 0.5 CSS px、线段与节点安全间隙 1 CSS px、字体 0.05 pt、occupancy 绝对误差 0.01；端口连接点只在端点半径 1 px 内豁免。若实现证明某项需不同容差，必须先加入带已知真值的 fixture 并在报告中解释，不能在失败后任意放宽。
6. 为 nested transform、切线、共线重叠、端点接触、箭头、文字越界分别提供至少一个应通过和一个应失败的手工 SVG fixture。
7. 把布局 metadata 当作待核对值；oracle 不得反写 metadata，独立值和 metadata 超出容差时必须失败。

至少修复这些已独立复现的问题：

- Diffusion 的 `Timestep -> Denoising U-Net` 路径穿过 `Prompt Condition` 和 `Noise Scheduler`；
- Transformer 至少 1 对无共同端点的边相交/重叠；
- U-Net 至少 2 对无共同端点的边相交/重叠。

七个权威架构必须做到：edge-node collisions = 0；未解释的非相邻边交叉 = 0；关键语义边连续可追踪。

同时执行结构保真门禁：输入 SHA 必须与上表一致；除固定 RNN 展开和 MoE 聚合外，预处理后的 node ID/edge ID 集必须与 fixture manifest 完全相同；RNN/MoE 必须保持完整 provenance。不得删除、隐藏或断开问题边来获得零交叉。七个权威样例不允许新加 bridge/junction 标记来消除失败；bridge/junction 只供其他确实需要的图使用，并必须对应真实拓扑且计入总量。

## P0-D：修复文字“字号合格但横向挤扁”

当前 ResNet 和 Transformer 的长统计字符串被 `textLength/lengthAdjust` 压到自然估计宽度约 62.4% 和 64.2%，虽然垂直字号仍超过 7 pt，但不具备论文可读性。

必须：

1. 为每个文本记录自然宽度、实际宽度和 horizontal scale；使用未四舍五入值判定，最终正文/统计文字不得低于 0.85。
2. 优先采用两行/三行布局、字段缩写、信息密度预设或隐藏次要统计；不得继续无限压缩字形。
3. 提供 renderer 级 `compact`、`paper`、`detailed` 三种确定性标签密度，不要求在 0.2.1 新建高级交互 UI。节点名和 op type 在三种模式中必显；`paper` 权威样例中，已有值的 shape、参数和 FLOPs 必须显示；`detailed` 还保留全部分析字段。不得通过隐藏必显字段过线。
4. 用 Chrome `getComputedTextLength()` 或可靠字体度量补充当前 `len * font * 0.58` 近似；纯 Python fallback 必须标注估算。
5. 在 SVG、PDF 和 TikZ 中检查最终字号、必显文本集合、换行与字体嵌入的一致性；差异由机器可读报告列出并阻断发布。

## P1：拆分并加强浏览器 E2E（仍是 0.2.1 release blocker）

把当前单个长场景拆为至少以下独立场景：

- load/console/security；
- node drag + coordinates；
- connect + edge route constraint；
- align/distribute/lock/hide + geometry；
- undo/redo；
- group/collapse/focus；
- annotation/comment/theme/page/perspective persistence；
- project round trip；
- seven-format downloads；
- DOM XSS。

每个场景使用独立初始化的页面/项目状态；每个动作必须验证状态或几何变化。例如节点拖动要断言前后坐标，align/distribute 要断言对应坐标关系，edge route 要断言控制点，不能只验证“没有报错”。汇总报告 scenario 的稳定 ID、passed/failed/skipped 及核心行为覆盖映射；assertion 数只作诊断，不能作为质量门槛，禁止通过重复断言或只拆测试名注水。

## P1：文档、环境与临时文件（仍是 0.2.1 release blocker）

1. 修正 README 零安装示例：标准库环境先演示 SVG/TikZ；PDF 示例必须明确使用工作区 `envs/python-tools` 或安装 `.[export]`。
2. 环境清单纳入 `eslint.config.mjs`、LICENSE、`.gitignore` 及所有会影响构建/验收的根配置；增加清单自身的完整性测试。
3. 提供可重建本轮 Python 验收环境的 constraints/lock 方案，同时保留 library extras 的合理版本范围。
4. 将 `.coverage`、mypy/ruff cache、quick summary、E2E 下载等放进 run-local 临时目录。成功默认清理；提供 `NNDV_KEEP_DIAGNOSTICS=1` 保留。
5. 项目仍不是 Git 仓库。不要擅自初始化或提交；如果需要正式版本历史，先向用户请求授权。
6. 每次权威 full 运行写入 `artifacts/v0.2.1/<UTC时间>-<run_id>/`：原始日志、机器可读 `verification.json`、硬件/OS/依赖指纹、测试 ID、覆盖率原始 JSON、压力结果、七样例指标、输入/源码/输出 SHA-256。文档中的数字必须从该 JSON 生成或校验，不能手抄临时目录输出。

## 验收矩阵

在编码前创建并持续维护机器可读验收矩阵，字段至少为：

```text
requirement_id | fixture_id/hash | command | independent_oracle | threshold | evidence_path
```

本 Prompt 中每一个“必须”和每一条完成标准都要映射到至少一个阻断检查；最终报告列出矩阵中 passed/failed/skipped/not-run 的数量。不得用 warning 代替失败，不得让没有证据路径的要求被计为通过。

## 完成标准

只有以下条件全部满足才可结束：

1. 0.2.0 的 73 个完整 Python test ID 全部仍被收集并通过；新增测试通过；报告 collected/passed/failed/skipped/deselected，必需集成 0 skip、0 deselected。
2. 用未四舍五入值判定：`core_line_coverage >= 88.5%` 且真实 `core_branch_coverage >= 80%`；core manifest/exclusions 不缩水；all-package line/branch 不低于 0.2.0 基线。core/all-package line、branch、combined 均报告原始分子分母。
3. 1k 深链完整 layout+SVG 每次 ≤5 秒、≤1 GiB RSS、≤20 MiB；10k summary/focus 三次均 ≤20 秒、≤2 GiB RSS、≤500 渲染节点、≤10 MiB；超大 Web 全图请求 2 秒内以 HTTP 422 安全拒绝。空间索引正确性和 10k/2 秒门槛通过。
4. 上表七个固定 SHA fixture 的预处理 Graph IR ID 集、关键边及 provenance 保真；最终 SVG edge-node collision = 0、未解释且无共同端点的 edge crossing = 0，且不能靠删边、改 fixture、藏必显字段或新增 bridge 标记过关。
5. 七架构以 `paper` 密度验收；所有正文/统计文字最终字号 ≥7 pt、horizontal scale ≥0.85，SVG/PDF/TikZ 的必显文本和换行一致性门禁通过。
6. 独立进程从落盘 SVG/Chrome DOM 计算 oracle，不导入布局质量实现；正负 oracle fixtures 全部正确，且独立值与 metadata 在规定容差内一致。
7. 浏览器 E2E 被拆为稳定、独立初始化的场景，并直接断言所有核心编辑状态变化；scenario 计数不能用拆名或重复 assertion 注水。
8. 七格式、PDF 字体、TikZ、PPTX、wheel/sdist 和安全门禁继续从空临时目录通过。
9. 验收矩阵没有 failed/skipped/not-run；每条“必须”都有阻断命令、独立 oracle 和证据路径。P0、P1 都是 0.2.1 release blockers。
10. README、ACCEPTANCE、VERIFICATION_REPORT、KNOWN_LIMITATIONS 和 0.2.1 release notes 与权威 `verification.json` 逐项一致；权威日志、环境指纹、原始数据和哈希已保存在项目内的版本化产物目录。

最终回复必须给出：

- 修改文件和设计决策；
- Python tests 的 collected/passed/failed/skipped/deselected、release checks、稳定 E2E scenarios 的分开计数；assertion 数只作诊断；
- core/all-package 的 line、branch、combined 原始分子分母和百分比；
- 固定语料哈希、100/1k/10k 三次压力结果、峰值 RSS 和阈值判定；
- 七架构的 collision、crossing、字号和 horizontal scale 表；
- 验收矩阵汇总、权威 `verification.json`、新生成产物与环境清单路径；
- 仍存在的限制；
- quick/full/nightly（若新增）可复制命令。

请持续执行到门槛真正通过。不得把 warning、skip、已有 artifact 或自报 metadata 当成完成证据。只有外部下载权限、Git 初始化或会显著改变范围的选择才停下来询问。

---
