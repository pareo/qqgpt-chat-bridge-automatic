# 可选的 ChatGPT 任务服务

普通聊天和识图仍走 MaiBot → sub2api。需要搜索时，MaiBot 调用 `web_search`；需要生成图片时，`generate_image` 根据 `images.backend` 选择 API 或独立 Windows ChatGPT 工作进程。QQ 收发始终由 MaiBot / NapCat 完成，任务服务没有群号参数或 QQ 收发接口。

```text
QQ ⇄ NapCat ⇄ MaiBot ── 普通聊天/识图 ── sub2api
                  └── 工具任务 ── 鉴权HTTP队列 ── 普通ChatGPT会话
                  └── 图片/文件校验、缓存 ── 来源聊天
```

## 提取范围

`services/desktop-worker/` 独立复制了旧项目的 ChatGPT 窗口适配、附件上传下载、回复提取和格式保留代码。没有复制旧项目的监听引擎、QQ 投递流程、Dashboard、配置、密钥或状态。原文件未作改动，原始文件摘要记录在 `provenance.json`。

原生适配器的几个 C# partial 共用底层辅助方法，因此源码保留了部分共享旧方法；新的原生分派器与 Node 客户端均只允许指定 ChatGPT 操作。`qq.*`、`browser.*`、配置 QQ 和强制丢弃草稿均无入口。无需依赖旧项目安装路径或启动旧程序。

## 启用

默认关闭。要求 Windows 交互桌面、已登录的普通 ChatGPT 会话、Node.js 22.13+ x64、.NET Framework 4.x x64。可在 `services/desktop-worker/bin/node.exe` 放便携 Node；编译产物与便携运行时忽略 Git。Linux Docker 继续运行 MaiBot，Windows 工作进程独立运行，不能塞入 Linux 容器执行 GUI 操作。

1. 在普通 ChatGPT 新建专用会话，标题和 `desktop_worker.conversation_title` 一致，默认“大肥龙工具”。不要与人工聊天共用输入框，不使用 Codex 或 Work 页面。
2. `config/local/project.json` 添加/修改 `desktop_worker`，完整字段见 `config/examples/project.json`。设 `enabled=true`，选定模型与思考档位；`current` 使用当前选择。
3. `config/local/secrets.json` 填 `desktop_worker_token`，至少32字符的随机令牌。新项目 `init` 自动生成，旧安装重新 `init` 只补令牌，不覆盖其他现有配置。
4. 生图走此后端时设 `images.backend="desktop"`；API 后端保持 `"api"`。`images.enabled` 和 `images.model` 管理 API 生图，桌面后端是否启用由 `desktop_worker.enabled` 决定。
5. `run.cmd worker-build` 编译独立适配器；`run.cmd worker-test` 执行内部测试；`run.cmd worker-start` 启动隐藏的任务服务；`worker-status` 查询鉴权服务状态。
6. 使用 `run.cmd configure` 明确应用新的工具提示，然后重启 MaiBot。注意 configure 会按 local 配置重新应用管理的字段，若已在 WebUI 改过聊天频率等，请先同步需要保留的数值。

容器通过 `desktop_worker.url` 访问 Windows，例如 `http://host.docker.internal:18120`。默认绑定 `127.0.0.1`；某些 Docker Desktop 网络不能访问宿主回环监听。这时可以改 `listen_host` 为 `0.0.0.0` 并通过 Windows 防火墙限制 Docker 网络来源，或者使用现有的受控转发。必须携带独立 Bearer 令牌，不允许跨域网页调用，不记录令牌。

`model`、`reasoning_effort` 在会话首次准备及窗口/配置发生变化时核对；同一个工作进程成功任务之间复用原生适配器的设置缓存，不每轮打开菜单。

## 结果与恢复

- UI 任务串行，普通 API 聊天不占这条队列；默认最多4个未完成任务。一个来源聊天等待工具期间仍受 MaiBot 自身会话调度约束，不能保证该聊天继续并行回复。
- POST 使用任务 ID 去重；丢失响应不重新 POST。读状态最多连续重试两次，超时后返回任务 ID。
- 提交之前落盘 `submitting`，提交之后为 `awaiting_result`。重启时不重跑未完成任务；已进入提交阶段的标记 `uncertain`。不把失败结果自动切换另一个后端重新生图。
- 结果待确认时仅暂停桌面工具队列。检查专用 ChatGPT 会话、人工处理遗留草稿或等待生成结束，再执行 `run.cmd worker-reset`。这只解除任务队列阻塞，不清空聊天、不重发任务，也不代表旧任务已成功。
- 输入单个附件最多 10 MiB，单次最多 4 个附件。最多可选 12 张角色参考图，超过可用附件数时编排为编号图版。改图原图单独放在最前面。返回图片 20 MiB，返回文件 10 MiB，下载后校验大小与 SHA-256，图片再验格式及像素。所有输出先保存到新项目 data，再由当前工具调用所属的聊天发送。
- `ctx.files.upload/send` 由 MaiBot Host 绑定原会话，模型不能指定其他群。QQ 投递不确定时保留全部附件缓存，停止后续发送，不重新提问 AI 或重复发送。
- 搜索结果返回当前 MaiBot 对话，由当前人设回复并保留 URL。明确要求生图或制作表情包时，图片确认发出后由当前人设撰写配文。闲聊配图沿用普通文字回复。
- 普通作图高质量，只有 sticker/casual_sticker 缩至300×300、96 DPI；只有 casual_sticker 检查概率与冷却。

## 验证边界与后续后端

原生编译和离线队列/HTTP/插件测试已完成；本次没有向 QQ 发消息，也没有在真实 ChatGPT 会话提交搜索或生成图片。首次使用仍需进行一次桌面端与容器之间的连通和端到端验证。GUI 上传、复制和下载可能临时使用前台与剪贴板，无法保证完全不影响桌面工作。

任务队列通过执行器函数与具体后端解耦，目前只实现 `chatgpt-app`，配置其他名称会明确拒绝。Codex 可以使用现成的 [codex-acp](https://github.com/agentclientprotocol/codex-acp) 对接 MaiBot 的自定义 ACP 接口，或另接 `app-server`/SDK。它不是 OpenAI 模型 API 的同一个协议，不能直接填进 MaiBot 的 Base URL。Codex ACP 支持模型与思考强度选择，也声明可处理搜索和图片生成事件；具体账户的工具可用性及 MaiBot 图片文件回传仍需独立验证。本次没有安装该适配器、读取或复制 Codex 登录令牌，也没有切换现有后端。
