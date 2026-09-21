import asyncio
from pathlib import Path
from harvester.translation.llm_translator import llm_translator

async def test_tr():
    hl = "പ്രളയ നഷ്ടപരിഹാരം ഉടൻ നൽകണം"
    body = (
        "ജൂലൈ, ആഗസ്ത് മാസങ്ങളിലുണ്ടായ പ്രകൃതിക്ഷോഭവും മഴക്കെടുതിയും മൂലം കാർഷിക മേഖലയിലുണ്ടായ "
        "നാശനഷ്ടങ്ങൾക്ക് ഉടൻ നഷ്ടപരിഹാരം നൽകണമെന്ന് കേരള കർഷകസംഘം സംസ്ഥാന സമ്മേളനം ആവശ്യപ്പെട്ടു. "
        "മഴക്കെടുതിയിൽ സംസ്ഥാനത്താകെ 127 കോടി രൂപയുടെ കൃഷി നശിച്ചു. ഇത് 45,904 കർഷക കുടുംബങ്ങളെ നേരിട്ട് ബാധിച്ചു. "
        "ദുരിതാശ്വാസ ക്യാമ്പിൽ അഭയം തേടിയ കുടുംബങ്ങൾക്ക് 10,000 രൂപ വീതവും സ്ഥാപനങ്ങളിൽ വെള്ളംകയറി "
        "ഉപജീവനം നഷ്ടപ്പെട്ട വ്യാപാരികൾക്ക് ധനസഹായം നൽകുമെന്നും പ്രഖ്യാപിച്ചിരുന്നു."
    )
    tr_hl = await llm_translator.translate(hl, source_lang="ml")
    tr_body = await llm_translator.translate(body, source_lang="ml")
    out = [
        "--- HEADLINE ---",
        f"ORIG: {hl}",
        f"ENG : {tr_hl.translated_text}",
        "--- BODY ---",
        f"ORIG: {body}",
        f"ENG : {tr_body.translated_text}"
    ]
    Path("scratch/real_translation_out.txt").write_text("\n".join(out), encoding="utf-8")
    print("Successfully translated and written to scratch/real_translation_out.txt")

asyncio.run(test_tr())
