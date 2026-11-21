# AI 修图工作台｜项目简历与面试展开

> 整理依据：当前仓库源码、README、部署与诊断文档，以及飞书「前端面试 / AI 修图工作台」中的项目总览、画布、Agent、选区、图层、多步计划、部署、简历写法、面试题解等资料。
>
> 定位：面向全栈 / AI 应用开发岗位，以后端任务架构、Agent 编排、数据建模和账号隔离为主线，保留复杂编辑器作为前端优势；附资源管理和部署方向的替换条目。以下是项目经历，不是包含教育、工作履历的完整个人简历。项目时间、演示地址等个人信息需要自行补充。
>
> 核验方式：静态源码与文档交叉阅读，未启动应用、运行测试、调用收费模型或复测线上性能。文中的实现描述不等于本轮运行验收结论。

## 一、推荐投递版：全栈 / AI 应用开发方向

### AI 修图工作台｜个人全栈项目

**项目介绍**：面向电商商品图及营销素材处理的全栈 AI 图像编辑应用。用户可上传或生成图片，通过自然语言驱动 Agent 规划修图步骤，也可在多图层画布中手动精修，支持背景处理、局部编辑、图层拆分与批量导出，覆盖素材创建、编辑和交付流程。

**技术栈**：Python、FastAPI、SQLAlchemy、PostgreSQL、Redis、ARQ、LangGraph、Pydantic、S3 兼容对象存储、Docker；React 19、TypeScript、Konva、Zustand、TanStack Query。

**主要工作**：

1. **异步任务与实时推送**：基于 Redis + ARQ 将耗时图像任务交由独立 Worker 执行，通过 Redis Pub/Sub + SSE 推送进度，结合快照恢复任务状态；使用 Redis 缓存会话选区状态，通过 TTL 自动过期与 revision 校验控制选区有效性。
2. **可控的 Agent 计划执行**：基于 LangGraph 构建规划与验证流程，对 LLM 输出进行工具存在性、Pydantic 参数及依赖合法性校验，以 Kahn 算法检测依赖环；实现计划落库、依赖就绪调度与 Worker 完成后的接续推进，支持多步确认、失败步骤重试和取消后续操作。
3. **统一工具与模型服务抽象**：以 ToolSpec 统一注册 22 个工具，复用参数模型生成 LLM 工具签名并执行服务端校验，统一同步 / 队列执行入口；通过 ImageProvider 抽象与调用作用域隔离模型接入，实现 Mock / 真实服务切换，便于无模型费用的开发验证。
4. **数据建模与编辑版本管理**：基于 SQLAlchemy + PostgreSQL 管理用户、素材、编辑会话及工具任务，通过 Alembic 管理数据库迁移；使用 JSONB 持久化图层文档与编辑快照，实现撤销 / 重做、重做分支截断及历史数量限制，并以 revision 校验避免选区作用于过期文档。
5. **用户级凭据与资源隔离**：实现用户自带模型 Key 的配置链路，使用 Fernet 加密存储、脱敏展示与错误文案清理保护凭据；API 与 Worker 按资源所属用户解析模型配置，并校验素材、会话和任务归属，默认关闭平台 Key 兜底，明确账号与模型费用边界。
6. **图像处理管线**：在服务端通过 CPU 推理运行 rembg 抠图与 SAM 点选分割，结合 OpenCV 背景修复、遮罩合成实现图层拆分与局部编辑，并通过 embedding 缓存复用减少 SAM 重复编码。
7. **前后端一体的图像编辑器**：基于 React + Konva 实现多图层编辑、锚点缩放和前后效果对比；将 SAM 点选、笔刷圈选与后端遮罩工具联动，通过近似选区预览、版本校验及客户端 / 服务端状态分层，衔接手动编辑与 Agent 自动修图。

### 一页简历的精简建议

- 这份项目经历的主线是“能够设计和交付完整系统”，不是“为前端项目补了几个接口”。正文约五条后端能力、一条图像处理能力和一条前端交付亮点。
- 篇幅不足时，优先保留第 1、2、3、4、6 条，再保留第 7 条作为前端交付亮点；不要把第 6、7 条拆成多条零散技术名词。
- 应聘偏 AI 应用岗位：第 6、2、3、1 条在前；应聘通用全栈岗位：第 1、4、5、6 条在前。
- 技术栈可缩成：`FastAPI / PostgreSQL / Redis / ARQ / LangGraph / Docker / React / TypeScript / Konva`。
- 第 1 条的“恢复”指读取持久化任务状态，不代表 Worker 进程故障后具备通用的自动断点续算能力。
- 不需要把下面的分析、源码依据和面试回答全部放进投递简历。

