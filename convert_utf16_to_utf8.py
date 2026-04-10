# convert_utf16_to_utf8.py

import sys
from pathlib import Path

def convert_utf16_to_utf8(input_path, output_path):
    with open(input_path, 'rb') as f:
        raw = f.read()
    # Try to decode as utf-16 (with BOM)
    try:
        text = raw.decode('utf-16')
    except UnicodeDecodeError:
        # Try little endian
        text = raw.decode('utf-16-le')
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(text)

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print('Usage: python convert_utf16_to_utf8.py <input_file> <output_file>')
        sys.exit(1)
    convert_utf16_to_utf8(sys.argv[1], sys.argv[2])
