# TodoList · 滴答清单桌面任务悬浮窗

把 [滴答清单（Dida365）](https://www.dida365.com) 里**今天的任务**同步到一个轻量的桌面悬浮窗中，按标签分组展示，随时看一眼今天要做什么，无需打开浏览器或手机 App。

> 项目源码位于 [`dida365-widget/`](dida365-widget/)，详细的文件说明与操作手册见 [dida365-widget/README.md](dida365-widget/README.md)。

## 功能特性

- **今日任务一览**：自动同步"今天"智能清单（今天到期 + 逾期未完成 + 今天已完成）。
- **按标签分组**：任务按第一个标签归类，无标签归入「无标签」组。
- **桌面悬浮**：无边框置顶小窗，可拖动、可自由调整大小，位置与尺寸自动记忆。
- **任务操作**：单击完成/撤销完成；右键标记完成、改期（今天 / 明天 / 后天 / 自定义日期时间）、在滴答清单中打开、删除。
- **定时刷新**：默认自动同步，刷新时保持滚动位置不跳动。
- **个性化**：字体 / 字号 / 文字颜色 / 强调色、窗口置顶、显示已完成、开机自启均可配置。
- **零第三方依赖**：主程序仅使用 Python 标准库（tkinter + urllib），也可直接运行打包好的 `DidaWidget.exe`。

## 快速开始

1. **获取 API 口令**
   登录 <https://www.dida365.com> → 左上角**头像** → **设置** → **账户与安全** → **API 口令** → 创建并复制。

2. **启动程序**
   - 方式一（推荐）：双击 `dida365-widget/DidaWidget.exe`，开箱即用，无需 Python 环境。
   - 方式二：双击 `dida365-widget/启动桌面任务.bat`，使用系统 Python 启动（无控制台窗口）。

3. **粘贴口令并连接**
   首次运行会弹出设置窗口，粘贴口令后点「保存并连接」。悬浮窗即出现在桌面右上角。

> 若使用源码运行，需要 Python ≥ 3.10（开发环境为 3.13）。

## 目录结构

| 路径 | 说明 |
|---|---|
| `dida365-widget/dida_widget.py` | 主程序源码（仅依赖 Python 标准库） |
| `dida365-widget/DidaWidget.exe` | 独立打包版，双击即用，不依赖 Python 环境 |
| `dida365-widget/启动桌面任务.bat` | 使用系统 Python 启动悬浮窗的批处理脚本 |
| `dida365-widget/config.example.json` | 配置文件模板（复制为 `config.json` 后填入自己的口令） |
| `dida365-widget/README.md` | 完整的操作说明与常见问题 |

## 配置说明

程序首次运行会在同目录生成 `config.json`，保存 API 口令、窗口位置、刷新间隔、字体外观等。仓库中只提供模板 `config.example.json`：

```bash
cp dida365-widget/config.example.json dida365-widget/config.json
```

然后编辑 `config.json`，把 `"access_token": ""` 换成你自己的口令即可。

## 安全与隐私

- ⚠️ **`config.json` 内含明文 API 口令，已被 `.gitignore` 排除，请勿提交或分享。**
- 仓库中不包含任何真实的账号口令或隐私数据；如需配置，请基于 `config.example.json` 自行创建。
- 如怀疑口令泄露，请及时到滴答清单「账户与安全」中重置 API 口令。

## 技术说明

- 使用滴答清单官方开放接口 `https://api.dida365.com/open/v1`（任务查询 `POST /task/filter`，时间字段为 UTC），认证方式为官方 API 口令（Bearer Token）。
- "今天的任务"口径 = 今天到期 + 逾期未完成 + 今天已完成，与滴答清单「今天」智能清单一致。
- 程序可离线运行（本地任务操作即时生效，同步失败会定时重试）。

## License

本项目仅用于个人学习与效率工具用途。滴答清单及 Dida365 为其各自所有者的商标。
