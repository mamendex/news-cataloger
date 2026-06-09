import sys
import subprocess
import os

REQUIRED_PYTHON = (3, 9)
SPACY_MODEL = "pt_core_news_sm"
REQUIREMENTS_FILE = os.path.join(os.path.dirname(__file__), "requirements.txt")


def check_python():
    v = sys.version_info[:2]
    if v < REQUIRED_PYTHON:
        print(f"[FAIL] Python {REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]}+ required, found {v[0]}.{v[1]}")
        sys.exit(1)
    print(f"[OK] Python {v[0]}.{v[1]}")


def install_packages():
    print(f"[...] installing dependencies from requirements.txt")
    r = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", REQUIREMENTS_FILE],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"[FAIL] pip install\n{r.stderr}")
        sys.exit(1)
    print(f"[OK] all dependencies installed")


def install_spacy_model():
    print(f"[...] downloading spaCy model {SPACY_MODEL}")
    r = subprocess.run(
        [sys.executable, "-m", "spacy", "download", SPACY_MODEL],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"[FAIL] spaCy model\n{r.stderr}")
        sys.exit(1)
    print(f"[OK] spaCy model {SPACY_MODEL}")


if __name__ == "__main__":
    print("=== Setup: news-cataloger ===")
    check_python()
    install_packages()
    install_spacy_model()
    print("\nSetup complete. Run 'python coordinator.py' to start cataloging.")
