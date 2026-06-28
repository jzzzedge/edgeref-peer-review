"""文件处理模块 — 获取上传文件的基本信息."""

import os
from typing import List, Dict


def get_file_info(uploaded_file) -> Dict[str, str]:
    """提取单个上传文件的基本信息.

    Args:
        uploaded_file: Streamlit UploadedFile 对象.

    Returns:
        包含 name, type, size 的字典.
    """
    # 确定文件类型后缀
    _, ext = os.path.splitext(uploaded_file.name)
    file_type = ext.lstrip(".").lower() if ext else "unknown"

    # 文件大小（KB 或 MB）
    size_bytes = uploaded_file.size or 0
    if size_bytes < 1024:
        size_str = f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        size_str = f"{size_bytes / 1024:.1f} KB"
    else:
        size_str = f"{size_bytes / (1024 * 1024):.2f} MB"

    return {
        "name": uploaded_file.name,
        "type": file_type,
        "size": size_str,
    }


def get_files_summary(uploaded_files: List) -> List[Dict[str, str]]:
    """批量获取上传文件的信息."""
    return [get_file_info(f) for f in uploaded_files]
