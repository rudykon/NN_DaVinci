# NN_DaVinci 0.7.0 功能完成矩阵

本矩阵记录权威 0.6.1 基线、0.7.0 实现位置、直接测试证据和验收合同。“实现”表示已有可调用代码与有意义的 focused test；“发布通过”只能由新的 `artifacts/v0.7.0/<run_id>/verification.json` 声明。`/tmp`、父制品、生成器布尔值和本文档都不能代替它。

## 基线与当前证据

- 冻结父版：0.6.1 Run ID `20260830T122225Z-0f6f36c2`；294 个 allow-listed 源文件，digest `26469ab2eb7fd2d10a4d058ec7061017f8de005d714ca2760e2412a414d7ad7f`。
- 编码前 clean-copy 回放：246/246 Python test IDs 通过，0 skip/error；all-package line 88.00%、branch 78.46%；14/14 父版生产 SVG 通过独立 Chrome oracle。
- 0.7 focused 事实：Scene core/projection/export/API、ruff/mypy/lint/format、CLI Scene Project create→validate→reproduce 均有直接检查；CLI 会持久化精确 `semantic_view.document`。WebGL 绘制真实 route segments 与投影 Scene labels；Start Center 暴露精确七个非空、template-only 的 3D Scene 模板。
- 候选 Scene corpus：`/tmp/nndv-070-scene-corpus-release-corpus-1`，14/14 Scene，14 Project 1.4，140 个 Scene exports，14 个 comparison 文件（七个真实模型各一对 SVG/PNG），168 文件，74,993,641 bytes，tree digest `ec674f5bca0455436d05b2a9164c1915a3ee668fe87d41c1092e2b8695623814`。`/tmp/nndv-070-scene-corpus-validation-report-2.json` 独立验证 14/14 PASS，SHA-256 `55a6beb4354fa763e7edf76a155145eb38d6d8a02c2e89f5bcf9d61768b28858`。该 `/tmp` 结果仅是开发证据；发布结论只读制品内的同源 corpus 报告与 `verification.json`。
- 本地三轮性能预检：250/1000 对象首次可交互 max 151.959/662.209 ms；500 对象 orbit p95 17.578 ms；selection/Inspector median 0.204 ms；CPU publication projection median 334.060/1462.243 ms；10k/50k 均有界到 249 对象；2D median 146.424 ms vs 141.115 ms，+3.762%。报告当前在 `/tmp/nndv-070-scene-performance.json`，尚非 artifact 权威值。
- 发布合同：full driver 绑定精确 246-ID/coverage、corpus、migration、performance、至少 44 张浏览器 PNG、10 个非空 Scene 格式下载和独立视觉报告。截图 manifest 覆盖四主题、七精确视口、七真模型 2D/3D 对和七个 Start Center 3D 模板；具体结果只读制品 `verification.json`。

## 导入、事实层与分析

