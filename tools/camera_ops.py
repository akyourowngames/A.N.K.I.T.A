"""
Camera operations for ANKITA - burst photos, video recording, QR scanning.
Uses LLM for intelligent decision-making instead of hardcoded logic.
"""
import cv2
import base64
import time
from pathlib import Path
from typing import Dict, Any, Optional
from llm.client import LLMRuntime, call_chat_once


def burst_photos(count: int = 5, interval: float = 2.0, save_dir: str = "Desktop", runtime: Optional[LLMRuntime] = None) -> Dict[str, Any]:
    """Take N photos spaced by interval seconds with LLM-guided quality assessment."""
    results = []
    errors = []
    
    try:
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            return {"ok": False, "error": "Could not open camera", "photos_taken": 0}
        
        # Warm up camera
        for _ in range(5):
            cap.read()
        
        desktop = Path.home() / "Desktop" if save_dir == "Desktop" else Path(save_dir)
        desktop.mkdir(parents=True, exist_ok=True)
        
        for i in range(count):
            ret, frame = cap.read()
            if ret:
                try:
                    timestamp = int(time.time())
                    path = desktop / f"photo_{i+1}_{timestamp}.jpg"
                    cv2.imwrite(str(path), frame)
                    results.append(str(path))
                    
                    # LLM-guided quality check on first photo
                    if i == 0 and runtime:
                        _, buffer = cv2.imencode('.jpg', frame)
                        img_b64 = base64.b64encode(buffer).decode('utf-8')
                        
                        quality_prompt = "Analyze this photo quality. Is it well-lit, in focus, and properly framed? Reply with: GOOD or POOR and brief reason."
                        try:
                            from llm.client import call_chat_with_image
                            quality_check = call_chat_with_image(runtime, quality_prompt, img_b64, max_tokens=50)
                            if "POOR" in quality_check.upper():
                                cap.release()
                                return {
                                    "ok": False, 
                                    "error": f"Photo quality issue: {quality_check}", 
                                    "photos": results,
                                    "photos_taken": len(results),
                                    "partial_success": True
                                }
                        except Exception as llm_err:
                            errors.append(f"Quality check failed: {llm_err}")
                
                except Exception as save_err:
                    errors.append(f"Failed to save photo {i+1}: {save_err}")
            else:
                errors.append(f"Failed to capture frame {i+1}")
            
            if i < count - 1:
                time.sleep(interval)
        
        cap.release()
        
        # Return success with warnings if some photos failed
        if results:
            return {
                "ok": True, 
                "photos": results, 
                "count": len(results),
                "requested": count,
                "errors": errors if errors else None,
                "partial_success": len(results) < count
            }
        else:
            return {
                "ok": False, 
                "error": "Failed to capture any photos", 
                "errors": errors,
                "photos_taken": 0
            }
            
    except Exception as e:
        return {
            "ok": False if not results else True, 
            "error": str(e),
            "photos": results,
            "photos_taken": len(results),
            "partial_success": len(results) > 0,
            "errors": errors
        }


def record_video(duration_seconds: int = 10, save_path: Optional[str] = None) -> Dict[str, Any]:
    """Record a video clip for N seconds."""
    frames_written = 0
    
    try:
        if save_path is None:
            save_path = str(Path.home() / "Desktop" / f"clip_{int(time.time())}.avi")
        
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            return {"ok": False, "error": "Could not open camera", "frames_written": 0}
        
        # Get camera properties
        fps = 20.0
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        fourcc = cv2.VideoWriter_fourcc(*'XVID')
        out = cv2.VideoWriter(save_path, fourcc, fps, (w, h))
        
        if not out.isOpened():
            cap.release()
            return {"ok": False, "error": "Could not initialize video writer", "frames_written": 0}
        
        end_time = time.time() + duration_seconds
        
        while time.time() < end_time:
            ret, frame = cap.read()
            if ret:
                out.write(frame)
                frames_written += 1
        
        cap.release()
        out.release()
        
        # Check if file was actually created
        video_path = Path(save_path)
        if video_path.exists() and video_path.stat().st_size > 0:
            return {
                "ok": True, 
                "path": save_path, 
                "duration": duration_seconds, 
                "frames": frames_written,
                "size_mb": round(video_path.stat().st_size / (1024 * 1024), 2)
            }
        else:
            return {
                "ok": False, 
                "error": "Video file was not created or is empty",
                "frames_written": frames_written,
                "attempted_path": save_path
            }
            
    except Exception as e:
        return {
            "ok": False, 
            "error": str(e),
            "frames_written": frames_written,
            "partial_success": frames_written > 0
        }


def scan_qr_from_webcam(timeout_seconds: int = 5) -> Dict[str, Any]:
    """Scan a QR code or barcode held up to the webcam."""
    try:
        detector = cv2.QRCodeDetector()
        cap = cv2.VideoCapture(0)
        
        if not cap.isOpened():
            return {"ok": False, "error": "Could not open camera"}
        
        # Warm up
        for _ in range(5):
            cap.read()
        
        start_time = time.time()
        attempts = 0
        
        while time.time() - start_time < timeout_seconds:
            ret, frame = cap.read()
            if ret:
                attempts += 1
                data, bbox, _ = detector.detectAndDecode(frame)
                if data:
                    cap.release()
                    return {"ok": True, "qr_data": data, "attempts": attempts}
            time.sleep(0.05)  # 20 fps
        
        cap.release()
        return {"ok": False, "error": f"No QR code detected in {timeout_seconds} seconds", "attempts": attempts}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def camera_control(action: str, runtime: Optional[LLMRuntime] = None, **kwargs) -> Dict[str, Any]:
    """
    Main camera control dispatcher with LLM integration.
    Actions: burst_photos, record_video, scan_qr
    """
    if action == "burst_photos":
        count = kwargs.get("count", 5)
        interval = kwargs.get("interval", 2.0)
        save_dir = kwargs.get("save_dir", "Desktop")
        return burst_photos(count, interval, save_dir, runtime)
    
    elif action == "record_video":
        duration = kwargs.get("duration", 10)
        save_path = kwargs.get("save_path")
        return record_video(duration, save_path)
    
    elif action == "scan_qr":
        timeout = kwargs.get("timeout", 5)
        return scan_qr_from_webcam(timeout)
    
    else:
        return {"ok": False, "error": f"Unknown camera action: {action}"}
