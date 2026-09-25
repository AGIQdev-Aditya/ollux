"""
ollux — Attachment & Document Processing Handler
Extracts text from PDFs, encodes vision images for multimodal models,
and formats large text chips.
"""

import os
import base64
from typing import Dict, Any, Optional


MAX_FILE_SIZE = 15 * 1024 * 1024  # 15MB safety limit to protect RAM budget


def process_file(filepath: str) -> Optional[Dict[str, Any]]:
    """Parse a file by path and return structured attachment data."""
    if not os.path.exists(filepath):
        return None

    filename = os.path.basename(filepath)

    if os.path.isdir(filepath):
        return {
            "name": filename,
            "type": "error",
            "error": f"'{filename}' is a directory. Please select or drag individual files."
        }

    ext = os.path.splitext(filename)[1].lower()
    size_bytes = os.path.getsize(filepath)
    size_str = f"{size_bytes / 1024:.1f} KB" if size_bytes < 1024 * 1024 else f"{size_bytes / (1024*1024):.1f} MB"

    if size_bytes > MAX_FILE_SIZE:
        return {
            "name": filename,
            "type": "error",
            "error": f"File exceeds maximum allowed size (15MB): {size_str}"
        }

    # 1. Images (JPEG, PNG, WEBP)
    if ext in [".png", ".jpg", ".jpeg", ".webp"]:
        try:
            with open(filepath, "rb") as f:
                b64_data = base64.b64encode(f.read()).decode("utf-8")
            return {
                "name": filename,
                "type": "image",
                "size": size_str,
                "path": filepath,
                "base64": b64_data
            }
        except Exception as e:
            return {"name": filename, "type": "error", "error": str(e)}

    # 2. PDF Documents
    elif ext == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(filepath)
            pages_text = []
            for i, page in enumerate(reader.pages):
                text = page.extract_text() or ""
                if text.strip():
                    pages_text.append(f"--- Page {i+1} ---\n{text.strip()}")
            
            full_text = "\n\n".join(pages_text)
            return {
                "name": filename,
                "type": "pdf",
                "size": size_str,
                "path": filepath,
                "pages": len(reader.pages),
                "text": full_text
            }
        except Exception as e:
            return {"name": filename, "type": "error", "error": str(e)}

    # 3. Plain Text / Markdown / Code files
    else:
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            return {
                "name": filename,
                "type": "text",
                "size": size_str,
                "path": filepath,
                "text": content
            }
        except Exception as e:
            return {"name": filename, "type": "error", "error": str(e)}
