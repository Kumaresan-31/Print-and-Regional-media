import json

def parse_concatenated_json(raw_text: str):
    decoder = json.JSONDecoder()
    idx = 0
    cookies = []
    while idx < len(raw_text):
        while idx < len(raw_text) and raw_text[idx].isspace():
            idx += 1
        if idx >= len(raw_text):
            break
        try:
            obj, end_idx = decoder.raw_decode(raw_text, idx)
            if isinstance(obj, list):
                cookies.extend(obj)
            elif isinstance(obj, dict):
                if "cookies" in obj:
                    cookies.extend(obj["cookies"])
                else:
                    cookies.append(obj)
            idx = end_idx
        except json.JSONDecodeError as e:
            print("Error at idx", idx, e)
            break
    return cookies

sample = '[{"name":"a","value":"1"}][{"name":"b","value":"2"}]'
res = parse_concatenated_json(sample)
print("Result:", res)
