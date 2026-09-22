import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from harvester.translation.llm_translator import llm_translator

text1 = "டம்ப்டி"
text2 = "இன்றைய காவிரி பிரச்னையில், சில கேள்விகள் எழுகின்றன. அவற்றுக்குத் தீர்வு என்ன? 1. மேக்கேதாட்டு அணையை கட்ட தமிழ் நாடு அரசு தடை விதிக்க முடியுமா?"
text3 = "சென்னையில் (54 பேருக்கு டெங்கு தினமும் 100 இடங்களில் மருத்துவ முகாம்கள்"

async def test():
    print("Testing text1:", text1)
    r1 = await llm_translator.translate(text1, source_lang="ta")
    print("Result 1:", r1.translated_text)
    
    print("\nTesting text2:", text2)
    r2 = await llm_translator.translate_long_text(text2, source_lang="ta")
    print("Result 2:", r2.translated_text)

    print("\nTesting text3:", text3)
    r3 = await llm_translator.translate(text3, source_lang="ta")
    print("Result 3:", r3.translated_text)

if __name__ == "__main__":
    asyncio.run(test())
