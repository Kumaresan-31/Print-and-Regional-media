import requests
resp = requests.get("https://epaperlokmat.in/js/footer1.js?v=1.1")
print(resp.text[:2000])
