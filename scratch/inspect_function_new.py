import requests, re

resp = requests.get("https://epaperlokmat.in/js/function_new.js?v=8.0&date=26-11-2025")
text = resp.text
print("Length:", len(text))
for m in re.finditer(r'function\s+(\w+)', text):
    print("Function:", m.group(1))

# Check how slides or images are created
for line in text.splitlines():
    if any(k in line for k in ["images.epaperlokmat", "baseUrl", "issueid", "highres", "pageimg", "Append", ".jpg"]):
        print("Line:", line[:150].strip())
