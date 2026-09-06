# NN_DaVinci 0.2 之后的实施路线

## 决策

下一轮不继续扩张框架和导出格式，先完成 0.2.1。原因是当前核心流程已经打通，最高价值工作从“功能有没有”转向“证据是否可信、复杂模型是否稳定、最终论文图是否真的清晰”。

0.2.1 的范围只包括：修正统计口径、替换递归图算法、为现有 focus/聚合路径建立大图安全策略、从最终产物独立验收几何，以及修复七个固定样例。完整的五级多分辨率浏览、惰性画布、异步任务/取消 UI、导入向导和高级信息密度交互留到 0.3，避免修正版变成功能扩张版。

## 阶段一：0.2.1 可信度与视觉鲁棒性修复

### P0：发布数字必须准确

- 分别计算 line、branch、combined coverage；修正现有 85.96% 的错误标签。
- 将总字段从 `tests=102` 改成 `checks=...`，保留 `python_tests`、`artifact_assertions`、`packaging_checks` 和 `e2e_scenarios` 明细。
- 使用未四舍五入原始值判定；核心 line 不低于 88.5%，核心真实 branch 不低于 80%，且不得缩小核心模块清单、增加 coverage 排除或删除代码来过线。
- 同时报告全包覆盖率，不用“核心”数字遮蔽 CLI、batch、API 和 editor 的低覆盖路径。

### P0：大图稳定性

- 将递归 SCC/DFS 改为迭代实现；1000 节点深链不得依赖 Python recursion limit。
- 为 100、1k、10k 节点建立深链、宽层、强循环、稀疏跳连和稠密局部子图语料。
- 将节点碰撞检测从 O(N²) 全对比较改为 sweep-line、网格或空间索引。
- 0.2.1 只复用现有 focus/聚合能力并增加统一规模预检：10k 图走受限摘要/聚焦路径，Web 对无 focus 的超大完整渲染快速拒绝并给出可操作提示；不在本轮新建完整惰性画布。
- 固定语料、随机种子、重复次数和计量方法；记录布局时间、SVG 大小、峰值 RSS 和降级策略，并在 i9-10900X/Python 3.13 基准主机上执行预先写死的上限。

### P0：从最终图独立验收视觉质量

- 从最终 SVG transform 后的几何或 Chrome SVG DOM 重算 bbox、字号、文本长度和裁切。
- 检查 edge-node intersection、非相邻 edge crossing/overlap、箭头遮挡、edge label 冲突、group/legend/annotation 越界。
- 修复已知 Diffusion 穿两个节点、Transformer 一组交叉、U-Net 两组交叉。
- 禁止正文或统计文字水平压缩到自然宽度的 85% 以下；优先换行、缩写、语义分级和隐藏次要统计。
- 建立“结构完整性”和“视觉清晰度”两个分开的指标，关键边不仅要存在，还必须可追踪。
- 锁定七个输入文件的 SHA-256、预处理后节点/边集合与关键语义边；不得通过删边、改 fixture、隐藏必显字段或把所有交叉标成 bridge 来获得零缺陷。
- oracle 必须从落盘后的 SVG/真实 Chrome 独立进程测量，不得导入布局质量实现；使用已知正负样例和明确的像素/点容差校准。

### P1（仍是 0.2.1 发布阻断项）：测试和复现卫生

- 把单体 Chrome 场景拆成可独立定位的编辑、持久化、导出、安全与无障碍场景。
- 对节点拖动、连线路由、对齐、分布、锁定和撤销重做直接断言坐标/约束变化。
- 保存 0.2.0 的完整 Python test ID 基线；报告 collected/passed/failed/skipped/deselected，E2E 场景需独立初始化，不能靠拆名称或重复断言注水。
- 修正 README 零安装命令；加入标准库-only 与全功能环境两条清晰路径。
- 环境清单纳入所有工程配置；提供 Python constraints/lock 或可重复构建说明。
- 将 coverage、mypy、ruff 和 E2E 临时文件定向到 run-local 目录；成功默认清理，可用显式参数保留诊断。
- 每次权威 full 运行保留机器可读汇总、完整日志、主机/依赖指纹、输入与输出哈希；报告数字由该汇总生成，不手抄。
- 若需要 Git，请先取得用户授权；不要在实施任务中静默初始化或提交。

### 0.2.1 完成门槛

