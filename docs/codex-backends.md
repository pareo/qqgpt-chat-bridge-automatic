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

普通搜索独立使用 `agent_worker.search_reasoning_effort`（默认 `low`），不改变深入分析和生图的思考强度。`search_max_rounds` 默认 2（可设 1～5），是传给模型的检索轮次预算，不是强制中断网络调用的硬限制。搜索优先返回短事实资料、日期和最多三个来源，不再撰写长报告；有访问限制时如实交代，不为追求速度伪造核验。资料转交回复模型时去除重复策略包装，按当前人设接话。任务记录中的 `timings` 分别记录会话准备、搜索生成与总耗时。

图片只接受 ACP 结构化图片输出并执行已有字节校验，不从文本描述推断成品，也不下载任意 URL 或读取模型声称的宿主路径。若账户只返回图片文件引用而没有嵌入图片，这个版本会明确失败，后续可在单独验证后增加受限文件产物通道。不能将 ACP 支持图片事件等同于账户必然可生图。

## 验证与边界

源码包含离线回归和安全边界测试。真实聊天、搜索与图片生成需使用部署者自己的账号逐项验收。账号是否可生图不能由模型名称推定；验证产物和任务记录保存在忽略的 data/ 目录，不随源码分发。

搜索资料通过 Host 的 content 字段返回 Planner，再由官方 before_request Hooks 绑定原会话和原消息交给 Replyer。保留事实与来源，去除重复策略包装，最终按当前人设回复。普通 start/stop 同时管理已启用的独立 Codex 服务。Windows 窗口服务保留为未启用的兼容选项，Codex 不依赖它。
