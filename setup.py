import sys
import subprocess

REQUIRED_PYTHON = (3, 9)
PACKAGES = ["feedparser", "spacy", "pyahocorasick"]
SPACY_MODEL = "pt_core_news_sm"


def check_python():
    v = sys.version_info[:2]
    if v < REQUIRED_PYTHON:
        print(f"[FAIL] Python {REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]}+ required, found {v[0]}.{v[1]}")
        sys.exit(1)
    print(f"[OK] Python {v[0]}.{v[1]}")


def install_packages():
    for pkg in PACKAGES:
        print(f"[...] installing {pkg}")
        r = subprocess.run([sys.executable, "-m", "pip", "install", pkg], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"[FAIL] {pkg}\n{r.stderr}")
            sys.exit(1)
        print(f"[OK] {pkg}")


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
