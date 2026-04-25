import argparse
import ctypes
import os
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


USER32 = ctypes.windll.user32
GDI32 = ctypes.windll.gdi32
ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

VK_A = 0x41
VK_D = 0x44
VK_F = 0x46
VK_Q = 0x51
VK_R = 0x52
VK_ESCAPE = 0x1B
VK_F8 = 0x77
VK_F9 = 0x78

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MAPVK_VK_TO_VSC = 0
SRCCOPY = 0x00CC0020
BI_RGB = 0
DIB_RGB_COLORS = 0


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("union", INPUT_UNION)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", ctypes.c_ushort),
        ("biBitCount", ctypes.c_ushort),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32 * 3)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


@dataclass
class BarInfo:
    green_center: float
    yellow_x: float | None
    error: float | None
    green_found: bool = True
    yellow_found: bool = True


@dataclass
class BotConfig:
    reverse: bool = False
    f_interval: float = 0.5
    click_interval: float = 1.0
    deadzone_ratio: float = 0.006
    input_mode: str = "scancode"
    tap_duration: float = 0.08
    save_debug: bool = False
    debug_interval: float = 2.0
    capture_mode: str = "foreground-client"
    reel_control: str = "pulse"
    reel_pulse_interval: float = 0.09
    reel_pulse_duration: float = 0.055
    reel_pulse_min_interval: float = 0.001
    reel_pulse_max_interval: float = 0.07
    reel_pulse_min_duration: float = 0.025
    reel_pulse_max_duration: float = 0.5
    reel_pulse_full_error_ratio: float = 0.08


class Logger:
    def __init__(self, path: Path | None, verbose: bool = False):
        self.path = path
        self.verbose = verbose
        self.file = None
        if path is not None:
            self.file = path.open("a", encoding="utf-8")
            self.write("log opened")

    def write(self, message: str, force: bool = False):
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        line = f"{stamp} {message}"
        if self.verbose or force:
            print(line)
        if self.file is not None:
            self.file.write(line + "\n")
            self.file.flush()

    def close(self):
        if self.file is not None:
            self.write("log closed")
            self.file.close()
            self.file = None


class ScreenCapture:
    def __init__(self, mode: str, logger: Logger):
        self.mode = mode
        self.logger = logger
        USER32.SetProcessDPIAware()
        self.width = USER32.GetSystemMetrics(0)
        self.height = USER32.GetSystemMetrics(1)
        self.hwnd = USER32.GetDesktopWindow()
        self.srcdc = USER32.GetWindowDC(self.hwnd)
        self.memdc = GDI32.CreateCompatibleDC(self.srcdc)
        self.bmp = GDI32.CreateCompatibleBitmap(self.srcdc, self.width, self.height)
        GDI32.SelectObject(self.memdc, self.bmp)
        self.bmi = BITMAPINFO()
        self.bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        self.bmi.bmiHeader.biWidth = self.width
        self.bmi.bmiHeader.biHeight = -self.height
        self.bmi.bmiHeader.biPlanes = 1
        self.bmi.bmiHeader.biBitCount = 32
        self.bmi.bmiHeader.biCompression = BI_RGB
        self.buffer = ctypes.create_string_buffer(self.width * self.height * 4)
        self.logger.write(f"capture initialized mode={self.mode} desktop={self.width}x{self.height}", force=True)

    def grab_full(self):
        GDI32.BitBlt(self.memdc, 0, 0, self.width, self.height, self.srcdc, 0, 0, SRCCOPY)
        GDI32.GetDIBits(
            self.memdc,
            self.bmp,
            0,
            self.height,
            self.buffer,
            ctypes.byref(self.bmi),
            DIB_RGB_COLORS,
        )
        bgra = np.frombuffer(self.buffer, dtype=np.uint8).reshape((self.height, self.width, 4))
        return bgra[:, :, :3].copy()

    def grab(self):
        img = self.grab_full()
        if self.mode == "full":
            return img

        rect = foreground_capture_rect(client=self.mode == "foreground-client")
        if rect is None:
            return img

        left, top, right, bottom = rect
        left = max(0, min(self.width - 1, left))
        top = max(0, min(self.height - 1, top))
        right = max(left + 1, min(self.width, right))
        bottom = max(top + 1, min(self.height, bottom))
        return img[top:bottom, left:right].copy()

    def close(self):
        GDI32.DeleteObject(self.bmp)
        GDI32.DeleteDC(self.memdc)
        USER32.ReleaseDC(self.hwnd, self.srcdc)


