import json
from pathlib import Path

# Array 4 cookies provided by the user
cookies = [
    {
        "domain": ".financialexpress.com",
        "expirationDate": 1821361841,
        "hostOnly": False,
        "httpOnly": False,
        "name": "FCNEC",
        "path": "/",
        "sameSite": None,
        "secure": False,
        "session": False,
        "storeId": None,
        "value": "%5B%5B%22AKsRol_1cwXzoU6dr13WPH0z45VKXcVsjxCE7ahfnyO1Vlh3dtrFwNM9_Y5AUqlfWvK0Pb6d-8px3c0vE3TEy-t-PPucsQeVl-vjHPM2Y-oBXIrnmBSUZ_cPivUK3QyK2sMCBDj55_hIOdPE4SzIS275Fj0yiHMFiw%3D%3D%22%5D%5D"
    },
    {
        "domain": ".financialexpress.com",
        "expirationDate": 1824385839.888686,
        "hostOnly": False,
        "httpOnly": False,
        "name": "_ga_7MX91MLTQY",
        "path": "/",
        "sameSite": None,
        "secure": False,
        "session": False,
        "storeId": None,
        "value": "GS2.2.s1789825299$o1$g1$t1789825839$j49$l0$h0"
    },
    {
        "domain": ".financialexpress.com",
        "expirationDate": 1800295903,
        "hostOnly": False,
        "httpOnly": False,
        "name": "fpuuid",
        "path": "/",
        "sameSite": "no_restriction",
        "secure": True,
        "session": False,
        "storeId": None,
        "value": "269010791465091"
    },
    {
        "domain": ".financialexpress.com",
        "expirationDate": 1789911683,
        "hostOnly": False,
        "httpOnly": False,
        "name": "panoramaId",
        "path": "/",
        "sameSite": "lax",
        "secure": False,
        "session": False,
        "storeId": None,
        "value": "c583824d1f2d19602d5c71413959a9fb927a0bb25913480b161dbc5d654f5eb6"
    },
    {
        "domain": ".financialexpress.com",
        "expirationDate": 1789825899,
        "hostOnly": False,
        "httpOnly": False,
        "name": "_gat_custom",
        "path": "/",
        "sameSite": None,
        "secure": False,
        "session": False,
        "storeId": None,
        "value": "1"
    },
    {
        "domain": ".financialexpress.com",
        "expirationDate": 1813153285,
        "hostOnly": False,
        "httpOnly": False,
        "name": "_pubcid",
        "path": "/",
        "sameSite": "lax",
        "secure": False,
        "session": False,
        "storeId": None,
        "value": "e3012c77-9409-4983-835e-5d472092f423"
    },
    {
        "domain": ".financialexpress.com",
        "expirationDate": 1824385839.673672,
        "hostOnly": False,
        "httpOnly": False,
        "name": "_ga",
        "path": "/",
        "sameSite": None,
        "secure": False,
        "session": False,
        "storeId": None,
        "value": "GA1.1.427729547.1768759903"
    },
    {
        "domain": ".financialexpress.com",
        "expirationDate": 1824385832.367848,
        "hostOnly": False,
        "httpOnly": False,
        "name": "_ga_9CPNE49VV8",
        "path": "/",
        "sameSite": None,
        "secure": False,
        "session": False,
        "storeId": None,
        "value": "GS2.1.s1789825284$o1$g1$t1789825832$j7$l0$h0"
    },
    {
        "domain": ".financialexpress.com",
        "expirationDate": 1789911683,
        "hostOnly": False,
        "httpOnly": False,
        "name": "panoramaId_expiry",
        "path": "/",
        "sameSite": "lax",
        "secure": False,
        "session": False,
        "storeId": None,
        "value": "1789911682905"
    },
    {
        "domain": ".financialexpress.com",
        "expirationDate": 1789912239,
        "hostOnly": False,
        "httpOnly": False,
        "name": "_gid",
        "path": "/",
        "sameSite": None,
        "secure": False,
        "session": False,
        "storeId": None,
        "value": "GA1.2.1306206561.1789825284"
    },
    {
        "domain": ".financialexpress.com",
        "expirationDate": 1805377282,
        "hostOnly": False,
        "httpOnly": False,
        "name": "__eoi",
        "path": "/",
        "sameSite": "no_restriction",
        "secure": True,
        "session": False,
        "storeId": None,
        "value": "ID=9d5872e6319447a3:T=1789825282:RT=1789825600:S=AA-Afjb96KOljHtozmMWNicNniIn"
    },
    {
        "domain": ".financialexpress.com",
        "expirationDate": 1789825887,
        "hostOnly": False,
        "httpOnly": False,
        "name": "_gat",
        "path": "/",
        "sameSite": None,
        "secure": False,
        "session": False,
        "storeId": None,
        "value": "1"
    },
    {
        "domain": "epaper.financialexpress.com",
        "expirationDate": 1792417839,
        "hostOnly": True,
        "httpOnly": False,
        "name": "rwmypublications",
        "path": "/",
        "sameSite": None,
        "secure": False,
        "session": False,
        "storeId": None,
        "value": "335%2C629%2C434%2C628%2C630%2C227%2C26733%2C301%2C267%2C272%2C631"
    },
    {
        "domain": ".financialexpress.com",
        "expirationDate": 1823521282,
        "hostOnly": False,
        "httpOnly": False,
        "name": "__gads",
        "path": "/",
        "sameSite": "no_restriction",
        "secure": True,
        "session": False,
        "storeId": None,
        "value": "ID=9265f6fc83ca1f0c:T=1789825282:RT=1789825600:S=ALNI_MYHX_5DH5Url0FoREOtSAoCzpJsig"
    },
    {
        "domain": ".financialexpress.com",
        "expirationDate": 1823521282,
        "hostOnly": False,
        "httpOnly": False,
        "name": "__gpi",
        "path": "/",
        "sameSite": "no_restriction",
        "secure": True,
        "session": False,
        "storeId": None,
        "value": "UID=0000157be7414a66:T=1789825282:RT=1789825600:S=ALNI_Map8oCWYk1HBmOwigbY0qkaiz4S3w"
    },
    {
        "domain": ".financialexpress.com",
        "expirationDate": 1802887902,
        "hostOnly": False,
        "httpOnly": False,
        "name": "_cb",
        "path": "/",
        "sameSite": None,
        "secure": True,
        "session": False,
        "storeId": None,
        "value": "DJIj8HCCc-pPliqR-"
    },
    {
        "domain": ".financialexpress.com",
        "expirationDate": 1813153285,
        "hostOnly": False,
        "httpOnly": False,
        "name": "_cc_id",
        "path": "/",
        "sameSite": "lax",
        "secure": False,
        "session": False,
        "storeId": None,
        "value": "8ed2470f55ccaf9493de2d7e5b8506bb"
    },
    {
        "domain": ".financialexpress.com",
        "expirationDate": 1802887902,
        "hostOnly": False,
        "httpOnly": False,
        "name": "_chartbeat2",
        "path": "/",
        "sameSite": None,
        "secure": True,
        "session": False,
        "storeId": None,
        "value": ".1768759902681.1768759902681.1.fxPvQC_GQzOCrBk7dC7_ickB9TLGI.1"
    },
    {
        "domain": ".financialexpress.com",
        "expirationDate": 1797601839,
        "hostOnly": False,
        "httpOnly": False,
        "name": "_fbp",
        "path": "/",
        "sameSite": "lax",
        "secure": False,
        "session": False,
        "storeId": None,
        "value": "fb.1.1789825299560.48355172465144530"
    },
    {
        "domain": ".financialexpress.com",
        "expirationDate": 1824385839.673142,
        "hostOnly": False,
        "httpOnly": False,
        "name": "_ga_9KTL14ZRVG",
        "path": "/",
        "sameSite": None,
        "secure": False,
        "session": False,
        "storeId": None,
        "value": "GS2.1.s1789825298$o1$g1$t1789825839$j60$l0$h0"
    },
    {
        "domain": ".financialexpress.com",
        "expirationDate": 1824385832.354097,
        "hostOnly": False,
        "httpOnly": False,
        "name": "_ga_VH7JQY923R",
        "path": "/",
        "sameSite": None,
        "secure": False,
        "session": False,
        "storeId": None,
        "value": "GS2.1.s1789825283$o3$g1$t1789825832$j7$l0$h2009101982"
    },
    {
        "domain": ".financialexpress.com",
        "expirationDate": 1823521829,
        "hostOnly": False,
        "httpOnly": False,
        "name": "_scor_uid",
        "path": "/",
        "sameSite": "no_restriction",
        "secure": True,
        "session": False,
        "storeId": None,
        "value": "0d46da0382354703a5e7d34cb6b774be"
    },
    {
        "domain": ".financialexpress.com",
        "expirationDate": 1823521287,
        "hostOnly": False,
        "httpOnly": False,
        "name": "cto_bundle",
        "path": "/",
        "sameSite": None,
        "secure": False,
        "session": False,
        "storeId": None,
        "value": "q-96iV9aNEJ4aWVaZTAyQWpWSUxXVk1hek5hNCUyRiUyRmlrUE5sN256JTJGUDNEQXRISEROQ0h4VzNMbWtJMkNyblRKNjhJWDNDREglMkI4NDFvSGtzV1ZTMzlIeXBkNHJseHd0RkxNTjg5WmpZSkxVcyUyRnRqWU8lMkI0OXpjOTJja1d6OFVhYjUlMkJMN3F2REI3cFFHU1ZneWwxRE5FaU1peUt4UURqSk9la1dXM2ExM1hjRGIySnNEbyUzRA"
    },
    {
        "domain": ".financialexpress.com",
        "expirationDate": 1823521840,
        "hostOnly": False,
        "httpOnly": False,
        "name": "FCCDCF",
        "path": "/",
        "sameSite": None,
        "secure": False,
        "session": False,
        "storeId": None,
        "value": "%5Bnull%2Cnull%2Cnull%2Cnull%2Cnull%2Cnull%2C%5B%5B32%2C%22%5B%5C%221677e159-9457-429a-a314-590ddb7bc726%5C%22%2C%5B1789825284%2C905000000%5D%5D%22%5D%5D%5D"
    },
    {
        "domain": ".financialexpress.com",
        "expirationDate": 1800295903,
        "hostOnly": False,
        "httpOnly": False,
        "name": "fpid",
        "path": "/",
        "sameSite": "no_restriction",
        "secure": True,
        "session": False,
        "storeId": None,
        "value": "1179dce30c6782eb6a8befbdadd0db02"
    },
    {
        "domain": ".financialexpress.com",
        "expirationDate": 1820066501.099653,
        "hostOnly": False,
        "httpOnly": False,
        "name": "moe_uuid",
        "path": "/",
        "sameSite": "no_restriction",
        "secure": True,
        "session": False,
        "storeId": None,
        "value": "2cd712e2-9bd2-4606-80e6-ec68f8e88d1e"
    },
    {
        "domain": ".financialexpress.com",
        "expirationDate": 1789911683,
        "hostOnly": False,
        "httpOnly": False,
        "name": "panoramaIdType",
        "path": "/",
        "sameSite": "lax",
        "secure": False,
        "session": False,
        "storeId": None,
        "value": "panoDevice"
    },
    {
        "domain": ".financialexpress.com",
        "expirationDate": 1817042501.225644,
        "hostOnly": False,
        "httpOnly": False,
        "name": "uplad",
        "path": "/",
        "sameSite": None,
        "secure": True,
        "session": False,
        "storeId": None,
        "value": "2026-07-31"
    }
]

out_dir = Path("data/sessions")
out_dir.mkdir(parents=True, exist_ok=True)

# 1. Master session file
data = {
    "source_id": "financial_express",
    "updated_at": "2026-09-19T14:20:00.000000+00:00",
    "cookies": cookies
}
with open(out_dir / "financial_express.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
print(f"Saved {out_dir / 'financial_express.json'} with {len(cookies)} cookies")

# Also alias "financialexpress.json"
with open(out_dir / "financialexpress.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)

# 2. Individual city session files
cities = [
    "delhi", "mumbai", "bengaluru", "chennai", "kolkata",
    "lucknow", "hyderabad", "ahmedabad", "pune", "chandigarh", "kochi"
]
for city in cities:
    city_data = {
        "source_id": f"financial_express_{city}",
        "edition": city,
        "updated_at": "2026-09-19T14:20:00.000000+00:00",
        "cookies": cookies
    }
    with open(out_dir / f"financial_express_{city}.json", "w", encoding="utf-8") as f:
        json.dump(city_data, f, indent=2)

print(f"Saved {len(cities)} city-specific session files in data/sessions/")
