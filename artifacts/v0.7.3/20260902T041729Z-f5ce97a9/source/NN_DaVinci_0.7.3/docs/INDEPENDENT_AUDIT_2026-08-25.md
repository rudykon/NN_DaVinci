# NN_DaVinci 0.1.0 独立核验报告

核验日期：2026-08-25  
核验对象：当前工作区 `NN_DaVinci` 目录  
核验原则：以当前源码重新运行，不把已有 `artifacts/` 当作成功证据。

## 结论

NN_DaVinci 不是空壳，已经是一个可以运行的、覆盖面较广的 0.1.0 原型：Python API、CLI、Graph IR、多个模型适配器、静态/运行时分析、领域布局、Web 编辑器和七种导出格式均有实质实现。本机的 41 项测试确实全部执行并通过，没有可选依赖测试被跳过。

但是，“已完整实现”不成立。更准确的发布状态应为：**功能型 Alpha / 研究原型**。现有证据主要覆盖小型 happy-path 模型和 API 级行为，尚未证明大型真实模型兼容性、浏览器编辑交互、论文版面可读性、分析数值准确性、性能、安全性和干净环境安装质量。

## 声明核验

| 原声明 | 核验结果 | 说明 |
| --- | --- | --- |
| PyTorch、ONNX、TensorFlow/Keras、JAX/MLIR、JSON/YAML、手工图导入 | 基本属实，但支持边界较窄 | 对应适配器均存在，相关真实依赖测试本机无跳过通过；ONNX、Keras、JAX、TensorFlow 和 MLIR 测试模型都很小，不能代表广泛兼容。 |
| 版本化 Graph IR、静态/运行时分析、TorchLens、TorchCAM、模型差异 | 属实 | 有实质源码和测试；静态 FLOPs、激活内存、感受野属于带覆盖率和限制说明的估算，不应当作所有算子的精确值。 |
| CNN、ResNet、Transformer、U-Net、RNN、MoE、多模态、Diffusion 布局 | 功能存在 | 有确定性和结构测试，也有示例产物；尚无可读性评分、边交叉基准、大图性能门槛或论文栏宽验收。 |
| 完整 Web 编辑器 | 部分属实 | 页面可由真实 Chrome 渲染，布局和 SVG API 成功；源码包含拖动、连线、撤销、折叠、聚焦、评论、主题等逻辑，但没有浏览器 E2E 测试来证明这些交互真正可用。 |
| 动画和 3D 演示 | 应降级表述 | 动画是 SVG 虚线流动；所谓 3D 是对二维 SVG 施加 CSS 透视、旋转和阴影，不是张量几何或网络结构的真正三维可视化。 |
| SVG、PDF、TikZ、PNG、EPS、可编辑 PPTX、交互 HTML 导出 | 属实 | 七种格式均从当前源码重新生成成功。SVG 可解析，PDF 字体嵌入，TikZ 可独立编译，PPTX 内为可编辑线条和形状而非整页位图，HTML 无外部脚本/样式依赖。 |
| Python API、CLI、批处理、报告、可复现项目、插件系统 | 基本属实 | 有源码和单元测试；尚未验证干净虚拟环境下的 wheel/sdist 安装、第三方插件兼容矩阵或跨版本迁移。 |
| 19 个参考项目设计取舍文档 | 属实 | `docs/REFERENCE_DESIGN.md` 中有 19 项记录。 |
| “完整实现并验收” | 不属实 | 目前应标记为 0.1.0 Alpha；现有验收不足以支撑 production-ready 或 feature-complete。 |

## 独立执行结果

### 测试与安装

- `NN_DaVinci/scripts/verify.sh`：41 项测试全部通过，0 failure、0 error，实际输出中没有 skip。
- 测试实际执行了 PyTorch、ONNX、Keras、TensorFlow GraphDef/SavedModel、JAXPR、TorchLens、TorchCAM、Flask、YAML 和 PPTX 集成。
- `envs/python-tools/bin/nnviz --version` 返回 `NN_DaVinci 0.1.0`。
- `pip show nn-davinci` 显示项目以 editable 方式安装，导入路径指向当前 `NN_DaVinci/src`。

### 全新七格式导出

使用当前源码从 `examples/resnet.json` 重新生成 SVG、PDF、TikZ、PNG、EPS、PPTX 和 HTML，七个输出均成功：

