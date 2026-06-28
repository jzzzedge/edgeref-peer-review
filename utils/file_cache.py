"""Session-only uploaded-file signature helpers.

These helpers intentionally do not persist uploaded file content to disk. For UX,
we use a lightweight signature based on file metadata available from Streamlit
(name, size, and type) so switching review modes or editing journal fields does
not force expensive file reads on every rerun.
"""

import hashlib
from typing import List, Optional


def _safe_file_type(uploaded_file) -> str:
    return getattr(uploaded_file, "type", "") or ""


def get_uploaded_file_signature(uploaded_file) -> Optional[str]:
    """Return a lightweight signature for one uploaded file.

    The signature is session-only and is not meant to be a cryptographic file
    integrity guarantee. It is used to detect normal user changes such as
    replacing a file, adding files, or removing files without repeatedly reading
    large file contents during Streamlit reruns.
    """
    if uploaded_file is None:
        return None
    name = getattr(uploaded_file, "name", "") or ""
    size = str(getattr(uploaded_file, "size", 0) or 0)
    file_type = _safe_file_type(uploaded_file)
    raw = f"{name}|{size}|{file_type}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def get_uploaded_files_signature(uploaded_files: List) -> Optional[str]:
    """Return a combined lightweight signature for multiple uploaded files."""
    if not uploaded_files:
        return None
    sigs = []
    for uploaded_file in uploaded_files:
        sig = get_uploaded_file_signature(uploaded_file)
        if sig:
            sigs.append(sig)
    if not sigs:
        return None
    raw = ",".join(sorted(sigs))
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def has_manuscript_changed(uploaded_file, previous_signature: Optional[str]) -> bool:
    """Check whether the manuscript upload differs from the processed version."""
    return get_uploaded_file_signature(uploaded_file) != previous_signature


def has_source_data_changed(uploaded_files: List, previous_signature: Optional[str]) -> bool:
    """Check whether the source-data upload set differs from the processed version."""
    return get_uploaded_files_signature(uploaded_files) != previous_signature