## 二、按岗位选择的替换条目

以下条目用于替换正文中与目标岗位相关性较弱的一条，不建议全部追加。前端亮点至少保留一条。

### 1. SAM 推理资源管理（偏 AI 工程 / 性能排查）

此条是正文图像处理条目的资源管理展开版，选用时合并或替换缓存部分，不与正文重复罗列。

将 SAM 图像编码与点选解码分离，进入点选模式时预热 embedding，并以图片内容哈希和容量受限的 LRU 缓存复用编码结果；针对模型内存常驻与多图处理内存增长，引入 ONNX Runtime CPU 内存池配置、闲置回收和推理占用保护，兼顾交互延迟与资源释放。

### 2. 容器交付与自动部署（偏产品交付 / 全栈）

编写前端构建、后端同源托管的多阶段镜像及 Compose 部署配置，配置 GitHub Actions 的前端 lint / build、后端静态检查和主分支自动部署；通过增量同步保护服务器本地配置，并串行执行部署，避免并发发布冲突。

### 3. 测试隔离与可验证性（偏后端工程质量）

围绕认证、素材、编辑会话、Agent 计划和模型配置编写 pytest 测试，利用 Mock Provider、替代分割实现及禁用 OCR 等方式隔离外部模型依赖，覆盖非法工具与参数、多步确认、步骤重试及账号凭据隔离等关键场景。

> 测试条目只描述当前仓库存在的用例与隔离机制，不表示本轮已经跑通测试，也不代表有已测得的覆盖率。

## 三、面试应该展开的技术难点

### 难点 1：长任务不阻塞 API，状态又不能只存在于连接中

**问题**：AI 图像处理耗时长，若在请求内等待，会把请求生命周期与第三方推理绑定；仅靠实时消息，刷新页面或重新建立连接后又缺少可靠状态。

**实现思路**：

- FastAPI 接收请求、校验资源与参数，建立任务记录，再交给 ARQ Worker 消费。
- Worker 执行模型 / 图像处理并回写任务状态，通过 Redis Pub/Sub 发布进度，API 转为 SSE。
- SSE 路由先建立订阅再读取快照，处理读取快照与订阅之间的竞态窗口；心跳维持空闲连接，终态结束推送。
- 前端将事件流与 REST 快照合并，刷新后根据任务记录恢复展示；Agent 整轮执行中另有约 800ms 的计划补拉。

**面试重点**：数据库保存可查询的状态，Redis Pub/Sub 是实时通知，不是持久消息日志；异步化缩短的是提交请求的等待，不是模型推理本身。

### 难点 2：LLM 的输出如何成为可控、可追踪的业务操作

**问题**：模型可能输出不存在的工具、非法参数或不可执行的计划；连续多步操作需要确认、失败处理和状态跟踪。

**实现思路**：

- LangGraph 负责 plan → verify；业务执行服务负责计划落库、确认、就绪判断和推进，两者职责不同。
- 逐步校验工具与参数，默认补全顺序依赖，以 Kahn 算法检测依赖环，单轮最多 8 步。
- 根据步骤状态、依赖成功情况和是否已有 run_id 判断能否提交。
- 单步计划直接启动，多步计划等待确认；工具自身还可以要求审批。
- 同步工具完成后直接推进，异步工具由 Worker 完成回调接续；失败支持重试，取消主要停止后续未执行操作。

**面试重点**：模型负责提出操作，服务端负责约束和执行。不能把 LangGraph 的规划图与业务步骤调度混为一谈，也不要称为多 Agent 系统或通用分布式工作流引擎。

### 难点 3：避免 UI、Agent 和执行端维护三套工具定义

**问题**：工具越来越多时，如果界面、模型函数签名、参数校验和执行入口分别维护，容易发生参数和行为漂移。

**实现思路**：

- ToolSpec 集中定义工具名称、说明、Pydantic 参数模型、handler，以及排队、审批、模型依赖等标记。
- 由参数模型生成 LLM 函数签名，实际执行仍经服务端校验，不把模型的结构化输出当作可信输入。
- 同步文档工具与排队像素工具使用统一提交入口，状态流转由执行外壳负责。
- ImageProvider 抽象屏蔽真实模型与 Mock 实现的差异；模型配置绑定在调用作用域，不使用跨用户共享的全局可变凭据。

