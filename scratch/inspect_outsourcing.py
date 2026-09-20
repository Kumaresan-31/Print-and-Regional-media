import requests, re

resp = requests.get("https://epaperlokmat.in/js/function_new.js?v=8.0&date=26-11-2025")
text = resp.text

for m in re.finditer(r'OutSourcingData.*?\}', text, re.DOTALL):
    snippet = m.group(0)[:500]
    print("--- API Call ---")
    print(snippet)