| 功能 | 0.6.1 状态 | 实现文件 | 直接测试/证据 | 0.7.0 处理结果 | 真实限制 |
|---|---|---|---|---|---|
| PyTorch Module/FX/sampled runtime | 部分 | `adapters/pytorch.py`, `api.py`, `import_wizard.py` | `test_compatibility_matrix.py`, `test_pytorch_runtime.py` | 保留；可进入 Graph→Semantic→Scene | custom C++/CUDA/distributed/任意控制流未广泛证明；dynamic 只是采样路径 |
| TorchScript | 部分 | `adapters/pytorch.py` | `test_compatibility_matrix.py` | 保留固定 traced corpus | 上游已趋向 `torch.export`；不宣称普遍支持 |
| PyTorch `state_dict` | 部分（weights-only） | `adapters/pytorch.py`, `import_wizard.py` | compatibility/paper tests | 明确禁止生成虚构 2D/3D topology | 只有 `ParameterGroup`，无 forward/branch/call 事实 |
| ONNX | 部分 | `adapters/onnx.py` | compatibility/ONNX/Web tests | 保留；Graph 后端可生成 Scene | 证据限于固定的 dynamic/multi-I/O/If/Loop/external-data 子集 |
| TensorFlow GraphDef/SavedModel | 部分 | `adapters/tensorflow.py` | compatibility/extended tests | 保留；通过统一 Graph 入口接 Scene | function/resource/asset/composite 仅有限覆盖 |
| Keras Functional | 部分 | `adapters/keras.py` | compatibility/extended tests | 保留 | subclass/custom object/backend-specific layer 超出已证范围 |
| JAX/JAXPR | 部分 | `adapters/jax.py` | compatibility/extended tests | 保留 | 需 callable + 代表性 sample input；checkpoint 不恢复拓扑 |
| textual MLIR | 部分 | `adapters/jax.py::MlirAdapter` | compatibility/extended tests | 保留 | 轻量单结果 SSA extractor，不是官方 parser/dialect validator |
| JSON/YAML/Graph IR/手工图 | 完整（基线边界） | `adapters/manual.py`, `adapters/config.py`, `editor.py` | core/semantic/extended tests | 保留；新增手工 Scene JSON/空白 3D | YAML 可选依赖；手工 Scene 不自动获得模型语义 |
| Import Wizard/trusted-input gate | 完整（基线边界） | `import_wizard.py`, `server.py`, `web/app.js` | semantic/security tests | 保留安全门禁 | Python/pickle 必须显式信任；检查本身不执行代码 |
| Graph IR 1.0 | 完整 | `ir.py`, adapters | core/semantic/compatibility tests | 保留为唯一模型事实层 | 不填补源格式无法证明的事实 |
| Semantic View 1.0 | 完整（证据边界） | `semantic.py` | semantic/real-model tests | 保留五级层次与双向索引；Figure/Scene 共享证据选择 | custom pattern 可保持 `unknown`；别名不改 ID |
| 静态分析 | 部分 | `analysis/static.py` | analysis/core tests | 保留；Scene Inspector 可通过 provenance 追溯 | FLOPs/activation/感受野只对覆盖算子与已知 shape 有意义 |
| 运行时/TorchLens/TorchCAM | 部分 | `analysis/runtime.py`, `analysis/torchlens.py`, `analysis/explain.py`, `api.py` | runtime/accuracy tests | 保留；Scene 仅显示有证据的记录 | sampled path；timing/memory 依赖环境；CAM 需兼容 layer |
| 模型 Diff | 部分 | `analysis/diff.py`, `diff_corpus.py` | core/paper tests | 保留；真实模型 corpus 增加 2D/3D comparison 图 | probable matching 为启发式，概念等价需复核 |
| 大图 summary/focus/viewport/search | 完整（有界策略） | `viewport.py`, `scaling.py`, `model_figure.py`, `model_scene.py`, `server.py` | large-graph/semantic/Scene model tests | Scene default 250；10k/50k 预检均 249 对象 | 不支持同步全量 10k/50k DOM/mesh；必须 focus/summary |
| Structure Lens | 部分 | `structure_lens.py`, `model_figure.py`, `server.py`, `web/app.js` | Structure Lens/Figure API + browser contract | 2D 能力保留；E2E 覆盖 bounded Lens 结果进入 Scene | 自定义/超预算 Lens 结果仍受 evidence 与 budget 边界；发布结论只读制品报告 |

## 2D Figure、项目与导出