1. 当前 73 个完整 test ID 均仍被收集并通过；新增测试与所有 release checks 通过，必需集成 0 skip、0 deselected。
2. 报告真实 core/all-package line、branch、combined 的原始分子分母；字段含义和阈值函数有固定 fixture 测试。
3. 以未四舍五入值判定：核心 branch ≥80%，核心 line ≥88.5%；覆盖范围和 exclusions 不得缩水。
4. 1000 节点深链完整布局和 SVG 在 5 秒、1 GiB RSS 内完成；10k 节点摘要/聚焦路径三次运行均在 20 秒、2 GiB RSS 内，输出不超过 500 节点和 10 MiB SVG。该绝对上限适用于 i9-10900X/Python 3.13 基准主机；其他主机同时报告归一化结果。
5. 七个固定 SHA 输入的 Graph IR 节点/边及摘要 provenance 保持；edge-node collisions = 0、未解释且无共同端点的 edge crossings = 0。权威样例不允许通过新增 bridge 标记消除失败。
6. 权威样例使用 `paper` 标签密度，必显字段保持；正文和统计文字最小水平缩放比例 ≥0.85，最终正文 ≥7 pt。
7. 几何数据由落盘 SVG/独立 Chrome 进程产生，不导入布局质量实现；独立值与 metadata 在逐项规定容差内一致，已知正负 oracle fixtures 全部判定正确。
8. 每个“必须”都在验收矩阵中映射到 fixture、命令、oracle、阈值和证据路径；P1 同样是 0.2.1 release blocker。
9. quick/full 从干净临时目录可重复运行；权威 full 保留可复验汇总与哈希，报告和文档数字由该汇总生成并一致。

## 阶段二：0.3.0 论文语义与高级绘图

0.2.1 门槛通过后再进入以下功能：

### 多分辨率结构视图

- 同一模型提供 model → stage → block → layer → operation 五级视图。
- 自动识别 residual、attention、encoder/decoder、U-Net skip、MoE expert、diffusion loop 和重复 block。
- 在“忠实结构图”和“论文概念图”间显式切换，记录每个摘要节点映射到哪些原始节点。
- 支持从论文概念图一键钻取到运行时、梯度、CAM 和 shape 证据。
- 在 0.2.1 的规模预检与受限 focus 原语之上，实现完整惰性画布、异步任务取消、导入向导和交互式层级切换。

### 以论文成图为中心的布局优化器

- 将节点重叠、边穿节点、交叉数、弯折数、路径长度、对称性、空白平衡、文字压缩和关键边显著度组成可解释目标函数。
- 为 ResNet、Transformer、U-Net、MoE、多模态和 Diffusion 提供结构专用模板与可编辑约束。
- 加入最终栏宽/字号 proof preview，支持单栏、双栏、横跨双栏和多 panel。
- 提供简洁、详细、教学、黑白印刷及色盲友好等信息密度预设。

### 真实世界模型与工作流

- 用本地可构建的 ResNet50、ViT、BERT 类 encoder、真实 U-Net、Diffusion U-Net 和 MoE 建立不下载权重的结构语料。
- 对比 framework graph、module graph、operation graph 的节点数、语义保真度与生成耗时。
- 增加导入向导：检测格式、提示 sample input、预估图规模、推荐摘要层级和页面。
- 增加实际尺寸导出预览、问题列表和“一键修复可读性”建议。

### 发布工程

- 在用户授权后建立正式 Git 历史、tag 和 changelog。
- 建立 Python 3.10–3.13、框架最小/当前版本、Linux/Windows/macOS 的 CI 矩阵。
- 提供 wheel/sdist、依赖约束、SBOM、源码与产物校验和及离线 smoke test。
- 将性能、兼容性、视觉质量和安全门禁拆成清晰的 quick、full、nightly 三层。

## 阶段三：人工论文场景验收

- 选择至少三篇不同架构论文，使用 NN_DaVinci 重画其结构而不复制原图风格。
- 让未参与开发的人在 15 分钟内完成导入、摘要、微调和 SVG/PDF 导出。
- 在 LaTeX 双栏 proof 和 PowerPoint 中按实际尺寸检查字号、线宽、颜色、字体嵌入与可编辑性。
- 记录人工修改次数、完成时间和主要卡点，以此决定 1.0 之前的 UX 优先级。
