import sys
sys.path.insert(0, ".")
import requests
import re
from tools.realtime_search import _get_random_headers

resp = requests.get(
    "https://www.google.com/search?q=Everest+Public+School+Shalimar+Garden&num=5&hl=en",
    headers=_get_random_headers(),
    timeout=15
)

# Find all hrefs
all_hrefs = re.findall(r'href="([^"]+)"', resp.text)
# Filter for external URLs
external = [h for h in all_hrefs if h.startswith("http") and "google" not in h and "gstatic" not in h]
print("External hrefs found:", len(external))
for h in external[:10]:
    print(" -", h[:80])

print()
# Look for data around "Everest"
idx = resp.text.find("Everest")
print("Context around 'Everest':")
print(repr(resp.text[max(0,idx-200):idx+300]))
