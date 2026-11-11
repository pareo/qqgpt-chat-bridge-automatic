# 大肥龙舞萌 DX

首版使用水鱼官方 HTTP API 和 OAuth。曲库与等级来自水鱼，歌曲昵称来自柚子的公开别名库。QQ群指令由 MaiBot 直接处理，B50 在本机排版成 PNG。

## 首次绑定

1. 在水鱼开发者控制台创建机密客户端，启用设备码绑定与代用户换票。申请 `prober.records.read`。如需本机导入成绩，再申请 `prober.records.write`，写权限需水鱼人工审核。
2. 在本项目 `config/local/secrets.json` 中填入 `diving_fish_client_id` 与 `diving_fish_client_secret`。无需重启。遇到容器网络问题时可在 `config/local/project.json` 里设置 `maimai.proxy`。
3. 在大肥龙的电脑，从项目根目录运行以下命令。浏览器授权页会显示被绑定 QQ 的部分数字，请核对后授权。链接仅在本机显示。

```powershell
$myQQ = '填自己的QQ号'
.\scripts\maimai.ps1 bind -QQ $myQQ
```

## QQ 群指令

| 命令 | 作用 |
| --- | --- |
| `@大肥龙 /绑定` | 检查当前 QQ 是否已授权 |
| `@大肥龙 /B50` | 查自己的最新 B50，按新曲 B15 和旧曲 B35 排版成图发到当前群 |
| `@大肥龙 /查歌 别名` | 按曲名、别名或 ID 查等级与定数 |
| `@大肥龙 /查歌 别名 \| 紫` | 只显示紫谱，亦可指定 `14+` 等等级 |
| `@大肥龙 /更新` | 显示水鱼的官方同步教程和本机导入提示 |
| `@大肥龙 /help` | 显示指令列表，兼容 `/查分帮助` |

## 更新成绩

可按水鱼官方教程在微信中同步最新成绩。也可以把自己的**最新**国服 NET 成绩页完整保存为 UTF-8 HTML，然后从大肥龙的电脑导入。旧快照可能覆盖水鱼中已有的较新记录。

```powershell
.\scripts\maimai.ps1 bind -QQ $myQQ -AllowImport
# 打开本机输出的链接，完成授权后再导入
.\scripts\maimai.ps1 import -QQ $myQQ -File 'C:\path\to\net-score.html'
```

本机导入会显示水鱼返回的更新与新增条数。超时后请先在水鱼网页核对结果。文件只发往水鱼 HTTPS 导入接口。

[水鱼开发者控制台](https://auth.diving-fish.com/console) · [OAuth 快速开始](https://maimai.diving-fish.com/manual/docs/developer/oauth-quickstart/) · [成绩同步教程](https://maimai.diving-fish.com/manual/docs/update-records/proxy/)