| 功能 | 0.6.1 状态 | 实现文件 | 直接测试/证据 | 0.7.0 处理结果 | 真实限制 |
|---|---|---|---|---|---|
| Figure IR 1.0 | 完整 | `figure_ir.py`, Figure schema | Figure IR/performance tests | 保留且与 Scene IR 独立 | Figure 无世界坐标/相机；不通过像素推断 Scene |
| Graph↔Semantic↔Figure provenance | 完整 | `model_figure.py`, `project.py` | model-Figure/project-provenance tests | Project 1.4 保留，并扩展为 Scene 上下文验证 | orphan/tamper 拒绝；unknown 不补语义 |
| Figure Studio/多页/A–H Panel | 完整 | `figure_ir.py`, `figure_export.py`, Web | Figure API/multi-page/E2E | 保留为显式 Figure workspace | 每 Page 最多 8 Panel；异构 PPTX 受单 slide size 限制 |
| Layer/Group/锁定/手工路由/多选 | 完整 | `figure_ir.py`, `model_figure.py`, `editor.py`, Web | Figure/editor tests | 保留；Scene 有独立三维状态 | lock 可导致空白或 proof failure，系统不强制移动 |
| 注释/Callout/legend/公式 | 部分 | `figure_ir.py`, `formula.py`, `figure_export.py` | formula/Figure export tests | 保留；Scene 增加 billboard annotation/legend | 公式是非执行 Unicode 子集，不是 TeX |
| Tensor Geometry | 完整（2D/isometric） | `tensor_geometry.py`, `figure_export.py` | tensor/Figure tests | 保留；与真 Scene volume 明确分层 | 2D extent 与 3D volume 都不自动是 tensor 事实 |
| Figure SVG/PDF/TikZ/PNG/EPS/PPTX/HTML | 完整（固定环境） | `figure_export.py`, `render/*` | multi-page/oracle/vector tests | 保留七格式与投稿包 | 对应可选依赖；PNG 有意 raster；最终 oracle 必须独立 |
| 七模板/七真实模型 Figure | 完整 | `figure_templates.py`, `real_models.py`, `model_figure.py` | real-model/Figure tests | 保留并生成 2D/3D comparison candidate corpus | 固定 seed/CPU/本地权重，不是普遍架构保证 |
| Project save/restore | 完整（1.3） | `project.py`, Project schemas, Web | project/composer/Figure tests | 升级为 1.4；显式 Scene IR；Graph/Semantic/Figure/Scene 证据链 | undo history 仍是 session-only；不序列化 future stack |
| 1.3→1.4 migration | 缺失 | `project.py`, `schemas/project-1.4.schema.json`, `scene_ir.py` | `test_model_scene_070.py`, `test_scene_api_070.py` | 已实现空 Scene + 双重 migration record | 不从 CSS perspective/名称生成任何 3D 对象 |
| Python API | 完整（2D/analysis） | `api.py`, `__init__.py` | core/runtime/model-Figure/Scene API tests | 新增 `scene_from_graph`, `render_scene` 和 workspace-aware `render_project` | 输出格式依赖仍需本地安装 |
| CLI | 部分 | `cli.py`, `__main__.py` | live command audit + CLI/Scene focused tests | `scene`、`project --workspace scene`、reproduce/validate 可用；Project 持久化精确 Semantic document | trusted code/pickle 仍显式 opt-in；不是 sandbox |
| HTTP API | 完整（旧 scope） | `server.py` | `test_scene_api_070.py` | 新增 templates/from-graph/validate/project/pick/transform/export | loopback 无认证，不是公开服务 |
| 批处理 | 部分 | `batch.py`, `cli.py` | 基线多为间接证据 | 保留；未增 Scene batch 权威用例 | ThreadPool 逐 job 报错，但 Scene 并发/失败隔离未作发布声称 |
| 插件 API 2.0 | 完整（本地边界） | `plugins.py` | plugin tests | 保留；无未经证明的 Scene plugin capability 声称 | 不是 sandbox；显式启用后以服务进程权限执行 |
| 安全/离线 | 部分（明确边界） | `server.py`, `scene_ir.py`, `scene_gltf.py`, exporters | Web security/Scene rejection/export tests | Scene parser 拒绝危险 key/非法字段；export asset validator 拒绝危险/外部 URI，glTF buffer 内嵌，HTML 无网络 | Flask 无认证；local plugin/trusted code 非安全隔离 |

## 真正三维能力

