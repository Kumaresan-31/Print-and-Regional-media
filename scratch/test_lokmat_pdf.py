import requests

data = {
    "selectedPagePdf": "1",
    "issueidPdf": "LOK_PULK_20260920"
}
headers = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://epaper.lokmat.com/main-editions/Pune%20Main/-1/1"
}
resp = requests.post("https://epaper.lokmat.com/loginform.php/", data=data, headers=headers, timeout=10)
print("Response status:", resp.status_code)
print("Response text:", resp.text)
