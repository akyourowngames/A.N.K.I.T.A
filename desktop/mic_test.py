"""Microphone diagnostic: what does headless Chrome actually hear?

    python desktop/mic_test.py              # current app flags
    python desktop/mic_test.py --real-mic   # without the fake-device flag

Speak at a normal volume during the 6-second measurement. The report shows
the audio inputs Chrome sees, which track got opened, and the peak level.
Peak ~0 + "fake" device label = Chrome is NOT hearing your real microphone.
"""

import argparse
import json
import sys
import tempfile
import time

PAGE = """<!DOCTYPE html><html><body><p id="report">...</p><script>
window.__report = {devices: [], track: 'none', peak: 0};
(async () => {
  try {
    const devs = await navigator.mediaDevices.enumerateDevices();
    window.__report.devices = devs.filter(d => d.kind === 'audioinput')
      .map(d => (d.label || '(no label)') + ' [' + d.deviceId.slice(0, 8) + ']');
    const stream = await navigator.mediaDevices.getUserMedia({audio: true});
    const track = stream.getAudioTracks()[0];
    window.__report.track = track ? track.label : 'none';
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const src = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 2048;
    src.connect(analyser);
    const buf = new Float32Array(analyser.fftSize);
    let peak = 0;
    const t0 = performance.now();
    while (performance.now() - t0 < 6000) {
      analyser.getFloatTimeDomainData(buf);
      for (let i = 0; i < buf.length; i++) {
        const v = Math.abs(buf[i]);
        if (v > peak) peak = v;
      }
      await new Promise(r => setTimeout(r, 50));
    }
    window.__report.peak = peak;
    window.__report.done = true;
  } catch (e) {
    window.__report.error = String(e);
    window.__report.done = true;
  }
})();
</script></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--real-mic", action="store_true",
                        help="drop --use-fake-device-for-media-stream")
    args = parser.parse_args()

    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager

    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(PAGE)
        url = "file:///" + fh.name.replace("\\", "/")

    options = Options()
    options.add_argument("--use-fake-ui-for-media-stream")
    if not args.real_mic:
        options.add_argument("--use-fake-device-for-media-stream")
    options.add_argument("--headless=new")
    options.add_argument("--log-level=3")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()),
                              options=options)
    try:
        driver.get(url)
        print("SPEAK NOW at normal volume (6 seconds)...", flush=True)
        for _ in range(40):
            done = driver.execute_script("return window.__report.done === true")
            if done:
                break
            time.sleep(0.5)
        report = driver.execute_script("return window.__report")
        print(json.dumps(report, indent=2, ensure_ascii=False))
        peak = float(report.get("peak") or 0)
        if report.get("error"):
            print("RESULT: getUserMedia FAILED ->", report["error"])
            return 1
        track = str(report.get("track") or "")
        low = track.lower()
        if "fake" in low:
            print("RESULT: FAKE DEVICE. Remove --use-fake-device-for-media-stream.")
            return 1
        if "hands-free" in low or "bluetooth" in low:
            print("WARNING: default input is a Bluetooth hands-free mic. On Windows")
            print("this is usually SILENT while stereo (A2DP) output is active.")
            print("Fix: Settings -> Sound -> Input -> pick 'Microphone Array")
            print("(Realtek Audio)' (or run: mmsys.cpl -> Recording tab -> Set Default).")
        if peak < 0.01:
            print("RESULT: SILENCE (peak %.4f). Speak during the test; if it stays" % peak)
            print("0 while you speak, the default input above is the wrong mic.")
            return 1
        print("RESULT: MIC LIVE (peak %.3f)." % peak)
        return 0
    finally:
        driver.quit()


if __name__ == "__main__":
    raise SystemExit(main())
