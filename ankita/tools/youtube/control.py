"""
YouTube Control Tool - Extended playback and navigation controls.

Features:
- Pause/Resume playback
- Skip YouTube ads
- Toggle fullscreen mode
- Navigate to subscriptions/history
- Add to queue
- Volume control within player
"""

from tools.youtube.browser import get_page, reset
import time


def _ensure_youtube(page) -> bool:
    """Ensure we're on YouTube, navigate if not."""
    try:
        if not page.url.startswith("https://www.youtube.com"):
            page.goto("https://www.youtube.com")
            time.sleep(2)
            return True
        return True
    except Exception as e:
        print(f"[YouTube] Failed to navigate: {e}")
        return False


def _is_video_playing(page) -> bool:
    """Check if a video is currently loaded."""
    try:
        return "/watch" in page.url or page.locator("video").count() > 0
    except:
        return False


def run(action: str = "pause", **kwargs) -> dict:
    """
    Control YouTube playback and navigation.
    
    Actions:
        - pause/play: Toggle video playback
        - fullscreen: Toggle fullscreen mode
        - skip_ad/skip: Skip YouTube ad
        - subscriptions: Go to subscriptions page
        - history: Go to watch history
        - queue/add_queue: Add current video to queue
        - mute: Mute video player
        - unmute: Unmute video player
        - volume_up: Increase player volume
        - volume_down: Decrease player volume
        - next: Play next video
        - previous: Play previous video
        - theater: Toggle theater mode
        - miniplayer: Toggle miniplayer
        - captions: Toggle captions/subtitles
        - speed_up: Increase playback speed
        - speed_down: Decrease playback speed
        - liked: Go to liked videos
        - watch_later: Go to watch later
    """
    action = (action or "pause").strip().lower().replace(" ", "_")
    
    # Normalize action aliases
    action_aliases = {
        "resume": "pause",
        "toggle_play": "pause",
        "playpause": "pause",
        "full": "fullscreen",
        "fs": "fullscreen",
        "skip": "skip_ad",
        "skipad": "skip_ad",
        "ad": "skip_ad",
        "subs": "subscriptions",
        "subscription": "subscriptions",
        "add_queue": "queue",
        "add_to_queue": "queue",
        "vol_up": "volume_up",
        "vol_down": "volume_down",
        "cc": "captions",
        "subtitles": "captions",
        "faster": "speed_up",
        "slower": "speed_down",
        "likes": "liked",
        "wl": "watch_later",
    }
    action = action_aliases.get(action, action)
    
    last_err = None
    for attempt in range(2):
        try:
            page = get_page()
            
            if not _ensure_youtube(page):
                return {"status": "fail", "reason": "Could not open YouTube"}
            
            # === Playback Controls ===
            
            if action == "pause":
                if not _is_video_playing(page):
                    return {"status": "skip", "message": "No video is playing"}
                
                # Press 'k' - YouTube's keyboard shortcut for play/pause
                page.keyboard.press("k")
                time.sleep(0.3)
                return {"status": "success", "message": "Toggled play/pause"}
            
            if action == "fullscreen":
                if not _is_video_playing(page):
                    return {"status": "skip", "message": "No video is playing"}
                
                # Press 'f' for fullscreen
                page.keyboard.press("f")
                time.sleep(0.5)
                return {"status": "success", "message": "Toggled fullscreen"}
            
            if action == "theater":
                if not _is_video_playing(page):
                    return {"status": "skip", "message": "No video is playing"}
                
                # Press 't' for theater mode
                page.keyboard.press("t")
                time.sleep(0.3)
                return {"status": "success", "message": "Toggled theater mode"}
            
            if action == "miniplayer":
                if not _is_video_playing(page):
                    return {"status": "skip", "message": "No video is playing"}
                
                # Press 'i' for miniplayer
                page.keyboard.press("i")
                time.sleep(0.3)
                return {"status": "success", "message": "Toggled miniplayer"}
            
            if action == "skip_ad":
                # Try to find and click skip ad button
                skip_selectors = [
                    "button.ytp-ad-skip-button",
                    "button.ytp-ad-skip-button-modern",
                    ".ytp-ad-skip-button-container button",
                    "[class*='skip'] button",
                    "button:has-text('Skip')",
                    "button:has-text('Skip Ad')",
                    "button:has-text('Skip Ads')",
                ]
                
                for selector in skip_selectors:
                    try:
                        skip_btn = page.locator(selector)
                        if skip_btn.is_visible(timeout=1000):
                            skip_btn.click()
                            time.sleep(0.5)
                            return {"status": "success", "message": "Skipped ad"}
                    except:
                        continue
                
                # If no skip button, might not be an ad
                return {"status": "skip", "message": "No skippable ad found"}
            
            if action == "mute":
                if not _is_video_playing(page):
                    return {"status": "skip", "message": "No video is playing"}
                
                # Press 'm' for mute
                page.keyboard.press("m")
                time.sleep(0.2)
                return {"status": "success", "message": "Muted video"}
            
            if action == "unmute":
                # Same as mute - it toggles
                page.keyboard.press("m")
                time.sleep(0.2)
                return {"status": "success", "message": "Unmuted video"}
            
            if action == "volume_up":
                # Press up arrow 5 times (each press is 5% volume)
                for _ in range(5):
                    page.keyboard.press("ArrowUp")
                    time.sleep(0.05)
                return {"status": "success", "message": "Volume increased"}
            
            if action == "volume_down":
                # Press down arrow 5 times
                for _ in range(5):
                    page.keyboard.press("ArrowDown")
                    time.sleep(0.05)
                return {"status": "success", "message": "Volume decreased"}
            
            if action == "next":
                # Shift+N for next video
                page.keyboard.press("Shift+n")
                time.sleep(1)
                return {"status": "success", "message": "Playing next video"}
            
            if action == "previous":
                # Shift+P for previous video  
                page.keyboard.press("Shift+p")
                time.sleep(1)
                return {"status": "success", "message": "Playing previous video"}
            
            if action == "captions":
                # Press 'c' for captions
                page.keyboard.press("c")
                time.sleep(0.3)
                return {"status": "success", "message": "Toggled captions"}
            
            if action == "speed_up":
                # Shift+> to speed up
                page.keyboard.press("Shift+>")
                time.sleep(0.2)
                return {"status": "success", "message": "Increased playback speed"}
            
            if action == "speed_down":
                # Shift+< to slow down
                page.keyboard.press("Shift+<")
                time.sleep(0.2)
                return {"status": "success", "message": "Decreased playback speed"}
            
            # === Navigation Controls ===
            
            if action == "subscriptions":
                page.goto("https://www.youtube.com/feed/subscriptions")
                time.sleep(2)
                return {"status": "success", "message": "Opened subscriptions"}
            
            if action == "history":
                page.goto("https://www.youtube.com/feed/history")
                time.sleep(2)
                return {"status": "success", "message": "Opened watch history"}
            
            if action == "liked":
                page.goto("https://www.youtube.com/playlist?list=LL")
                time.sleep(2)
                return {"status": "success", "message": "Opened liked videos"}
            
            if action == "watch_later":
                page.goto("https://www.youtube.com/playlist?list=WL")
                time.sleep(2)
                return {"status": "success", "message": "Opened Watch Later"}
            
            if action == "queue":
                if not _is_video_playing(page):
                    return {"status": "skip", "message": "No video to add to queue"}
                
                # Try to find the 3-dot menu and add to queue
                try:
                    # Click the video title area to ensure we're focused
                    page.click("#container h1.ytd-video-primary-info-renderer", timeout=2000)
                except:
                    pass
                
                # Try right-click context menu approach
                try:
                    menu_btn = page.locator("#button[aria-label='More actions']").first
                    if menu_btn.is_visible(timeout=2000):
                        menu_btn.click()
                        time.sleep(0.5)
                        
                        add_queue = page.locator("tp-yt-paper-listbox [aria-label*='queue'], ytd-menu-service-item-renderer:has-text('queue')").first
                        if add_queue.is_visible(timeout=1000):
                            add_queue.click()
                            return {"status": "success", "message": "Added to queue"}
                except:
                    pass
                
                return {"status": "skip", "message": "Could not add to queue - try manually"}
            
            if action == "home":
                page.goto("https://www.youtube.com")
                time.sleep(2)
                return {"status": "success", "message": "Went to YouTube home"}
            
            if action == "trending":
                page.goto("https://www.youtube.com/feed/trending")
                time.sleep(2)
                return {"status": "success", "message": "Opened trending"}
            
            if action == "shorts":
                page.goto("https://www.youtube.com/shorts")
                time.sleep(2)
                return {"status": "success", "message": "Opened YouTube Shorts"}
            
            return {"status": "fail", "reason": f"Unknown action: {action}"}
            
        except Exception as e:
            last_err = e
            msg = str(e)
            print(f"[YouTube Control] Error: {msg}")
            if attempt == 0 and ("Target page" in msg or "has been closed" in msg):
                reset()
                time.sleep(0.3)
                continue
            break
    
    return {"status": "fail", "reason": str(last_err)}
