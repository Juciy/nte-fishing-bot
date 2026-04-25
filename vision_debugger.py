import ctypes
import time
import tkinter as tk
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, ImageTk


USER32 = ctypes.windll.user32
GDI32 = ctypes.windll.gdi32

SRCCOPY = 0x00CC0020
BI_RGB = 0
DIB_RGB_COLORS = 0


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
class Detection:
    green_box: tuple[int, int, int, int] | None
    yellow_box: tuple[int, int, int, int] | None
    green_center: float | None
    yellow_center: float | None
    error: float | None
    action: str


class ScreenCapture:
    def __init__(self, target_hwnd=None):
        USER32.SetProcessDPIAware()
        self.target_hwnd = target_hwnd
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

    def grab_foreground_client(self):
        img = self.grab_full()
        rect = window_client_rect(self.target_hwnd) if self.target_hwnd else foreground_client_rect()
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


def foreground_client_rect():
    return window_client_rect(USER32.GetForegroundWindow())


def window_client_rect(hwnd):
    if not hwnd:
        return None
    rect = RECT()
    if not USER32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    pt = POINT(0, 0)
    if not USER32.ClientToScreen(hwnd, ctypes.byref(pt)):
        return None
    return (pt.x, pt.y, pt.x + rect.right - rect.left, pt.y + rect.bottom - rect.top)


PARAM_DEFAULTS = {
    "roi_y1": 61,
    "roi_y2": 81,
    "roi_x1": 314,
    "roi_x2": 674,
    "g_h_min": 80,
    "g_h_max": 88,
    "g_s_min": 150,
    "g_v_min": 160,
    "y_h_min": 20,
    "y_h_max": 40,
    "y_s_min": 60,
    "y_v_min": 154,
    "deadzone": 6,
}

PARAM_LIMITS = {
    "roi_y1": 300,
    "roi_y2": 400,
    "roi_x1": 500,
    "roi_x2": 1000,
    "g_h_min": 179,
    "g_h_max": 179,
    "g_s_min": 255,
    "g_v_min": 255,
    "y_h_min": 179,
    "y_h_max": 179,
    "y_s_min": 255,
    "y_v_min": 255,
    "deadzone": 30,
}


def best_box(mask, w, h, roi_x1, roi_y1, kind):
    _, _, stats, _centroids = cv2.connectedComponentsWithStats(mask)
    best = None
    for i in range(1, len(stats)):
        x, y, bw, bh, area = stats[i]
        sx, sy = x + roi_x1, y + roi_y1
        if kind == "green":
            aspect = bw / max(1, bh)
            ok = (
                bw >= max(60, w * 0.03)
                and bw <= max(260, w * 0.18)
                and 5 <= bh <= max(24, h * 0.025)
                and area >= 180
                and aspect >= 5.0
                and roi_y1 <= sy <= roi_y1 + mask.shape[0]
            )
            score = area + aspect * 50
        else:
            ok = (
                2 <= bw <= max(18, w * 0.012)
                and 8 <= bh <= max(58, h * 0.055)
                and area >= 18
                and roi_y1 <= sy <= roi_y1 + mask.shape[0]
            )
            score = area + bh * 4 - bw * 3
        if ok and (best is None or score > best[-1]):
            best = (x + roi_x1, y + roi_y1, bw, bh, score)
    if best is None:
        return None
    x, y, bw, bh, _score = best
    return (int(x), int(y), int(bw), int(bh))


def detect(img, params):
    h, w = img.shape[:2]
    roi_y1 = int(h * params["roi_y1"] / 1000)
    roi_y2 = int(h * params["roi_y2"] / 1000)
    roi_x1 = int(w * params["roi_x1"] / 1000)
    roi_x2 = int(w * params["roi_x2"] / 1000)
    roi_y2 = max(roi_y1 + 1, roi_y2)
    roi_x2 = max(roi_x1 + 1, roi_x2)

    roi = img[roi_y1:roi_y2, roi_x1:roi_x2]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(
        hsv,
        np.array([params["g_h_min"], params["g_s_min"], params["g_v_min"]]),
        np.array([params["g_h_max"], 255, 255]),
    )
    yellow = cv2.inRange(
        hsv,
        np.array([params["y_h_min"], params["y_s_min"], params["y_v_min"]]),
        np.array([params["y_h_max"], 255, 255]),
    )

    green_box = best_box(green, w, h, roi_x1, roi_y1, "green")
    yellow_box = best_box(yellow, w, h, roi_x1, roi_y1, "yellow")

    green_center = None
    yellow_center = None
    error = None
    action = "wait"
    if green_box is not None:
        gx, _gy, gw, _gh = green_box
        green_center = gx + gw / 2
    if yellow_box is not None:
        yx, _yy, yw, _yh = yellow_box
        yellow_center = yx + yw / 2
    if green_box is not None and yellow_box is not None:
        error = yellow_center - green_center
        deadzone = max(10, w * params["deadzone"] / 1000)
        if error < -deadzone:
            action = "D"
        elif error > deadzone:
            action = "A"
        else:
            action = "-"
    return Detection(green_box, yellow_box, green_center, yellow_center, error, action), green, yellow, (roi_x1, roi_y1, roi_x2, roi_y2)


