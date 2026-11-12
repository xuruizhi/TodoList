# 滴答清单桌面任务悬浮窗 · 项目指令

## 项目概览

从滴答清单（Dida365）官方开放接口同步**今天的任务**，按**标签分组**显示在 Windows 桌面右上角的无边框悬浮窗（Tkinter）。无主界面，常驻桌面，支持标记完成 / 撤销 / 改期 / 删除 / 在滴答清单中打开。

- 平台：Windows（依赖 tkinter；有开机自启、Windows 启动文件夹逻辑）
- 语言：Python，**仅使用标准库**（`tkinter` + `urllib`），不引入任何第三方依赖
- 分发：`DidaWidget.exe`（PyInstaller 打包，推荐）或 `启动桌面任务.bat`（系统 Python 启动）

## 关键文件

| 文件 | 作用 |
|---|---|
| `dida_widget.py` | 主程序，单文件（约 1300 行），全部逻辑在此 |
| `DidaWidget.exe` | PyInstaller 打包产物（由 `dida_widget.py` 生成） |
| `启动桌面任务.bat` | 用系统 Python 无控制台启动源码 |
| `config.example.json` | 配置模板（可直接分发的空白口令版本） |
| `config.json` | **本机实际配置（含明文 API 口令，勿提交 / 勿分享 / 勿写入文档）** |
| `widget.log` | 运行日志（GBK 落盘，文本编辑器看可能乱码，属正常现象） |
| `README.md` | 面向使用者的说明文档 |

## 程序结构（`dida_widget.py`）

- **工具/接口层**（模块级函数）：`log` / `load_config` / `save_config` / `parse_dt` / `to_utc_str` / `fetch_today` / `complete_task` / `undo_task` / `delete_task` / `reschedule_task` / `_sort_key` 等
- **`Widget` 类**：全部 UI 与交互。分区大致为：`_build_ui`（构建）→ 拖拽调整大小 `_resize_*` / `_on_wheel` → 数据刷新 `_fetch_worker` / `_apply_data` / `_render` / `_render_row` → 任务操作 `_task_menu` / `_quick_reschedule` / `_custom_reschedule` / `_complete_worker` → 设置 `open_settings` → 开机自启 `_add_autostart` / `_remove_autostart`
- **`main()`**：入口；`--smoke` 参数用于假口令构建 UI、3 秒自动退出的冒烟测试（不写配置）
- 网络请求在后台线程执行，UI 更新回主线程；`load_config` 用 `_cfg_lock` 保护并缓存

## 接口与业务口径（改动前务必理解）

- Base URL：`https://api.dida365.com/open/v1`；认证为官方 **API 口令**（Bearer Token），非 OAuth
- 任务列表：`POST /task/filter`（`GET /task` 不被支持）；已完成：`POST /task/completed`
- 撤销完成无独立接口：`GET` 回任务 → 置 `status=0`、去掉 `completedTime` → `POST /task/{id}`
- 「今天的任务」= 今天到期 + 逾期未完成 + 今天已完成（对齐滴答「今天」智能清单）
- **时间字段一律 UTC 字符串**；`isAllDay` 区分全天/定时；改期需同步维护 `startDate`（见 `reschedule_task`）
- 显示口径与网页版对齐：今天的定时任务显示 `HH:MM`，今天全天显示「今天」，其他日期标日期（不显示「逾期」）

## 约定与注意事项

- **保持零第三方依赖**：新增功能只用标准库，否则会破坏「解压即用 / 打包即用」的分发形态
- **路径逻辑**：`FROZEN`（PyInstaller）时 `APP_DIR` 取 exe 所在目录，否则取源码所在目录；配置文件与日志始终随程序目录，勿改成用户目录
- **配置**：读写经 `load_config` / `save_config`；`window` / `font` 为嵌套字典，只以非 `None` 值覆盖默认配置（见 `load_config`），新增配置项要同时补到 `DEFAULT_CONFIG` 与 `config.example.json`
- **主题**：字体/颜色统一走 `self.th`（由 `_load_theme` 生成），改样式后需 `_retheme()` 重绘
- **中文界面与日志**：所有面向用户的文案、`log()` 内容使用简体中文
- **绝不泄露 `config.json` 中的 `access_token`**；截图 / 调试时如需假口令，用 `smoke-test-token` 之类的假值，勿动真实配置

## 常见维护操作

- **验证 UI 不崩溃**：`python dida_widget.py --smoke`（3 秒后自动退出，不改配置）
- **手动启动**：`pythonw dida_widget.py` 或双击 `启动桌面任务.bat`
- **重新打包 exe**（需先安装 PyInstaller）：`pyinstaller -F -w -n DidaWidget dida_widget.py`（打包前确认 `dida_widget.py` 能 `--smoke` 通过）
- **排查线上问题**：查看 `widget.log` 末尾；日志为 GBK，PowerShell 下 `Get-Content widget.log -Tail 20` 可读，编辑器若乱码属编码显示问题，不是文件损坏

## 环境与运行要求

- 程序要求 Python ≥ 3.10（含 tkinter，Windows 版 Python 默认自带）
- 从源码运行：`python dida_widget.py`；无控制台方式可用 `pythonw` 或 `启动桌面任务.bat`（脚本调用 PATH 中的 `pythonw`）
- 重新打包 exe 需自行安装 PyInstaller：`pip install pyinstaller`
