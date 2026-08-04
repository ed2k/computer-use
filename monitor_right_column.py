#!/usr/bin/env python3
"""
Right 1/4 Screen & Specific Window Monitor
===========================================
A Python program that continuously monitors the computer screen or a specific target window
(or right 1/4 column of a window/screen) and automatically saves images when changes are detected.

Requirements:
    Pillow (PIL) -> pre-installed or install via `pip install Pillow`

Usage Examples:
    # 1. Monitor right 1/4 of full screen (Default)
    python monitor_right_column.py

    # 2. List running applications to find window targets
    python monitor_right_column.py --list-apps

    # 3. Monitor right 1/4 column of a specific application window (e.g., Chrome, Terminal, Code)
    python monitor_right_column.py --window-app "Google Chrome"

    # 4. Monitor full specific window instead of just the right 1/4
    python monitor_right_column.py --window-app "Terminal" --window-region full

    # 5. Monitor a custom window bounding box (X Y Width Height)
    python monitor_right_column.py --window-bbox 500 100 1200 800

    # 6. Save visual diff images and metadata log
    python monitor_right_column.py --window-app "Chrome" --save-diff --log-json
"""

import os
import sys
import time
import json
import subprocess
import argparse
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageGrab, ImageChops, ImageStat, ImageDraw


def parse_args():
    parser = argparse.ArgumentParser(
        description="Monitor the right 1/4 column of screen or a specific application window for changes."
    )
    
    # Window / Target selection arguments
    target_group = parser.add_argument_group("Target & Region Options")
    target_group.add_argument(
        "-w", "--window-app",
        type=str,
        default=None,
        help="Target application name to monitor (e.g., 'Google Chrome', 'Terminal', 'Notes', 'Finder')"
    )
    target_group.add_argument(
        "--window-title",
        type=str,
        default=None,
        help="Target window title keyword to match"
    )
    target_group.add_argument(
        "--window-bbox",
        type=int,
        nargs=4,
        metavar=("X", "Y", "WIDTH", "HEIGHT"),
        default=None,
        help="Explicit window bounding box coordinates: X Y WIDTH HEIGHT (e.g., 500 100 1200 800)"
    )
    target_group.add_argument(
        "-f", "--fraction",
        type=float,
        default=0.25,
        help="Fraction of width from right edge to monitor (default: 0.25 for right 1/4)"
    )
    target_group.add_argument(
        "-r", "--window-region",
        type=str,
        choices=["right-quarter", "right-half", "left-half", "full"],
        default=None,
        help="Region of the target window to monitor (default: right-quarter for full screen, full for a specific window)"
    )
    target_group.add_argument(
        "--list-apps",
        action="store_true",
        help="List currently running open applications and exit"
    )

    # Sampling & Detection settings
    detect_group = parser.add_argument_group("Detection & Output Options")
    detect_group.add_argument(
        "-i", "--interval",
        type=float,
        default=0.5,
        help="Polling interval in seconds (default: 0.5)"
    )
    detect_group.add_argument(
        "-t", "--threshold",
        type=float,
        default=0.2,
        help="Percentage change threshold to trigger saving (0.0 to 100.0, default: 0.2)"
    )
    detect_group.add_argument(
        "-o", "--output-dir",
        type=str,
        default="captures",
        help="Directory to save captured images (default: captures)"
    )
    detect_group.add_argument(
        "--save-diff",
        action="store_true",
        help="Save a visual diff image highlighting changed areas for each event"
    )
    detect_group.add_argument(
        "--save-full-screen",
        action="store_true",
        help="Save full screen screenshot instead of cropped region when a change is detected"
    )
    detect_group.add_argument(
        "--min-save-interval",
        type=float,
        default=0.5,
        help="Minimum seconds between consecutive saves to avoid rapid spam (default: 0.5)"
    )
    detect_group.add_argument(
        "--max-captures",
        type=int,
        default=0,
        help="Maximum number of captures to save before stopping (0 = unlimited, default: 0)"
    )
    detect_group.add_argument(
        "--log-json",
        action="store_true",
        help="Maintain a captures_log.json metadata file in the output directory"
    )

    return parser.parse_args()