**面试重点**：注册表解决“工具定义与执行规则一致”，Provider 解决“模型服务可替换”，二者不是同一个抽象层。

### 难点 4：用户模型 Key 如何跨 API / Worker 使用而不串号

**问题**：异步任务离开原始 HTTP 请求后，仍需要拿到正确账号的模型配置；凭据不能以明文返回浏览器，也不能因错误回显而泄露。

**实现思路**：

- Key 使用独立主密钥进行 Fernet 加密后持久化，查询返回配置状态及脱敏提示。
- API 与 Worker 根据用户 / 任务归属加载模型配置，在调用作用域中使用解密结果。
- 素材、会话、任务查询执行用户归属校验，模型错误文案清理 Key 内容。
- 平台 Key 兜底默认关闭；未配置或解密失败时明确拒绝，而不是静默消耗平台额度。

**面试重点**：这是用户级资源和模型调用隔离，不要扩大成已实现企业级多租户权限体系、密钥轮换平台或细粒度 RBAC。

### 难点 5：可编辑图层、历史快照和选区必须保持一致

**问题**：图层修改后，旧遮罩可能已经不适用于当前画布；撤销后再编辑时，旧重做分支也不能保留。每次鼠标移动都落库又会污染历史。

**实现思路**：

- 使用结构化 LayerDocument 表达画布与图层，以 JSONB 保存文档；编辑快照记录修改前后状态。
- 统一 apply_edit 入口执行重做分支截断、文档更新和历史追加，保留最近 20 条线性历史。
- 点选 / 笔刷请求携带 revision，服务端拒绝过期输入；临时选区放在带 TTL 的 Redis 状态中。
- Agent 计划可固定本轮遮罩引用，避免同一计划前一步递增 revision 后，后一步丢失同一选区；画幅变化则不能直接拉伸旧遮罩继续使用。
- 视口、临时预览由客户端管理，应用编辑才写入文档历史。

**面试重点**：说明为什么关系模型与 JSONB 各自承担不同职责，以及 revision 如何用于一致性校验；不要将其描述为覆盖所有并发写场景的乐观锁方案。

### 难点 6：分割结果如何变成可编辑图层，而不只是返回一张抠图

**问题**：分离主体后，背景会留下空洞；模型补全可能改动原本不需要修改的区域；每次点选重新编码又会带来重复计算。

**实现思路**：

- rembg 输出带透明通道的主体，由 Alpha 通道提取遮罩；SAM 负责按用户点选生成区域遮罩，两者承担不同任务。
- 对需要移除的区域扩张遮罩，用 OpenCV Telea Inpainting 预修复，再调用图像模型补全背景，降低主体残留或被重新生成的风险。
- 将模型输出按遮罩合成回输入图像，使用高斯模糊平滑边缘，约束修改范围；羽化边界可能轻微影响邻近像素，不承诺选区外每个像素严格不变。
- 将图像资产与图层位置分别记录，支持主体 / 背景独立编辑和选区成层；可选 RapidOCR 识别文字及边界框并生成文字层，但不等于还原原字体和排版。
- 将 SAM 图像编码与点选解码分开，以内容哈希索引 LRU embedding 缓存，进入点选时预热；闲置回收时先确认无推理占用，避免与进行中的请求冲突。

**面试重点**：技术含量在分割、修复、合成和资源管理的组合，不是自研分割算法、训练 SAM 或自行完成模型量化。Pillow 调色是另外一条像素处理能力，不应描述为图层拆分的必经步骤。

### 难点 7：前端优势如何转化为全栈交付能力

**问题**：后端能生成图片不代表产品可用，用户还需要准确选中区域、调整图层，并理解长时间等待和执行结果。

**实现思路**：

- 将 Stage 视口变换与图层变换分开，锚点缩放保持鼠标位置稳定，协调图层拖拽与画布平移。
- 点选 / 笔刷使用归一化坐标，与后端遮罩和图层文档衔接。
- 近似选区先给过渡反馈，服务端遮罩返回后接替；本地预览用递增 token 忽略过期异步结果。
- Zustand 管理客户端交互，TanStack Query 管理服务端资源；调色预览与实际应用分离。

