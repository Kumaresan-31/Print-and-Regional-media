import sys
sys.path.insert(0, 'backend')
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from PIL import Image
from harvester.news.news_cropper import generate_news_crop, get_or_create_boxes
from harvester.news.pdf_search_index import pdf_search_index

# Test 1: Loksatta with 'rainfall'
lok_doc = pdf_search_index._memory_index.get('loksatta:2026-09-19')
print('=== LOKSATTA ===')
lok_snap = Path(lok_doc['pages'][0]['snapshot_path'])
print('Snapshot path:', lok_snap, 'exists:', lok_snap.exists())
boxes = get_or_create_boxes(lok_snap)
print('Total boxes:', len(boxes))
# Let's see how many boxes matched 'rainfall' or 'heavy'
for b in boxes:
    txt = b.get('text', '')
    if any(w in txt.lower() for w in ['rainfall', 'heavy', 'warning', 'collapse']):
        print('  matched box:', txt, b.get('box'))

crop_file = generate_news_crop(lok_snap, 'rainfall')
crop_img = Image.open(crop_file)
print('Generated crop file:', crop_file, 'size:', crop_img.size)

# Test 2: Financial Express with 'stocks'
fe_doc = pdf_search_index._memory_index.get('financial_express:2026-09-19')
print('\n=== FINANCIAL EXPRESS ===')
fe_snap = Path(fe_doc['pages'][0]['snapshot_path'])
print('Snapshot path:', fe_snap, 'exists:', fe_snap.exists())
boxes_fe = get_or_create_boxes(fe_snap)
print('Total boxes:', len(boxes_fe))
for b in boxes_fe:
    txt = b.get('text', '')
    if any(w in txt.lower() for w in ['stocks', 'jefferies', 'textile']):
        print('  matched box:', txt, b.get('box'))

crop_file_fe = generate_news_crop(fe_snap, 'stocks')
crop_img_fe = Image.open(crop_file_fe)
print('Generated crop file:', crop_file_fe, 'size:', crop_img_fe.size)
