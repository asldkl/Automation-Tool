import os, sys
ROOT = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(ROOT, "template_capture.py")

with open(PATH, 'r', encoding='utf-8') as f:
    content = f.read()

# Find the line numbers
lines = content.split('\n')
start = end = None
for i, line in enumerate(lines):
    if 'def _image_match_upload(self):' in line:
        start = i
    if start is not None and i > start and line.strip().startswith('def '):
        end = i
        break

print(f"Lines {start+1} to {end}")
if start is None or end is None:
    print("ERROR: could not find function boundaries")
    sys.exit(1)

# Read the new code from a separate file
new_code_file = os.path.join(ROOT, "_new_match_code.py")
with open(new_code_file, 'r', encoding='utf-8') as f:
    new_code = f.read()

# Replace
new_lines = lines[:start] + [new_code] + lines[end:]
with open(PATH, 'w', encoding='utf-8') as f:
    f.write('\n'.join(new_lines))

print("OK")
