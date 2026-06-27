from __future__ import annotations

from backend.app.sample_pdf import ensure_default_sample_pdf


if __name__ == "__main__":
    path = ensure_default_sample_pdf()
    print(path)

