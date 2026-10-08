"""Validate JSON, cell structure and Python syntax without executing network cells."""
import ast
import json
from pathlib import Path

book = json.loads(Path('notebooks/train_in_colab.ipynb').read_text())
assert book['nbformat'] == 4 and book['cells']
for cell in book['cells']:
    assert cell['cell_type'] in ('markdown', 'code') and isinstance(cell['source'], list)
    if cell['cell_type'] == 'code':
        assert cell['outputs'] == [] and cell['execution_count'] is None
        source = ''.join(line for line in cell['source'] if not line.lstrip().startswith(('!', '%')))
        ast.parse(source)
print(f"PASS: {len(book['cells'])} cells; structure and Python syntax only, not Colab execution")
