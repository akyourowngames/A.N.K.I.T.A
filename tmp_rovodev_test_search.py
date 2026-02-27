import sys
sys.path.insert(0, ".")
import requests
import re
from urllib.parse import urlencode
from tools.realtime_search import _get_random_headers, _DuckResultParser, search_web

# Test DDG
print("=== DDG Test ===")
try:
    resp = requests.get("https://html.duckduckgo.com/html/?q=Everest+Public+School+Shalimar+Garden", headers=_get_random_headers(), timeout=15)
    print("DDG Status:", resp.status_code)
    print("DDG Content length:", len(resp.text))
    # Count result anchors
    uddg_count = resp.text.count("uddg=")
    result_a_count = resp.text.count("result__a")
    print("uddg= occurrences:", uddg_count)
    print("result__a occurrences:", result_a_count)
    # Try parser
    parser = _DuckResultParser()
    parser.feed(resp.text)
    print("DDG parsed results:", len(parser.results))
    for r in parser.results[:3]:
        print(" -", r["title"], "|", r["url"][:60])
except Exception as e:
    print("DDG Error:", e)

# Test Google udm=14
print()
print("=== Google udm=14 Test ===")
try:
    url = "https://www.google.com/search?q=Everest+Public+School+Shalimar+Garden&udm=14&num=5"
    resp = requests.get(url, headers=_get_random_headers(), timeout=15)
    print("Google Status:", resp.status_code)
    print("Google Content length:", len(resp.text))
    links = re.findall(r'<a href="/url\?q=([^&"]+)[^"]*"[^>]*>([^<]+)', resp.text)
    print("Google links found:", len(links))
    for raw_url, raw_title in links[:3]:
        from urllib.parse import unquote
        clean_url = unquote(raw_url)
        if clean_url.startswith("http") and "google.com" not in clean_url:
            print(" -", raw_title[:50], "|", clean_url[:60])
except Exception as e:
    print("Google Error:", e)

# Full search test
print()
print("=== Full search_web Test ===")
result = search_web("Everest Public School Shalimar Garden", max_results=5, include_urls=True)
print("Engine:", result["engine"])
print("Results:", len(result["results"]))
for r in result["results"]:
    print(" -", r.get("title","")[:60], "|", r.get("url","")[:70])
