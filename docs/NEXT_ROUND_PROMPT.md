# NN_DaVinci 下一轮实施 Prompt（v0.2 质量加固）

下面内容可直接复制到新的 Codex 对话中：

---

你现在接手工作区中的 `NN_DaVinci`。请直接实施 **v0.2 质量加固**，不要重写项目，也不要继续堆砌未经验证的新功能。目标是把当前“功能广泛的 0.1.0 Alpha”推进到真正可用于论文制图和结构分析的可靠 Beta。

开始前必须完整阅读：

- `NN_DaVinci/README.md`
- `NN_DaVinci/docs/REQUIREMENTS.md`
- `NN_DaVinci/docs/ARCHITECTURE.md`
- `NN_DaVinci/docs/ACCEPTANCE.md`
- `NN_DaVinci/docs/INDEPENDENT_AUDIT_2026-08-25.md`
- 现有源码和全部测试

先原样运行 `NN_DaVinci/scripts/verify.sh` 建立基线，然后实施以下工作。已有 41 项测试必须始终保持通过。不要用预先存在的 `artifacts/` 代替新生成结果，不得把 skip 当作“已验证”，不得在没有证据时使用“完整实现”“全部兼容”或“生产可用”等表述。

## P0：让论文预设真正可读

修复当前 ResNet 在 `double-column` 页面中被压缩到约 61 像素高的问题。设计并实现面向论文的自适应排版机制，至少包括：

1. 内容裁切和页面留白控制；
2. 超宽网络自动换行、分段或 stage-aware 排版；
3. 重复块自动聚合/折叠，并允许显示 `×N`；
4. residual、U-Net skip、attention、MoE routing 等关键边保持可辨识；
5. 在 single-column、double-column、widescreen 和 fit-content 间做明确选择；
6. 根据最终缩放比例保证正文最终字号不低于 7 pt，并在无法满足时给出可操作警告，而不是静默生成不可读图；
7. 支持用户锁定位置和手工路由后再次适配页面，不破坏锁定内容。

为 ResNet、Transformer、U-Net、RNN、MoE、多模态和 Diffusion 建立几何质量测试。测试至少检查：无裁切、节点不重叠、文本不越界、最终字号、内容占用率、关键边存在、布局确定性。保留一组新生成的 SVG/PDF/PNG 作为 v0.2 视觉验收样例，并在文档中给出选择该布局的理由。不要只做像素截图比较。

## P0：补齐真实浏览器 E2E

添加 Playwright（优先）或等价浏览器测试，真实启动本地服务并验证：

- 首页加载，无未处理的 console error；
- 从组件面板拖入节点；
- 拖动节点、连接两个节点、编辑连线路由；
- 多选、复制、成组、折叠/展开、聚焦/恢复；
- 锁定、隐藏、对齐、均匀分布；
- 撤销/重做确实恢复图和布局状态；
- 注释、评论、主题和排版参数可保存；
- 动画和透视模式状态可切换并随项目往返；
- 导入 `.nndv.json` 后图、布局、评论和展示状态保持；
- SVG、PDF、TikZ、PNG、EPS、PPTX、HTML 下载均成功；
- 恶意节点名不会形成 DOM XSS。

当前环境没有 Playwright/Selenium。如果必须下载浏览器或依赖，只安装到工作区隔离环境，并先按系统权限流程申请；不要安装到系统或用户全局环境。若客观上无法安装，仍需先完成可提交的 E2E 测试和配置，并明确记录唯一阻塞，不能声称已通过。

同时修复已发现问题：缺失 `/favicon.ico` 应返回正常 404 或提供 favicon，不能被通用异常处理器转换成 500。HTTP 4xx 异常应保留原状态码。

## P0：把完整验收变成一条可重复命令

扩展 `NN_DaVinci/scripts/verify.sh`，或提供清晰的 `verify-quick.sh` 与 `verify-full.sh`：

- 从空临时目录重新生成七种格式；
- 校验文件签名及非空内容；
- 用 XML parser 校验 SVG；
- 用 `pdffonts` 断言 PDF 字体嵌入；
- 用独立 `pdflatex` 编译新生成的 TikZ，并为沙箱设置可写 `TEXMFVAR`；
- 用 `python-pptx` 断言 PPTX 由可编辑形状/连线组成，而不是整页位图；
- 断言交互 HTML 自包含且安全；
- 运行浏览器 E2E；
- 输出测试总数、失败数、错误数、跳过数、覆盖率和耗时；
- full 模式下，声明为必需的集成若发生 skip 必须失败；
- 所有检查只使用本轮新生成的临时产物，失败时保留诊断路径，成功时可清理。

