# QQGPT Chat Bridge Automatic

独立于旧版窗口桥接程序的新项目。QQ 消息通过 NapCat 的 OneBot WebSocket 接入 MaiBot，普通聊天通过 API 调用。搜索和图片生成可以选用独立的 Windows ChatGPT 任务服务，QQ 收发始终走 NapCat。

MaiBot + NapCat 的 QQ 聊天桥接程序，包含可选的普通 ChatGPT 窗口任务服务。仓库只提供通用示例；账号、群号、API 凭据、人设与参考图均由使用者在 `config/local/` 配置。

## 快速开始

核心要求：Docker Engine/Desktop 的 Linux 引擎、Docker Compose v2 或以上、至少 2 GiB 可用内存。核心宿主无需安装 Node.js、Python 或 QQ 桌面客户端；首次初始化需要网络下载官方镜像和连接器。可选 Windows ChatGPT 任务服务另需 Node.js 22.13+、.NET Framework 4.x 和可交互的普通 ChatGPT 会话，见[混合任务服务](docs/hybrid-worker.md)。

Windows 在项目目录使用 `run.cmd`；Linux/macOS 使用 `sh run.sh`，命令相同。

```powershell
.\run.cmd init
```

初始化不会覆盖已有 `config/local/`。然后修改：

- `config/local/project.json`：QQ 账号、允许的群（名称和群号配套）、模型、思考强度、接口地址、配图和端口。
- `config/local/secrets.json`：`sub2api_api_key`；需要独立生图服务时填写 `image_api_key`。NapCat、OneBot 和可选桌面任务服务的访问令牌会自动生成。
- `config/local/modes.json`：三种模式的完整提示词。
- `config/local/characters.json` 与 `config/local/assets/characters/`：角色资料与参考图。

`bot.listen_mode` 默认为 `allowlist`，只读取 `groups` 列出的群；改为 `all` 可开放该 QQ 账号的全部群，回复仍按来源聊天路由。默认只允许明确配置的群，私聊关闭。

`chat.artificial_typos` 默认关闭，避免内置模块为了模拟真人而改坏正确文字；`chat.typing_speed` 默认 0，去掉模拟打字等待。自然分气泡仍保留。

```powershell
.\run.cmd api-check
# 查询服务实际允许的模型标识，不产生聊天或图片请求。
.\run.cmd configure
.\run.cmd start
.\run.cmd webui
.\run.cmd napcat-webui
```

使用 `webui` 打印的一次性链接进入 MaiBot；使用 `napcat-webui` 的链接进入 NapCat，再用手机 QQ 扫码授权。两处 QQ 账号必须一致。首次联调只开放测试群，旧版监听应先停止，防止两个程序同时回复。

若尚未填写 API Key，可先运行 `run.cmd setup` 查看 MaiBot 管理页面。此时 QQ 连接器自动停用，不会不停请求模型。Key 不需要发给开发者，也不要放进 Git。

API 地址在 `api.base_url` 中配置。宿主机服务可通过 `host.docker.internal` 从容器访问；也可使用自己的远程服务。先用 `api-check` 验证可用模型。Responses 的思考强度使用 `reasoning.effort`，Chat Completions 使用 `reasoning_effort`，项目会按客户端类型生成参数。

## 管理

| 命令 | 用途 |
|---|---|
| `run.cmd start` | 检查配置后启动两项服务 |
| `run.cmd stop` | 停止，保留配置、QQ 登录与聊天数据 |
| `run.cmd restart` | 重启服务，不重新问 AI、不重发消息 |
| `run.cmd status` | 显示容器、MaiBot 内部 Bot 状态、QQ 连接及账号是否匹配 |
| `run.cmd logs` | 查看日志；Ctrl+C 只退出日志 |
| `run.cmd doctor` | 检查 Docker 和配置是否具备启动条件 |
| `run.cmd configure` | 将本地配置应用到运行文件并备份旧文件 |
| `run.cmd test` | 运行离线测试，不向 QQ 或真实模型发送消息 |

常用模型、人设、群白名单、聊天频率等也能在 MaiBot 原生 WebUI 修改。大肥龙扩展设置提供闲聊配图概率选项 0%、10%、30%、50%、80%、100%。`configure` 是明确的重新应用操作，会以 `config/local/` 覆盖本项目管理的设置；普通 `start/restart` 不会重新生成或覆盖 WebUI 调整。

