# NN_DaVinci 0.2.1 之后的实施路线

## 路线决策

下一轮先发布 0.2.2，不直接进入 0.3。

0.2.1 已证明导入、分析、布局、编辑和多格式导出的主链条可用，七个当前架构样例也明显改善。现在最大的短板不是缺少更多按钮，而是 release gate 本身仍可能错误通过：48 行矩阵没有逐行执行、证据日志哈希在封口后变化、空间索引有最坏情况退化、SVG oracle 对 transform 和 annotation 存在盲区。

因此按以下顺序推进：

```text
0.2.2 证明系统闭环
  ↓
0.3.0 论文语义与大图交互
  ↓
0.4.0 真实模型、插件与跨平台发布
  ↓
1.0   人工论文场景验收与稳定 API
```

版本政策：0.2.x 只接受向后兼容的缺陷修复，以及使既有功能可恢复、可验证所必需的小型选项；新的产品能力进入 0.3.0。0.2.2 中的 CLI focus 参数和 publication layer 分离，分别修复“大图建议不可执行”和“编辑控件泄露到论文导出”，不作为新产品面扩张。

## 阶段一：0.2.2 Verification Closure & Adversarial Geometry

目标：让“通过”真正代表每项需求被执行、证据在落盘后可复验、对抗输入不会绕过质量门槛。

### P0：可执行验收矩阵

- 为每一行定义稳定 `requirement_id`、validator、输入、谓词、期望值和证据 JSON Pointer。
- 在 full 中逐行调用 validator；保存每行实际结果、耗时、观测值、阈值和失败原因。
- 校验 command/oracle 路径存在、JSON Pointer 可解析、证据类型符合 schema。
- finalizer 只汇总行结果，禁止把一个全局状态批量复制为 48 个 passed。
- 加入 mutation tests：分别篡改临时文件、coverage、SVG 指标、E2E 结果、基线哈希和 evidence pointer，要求相应 blocker 与整个 bundle 失败。
- `release blocker checks` 只统计实际执行过谓词的行；结构检查、诊断 assertion 和文件存在性不得重复注水。
- 使用本轮外置的只读 trust anchor 固定旧 test IDs、旧矩阵 ID、输入 SHA、基线和阈值；独立 verifier 接收预期 anchor SHA，而不是从实施者新生成的报告中学习期望值。
- post-seal verifier 从证据副本重新解释 JSON Pointer、重算 coverage/压力判定并重跑落盘 SVG oracle；不能只重算文件哈希或相信矩阵中的 `status`。

### P0：证据归档原子封口

- 将 run 分为执行、关闭所有日志、生成汇总、生成 detached checksums、独立复验五阶段。
- checksum 覆盖所有保留证据及最终 `verification.json`；checksum 文件自身采用明确排除规则。
- 在复制后的证据目录中重新计算全部哈希，要求 mismatch=0，且复验后禁止继续写入已封口文件。
- `verification.json` 显式记录 schema version、run ID、evidence root、源码树摘要、命令、退出码与开始/结束时间。
- 为本轮已发现的 `full.log`、`finalize.log` stale hash 写回归测试。
- 权威 full 从随机路径的 clean source snapshot 运行，快照不含旧 `artifacts/`、build、cache 或 `node_modules`；保存 consumed-input lineage，任何旧 artifact 路径作为通过输入均失败。
- 证据仅在本地通过 atomic rename 提升为权威目录；这不是上传、PyPI/npm 发布或 Git 操作。

### P0：最坏情况可控的空间查询与图算法

- 用二维 interval index、R-tree、层次网格或等价结构替换只在 x 轴剪枝的 active-list 实现。
- 固定测试同 x/不同 y、同 y/不同 x、嵌套矩形、边界接触、重复矩形和真正稠密输出。
- 10k 同 x、y 不相交的零输出语料在基准机上必须 ≤2 秒，并继续与至少 100 个小随机朴素语料逐对比对。
- 对理论上必须返回 O(N²) pairs 的稠密图使用固定默认 pair budget、计数模式或 short-circuit；明确 `complete/truncated/lower_bound` 语义，避免内存失控。
- wide DAG、SCC、sparse skip、locally dense 不只生成哈希，还要实际运行相应 layout/summary 路径。
- 对 SCC 增加至少 100 个确定性随机小图，与简单参考实现比较 component partition 与 condensation DAG。

### P0：对抗 SVG oracle

- 用 CTM 的水平/垂直有效比例计算各向异性缩放；覆盖嵌套 transform、CSS transform、`font-stretch` 和 `textLength`。
- 权威 SVG 必须带 schema 合法、run/fixture 一致的 metadata；缺失、过期或无法解析均失败。
- 检查 annotation、legend、group、edge label、node 与页面边界之间的全部目标冲突。
- 依据 marker 的最终几何检查箭头，而非只检查 path endpoint。
- 在 screen space 自适应展开曲线，规定最大误差；大 transform 下仍满足容差。
- 提供人工真值 fixture：50% 横向压缩、annotation 覆盖节点、缺失/过期 metadata、marker 穿节点、大 transform 曲线。正反例必须被正确分类。
- 保持当前七架构输入、结构和 provenance 不变，并继续通过修复后的 oracle。
- strict publication SVG 中每个图形对象必须有受支持 role 或明确 decoration role；未知 role 失败。碰撞矩阵、允许的 group containment、端口豁免和 crossing exception 均来自输入侧 manifest，不能由 SVG 自己临时宣布“已解释”。

### P1：基线、覆盖率、依赖与 CLI 收口