更新 `docs/ACCEPTANCE.md`，使其中每项通过声明都能映射到自动化命令和测试名称。

## P1：真实模型兼容矩阵

建立小而有代表性的本地兼容语料，至少覆盖：

- PyTorch：`torchvision` ResNet18、共享权重、动态控制流、嵌套输出、TorchScript；
- PyTorch `state_dict`：明确显示“仅权重分组、无法恢复拓扑”，不能伪装成完整网络结构；
- ONNX：动态维度、initializer、If/Loop 子图、external data、多个输入输出；
- Keras：分支、残差、共享 layer、嵌套 Model；
- TensorFlow：GraphDef、SavedModel、多签名和控制边；
- JAX：pytree 输入、多个输出，并明确其接口是 callable + sample input -> JAXPR；
- MLIR：为当前轻量 SSA parser 明确支持语法和拒绝行为；若不引入官方 parser，不得称为完整 MLIR 支持。

每个语料都校验节点/边、shape、参数量、层级、共享权重和错误提示中的关键不变量。产出 `docs/COMPATIBILITY.md`，区分“已测试”“实验性”“不支持”，并记录框架版本。

## P1：分析准确性和可信度

为参数量、FLOPs/MACs、激活内存、深度、感受野和运行时间建立基准：

- 与至少一种可信实现或手工可验证公式对照；
- 明确 FLOPs 的 multiply-add 计数约定；
- 对动态 shape、未知算子、共享参数、branch/merge 和循环给出覆盖率；
- UI 和报告中必须同时显示数值、覆盖率、估算/实测标签和 limitations；
- 未覆盖部分不能按 0 冒充完整总量；
- 运行时间测试使用 warm-up、多次迭代和统计量，避免把单次噪声当结论。

## P1：工程、维护性和安全

1. 将极长行的 Web JavaScript/CSS 拆成可维护模块或至少规范化格式，并增加 JS lint；保持无构建或轻量构建均可，但要说明取舍。
2. 添加 Python lint、类型检查和覆盖率；核心 IR、布局、导出、项目往返与安全解析目标行覆盖率不低于 85%。第三方框架分支可单独统计。
3. 增加请求体/上传大小上限、格式白名单、畸形 JSON/ONNX、超深嵌套、路径穿越和错误状态码测试。
4. 修正 CLI `--format` 帮助文本，使其包含 `html`。
5. 构建 wheel 和 sdist，在新的临时虚拟环境中完成安装、导入、`nnviz --version`、基本渲染和 package-data/Web 资产检查。
6. 项目当前不是 Git 仓库。不要擅自初始化或提交 Git；在验收报告中明确这一事实，并生成源码/环境版本清单以便追踪。

## P1：纠正“3D”命名

当前实现只是对二维 SVG 使用 CSS perspective/rotate/drop-shadow。默认方案是将 UI 和文档统一改名为“透视展示模式”。只有当你真正实现由 tensor shape 驱动的三维块体、相机控制、深度/遮挡逻辑，并有 E2E 和视觉验收时，才可以继续称为“3D 视图”。

## 完成标准

只有同时满足以下条件才可结束：

1. 原 41 项测试保持通过，新增测试全部通过；完整验收中必需集成 0 skip。
2. 七格式从空临时目录重新生成并逐项验证；TikZ 独立编译，PDF 字体嵌入，PPTX 可编辑。
3. 浏览器 E2E 真实执行并覆盖核心编辑闭环；浏览器控制台无未处理错误。
4. ResNet 等七类架构在论文页面预设下满足可读性指标，当前 61 像素高问题不再出现。
5. 真实模型兼容矩阵和分析准确性测试有可复现结果。
6. `verify-full.sh` 一条命令可重跑上述验收，不依赖已有 artifacts。
7. README、ACCEPTANCE、COMPATIBILITY、已知限制和发布说明与实际证据一致。

完成后请给出：

- 实际修改摘要和关键文件；
- 精确测试数、失败数、错误数、跳过数、覆盖率和耗时；
- 浏览器及各框架的实际版本；
- 新生成验收产物路径；
- 仍未解决的限制，不得隐藏或模糊处理；
- 可直接复制执行的 quick/full 验收命令。

请持续执行到上述目标真正完成；只有涉及外部下载权限或会改变任务范围的关键选择时才停下来询问。

---
