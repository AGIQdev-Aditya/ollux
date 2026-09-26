"""
ollux — Attachment & Document Processing Handler
Extracts text from PDFs, encodes vision images for multimodal models,
and formats large text chips.
"""

import os
import stat
import base64
from typing import Dict, Any, Optional

MAX_FILE_SIZE = 15 * 1024 * 1024  # 15MB safety limit to protect RAM budget
MAX_TEXT_CHARS = 250_000  # ~60,000 tokens maximum text budget


def process_file(filepath: str) -> Optional[Dict[str, Any]]:
    """Parse a file by path and return structured attachment data."""
    if not filepath or not isinstance(filepath, str):
        return None

    # Canonicalize and resolve symlinks
    real_path = os.path.realpath(os.path.expanduser(filepath))
    if not os.path.exists(real_path):
        return None

    filename = os.path.basename(real_path)

    # Validate file type using stat to block devices, sockets, and FIFOs
    try:
        st = os.stat(real_path)
    except Exception as e:
        return {"name": filename, "type": "error", "error": f"Stat failure: {e}"}

    if stat.S_ISDIR(st.st_mode):
        return {
            "name": filename,
            "type": "error",
            "error": f"'{filename}' is a directory. Please select or drag individual files."
        }

    if not stat.S_ISREG(st.st_mode):
        return {
            "name": filename,
            "type": "error",
            "error": f"'{filename}' is a special device file or named pipe. Only regular files are supported."
        }

    size_bytes = st.st_size
    size_str = f"{size_bytes / 1024:.1f} KB" if size_bytes < 1024 * 1024 else f"{size_bytes / (1024*1024):.1f} MB"

    if size_bytes > MAX_FILE_SIZE:
        return {
            "name": filename,
            "type": "error",
            "error": f"File exceeds maximum allowed size (15MB): {size_str}"
        }

    ext = os.path.splitext(filename)[1].lower()

    # 1. Images (JPEG, PNG, WEBP)
    if ext in [".png", ".jpg", ".jpeg", ".webp"]:
        try:
            with open(real_path, "rb") as f:
                b64_data = base64.b64encode(f.read()).decode("utf-8")
            return {
                "name": filename,
                "type": "image",
                "size": size_str,
                "path": real_path,
                "base64": b64_data
            }
        except Exception as e:
            return {"name": filename, "type": "error", "error": str(e)}

    # 2. PDF Documents
    elif ext == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(real_path)
            pages_text = []
            for i, page in enumerate(reader.pages):
                text = page.extract_text() or ""
                if text.strip():
                    pages_text.append(f"--- Page {i+1} ---\n{text.strip()}")

            full_text = "\n\n".join(pages_text)
            if len(full_text) > MAX_TEXT_CHARS:
                full_text = full_text[:MAX_TEXT_CHARS] + f"\n\n[... Truncated to 250,000 characters to fit memory ...]"

            return {
                "name": filename,
                "type": "pdf",
                "size": size_str,
                "path": real_path,
                "pages": len(reader.pages),
                "text": full_text
            }
        except Exception as e:
            return {"name": filename, "type": "error", "error": str(e)}

    # 3. Plain Text / Markdown / Code files
    else:
        try:
            with open(real_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(MAX_TEXT_CHARS + 1024)
            if len(content) > MAX_TEXT_CHARS:
                content = content[:MAX_TEXT_CHARS] + f"\n\n[... Truncated to 250,000 characters to protect RAM ...]"

            return {
                "name": filename,
                "type": "text",
                "size": size_str,
                "path": real_path,
                "text": content
            }
        except Exception as e:
            return {"name": filename, "type": "error", "error": str(e)}
