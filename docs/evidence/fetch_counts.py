import urllib.request
import re
import json

for rid in ['wrvz-psew', 'm6dm-c72p']:
    url = f"https://data.cityofchicago.org/d/{rid}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
            matches = re.findall(r'(\d[\d,]*\s*(?:Rows|rows))', html)
            print(rid, "matches:", matches[:10])
            # search for JSON blobs in html
            scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
            for s in scripts:
                if 'rowCount' in s or 'count' in s:
                    m = re.findall(r'"rowCount":\s*(\d+)', s)
                    if m:
                        print(rid, "script rowCount:", m)
    except Exception as e:
        print(rid, "error:", e)