class FishingBot:
    def __init__(self, root: Path, config: BotConfig, logger: Logger, debug: bool = False):
        self.root = root
        self.config = config
        self.logger = logger
        self.debug = debug
        self.last_f = 0.0
        self.last_click = 0.0
        self.active_key = None
        self.last_state = None
        self.last_debug_save = 0.0
        self.last_reel_input = 0.0
        self.fish_caught = 0
        self.last_counted_complete = 0.0
        self.complete_ref_size = None
        self.complete_template = self._load_complete_template()

    def _load_complete_template(self):
        ref = read_image(self.root / "4.png")
        if ref is None:
            return None
        h, w = ref.shape[:2]
        self.complete_ref_size = (w, h)
        # Bottom instruction text is stable and avoids matching ordinary gameplay.
        tpl = ref[int(h * 0.86) : int(h * 0.94), int(w * 0.38) : int(w * 0.62)]
        gray = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
        return cv2.Canny(gray, 50, 150)

    def is_complete(self, img):
        if self.complete_template is None or self.complete_ref_size is None:
            return False, 0.0
        h, w = img.shape[:2]
        roi = img[int(h * 0.82) : int(h * 0.97), int(w * 0.30) : int(w * 0.70)]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)

        ref_w, ref_h = self.complete_ref_size
        scale = min(w / ref_w, h / ref_h)
        template = self.complete_template
        if abs(scale - 1.0) > 0.03:
            tw = max(10, int(template.shape[1] * scale))
            th = max(10, int(template.shape[0] * scale))
            template = cv2.resize(template, (tw, th), interpolation=cv2.INTER_AREA)

        th, tw = template.shape[:2]
        if edges.shape[0] < th or edges.shape[1] < tw:
            return False, 0.0
        score = float(cv2.matchTemplate(edges, template, cv2.TM_CCOEFF_NORMED).max())
        return score >= 0.42, score

    def find_reel_bar(self, img):
        h, w = img.shape[:2]
        roi_y1, roi_y2 = int(h * 0.061), int(h * 0.081)
        roi_x1, roi_x2 = int(w * 0.314), int(w * 0.674)
        roi = img[roi_y1:roi_y2, roi_x1:roi_x2]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

        green = cv2.inRange(hsv, np.array([80, 150, 160]), np.array([88, 255, 255]))
        yellow = cv2.inRange(hsv, np.array([20, 60, 154]), np.array([40, 255, 255]))

        green_box = None
        _, _, stats, centroids = cv2.connectedComponentsWithStats(green)
        for i in range(1, len(stats)):
            x, y, bw, bh, area = stats[i]
            sx, sy = x + roi_x1, y + roi_y1
            aspect = bw / max(1, bh)
            if (
                bw >= max(60, w * 0.03)
                and bw <= max(260, w * 0.18)
                and 5 <= bh <= max(24, h * 0.025)
                and area >= 180
                and aspect >= 5.0
                and roi_y1 <= sy <= roi_y2
            ):
                score = area + aspect * 50
                if green_box is None or score > green_box[-1]:
                    green_box = (x, y, bw, bh, area, score)

        yellow_box = None
        _, _, stats, centroids = cv2.connectedComponentsWithStats(yellow)
        for i in range(1, len(stats)):
            x, y, bw, bh, area = stats[i]
            sy = y + roi_y1
            if (
                2 <= bw <= max(18, w * 0.012)
                and 8 <= bh <= max(58, h * 0.055)
                and area >= 18
                and roi_y1 <= sy <= roi_y2
            ):
                score = area + bh * 4 - bw * 3
                if yellow_box is None or score > yellow_box[-1]:
                    yellow_box = (x, y, bw, bh, area, score)

        if green_box is None or yellow_box is None:
            return None

        gx, _, gw, _, _, _ = green_box
        green_center = roi_x1 + gx + gw / 2
        yx, _, yw, _, _, _ = yellow_box
        yellow_x = roi_x1 + yx + yw / 2
        return BarInfo(green_center=float(green_center), yellow_x=float(yellow_x), error=float(yellow_x - green_center))

    def save_debug_frame(self, img, label):
        if not self.config.save_debug:
            return
        now = time.monotonic()
        if now - self.last_debug_save < self.config.debug_interval:
            return
        self.last_debug_save = now
        out_dir = self.root / "debug_frames"
        out_dir.mkdir(exist_ok=True)
        path = out_dir / f"{int(time.time())}_{label}.png"
        ok = cv2.imwrite(str(path), img)
        self.logger.write(f"[debug-frame] saved={ok} path={path}", force=True)

    def tap_key(self, vk):
        self.key_down(vk)
        time.sleep(self.config.tap_duration)
        self.key_up(vk)

    def key_down(self, vk):
        sent = self.send_key(vk, False)
        if self.debug:
            self.logger.write(f"[input] down {key_name(vk)} mode={self.config.input_mode} sent={sent}")
        return sent

    def key_up(self, vk):
        sent = self.send_key(vk, True)
        if self.debug:
            self.logger.write(f"[input] up {key_name(vk)} mode={self.config.input_mode} sent={sent}")
        return sent

    def send_key(self, vk, key_up):
        flags = KEYEVENTF_KEYUP if key_up else 0
        scan = 0
        send_vk = vk
        if self.config.input_mode == "scancode":
            scan = USER32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
            send_vk = 0
            flags |= KEYEVENTF_SCANCODE
        inp = INPUT(
            INPUT_KEYBOARD,
            INPUT_UNION(ki=KEYBDINPUT(send_vk, scan, flags, 0, 0)),
        )
        return USER32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

    def release_direction(self):
        if self.active_key is not None:
            self.key_up(self.active_key)
            self.active_key = None

    def hold_direction(self, vk):
        if self.active_key == vk:
            return
        self.release_direction()
        self.key_down(vk)
        self.active_key = vk

    def pulse_direction(self, vk, duration=None):
        self.release_direction()
        self.key_down(vk)
        time.sleep(self.config.reel_pulse_duration if duration is None else duration)
        self.key_up(vk)

    def proportional_pulse(self, vk, error, screen_width):
        full_error = max(1.0, screen_width * self.config.reel_pulse_full_error_ratio)
        strength = min(1.0, abs(error) / full_error)
        duration = lerp(self.config.reel_pulse_min_duration, self.config.reel_pulse_max_duration, strength)
        interval = lerp(self.config.reel_pulse_max_interval, self.config.reel_pulse_min_interval, strength)
        now = time.monotonic()
        if now - self.last_reel_input >= interval:
            self.pulse_direction(vk, duration=duration)
            self.last_reel_input = time.monotonic()
        return strength, duration, interval

    def click_left(self):
        down = INPUT(
            INPUT_MOUSE,
            INPUT_UNION(mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, 0)),
        )
        up = INPUT(
            INPUT_MOUSE,
            INPUT_UNION(mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, 0)),
        )
        USER32.SendInput(1, ctypes.byref(down), ctypes.sizeof(down))
        time.sleep(0.04)
        USER32.SendInput(1, ctypes.byref(up), ctypes.sizeof(up))

    def click_relative(self, x_ratio, y_ratio, label, client=True):
        rect = foreground_capture_rect(client=client)
        if rect is None:
            self.logger.write(f"[click] skipped label={label} reason=no-foreground-rect", force=True)
            return False
        left, top, right, bottom = rect
        x = int(left + (right - left) * x_ratio)
        y = int(top + (bottom - top) * y_ratio)
        USER32.SetCursorPos(x, y)
        time.sleep(0.05)
        self.click_left()
        self.logger.write(f"[click] {label} at=({x},{y}) ratio=({x_ratio:.3f},{y_ratio:.3f}) rect={rect}", force=True)
        return True

    def click_screen(self, x, y, label):
        USER32.SetCursorPos(int(x), int(y))
        time.sleep(0.05)
        self.click_left()
        self.logger.write(f"[click] {label} at=({int(x)},{int(y)})", force=True)
        return True

    def click_template(self, template_path, label, threshold=0.62):
        template = read_image(template_path)
        if template is None:
            self.logger.write(f"[template] missing label={label} path={template_path}", force=True)
            return False

        cap = ScreenCapture(mode="foreground-client", logger=self.logger)
        try:
            img = cap.grab()
        finally:
            cap.close()

        h, w = img.shape[:2]
        # Search the left shop item grid, not the item detail panel.
        search = img[int(h * 0.05) : int(h * 0.92), 0 : int(w * 0.42)]
        search_gray = cv2.cvtColor(search, cv2.COLOR_BGR2GRAY)
        template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)

        base_scale = w / 960.0
        scales = [base_scale * factor for factor in (0.82, 0.9, 1.0, 1.1, 1.18)]
        best = None
        for scale in scales:
            tw = max(12, int(template_gray.shape[1] * scale))
            th = max(12, int(template_gray.shape[0] * scale))
            if tw >= search_gray.shape[1] or th >= search_gray.shape[0]:
                continue
            tpl = cv2.resize(template_gray, (tw, th), interpolation=cv2.INTER_AREA)
            result = cv2.matchTemplate(search_gray, tpl, cv2.TM_CCOEFF_NORMED)
            _, score, _, loc = cv2.minMaxLoc(result)
            if best is None or score > best[0]:
                best = (score, loc, tw, th)

        if best is None:
            self.logger.write(f"[template] no candidate label={label}", force=True)
            return False

        score, loc, tw, th = best
        self.logger.write(f"[template] label={label} score={score:.3f} loc={loc} size=({tw},{th})", force=True)
        if score < threshold:
            return False

        rect = foreground_capture_rect(client=True)
        if rect is None:
            return False
        left, top, _, _ = rect
        x = left + loc[0] + tw / 2
        y = top + int(h * 0.05) + loc[1] + th / 2
        return self.click_screen(x, y, label)

    def step(self, img):
        now = time.monotonic()
        complete, complete_score = self.is_complete(img)
        if complete:
            self.release_direction()
            if now - self.last_click > self.config.click_interval:
                self.tap_key(VK_ESCAPE)
                self.last_click = now
                self.logger.write(f"[complete] close with ESC, score={complete_score:.2f}", force=True)
            if now - self.last_counted_complete > max(2.0, self.config.click_interval):
                self.fish_caught += 1
                self.last_counted_complete = now
                self.logger.write(f"[count] fish_caught={self.fish_caught}", force=True)
            self.log_state("complete")
            return "complete"

        bar = self.find_reel_bar(img)
        if bar is not None:
            deadzone = max(10, img.shape[1] * self.config.deadzone_ratio)
            # Fixed mapping confirmed in-game:
            # yellow left of green -> D, yellow right of green -> A.
            if bar.error < -deadzone:
                vk, action = (VK_A, "A") if self.config.reverse else (VK_D, "D")
            elif bar.error > deadzone:
                vk, action = (VK_D, "D") if self.config.reverse else (VK_A, "A")
            else:
                vk = None
                action = "-"

            if vk is None:
                self.release_direction()
            elif self.config.reel_control == "hold":
                self.hold_direction(vk)
                strength = 1.0
                pulse_duration = 0.0
                pulse_interval = 0.0
            else:
                strength, pulse_duration, pulse_interval = self.proportional_pulse(vk, bar.error, img.shape[1])

            if self.debug:
                self.logger.write(
                    f"[reel] green={bar.green_center:.0f} yellow={bar.yellow_x:.0f} "
                    f"error={bar.error:.0f} action={action} strength={strength:.2f} "
                    f"pulse_duration={pulse_duration:.3f} pulse_interval={pulse_interval:.3f}"
                )
            self.log_state("reel")
            return "reel"

        self.release_direction()
        if now - self.last_f >= self.config.f_interval:
            self.tap_key(VK_F)
            self.last_f = now
            self.logger.write(f"[wait] tap F foreground={foreground_window_title()}", force=self.debug)
            self.save_debug_frame(img, "wait")
        self.log_state("wait")
        return "wait"

    def log_state(self, state):
        if state != self.last_state:
            self.logger.write(f"[state] {self.last_state or 'none'} -> {state}", force=True)
            self.last_state = state