def get_running_applications_macos():
    """
    Returns a list of running GUI process names on macOS using osascript.
    """
    cmd = ['osascript', '-e', 'tell application "System Events" to get name of every process whose background only is false']
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if res.returncode == 0 and res.stdout.strip():
            apps = [a.strip() for a in res.stdout.strip().split(',') if a.strip()]
            return sorted(list(set(apps)))
    except Exception:
        pass
    return []


def get_window_bounds_macos(app_name: str, title_keyword: str = None):
    """
    Queries macOS System Events via AppleScript to find position and size of target window.
    Direct process lookup is performed first to bypass process iteration permission checks.
    """
    # 1. Direct process lookup (fast & avoids process iteration permission errors)
    direct_script = f'''
    tell application "System Events"
        try
            tell process "{app_name}"
                set wList to windows
                if (count of wList) > 0 then
                    set w to item 1 of wList
                    set wPos to position of w
                    set wSize to size of w
                    return (item 1 of wPos) & "," & (item 2 of wPos) & "," & (item 1 of wSize) & "," & (item 2 of wSize)
                end if
            end tell
        end try
    end tell
    return ""
    '''
    try:
        res = subprocess.run(['osascript', '-e', direct_script], capture_output=True, text=True, timeout=5)
        out = res.stdout.strip()
        if out:
            parts = [int(p.strip()) for p in out.replace(' ', '').split(',') if p.strip().isdigit()]
            if len(parts) == 4 and parts[2] > 0 and parts[3] > 0:
                return tuple(parts)
    except Exception:
        pass

    # 2. Case-insensitive search over processes.
    # AppleScript's `contains` is already case-insensitive, so we do not use
    # `as lowercase` (which is a syntax error under /usr/bin/osascript) or the
    # legacy `creating process`/`background only` heuristics. Iterate all
    # processes, collect name matches, then return the first window with a
    # usable size. Prefer an exact (case-insensitive) name match when possible.
    search_script = f'''
    tell application "System Events"
        set matches to {{}}
        repeat with proc in (processes)
            try
                if (name of proc) contains "{app_name}" then
                    set end of matches to proc
                end if
            end try
        end repeat
        repeat with proc in matches
            try
                if (name of proc) as string = "{app_name}" then
                    repeat with w in (windows of proc)
                        try
                            set wPos to position of w
                            set wSize to size of w
                            if (item 1 of wSize) > 0 and (item 2 of wSize) > 0 then
                                return (item 1 of wPos) & "," & (item 2 of wPos) & "," & (item 1 of wSize) & "," & (item 2 of wSize)
                            end if
                        end try
                    end repeat
                end if
            end try
        end repeat
        repeat with proc in matches
            try
                repeat with w in (windows of proc)
                    try
                        set wPos to position of w
                        set wSize to size of w
                        if (item 1 of wSize) > 0 and (item 2 of wSize) > 0 then
                            return (item 1 of wPos) & "," & (item 2 of wPos) & "," & (item 1 of wSize) & "," & (item 2 of wSize)
                        end if
                    end try
                end repeat
            end try
        end repeat
    end tell
    return ""
    '''
    try:
        res = subprocess.run(['osascript', '-e', search_script], capture_output=True, text=True, timeout=15)
        out = res.stdout.strip()
        if out:
            parts = [int(p.strip()) for p in out.replace(' ', '').split(',') if p.strip().isdigit()]
            if len(parts) == 4 and parts[2] > 0 and parts[3] > 0:
                return tuple(parts)
    except Exception:
        pass

    return None