- SVG：有效 XML/SVG。
- PDF：PDF 1.7；`pdffonts` 检出嵌入子集字体 `NotoSans-Bold` 和 `NotoSans-Regular`。
- TikZ：设置可写 `TEXMFVAR` 后，`pdflatex -halt-on-error` 编译成功。
- PNG：有效 PNG。
- EPS：有效 DSC Level 3 EPS。
- PPTX：ZIP 容器完整；`python-pptx` 检出 1 页、40 个可编辑对象，其中 30 条线和 10 个 AutoShape，0 个 Picture。
- HTML：有效且自包含；未发现外链脚本或样式表。

### Web 启动

- `bash scripts/run-nn-davinci.sh --no-browser` 可启动 Flask 服务并绑定 `127.0.0.1:8765`。
- `/api/state` 返回 200，声明了 8 个适配器、10 种布局和 7 种导出格式。
- 无头 Chrome 成功加载首页、样式和脚本，并实际调用 `/api/layout` 与 `/api/render`；编辑器和示例网络能够正常显示。

## 主要缺口与可复现问题

### P0：论文版面适配未达到产品目标

使用 ResNet 示例和 `--page double-column --layout resnet` 重新导出时：

- 页面为 840×620 像素（PDF 为 630×465 pt）；
- 非白色内容的包围盒约为 `x=32..802, y=284..345`；
- 整个网络只有约 61 像素高，只占页面高度约 10%，文字在论文尺寸下不可读。

这说明“有双栏预设”不等于“适合论文”。需要内容裁切、自动换行/分段、语义折叠、最终字号约束及可读性验收指标。

### P0：Web 交互没有端到端验收

当前 Web 测试使用 Flask test client，并通过搜索函数名来证明 JavaScript 资产存在；它没有在浏览器中点击、拖动或验证状态变化。当前环境也没有 Playwright/Selenium。节点拖动、连线、撤销/重做、折叠、聚焦、评论、主题编辑、项目往返和导出下载仍需真实浏览器 E2E。

### P1：`verify.sh` 与验收文档并不等价

`scripts/verify.sh` 当前只执行 JavaScript 语法检查、Python compileall、unittest 和一次 Graph IR 校验。它不会：

- 从源码重新生成七格式产物；
- 检查 PDF 字体嵌入；
- 编译 TikZ；
- 检查 PPTX 可编辑性；
- 启动浏览器 E2E；
- 检查测试跳过数、覆盖率、lint、类型、依赖或干净安装。

因此 `docs/ACCEPTANCE.md` 中的若干检查是一次性人工执行记录，不是可重复验收脚本的一部分。

### P1：导入能力需要诚实的兼容边界

- PyTorch `state_dict` 只能生成 `ParameterGroup` 节点，元数据明确为 `structure_available: false`，无法仅从权重恢复网络拓扑。
- JAX 导入接收可调用函数，并要求 `sample_input` 生成 JAXPR；不是任意 JAX/Flax 检查点导入。
- MLIR 是逐行正则提取文本 SSA 的轻量解析器，不是完整 MLIR dialect parser。
- ONNX 测试只有单个 MatMul；Keras 是三层 Functional 模型；TensorFlow 和 JAX 也是很小的示例。控制流、子图、外部权重、共享层、动态形状和真实模型族仍需兼容测试集。

### P1：静态分析是估算而非普遍精确分析

FLOPs 只覆盖若干常见算子，attention、卷积、线性和逐元素公式均依赖已知形状和属性；感受野在 merge 处是保守估算；激活内存不考虑张量生命周期和分配器开销。API 已返回覆盖率和 limitations，但 README 与 UI 应持续显示这些限制，避免把估算值表述成精确值。

### P1：工程与安全基线不足

- 项目目录不是 Git 仓库，缺少提交级来源追踪。
- 没有覆盖率、Python/JavaScript lint、类型检查和干净 wheel/sdist 安装验收。
- Web 上传直接 `read()` 全部内容，没有请求体大小上限。
- Flask 的通用 `Exception` handler 会把缺失的 `/favicon.ico` 从正常 404 变成 500，并写错误堆栈。
- CLI 的 `--format` 帮助文本漏写已经支持的 `html`。
- Web JavaScript/CSS 采用极长压缩式行，后续维护和细粒度测试成本较高。

## 建议发布口径

在下一轮质量门槛通过前，建议对外使用以下描述：

> NN_DaVinci 0.1.0 是一个本地优先的神经网络绘图与结构分析 Alpha 原型，已打通多框架导入、Graph IR、Web 编辑和论文常用格式导出的主要流程。当前重点是论文版面可读性、真实模型兼容、浏览器 E2E、分析准确性和工程加固。

下一轮执行任务见 `docs/NEXT_ROUND_PROMPT.md`。