def hotkey_pressed(vk):
    return bool(USER32.GetAsyncKeyState(vk) & 1)


def lerp(a, b, t):
    return a + (b - a) * max(0.0, min(1.0, t))


def foreground_window_title():
    hwnd = USER32.GetForegroundWindow()
    if not hwnd:
        return "<none>"
    length = USER32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    USER32.GetWindowTextW(hwnd, buffer, length + 1)
    pid = ctypes.c_ulong()
    USER32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return f"hwnd=0x{hwnd:x} pid={pid.value} title={buffer.value!r}"


def foreground_capture_rect(client: bool):
    hwnd = USER32.GetForegroundWindow()
    if not hwnd:
        return None

    if client:
        rect = RECT()
        if not USER32.GetClientRect(hwnd, ctypes.byref(rect)):
            return None
        pt = POINT(0, 0)
        if not USER32.ClientToScreen(hwnd, ctypes.byref(pt)):
            return None
        return (pt.x, pt.y, pt.x + rect.right - rect.left, pt.y + rect.bottom - rect.top)

    rect = RECT()
    if not USER32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return (rect.left, rect.top, rect.right, rect.bottom)


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def key_name(vk):
    names = {
        VK_A: "A",
        VK_D: "D",
        VK_F: "F",
        VK_Q: "Q",
        VK_R: "R",
        VK_ESCAPE: "ESC",
        VK_F8: "F8",
        VK_F9: "F9",
    }
    return names.get(vk, f"VK_{vk:02x}")