def get_screen_logical_size():
    """
    Returns the logical (point) resolution of the main display, e.g. (1680, 1050),
    by asking Finder for the desktop window bounds. Returns None if unavailable.
    """
    script = 'tell application "Finder" to get bounds of window of desktop'
    try:
        res = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=5)
        parts = [int(p.strip()) for p in res.stdout.replace(' ', '').split(',') if p.strip().isdigit()]
        if len(parts) == 4 and parts[2] > 0 and parts[3] > 0:
            return (parts[2], parts[3])
    except Exception:
        pass
    return None


def estimate_scale_factor(pixel_w: int, pixel_h: int, logical=None) -> float:
    """
    Compute the display scale factor as pixel resolution / logical resolution.

    macOS System Events reports window position/size in logical points, while
    ImageGrab.grab() returns physical pixels. Using the display ratio (instead
    of guessing from the window's own bounds) avoids geometric mis-translation
    for windows that are large or positioned past the screen midline.
    """
    if logical is None:
        logical = get_screen_logical_size()
    if logical and logical[0] > 0 and logical[1] > 0:
        sx = pixel_w / logical[0]
        sy = pixel_h / logical[1]
        s = (sx + sy) / 2.0
        for cand in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0):
            if abs(s - cand) < 0.01:
                return cand
        return s
    return 1.0


def calculate_image_diff(img1: Image.Image, img2: Image.Image) -> float:
    """
    Computes the root mean square (RMS) difference percentage between two images.
    Returns value between 0.0 (identical) and 100.0 (completely different).
    """
    if img1.size != img2.size or img1.mode != img2.mode:
        img2 = img2.convert(img1.mode).resize(img1.size)

    diff = ImageChops.difference(img1, img2)
    stat = ImageStat.Stat(diff)
    
    rms_sum = sum(stat.rms)
    max_possible = len(stat.rms) * 255.0
    return (rms_sum / max_possible) * 100.0


def create_visual_diff(img1: Image.Image, img2: Image.Image) -> Image.Image:
    """
    Creates a side-by-side comparison highlighting changes between img1 and img2.
    """
    diff = ImageChops.difference(img1.convert("RGB"), img2.convert("RGB"))
    enhanced_diff = diff.point(lambda p: min(255, p * 5))
    
    w, h = img2.size
    combined = Image.new("RGB", (w * 2, h))
    combined.paste(img2, (0, 0))
    combined.paste(enhanced_diff, (w, 0))
    
    draw = ImageDraw.Draw(combined)
    draw.text((10, 10), "Current Capture", fill=(255, 255, 255))
    draw.text((w + 10, 10), "Difference Highlight", fill=(255, 0, 0))
    
    return combined


def compute_target_bbox(screen_w: int, screen_h: int, scale_factor: float,
                        win_bounds=None, fraction=0.25, region="right-quarter"):
    """
    Computes screen pixel bounding box tuple (left, top, right, bottom)
    scaled to match screen Retina / display grab pixel coordinates.
    """
    if win_bounds:
        wx, wy, ww, wh = win_bounds
        # Scale to pixel coordinates if screen resolution is Retina (e.g. 2x)
        wx_px = int(wx * scale_factor)
        wy_px = int(wy * scale_factor)
        ww_px = int(ww * scale_factor)
        wh_px = int(wh * scale_factor)

        if region == "full":
            left = wx_px
            top = wy_px
            right = wx_px + ww_px
            bottom = wy_px + wh_px
        elif region == "right-half":
            col_w = int(ww_px * 0.5)
            left = wx_px + ww_px - col_w
            top = wy_px
            right = wx_px + ww_px
            bottom = wy_px + wh_px
        elif region == "left-half":
            col_w = int(ww_px * 0.5)
            left = wx_px
            top = wy_px
            right = wx_px + col_w
            bottom = wy_px + wh_px
        else: # "right-quarter" or custom fraction
            col_w = int(ww_px * fraction)
            left = wx_px + ww_px - col_w
            top = wy_px
            right = wx_px + ww_px
            bottom = wy_px + wh_px
    else:
        # Full Screen Right Column
        col_w = int(screen_w * fraction)
        left = screen_w - col_w
        top = 0
        right = screen_w
        bottom = screen_h

    # Clamp coordinates to valid screen bounds
    left = max(0, min(left, screen_w - 1))
    top = max(0, min(top, screen_h - 1))
    right = max(left + 1, min(right, screen_w))
    bottom = max(top + 1, min(bottom, screen_h))

    return (left, top, right, bottom)