群聊命令：`/模式` 查看，`/模式 大肥龙模式`、`/模式 正经模式`、`/模式 猫娘模式` 切换。任何群友可用，**当前切换作用于这个 Bot 的全部会话**。开放多个群之前应评估是否需要各群独立模式。

## 功能与当前边界

详细状态见 [功能迁移清单](docs/features.md)。已经接入自然聊天、连续消息合并、原生提及、三模式、人设资料、10 MiB 文件限制、生图/改图工具和表格图片工具。运行框架、离线测试通过与真实 QQ/API 端到端通过，是不同的验证阶段。

生图单独配置 `images.enabled/model/base_url`。默认通过 `/v1/images/generations`，需要原图或角色参考图时通过 `/v1/images/edits`。sub2api 的账号、API 分组、版本和模型必须实际支持这些端点，**聊天成功不代表生图成功**。没有配置生图模型时明确报错，不假装已生成。

普通作图保持高质量、保留用户主题；仅 `sticker/casual_sticker` 转成 300×300 PNG、96 DPI。只有 `casual_sticker` 检查概率和冷却；明确作图任务不受影响。GPT 娘优先的规则只用于随聊天生成的反应表情。不会恢复旧表情库或下载陌生来源图片。

图片生成超时可能已在上游执行，所以不会盲目重复提交。生成结果先写入 `data/core/plugins/local.daifeilong/generated/`，再按来源聊天发送；未确认发送不会重生成或自动整条重发。

## 结构

```text
run.cmd / run.sh        唯一命令入口
compose.yaml           服务编排
docker/                运行镜像
scripts/               初始化、配置、环境检查与管理
plugins/daifeilong/     自定义业务扩展
services/desktop-worker/ 可选普通ChatGPT任务服务、原生适配器及内部测试
config/examples/       可提交的通用示例
config/local/          私人配置、人设、密钥、参考图（忽略 Git）
config/generated/      运行配置、宿主凭据、模型目录、配置备份（忽略 Git）
vendor/                锁定的官方 QQ 连接器（init 下载，忽略 Git）
data/                  聊天数据库、QQ 登录、插件数据和输出
logs/                  日志
tests/                 离线验证
sources.lock.json      上游版本、提交与容器摘要
docs/                  迁移与验收说明
```

宿主路径全部相对项目目录解析；容器内固定的 `/MaiMBot`、`/project` 是部署接口，不依赖旧电脑用户名或盘符。

## 迁移与升级

1. `run.cmd stop` 后备份 `config/`。需要保留记忆、聊天历史和登录态时，同时备份 `data/`。
2. 在新电脑下载源码，安装并启动 Docker，运行 `init` 下载锁定的连接器。
3. 恢复自己的 `config/local/`，调整接口地址和端口。完整恢复时还要带上 `config/generated/` 与 `data/`，不要覆盖现有数据。
4. 运行 `configure`、`doctor`、`start`。QQ 可能要求重新扫码；登录态不能保证跨机器永久可用。

当前锁定 MaiBot 1.4.3、SDK 2.22.1、NapCat 镜像摘要及 QQ 连接器提交。升级应先备份，再更新锁定版本并验证，不在运行时自动拉取 latest。

当前官方 QQ 连接器的 manifest 仍声明最高 MaiBot 1.3.99；本项目仅将这一上限适配为 1.4.99，已核对 SDK 并验证加载。没有关闭其他版本检查或修改 MaiBot 核心，补丁记录在 `sources.lock.json`。

来源：[MaiBot](https://github.com/Mai-with-u/MaiBot)、[官方 QQ 连接器](https://github.com/Mai-with-u/MaiBot-SnowLuma-Adapter)、[NapCat](https://github.com/NapNeko/NapCatQQ)。NapCat 是非官方个人 QQ 接入，账号侧限制不会因改用 Docker 消失。

## 分支与脱敏

`main` 仅保留空提交；当前完整实现位于 `develop_with_window_needed`。本分支包含可选 Windows 窗口服务，尚未接入 Codex ACP。独立发布副本不含旧提交历史、私人配置、密钥、QQ 登录、聊天数据、参考图或二进制运行时，详见 [脱敏与发布说明](docs/publication.md)。