def run_shop_cycle(bot: FishingBot, buy_count: int):
    bot.release_direction()
    bot.logger.write(f"[shop-test] start sell fish and buy bait count={buy_count}", force=True)

    # Sell fish: Q -> second left tab -> one-click sell -> confirm -> close result -> ESC.
    time.sleep(1.2)
    bot.tap_key(VK_Q)
    bot.logger.write("[shop-test] pressed Q for sell menu", force=True)
    time.sleep(1.4)
    bot.click_relative(0.077, 0.381, "sell second left tab")
    time.sleep(0.8)
    bot.click_relative(0.559, 0.896, "sell one-click sell")
    time.sleep(0.8)
    bot.click_relative(0.625, 0.656, "sell confirm")
    time.sleep(1.2)
    bot.click_relative(0.530, 0.891, "sell result close blank")
    time.sleep(0.6)
    bot.tap_key(VK_ESCAPE)
    bot.logger.write("[shop-test] pressed ESC after sell", force=True)
    time.sleep(1.2)

    # Buy bait: R -> top-left universal bait -> plus until requested count -> buy -> click again -> ESC.
    bot.tap_key(VK_R)
    bot.logger.write("[shop-test] pressed R for bait shop", force=True)
    time.sleep(1.4)
    template_path = bot.root / "templates" / "universal_bait.png"
    if not bot.click_template(template_path, "buy universal bait template"):
        bot.logger.write("[template] fallback to old universal bait coordinate", force=True)
        bot.click_relative(0.077, 0.233, "buy universal bait fallback")
    time.sleep(0.6)
    for i in range(max(0, buy_count - 1)):
        bot.click_relative(0.923, 0.881, f"buy plus {i + 1}/{max(0, buy_count - 1)}")
        time.sleep(0.08)
    bot.click_relative(0.839, 0.956, "buy button")
    time.sleep(0.45)
    bot.click_relative(0.604, 0.659, "buy confirm dialog")
    time.sleep(5.0)
    bot.tap_key(VK_ESCAPE)
    bot.logger.write("[shop-test] pressed ESC after buy #1", force=True)
    time.sleep(3.0)
    bot.tap_key(VK_ESCAPE)
    bot.logger.write("[shop-test] pressed ESC after buy #2", force=True)
    time.sleep(1.0)
    bot.last_f = time.monotonic()
    bot.logger.write("[shop-test] done", force=True)


