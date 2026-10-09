"""Aggregate receipts only; never dump raw work files into Actions logs."""
import json
from pathlib import Path

print('# Yanjaro research evidence\n')
for name in ('probe', 'prepare', 'extract', 'metrics'):
    path = Path('artifacts') / f'{name}.json'
    print(f'## {name}\n')
    if path.exists():
        print('```json\n'+json.dumps(json.loads(path.read_text()), indent=2)+'\n```\n')
    else:
        print('NOT RUN / no artifact\n')
print('Synthetic tests are not real training. No Render deployment or Yandex ID mapping.')
