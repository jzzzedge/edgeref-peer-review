"""论文解析模块 — 从 PDF/DOCX/TXT 中提取文本并初步识别章节."""

import os
import re
from typing import Dict, List

from .language_detector import detect_manuscript_language

import pypdf
import docx


_SECTION_PATTERNS = [
    (r"^\s*(?:Abstract|ABSTRACT|摘要)\s*$", "Abstract"),
    (r"^\s*(?:Introduction|INTRODUCTION|背景|引言)\s*$", "Introduction"),
    (r"^\s*(?:Background|BACKGROUND|研究背景)\s*$", "Introduction"),
    (r"^\s*(?:Methods?|METHODS?|Methodology|METHODOLOGY)\s*$", "Methods"),
    (r"^\s*(?:Materials\s+(?:and|&)\s+Methods?)\s*$", "Methods"),
    (r"^\s*(?:实验方法|材料与方法|方法)\s*$", "Methods"),
    (r"^\s*(?:Results?|RESULTS?|结果)\s*$", "Results"),
    (r"^\s*(?:Discussion|DISCUSSION|讨论)\s*$", "Discussion"),
    (r"^\s*(?:Conclusions?|CONCLUSIONS?|Concluding\s+remarks?)\s*$", "Conclusion"),
    (r"^\s*(?:结论|总结)\s*$", "Conclusion"),
    (r"^\s*(?:References|REFERENCES|Bibliography|BIBLIOGRAPHY)\s*$", "References"),
    (r"^\s*(?:参考文献)\s*$", "References"),
]

def extract_text_from_pdf(uploaded_file) -> str:
    """从 PDF 文件中提取文本。失败时返回空字符串。"""
    try:
        reader = pypdf.PdfReader(uploaded_file)
        pages = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                pages.append(t)
        return "\n".join(pages)
    except Exception:
        return ""

def extract_text_from_docx(uploaded_file) -> str:
    """从 DOCX 文件中提取文本。失败或空文档时返回空字符串。"""
    try:
        doc = docx.Document(uploaded_file)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs)
    except Exception:
        return ""

def extract_text_from_txt(uploaded_file) -> str:
    """从 TXT 文件中提取文本（自动探测编码）. """
    raw = uploaded_file.read()
    uploaded_file.seek(0)
    if not raw:
        return ""
    for encoding in ("utf-8", "gbk", "gb2312", "latin-1"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1", errors="replace")


def _detect_sections(full_text: str) -> Dict[str, str]:
    """按标题关键词简单匹配，将全文切分为各章节."""
    if not full_text:
        return {}
    lines = full_text.split("\n")
    matches: List[tuple[int, str]] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        for pattern, section_name in _SECTION_PATTERNS:
            if re.match(pattern, stripped):
                matches.append((i, section_name))
                break

    if not matches:
        txt = full_text[:2000] if full_text else ""
        return {"Title": txt} if txt.strip() else {}

    sections = {}
    first_idx = matches[0][0]

    title_text = "\n".join(lines[:first_idx]).strip()
    if title_text:
        sections["Title"] = title_text

    for idx, (start, name) in enumerate(matches):
        end = matches[idx + 1][0] if idx + 1 < len(matches) else len(lines)
        content = "\n".join(lines[start:end]).strip()
        sections[name] = content

    return sections


def _count_words(text: str) -> int:
    """统计词数（中英文混合场景）. """
    english_words = len(re.findall(r"[a-zA-Z]+", text))
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    return english_words + chinese_chars


def parse_manuscript(uploaded_file) -> Dict:
    """解析论文文件，返回结构化信息。

    Args:
        uploaded_file: Streamlit UploadedFile 对象。

    Returns:
        dict，包含 file_name, file_type, full_text, char_count,
        word_count, detected_sections, parse_status, error_message,
        extracted_text_available.
    """
    file_name = uploaded_file.name
    _, ext = os.path.splitext(file_name)
    file_type = ext.lstrip(".").lower()

    # 空文件检查
    if uploaded_file.size == 0:
        return {
            "file_name": file_name,
            "file_type": file_type,
            "full_text": "",
            "char_count": 0,
            "word_count": 0,
            "detected_sections": {},
            "parse_status": "failed",
            "error_message": "空文件：上传的文件不包含任何数据。",
            "extracted_text_available": False,
            "detected_language": "Unknown",
            "output_language": "English",
        }

    # 提取文本（含异常保护）
    try:
        if file_type == "pdf":
            full_text = extract_text_from_pdf(uploaded_file)
        elif file_type == "docx":
            full_text = extract_text_from_docx(uploaded_file)
        elif file_type == "txt":
            full_text = extract_text_from_txt(uploaded_file)
        else:
            full_text = ""
    except Exception as exc:
        return {
            "file_name": file_name,
            "file_type": file_type,
            "full_text": "",
            "char_count": 0,
            "word_count": 0,
            "detected_sections": {},
            "parse_status": "failed",
            "error_message": f"文件解析异常: {exc}",
            "extracted_text_available": False,
            "detected_language": "Unknown",
            "output_language": "English",
        }

    sections = _detect_sections(full_text)
    char_count = len(full_text)
    word_count = _count_words(full_text)

    text_available = bool(full_text.strip())
    lang_result = detect_manuscript_language(full_text) if text_available else {
        "language": "Unknown",
        "chinese_ratio": 0.0,
        "english_ratio": 0.0,
        "output_language": "English",
    }
    parse_status = "success" if text_available else "failed"
    error_message = ""
    if not text_available:
        if file_type == "pdf":
            error_message = "PDF 文本提取结果为空。可能是扫描版 PDF（图片格式），无法提取文字。"
        elif file_type == "docx":
            error_message = "DOCX 文件未包含可提取的文本内容。"
        elif file_type == "txt":
            error_message = "TXT 文件解码后内容为空。"
        else:
            error_message = f"不支持的文件格式 (.{file_type}) 或无文本内容。"

    return {
        "file_name": file_name,
        "file_type": file_type,
        "full_text": full_text,
        "char_count": char_count,
        "word_count": word_count,
        "detected_sections": sections,
        "parse_status": parse_status,
        "error_message": error_message,
        "extracted_text_available": text_available,
        "detected_language": lang_result["language"],
        "output_language": lang_result["output_language"],
    }
