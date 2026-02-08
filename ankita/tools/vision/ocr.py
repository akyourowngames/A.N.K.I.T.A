"""
Vision OCR Tool - Local text recognition and UI coordinate mapping.
Integrated with PyAutoGUI for OS-level control.
"""
import os
import time
import pyautogui
import datetime
from PIL import Image


def run(action: str = "read_screen", target_text: str = None, **kwargs) -> dict:
    """
    Perform OCR and UI element detection.
    
    Actions:
        - read_screen: Capture screen and extract all text
        - find_text: Locate specific text and return coordinates
        - click_text: Find specific text and click it
        - scan_region: Extract text from a specific screen box
    """
    action = (action or "read_screen").strip().lower()
    
    # Try to import OCR engine (EasyOCR preferred for local)
    try:
        import easyocr
        import numpy as np
    except ImportError:
        return {
            "status": "fail", 
            "reason": "OCR dependencies missing.",
            "hint": "Run: .venv311\\Scripts\\pip install easyocr torch torchvision"
        }

    try:
        # Initialize Reader (cached if possible)
        # Note: 'en' is English, can add more
        reader = easyocr.Reader(['en'], gpu=False) # Force CPU for compatibility
        
        # Capture the current state
        screenshot = pyautogui.screenshot()
        img_np = np.array(screenshot)
        
        if action == "read_screen":
            results = reader.readtext(img_np)
            full_text = " ".join([res[1] for res in results])
            return {
                "status": "success",
                "message": "Screen read successfully",
                "text": full_text,
                "segments": [{"text": res[1], "confidence": res[2]} for res in results]
            }

        if action in ("find_text", "click_text"):
            if not target_text:
                return {"status": "fail", "reason": "No target_text provided"}
            
            results = reader.readtext(img_np)
            target_lower = target_text.lower()
            
            for (bbox, text, prob) in results:
                if target_lower in text.lower():
                    # Calculate center of the bounding box
                    # bbox is [[x1,y1], [x2,y1], [x2,y2], [x1,y2]]
                    center_x = int((bbox[0][0] + bbox[1][0]) / 2)
                    center_y = int((bbox[0][1] + bbox[2][1]) / 2)
                    
                    if action == "click_text":
                        pyautogui.click(center_x, center_y)
                        return {"status": "success", "message": f"Clicked '{text}' at ({center_x}, {center_y})"}
                    
                    return {
                        "status": "success", 
                        "message": f"Found '{text}'", 
                        "coords": (center_x, center_y),
                        "confidence": prob
                    }
            
            return {"status": "fail", "reason": f"Text '{target_text}' not found on screen"}

        if action == "scan_region":
            # kwargs should have x1, y1, x2, y2
            region = kwargs.get("region") # (left, top, width, height)
            if not region:
                return {"status": "fail", "reason": "No region provided"}
            
            screenshot = pyautogui.screenshot(region=region)
            results = reader.readtext(np.array(screenshot))
            text = " ".join([res[1] for res in results])
            return {"status": "success", "text": text}

        return {"status": "fail", "reason": f"Unknown vision action: {action}"}

    except Exception as e:
        return {"status": "fail", "reason": f"Vision/OCR Error: {str(e)}"}
