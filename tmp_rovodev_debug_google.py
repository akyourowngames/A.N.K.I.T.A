import sys
sys.path.insert(0, ".")
import requests
import re
from urllib.parse import urlencode
from tools.realtime_search import _get_random_headers

# Save Google response to inspect it
resp = requests.get(
    "https://www.google.com/search?q=Everest+Public+School+Shalimar+Garden&num=5&hl=en",
    headers=_get_random_headers(),
    timeout=15
)
print("Status:", resp.status_code)
print("Content-Type:", resp.headers.get("Content-Type",""))
print("Content length:", len(resp.text))

# Check what's in the HTML - look for common Google result markers
print("Has 'Sorry':", "Sorry" in resp.text or "sorry" in resp.text)
print("Has 'captcha':", "captcha" in resp.text.lower())
print("Has 'Everest':", "Everest" in resp.text)

# Check DDG lite response
print()
print("=== DDG LITE ===")
resp2 = requests.get(
    "https://lite.duckduckgo.com/lite/?q=Everest+Public+School",
    headers=_get_random_headers(),
    timeout=15
)
print("Status:", resp2.status_code)
print("Content length:", len(resp2.text))
print("Has 'Everest':", "Everest" in resp2.text)
# Print a snippet of the HTML to understand structure
start = resp2.text.find("result")
if start > 0:
    print("Snippet around 'result':", resp2.text[max(0,start-100):start+300])
else:
    print("First 800 chars:", resp2.text[:800])

# Also try Bing
print()
print("=== BING TEST ===")
resp3 = requests.get(
    "https://www.bing.com/search?q=Everest+Public+School+Shalimar+Garden",
    headers=_get_random_headers(),
    timeout=15
)
print("Status:", resp3.status_code)
print("Content length:", len(resp3.text))
print("Has 'Everest':", "Everest" in resp3.text)
# Try to find result links
links = re.findall(r'<a[^>]+href="(https?://(?!www\.bing\.com)[^"]+)"[^>]*>([^<]{10,80})</a>', resp3.text)
print("Bing links found:", len(links))
for url, title in links[:5]:
    print(" -", title[:50], "|", url[:60])
