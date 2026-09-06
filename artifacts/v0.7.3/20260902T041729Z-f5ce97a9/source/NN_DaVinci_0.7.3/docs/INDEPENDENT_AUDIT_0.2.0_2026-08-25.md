# NN_DaVinci 0.2.0 Beta 独立复验报告

复验日期：2026-08-25  
对象：当前工作区 `NN_DaVinci` 0.2.0  
原则：重新运行门禁、读取原始覆盖率数据，并从最终 SVG/PNG 独立抽查，不把发布报告中的数字直接当作结论。

## 总结结论

本轮反馈的主体内容可信。v0.2.0 不是仅修改文档或伪造测试数字：论文排版、兼容语料、分析口径、Web 安全、Chrome E2E、七格式验收、隔离打包和透视模式改名都有实质代码与实际通过记录。当前版本可以继续称为 **Beta**。

但“最终发布门禁通过”只能理解为“当前脚本按自身规则返回成功”，不能理解为质量问题已经闭环。独立复验发现一项确定的统计错误和两类门禁盲区：

1. `core_branch_coverage=85.96%` 是错误标签；真实核心分支覆盖率是 **78.07%**。
2. 1000 节点顺序图会在布局阶段触发 `RecursionError`。
3. 几何验收没有从最终图独立检测边穿过节点、边交叉及严重横向压缩文字；保留样例中可以复现这些问题。

建议先发布一个范围严格的 **0.2.1 可信度与视觉鲁棒性修正版**，再开始 v0.3 功能扩展。

## 独立重跑结果

### Quick 门禁

`./scripts/verify-quick.sh` 本机重新执行成功：

```text
Ran 73 tests
failures=0 errors=0 skips=0
core_line_coverage=88.93%
脚本所打印的 core_branch_coverage=85.96%（该标签有误，见下文）
```

Ruff、目标模块 mypy、ESLint、Prettier、JavaScript 语法检查、Graph IR 校验均通过。实际框架测试没有依赖 skip 获得成功。

### Full 门禁

`./scripts/verify-full.sh` 本机重新执行成功，耗时 27.52 秒：

```text
NNDV_FULL_RESULT tests=102 failures=0 errors=0 skips=0
python_tests=73 artifact_checks=20 integration_checks=8 e2e_tests=1
browser=150.0.7871.100 elapsed=27.52s
```

本轮实际完成：

- 从新建临时目录生成 SVG、PDF、TikZ、PNG、EPS、PPTX、HTML；
- 20 项文件/结构断言；
- PDF 嵌入字体检查与独立 TikZ 编译；
- wheel/sdist 构建、临时 venv 安装、CLI/资源 smoke test；
- Playwright-core 驱动真实 Chrome 完成编辑器闭环；
- 成功后清理 full 主临时目录。

新一轮 E2E 下载保留于 `/tmp/nndv-e2e-uz02e0`，其中两个项目文件及七种导出文件的签名和类型均正确。

## 反馈逐项核验

| 反馈声明 | 结论 | 独立证据与边界 |
| --- | --- | --- |
| 论文自适应排版 | 部分核实 | ResNet 双栏矢量元数据为 352.8 px、7.35 pt；最终 PNG 非白区域约 804×372 px，已解决旧版 61 px 条带问题。横向文字压缩仍未由原门禁覆盖。 |
| 七架构几何验收 | 部分核实 | 七架构测试和 SVG/PDF/PNG 均存在，字号与节点重叠门槛通过；没有检测边穿节点、边交叉、group/legend 边界及文字压缩率。 |
| 真实 Chrome E2E | 部分核实 | Chrome 150 实际执行，完成项目往返和九次下载；目前是一个长场景，部分动作只触发而未直接断言最终几何。 |
| Web 安全 | 部分核实 | 16 MiB、扩展名/导出白名单、畸形 ONNX、深 JSON、413/400/404、CSP、favicon、DOM XSS 测试均实际通过。服务仍按文档限定为无认证回环工具，不能外推为多用户服务安全。 |
| 兼容语料 | 已核实 | torchvision ResNet18、动态 PyTorch、TorchScript、state_dict、ONNX If/Loop/external data、Keras 分支共享、TF 多签名、JAX pytree、轻量 MLIR 均有真实测试。文档没有把子集夸大为普遍兼容。 |
| 分析可信度 | 部分核实 | 手算卷积、未知算子覆盖率、循环标签、warm-up/统计分布和报告 limitations 均有测试；仍是文档所述的估算系统。 |
| Ruff/mypy/ESLint/Prettier/打包 | 已核实 | 本机重新通过；wheel 在临时 venv 中导入并渲染，Web package data 存在。 |
| 原“3D”改名 | 已核实 | UI、项目新键和文档使用 `perspective_mode`；旧 `three_dimensional` 可迁移且不再写回。 |
| 102 tests | 错误（字段名） | 总数算术成立，但实际是 73 个 Python test case + 20 个脚本断言 + 2 个 PDF/TikZ 检查 + 6 个打包检查 + 1 个长 E2E 场景，应称为 102 release checks。 |
| 核心行覆盖率 88.93% | 已核实 | 原始覆盖率 JSON：1736/1952。 |
| 核心分支覆盖率 85.96% | 错误 | 原始覆盖率 JSON：573/734 = 78.07%；85.96% 是 statements 与 branches 合并后的 coverage.py 综合比例。 |
| 84 个源码 SHA-256 | 部分核实 | 84 个已登记文件与当前文件逐一匹配，0 mismatch；根目录 `eslint.config.mjs`、`LICENSE` 和 `.gitignore` 未纳入。 |
| 实际软件版本 | 已核实 | Python、Chrome、Node、PyTorch/torchvision、ONNX、TF/Keras、JAX、TorchLens/TorchCAM、Flask、CairoSVG、PPTX、TeX/Poppler 均与反馈一致。 |

