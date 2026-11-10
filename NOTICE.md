本项目的主体运行时来自 MaiBot，QQ 接入来自官方统一 QQ 连接器与 NapCat。

- MaiBot：https://github.com/Mai-with-u/MaiBot ，GPL-3.0。
- 统一 QQ 连接器：https://github.com/Mai-with-u/MaiBot-SnowLuma-Adapter ，其 manifest 声明 GPL-v3.0-or-later。
- SDK：https://github.com/Mai-with-u/maibot-plugin-sdk 。运行依赖由上游镜像提供。
- NapCat：https://github.com/NapNeko/NapCatQQ 。独立容器运行，通过公开 OneBot 接口通信；不将其核心源码并入本仓库。

部署镜像与连接器提交记录在 sources.lock.json。QQ 连接器的本地兼容改动只涉及 manifest 的宿主最高版本声明；其余源码保留上游版本。未来分发镜像或连接器源码时，须保留相应声明及履行上游许可证要求。

私人运行目录中的角色图由用户提供，未随源码公开，也未以本项目许可证重新授权。示例模式是通用占位文案，实际人设保存在 Git 忽略的 config/local/。

可选 Windows ChatGPT 任务服务提取自用户提供的 qqgpt-chat-bridge 1.21.0 源码，遵循本项目 GPL-3.0-or-later 分发。原始文件 SHA-256、提取范围和本地改动说明位于 services/desktop-worker/provenance.json；不分发旧配置、凭据、聊天数据或便携运行时。
