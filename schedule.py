import json
from pathlib import Path
_DATA = Path(__file__).with_name('schedule_data.json')
with _DATA.open(encoding='utf-8') as f:
    STATIC_SCHEDULE = json.load(f)