## 确定问题

### P0：分支覆盖率被错误计算和命名

`verify-quick.sh` 与 `verify-full.sh` 都把 `coverage["percent_covered"]` 输出为 branch coverage。该字段是行与分支机会合并后的综合百分比，不是分支百分比。

核心集合的原始数据为：

```text
covered_lines=1736 / num_statements=1952  -> 88.93%
covered_branches=573 / num_branches=734  -> 78.07%
combined percent_covered                 -> 85.96%
```

全部 Python 包的本轮覆盖率为：

```text
line=81.74%  branch=71.76%  combined=79.10%
```

当前 `coverage report --fail-under=85` 约束的是综合值，不是独立的行覆盖率或分支覆盖率。发布报告和脚本输出必须纠正，并增加分别计算的门槛。

### P0：千节点顺序图会递归崩溃

独立生成 1000 个按顺序连接的 `Linear` 节点时，`LayoutEngine.layout()` 在 `_component_ranks()` 的递归 Tarjan DFS 中触发：

```text
RecursionError: maximum recursion depth exceeded
```

900 节点 fit-content 布局可完成，当前主机约 0.186 秒；到约 1000 层时由 Python 递归深度而不是算法语义决定成败。不能通过提高 `sys.setrecursionlimit` 作为正式修复，应改成迭代 SCC/DFS，并为深链、宽图、循环图和 10k 节点聚焦视图建立压力门禁。

### P0：最终图仍有连线路由质量问题

基于最终布局 route points 与非端点节点矩形的独立线段相交检查发现：

- Diffusion 中 `Timestep -> Denoising U-Net` 路径穿过 `Prompt Condition` 与 `Noise Scheduler` 两个节点；
- Transformer 至少有 1 对无共同端点的边相交/重叠；
- U-Net 至少有 2 对无共同端点的边相交/重叠。

现有 `GeometryQuality` 只要求关键边 ID 仍存在，没有检查关键边是否可辨识。视觉样例中 Transformer、U-Net 和 MoE 的局部线束也较拥挤。因此“关键边存在”不能等同于“关键边清晰”。

### P0：7 pt 门槛没有覆盖横向字形压缩

SVG 渲染器会用 `textLength` 与 `lengthAdjust="spacingAndGlyphs"` 把长统计字符串压入固定宽度。按当前验收使用的同一近似字宽反算：

- ResNet 最严重字符串被压到自然估计宽度的约 **62.4%**；
- Transformer 最严重字符串约为 **64.2%**。

垂直字号仍可计算为 7 pt 以上，但字形被横向压缩约 36%–38%，不符合高质量论文排版。应使用分级信息、换行、缩写或隐藏次要统计，设置最小水平缩放比例，而不是只检查 `textLength <= max-width`。

## 其他需要收紧的地方

### E2E 断言粒度

真实 Chrome 测试的覆盖面很好，但目前全部放在一个 `tests: 1` 长场景中。节点拖动后没有断言坐标变化；对齐/均匀分布主要验证动作没有报错；七格式下载主要检查签名。应拆成独立场景并验证图数据、布局坐标、约束和导出结构。

### 几何验收的独立性

`assess_geometry()` 的 clipping、node overlap、字号和 occupancy 主要读取 `layout.metadata["paper"]`；也就是布局器计算指标，验收器再读取同一指标。SVG parser 当前只独立检查文本字段的一部分。下一版应从最终 SVG 或浏览器 `getBBox()/getComputedTextLength()` 重算完整几何，并将元数据只作为被比对对象。

### 快速开始命令

README 的零安装示例使用当前 shell 的 `python` 并要求直接导出 PDF。本机默认 `/opt/miniconda3/bin/python` 没有 CairoSVG，该示例实际返回 `PDF export requires CairoSVG`。应改为工作区隔离解释器，或先给出只需标准库的 SVG/TikZ 示例，再明确安装 `export` extra 后生成 PDF。

### 可复现性

- Python 可选依赖只有最低版本约束，没有 lock/constraints；环境清单记录了本次环境，但不能自动重建同一环境。
- 84 文件清单漏掉 ESLint 配置等根目录工程文件。
- quick/full 会在项目根留下 `.coverage`、mypy/ruff cache；E2E 成功会保留单独的下载临时目录。
- 项目仍没有 Git 提交身份。该事实记录正确，但 SHA 清单不是版本控制、变更审查和回滚的等价替代品。

## 发布建议

当前可采用以下口径：

> NN_DaVinci 0.2.0 Beta 已通过当前工作区的功能、格式、兼容性、安全、打包和真实浏览器门禁。论文排版回归已显著改善。发布统计中的分支覆盖率需在 0.2.1 纠正；大图递归稳定性、最终 SVG 路由和文字压缩仍是发布前的优先问题。

下一步路线见 `docs/ROADMAP_AFTER_0.2.md`，直接实施 Prompt 见 `docs/NEXT_ROUND_PROMPT_0.2.1.md`。
