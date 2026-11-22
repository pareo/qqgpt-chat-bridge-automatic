# API 与 Codex ACP 双后端（本地开发）

普通群聊和识图继续走 MaiBot + 可配置模型 API；联网/复杂任务及可用的原生图片任务走独立 Codex ACP 服务。`images.backend` 可选 `api` 或 `codex-acp`。旧 `desktop_worker.enabled` 设为 false，不再启动图形界面路径；尚未将 MaiBot 的实验性 ACP Planner 设为默认聊天 Planner。

## 安全边界

codex-acp 2.6.0 与 Codex 0.166.0 固定版本，传递依赖由 package-lock 锁定；npm 安装禁用生命周期脚本。Node 容器非 root、只读根文件系统、移除 capabilities、限制进程/内存、禁止提升权限。仅挂载专用 worker 配置（独立令牌、模型和超时）及独立命名卷；不挂载私人项目、完整 secrets.json、QQ 登录态、宿主 home 或 Docker socket。

模型使用 read-only 模式，shell_tool=false；ACP 客户端不提供文件读写、终端或 MCP 能力，权限请求一律取消。群输入不能覆盖命令、模型、环境、会话目录或回复群。每个工具任务创建独立会话防串群；结果只交回发起工具调用的 MaiBot 会话。队列去重与不确定结果不自动重放。

这些是分层限制，不是绝对安全保证：登录令牌由 Codex 进程使用，仍可能受到上游漏洞影响；容器有网络以访问 OpenAI 和搜索服务，尚未部署出口域名代理。未开启任何自动全权限模式。

## 使用

`run.cmd codex-prepare` 创建 config/local 的 agent_worker 设置及独立令牌，生成 config/generated/codex-worker.json；不会将 agent_worker.enabled 打开，也不覆盖运行中的 WebUI 设置。`codex-build` 构建容器；`codex-login` 后由用户按 logs/codex-worker/login.log 的地址与设备码完成独立 ChatGPT 登录。不会复用当前 Codex App 凭据。

`codex-start` 启动任务服务，`codex-smoke` 检查握手、登录、会话及配置选项；不会向群发消息。协议与真实工具测试通过后才能将 agent_worker.enabled 改为 true、images.backend 改为 codex-acp。`codex-stop` 停止此服务，API 普通聊天保持可用；没有自动回退到窗口或重新生图。

模型和思考强度分别在 agent_worker.model/reasoning_effort 配置。改变后运行 codex-prepare 并重启 worker。当前配置不自动将长任务交给某个群外的客户端。

使用 Codex ACP 生图时，`agent_worker.image_model` 可以为画图、改图和制作新表情包单独指定模型。留空时沿用 `agent_worker.model`。以 `gpt-6.2-sol` 为例，这是发起图像工具调用的 Codex 模型，图像工具自行选择实际绘图模型。

普通搜索独立使用 `agent_worker.search_reasoning_effort`（默认 `low`），不改变深入分析和生图的思考强度。`search_max_rounds` 默认 2（可设 1～5），是传给模型的检索轮次预算，不是强制中断网络调用的硬限制。搜索优先返回短事实资料、日期和最多三个来源，不再撰写长报告；有访问限制时如实交代，不为追求速度伪造核验。资料转交回复模型时去除重复策略包装，按当前人设接话。任务记录中的 `timings` 分别记录会话准备、搜索生成与总耗时。

图片只接受 ACP 结构化图片输出并执行已有字节校验，不从文本描述推断成品，也不下载任意 URL 或读取模型声称的宿主路径。若账户只返回图片文件引用而没有嵌入图片，这个版本会明确失败，后续可在单独验证后增加受限文件产物通道。不能将 ACP 支持图片事件等同于账户必然可生图。

## 本地验收

独立 ChatGPT 登录、ACP 会话、gpt-6.1-terra 与 medium 配置确认通过。实际文字任务、带 completed 搜索事件的官方页面检索、带 completed 生图事件的图片任务均通过；已下载生成图片并校验大小、SHA-256 和图片格式。结果证据仅保存在被 Git 忽略的 data/core/verification/，不包含在源码中。29 项 Python 回归和 6 项 Codex 安全边界测试通过。没有主动向 QQ 发送本轮测试内容；群聊实测仍需用户验收。

已针对验证过的能力启用 agent_worker 和 codex-acp 图片路由，旧窗口后端关闭。只更新 live 工具提示，保留现有 WebUI 聊天频率等配置。普通 start/stop 同时管理已启用的独立任务服务。

搜索结果正文使用 Host 要求的 content 字段。搜索回复规则同时覆盖群聊、私聊及每个人设模式，配置生成和启用脚本也保留这些规则：有线索时提供摘要、来源和核验限制，不把原站访问失败当作完全无结果。缓存资料已分别经过插件、Host 解析器和当前回复模型的群聊/私聊内部回放；32 项回归测试通过。这些自测不向 QQ 发送消息，也不代替聊天现场的验收。

后续检查实际 Replyer 请求发现：原生框架过滤工具结果，只向 Replyer 传真实 IM 消息和 Planner 的回复意图，因此正文仍可能在 Planner→Replyer 之间丢失。插件现通过官方 before_request Hooks，将成功搜索/分析工具的资料绑定到原会话、原消息，并作为额外参考传入 Replyer。缓存180秒后失效，最多128会话，不向其他消息串用；不修改 MaiBot 核心。已使用真实失败回复的完整监控请求内部回放，确认加入交接后保留具体摘要、新来源链接及核验说明，而非只验证简化提示。