def main():
    args = parse_args()

    # If --list-apps requested, display running apps and exit
    if args.list_apps:
        print("=" * 60)
        print(" 📱 RUNNING OPEN APPLICATIONS")
        print("=" * 60)
        apps = get_running_applications_macos()
        if apps:
            for idx, app in enumerate(apps, 1):
                print(f"  {idx:2d}. {app}")
            print("\nUsage example:")
            print(f"  python monitor_right_column.py --window-app \"{apps[0]}\"")
        else:
            print("  No open GUI applications detected or access restricted.")
        print("=" * 60)
        sys.exit(0)

    output_path = Path(args.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print("=" * 65)
    print(" 🖥️   SCREEN & WINDOW MONITOR")
    print("=" * 65)

    # Initial screen grab for dimensions & scale factor calculation
    try:
        initial_grab = ImageGrab.grab()
    except Exception as e:
        print(f"❌ Error grabbing screen: {e}")
        print("Note: On macOS, ensure Python/Terminal has Screen Recording permissions.")
        sys.exit(1)

    screen_w, screen_h = initial_grab.size

    # Scale factor derived from display pixel/logical ratio (Retina = 2.0).
    # System Events coordinates are in logical points; ImageGrab returns pixels.
    logical_size = get_screen_logical_size()
    scale_factor = estimate_scale_factor(screen_w, screen_h, logical_size)
    win_bounds = None
    win_description = "Full Screen (Right Column)"

    if args.window_bbox:
        win_bounds = tuple(args.window_bbox)
        scale_factor = 1.0  # explicit bbox uses pixel coordinates directly
        win_description = f"Custom Window BBox {win_bounds}"
    elif args.window_app or args.window_title:
        target_name = args.window_app or args.window_title
        print(f"🔍 Searching for window matching '{target_name}'...")
        bounds = get_window_bounds_macos(target_name, args.window_title)
        if bounds:
            win_bounds = bounds
            win_description = f"Window '{target_name}' {bounds}"
            print(f"  ✅ Window found: Pos=({bounds[0]}, {bounds[1]}), Size=({bounds[2]}x{bounds[3]})")
            print(f"  📐 Display scale factor: {scale_factor:.2f}x "
                  f"(pixel {screen_w}x{screen_h} / logical {logical_size[0]}x{logical_size[1]})"
                  if logical_size else f"  📐 Display scale factor: {scale_factor:.2f}x")
        else:
            print(f"  ⚠️ Could not automatically fetch bounds for '{target_name}'.")
            print("  Tip: Use --window-bbox X Y W H to specify window position explicitly.")
            print("  Defaulting to screen-based right column monitoring...\n")

    # Determine the effective region: right-quarter only applies to the
    # full-screen mode; a specific window/bbox defaults to the full window.
    # An explicit --window-region always wins.
    if args.window_region is not None:
        region = args.window_region
    elif win_bounds is None:
        region = "right-quarter"
    else:
        region = "full"

    bbox = compute_target_bbox(
        screen_w, screen_h,
        scale_factor=scale_factor,
        win_bounds=win_bounds,
        fraction=args.fraction,
        region=region
    )

    monitored_w = bbox[2] - bbox[0]
    monitored_h = bbox[3] - bbox[1]

    print(f" Target Target     : {win_description}")
    print(f" Monitored Region  : {region} (x: {bbox[0]}->{bbox[2]}, y: {bbox[1]}->{bbox[3]})")
    print(f" Region Dimensions : {monitored_w} x {monitored_h} pixels")
    print(f" Output Directory  : {output_path.resolve()}")
    print(f" Sensitivity       : Threshold >= {args.threshold}% change")
    print(f" Polling Interval  : {args.interval}s")
    print("=" * 65)
    print("Press Ctrl+C to stop monitoring.\n")

    previous_crop = None
    capture_count = 0
    scan_count = 0
    last_save_time = 0.0
    start_time = time.time()
    log_entries = []

    try:
        while True:
            scan_count += 1
            now = time.time()
            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            readable_time = datetime.now().strftime("%H:%M:%S.%f")[:-3]

            full_screen = ImageGrab.grab()
            target_crop = full_screen.crop(bbox)

            if previous_crop is None:
                previous_crop = target_crop
                save_img = full_screen if args.save_full_screen else target_crop
                filename = f"capture_baseline_{timestamp_str}.png"
                filepath = output_path / filename
                save_img.save(filepath)
                capture_count += 1

                print(f"[{readable_time}] 🚀 Initialized monitor. Saved baseline: {filename}")

                if args.log_json:
                    log_entries.append({
                        "id": capture_count,
                        "timestamp": timestamp_str,
                        "readable_time": readable_time,
                        "diff_percent": 0.0,
                        "filename": filename,
                        "type": "baseline"
                    })

                time.sleep(args.interval)
                continue

            diff_pct = calculate_image_diff(previous_crop, target_crop)

            if diff_pct >= args.threshold:
                time_since_last = now - last_save_time
                if time_since_last >= args.min_save_interval:
                    capture_count += 1
                    last_save_time = now

                    filename = f"capture_{timestamp_str}.png"
                    filepath = output_path / filename
                    save_img = full_screen if args.save_full_screen else target_crop
                    save_img.save(filepath)

                    diff_msg = f"Save #{capture_count}: {filename} (Diff: {diff_pct:.2f}%)"

                    if args.save_diff:
                        diff_filename = f"diff_{timestamp_str}.png"
                        diff_path = output_path / diff_filename
                        v_diff = create_visual_diff(previous_crop, target_crop)
                        v_diff.save(diff_path)
                        diff_msg += f" + {diff_filename}"

                    print(f"[{readable_time}] 📸 CHANGE DETECTED! {diff_msg}")

                    if args.log_json:
                        log_entries.append({
                            "id": capture_count,
                            "timestamp": timestamp_str,
                            "readable_time": readable_time,
                            "diff_percent": round(diff_pct, 4),
                            "filename": filename,
                            "type": "change"
                        })

                    previous_crop = target_crop

                    if args.max_captures > 0 and capture_count >= args.max_captures:
                        print(f"\nReached maximum capture limit ({args.max_captures}). Stopping.")
                        break
                else:
                    print(f"[{readable_time}] ⏳ Change detected ({diff_pct:.2f}%), throttled by min-save-interval.")
            else:
                sys.stdout.write(f"\r[{readable_time}] Monitoring... (Last diff: {diff_pct:.3f}%)")
                sys.stdout.flush()

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\n\nStopping monitor...")

    finally:
        total_time = time.time() - start_time
        print("\n" + "=" * 65)
        print(" 📊 MONITORING SUMMARY")
        print("=" * 65)
        print(f" Total Runtime    : {total_time:.1f} seconds")
        print(f" Total Scans      : {scan_count}")
        print(f" Captures Saved   : {capture_count}")
        print(f" Saved Location   : {output_path.resolve()}")

        if args.log_json and log_entries:
            log_file = output_path / "captures_log.json"
            with open(log_file, "w") as f:
                json.dump(log_entries, f, indent=2)
            print(f" Log File Saved   : {log_file}")
        print("=" * 65)


if __name__ == "__main__":
    main()
