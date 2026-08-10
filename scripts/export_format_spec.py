import sys
sys.path.insert(0, '.')
from workbench.backend.services.format_spec import generate_format_spec_md
text = generate_format_spec_md()
with open('docs/specguard-yaml-format-spec.md', 'w', encoding='utf-8') as f:
    f.write(text)
print(f'OK: wrote {len(text)} chars')
