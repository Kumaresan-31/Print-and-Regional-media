import requests, re
from bs4 import BeautifulSoup

url = "https://epaper.lokmat.com/articlepage.php?catid=1&eddate=2026-09-20"
resp = requests.get(url, timeout=15)
soup = BeautifulSoup(resp.text, "html.parser")

# Find all script src
scripts = [s.get("src") for s in soup.find_all("script") if s.get("src")]
print("Scripts:", scripts[:10])

# Find all images or canvas or zoom containers
containers = [tag.get("id") or tag.get("class") for tag in soup.find_all(["div", "section", "main"]) if any(k in str(tag.get("id") or "") or k in str(tag.get("class") or "") for k in ["page", "epaper", "edition", "book", "zoom", "read"])]
print("Containers:", containers[:10])

# Search for any image links with jpg or png or article
all_imgs = [img.get("src") or img.get("data-src") for img in soup.find_all("img")]
print("All img srcs:", all_imgs[:10])

# Search for inline scripts with eddate or page or catid
inline = [s.text for s in soup.find_all("script") if not s.get("src") and ("page" in s.text or "eddate" in s.text or "catid" in s.text)]
print(f"Found {len(inline)} inline scripts.")
for idx, s in enumerate(inline):
    print(f"--- Inline {idx} (first 300 chars) ---")
    print(s[:300].strip())