| 功能 | 0.6.1 状态 | 实现文件 | 直接测试/证据 | 0.7.0 处理结果 | 真实限制 |
|---|---|---|---|---|---|
| Scene IR 1.0 | 缺失 | `scene_ir.py`, `scene_math.py`, Scene schema | `test_scene_ir_070.py` | 已实现 Scene/Camera/Light/Layer3D/Group3D/Object3D，确定 ID/digest，世界/投影记录 | rotation 单位为 degrees；parser 10k ceiling 不是性能目标 |
| 三维科学图元 | 缺失 | `scene_ir.py`, `model_scene.py`, `scene-renderer.js`, exporters | Scene IR/model/export + browser focused checks | tensor/plane/op/conv/scale/skip/attention/QKV/token/MoE/multimodal/diffusion/frame/label/routes 已落地；WebGL 路由不用原点方块代替，标签有投影避让 | 浏览器手工插入仅 Box/Sphere/Cylinder/Tensor；其他来自模板/生成器 |
| 七架构模板 | 缺失 | `model_scene.py`, `scene_templates/`, `templates/scene_studio/`, Web Start Center | model/template/API/UI focused checks | CNN/ResNet/U-Net/Transformer/MoE/Multimodal/Diffusion 精确七家族已实现，每张 UI 卡打开非空 3D Scene | template-only，不宣称 checkpoint/精度 |
| 七架构模型转 Scene | 缺失 | `model_scene.py` | seven-family/provenance/focus tests | 已实现 evidence-only family/role 和有界生成 | 显式 layout family 不等于 evidenced family；name-only 仍 unknown |
| Orbit/pan/zoom/相机 | 缺失 | `web/scene-renderer.js`, `scene-interactions.js`, `app.js` | Scene E2E source/focused run | 已接线 WebGL2 相机与命名视图 | WebGL/驱动差异通过 CPU fallback 降级 |
| ray picking/多选/框选 | 缺失 | `scene_ir.py`, `scene_math.py`, `scene-interactions.js` | Scene IR + E2E | 已实现最近深度选择、additive 与 marquee | exotic third-party mesh 不在已证 bounds/triangle 范围 |
| XYZ 编辑/吸附/对齐/分布 | 缺失 | `scene_ir.py`, `scene-interactions.js`, `app.js` | transform tests + E2E | 数字/控制器驱动已实现 | 无 on-canvas gizmo；context toolbar 当前只直接暴露 X distribute |
| lock/group/hide/isolate/focus/explode | 缺失 | Scene runtime/interaction modules | Scene tests/E2E | 已实现并进 undo/autosave | Group 已显示，Ungroup 仍为 controller-only；collapse/explode 基于 selection；无专用 group-collapse tree widget |
| 2D/3D selection/provenance/context | 缺失 | `model_scene.py`, `project.py`, `web/app.js`, state machine | provenance tests + browser contract | 物化证据双向 index、workspace context 与 3D→2D 返回链路已实现 | >10k summary 用 digest+有界代表 ID；发布结论只读制品报告 |
| WebGL2/static fallback | 缺失 | `scene-renderer.js`, `app.js`, `/api/scene/project` | Scene E2E | 已实现显式 CPU SVG 降级 | fallback 不复制 GPU shading；它是编辑视图而非质量 oracle |
| CPU projection/occlusion/labels | 缺失 | `scene_projection.py` | `test_scene_projection_070.py` | 已实现 camera/depth/backface/basic occlusion/hidden line/labels | sampled hidden-line 非任意相交 mesh 的精确 CSG |
| 七纸面格式 | 缺失 | `scene_export.py` | `test_scene_exports_070.py`, candidate validator | SVG/PDF/TikZ/PPTX/PNG/EPS/HTML 已实现 | PNG 有意 raster；landed oracle 结论只读制品 `verification.json` |
| Scene JSON/glTF/GLB | 缺失 | `scene_gltf.py` | export/GLB tests, candidate validator | canonical JSON 与真 XYZ glTF/GLB 已实现 | 无 external URI/texture/shader；GLB 不是 Project envelope |
| 七模板+七真模型产物 | 缺失 | release corpus generator/validator | candidate generation + validation report | 14/14 candidate PASS；每例 Project + 10 Scene outputs，真模型加 comparison | 仍在 `/tmp`，必须进 fresh artifact 才是发布证据 |

## UX、操作逻辑与信息密度

