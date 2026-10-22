# -*- coding: utf-8 -*-
"""
滴答清单桌面任务悬浮窗
================================
- 从滴答清单(Dida365)同步"今天的任务"：今天到期 + 逾期未完成 + 今天已完成
- 常驻桌面右上角的无边框悬浮窗，无主界面
- 支持操作：标记完成 / 撤销完成 / 改期(今天/明天/后天/自定义) / 删除 / 在滴答清单中打开
- 按标签分组显示；窗口置顶可开关（默认不置顶）
- 显示口径与网页版滴答清单对齐：今天的全天任务显示「今天」，其他日期标注日期
- 支持界面设置：字体、字号、文字颜色、强调色
- 仅依赖 Python 标准库（tkinter + urllib），无需安装任何第三方包

首次使用：
    1. 打开 https://www.dida365.com ，登录后点击左上角头像 → 设置 → 账户与安全 → API 口令
    2. 创建并复制口令，启动本程序后粘贴到设置窗口中即可
"""

import json
import os
import re
import shutil
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
import tkinter.ttk as ttk
import webbrowser
from datetime import datetime, date, timedelta, timezone
from tkinter import colorchooser, messagebox, simpledialog
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

FROZEN = getattr(sys, "frozen", False)
if FROZEN:
    # PyInstaller 打包：__file__ 指向临时解压目录，配置应保存在 exe 所在目录
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
LOG_PATH = os.path.join(APP_DIR, "widget.log")
API_BASE = "https://api.dida365.com/open/v1"
DIDA_WEB = "https://www.dida365.com"
UA = "DidaDesktopWidget/3.0"

DEFAULT_CONFIG = {
    "access_token": "",
    "window": {"x": None, "y": None, "width": 344, "height": None},
    "refresh_minutes": 5,
    "show_completed": True,
    "topmost": False,
    "font": {"family": None, "size": 9, "text_color": None, "accent_color": None},
    "pythonw_path": "",
}

# ---------------- 默认配色 ----------------
PRIORITY_COLOR = {5: "#EF4444", 3: "#F59E0B", 1: "#3B82F6", 0: "#E5E7EB"}
FONT = "Microsoft YaHei UI"
COLOR_BORDER = "#E2E8F0"       # 窗口细边框
COLOR_BG = "#FFFFFF"           # 主体背景
COLOR_HEADER_BG = "#FFFFFF"    # 标题栏背景
COLOR_HEADER_TEXT = "#1E293B"  # 标题文字
COLOR_TEXT = "#1E293B"         # 任务文字
COLOR_SUB = "#94A3B8"          # 次要文字
COLOR_ACCENT = "#3B82F6"       # 强调色（今天时间 / 置顶 / 分组条）
COLOR_GROUP_BG = "#F8FAFC"     # 分组头背景
COLOR_GROUP_TEXT = "#64748B"   # 分组名
COLOR_STATUS_BG = "#F8FAFC"
COLOR_COMPLETED = "#CBD5E1"    # 已完成
COLOR_HOVER = "#F1F5F9"        # 行悬停
COLOR_DIVIDER = "#EEF2F7"      # 分隔线
COLOR_DANGER = "#EF4444"       # 关闭按钮悬停 / 错误提示

# 窗口尺寸范围（可拖拽调整）
WIN_MIN_W, WIN_MAX_W = 260, 900
WIN_MIN_H, WIN_MAX_H = 120, 1000

_cfg_lock = threading.Lock()
_cfg = None


# ---------------------------------------------------------------- 工具函数

def log(msg):
    """写日志文件，便于排查问题。"""
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def load_config():
    global _cfg
    with _cfg_lock:
        if _cfg is not None:
            return _cfg
        cfg = dict(DEFAULT_CONFIG)
        cfg["window"] = dict(DEFAULT_CONFIG["window"])
        cfg["font"] = dict(DEFAULT_CONFIG["font"])
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            for k, v in saved.items():
                if k == "window" and isinstance(v, dict):
                    cfg["window"].update({kk: vv for kk, vv in v.items() if vv is not None})
                elif k == "font" and isinstance(v, dict):
                    cfg["font"].update({kk: vv for kk, vv in v.items() if vv is not None})
                else:
                    cfg[k] = v
        except FileNotFoundError:
            pass
        except Exception as e:
            log("读取配置失败: %r" % e)
        _cfg = cfg
        return cfg


