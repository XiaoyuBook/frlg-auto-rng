# QQ 通知独立测试工具

使用 Python + PySide6，独立于 FRLG 主程序。仅依赖 PySide6，不连接游戏、采集卡或手柄。当前阶段用于验证 QQ 通知链路，尚未接入主程序的任务通知；接入方案和后续验收清单见 [QQ 通知集成准备](../../docs/QQ_NOTIFICATION_INTEGRATION.md)。

## 启动

在当前项目中双击 `run.bat`，优先使用项目 `.venv`，不存在时使用 PATH 中的 Python。

也可以在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe tools\qq_notify_test\app.py
```

首次准备环境（项目根目录）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r tools\qq_notify_test\requirements.txt
```

也支持模块入口：`.\.venv\Scripts\python.exe -m tools.qq_notify_test.app`。

单独复制此目录使用时，安装 Python 3.12，然后执行：

```powershell
python -m pip install -r requirements.txt
python app.py
```

## 测试步骤

1. 在 QQ 开放平台创建、配置机器人，准备 AppID 和 AppSecret，以及对应的私聊／群聊权限。
2. 填入凭据，点击“验证凭据”。成功表示已获得访问令牌，不代表已验证消息发送权限。
3. 点击“绑定私聊”，在 QQ 中向机器人发送界面显示的验证码；或点击“绑定群聊”，在目标群 @机器人并发送验证码。READY 后等待 60 秒，超时可重新绑定。
4. 选择私聊、群聊或同时发送。也可手动填写已有 OpenID，OpenID 不是 QQ 号或群号。
5. 输入文字，可选一张图片，点击“发送测试通知”，在 QQ 中核对实际收到的消息。

只发送图片时可清空文字。图片会转为 JPEG，按 QQ API 分片上传；先发送文字，再发送图片。私聊和群聊分别处理，某个目标失败不阻止尝试另一个目标。

绑定时必须匹配当前验证码，不会仅凭陌生好友添加或机器人入群事件自动绑定。WebSocket 只在绑定期间存在，日常发送使用 HTTP API。网络操作在 Qt 事件循环中异步执行，支持取消；取消不能撤回已发出的消息。测试工具不自动重试发送，避免因响应丢失而重复通知。

## 配置与日志

AppID、用户／群 OpenID、发送目标保存在 `%LOCALAPPDATA%\FRLG-Auto-RNG\QQNotifyTest\config.json`，与原 BDSP 工具的配置隔离。绑定成功和关闭窗口时自动保存，也可点击“保存配置”。AppSecret、Token 不保存到文件，也不显示在日志中。

HTTP 失败会显示状态码及平台返回的错误。消息权限、可发送对象、主动消息额度等以机器人在 QQ 开放平台的实际配置为准。当前客户端使用正式环境端点。

## 离线验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tools\qq_notify_test -p "test_*.py" -v
```

测试通过本机 HTTP / WebSocket 服务模拟平台，不向 QQ 发送消息。实际账号的绑定和推送需填写自己的凭据后操作 GUI 验证。

CI 使用等价的包入口：`python -m unittest tools.qq_notify_test.test_client -v`。

## 参考实现

源码来自本机线程 `01a0bc69-34ef-7701-b2c2-e8ec45831ce0` 的 `auto-bdsp-rng/tools/qq_notify_test`。导入时是未提交文件；[SOURCE.json](SOURCE.json) 保存源仓库 HEAD、导入时间及每个原文件的 SHA-256，HEAD 本身不包含这些文件。`client.py` 的协议实现原样保留；本仓库只适配配置目录、窗口标题、包导入、依赖版本及说明。

协议流程参考 [BetterGI QqNotifier.cs](https://github.com/babalae/better-genshin-impact/blob/f29966868c6e2d5b8798bb6a4f3df201ec4a5f95/BetterGenshinImpact/Service/Notifier/QqNotifier.cs) 和同目录的 `QqWebSocketHelper.cs`，版本 `f29966868c6e2d5b8798bb6a4f3df201ec4a5f95`。本目录导入的工具源码沿用来源项目的 GPL-3.0-or-later 许可，见 [LICENSE.txt](LICENSE.txt)；该声明仅针对本工具。
