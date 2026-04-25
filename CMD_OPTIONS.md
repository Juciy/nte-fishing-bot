# CMD / PowerShell 啟動參數

本文件說明 `fish_bot.py` 的常用命令列啟動方式。請在專案資料夾中執行，並建議用系統管理員權限開啟 CMD 或 PowerShell。

## 基本啟動

```powershell
python fish_bot.py --auto-start
```

預設會倒數 3 秒後開始。倒數期間請切回遊戲視窗。

```powershell
python fish_bot.py --auto-start --start-delay 5
```

將啟動倒數改為 5 秒。

## 正式買賣循環

```powershell
python fish_bot.py --auto-start --shop-test --shop-every 50 --buy-bait-count 50
```

每釣 50 隻魚後，賣出全部魚並買入 50 個魚餌，再繼續循環。

如果身上已經有很多魚餌，可以先釣指定數量後再開始買賣循環：

```powershell
python fish_bot.py --auto-start --shop-test --initial-fish-before-shop 200
```

## 測試買賣流程

```powershell
python fish_bot.py --test-shop-cycle --start-delay 5 --buy-bait-count 50 --debug
```

只跑一次賣魚與買餌流程，不等待釣魚數量。

## Debug 與除錯

```powershell
python fish_bot.py --auto-start --debug
```

輸出較詳細的狀態，並寫入 `fish_bot.log`。

```powershell
python fish_bot.py --auto-start --debug --save-debug
```

額外保存除錯截圖到 `debug_frames`。

```powershell
python fish_bot.py --test-key F --start-delay 5
```

測試遊戲是否能收到程式送出的 `F`。

```powershell
python fish_bot.py --test-images
```

用參考圖片測試辨識邏輯。

## 追蹤速度參數

目前預設使用比例脈衝控制：

```powershell
python fish_bot.py --auto-start --reel-control pulse
```

常用調整：

```powershell
python fish_bot.py --auto-start --reel-pulse-min-duration 0.025 --reel-pulse-max-duration 0.5 --reel-pulse-min-interval 0.001 --reel-pulse-max-interval 0.07 --reel-pulse-full-error 0.08
```

參數含義：

- `--reel-pulse-min-duration`：誤差很小時，每次 A/D 的最短按壓時間。
- `--reel-pulse-max-duration`：誤差很大時，每次 A/D 的最長按壓時間。
- `--reel-pulse-min-interval`：誤差很大時，兩次按鍵之間的最短間隔。
- `--reel-pulse-max-interval`：誤差很小時，兩次按鍵之間的最長間隔。
- `--reel-pulse-full-error`：誤差達到此比例時視為需要最大修正。

## 其他參數

- `--capture foreground-client`：只截取前景視窗的遊戲內容，預設值。
- `--capture foreground-window`：截取整個前景視窗。
- `--capture full`：截取全螢幕。
- `--input-mode scancode`：使用掃描碼送出按鍵，預設值，通常較適合遊戲。
- `--input-mode vk`：使用 Windows virtual-key 輸入。
- `--f-interval 0.5`：等待上鉤時按 `F` 的間隔。
- `--deadzone 0.006`：黃條接近綠條中心時不修正的範圍。
- `--reverse`：反轉 A/D 方向，正常使用不建議開啟。
- `--log-file fish_bot.log`：指定 log 檔案；空字串可關閉檔案 log。

## 操作要求

- 遊戲請設為 `1920x1080` 視窗模式。
- 建議關閉 HDR。
- 本程式請用系統管理員權限執行。
- 執行時需保持遊戲在前景。
