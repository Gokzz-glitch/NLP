import sys
from pathlib import Path
pdf_path = Path('gpu.md.pdf')
text_parts = []
reader = None
err_msgs = []
for mod in ('pypdf','PyPDF2'):
    try:
        m = __import__(mod)
        reader = m.PdfReader(str(pdf_path))
        break
    except Exception as e:
        err_msgs.append(f"{mod}: {e}")
if reader is None:
    print('IMPORT_FAIL')
    print('\n'.join(err_msgs))
    sys.exit(1)
for page in reader.pages:
    try:
        text_parts.append(page.extract_text() or '')
    except Exception as e:
        text_parts.append(f"\n[EXTRACT_ERROR]{e}\n")
text = '\n'.join(text_parts)
Path('tmp_gpu_text.txt').write_text(text, encoding='utf-8')
print('EXTRACT_OK')
print(f'CHARS={len(text)} PAGES={len(reader.pages)}')
print(text[:8000])
