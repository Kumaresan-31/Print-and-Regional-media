import requests

base_urls = [
    "https://images.epaperlokmat.in/eNewspaper/News/LOK/PULK/2026/09/20/1208193334.jpg",
    "https://images.epaperlokmat.in/eNewspaper/News/LOK/PULK/2026/09/20/Images/1208193334.jpg",
    "https://images.epaperlokmat.in/eNewspaper/News/LOK/PULK/2026/09/20/Big/1208193334.jpg",
    "https://images.epaperlokmat.in/eNewspaper/News/LOK/PULK/2026/09/20/Thumbnails/1208193334.jpg",
    "https://epaperlokmat.in/eNewspaper/News/LOK/PULK/2026/09/20/1208193334.jpg",
]

for u in base_urls:
    r = requests.head(u, timeout=5)
    print(u, r.status_code, r.headers.get("content-length"))