| 功能 | 0.6.1 状态 | 实现文件 | 直接测试/证据 | 0.7.0 处理结果 | 真实限制 |
|---|---|---|---|---|---|
| 显式 Graph/Figure/Scene workspace | 缺失（无 Scene） | `index.html`, `app.js`, `state-machine.js` | Scene E2E contract | 三 workspace、本地 context、real-model→Scene→2D 证据链已落地 | 发布结论由制品报告所有 |
| 四阶段工作流/Start Center | 部分 | Web shell | product/Scene E2E contract | Import→Explore→Compose→Proof、Blank 2D/3D 与精确七个可编辑 3D Scene 模板入口已落地 | 不是所有旧 workflow 都已转为同一 command registry |
| Design System/四 app 主题 | 部分 | `design-system.css`, `styles.css` | lint/format + E2E/visual contract | Light/Dark/High Contrast/Paper tokens 已实现；至少 44 张 manifest 覆盖四主题 | 不是每个组件状态的人工 WCAG 审计 |
| 应用密度 | 缺失 | `state-machine.js`, `design-system.css`, `index.html` | E2E preference | Comfortable/Balanced/Compact，Balanced default，持久化 | 只改 chrome，不改科学内容 |
| 图内容密度 | 部分 | Graph/Figure generators, semantic zoom；Scene summary/focus | semantic/large-graph tests | Graph/Figure 保留 Compact/Paper/Detailed；Scene 用 level/view + 有界 summary/focus | Scene 无独立 compact/paper/detailed toggle；详细证据进 Inspector/Lens，不平铺到 canvas |
| 顶栏/任务菜单/context toolbar | 部分 | `index.html`, `app.js`, Design CSS | responsive/Scene E2E | 主组压缩、任务归属、Scene context toolbar 已落地；focused Chrome 确认 7 个顶层组 | 三层菜单深度和完整 surface 几何仍须 artifact-bound 独立报告 |
| Ctrl/Cmd+K command registry | 部分（旧静态面板） | `commands.js`, `app.js` | Scene E2E | 上下文 availability/disabled reason/shortcut/search/focus restore 已实现 | 旧控件未全部 registry 化 |
| 统一 surface/state machine | 部分 | `state-machine.js`, inherited surface manager | Scene + inherited responsive E2E contract | workspace/save/action state、互斥 surface、keyboard/focus/error/cancel/retry 已接线 | 旧控件未全部 registry 化；运行结论只读制品报告 |
| autosave/save state/conflict compare | 部分 | `app.js`, `state-machine.js`, conflict dialog | Scene E2E source | dirty/saving/saved/error/conflict 与当前-vs-存储 revision 对比/显式选择已实现 | 当前测试是 localStorage 单用户冲突，不是多人协作 |
| 侧栏 resize/persist/pin | 部分 | `design-system.css`, state/app modules | Scene E2E source | 键盘/指针 resize、宽度持久化、Inspector pin/unpin 已实现 | ≤800 时用 drawer，不提供 desktop resizer |
| 响应式视口 | 部分 | Web CSS/surface manager | 七精确尺寸 focused 面积检查 | document/toolbar/menu/dialog/overflow/topbar 与 full-viewport 面积 gate 已编码 | 桌面 0.691117/0.625341/0.614173/0.617669，窄屏关 drawer 后 0.900000/0.812500/0.928910，分别达 60%/70% |
| Inspector progressive disclosure | 部分 | `index.html`, `app.js`, CSS | focused E2E | Scene 无选择/单选/多选 context 与 provenance 已实现 | 六组可折叠结构尚未在所有 workspace/object 统一 |
| Task Center/action feedback | 完整 server，UI 部分 | `tasks.py`, `server.py`, Web | task/semantic tests + browser contract | Scene async 接共享 busy/success/warning/error/retry，并编码 error→cancel→retry | 旧控件未全部 registry 化；运行结论只读制品报告 |

## 验收合同与真实边界

| 验收项 | 必须落盘的证据 | 结论权威 |
|---|---|---|
| 真 3D 数学/世界坐标/相机/遮挡/ray/GLB | focused 与 full 数学/格式报告 | 制品 `verification.json` |
| 14 个 Scene corpus 及 140 exports | corpus + 独立 validator + landed hashes | 制品 `verification.json` |
| 性能阈值 | 三轮、环境、输入尺寸与 retained-2D 对比 | 制品 `verification.json` |
| Scene Chrome UX | 至少 44 screenshots、10 downloads、七视口面积、四主题、错误/回退状态 | 制品 `verification.json` |
| 视觉验收/七真模型/七模板 | 七个 2D/3D pair、七个真实 3D template capture、route/label 证据和独立视觉报告 | 制品 `verification.json` |
| 精确 246-ID + coverage + 全 E2E/oracle | 当前树 clean full 报告，不得引用父 artifact 代替 | 制品 `verification.json` |
| 真人可用性 | 0 participants / 0 sessions / 所有指标 null | 无真人结论 |

本矩阵不给当前 run 贴 PASS/FAIL 标签；读者必须检查新制品的 `verification.json`。自动化不计入真人指标。