**面试重点**：不把前端能力藏起来，但将它作为“能把后端 AI 能力交付成可用产品”的证据，而不是再次证明会写 React 页面。

## 四、项目口述稿（约 1 分钟）

我做的是一个面向商品图和营销素材的 AI 修图工作台，覆盖图片创建、自然语言修图、多图层精修和批量导出。我本身是前端出身，这个项目重点补齐的是从后端业务建模、任务执行到部署交付的完整链路。

后端使用 FastAPI 和 PostgreSQL，长时间的模型调用交给 ARQ Worker，通过 Redis Pub/Sub 和 SSE 推送进度，再用持久化快照恢复刷新后的任务状态。Agent 不直接执行模型返回的调用，而是先校验工具、参数和步骤依赖，多步计划确认后才执行，Worker 完成后继续推进后续步骤。

工程上，我用统一注册表管理工具定义，用 Provider 隔离模型服务，将 rembg、SAM 分割与背景修复、遮罩合成串成可编辑图层管线，并实现了用户模型 Key 的加密保存和 API、Worker 间的按用户调用隔离。前端则发挥已有优势，用 Konva 实现多图层编辑和智能选区，把这些后端能力真正整合成可操作的产品。

> 口述时只保留自己真正理解、能够现场展开的实现。如果部分代码来自学习项目，应如实区分参考实现和个人扩展，不把“个人完成”表述成“所有设计完全原创”。

## 五、与现有资料相比，需要修正的表述

1. **工具数**：飞书参考写法提到 21 个，当前源码 SPECS 实际注册 22 个；简历以当前代码为准。
2. **调色预览**：当前实现包含 Konva 自定义逐像素滤镜和查找表处理，不宜只沿用旧文档的“CSS filter”描述；锐化、清晰度等卷积效果仍由后端应用时处理。
3. **Agent 进度**：任务级 useRun 使用 SSE，整轮 Agent 计划状态还依赖执行中轮询；不要写“全部 SSE、完全无轮询”。
4. **选区历史**：当前 Hook 在 revision 变化时清理失效选区并重置选区历史，不宜直接写“版本切换自动完整恢复所有选区”。
5. **历史记录**：最近 20 条线性记录，不能写无限历史或版本分支树。
6. **取消语义**：取消后续步骤不等同于强制终止已经发往第三方模型的请求，也不保证撤销第三方费用。
7. **性能结论**：没有本轮基准测试，不写“稳定 60 FPS”“响应降低 90%”“支持万人并发”等数据；异步接口快速返回不代表模型推理变快。
8. **部署状态**：仓库有部署流水线和部署记录，但本轮未验证公网演示可用性或最近一次流水线结果。
9. **原创边界**：飞书中有教程型材料和参考简历，适合提炼设计思路，不适合直接复制为个人独创成果。投递时优先突出自己理解和实际扩展的部分。

### 有记录但仍需本人确认的数据

仓库内存诊断文档记录过：禁用 ONNX Runtime CPU 内存池后，在当时测试条件下内存由约 6.6GB 降到约 3.5GB，并不再随处理图片数持续上涨。这是已有诊断记录，不是本轮复测结果。只有能说明硬件、模型、图片规模、内存统计口径和复现过程时，才建议作为简历中的量化成果。

不建议使用飞书通用示例中的“最长 60 秒降至毫秒级”作为性能提升：它混淆了任务完成耗时与异步接口返回耗时。

## 六、源码依据（供回查，不放进投递正文）

以下路径以当前工作区为准，行号可能随后续修改发生变化。

