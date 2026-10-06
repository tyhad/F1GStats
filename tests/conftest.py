import sys
from pathlib import Path

# Supaya `import fetch_f1_data` jalan tanpa harus `pip install -e .`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