def draw(img, detection, roi_rect):
    out = img.copy()
    x1, y1, x2, y2 = roi_rect
    cv2.rectangle(out, (x1, y1), (x2, y2), (180, 180, 180), 2)
    if detection.green_box is not None:
        x, y, w, h = detection.green_box
        cv2.rectangle(out, (x, y), (x + w, y + h), (0, 255, 0), 2)
        if detection.green_center is not None:
            cv2.line(out, (int(detection.green_center), y - 15), (int(detection.green_center), y + h + 15), (0, 255, 0), 2)
    if detection.yellow_box is not None:
        x, y, w, h = detection.yellow_box
        cv2.rectangle(out, (x, y), (x + w, y + h), (0, 255, 255), 2)
        if detection.yellow_center is not None:
            cv2.line(out, (int(detection.yellow_center), y - 15), (int(detection.yellow_center), y + h + 15), (0, 255, 255), 2)

    text = f"action={detection.action}"
    if detection.error is not None:
        text += f" error={detection.error:.1f} green={detection.green_center:.1f} yellow={detection.yellow_center:.1f}"
    else:
        text += f" green_found={detection.green_box is not None} yellow_found={detection.yellow_box is not None}"
    cv2.putText(out, text, (20, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.putText(out, text, (20, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
    return out


class DebuggerApp:
    def __init__(self, cap):
        self.cap = cap
        self.root = tk.Tk()
        self.root.title("NTE Vision Debugger")
        self.vars = {}
        self.last_detection = None

        self.vision_label = tk.Label(self.root)
        self.vision_label.grid(row=0, column=0, rowspan=2, sticky="nsew")

        side = tk.Frame(self.root)
        side.grid(row=0, column=1, sticky="nsew")
        self.green_label = tk.Label(side)
        self.green_label.pack()
        self.yellow_label = tk.Label(side)
        self.yellow_label.pack()

        controls = tk.Frame(self.root)
        controls.grid(row=1, column=1, sticky="nsew")
        for row, (name, value) in enumerate(PARAM_DEFAULTS.items()):
            var = tk.IntVar(value=value)
            self.vars[name] = var
            tk.Label(controls, text=name, width=10, anchor="w").grid(row=row, column=0, sticky="w")
            tk.Scale(
                controls,
                from_=0,
                to=PARAM_LIMITS[name],
                orient="horizontal",
                variable=var,
                length=250,
            ).grid(row=row, column=1, sticky="ew")

        self.status = tk.Label(self.root, text="", anchor="w", font=("Consolas", 10))
        self.status.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.root.bind("q", lambda _event: self.root.destroy())
        self.root.bind("s", self.print_params)
        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)
        self.root.after(20, self.update_frame)
        print("Focus the game window first. Press s to print params, q to quit.")

    def params(self):
        return {name: var.get() for name, var in self.vars.items()}

    def print_params(self, _event=None):
        print(time.strftime("%H:%M:%S"), self.params(), self.last_detection)

    def update_frame(self):
        try:
            img = self.cap.grab_foreground_client()
            params = self.params()
            detection, green_mask, yellow_mask, roi_rect = detect(img, params)
            self.last_detection = detection
            view = draw(img, detection, roi_rect)
            self.set_image(self.vision_label, view, 1280, bgr=True)
            self.set_image(self.green_label, green_mask, 420, bgr=False)
            self.set_image(self.yellow_label, yellow_mask, 420, bgr=False)
            self.status.config(text=self.status_text(detection))
        except Exception as exc:
            self.status.config(text=f"error: {exc}")
        if self.root.winfo_exists():
            self.root.after(20, self.update_frame)

    def status_text(self, detection):
        if detection.error is None:
            return f"action={detection.action} green_found={detection.green_box is not None} yellow_found={detection.yellow_box is not None}"
        return f"action={detection.action} error={detection.error:.1f} green={detection.green_center:.1f} yellow={detection.yellow_center:.1f}"

    def set_image(self, label, img, max_width, bgr):
        display = resize_for_display(img, max_width)
        if len(display.shape) == 2:
            pil = Image.fromarray(display)
        elif bgr:
            pil = Image.fromarray(cv2.cvtColor(display, cv2.COLOR_BGR2RGB))
        else:
            pil = Image.fromarray(display)
        photo = ImageTk.PhotoImage(pil)
        label.configure(image=photo)
        label.image = photo

    def run(self):
        self.root.mainloop()


def main():
    print("Focus the game window within 3 seconds. The debugger will lock onto that window.")
    time.sleep(3.0)
    target_hwnd = USER32.GetForegroundWindow()
    print(f"locked target hwnd=0x{target_hwnd:x}")
    cap = ScreenCapture(target_hwnd=target_hwnd)
    app = DebuggerApp(cap)
    try:
        app.run()
    finally:
        cap.close()


def resize_for_display(img, max_width):
    h, w = img.shape[:2]
    if w <= max_width:
        return img
    scale = max_width / w
    return cv2.resize(img, (max_width, int(h * scale)), interpolation=cv2.INTER_AREA)


if __name__ == "__main__":
    main()
