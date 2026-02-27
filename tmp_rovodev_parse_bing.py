import sys
sys.path.insert(0, ".")
import requests
import re
from tools.realtime_search import _get_random_headers

resp = requests.get(
    "https://www.bing.com/search?q=Everest+Public+School+Shalimar+Garden&count=8",
    headers=_get_random_headers(),
    timeout=15
)
print("Status:", resp.status_code)
print("Content length:", len(resp.text))
print("Has 'Everest':", "Everest" in resp.text)

# Bing result links are typically in <h2><a href="https://...">
h2_links = re.findall(r'<h2[^>]*><a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', resp.text, re.DOTALL)
print("h2 links found:", len(h2_links))
for url, title in h2_links[:5]:
    clean = re.sub(r'<[^>]+>', '', title).strip()
    print(" -", clean[:60], "|", url[:70])

print()
# Try citation/cite links
cite_links = re.findall(r'<cite[^>]*>(.*?)</cite>', resp.text, re.DOTALL)
print("cite elements:", len(cite_links))
for c in cite_links[:5]:
    print(" -", re.sub(r'<[^>]+>', '', c).strip()[:60])

print()
# Find all external hrefs
all_hrefs = re.findall(r'href="(https?://[^"]+)"', resp.text)
external = [h for h in all_hrefs if "bing.com" not in h and "microsoft.com" not in h and "msn.com" not in h]
print("External hrefs:", len(external))
for h in external[:8]:
    print(" -", h[:80])

# Also find context around 'Everest'
idx = resp.text.find("Everest")
if idx > 0:
    print()
    print("Context around 'Everest':")
    print(repr(resp.text[max(0,idx-300):idx+200]))
