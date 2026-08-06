#!/usr/bin/env python3
"""
process_red_dots.py

Automated workflow script:
1. Locates the first small solid red notification dot in a target application window (e.g. WeChat).
2. Clicks on the red dot to open the conversation / detail view.
3. Captures screenshot of the opened content and saves it to captures/.
4. Locates the first left angle bracket ('<') back chevron and clicks it to return to the list.
5. Repeats the process until no more red dots remain, then exits.

Usage:
    python3 process_red_dots.py --window-app "WeChat"
    python3 process_red_dots.py --dry-run
"""

import sys
import time
import argparse
import platform
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageGrab

try:
    import Quartz
except ImportError:
    Quartz = None

from monitor_right_column import (
    locate_red_dots_in_window,
    locate_left_bracket_in_window,
    locate_three_dots_red_circle_in_window,
    is_macos_window_close_button
)


def click_screen_point(x: int, y: int, delay: float = 0.5):
    """
    Simulates a hardware left mouse click at absolute screen coordinates (x, y).
    Uses native macOS Quartz CGEvent on macOS, or pyautogui if available.
    """
    print(f"🖱️  Clicking screen point: ({x}, {y})...", flush=True)
    if platform.system() == "Darwin" and Quartz:
        try:
            point = Quartz.CGPoint(x, y)
            event_down = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventLeftMouseDown, point, Quartz.kCGMouseButtonLeft)
            event_up = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventLeftMouseUp, point, Quartz.kCGMouseButtonLeft)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, event_down)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, event_up)
            time.sleep(delay)
            return True
        except Exception as e:
            print(f"⚠️ Quartz click error: {e}", file=sys.stderr, flush=True)

    try:
        import pyautogui
        pyautogui.click(x, y)
        time.sleep(delay)
        return True
    except Exception as e:
        print(f"⚠️ PyAutoGUI click error: {e}", file=sys.stderr, flush=True)

    return False


def capture_app_window(app_name: str = "WeChat") -> Image.Image:
    """
    Captures a fresh screenshot of the target application window.
    """
    if platform.system() == "Darwin" and Quartz:
        try:
            options = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
            w_list = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID)
            for w in w_list:
                owner = w.get("kCGWindowOwnerName", "")
                if app_name.lower() in owner.lower() and w.get("kCGWindowLayer", 0) <= 5:
                    b = w.get("kCGWindowBounds", {})
                    wx, wy, ww, wh = int(b.get("X", 0)), int(b.get("Y", 0)), int(b.get("Width", 0)), int(b.get("Height", 0))
                    if ww > 100 and wh > 100:
                        return ImageGrab.grab(bbox=(wx, wy, wx + ww, wy + wh))
        except Exception as e:
            print(f"⚠️ App window grab error: {e}", file=sys.stderr, flush=True)

    try:
        return ImageGrab.grab()
    except Exception:
        return Image.new("RGB", (800, 600), (240, 240, 240))