- 将冻结 test-ID 基线的 SHA 锚点纳入独立配置并验证 mode/hash；不能只让数据和 sidecar 一起可改。
- 保留 0.2.1 旧 core manifest 的 line 91.18497110% / branch 83.29048843% 不回退；另把 `labels.py`、`scaling.py`、`verification.py` 加入 expanded-core，并要求 line ≥88.5%、branch ≥80%。报告两套分母，不能用扩大集合后的较低门槛遮蔽旧 core 回退。
- 生成包含传递依赖、版本、来源、平台和可选 hash 的验证环境锁；在 clean venv 中安装并运行 `pip check`。
- Node 侧至少加入从 `package-lock.json` 的 clean `npm ci` 验证；若必须依赖缓存，报告 cache 命中与离线边界。
- CLI 增加可执行的 `--focus`、`--focus-hops` 及 summary 路径，确保大图拒绝消息给出的命令可复制运行。
- 论文导出移除 `⊞` 等编辑控件；编辑器预览与 publication export 使用明确分离的 layer/profile。
- nightly 要么真正增加 property/adversarial/clean-install 负载，要么明确标注为 full alias，不能另算独立测试覆盖。

### 0.2.2 完成门槛

1. 现有 89 个 Python test 均继续通过，冻结的 73 个 ID 逐一存在；必需集成 0 skip、0 deselected。P0 和 P1 全部是 0.2.2 release blockers。
2. 矩阵每行都有实际 validator 结果；所有 command/oracle 存在，所有 JSON Pointer 可解析；mutation tests 能使对应行和 bundle 确定失败。
3. 封口后独立复制并重算证据目录，全部文件 checksum mismatch=0。
4. 10k 同 x、y 分离语料三次均 ≤2 秒；小随机 differential 完全一致；稠密输出有资源上限。
5. 对抗 SVG fixtures 全部分类正确；50% 各向异性文字、annotation 覆盖和缺 metadata 必须失败。
6. 七个固定架构在新 oracle 下保持结构、provenance、字号、零裁切、零节点重叠、零 edge-node collision 和零未解释 crossing。
7. 旧 core manifest 不低于 0.2.1 的 line 91.18497110% / branch 83.29048843%；expanded-core 满足 line ≥88.5%、branch ≥80%；all-package line/branch 不低于 0.2.1。
8. clean Python/Node 安装、wheel/sdist、七格式、字体、TikZ、PPTX、Web 安全及 10 个 Chrome E2E 场景继续通过。

## 阶段二：0.3.0 论文语义与大图交互

0.2.2 闭环后，再推进用户能直接感知的先进绘图能力。

### 五级语义浏览

- model → stage → block → layer → operation 五级缩放与钻取。
- 自动识别 residual、attention、encoder/decoder、U-Net skip、MoE expert、diffusion loop 和重复 block。
- “忠实结构图”和“论文概念图”明确分开；每个摘要节点保留到原始节点/边的双向 provenance。
- focus、折叠、搜索、分析指标和运行时证据在各层级间保持选择状态。

### 惰性画布与任务控制

- 只实例化视口附近元素，支持大图平移、缩放和逐层加载。
- layout/import/analyze/export 进入可取消任务，显示阶段、耗时、资源预算和可恢复错误。
- 在同步预检的基础上提供后台计算，但本地 Flask 仍默认只监听 loopback。

### 论文成图优化器

- 联合优化节点重叠、边穿节点、交叉、弯折、路径长度、对称性、空白、标签和关键边显著度。
- 支持单栏、双栏、跨双栏和多 panel 的实际尺寸 proof preview。
- 提供简洁、论文、详细、教学、黑白印刷和色盲友好预设。
- 将自动建议显示为可审查 diff，保留锁定节点和人工路由，不静默重写用户布局。

### 导入向导与结构分析

- 自动检测格式、所需 sample input、动态图采样边界和预计图规模。
- 推荐 graph/module/operation 视图、摘要层级、页面规格和标签密度。
- 将参数、FLOPs/MACs、激活、感受野、运行时、梯度和 CAM 的覆盖率与未知项可视化。
- 对两个模型或两个 checkpoint 的结构差异提供稳定匹配、置信度和可导出的 diff 图。

## 阶段三：0.4.0 真实模型、插件与发布工程

- 建立无需下载权重即可构造的 ResNet50、ViT、BERT encoder、U-Net、Diffusion U-Net 和 MoE 语料。
- 对 framework graph、module graph、operation graph 的语义保真、耗时和图规模做基准。
- 稳定插件 API、隔离失败插件，并为导入器、分析器、布局器和导出器提供模板。
- 在用户授权后建立 Git 历史、tag、changelog、SBOM 和签名发布物。
- 覆盖 Python 3.10–3.13、Linux/Windows/macOS 及主要框架最小/当前版本。

## 阶段四：1.0 人工论文场景验收

- 选择至少三类真实论文架构，从模型导入到论文图完成全流程重画，不复制原图风格。
- 让未参与开发者在 15 分钟内完成导入、摘要、微调和 SVG/PDF 导出。
- 在 LaTeX 单栏/双栏 proof、PPTX 和矢量编辑器中检查实际字号、线宽、颜色、字体与可编辑性。
- 记录首图完成时间、人工操作数、撤销次数、导出后修图次数和失败任务恢复率。
- 冻结 Graph IR、项目文件和插件 API 的 1.0 兼容策略。

## 暂不自动执行的事项

- 不擅自初始化 Git、创建远程仓库或发布软件包；这些需要用户明确授权。
- 不把本地无认证 Flask 服务描述为公网协作服务。
- 不把当前七个样例通过等同于所有第三方 SVG 或所有真实模型均受支持。
- 不以增加检查计数、复制 assertion 或保留旧 artifact 代替新一轮证据。
