from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import load_config


root = Path(__file__).resolve().parents[1]
config = load_config(root)

print("Configuração carregada com sucesso.")
print(f"Fonte 1: {config.sources[0]}")
print(f"Fonte 2: {config.sources[1]}")
print(f"Fonte 3: {config.sources[2]}")
