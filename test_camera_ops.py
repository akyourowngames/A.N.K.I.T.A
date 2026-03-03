"""
Deep test for camera_ops with real scenarios.
"""
import sys
from pathlib import Path
from tools.camera_ops import camera_control

def test_camera_list_devices():
    """Test if camera is accessible."""
    print("\n" + "="*60)
    print("TEST 1: Camera Device Detection")
    print("="*60)
    
    try:
        import cv2
        cap = cv2.VideoCapture(0)
        if cap.isOpened():
            print("✅ Camera device found and accessible")
            ret, frame = cap.read()
            if ret:
                print(f"✅ Can capture frames: {frame.shape}")
            else:
                print("⚠️ Camera opened but cannot read frames")
            cap.release()
        else:
            print("❌ No camera device found or camera is in use")
            return False
    except Exception as e:
        print(f"❌ Error accessing camera: {e}")
        return False
    
    return True


def test_qr_scan():
    """Test QR code scanning (will timeout if no QR code)."""
    print("\n" + "="*60)
    print("TEST 2: QR Code Scanner")
    print("="*60)
    print("Testing QR scanner with 2 second timeout...")
    print("(Will timeout if no QR code is shown to camera)")
    
    try:
        result = camera_control(action="scan_qr", timeout=2)
        
        if result.get("ok"):
            print(f"✅ QR Code detected: {result.get('qr_data')}")
            print(f"   Attempts: {result.get('attempts')}")
        else:
            print(f"⚠️ No QR code detected (expected): {result.get('error')}")
            print(f"   Attempts made: {result.get('attempts', 0)}")
        
        return True
    except Exception as e:
        print(f"❌ QR scan error: {e}")
        return False


def test_burst_photos_dry_run():
    """Test burst photo logic without actually saving (quick test)."""
    print("\n" + "="*60)
    print("TEST 3: Burst Photos (Dry Run)")
    print("="*60)
    print("Testing burst photo capture (2 photos, 1 sec interval)...")
    
    try:
        # Create temp directory
        temp_dir = Path("test_output")
        temp_dir.mkdir(exist_ok=True)
        
        result = camera_control(
            action="burst_photos",
            count=2,
            interval=1.0,
            save_dir=str(temp_dir)
        )
        
        if result.get("ok"):
            photos = result.get("photos", [])
            print(f"✅ Captured {len(photos)} photos")
            for i, photo in enumerate(photos, 1):
                photo_path = Path(photo)
                if photo_path.exists():
                    size_kb = photo_path.stat().st_size / 1024
                    print(f"   Photo {i}: {photo_path.name} ({size_kb:.1f} KB)")
                else:
                    print(f"   ⚠️ Photo {i}: File not found at {photo}")
            
            # Cleanup
            for photo in photos:
                try:
                    Path(photo).unlink()
                except:
                    pass
            
            return True
        else:
            print(f"❌ Burst photos failed: {result.get('error')}")
            return False
            
    except Exception as e:
        print(f"❌ Burst photos error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_video_recording():
    """Test video recording (short 3 second clip)."""
    print("\n" + "="*60)
    print("TEST 4: Video Recording")
    print("="*60)
    print("Recording 3-second test video...")
    
    try:
        temp_dir = Path("test_output")
        temp_dir.mkdir(exist_ok=True)
        video_path = temp_dir / "test_video.avi"
        
        result = camera_control(
            action="record_video",
            duration=3,
            save_path=str(video_path)
        )
        
        if result.get("ok"):
            print(f"✅ Video recorded: {result.get('path')}")
            print(f"   Duration: {result.get('duration')} seconds")
            print(f"   Frames: {result.get('frames')}")
            
            if video_path.exists():
                size_mb = video_path.stat().st_size / (1024 * 1024)
                print(f"   File size: {size_mb:.2f} MB")
                
                # Cleanup
                try:
                    video_path.unlink()
                except:
                    pass
            
            return True
        else:
            print(f"❌ Video recording failed: {result.get('error')}")
            return False
            
    except Exception as e:
        print(f"❌ Video recording error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_invalid_action():
    """Test error handling for invalid action."""
    print("\n" + "="*60)
    print("TEST 5: Error Handling")
    print("="*60)
    print("Testing invalid action...")
    
    try:
        result = camera_control(action="invalid_action")
        
        if not result.get("ok"):
            print(f"✅ Correctly rejected invalid action: {result.get('error')}")
            return True
        else:
            print("❌ Should have rejected invalid action")
            return False
            
    except Exception as e:
        print(f"❌ Error handling test failed: {e}")
        return False


if __name__ == "__main__":
    print("\n" + "🎥 " * 20)
    print("CAMERA OPERATIONS - DEEP INTEGRATION TEST")
    print("🎥 " * 20)
    
    results = []
    
    # Test 1: Camera detection (critical)
    camera_available = test_camera_list_devices()
    results.append(("Camera Detection", camera_available))
    
    if not camera_available:
        print("\n⚠️ Camera not available - skipping camera-dependent tests")
        print("This is normal if:")
        print("  - No webcam is connected")
        print("  - Camera is in use by another application")
        print("  - Camera permissions are not granted")
    else:
        # Test 2: QR scanning
        results.append(("QR Scanner", test_qr_scan()))
        
        # Test 3: Burst photos
        results.append(("Burst Photos", test_burst_photos_dry_run()))
        
        # Test 4: Video recording
        results.append(("Video Recording", test_video_recording()))
    
    # Test 5: Error handling (doesn't need camera)
    results.append(("Error Handling", test_invalid_action()))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed!")
        sys.exit(0)
    else:
        print(f"\n⚠️ {total - passed} test(s) failed")
        sys.exit(1)
