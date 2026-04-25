import json
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import fish_bot


APP_NAME = "NTE Fishing Bot"

DEFAULT_SETTINGS = {
    "start_delay": 3.0,
    "shop_enabled": True,
    "shop_every": 50,
    "buy_bait_count": 50,
    "initial_fish_before_shop": 0,
    "debug": False,
    "save_debug": False,
    "capture": "foreground-client",
    "reel_min_duration": 0.025,
    "reel_max_duration": 0.5,
    "reel_min_interval": 0.001,
    "reel_max_interval": 0.07,
    "reel_full_error": 0.08,
}

REQUIREMENT_TEXT = (
    "操作要求：遊戲設為 1920x1080 視窗、關閉 HDR、用系統管理員啟動本程式、"
    "並保持遊戲在前景。"
)


def app_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_dir():
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def clamp(value, low, high):
    return max(low, min(high, value))


class ToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def show(self, _event=None):
        if self.tip is not None or not self.text:
            return
        x = self.widget.winfo_rootx() + 18
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            self.tip,
            text=self.text,
            justify="left",
            wraplength=360,
            bg="#fff8d8",
            fg="#263445",
            relief="solid",
            borderwidth=1,
            padx=10,
            pady=7,
            font=("Microsoft JhengHei UI", 11),
        )
        label.pack()

    def hide(self, _event=None):
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, bg="#f6f8fb")
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.content = ttk.Frame(self.canvas)
        self.window_id = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.content.bind("<Configure>", self._on_content_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_content_configure(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self.window_id, width=event.width)

    def _on_mousewheel(self, event):
        if self.winfo_toplevel().focus_get() is not None:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


class FishingWorker:
    def __init__(self, settings, status_callback):
        self.settings = settings
        self.status_callback = status_callback
        self.stop_event = threading.Event()
        self.thread = None
        self.bot = None

    def start(self):
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def run(self):
        root = resource_dir()
        log_path = app_dir() / "fish_bot.log"
        logger = GuiLogger(log_path, verbose=bool(self.settings["debug"]), log_callback=self.emit_log)
        cap = None
        try:
            logger.write("gui worker starting", force=True)
            config = fish_bot.BotConfig(
                reverse=False,
                f_interval=0.5,
                click_interval=1.0,
                deadzone_ratio=0.006,
                input_mode="scancode",
                tap_duration=0.08,
                save_debug=bool(self.settings["save_debug"]),
                debug_interval=2.0,
                capture_mode=self.settings["capture"],
                reel_control="pulse",
                reel_pulse_min_interval=float(self.settings["reel_min_interval"]),
                reel_pulse_max_interval=float(self.settings["reel_max_interval"]),
                reel_pulse_min_duration=float(self.settings["reel_min_duration"]),
                reel_pulse_max_duration=float(self.settings["reel_max_duration"]),
                reel_pulse_full_error_ratio=float(self.settings["reel_full_error"]),
            )
            self.bot = fish_bot.FishingBot(root, config=config, logger=logger, debug=bool(self.settings["debug"]))
            cap = fish_bot.ScreenCapture(mode=self.settings["capture"], logger=logger)

            delay = max(0.0, float(self.settings["start_delay"]))
            end = time.monotonic() + delay
            while time.monotonic() < end and not self.stop_event.is_set():
                remain = max(0.0, end - time.monotonic())
                self.emit("countdown", f"啟動倒數 {remain:.1f}s")
                time.sleep(0.1)

            shop_every = clamp(int(self.settings["shop_every"]), 1, 99)
            next_shop_at = max(0, int(self.settings["initial_fish_before_shop"])) + shop_every
            self.emit("running", "釣魚中", fish_count=0, next_shop_at=next_shop_at)

            while not self.stop_event.is_set():
                state = self.bot.step(cap.grab())
                fish_count = self.bot.fish_caught
                self.emit(
                    "running",
                    f"狀態: {state} / 已釣: {fish_count} / 下次買賣: {next_shop_at}",
                    fish_count=fish_count,
                    next_shop_at=next_shop_at,
                )
                if self.settings["debug"]:
                    self.emit_log(
                        f"state={state} fish_count={fish_count} next_shop_at={next_shop_at} "
                        f"foreground={fish_bot.foreground_window_title()}"
                    )

                if self.settings["shop_enabled"] and fish_count >= next_shop_at:
                    self.emit("shopping", "買賣循環中", fish_count=fish_count, next_shop_at=next_shop_at)
                    fish_bot.run_shop_cycle(self.bot, buy_count=clamp(int(self.settings["buy_bait_count"]), 1, 99))
                    next_shop_at = self.bot.fish_caught + shop_every
                    self.emit(
                        "running",
                        f"買賣完成，下次: {next_shop_at}",
                        fish_count=self.bot.fish_caught,
                        next_shop_at=next_shop_at,
                    )

                time.sleep(0.05)
        except Exception as exc:
            self.emit("error", f"錯誤: {exc}")
            logger.write(f"gui worker error: {exc}", force=True)
        finally:
            if self.bot is not None:
                self.bot.release_direction()
            if cap is not None:
                cap.close()
            logger.close()
            self.emit("stopped", "已停止")

    def emit(self, state, message, **extra):
        self.status_callback({"state": state, "message": message, **extra})

    def emit_log(self, line):
        if self.settings["debug"]:
            self.status_callback({"state": "log", "message": line})


class GuiLogger(fish_bot.Logger):
    def __init__(self, path, verbose=False, log_callback=None):
        self.log_callback = log_callback
        super().__init__(path, verbose=verbose)

    def write(self, message: str, force: bool = False):
        super().write(message, force=force)
        if self.log_callback is not None and (self.verbose or force):
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            self.log_callback(f"{stamp} {message}")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("760x690")
        self.minsize(640, 500)
        self.configure(bg="#f6f8fb")
        self.settings_path = app_dir() / "settings.json"
        self.vars = {}
        self.worker = None
        self.status_var = tk.StringVar(value="待機")
        self.fish_count_var = tk.StringVar(value="0")
        self.next_shop_var = tk.StringVar(value="-")
        self.console_frame = None
        self.console_text = None
        self.console_lines = 0

        self.load_settings()
        self.build_style()
        self.build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def build_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", font=("Microsoft JhengHei UI", 11), background="#f6f8fb")
        style.configure("TFrame", background="#f6f8fb")
        style.configure("TLabel", background="#f6f8fb", foreground="#263445")
        style.configure("TCheckbutton", background="#f6f8fb")
        style.configure("TLabelframe", background="#f6f8fb", bordercolor="#d9e1ec")
        style.configure("TLabelframe.Label", background="#f6f8fb", foreground="#263445")
        style.configure("TNotebook", background="#f6f8fb", borderwidth=0)
        style.configure("TNotebook.Tab", font=("Microsoft JhengHei UI", 10), padding=(12, 5))
        style.map(
            "TNotebook.Tab",
            font=[("selected", ("Microsoft JhengHei UI", 12, "bold"))],
            padding=[("selected", (18, 8)), ("!selected", (12, 5))],
            background=[("selected", "#ffffff"), ("!selected", "#e5e9ef")],
        )
        style.configure("TButton", padding=(10, 6), font=("Microsoft JhengHei UI", 11))
        style.configure("Accent.TButton", background="#2f7de1", foreground="white")
        style.map("Accent.TButton", background=[("active", "#1f6ed4")])
        style.configure("Danger.TButton", background="#e05252", foreground="white")
        style.configure("Warn.TFrame", background="#fff4ce")
        style.configure("Warn.TLabel", background="#fff4ce", foreground="#4a3610")

    def build_ui(self):
        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)

        top = ttk.Frame(root)
        top.pack(fill="x")
        ttk.Label(top, text="NTE 自動釣魚", font=("Microsoft JhengHei UI", 17, "bold")).pack(side="left")
        ttk.Label(top, textvariable=self.status_var).pack(side="right")

        actions = ttk.Frame(root)
        actions.pack(fill="x", pady=(8, 8))
        self.start_button = ttk.Button(actions, text="啟動", style="Accent.TButton", command=self.start_bot)
        self.start_button.pack(side="left")
        ToolTip(self.start_button, "儲存目前設定後開始自動釣魚。啟動後請立刻切回遊戲前景。")
        self.stop_button = ttk.Button(actions, text="停止", style="Danger.TButton", command=self.stop_bot, state="disabled")
        self.stop_button.pack(side="left", padx=(8, 0))
        ToolTip(self.stop_button, "停止自動輸入，並釋放 A/D 方向鍵。")
        debug_button = ttk.Button(actions, text="Vision Debugger", command=self.open_vision_debugger)
        debug_button.pack(side="left", padx=(8, 0))
        ToolTip(debug_button, "開啟即時視覺偵測調參工具。")
        ttk.Button(actions, text="儲存", command=self.save_settings).pack(side="right")
        ttk.Button(actions, text="預設", command=self.reset_defaults).pack(side="right", padx=(0, 8))

        warn = ttk.Frame(root, style="Warn.TFrame", padding=(10, 8))
        warn.pack(fill="x", pady=(0, 8))
        warn_label = ttk.Label(warn, text=REQUIREMENT_TEXT, style="Warn.TLabel", wraplength=700)
        warn_label.pack(fill="x")
        ToolTip(
            warn_label,
            "解析度、HDR、權限與前景狀態會直接影響截圖辨識與 SendInput 成功率；不符合時容易漏按或卡在買賣畫面。",
        )

        stats = ttk.Frame(root)
        stats.pack(fill="x", pady=(0, 8))
        self.stat_card(stats, "已釣魚數", self.fish_count_var).pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.stat_card(stats, "下次買賣門檻", self.next_shop_var).pack(side="left", fill="x", expand=True, padx=(6, 0))

        scroller = ScrollableFrame(root)
        scroller.pack(fill="both", expand=True)

        notebook = ttk.Notebook(scroller.content)
        notebook.pack(fill="both", expand=True, padx=(0, 4), pady=(0, 8))

        main_tab = ttk.Frame(notebook, padding=10)
        reel_tab = ttk.Frame(notebook, padding=10)
        info_tab = ttk.Frame(notebook, padding=10)
        notebook.add(main_tab, text="主要")
        notebook.add(reel_tab, text="追蹤")
        notebook.add(info_tab, text="說明/免責")

        self.add_number(main_tab, "啟動延遲 秒", "start_delay", 0, 0, "按下啟動後等待幾秒才開始，方便你切回遊戲。")
        self.add_check(main_tab, "啟用買賣循環", "shop_enabled", 0, 2, "開啟後到達門檻會自動賣魚並買魚餌。")
        self.add_number(main_tab, "每幾隻買賣", "shop_every", 1, 0, "正式循環門檻。建議越大越穩，最高 99。")
        self.add_number(main_tab, "每次買餌數", "buy_bait_count", 1, 2, "每輪購買魚餌數，遊戲單次最多 99。")
        self.add_number(main_tab, "循環前前置釣數", "initial_fish_before_shop", 2, 0, "如果身上已有魚餌，先釣指定數量後才開始買賣循環。")
        self.add_check(main_tab, "Debug 日誌", "debug", 2, 2, "寫入更詳細的 fish_bot.log，方便排查狀態判斷。")
        self.add_check(main_tab, "保存除錯截圖", "save_debug", 3, 0, "保存辨識截圖，會增加硬碟寫入量。")

        self.add_number(reel_tab, "短按最小 秒", "reel_min_duration", 0, 0, "誤差很小時的最短按鍵時間。")
        self.add_number(reel_tab, "長按最大 秒", "reel_max_duration", 0, 2, "誤差很大時的最長按鍵時間。")
        self.add_number(reel_tab, "最快間隔 秒", "reel_min_interval", 1, 0, "誤差很大時兩次脈衝之間的最短等待。")
        self.add_number(reel_tab, "最慢間隔 秒", "reel_max_interval", 1, 2, "誤差很小時兩次脈衝之間的較長等待。")
        self.add_number(reel_tab, "滿力誤差比例", "reel_full_error", 2, 0, "誤差達到此比例時使用最大按壓力度。")

        info = tk.Text(
            info_tab,
            height=12,
            wrap="word",
            relief="flat",
            bg="#f6f8fb",
            fg="#263445",
            font=("Microsoft JhengHei UI", 11),
        )
        info.insert(
            "1.0",
            "操作要求\n"
            "1. 遊戲請設為 1920x1080 視窗。\n"
            "2. 關閉 HDR，避免顏色偵測偏移。\n"
            "3. 本應用需用系統管理員啟動，否則遊戲可能收不到按鍵。\n"
            "4. 目前仍須保持遊戲在前景，切到其他視窗會影響輸入與截圖。\n\n"
            "買賣門檻\n"
            "買賣流程不如釣魚本體穩定，UI 延遲或確認視窗沒點到都可能卡死。"
            "所以間隔越多越好，但每次買餌數與門檻不要超過 99，因為遊戲單次最多買 99 個魚餌。\n\n"
            "免責聲明\n"
            "此程式是非官方自動化工具，可能因遊戲更新、解析度、HDR、UI 延遲或輸入攔截而不穩定。"
            "使用本程式造成的卡死、誤操作、資源損失、帳號封鎖或其他風險，使用者需自行承擔。"
        )
        info.configure(state="disabled")
        info.pack(fill="both", expand=True)

        self.console_frame = ttk.LabelFrame(root, text="Debug 控制台輸出", padding=8)
        self.console_text = tk.Text(
            self.console_frame,
            height=7,
            wrap="word",
            bg="#101418",
            fg="#dbe7f3",
            insertbackground="#dbe7f3",
            relief="flat",
            font=("Consolas", 11),
        )
        console_scroll = ttk.Scrollbar(self.console_frame, orient="vertical", command=self.console_text.yview)
        self.console_text.configure(yscrollcommand=console_scroll.set, state="disabled")
        self.console_text.pack(side="left", fill="both", expand=True)
        console_scroll.pack(side="right", fill="y")

        self.vars["debug"].trace_add("write", lambda *_: self.refresh_console_visibility())
        self.refresh_console_visibility()

    def stat_card(self, parent, title, value_var):
        frame = ttk.Frame(parent, padding=(10, 8), relief="solid")
        ttk.Label(frame, text=title, font=("Microsoft JhengHei UI", 10)).pack(anchor="w")
        ttk.Label(frame, textvariable=value_var, font=("Microsoft JhengHei UI", 18, "bold")).pack(anchor="w")
        return frame

    def add_number(self, parent, label, key, row, col, tooltip="", width=10):
        label_widget = ttk.Label(parent, text=label)
        label_widget.grid(row=row, column=col, sticky="w", padx=(0, 6), pady=5)
        if tooltip:
            ToolTip(label_widget, tooltip)
        var = tk.StringVar(value=str(self.settings[key]))
        self.vars[key] = var
        entry = ttk.Entry(parent, textvariable=var, width=width)
        entry.grid(row=row, column=col + 1, sticky="w", pady=5)
        if tooltip:
            ToolTip(entry, tooltip)

    def add_check(self, parent, label, key, row, col, tooltip=""):
        var = tk.BooleanVar(value=bool(self.settings[key]))
        self.vars[key] = var
        check = ttk.Checkbutton(parent, text=label, variable=var)
        check.grid(row=row, column=col, columnspan=2, sticky="w", padx=(8, 0), pady=5)
        if tooltip:
            ToolTip(check, tooltip)

    def load_settings(self):
        self.settings = dict(DEFAULT_SETTINGS)
        if self.settings_path.exists():
            try:
                self.settings.update(json.loads(self.settings_path.read_text(encoding="utf-8")))
            except Exception:
                pass

    def collect_settings(self):
        settings = {}
        for key, default in DEFAULT_SETTINGS.items():
            var = self.vars.get(key)
            if var is None:
                settings[key] = self.settings.get(key, default)
                continue
            if isinstance(default, bool):
                settings[key] = bool(var.get())
            elif isinstance(default, int):
                value = int(float(var.get()))
                if key in {"shop_every", "buy_bait_count"}:
                    value = clamp(value, 1, 99)
                settings[key] = value
            elif isinstance(default, float):
                settings[key] = float(var.get())
            else:
                settings[key] = var.get()
        settings["capture"] = "foreground-client"
        return settings

    def apply_settings_to_vars(self):
        for key, value in self.settings.items():
            var = self.vars.get(key)
            if var is not None:
                var.set(value)

    def reset_defaults(self):
        self.settings = dict(DEFAULT_SETTINGS)
        self.apply_settings_to_vars()
        self.save_settings()

    def save_settings(self):
        self.settings = self.collect_settings()
        self.apply_settings_to_vars()
        self.settings_path.write_text(json.dumps(self.settings, ensure_ascii=False, indent=2), encoding="utf-8")
        self.status_var.set("設定已儲存")

    def start_bot(self):
        self.save_settings()
        self.clear_console()
        self.append_console("Debug console enabled. Starting worker...")
        self.worker = FishingWorker(self.settings, self.on_worker_status)
        self.worker.start()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")

    def stop_bot(self):
        if self.worker is not None:
            self.worker.stop()
        self.status_var.set("停止中")

    def open_vision_debugger(self):
        if getattr(sys, "frozen", False):
            subprocess.Popen([sys.executable, "--vision-debugger"], cwd=str(app_dir()))
        else:
            subprocess.Popen([sys.executable, str(Path(__file__).resolve().parent / "vision_debugger.py")], cwd=str(app_dir()))

    def on_worker_status(self, status):
        self.after(0, self.apply_worker_status, status)

    def apply_worker_status(self, status):
        if status.get("state") == "log":
            self.append_console(status.get("message", ""))
            return
        self.status_var.set(status.get("message", ""))
        if self.settings.get("debug"):
            self.append_console(status.get("message", ""))
        if "fish_count" in status:
            self.fish_count_var.set(str(status["fish_count"]))
        if "next_shop_at" in status:
            self.next_shop_var.set(str(status["next_shop_at"]))
        if status.get("state") in {"stopped", "error"}:
            self.start_button.configure(state="normal")
            self.stop_button.configure(state="disabled")

    def refresh_console_visibility(self):
        if self.console_frame is None:
            return
        debug_enabled = bool(self.vars.get("debug") and self.vars["debug"].get())
        if debug_enabled:
            if not self.console_frame.winfo_ismapped():
                self.console_frame.pack(fill="both", expand=False, pady=(8, 0))
        else:
            if self.console_frame.winfo_ismapped():
                self.console_frame.pack_forget()

    def append_console(self, line):
        if self.console_text is None or not self.settings.get("debug", False):
            return
        self.console_text.configure(state="normal")
        self.console_text.insert("end", line.rstrip() + "\n")
        self.console_lines += 1
        if self.console_lines > 500:
            self.console_text.delete("1.0", "2.0")
            self.console_lines -= 1
        self.console_text.see("end")
        self.console_text.configure(state="disabled")

    def clear_console(self):
        if self.console_text is None:
            return
        self.console_text.configure(state="normal")
        self.console_text.delete("1.0", "end")
        self.console_text.configure(state="disabled")
        self.console_lines = 0

    def on_close(self):
        self.save_settings()
        self.stop_bot()
        self.destroy()


def main():
    if "--vision-debugger" in sys.argv:
        import vision_debugger

        vision_debugger.main()
        return
    App().mainloop()


if __name__ == "__main__":
    main()