def test_images(root: Path):
    logger = Logger(None, verbose=True)
    bot = FishingBot(root, BotConfig(), logger=logger, debug=True)
    for name in ("1.png", "2.png", "3.png", "4.png"):
        img = read_image(root / name)
        if img is None:
            print(f"{name}: missing")
            continue
        complete, score = bot.is_complete(img)
        bar = bot.find_reel_bar(img)
        print(f"{name}: complete={complete} score={score:.2f} bar={bar}")


def read_image(path: Path):
    if not path.exists():
        return None
    data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def main():
    parser = argparse.ArgumentParser(description="NTE fishing automation helper")
    parser.add_argument("--debug", action="store_true", help="print detection details")
    parser.add_argument("--test-images", action="store_true", help="test detection against 1.png-4.png")
    parser.add_argument("--reverse", action="store_true", help="swap A/D reel direction")
    parser.add_argument("--f-interval", type=float, default=0.5, help="seconds between F taps while waiting")
    parser.add_argument("--deadzone", type=float, default=0.006, help="reel deadzone as screen-width ratio")
    parser.add_argument("--click-interval", type=float, default=1.0, help="minimum seconds between completion clicks")
    parser.add_argument("--auto-start", action="store_true", help="start automatically after a short countdown")
    parser.add_argument("--start-delay", type=float, default=3.0, help="countdown seconds before auto-start")
    parser.add_argument("--input-mode", choices=("scancode", "vk"), default="scancode", help="keyboard injection mode")
    parser.add_argument("--tap-duration", type=float, default=0.08, help="seconds to hold tapped keys")
    parser.add_argument("--log-file", default="fish_bot.log", help="debug log path, or empty string to disable file logging")
    parser.add_argument("--test-key", choices=("A", "D", "F"), help="after countdown, press one key repeatedly for input testing")
    parser.add_argument("--save-debug", action="store_true", help="save periodic screenshots for detection debugging")
    parser.add_argument("--debug-interval", type=float, default=2.0, help="minimum seconds between saved debug screenshots")
    parser.add_argument(
        "--capture",
        choices=("foreground-client", "foreground-window", "full"),
        default="foreground-client",
        help="screen capture area",
    )
    parser.add_argument("--reel-control", choices=("pulse", "hold"), default="pulse", help="A/D control style while reeling")
    parser.add_argument("--reel-pulse-interval", type=float, default=0.09, help="seconds between A/D pulses")
    parser.add_argument("--reel-pulse-duration", type=float, default=0.08, help="seconds to hold each A/D pulse")
    parser.add_argument("--reel-pulse-min-interval", type=float, default=0.001, help="proportional pulse: fastest interval")
    parser.add_argument("--reel-pulse-max-interval", type=float, default=0.07, help="proportional pulse: slowest interval")
    parser.add_argument("--reel-pulse-min-duration", type=float, default=0.025, help="proportional pulse: shortest press")
    parser.add_argument("--reel-pulse-max-duration", type=float, default=0.5, help="proportional pulse: longest press")
    parser.add_argument("--reel-pulse-full-error", type=float, default=0.08, help="screen-width ratio treated as full correction")
    parser.add_argument("--shop-test", action="store_true", help="enable sell/buy cycle after a fixed catch count")
    parser.add_argument("--shop-every", type=int, default=50, help="shop cycle: run shop cycle after this many fish")
    parser.add_argument("--buy-bait-count", type=int, default=50, help="shop cycle: target bait purchase count")
    parser.add_argument("--initial-fish-before-shop", type=int, default=0, help="fish this many first before starting shop cycles")
    parser.add_argument("--test-shop-cycle", action="store_true", help="run one sell/buy shop cycle after countdown, then exit")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    if args.test_images:
        test_images(root)
        return

    log_path = root / args.log_file if args.log_file else None
    logger = Logger(log_path, verbose=args.debug)
    logger.write(
        "startup "
        f"pid={os.getpid()} admin={is_admin()} input_mode={args.input_mode} "
        f"tap_duration={args.tap_duration} shop_test={args.shop_test} "
        f"shop_every={args.shop_every} buy_bait_count={args.buy_bait_count} "
        f"initial_fish_before_shop={args.initial_fish_before_shop} "
        f"foreground={foreground_window_title()}",
        force=True,
    )

    config = BotConfig(
        reverse=args.reverse,
        f_interval=max(0.1, args.f_interval),
        click_interval=max(0.2, args.click_interval),
        deadzone_ratio=max(0.001, args.deadzone),
        input_mode=args.input_mode,
        tap_duration=max(0.02, args.tap_duration),
        save_debug=args.save_debug,
        debug_interval=max(0.5, args.debug_interval),
        capture_mode=args.capture,
        reel_control=args.reel_control,
        reel_pulse_interval=max(0.04, args.reel_pulse_interval),
        reel_pulse_duration=max(0.01, args.reel_pulse_duration),
        reel_pulse_min_interval=max(0.001, args.reel_pulse_min_interval),
        reel_pulse_max_interval=max(0.001, args.reel_pulse_max_interval),
        reel_pulse_min_duration=max(0.005, args.reel_pulse_min_duration),
        reel_pulse_max_duration=max(0.005, args.reel_pulse_max_duration),
        reel_pulse_full_error_ratio=max(0.005, args.reel_pulse_full_error),
    )
    bot = FishingBot(root, config=config, logger=logger, debug=args.debug)
    shop_every = max(1, args.shop_every)
    initial_fish_before_shop = max(0, args.initial_fish_before_shop)
    next_shop_at = initial_fish_before_shop + shop_every

    if args.test_shop_cycle:
        delay = max(0.0, args.start_delay)
        print(f"test-shop-cycle: starting in {delay:.1f}s. Focus the game window now. Ctrl+C to stop.")
        time.sleep(delay)
        try:
            run_shop_cycle(bot, buy_count=max(1, args.buy_bait_count))
        except KeyboardInterrupt:
            print("stopped by Ctrl+C")
        finally:
            bot.release_direction()
            logger.close()
        return

    if args.test_key:
        key_map = {"A": VK_A, "D": VK_D, "F": VK_F}
        delay = max(0.0, args.start_delay)
        print(f"test-key {args.test_key}: starting in {delay:.1f}s. Focus the game window now. Ctrl+C to stop.")
        time.sleep(delay)
        try:
            while True:
                bot.tap_key(key_map[args.test_key])
                logger.write(f"[test-key] tapped {args.test_key} foreground={foreground_window_title()}", force=True)
                time.sleep(1.0)
        except KeyboardInterrupt:
            print("stopped by Ctrl+C")
        finally:
            bot.release_direction()
            logger.close()
        return

    cap = ScreenCapture(mode=args.capture, logger=logger)
    enabled = args.auto_start
    if args.auto_start:
        delay = max(0.0, args.start_delay)
        print(f"auto-start in {delay:.1f}s. Focus the game window now. Press Ctrl+C to stop.")
        time.sleep(delay)
        print("state: running")
    else:
        print("F8 start/pause, F9 quit. Ctrl+C also stops the script.")
        print("Keep the game window focused and place the mouse over a blank clickable area.")
    try:
        while True:
            if hotkey_pressed(VK_F8):
                enabled = not enabled
                bot.release_direction()
                print("state: running" if enabled else "state: paused")
                logger.write("state: running" if enabled else "state: paused", force=True)
                time.sleep(0.25)
            if hotkey_pressed(VK_F9):
                print("quit")
                logger.write("quit by F9", force=True)
                break
            if enabled:
                bot.step(cap.grab())
                if args.shop_test:
                    if bot.fish_caught > 0 or initial_fish_before_shop:
                        bot.logger.write(
                            f"[shop-test] check fish_caught={bot.fish_caught} "
                            f"next_shop_at={next_shop_at} initial_skip={initial_fish_before_shop}",
                            force=args.debug,
                        )
                if args.shop_test and bot.fish_caught >= next_shop_at:
                    bot.logger.write(
                        f"[shop-test] trigger fish_caught={bot.fish_caught} next_shop_at={next_shop_at}",
                        force=True,
                    )
                    run_shop_cycle(bot, buy_count=max(1, args.buy_bait_count))
                    next_shop_at = bot.fish_caught + shop_every
                    bot.logger.write(f"[shop-test] next_shop_at={next_shop_at}", force=True)
                time.sleep(0.05)
            else:
                time.sleep(0.1)
    except KeyboardInterrupt:
        print("stopped by Ctrl+C")
    finally:
        bot.release_direction()
        cap.close()
        logger.close()


if __name__ == "__main__":
    main()