| 亮点 | 主要依据 |
| --- | --- |
| 画布与图层交互、对比裁剪 | `/Users/lansen/Desktop/code/ai-photo-workspace/client/src/components/editor/CanvasStage.tsx:32`、`:229`、`:849`、`:974` |
| 锚点缩放、滚轮行为 | `/Users/lansen/Desktop/code/ai-photo-workspace/client/src/stores/canvasView.ts:194`、`:215` |
| 服务端状态与实时任务合并 | `/Users/lansen/Desktop/code/ai-photo-workspace/client/src/hooks/useRun.ts:32` |
| Agent 执行中轮询与终态刷新 | `/Users/lansen/Desktop/code/ai-photo-workspace/client/src/hooks/useAgent.ts:36` |
| 选区历史与版本失效 | `/Users/lansen/Desktop/code/ai-photo-workspace/client/src/hooks/useSelection.ts:45` |
| 近似选区及过期结果隔离 | `/Users/lansen/Desktop/code/ai-photo-workspace/client/src/hooks/usePointPreview.ts`、`/Users/lansen/Desktop/code/ai-photo-workspace/client/src/lib/floodPreview.ts` |
| 本地逐像素调色与查找表 | `/Users/lansen/Desktop/code/ai-photo-workspace/client/src/lib/adjustPreview.ts`、`/Users/lansen/Desktop/code/ai-photo-workspace/client/src/components/editor/LayerPanel.tsx:551` |
| 进度平滑 | `/Users/lansen/Desktop/code/ai-photo-workspace/client/src/hooks/useSmoothedProgress.ts:22` |
| SSE 先订阅后快照 | `/Users/lansen/Desktop/code/ai-photo-workspace/backend/app/routers/events.py:30` |
| JSONB 图层文档 | `/Users/lansen/Desktop/code/ai-photo-workspace/backend/app/models/edit_session.py:37`、`/Users/lansen/Desktop/code/ai-photo-workspace/backend/app/layers.py` |
| 编辑快照、撤销 / 重做、历史截断 | `/Users/lansen/Desktop/code/ai-photo-workspace/backend/app/services/sessions.py:112`、`:352`、`:367`；`/Users/lansen/Desktop/code/ai-photo-workspace/backend/app/models/edit_history.py:10` |
| 22 个工具的统一注册 | `/Users/lansen/Desktop/code/ai-photo-workspace/backend/app/tools/__init__.py:23`、`/Users/lansen/Desktop/code/ai-photo-workspace/backend/app/tools/base.py:42` |
| 规划验证、函数签名与环检测 | `/Users/lansen/Desktop/code/ai-photo-workspace/backend/app/agent/graph.py:71`、`/Users/lansen/Desktop/code/ai-photo-workspace/backend/app/agent/llm.py:15`、`/Users/lansen/Desktop/code/ai-photo-workspace/backend/app/agent/plan.py:54`、`:107` |
| 多步计划推进与 Worker 接力 | `/Users/lansen/Desktop/code/ai-photo-workspace/backend/app/services/agent.py:212`、`/Users/lansen/Desktop/code/ai-photo-workspace/backend/app/tasks/tools.py` |
| 模型 Key 加密与调用作用域 | `/Users/lansen/Desktop/code/ai-photo-workspace/backend/app/credentials.py:57`、`/Users/lansen/Desktop/code/ai-photo-workspace/backend/app/services/model_settings.py`、`/Users/lansen/Desktop/code/ai-photo-workspace/backend/app/providers/__init__.py:36` |
| SAM 缓存、内存池与回收 | `/Users/lansen/Desktop/code/ai-photo-workspace/backend/app/edits/segment.py:56`、`:106`、`:125`；`/Users/lansen/Desktop/code/ai-photo-workspace/backend/app/main.py` |
| 局部编辑的遮罩合成 | `/Users/lansen/Desktop/code/ai-photo-workspace/backend/app/edits/mask.py:64` |
| 图层拆分 | `/Users/lansen/Desktop/code/ai-photo-workspace/backend/app/edits/split.py` |
| 自动部署与静态检查 | `/Users/lansen/Desktop/code/ai-photo-workspace/.github/workflows/ci.yml`、`/Users/lansen/Desktop/code/ai-photo-workspace/.github/workflows/deploy.yml`、`/Users/lansen/Desktop/code/ai-photo-workspace/Dockerfile` |
| 历史内存诊断记录 | `/Users/lansen/Desktop/code/ai-photo-workspace/docs/container-memory-diagnostics.md` |

## 七、投递前补齐

- 项目实际起止时间；不要把教程发布时间或 Git 最近提交时间直接当作项目周期。
- 已核验可访问的演示地址和代码仓库地址。
- 在七条主线中选择自己能够深入回答的 4～6 条，保留图像处理条目，并至少保留一条前端 / 跨端交付亮点。
- 如需量化，优先补测任务提交耗时、选区预热前后延迟、SAM 多图内存曲线等；记录条件，不混用公网链路耗时与服务端耗时。
- 根据实际贡献明确“参考实现 / 自己新增 / 自己重构”的边界，准备相应提交、问题定位过程和演示。