def save_config():
    global _cfg
    with _cfg_lock:
        if _cfg is None:
            return
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(_cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log("保存配置失败: %r" % e)


def parse_dt(s):
    """解析 API 时间字符串（格式形如 2026-09-23T16:00:00.000+0000），
    统一转换为本地时区；无时区时按本地时间处理。"""
    if not s:
        return None
    t = re.sub(r"([+-]\d\d)$", r"\1:00", s)
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone()


def local_tz():
    """本地时区对象（用于构造本地时间）。"""
    return datetime.now().astimezone().tzinfo


def to_utc_str(dt):
    """本地 datetime 转 API 使用的 UTC 字符串格式：2026-09-29T01:00:00.000+0000"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=local_tz())
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000+0000")


def truncate(text, font, max_px):
    """按像素宽度截断文本，超出部分加省略号。"""
    if font.measure(text) <= max_px:
        return text
    lo, hi = 1, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if font.measure(text[:mid] + "…") <= max_px:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + "…"


def _fmt_date(d):
    """日期标注：与网页版滴答清单一致，今年显示「9月23日」，跨年显示「2025年6月30日」。"""
    if d.year == date.today().year:
        return "%d月%d日" % (d.month, d.day)
    return "%d年%d月%d日" % (d.year, d.month, d.day)


def _due_label(t, th):
    """返回 (标注文本, 颜色)。与网页版拉齐：今天→时间或「今天」；其他日期→标注日期。"""
    due_dt = parse_dt(t.get("dueDate"))
    today = date.today()
    if not due_dt:
        return "", th["sub"]
    d = due_dt.date()
    if t.get("isAllDay"):
        if d == today:
            return "今天", th["sub"]
        return _fmt_date(d), th["sub"]
    if d == today:
        return due_dt.strftime("%H:%M"), th["accent"]
    return _fmt_date(d) + " " + due_dt.strftime("%H:%M"), th["sub"]


def _group_due(due):
    """按第一个标签分组；无标签归入「无标签」。返回 [(标签, [任务]), ...]，无标签在最后。"""
    groups = []
    index = {}
    for t in due:
        tags = t.get("tags") or []
        key = tags[0] if tags else ""
        if key not in index:
            index[key] = len(groups)
            groups.append([key, []])
        groups[index[key]][1].append(t)
    groups.sort(key=lambda g: (1 if g[0] == "" else 0, g[0]))
    return groups


# ---------------------------------------------------------------- API 封装

class ApiError(Exception):
    def __init__(self, msg, status=None):
        super().__init__(msg)
        self.status = status


def api_call(method, path, body=None, timeout=20):
    cfg = load_config()
    token = cfg.get("access_token") or ""
    if not token:
        raise ApiError("未配置 API 口令")
    url = API_BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", UA)
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "ignore")[:200]
        except Exception:
            pass
        raise ApiError("HTTP %s %s" % (e.code, detail), e.code)
    except URLError as e:
        raise ApiError("网络错误: %s" % e.reason)


def fetch_today():
    """拉取今天的任务，返回 (待办列表, 已完成列表)。
    今天的任务 = 今天到期 + 逾期未完成（与滴答清单「今天」智能清单口径一致）。"""
    now_local = datetime.now().astimezone()
    today = now_local.date()
    t0 = datetime(today.year, today.month, today.day, 0, 0, 0, tzinfo=now_local.tzinfo)
    t1 = t0 + timedelta(days=1) - timedelta(microseconds=1)

    # 任务列表接口为 POST /task/filter（GET /task 在该接口上不受支持）
    try:
        tasks = api_call("POST", "/task/filter", {"status": [0]}) or []
    except ApiError:
        tasks = api_call("POST", "/task/filter", {}) or []

    due = []
    for t in tasks:
        d = parse_dt(t.get("dueDate"))
        if d and d <= t1:
            due.append(t)

    completed = []
    try:
        comp = api_call("POST", "/task/completed", {
            "startDate": to_utc_str(t0),
            "endDate": to_utc_str(t1),
        }) or []
        for t in comp:
            ct = parse_dt(t.get("completedTime"))
            if ct and t0 <= ct <= t1:
                completed.append(t)
    except ApiError as e:
        log("拉取已完成任务失败(忽略): %s" % e)

    return due, completed


def _sort_key(t):
    d = parse_dt(t.get("dueDate"))
    timed = bool(d and not t.get("isAllDay"))
    return (
        0 if timed else 1,
        d.strftime("%H:%M") if timed else "",
        -int(t.get("priority") or 0),
        (t.get("title") or "").lower(),
    )


def complete_task(t):
    pid, tid = t.get("projectId"), t.get("id")
    api_call("POST", "/project/%s/task/%s/complete" % (pid, tid), {})


def undo_task(t):
    """滴答清单中国版无独立撤销接口：先查回任务，再用更新接口把状态改回未完成。"""
    pid, tid = t.get("projectId"), t.get("id")
    got = api_call("GET", "/project/%s/task/%s" % (pid, tid))
    body = dict(got)
    body["status"] = 0
    body.pop("completedTime", None)
    api_call("POST", "/task/%s" % tid, body)


def delete_task(t):
    pid, tid = t.get("projectId"), t.get("id")
    api_call("DELETE", "/project/%s/task/%s" % (pid, tid))


def reschedule_task(t, new_dt, all_day):
    """修改任务到期时间。all_day=True 表示全天任务，否则保留时分。
    时间以 UTC 字符串格式提交（与接口返回格式一致）。"""
    body = dict(t)
    if new_dt.tzinfo is None:
        new_dt = new_dt.replace(tzinfo=local_tz())
    orig_due = parse_dt(t.get("dueDate"))
    orig_start = parse_dt(t.get("startDate"))
    if all_day:
        body["dueDate"] = to_utc_str(new_dt)
        body["startDate"] = to_utc_str(new_dt)
        body["isAllDay"] = True
    else:
        body["dueDate"] = to_utc_str(new_dt)
        # 开始时间与到期同一天的，跟随一起移动；否则保留原值
        if orig_start and orig_due and orig_start.date() == orig_due.date():
            body["startDate"] = to_utc_str(new_dt)
        else:
            body["startDate"] = t.get("startDate")
        body["isAllDay"] = False
    api_call("POST", "/task/%s" % t.get("id"), body)


# ---------------------------------------------------------------- 主窗口

class Widget:
    def __init__(self, smoke=False):
        self.smoke = smoke
        self.cfg = load_config()
        self.due = []
        self.completed = []
        self.refreshing = False
        self.drag_info = None
        self._refresh_job = None
        self._chrome = None
        self.th = self._load_theme()

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("滴答清单今日任务")
        self.root.configure(bg=COLOR_BORDER)
        self.root.overrideredirect(True)
        try:
            self.root.attributes("-topmost", bool(self.cfg.get("topmost")))
            self.root.attributes("-alpha", 0.97)
        except Exception:
            pass

        self._build_ui()
        self._place_window()
        self.root.deiconify()

        if not self.cfg.get("access_token"):
            self.root.after(300, self.open_settings)

        self.root.after(400, self.refresh)
        minutes = max(0, int(self.cfg.get("refresh_minutes") or 5))
        if minutes > 0:
            self._schedule_refresh(minutes * 60000)

        if self.smoke:
            self.root.after(3000, self.root.destroy)

    # ---------------- 主题

    def _load_theme(self):
        """从配置解析界面主题（字体族 / 字号 / 文字色 / 强调色）。"""
        f = self.cfg.get("font") or {}
        try:
            size = int(f.get("size") or 9)
        except (TypeError, ValueError):
            size = 9
        size = max(7, min(18, size))
        return {
            "family": (f.get("family") or "").strip() or FONT,
            "size": size,
            "small": max(7, size - 1),
            "text": f.get("text_color") or COLOR_TEXT,
            "accent": f.get("accent_color") or COLOR_ACCENT,
            "sub": COLOR_SUB,
            "completed": COLOR_COMPLETED,
        }

    def _row_h(self):
        return self.th["size"] + 21

    def _group_h(self):
        return self.th["size"] + 17

    def _header_h(self):
        return self.th["size"] + 21

    def _status_h(self):
        return self.th["size"] + 11

    def _retheme(self):
        """应用新的字体/颜色配置并重绘。"""
        self._chrome = None
        self.th = self._load_theme()
        self.title_label.configure(
            font=(self.th["family"], self.th["size"], "bold"), fg=self.th["text"])
        for b in (self.pin_btn, self._close_btn, self._refresh_btn):
            b.configure(font=(self.th["family"], self.th["size"]))
        self.status_bar.configure(font=(self.th["family"], self.th["small"]))
        self.header.configure(height=self._header_h())
        self._update_pin_ui()
        self._render()

    # ---------------- 界面构建

    def _make_header_btn(self, text, cmd, danger=False):
        """标题栏小按钮：默认灰色，悬停变强调色（关闭按钮变红色）。"""
        btn = tk.Label(self.header, text=text, bg=COLOR_HEADER_BG, fg=COLOR_SUB,
                       font=(self.th["family"], self.th["size"]), cursor="hand2", padx=5)
        btn.bind("<Button-1>", lambda e, c=cmd: c())
        btn.bind("<Enter>", lambda e, b=btn, d=danger: b.configure(fg=COLOR_DANGER if d else self.th["accent"]))
        btn.bind("<Leave>", lambda e, b=btn, d=danger: b.configure(fg=COLOR_SUB))
        return btn

    def _build_ui(self):
        # 1px 细边框：外层容器留 1px 空隙露出 root 边框色
        self.outer = tk.Frame(self.root, bg=COLOR_BG)
        self.outer.pack(fill="both", expand=True, padx=1, pady=1)

        # 标题栏（矮版）
        self.header = tk.Frame(self.outer, bg=COLOR_HEADER_BG, height=self._header_h())
        self.header.pack(fill="x")
        self.header.pack_propagate(False)

        self.title_label = tk.Label(
            self.header, text="", bg=COLOR_HEADER_BG, fg=self.th["text"],
            font=(self.th["family"], self.th["size"], "bold"), anchor="w",
        )
        self.title_label.pack(side="left", padx=(12, 4), fill="both", expand=True)

        # 置顶按钮（📌 高亮=已置顶）
        self.pin_btn = tk.Label(self.header, text="📌", bg=COLOR_HEADER_BG, fg=COLOR_SUB,
                                font=(self.th["family"], self.th["size"]), cursor="hand2", padx=5)
        self.pin_btn.pack(side="right", padx=(0, 2))
        self.pin_btn.bind("<Button-1>", lambda e: self._pin_clicked())
        self.pin_btn.bind("<Enter>", lambda e: self.pin_btn.configure(fg=self.th["accent"]))
        self.pin_btn.bind("<Leave>", lambda e: self._update_pin_ui())

        self._close_btn = self._make_header_btn("✕", self.quit_app, danger=True)
        self._close_btn.pack(side="right", padx=(0, 8))
        self._refresh_btn = self._make_header_btn("⟳", self.refresh)
        self._refresh_btn.pack(side="right")

        # 拖拽移动（标题栏空白处）
        for w in (self.header, self.title_label):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<ButtonRelease-1>", self._drag_end)

        # 标题栏右键菜单：标题栏容器及其全部子控件都绑定，
        # 否则点击落在子控件上时事件不会冒泡到容器，菜单弹不出来
        for w in (self.header, self.title_label, self.pin_btn,
                  self._close_btn, self._refresh_btn):
            w.bind("<Button-3>", self._header_menu)

        # 状态条
        self.status_bar = tk.Label(
            self.outer, text="正在加载…", bg=COLOR_STATUS_BG, fg=COLOR_SUB,
            font=(self.th["family"], self.th["small"]), anchor="w", padx=12, pady=1,
        )
        self.status_bar.pack(fill="x")

        # 任务列表（画布 + 滚动）
        self.body = tk.Frame(self.outer, bg=COLOR_BG)
        self.body.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(self.body, bg=COLOR_BG, highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)

        self.vbar = tk.Scrollbar(self.body, orient="vertical", command=self.canvas.yview,
                                 width=8, relief="flat", troughcolor=COLOR_BG)
        self.vbar.pack(side="right", fill="y")
        self._vbar_visible = True
        self._last_content_h = 0

        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.list_frame = tk.Frame(self.canvas, bg=COLOR_BG)
        self._win_id = self.canvas.create_window((0, 0), window=self.list_frame, anchor="nw")
        self.list_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._on_canvas_config)
        self.canvas.bind("<MouseWheel>", self._on_wheel)

        self.root.bind("<MouseWheel>", self._on_wheel)

        # ------- 可拖拽调整大小 -------
        # 右侧拖动条（调宽度）
        self.right_strip = tk.Frame(self.outer, width=6, bg=COLOR_DIVIDER, cursor="sb_h_double_arrow")
        self.right_strip.pack(side="right", fill="y")
        self.right_strip.bind("<ButtonPress-1>", self._resize_w_start)
        self.right_strip.bind("<B1-Motion>", self._resize_w_move)
        self.right_strip.bind("<ButtonRelease-1>", self._resize_end)

        # 底部拖动条（调高度）
        self.bottom_strip = tk.Frame(self.outer, height=6, bg=COLOR_DIVIDER, cursor="sb_v_double_arrow")
        self.bottom_strip.pack(side="bottom", fill="x")
        self.bottom_strip.bind("<ButtonPress-1>", self._resize_h_start)
        self.bottom_strip.bind("<B1-Motion>", self._resize_h_move)
        self.bottom_strip.bind("<ButtonRelease-1>", self._resize_end)

        # 右下角手柄（同时调长宽；双击恢复自适应高度）
        self.grip_cv = tk.Canvas(self.outer, width=16, height=16, bg=COLOR_DIVIDER,
                                 highlightthickness=0, cursor="sizing")
        self.grip_cv.create_line(16, 4, 4, 16, fill="#94A3B8")
        self.grip_cv.create_line(16, 9, 9, 16, fill="#94A3B8")
        self.grip_cv.create_line(16, 13, 13, 16, fill="#94A3B8")
        self.grip_cv.place(relx=1.0, rely=1.0, anchor="se")
        self.grip_cv.bind("<ButtonPress-1>", self._resize_corner_start)
        self.grip_cv.bind("<B1-Motion>", self._resize_corner_move)
        self.grip_cv.bind("<ButtonRelease-1>", self._resize_end)
        self.grip_cv.bind("<Double-Button-1>", self._grip_auto_height)

        self._update_pin_ui()

    # ---------------- 拖拽调整大小

    def _resize_w_start(self, e):
        self._resize_info = {"w": self._win_w(), "x": e.x_root}

    def _resize_w_move(self, e):
        info = self._resize_info
        if not info or "w" not in info:
            return
        nw = max(WIN_MIN_W, min(WIN_MAX_W, info["w"] + (e.x_root - info["x"])))
        self.cfg["window"]["width"] = nw
        self.root.geometry("%dx%d+%d+%d" % (nw, self.root.winfo_height(),
                                            self.root.winfo_x(), self.root.winfo_y()))

    def _resize_h_start(self, e):
        self._resize_info = {"h": self.root.winfo_height(), "y": e.y_root}

    def _resize_h_move(self, e):
        info = self._resize_info
        if not info or "h" not in info:
            return
        nh = max(WIN_MIN_H, min(WIN_MAX_H, info["h"] + (e.y_root - info["y"])))
        self.cfg["window"]["height"] = nh
        self.root.geometry("%dx%d+%d+%d" % (self.root.winfo_width(), nh,
                                            self.root.winfo_x(), self.root.winfo_y()))

    def _resize_corner_start(self, e):
        self._resize_info = {"w": self._win_w(), "x": e.x_root,
                             "h": self.root.winfo_height(), "y": e.y_root}

    def _resize_corner_move(self, e):
        info = self._resize_info
        if not info or "w" not in info:
            return
        nw = max(WIN_MIN_W, min(WIN_MAX_W, info["w"] + (e.x_root - info["x"])))
        nh = max(WIN_MIN_H, min(WIN_MAX_H, info["h"] + (e.y_root - info["y"])))
        self.cfg["window"]["width"] = nw
        self.cfg["window"]["height"] = nh
        self.root.geometry("%dx%d+%d+%d" % (nw, nh, self.root.winfo_x(), self.root.winfo_y()))

    def _resize_end(self, e):
        if getattr(self, "_resize_info", None):
            save_config()
            self._resize_info = None
            self._render()

    def _grip_auto_height(self, e=None):
        """恢复内容自适应高度（双击右下角手柄或菜单勾选）。"""
        self.cfg["window"]["height"] = None
        save_config()
        self._render()
        if hasattr(self, "_auto_h_var"):
            self._auto_h_var.set(True)
        self.status_bar.configure(text="已恢复自适应高度", fg=COLOR_SUB)

    def _on_wheel(self, e):
        self.canvas.yview_scroll(-1 * (e.delta // 120), "units")

    def _win_w(self):
        """当前窗口宽度（用户可拖拽调整，保存在配置中）。"""
        try:
            w = int(self.cfg["window"].get("width") or 344)
        except (TypeError, ValueError):
            w = 344
        return max(WIN_MIN_W, min(WIN_MAX_W, w))

    def _on_canvas_config(self, e):
        self.canvas.itemconfigure(self._win_id, width=e.width)
        self._set_vbar(getattr(self, "_last_content_h", 0) > e.height)

    def _set_vbar(self, need):
        """需要滚动时显示滚动条，否则隐藏（避免右侧出现小三角箭头）。"""
        try:
            if need and not self._vbar_visible:
                self.vbar.pack(side="right", fill="y")
                self._vbar_visible = True
            elif not need and self._vbar_visible:
                self.vbar.pack_forget()
                self._vbar_visible = False
        except Exception:
            pass

    def _max_canvas_h(self):
        """自适应高度上限：窗口不超出屏幕底部。"""
        try:
            if self._chrome is None:
                self._measure_chrome()
            sh = self.root.winfo_screenheight()
            y = self.root.winfo_y()
            max_h = sh - y - (self._chrome or 70) - 12
            return max(300, max_h)
        except Exception:
            return 460

    def _measure_chrome(self):
        """实测固定占用高度（标题栏+状态条+底部拖动条+上下边框）。"""
        try:
            self.root.update_idletasks()
            c = self.root.winfo_height() - self.canvas.winfo_height()
            if c > 30:
                self._chrome = c
        except Exception:
            pass

    def _place_window(self):
        w = self._win_w()
        try:
            h = int(self.cfg["window"].get("height") or 400)
        except (TypeError, ValueError):
            h = 400
        h = max(WIN_MIN_H, min(WIN_MAX_H, h))
        x = self.cfg["window"].get("x")
        y = self.cfg["window"].get("y")
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        if x is None or y is None:
            x, y = sw - w - 24, 64
        # 防止窗口拖出屏幕外
        x = max(0, min(x, sw - 120))
        y = max(0, min(y, sh - 80))
        self.root.geometry("%dx%d+%d+%d" % (w, h, x, y))

    def _drag_start(self, e):
        self.drag_info = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _drag_move(self, e):
        if self.drag_info:
            dx, dy = self.drag_info
            self.root.geometry("+%d+%d" % (e.x_root - dx, e.y_root - dy))

    def _drag_end(self, e):
        if self.drag_info:
            self.cfg["window"]["x"] = self.root.winfo_x()
            self.cfg["window"]["y"] = self.root.winfo_y()
            save_config()
            self.drag_info = None

    # ---------------- 数据刷新

    def _schedule_refresh(self, interval_ms):
        if self._refresh_job:
            try:
                self.root.after_cancel(self._refresh_job)
            except Exception:
                pass
        self._refresh_job = self.root.after(interval_ms, self._auto_refresh)

    def _auto_refresh(self):
        self._refresh_job = None
        minutes = int(self.cfg.get("refresh_minutes") or 0)
        if minutes <= 0:
            return
        self.refresh(manual=False)
        self._schedule_refresh(minutes * 60000)

    def refresh(self, manual=True):
        if self.refreshing:
            return
        self.refreshing = True
        if manual:
            self.status_bar.configure(text="正在刷新…")
        threading.Thread(target=self._fetch_worker, daemon=True).start()

    def _fetch_worker(self):
        try:
            due, completed = fetch_today()
            self.root.after(0, lambda: self._apply_data(due, completed, None))
        except ApiError as e:
            log("刷新失败: %s" % e)
            self.root.after(0, lambda: self._apply_data([], [], str(e)))
        finally:
            self.refreshing = False

    def _apply_data(self, due, completed, error):
        due.sort(key=_sort_key)
        if self.cfg.get("show_completed"):
            completed.sort(key=lambda t: parse_dt(t.get("completedTime")) or datetime.min.replace(tzinfo=local_tz()), reverse=True)
        self.due, self.completed = due, completed
        if error:
            if "401" in error or "口令" in error or "HTTP 401" in error:
                self.status_bar.configure(text="API 口令无效或过期，请右键标题栏 → 设置", fg=COLOR_DANGER)
            else:
                self.status_bar.configure(text="同步失败：%s" % error, fg=COLOR_DANGER)
        else:
            now = datetime.now().strftime("%H:%M")
            interval = int(self.cfg.get("refresh_minutes") or 0)
            auto_txt = " · 每%d分钟自动刷新" % interval if interval > 0 else ""
            self.status_bar.configure(
                text="已同步 %s · 待办 %d 项%s%s" % (now, len(due),
                                                  " · 已完成 %d 项" % len(completed) if completed else "",
                                                  auto_txt),
                fg=COLOR_SUB,
            )
        self._render()

    # ---------------- 渲染

    def _render(self):
        # 记录当前滚动位置，刷新后保持（避免每次自动刷新跳回顶部）
        try:
            scroll_frac = self.canvas.yview()[0]
        except Exception:
            scroll_frac = 0.0

        for child in self.list_frame.winfo_children():
            child.destroy()

        today = date.today()
        week = "一二三四五六日"[today.weekday()]
        self.title_label.configure(text="%d月%d日 周%s" % (today.month, today.day, week))

        th = self.th
        content_h = 0
        if not self.due and not self.completed:
            tk.Label(
                self.list_frame, text="今日暂无任务", bg=COLOR_BG, fg=th["sub"],
                font=(th["family"], th["size"]), pady=24,
            ).pack(fill="x")
            content_h = 60

        # 按标签分组
        for tag, tasks in _group_due(self.due):
            self._render_group_header(tag, len(tasks))
            content_h += self._group_h()
            for t in tasks:
                self._render_row(t, completed=False)
                content_h += self._row_h()

        # 今日已完成
        if self.completed and self.cfg.get("show_completed"):
            tk.Frame(self.list_frame, bg=COLOR_DIVIDER, height=1).pack(fill="x")
            content_h += 1
            self._render_group_header("已完成", len(self.completed), accent=False)
            content_h += self._group_h()
            for t in self.completed:
                self._render_row(t, completed=True)
                content_h += self._row_h()

        # 尺寸：宽度始终由用户调整后的值决定；高度未手动调整时按内容自适应
        # chrome 用实测值（标题栏+状态条+底部拖动条+边框），自适应时内容区恰好容纳全部任务
        w = self._win_w()
        if self._chrome is None:
            self._measure_chrome()
        chrome = self._chrome or (self._header_h() + self._status_h() + 8)
        hset = self.cfg["window"].get("height")
        if hset:
            try:
                h = max(WIN_MIN_H, min(WIN_MAX_H, int(hset)))
            except (TypeError, ValueError):
                h = max(WIN_MIN_H, content_h + chrome)
            canvas_h = max(90, h - chrome)
        else:
            # 自适应：容纳全部内容（含已完成条目），上限为屏幕底部，超出才滚动
            canvas_h = min(self._max_canvas_h(), max(90, content_h))
            h = canvas_h + chrome
        self.root.geometry("%dx%d+%d+%d" % (w, h, self.root.winfo_x(), self.root.winfo_y()))
        # 内容不超一屏时隐藏滚动条，需要滚动时才显示
        self._last_content_h = content_h
        self._set_vbar(content_h > canvas_h)
        # 恢复滚动位置（等 scrollregion 更新后再滚动）
        if scroll_frac:
            self.root.after_idle(lambda f=scroll_frac: self.canvas.yview_moveto(f))

    def _render_group_header(self, tag, count, accent=True):
        th = self.th
        bar = tk.Frame(self.list_frame, bg=COLOR_GROUP_BG, height=self._group_h())
        bar.pack(fill="x")
        bar.pack_propagate(False)

        bar_color = th["accent"] if accent else COLOR_DIVIDER
        tk.Frame(bar, bg=bar_color, width=3).pack(side="left", fill="y", padx=(10, 6))

        name = tag if tag else "无标签"
        tk.Label(bar, text=name, bg=COLOR_GROUP_BG, fg=COLOR_GROUP_TEXT,
                 font=(th["family"], th["small"], "bold")).pack(side="left")
        tk.Label(bar, text=str(count), bg=COLOR_GROUP_BG, fg=COLOR_SUB,
                 font=(th["family"], th["small"])).pack(side="right", padx=(0, 12))

    def _render_row(self, t, completed=False):
        th = self.th
        row = tk.Frame(self.list_frame, bg=COLOR_BG, height=self._row_h())
        row.pack(fill="x")
        row.pack_propagate(False)

        title_font = (th["family"], th["size"], "overstrike") if completed else (th["family"], th["size"])
        fg = th["completed"] if completed else th["text"]

        # 复选框
        box = tk.Label(row, text="☑" if completed else "☐", bg=COLOR_BG,
                       fg=th["completed"] if completed else th["accent"],
                       font=(th["family"], th["size"]), cursor="hand2")
        box.pack(side="left", padx=(10, 2))

        # 优先级圆点
        pr = int(t.get("priority") or 0)
        dot = tk.Label(row, text="●", bg=COLOR_BG, fg=PRIORITY_COLOR.get(pr, "#E5E7EB"),
                       font=(th["family"], max(6, th["size"] - 2)))
        if pr == 0:
            dot.configure(fg=COLOR_BG)
        dot.pack(side="left", padx=(0, 4))

        # 时间 / 日期标注
        if completed:
            time_text, time_fg = "已完成", th["completed"]
        else:
            time_text, time_fg = _due_label(t, th)
        time_label = tk.Label(row, text=time_text, bg=COLOR_BG, fg=time_fg,
                              font=(th["family"], th["small"]))
        time_label.pack(side="right", padx=(6, 10))

        # 标题
        title = (t.get("title") or "").strip() or "(无标题)"
        tf = tkfont.Font(family=th["family"], size=th["size"], overstrike=completed)
        avail = self._win_w() - 140
        title = truncate(title, tf, avail)
        title_label = tk.Label(row, text=title, bg=COLOR_BG, fg=fg, font=title_font, anchor="w")
        title_label.pack(side="left", fill="both", expand=True, padx=(2, 2))

        # 绑定交互
        for w in (row, box, dot, title_label):
            w.bind("<Button-3>", lambda e, task=t, done=completed: self._task_menu(e, task, done))
        for w in (row, title_label, dot):
            w.bind("<Button-1>", lambda e, task=t, done=completed: self._toggle_complete(task, done))
        box.bind("<Button-1>", lambda e, task=t, done=completed: self._toggle_complete(task, done))

        # 悬停高亮
        def _enter(e, r=row):
            r.configure(bg=COLOR_HOVER)
            for c in r.winfo_children():
                if isinstance(c, tk.Label):
                    c.configure(bg=COLOR_HOVER)

        def _leave(e, r=row):
            r.configure(bg=COLOR_BG)
            for c in r.winfo_children():
                if isinstance(c, tk.Label):
                    c.configure(bg=COLOR_BG)

        for w in (row, box, dot, title_label):
            w.bind("<Enter>", _enter)
            w.bind("<Leave>", _leave)

    # ---------------- 窗口置顶

    def _set_topmost(self, val):
        self.cfg["topmost"] = bool(val)
        save_config()
        try:
            self.root.attributes("-topmost", self.cfg["topmost"])
        except Exception:
            pass
        self._update_pin_ui()
        self.status_bar.configure(
            text="窗口置顶已%s" % ("开启" if self.cfg["topmost"] else "关闭"), fg=COLOR_SUB)

    def _toggle_topmost(self):
        """标题栏右键菜单勾选回调。"""
        self._set_topmost(bool(self.topmost_var.get()))

    def _pin_clicked(self):
        val = not bool(self.cfg.get("topmost"))
        if hasattr(self, "topmost_var"):
            self.topmost_var.set(val)
        self._set_topmost(val)

    def _update_pin_ui(self):
        pinned = bool(self.cfg.get("topmost"))
        self.pin_btn.configure(fg=self.th["accent"] if pinned else COLOR_SUB)

    # ---------------- 任务操作

    def _toggle_complete(self, task, done):
        threading.Thread(target=self._complete_worker, args=(task, done), daemon=True).start()

    def _complete_worker(self, task, done):
        try:
            if done:
                undo_task(task)
            else:
                complete_task(task)
            self.root.after(0, self.refresh)
        except ApiError as e:
            log("操作失败: %s" % e)
            self.root.after(0, lambda: self.status_bar.configure(text="操作失败：%s" % e, fg=COLOR_DANGER))

    def _task_menu(self, e, task, done):
        m = tk.Menu(self.root, tearoff=0, font=(FONT, 9))
        if done:
            m.add_command(label="撤销完成", command=lambda: self._toggle_complete(task, True))
        else:
            m.add_command(label="标记完成", command=lambda: self._toggle_complete(task, False))
        m.add_separator()
        sm = tk.Menu(m, tearoff=0, font=(FONT, 9))
        sm.add_command(label="改到今天", command=lambda: self._quick_reschedule(task, 0))
        sm.add_command(label="改到明天", command=lambda: self._quick_reschedule(task, 1))
        sm.add_command(label="改到后天", command=lambda: self._quick_reschedule(task, 2))
        sm.add_command(label="自定义日期时间…", command=lambda: self._custom_reschedule(task))
        m.add_cascade(label="改期", menu=sm)
        m.add_command(label="在滴答清单中打开", command=self._open_in_dida)
        m.add_separator()
        m.add_command(label="删除任务", command=lambda: self._delete_task(task))
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    def _quick_reschedule(self, task, days):
        orig_due = parse_dt(task.get("dueDate"))
        all_day = bool(task.get("isAllDay"))
        if all_day and orig_due:
            nd = orig_due.date() + timedelta(days=days)
            new_dt = datetime(nd.year, nd.month, nd.day)
        elif orig_due:
            new_dt = orig_due + timedelta(days=days)
        else:
            nd = date.today() + timedelta(days=days)
            new_dt = datetime(nd.year, nd.month, nd.day)
            all_day = True
        self._do_reschedule(task, new_dt, all_day)

    def _custom_reschedule(self, task):
        answer = simpledialog.askstring(
            "修改到期时间", "输入新到期时间：\n\n"
            "  2026-10-01          → 全天\n"
            "  2026-10-01 14:30    → 定时\n"
            "  14:30               → 今天 14:30\n"
            "  10-02 09:00         → 今年 10月2日 09:00\n\n"
            "也可输入：今天 / 明天 / 后天",
            parent=self.root, initialvalue="",
        )
        if answer is None:
            return
        answer = answer.strip()
        if answer in ("今天", "明天", "后天"):
            days = {"今天": 0, "明天": 1, "后天": 2}[answer]
            self._quick_reschedule(task, days)
            return
        new_dt, all_day = self._parse_dt_input(answer)
        if new_dt is None:
            messagebox.showerror("格式错误", "无法识别的时间格式：%s" % answer, parent=self.root)
            return
        self._do_reschedule(task, new_dt, all_day)

    @staticmethod
    def _parse_dt_input(s):
        today = date.today()
        m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
        if m:
            y, mo, d = map(int, m.groups())
            return datetime(y, mo, d), True
        m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})", s)
        if m:
            y, mo, d, h, mi = map(int, m.groups())
            return datetime(y, mo, d, h, mi), False
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", s)
        if m:
            h, mi = map(int, m.groups())
            return datetime(today.year, today.month, today.day, h, mi), False
        m = re.fullmatch(r"(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})", s)
        if m:
            mo, d, h, mi = map(int, m.groups())
            return datetime(today.year, mo, d, h, mi), False
        return None, None

    def _do_reschedule(self, task, new_dt, all_day):
        threading.Thread(target=self._reschedule_worker, args=(task, new_dt, all_day), daemon=True).start()

    def _reschedule_worker(self, task, new_dt, all_day):
        try:
            reschedule_task(task, new_dt, all_day)
            self.root.after(0, self.refresh)
        except ApiError as e:
            log("改期失败: %s" % e)
            self.root.after(0, lambda: self.status_bar.configure(text="改期失败：%s" % e, fg=COLOR_DANGER))

    def _delete_task(self, task):
        if not messagebox.askyesno("删除任务", "确定删除任务“%s”吗？" % (task.get("title") or ""), parent=self.root):
            return
        threading.Thread(target=self._delete_worker, args=(task,), daemon=True).start()

    def _delete_worker(self, task):
        try:
            delete_task(task)
            self.root.after(0, self.refresh)
        except ApiError as e:
            log("删除失败: %s" % e)
            self.root.after(0, lambda: self.status_bar.configure(text="删除失败：%s" % e, fg=COLOR_DANGER))

    @staticmethod
    def _open_in_dida():
        try:
            os.startfile("ticktick://v1/show?smartlist=today")  # noqa
        except Exception:
            try:
                webbrowser.open(DIDA_WEB)
            except Exception:
                pass

    # ---------------- 标题栏菜单 / 设置

    def _header_menu(self, e):
        m = tk.Menu(self.root, tearoff=0, font=(FONT, 9))

        # 窗口置顶（勾选=置顶）
        self.topmost_var = tk.BooleanVar(value=bool(self.cfg.get("topmost")))
        m.add_checkbutton(label="窗口置顶", variable=self.topmost_var, command=self._toggle_topmost)

        m.add_command(label="立即刷新", command=self.refresh)

        # 自动刷新间隔（单选，当前值自动打勾）
        sm = tk.Menu(m, tearoff=0, font=(FONT, 9))
        self._refresh_var = tk.IntVar(value=int(self.cfg.get("refresh_minutes") or 0))
        for val in (1, 5, 15, 30, 60):
            sm.add_radiobutton(label="%d 分钟" % val, variable=self._refresh_var,
                               value=val, command=lambda v=val: self._set_refresh(v))
        sm.add_radiobutton(label="关闭自动刷新", variable=self._refresh_var,
                           value=0, command=lambda: self._set_refresh(0))
        m.add_cascade(label="自动刷新间隔", menu=sm)

        # 显示今日已完成（勾选=显示，合并了原来的显示/隐藏两项）
        self._completed_var = tk.BooleanVar(value=bool(self.cfg.get("show_completed", True)))
        m.add_checkbutton(label="显示今日已完成", variable=self._completed_var,
                          command=self._toggle_completed)

        # 窗口自适应高度（勾选=按内容自动伸缩）
        self._auto_h_var = tk.BooleanVar(value=self.cfg["window"].get("height") is None)
        m.add_checkbutton(label="窗口自适应高度", variable=self._auto_h_var,
                          command=self._toggle_auto_height)

        # 开机自启（勾选=已添加，合并了添加/移除两项）
        self._autostart_var = tk.BooleanVar(value=self._autostart_exists())
        m.add_checkbutton(label="开机自启", variable=self._autostart_var,
                          command=self._toggle_autostart)

        m.add_separator()
        m.add_command(label="设置…", command=self.open_settings)
        m.add_separator()
        m.add_command(label="退出", command=self.quit_app)
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    def _autostart_exists(self):
        return os.path.exists(self._startup_bat_path())

    def _toggle_auto_height(self):
        """菜单勾选项：勾选=自适应高度，取消=固定当前高度。"""
        if bool(self._auto_h_var.get()):
            self.cfg["window"]["height"] = None
            save_config()
            self._render()
            self.status_bar.configure(text="已恢复自适应高度", fg=COLOR_SUB)
        else:
            self.cfg["window"]["height"] = self.root.winfo_height()
            save_config()
            self.status_bar.configure(text="已固定当前高度", fg=COLOR_SUB)

    def _toggle_autostart(self):
        """菜单勾选项：勾选=添加开机自启，取消=移除。"""
        if bool(self._autostart_var.get()):
            self._add_autostart()
            if not self._autostart_exists():
                self._autostart_var.set(False)
        else:
            self._remove_autostart()
            if self._autostart_exists():
                self._autostart_var.set(True)

    def _set_refresh(self, minutes):
        self.cfg["refresh_minutes"] = minutes
        if hasattr(self, "_refresh_var"):
            self._refresh_var.set(minutes)
        save_config()
        if minutes > 0:
            self._schedule_refresh(minutes * 60000)
        elif self._refresh_job:
            try:
                self.root.after_cancel(self._refresh_job)
            except Exception:
                pass
            self._refresh_job = None
        self.status_bar.configure(text="自动刷新间隔：%s" % ("关闭" if minutes == 0 else "%d 分钟" % minutes), fg=COLOR_SUB)

    def _toggle_completed(self):
        self.cfg["show_completed"] = not self.cfg.get("show_completed", True)
        save_config()
        self._render()

    # ---------------- 设置（API 口令 + 界面与字体）

    def open_settings(self):
        win = tk.Toplevel(self.root)
        win.title("设置 - 滴答清单桌面任务")
        win.configure(bg="#FFFFFF")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()
        win.update_idletasks()
        x = self.root.winfo_x() + 20
        y = self.root.winfo_y() + 40
        win.geometry("+%d+%d" % (x, y))

        cur = self.th
        token_var = tk.StringVar(value=self.cfg.get("access_token") or "")
        font_var = tk.StringVar(value=cur["family"])
        size_var = tk.StringVar(value=str(cur["size"]))
        text_color_var = tk.StringVar(value=cur["text"])
        accent_color_var = tk.StringVar(value=cur["accent"])

        def _pick_color(var, swatch):
            rgb, hexv = colorchooser.askcolor(color=var.get() or "#FFFFFF", parent=win, title="选择颜色")
            if hexv:
                var.set(hexv)
                swatch.configure(bg=hexv)

        def _row(label_text, pady=(12, 3)):
            tk.Label(win, text=label_text, bg="#FFFFFF", fg=COLOR_TEXT,
                     font=(FONT, 9, "bold")).pack(anchor="w", padx=14, pady=pady)

        # ============ 第 1 部分：API 口令 ============
        _row("API 口令（Bearer Token）", pady=(14, 4))
        entry = tk.Entry(win, textvariable=token_var, width=40, font=(FONT, 9))
        entry.pack(padx=14, fill="x")

        hint = tk.Label(win, text="获取方式：登录 https://www.dida365.com\n头像 → 设置 → 账户与安全 → API 口令 → 创建并复制",
                        bg="#FFFFFF", fg=COLOR_SUB, font=(FONT, 8), justify="left")
        hint.pack(anchor="w", padx=14, pady=(6, 0))

        tk.Frame(win, bg=COLOR_DIVIDER, height=1).pack(fill="x", padx=14, pady=(10, 2))

        # ============ 第 2 部分：界面与字体 ============
        _row("界面与字体")

        # 字体候选：常用字体 + 系统已安装字体
        try:
            families = sorted(set(tkfont.families()))
        except Exception:
            families = []
        common = ["Microsoft YaHei UI", "微软雅黑", "Microsoft YaHei", "黑体", "宋体", "楷体",
                  "仿宋", "Segoe UI", "Segoe UI Emoji", "Consolas", "Arial", "Verdana",
                  "Times New Roman", "Courier New"]
        values = common + [f for f in families if f not in common]

        def _row_item(label_text):
            """返回一行控件容器：左侧为标签文本。"""
            frm = tk.Frame(win, bg="#FFFFFF")
            frm.pack(padx=14, fill="x", pady=(6, 0))
            tk.Label(frm, text=label_text, bg="#FFFFFF", fg=COLOR_TEXT,
                     font=(FONT, 9)).pack(side="left")
            return frm

        # 字体
        frm_font = _row_item("字体")
        fam_cb = ttk.Combobox(frm_font, textvariable=font_var, values=values,
                              font=(FONT, 9), width=28)
        fam_cb.pack(side="right", fill="x", expand=True)

        # 字号
        frm_size = _row_item("字号")
        size_cb = ttk.Combobox(frm_size, textvariable=size_var,
                               values=[str(i) for i in range(7, 19)],
                               font=(FONT, 9), width=6, state="readonly")
        size_cb.pack(side="right", anchor="e")

        # 文字颜色
        frm_text = _row_item("文字颜色")
        sw1 = tk.Label(frm_text, text="  ", bg=text_color_var.get(), width=4, relief="sunken")
        sw1.pack(side="right", padx=(0, 4))
        tk.Button(frm_text, text="选择…", font=(FONT, 9), relief="flat", cursor="hand2",
                  command=lambda: _pick_color(text_color_var, sw1)).pack(side="right")

        # 强调色
        frm_accent = _row_item("强调色")
        sw2 = tk.Label(frm_accent, text="  ", bg=accent_color_var.get(), width=4, relief="sunken")
        sw2.pack(side="right", padx=(0, 4))
        tk.Button(frm_accent, text="选择…", font=(FONT, 9), relief="flat", cursor="hand2",
                  command=lambda: _pick_color(accent_color_var, sw2)).pack(side="right")

        note = tk.Label(win, text="强调色：今天的时间 / 复选框 / 分组条 / 置顶按钮",
                        bg="#FFFFFF", fg=COLOR_SUB, font=(FONT, 8), justify="left")
        note.pack(anchor="w", padx=14, pady=(4, 0))

        btns = tk.Frame(win, bg="#FFFFFF")
        btns.pack(fill="x", padx=14, pady=(12, 8))

        def _reset_font():
            font_var.set(FONT)
            size_var.set("9")
            text_color_var.set(COLOR_TEXT)
            accent_color_var.set(COLOR_ACCENT)
            sw1.configure(bg=COLOR_TEXT)
            sw2.configure(bg=COLOR_ACCENT)

        def _save():
            token = token_var.get().strip()
            if not token:
                messagebox.showwarning("提示", "口令不能为空", parent=win)
                return
            try:
                size = max(7, min(18, int(size_var.get())))
            except (TypeError, ValueError):
                size = 9
            self.cfg["access_token"] = token
            self.cfg["font"] = {
                "family": (font_var.get() or "").strip() or FONT,
                "size": size,
                "text_color": text_color_var.get(),
                "accent_color": accent_color_var.get(),
            }
            save_config()
            self._retheme()
            win.destroy()
            self.status_bar.configure(text="设置已保存，正在验证口令…", fg=COLOR_SUB)
            self.refresh()

        def _open_web():
            try:
                webbrowser.open(DIDA_WEB)
            except Exception:
                pass

        tk.Button(btns, text="恢复默认字体", command=_reset_font, font=(FONT, 9), relief="flat",
                  cursor="hand2").pack(side="left")
        tk.Button(btns, text="打开滴答清单获取口令", command=_open_web, font=(FONT, 9), relief="flat",
                  padx=8, cursor="hand2").pack(side="left", padx=(8, 0))
        tk.Button(btns, text="关闭", command=win.destroy, font=(FONT, 9), relief="flat",
                  padx=8, cursor="hand2").pack(side="right")
        tk.Button(btns, text="保存并应用", command=_save, font=(FONT, 9), bg=COLOR_ACCENT, fg="white",
                  relief="flat", padx=10, cursor="hand2", activebackground="#2563EB",
                  activeforeground="white").pack(side="right", padx=(0, 4))

        entry.focus_set()

    # ---------------- 开机启动

    @staticmethod
    def _startup_bat_path():
        appdata = os.environ.get("APPDATA", "")
        return os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs",
                            "Startup", "dida-widget.bat")

    def _add_autostart(self):
        try:
            if FROZEN:
                content = '@echo off\r\nstart "" "%s"\r\n' % sys.executable
            else:
                pyw = self.cfg.get("pythonw_path") or shutil.which("pythonw") or sys.executable
                script = os.path.join(APP_DIR, "dida_widget.py")
                content = '@echo off\r\nstart "" "%s" "%s"\r\n' % (pyw, script)
            with open(self._startup_bat_path(), "w", encoding="ascii") as f:
                f.write(content)
            if not FROZEN:
                self.cfg["pythonw_path"] = pyw
            save_config()
            self.status_bar.configure(text="已添加到开机启动", fg=COLOR_SUB)
        except Exception as e:
            log("添加开机启动失败: %r" % e)
            self.status_bar.configure(text="添加开机启动失败：%s" % e, fg=COLOR_DANGER)

    def _remove_autostart(self):
        try:
            p = self._startup_bat_path()
            if os.path.exists(p):
                os.remove(p)
            self.status_bar.configure(text="已移除开机启动", fg=COLOR_SUB)
        except Exception as e:
            log("移除开机启动失败: %r" % e)
            self.status_bar.configure(text="移除开机启动失败：%s" % e, fg=COLOR_DANGER)

    # ---------------- 退出

    def quit_app(self):
        try:
            self.cfg["window"]["x"] = self.root.winfo_x()
            self.cfg["window"]["y"] = self.root.winfo_y()
            save_config()
        except Exception:
            pass
        self.root.destroy()


def main():
    smoke = "--smoke" in sys.argv
    if smoke:
        # 冒烟测试：用假口令构建界面，3 秒后自动退出，仅验证 UI 不崩溃（不写入配置）
        cfg = load_config()
        if not cfg.get("access_token"):
            cfg["access_token"] = "smoke-test-token"
    try:
        Widget(smoke=smoke)
        tk.mainloop()
    except Exception:
        import traceback
        log("程序异常退出:\n" + traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
