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

    # 7. Simulate mouse scroll down (-5 lines) at coordinates (500, 300) and exit
    python monitor_right_column.py --scroll -5 --scroll-at 500 300 --scroll-only
"""

import os
import sys
import time
import json
import math
import subprocess
import argparse
import platform
import ctypes
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageGrab, ImageChops, ImageStat, ImageDraw


def simulate_mouse_scroll(
    dy: int = 0,
    dx: int = 0,
    x: int = None,
    y: int = None,
    units: str = "line",
    steps: int = None,
    delay: float = 0.008,
    flick: bool = True
) -> bool:
    """
    Simulates a mouse scroll event (vertical and/or horizontal) at optional screen coordinates.
    For large scroll distances on macOS, automatically breaks down the scroll into a fast, natural
    sequence of individual ticks mimicking a human finger flick on a trackpad or scroll wheel spin.

    Args:
        dy (int): Vertical scroll distance (positive = scroll up, negative = scroll down).
        dx (int): Horizontal scroll distance (positive = scroll right, negative = scroll left).
        x (int, optional): Target screen X coordinate to move cursor before scrolling.
        y (int, optional): Target screen Y coordinate to move cursor before scrolling.
        units (str): Scroll units, either 'line' (default) or 'pixel'.
        steps (int, optional): Number of incremental steps to split the scroll action across.
            If None, automatically calculated based on total distance for human-like sequence flicks.
        delay (float): Delay in seconds between sequence ticks during scrolling (default: 0.008s).
        flick (bool): If True and scrolling across multiple sequence ticks, applies an easing velocity
            curve (acceleration/deceleration) to mimic natural finger-flicking on macOS trackpads.

    Returns:
        bool: True if the scroll event was successfully sent, False otherwise.
    """
    if dy == 0 and dx == 0:
        return True

    unit_is_pixel = units.lower() == "pixel"
    max_tick_size = 25 if unit_is_pixel else 3
    abs_max_delta = max(abs(dy), abs(dx))

    if steps is None:
        if abs_max_delta > max_tick_size:
            steps = max(1, int(math.ceil(abs_max_delta / max_tick_size)))
        else:
            steps = 1
    else:
        steps = max(1, steps)

    os_name = platform.system()

    # Pre-generate per-step deltas (with optional momentum/velocity curve)
    deltas_y = []
    deltas_x = []

    if flick and steps > 3:
        # Sine-based ease-in-out curve for human-like trackpad flick momentum
        weights = [math.sin(math.pi * (i + 0.5) / steps) for i in range(steps)]
        sum_w = sum(weights)

        rem_y = float(dy)
        rem_x = float(dx)
        for i in range(steps):
            if i == steps - 1:
                step_y_val = int(round(rem_y))
                step_x_val = int(round(rem_x))
            else:
                step_y_val = int(round(dy * weights[i] / sum_w))
                step_x_val = int(round(dx * weights[i] / sum_w))
                rem_y -= step_y_val
                rem_x -= step_x_val
            deltas_y.append(step_y_val)
            deltas_x.append(step_x_val)
    else:
        step_dy = dy / steps
        step_dx = dx / steps
        accum_y = 0.0
        accum_x = 0.0
        for _ in range(steps):
            accum_y += step_dy
            accum_x += step_dx
            cur_y = int(round(accum_y))
            cur_x = int(round(accum_x))
            accum_y -= cur_y
            accum_x -= cur_x
            deltas_y.append(cur_y)
            deltas_x.append(cur_x)

    # 1. macOS Native Implementation via CoreGraphics (ctypes)
    if os_name == "Darwin":
        try:
            cg = ctypes.CDLL(
                '/System/Library/Frameworks/ApplicationServices.framework/Frameworks/CoreGraphics.framework/CoreGraphics'
            )
            cf = ctypes.CDLL(
                '/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation'
            )

            class CGPoint(ctypes.Structure):
                _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

            cg.CGEventCreateMouseEvent.restype = ctypes.c_void_p
            cg.CGEventCreateMouseEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, CGPoint, ctypes.c_uint32]
            cg.CGEventCreateScrollWheelEvent.restype = ctypes.c_void_p
            cg.CGEventCreateScrollWheelEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int32, ctypes.c_int32]
            cg.CGEventPost.restype = None
            cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
            cf.CFRelease.restype = None
            cf.CFRelease.argtypes = [ctypes.c_void_p]

            if x is not None and y is not None:
                move_ev = cg.CGEventCreateMouseEvent(None, 5, CGPoint(float(x), float(y)), 0)
                if move_ev:
                    cg.CGEventPost(0, move_ev)
                    cf.CFRelease(move_ev)

            unit_flag = 1 if unit_is_pixel else 0

            for step_y, step_x in zip(deltas_y, deltas_x):
                if step_y != 0 or step_x != 0:
                    scroll_ev = cg.CGEventCreateScrollWheelEvent(None, unit_flag, 2, step_y, step_x)
                    if scroll_ev:
                        cg.CGEventPost(0, scroll_ev)
                        cf.CFRelease(scroll_ev)

                if steps > 1 and delay > 0:
                    time.sleep(delay)
            return True
        except Exception as e:
            print(f"macOS native scroll error: {e}", file=sys.stderr)

    # 2. Windows Native Implementation via user32.dll (ctypes)
    elif os_name == "Windows":
        try:
            user32 = ctypes.windll.user32
            if x is not None and y is not None:
                user32.SetCursorPos(int(x), int(y))

            MOUSEEVENTF_WHEEL = 0x0800
            MOUSEEVENTF_HWHEEL = 0x01000
            WHEEL_DELTA = 120

            for step_y, step_x in zip(deltas_y, deltas_x):
                if step_y != 0:
                    user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, int(step_y * WHEEL_DELTA), 0)
                if step_x != 0:
                    user32.mouse_event(MOUSEEVENTF_HWHEEL, 0, 0, int(step_x * WHEEL_DELTA), 0)
                if steps > 1 and delay > 0:
                    time.sleep(delay)
            return True
        except Exception as e:
            print(f"Windows scroll error: {e}", file=sys.stderr)

    # 3. Linux Implementation via xdotool
    elif os_name == "Linux":
        try:
            if x is not None and y is not None:
                subprocess.run(["xdotool", "mousemove", str(int(x)), str(int(y))], check=False)

            for step_y, step_x in zip(deltas_y, deltas_x):
                if step_y > 0:
                    subprocess.run(["xdotool", "click", "--repeat", str(step_y), "4"], check=False)
                elif step_y < 0:
                    subprocess.run(["xdotool", "click", "--repeat", str(abs(step_y)), "5"], check=False)

                if step_x > 0:
                    subprocess.run(["xdotool", "click", "--repeat", str(step_x), "7"], check=False)
                elif step_x < 0:
                    subprocess.run(["xdotool", "click", "--repeat", str(abs(step_x)), "6"], check=False)

                if steps > 1 and delay > 0:
                    time.sleep(delay)
            return True
        except Exception as e:
            print(f"Linux scroll error: {e}", file=sys.stderr)

    # 4. Fallback to PyAutoGUI if native methods failed or unhandled platform
    try:
        import pyautogui
        if x is not None and y is not None:
            pyautogui.moveTo(x, y)
        for step_y, step_x in zip(deltas_y, deltas_x):
            if step_y != 0:
                pyautogui.scroll(step_y)
            if step_x != 0 and hasattr(pyautogui, 'hscroll'):
                pyautogui.hscroll(step_x)
            if steps > 1 and delay > 0:
                time.sleep(delay)
        return True
    except ImportError:
        pass
    except Exception:
        pass

    return False


def estimate_image_scroll_offset(
    img_before: Image.Image,
    img_after: Image.Image,
    max_shift_y: int = 400,
    max_shift_x: int = 50,
    step: int = 1,
    target_early_stop_inv: float = 90.0,
    req_dy: int = None,
    req_dx: int = None,
    mouse_x: int = None,
    mouse_y: int = None
) -> dict:
    """
    Compares two screenshots (before and after scrolling) to calculate the visual pixel offset.
    Checks the physical directional relationship FIRST:
      - Scroll Down (req_dy <= 0) -> Content moves UP (points in img_before near/below mouse move above).
      - Scroll Up (req_dy > 0)   -> Content moves DOWN (points in img_before near/above mouse move below).
    Locks onto expected directional shifts first, falling back to multi-granularity pyramid search if needed.

    Args:
        img_before (PIL.Image.Image): Screenshot captured before scrolling.
        img_after (PIL.Image.Image): Screenshot captured after scrolling.
        max_shift_y (int): Maximum vertical pixel offset to search (default: 400).
        max_shift_x (int): Maximum horizontal pixel offset to search (default: 50).
        step (int): Fine search pixel resolution step (default: 1).
        target_early_stop_inv (float): Target invariant percentage threshold (0-100%) to trigger early stopping.
        req_dy (int, optional): Requested vertical scroll magnitude.
        req_dx (int, optional): Requested horizontal scroll magnitude.
        mouse_x (int, optional): Mouse cursor X coordinate.
        mouse_y (int, optional): Mouse cursor Y coordinate.

    Returns:
        dict: A dictionary containing:
            - 'detected_dx': Horizontal pixel shift of content.
            - 'detected_dy': Vertical pixel shift of content (negative = content moved UP / scrolled down).
            - 'scrolled_distance_px': Euclidean pixel distance of movement.
            - 'similarity': Invariant matching confidence percentage (0.0 to 100.0%).
            - 'effect_detected': True if visual scroll effect detected, False otherwise.
            - 'changed_area_bbox': Smallest bounding box tuple (left, top, right, bottom) of changed pixels.
    """
    b_gray = img_before.convert("L")
    a_gray = img_after.convert("L")
    w, h = b_gray.size

    # Expected direction based on requested scroll
    # Default assumption: scroll down (req_dy <= 0) -> content moves UP (expected_dy_dir = -1)
    expected_dy_dir = -1 if (req_dy is None or req_dy <= 0) else 1
    expected_dx_dir = -1 if (req_dx is not None and req_dx < 0) else (1 if (req_dx is not None and req_dx > 0) else 0)

    # 1. FIRST CHECK: Physical Directional Mouse Feature Region Check
    mx = mouse_x if mouse_x is not None else w // 2
    my = mouse_y if mouse_y is not None else h // 2
    mx = max(0, min(w - 1, mx))
    my = max(0, min(h - 1, my))

    rw = min(w // 2, 500)
    rh = min(h // 3, 350)
    rx1 = max(0, mx - rw // 2)
    rx2 = min(w, mx + rw // 2)

    # For scroll down (expected_dy_dir < 0), feature points in img_before are below/at mouse (my to my+rh)
    # For scroll up (expected_dy_dir > 0), feature points in img_before are above/at mouse (my-rh to my)
    ry1 = max(0, my if expected_dy_dir < 0 else my - rh)
    ry2 = min(h, my + rh if expected_dy_dir < 0 else my)

    crop_mouse_before = b_gray.crop((rx1, ry1, rx2, ry2))

    # Search in expected directional displacement order FIRST!
    dy_search_coarse = range(0, -max_shift_y - 1, -4) if expected_dy_dir < 0 else range(0, max_shift_y + 1, 4)

    best_mouse_inv = 0.0
    best_coarse_dy = 0

    for cand_dy in dy_search_coarse:
        ay1 = ry1 + cand_dy
        ay2 = ry2 + cand_dy
        if ay1 < 0 or ay2 > h:
            continue
        crop_after_shifted = a_gray.crop((rx1, ay1, rx2, ay2))

        diff = ImageChops.difference(crop_mouse_before, crop_after_shifted)
        inv_mask = diff.point(lambda p: 255 if p <= 15 else 0)
        inv_pct = (ImageStat.Stat(inv_mask).mean[0] / 255.0) * 100.0

        if inv_pct > best_mouse_inv:
            best_mouse_inv = inv_pct
            best_coarse_dy = cand_dy

    # Fine step refinement around best directional match
    fine_best_inv = best_mouse_inv
    final_dy = best_coarse_dy
    for fine_dy in range(best_coarse_dy - 4, best_coarse_dy + 5):
        ay1 = ry1 + fine_dy
        ay2 = ry2 + fine_dy
        if ay1 < 0 or ay2 > h:
            continue
        crop_after_shifted = a_gray.crop((rx1, ay1, rx2, ay2))
        diff = ImageChops.difference(crop_mouse_before, crop_after_shifted)
        inv_mask = diff.point(lambda p: 255 if p <= 15 else 0)
        inv_pct = (ImageStat.Stat(inv_mask).mean[0] / 255.0) * 100.0
        if inv_pct > fine_best_inv:
            fine_best_inv = inv_pct
            final_dy = fine_dy

    # If First Check hits target confidence, early stop immediately!
    if fine_best_inv >= target_early_stop_inv:
        dist = math.hypot(0, final_dy)
        diff_full = ImageChops.difference(img_before, img_after)
        mask = diff_full.convert("L").point(lambda p: 255 if p > 12 else 0)
        tight_bbox = mask.getbbox()

        return {
            "detected_dx": 0,
            "detected_dy": final_dy,
            "scrolled_distance_px": round(dist, 2),
            "similarity": round(fine_best_inv, 2),
            "effect_detected": True,
            "changed_area_bbox": tight_bbox if tight_bbox else (rx1, ry1, rx2, ry2)
        }

    # 2. FALLBACK: Dynamic multi-granularity pyramid search (checking expected direction first)
    targets = [200, 450, 900, 1600, max(w, h)]
    scales = []
    for t in targets:
        s = min(1.0, max(0.05, t / float(max(w, h))))
        if not scales or abs(s - scales[-1]) > 0.05:
            scales.append(s)
    if scales[-1] != 1.0:
        scales.append(1.0)

    best_dy, best_dx = 0, 0
    best_inv_pct = 0.0

    for level, scale in enumerate(scales):
        sw = max(1, int(round(w * scale)))
        sh = max(1, int(round(h * scale)))

        b_level = b_gray.resize((sw, sh), Image.BILINEAR) if scale < 1.0 else b_gray
        a_level = a_gray.resize((sw, sh), Image.BILINEAR) if scale < 1.0 else a_gray

        center_y = int(round(best_dy * scale))
        center_x = int(round(best_dx * scale))

        if level == 0:
            search_r_y = max(1, int(round(max_shift_y * scale)))
            search_r_x = max(1, int(round(max_shift_x * scale)))
            step_size = max(1, int(round(2 * scale * 10)))
        else:
            search_r_y = max(2, int(round(3 * (scales[level] / scales[level - 1]))))
            search_r_x = max(2, int(round(3 * (scales[level] / scales[level - 1]))))
            step_size = max(1, step)

        level_best_inv = 0.0
        level_best_s_dy = center_y
        level_best_s_dx = center_x

        y_min = max(-int(round(max_shift_y * scale)), center_y - search_r_y)
        y_max = min(int(round(max_shift_y * scale)), center_y + search_r_y)
        x_min = max(-int(round(max_shift_x * scale)), center_x - search_r_x)
        x_max = min(int(round(max_shift_x * scale)), center_x + search_r_x)

        # Order search in expected physical direction FIRST
        y_steps = range(y_min, y_max + 1, step_size)
        if expected_dy_dir < 0:
            y_steps = sorted(y_steps, key=lambda val: (val > 0, abs(val)))
        else:
            y_steps = sorted(y_steps, key=lambda val: (val < 0, abs(val)))

        for s_dy in y_steps:
            for s_dx in range(x_min, x_max + 1, step_size):
                b_left, b_top = max(0, -s_dx), max(0, -s_dy)
                b_right, b_bottom = min(sw, sw - s_dx), min(sh, sh - s_dy)
                a_left, a_top = max(0, s_dx), max(0, s_dy)
                a_right, a_bottom = min(sw, sw + s_dx), min(sh, sh + s_dy)

                if (b_right - b_left) < sw * 0.3 or (b_bottom - b_top) < sh * 0.3:
                    continue

                crop_b = b_level.crop((b_left, b_top, b_right, b_bottom))
                crop_a = a_level.crop((a_left, a_top, a_right, a_bottom))

                diff = ImageChops.difference(crop_b, crop_a)
                inv_mask = diff.point(lambda p: 255 if p <= 15 else 0)
                inv_pct = (ImageStat.Stat(inv_mask).mean[0] / 255.0) * 100.0

                if inv_pct > level_best_inv:
                    level_best_inv = inv_pct
                    level_best_s_dy = s_dy
                    level_best_s_dx = s_dx

        best_dy = int(round(level_best_s_dy / scale))
        best_dx = int(round(level_best_s_dx / scale))
        best_inv_pct = level_best_inv

        if level >= 1 and best_inv_pct >= target_early_stop_inv:
            break

    dist = math.hypot(best_dx, best_dy)
    diff_full = ImageChops.difference(img_before, img_after)
    mask = diff_full.convert("L").point(lambda p: 255 if p > 12 else 0)
    tight_bbox = mask.getbbox()

    if (best_dy == 0 and best_dx == 0) or tight_bbox is None:
        changed_area_bbox = None
        effect_detected = False
    else:
        changed_area_bbox = tight_bbox
        effect_detected = True

    return {
        "detected_dx": best_dx,
        "detected_dy": best_dy,
        "scrolled_distance_px": round(dist, 2),
        "similarity": round(best_inv_pct, 2),
        "effect_detected": effect_detected,
        "changed_area_bbox": changed_area_bbox
    }


def draw_detected_scroll_box(
    img_after: Image.Image,
    bbox: tuple,
    dy: int = 0,
    dx: int = 0,
    similarity: float = 0.0
) -> Image.Image:
    """
    Draws a prominent bounding box outline and annotation label badge on the after image showing detected scrolled area.
    """
    annotated = img_after.copy().convert("RGB")
    draw = ImageDraw.Draw(annotated)

    if bbox is not None:
        left, top, right, bottom = bbox
        w, h = right - left, bottom - top

        # Outer black shadow outline + inner bright green border for high contrast
        draw.rectangle([left - 1, top - 1, right + 1, bottom + 1], outline=(0, 0, 0), width=4)
        draw.rectangle([left, top, right, bottom], outline=(0, 255, 0), width=2)

        # Annotation text badge
        label = f" Scrolled Area: dy={dy}px, dx={dx}px ({w}x{h}px, {similarity}% match) "
        text_y = max(5, top - 24) if top >= 25 else top + 5
        text_w = len(label) * 7 + 10
        draw.rectangle([left, text_y, left + text_w, text_y + 20], fill=(0, 0, 0))
        draw.text((left + 5, text_y + 3), label, fill=(0, 255, 0))

    return annotated


def scroll_and_measure_offset(
    dy: int = 0,
    dx: int = 0,
    x: int = None,
    y: int = None,
    bbox: tuple = None,
    units: str = "line",
    steps: int = None,
    settling_delay: float = 0.3,
    max_search_offset: int = 400,
    output_dir: str = None
) -> dict:
    """
    Captures screen content before scrolling, executes a mouse scroll simulation,
    waits for rendering to settle, captures screen content after scrolling, compares
    the images to figure out exact scrolled pixel distance, and draws a bounding box on the after capture.

    Args:
        dy (int): Vertical scroll distance.
        dx (int): Horizontal scroll distance.
        x (int, optional): Target screen X coordinate for cursor.
        y (int, optional): Target screen Y coordinate for cursor.
        bbox (tuple, optional): Screen bounding box (left, top, right, bottom) to monitor and measure.
        units (str): Scroll units ('line' or 'pixel').
        steps (int, optional): Number of scroll sequence steps.
        settling_delay (float): Settling time in seconds after scrolling before capturing after image.
        max_search_offset (int): Maximum pixel search offset to align images.
        output_dir (str, optional): Directory to save before, after, and annotated detection images.

    Returns:
        dict: A result dictionary containing requested scroll, detected pixel offset,
              similarity metrics, effect detection status, smallest boundary box, PIL Images, and saved file paths.
    """
    print("  📷 [1/3] Capturing initial screen state...", flush=True)
    try:
        img_before = ImageGrab.grab(bbox=bbox)
    except Exception as e:
        print(f"❌ Error grabbing initial screenshot: {e}", file=sys.stderr, flush=True)
        print("Note: On macOS, ensure Python/Terminal has Screen Recording permissions in System Settings.", file=sys.stderr, flush=True)
        return None

    print("  🖱️  [2/3] Dispatched scroll event, waiting for UI render...", flush=True)
    simulate_mouse_scroll(
        dy=dy,
        dx=dx,
        x=x,
        y=y,
        units=units,
        steps=steps
    )

    if settling_delay > 0:
        time.sleep(settling_delay)

    try:
        img_after = ImageGrab.grab(bbox=bbox)
    except Exception as e:
        print(f"❌ Error grabbing screenshot after scroll: {e}", file=sys.stderr, flush=True)
        return None

    print("  🔍 [3/3] Analyzing image displacement & bounding area...", flush=True)
    search_y = max_search_offset if dy != 0 else 15
    search_x = max(15, abs(dx) * 15) if dx != 0 else 10

    offset_result = estimate_image_scroll_offset(
        img_before,
        img_after,
        max_shift_y=search_y,
        max_shift_x=search_x,
        req_dy=dy,
        req_dx=dx,
        mouse_x=x,
        mouse_y=y
    )

    tight_bbox = offset_result["changed_area_bbox"]
    screen_bbox = None
    if tight_bbox and bbox:
        screen_bbox = (
            bbox[0] + tight_bbox[0],
            bbox[1] + tight_bbox[1],
            bbox[0] + tight_bbox[2],
            bbox[1] + tight_bbox[3]
        )
    elif tight_bbox:
        screen_bbox = tight_bbox

    # Draw detected bounding box on after image
    img_after_annotated = draw_detected_scroll_box(
        img_after,
        tight_bbox,
        dy=offset_result["detected_dy"],
        dx=offset_result["detected_dx"],
        similarity=offset_result["similarity"]
    )

    saved_files = {}
    if output_dir:
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]

        before_file = out_path / f"scroll_before_{ts}.png"
        after_file = out_path / f"scroll_after_{ts}.png"
        annotated_file = out_path / f"scroll_detected_box_{ts}.png"

        img_before.save(before_file)
        img_after.save(after_file)
        img_after_annotated.save(annotated_file)

        saved_files = {
            "before": str(before_file.resolve()),
            "after": str(after_file.resolve()),
            "annotated": str(annotated_file.resolve())
        }

    return {
        "requested_scroll": {"dy": dy, "dx": dx},
        "detected_offset": {
            "dx": offset_result["detected_dx"],
            "dy": offset_result["detected_dy"]
        },
        "scrolled_distance_px": offset_result["scrolled_distance_px"],
        "similarity": offset_result["similarity"],
        "effect_detected": offset_result["effect_detected"],
        "changed_area_bbox": tight_bbox,
        "changed_area_screen_bbox": screen_bbox,
        "before_image": img_before,
        "after_image": img_after,
        "annotated_after_image": img_after_annotated,
        "saved_files": saved_files
    }



def subtract_rect_2d(rect_to_subtract: tuple, from_rect: tuple) -> list:
    """
    Subtracts rect_to_subtract from from_rect and returns a list of non-overlapping sub-rectangles.
    Rectangles are represented as tuples: (left, top, right, bottom).
    """
    x1, y1, x2, y2 = from_rect
    sx1, sy1, sx2, sy2 = rect_to_subtract

    # Check if no intersection
    if sx2 <= x1 or sx1 >= x2 or sy2 <= y1 or sy1 >= y2:
        return [from_rect]

    # Intersection exists, compute overlapping box
    ix1, iy1 = max(x1, sx1), max(y1, sy1)
    ix2, iy2 = min(x2, sx2), min(y2, sy2)

    pieces = []
    # Top piece
    if y1 < iy1:
        pieces.append((x1, y1, x2, iy1))
    # Bottom piece
    if iy2 < y2:
        pieces.append((x1, iy2, x2, y2))
    # Left piece
    if x1 < ix1:
        pieces.append((x1, iy1, ix1, iy2))
    # Right piece
    if ix2 < x2:
        pieces.append((ix2, iy1, x2, iy2))

    return pieces


def identify_screen_window_areas(
    min_width: int = 100,
    min_height: int = 100,
    draw_annotation: bool = False,
    output_path: str = None
) -> list:
    """
    Identifies and segments the computer screen into multiple non-overlapping rectangular window areas.

    Queries open GUI windows, orders them front-to-back by Z-index, and resolves overlaps
    via 2D rectangle geometry subtraction. Ensures every returned window bounding box
    (left, top, right, bottom) is strictly non-overlapping.

    Args:
        min_width (int): Minimum width threshold for valid window area (default: 100px).
        min_height (int): Minimum height threshold for valid window area (default: 100px).
        draw_annotation (bool): If True, captures screen and overlays colored boundary boxes and labels.
        output_path (str, optional): File path to save annotated screenshot if draw_annotation is True.

    Returns:
        list of dict: List of non-overlapping window area dictionaries.
    """
    raw_windows = []

    # Query macOS Window Manager via Quartz
    if platform.system() == "Darwin":
        try:
            import Quartz
            options = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
            window_list = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID)

            for w in window_list:
                layer = w.get("kCGWindowLayer", 0)
                # Filter out system overlay layers (menu bars, tooltips)
                if layer > 5:
                    continue

                bounds = w.get("kCGWindowBounds", {})
                width = int(bounds.get("Width", 0))
                height = int(bounds.get("Height", 0))

                if width < min_width or height < min_height:
                    continue

                x = int(bounds.get("X", 0))
                y = int(bounds.get("Y", 0))
                app_name = w.get("kCGWindowOwnerName", "Unknown")
                title = w.get("kCGWindowName", "")
                window_id = w.get("kCGWindowNumber", None)

                rect = (x, y, x + width, y + height)
                meta = {
                    "app_name": app_name,
                    "title": title,
                    "window_id": window_id,
                    "layer": layer
                }
                raw_windows.append((rect[0], rect[1], rect[2], rect[3], meta))
        except Exception as e:
            print(f"⚠️ Quartz window query error: {e}", file=sys.stderr, flush=True)

    # Perform Z-order 2D rectangle subtraction to generate strictly non-overlapping areas
    placed_rects = []
    result_areas = []

    for left, top, right, bottom, meta in raw_windows:
        current_pieces = [(left, top, right, bottom)]

        for p_rect in placed_rects:
            next_pieces = []
            for piece in current_pieces:
                subdivided = subtract_rect_2d(p_rect, piece)
                next_pieces.extend(subdivided)
            current_pieces = next_pieces

        valid_pieces = [p for p in current_pieces if (p[2] - p[0]) >= min_width and (p[3] - p[1]) >= min_height]

        for p in valid_pieces:
            area_dict = {
                "area_id": len(result_areas) + 1,
                "app_name": meta.get("app_name", ""),
                "title": meta.get("title", ""),
                "bbox": p,
                "width": p[2] - p[0],
                "height": p[3] - p[1],
                "window_id": meta.get("window_id", None)
            }
            result_areas.append(area_dict)

        placed_rects.append((left, top, right, bottom))

    # Optional visual annotation drawing
    if draw_annotation or output_path:
        try:
            screen_img = ImageGrab.grab()
            annotated = screen_img.copy().convert("RGB")
            draw = ImageDraw.Draw(annotated)

            colors = [
                (255, 50, 50),   # Red
                (50, 205, 50),   # Lime Green
                (30, 144, 255),  # Dodger Blue
                (255, 165, 0),   # Orange
                (147, 112, 219), # Purple
                (0, 206, 209),   # Cyan
                (255, 105, 180), # Hot Pink
                (255, 215, 0)    # Gold
            ]

            for idx, area in enumerate(result_areas, 1):
                color = colors[(idx - 1) % len(colors)]
                b = area["bbox"]
                b_left, b_top, b_right, b_bottom = b[0], b[1], b[2], b[3]

                draw.rectangle([b_left - 1, b_top - 1, b_right + 1, b_bottom + 1], outline=(0, 0, 0), width=4)
                draw.rectangle([b_left, b_top, b_right, b_bottom], outline=color, width=2)

                label = f" #{idx} {area['app_name']} ({area['width']}x{area['height']}px) "
                text_y = max(5, b_top + 5)
                text_w = len(label) * 7 + 10
                draw.rectangle([b_left + 5, text_y, b_left + 5 + text_w, text_y + 22], fill=(0, 0, 0))
                draw.text((b_left + 10, text_y + 3), label, fill=color)

            if output_path:
                out_p = Path(output_path)
                out_p.parent.mkdir(parents=True, exist_ok=True)
                annotated.save(out_p)
                print(f"📷 Saved Non-Overlapping Window Areas Annotation: {out_p.resolve()}", flush=True)

        except Exception as e:
            print(f"⚠️ Error rendering window area annotation: {e}", file=sys.stderr, flush=True)

    return result_areas


def identify_app_window_panels(
    app_name: str = None,
    window_bbox: tuple = None,
    img: Image.Image = None,
    min_panel_w: int = 80,
    min_panel_h: int = 80,
    draw_annotation: bool = False,
    output_path: str = None
) -> tuple:
    """
    Identifies and segments a single application window into multiple non-overlapping
    rectangular UI panel areas (e.g., sidebars, toolbars, main pane, status bars, right columns).

    Args:
        app_name (str, optional): Target application name to locate and capture (e.g., 'WeChat', 'Google Chrome').
        window_bbox (tuple, optional): Explicit window bounding box (left, top, right, bottom).
        img (PIL.Image.Image, optional): Direct window screenshot PIL Image object.
        min_panel_w (int): Minimum width threshold for valid sub-panels (default: 80px).
        min_panel_h (int): Minimum height threshold for valid sub-panels (default: 80px).
        draw_annotation (bool): If True, overlays colored boundary boxes and labels on window capture.
        output_path (str, optional): File path to save annotated window panels screenshot.

    Returns:
        tuple: (target_image, list_of_panel_dicts)
            - target_image: PIL Image of captured window.
            - list_of_panel_dicts: List of non-overlapping sub-panel bounding boxes and region tags.
    """
    win_left, win_top = 0, 0
    target_img = None

    if img is not None:
        target_img = img
    elif window_bbox is not None:
        win_left, win_top = window_bbox[0], window_bbox[1]
        try:
            target_img = ImageGrab.grab(bbox=window_bbox)
        except Exception:
            pass
    elif app_name:
        if platform.system() == "Darwin":
            try:
                import Quartz
                options = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
                w_list = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID)
                for w in w_list:
                    owner = w.get("kCGWindowOwnerName", "")
                    if app_name.lower() in owner.lower() and w.get("kCGWindowLayer", 0) <= 5:
                        b = w.get("kCGWindowBounds", {})
                        wx = int(b.get("X", 0))
                        wy = int(b.get("Y", 0))
                        ww = int(b.get("Width", 0))
                        wh = int(b.get("Height", 0))
                        if ww > 100 and wh > 100:
                            win_left, win_top = wx, wy
                            target_img = ImageGrab.grab(bbox=(wx, wy, wx + ww, wy + wh))
                            break
            except Exception as e:
                print(f"⚠️ Quartz query error for '{app_name}': {e}", file=sys.stderr, flush=True)

    if target_img is None:
        try:
            target_img = ImageGrab.grab()
        except Exception:
            target_img = Image.new("RGB", (800, 600), (240, 240, 240))

    w, h = target_img.size
    gray = target_img.convert("L")

    # Detect horizontal divider lines across window image
    h_diffs = []
    for y in range(1, h - 1):
        r1 = gray.crop((0, y - 1, w, y))
        r2 = gray.crop((0, y, w, y + 1))
        row_diff = abs(sum(r1.getdata()) - sum(r2.getdata())) / float(w)
        h_diffs.append((row_diff, y))

    # Detect vertical divider lines across window image
    v_diffs = []
    for x in range(1, w - 1):
        c1 = gray.crop((x - 1, 0, x, h))
        c2 = gray.crop((x, 0, x + 1, h))
        col_diff = abs(sum(c1.getdata()) - sum(c2.getdata())) / float(h)
        v_diffs.append((col_diff, x))

    sorted_h = sorted(h_diffs, key=lambda item: item[0], reverse=True)
    h_splits = [0, h]
    for score, y in sorted_h:
        if score > 15.0 and all(abs(y - existing) >= min_panel_h for existing in h_splits):
            h_splits.append(y)
            if len(h_splits) >= 4:
                break
    h_splits = sorted(h_splits)

    sorted_v = sorted(v_diffs, key=lambda item: item[0], reverse=True)
    v_splits = [0, w]
    for score, x in sorted_v:
        if score > 15.0 and all(abs(x - existing) >= min_panel_w for existing in v_splits):
            v_splits.append(x)
            if len(v_splits) >= 4:
                break
    v_splits = sorted(v_splits)

    # Build non-overlapping sub-rectangle panel grid
    panels = []
    panel_id = 1
    for i in range(len(h_splits) - 1):
        top_y, bot_y = h_splits[i], h_splits[i + 1]
        for j in range(len(v_splits) - 1):
            left_x, right_x = v_splits[j], v_splits[j + 1]
            pw, ph = right_x - left_x, bot_y - top_y

            if pw >= min_panel_w and ph >= min_panel_h:
                if top_y == 0 and ph < h * 0.18:
                    tag = "Header Bar"
                elif bot_y == h and ph < h * 0.15:
                    tag = "Footer Bar"
                elif left_x == 0 and pw < w * 0.35:
                    tag = "Left Sidebar"
                elif right_x == w and pw < w * 0.35:
                    tag = "Right Panel"
                else:
                    tag = "Main Content Pane"

                panels.append({
                    "panel_id": panel_id,
                    "tag": tag,
                    "local_bbox": (left_x, top_y, right_x, bot_y),
                    "screen_bbox": (win_left + left_x, win_top + top_y, win_left + right_x, win_top + bot_y),
                    "width": pw,
                    "height": ph
                })
                panel_id += 1

    # Optional visual annotation drawing
    if draw_annotation or output_path:
        try:
            annotated = target_img.copy().convert("RGB")
            draw = ImageDraw.Draw(annotated)

            colors = [
                (255, 50, 50),   # Red
                (50, 205, 50),   # Lime Green
                (30, 144, 255),  # Dodger Blue
                (255, 165, 0),   # Orange
                (147, 112, 219), # Purple
                (0, 206, 209),   # Cyan
                (255, 105, 180), # Hot Pink
                (255, 215, 0)    # Gold
            ]

            for idx, panel in enumerate(panels, 1):
                color = colors[(idx - 1) % len(colors)]
                b = panel["local_bbox"]
                b_left, b_top, b_right, b_bottom = b[0], b[1], b[2], b[3]

                draw.rectangle([b_left - 1, b_top - 1, b_right + 1, b_bottom + 1], outline=(0, 0, 0), width=4)
                draw.rectangle([b_left, b_top, b_right, b_bottom], outline=color, width=2)

                label = f" #{idx} {panel['tag']} ({panel['width']}x{panel['height']}px) "
                text_y = max(5, b_top + 5)
                text_w = len(label) * 7 + 10
                draw.rectangle([b_left + 5, text_y, b_left + 5 + text_w, text_y + 22], fill=(0, 0, 0))
                draw.text((b_left + 10, text_y + 3), label, fill=color)

            if output_path:
                out_p = Path(output_path)
                out_p.parent.mkdir(parents=True, exist_ok=True)
                annotated.save(out_p)
                print(f"📷 Saved App Window Sub-Panels Annotation: {out_p.resolve()}", flush=True)

        except Exception as e:
            print(f"⚠️ Error rendering app window sub-panels annotation: {e}", file=sys.stderr, flush=True)

    return target_img, panels


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
    target_group.add_argument(
        "--identify-windows",
        action="store_true",
        help="Identify and segment computer screen into multiple non-overlapping window areas and exit"
    )
    target_group.add_argument(
        "--draw-windows",
        action="store_true",
        help="Draw colored bounding boxes and labels for identified window areas and save screenshot"
    )
    target_group.add_argument(
        "--identify-panels",
        action="store_true",
        help="Identify and segment a target app window into multiple non-overlapping UI sub-panel rectangles and exit"
    )
    target_group.add_argument(
        "--draw-panels",
        action="store_true",
        help="Draw colored bounding boxes and labels for identified app sub-panels and save screenshot"
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

    # Mouse Action options
    mouse_group = parser.add_argument_group("Mouse Action Options")
    mouse_group.add_argument(
        "--scroll",
        type=int,
        default=0,
        metavar="AMOUNT",
        help="Simulate mouse vertical scroll (positive = up, negative = down)"
    )
    mouse_group.add_argument(
        "--scroll-h",
        type=int,
        default=0,
        metavar="AMOUNT",
        help="Simulate mouse horizontal scroll (positive = right, negative = left)"
    )
    mouse_group.add_argument(
        "--scroll-at",
        type=int,
        nargs=2,
        metavar=("X", "Y"),
        default=None,
        help="Coordinates (X Y) to move mouse cursor to before scrolling"
    )
    mouse_group.add_argument(
        "--scroll-steps",
        type=int,
        default=None,
        help="Number of steps for scroll sequence (default: auto calculated for trackpad flick sequence)"
    )
    mouse_group.add_argument(
        "--no-flick",
        action="store_true",
        help="Disable trackpad momentum velocity curve (ease-in-out) during scroll sequence"
    )
    mouse_group.add_argument(
        "--scroll-and-measure",
        action="store_true",
        help="Compare before and after screenshots during scrolling to measure exact visual pixel offset"
    )
    mouse_group.add_argument(
        "--scroll-only",
        action="store_true",
        help="Perform requested mouse scroll operation and exit without monitoring"
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

    # If --identify-windows requested, segment screen into non-overlapping areas and exit
    if args.identify_windows or args.draw_windows:
        out_file = None
        if args.draw_windows or args.output_dir:
            out_dir = Path(args.output_dir)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_file = str((out_dir / f"screen_window_areas_{ts}.png").resolve())

        areas = identify_screen_window_areas(
            draw_annotation=args.draw_windows,
            output_path=out_file
        )

        print("=" * 80)
        print(f" 🔲 IDENTIFIED NON-OVERLAPPING SCREEN WINDOW AREAS ({len(areas)} found)")
        print("=" * 80)
        if areas:
            for area in areas:
                b = area["bbox"]
                print(f"  {area['area_id']:2d}. App: {area['app_name']:20s} | Size: {area['width']:4d}x{area['height']:<4d} | BBox: ({b[0]}, {b[1]}, {b[2]}, {b[3]}) | Title: {area['title'][:35]}")
        else:
            print("  No visible window areas detected.")
        print("=" * 80)
        sys.exit(0)

    # If --identify-panels requested, segment target app window into sub-panels and exit
    if args.identify_panels or args.draw_panels:
        out_file = None
        if args.draw_panels or args.output_dir:
            out_dir = Path(args.output_dir)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            app_tag = args.window_app.replace(" ", "_") if args.window_app else "window"
            out_file = str((out_dir / f"app_panels_{app_tag}_{ts}.png").resolve())

        win_bbox_tuple = tuple(args.window_bbox) if args.window_bbox else None
        _, panels = identify_app_window_panels(
            app_name=args.window_app,
            window_bbox=win_bbox_tuple,
            draw_annotation=args.draw_panels,
            output_path=out_file
        )

        target_name = args.window_app or "Target Application Window"
        print("=" * 85)
        print(f" 🧩 IDENTIFIED NON-OVERLAPPING SUB-PANEL AREAS for '{target_name}' ({len(panels)} found)")
        print("=" * 85)
        if panels:
            for p in panels:
                lb = p["local_bbox"]
                sb = p["screen_bbox"]
                print(f"  Panel #{p['panel_id']:2d}: Tag: {p['tag']:20s} | Size: {p['width']:4d}x{p['height']:<4d} | Local: ({lb[0]}, {lb[1]}, {lb[2]}, {lb[3]}) | Screen: ({sb[0]}, {sb[1]}, {sb[2]}, {sb[3]})")
        else:
            print("  No sub-panel areas detected.")
        print("=" * 85)
        sys.exit(0)
    if args.scroll_and_measure:
        x_at, y_at = (args.scroll_at[0], args.scroll_at[1]) if args.scroll_at else (None, None)
        print(f"🖱️  Scrolling and measuring visual offset: dy={args.scroll}, dx={args.scroll_h}, at=({x_at}, {y_at})...", flush=True)
        res = scroll_and_measure_offset(
            dy=args.scroll,
            dx=args.scroll_h,
            x=x_at,
            y=y_at,
            steps=args.scroll_steps,
            output_dir=args.output_dir
        )
        if res:
            print(f"  ✅ Measured Content Shift : dy={res['detected_offset']['dy']} px, dx={res['detected_offset']['dx']} px", flush=True)
            print(f"  📏 Scrolled Distance     : {res['scrolled_distance_px']} px", flush=True)
            print(f"  🎯 Match Confidence      : {res['similarity']}%", flush=True)
            if res.get('effect_detected'):
                print(f"  📦 Smallest Scrolled Boundary BBox : {res['changed_area_bbox']}", flush=True)
                if res.get('changed_area_screen_bbox') and res['changed_area_screen_bbox'] != res['changed_area_bbox']:
                    print(f"  🖥️  Absolute Screen Boundary BBox   : {res['changed_area_screen_bbox']}", flush=True)
            else:
                print("  ℹ️  No visual scroll effect detected.", flush=True)

            if res.get('saved_files'):
                print("  📷 Saved Captures & Detection Box:", flush=True)
                print(f"    • Before Image : {res['saved_files']['before']}", flush=True)
                print(f"    • After Image  : {res['saved_files']['after']}", flush=True)
                print(f"    • Detected Box : {res['saved_files']['annotated']}", flush=True)
        else:
            print("  ❌ Failed to perform scroll measurement.", flush=True)
        if args.scroll_only:
            sys.exit(0)
    elif args.scroll != 0 or args.scroll_h != 0 or args.scroll_only:
        x_at, y_at = (args.scroll_at[0], args.scroll_at[1]) if args.scroll_at else (None, None)
        flick_enabled = not args.no_flick
        print(f"🖱️  Simulating mouse scroll: dy={args.scroll}, dx={args.scroll_h}, at=({x_at}, {y_at}), steps={args.scroll_steps or 'auto'}, flick={flick_enabled}")
        ok = simulate_mouse_scroll(
            dy=args.scroll,
            dx=args.scroll_h,
            x=x_at,
            y=y_at,
            steps=args.scroll_steps,
            flick=flick_enabled
        )
        if ok:
            print("  ✅ Mouse scroll event dispatched successfully.")
        else:
            print("  ❌ Failed to dispatch mouse scroll event.")

        if args.scroll_only:
            sys.exit(0 if ok else 1)

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