def run_red_dot_processing_loop(
    app_name: str = "WeChat",
    output_dir: str = "captures",
    delay: float = 1.0,
    max_iterations: int = 20,
    dry_run: bool = False,
    include_three_dots: bool = False
):
    """
    Main execution loop to iteratively process red notification dots in a target app window.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 85)
    print(f"🚀 AUTOMATED RED DOT PROCESSING LOOP FOR '{app_name}'")
    print(f"   Settings: delay={delay}s, max_iterations={max_iterations}, dry_run={dry_run}")
    print("=" * 85)

    iteration = 1
    processed_count = 0

    while iteration <= max_iterations:
        print(f"\n--- Iteration #{iteration} ---", flush=True)

        # 1. Locate red notification dots
        img_red, dots = locate_red_dots_in_window(app_name=app_name)

        if not dots and include_three_dots:
            print("🔍 No small red dots found. Checking for three-dots red circles...", flush=True)
            _, badges = locate_three_dots_red_circle_in_window(app_name=app_name)
            if badges:
                dots = badges

        if not dots:
            print("✅ NO MORE RED DOTS FOUND! All notifications cleared. Quitting loop.", flush=True)
            break

        # Filter out candidate dots that are actually macOS window close buttons (black 'x' appears on hover)
        valid_dot = None
        for candidate in dots:
            lc = candidate["local_center"]
            sc = candidate["screen_center"]

            is_close, reason = is_macos_window_close_button(local_x=lc[0], local_y=lc[1], screen_x=sc[0], screen_y=sc[1], hover_delay=0.15)
            if is_close:
                print(f"🛑 SKIPPING candidate dot at Local ({lc[0]},{lc[1]}): {reason}", flush=True)
                continue

            valid_dot = candidate
            break

        if not valid_dot:
            print("✅ NO AUTHENTIC NOTIFICATION RED DOTS REMAIN (all candidates were window close buttons). Quitting loop.", flush=True)
            break

        first_dot = valid_dot
        lc = first_dot["local_center"]
        sc = first_dot["screen_center"]
        dot_radius = first_dot.get("radius", 0)

        print(f"📍 Selected Authentic Red Dot #{first_dot.get('dot_id', 1)}: Local=({lc[0]}, {lc[1]}), Screen=({sc[0]}, {sc[1]}), Radius={dot_radius}px", flush=True)

        if dry_run:
            print(f"🧪 [DRY RUN] Would click Red Dot at Screen ({sc[0]}, {sc[1]}), capture app window content, and click Back Chevron.", flush=True)
            processed_count += 1
            break

        # 2. Click the first red dot
        click_success = click_screen_point(sc[0], sc[1], delay=delay)
        if not click_success:
            print("❌ Mouse click failed. Aborting loop.", file=sys.stderr, flush=True)
            break

        # 3. Capture fresh screenshot of the opened app window content
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
        app_tag = app_name.replace(" ", "_")
        capture_path = out_dir / f"red_dot_content_{app_tag}_{iteration:02d}_{ts}.png"

        try:
            content_img = capture_app_window(app_name=app_name)
            content_img.save(capture_path)
            print(f"📸 Captured Content Screenshot of '{app_name}': {capture_path.resolve()}", flush=True)
        except Exception as e:
            print(f"⚠️ Failed to save screenshot: {e}", file=sys.stderr, flush=True)

        # 4. Locate first left angle bracket ('<') to navigate back
        print("🔍 Searching for Left Angle Bracket ('<') back chevron...", flush=True)
        time.sleep(0.3)
        img_bracket, brackets = locate_left_bracket_in_window(app_name=app_name)

        if brackets:
            first_bracket = brackets[0]
            blc = first_bracket["local_center"]
            bsc = first_bracket["screen_center"]
            print(f"‹ Found Left Angle Bracket #{first_bracket['bracket_id']}: Local=({blc[0]}, {blc[1]}), Screen=({bsc[0]}, {bsc[1]})", flush=True)

            print(f"🔙 Clicking Left Angle Bracket at Screen ({bsc[0]}, {bsc[1]}) to return...", flush=True)
            click_screen_point(bsc[0], bsc[1], delay=delay)
        else:
            print("⚠️ No Left Angle Bracket ('<') chevron found! Attempting fallback delay.", flush=True)
            time.sleep(delay)

        processed_count += 1
        iteration += 1

    print("=" * 85)
    print(f"🎉 COMPLETED: Processed {processed_count} red dot notification(s). Exiting.")
    print("=" * 85)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Iteratively find the first red dot, click it, capture content, click back chevron, and repeat until clean."
    )
    parser.add_argument(
        "-w", "--window-app",
        type=str,
        default="WeChat",
        help="Target application window name (default: 'WeChat')"
    )
    parser.add_argument(
        "-o", "--output-dir",
        type=str,
        default="captures",
        help="Output directory for captured content screenshots (default: 'captures')"
    )
    parser.add_argument(
        "-d", "--delay",
        type=float,
        default=1.0,
        help="Pause delay in seconds between clicks and actions (default: 1.0s)"
    )
    parser.add_argument(
        "-m", "--max-iterations",
        type=int,
        default=20,
        help="Maximum loop safety limit (default: 20)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Locate targets and simulate workflow without performing physical mouse clicks"
    )
    parser.add_argument(
        "--include-three-dots",
        action="store_true",
        help="Also process large three-dots red circle badges if no small red dots remain"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_red_dot_processing_loop(
        app_name=args.window_app,
        output_dir=args.output_dir,
        delay=args.delay,
        max_iterations=args.max_iterations,
        dry_run=args.dry_run,
        include_three_dots=args.include_three_dots
    )
