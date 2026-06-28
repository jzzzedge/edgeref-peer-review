"""Source data 解析模块：读取 CSV/XLSX/ZIP 并生成基础数据概况。"""

import io
import os
import zipfile
from typing import Any, Dict, List, Optional

import pandas as pd


def _get_file_size(file_obj) -> int:
    """兼容 Streamlit UploadedFile 和 BytesIO 的文件大小读取。"""
    size = getattr(file_obj, "size", None)
    if size is not None:
        return int(size)

    current_pos = file_obj.tell()
    file_obj.seek(0, io.SEEK_END)
    size = file_obj.tell()
    file_obj.seek(current_pos)
    return int(size)


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.2f} MB"


def _safe_file_name(file_obj, default: str = "unknown") -> str:
    return getattr(file_obj, "name", default)


def _get_numeric_summary(df: pd.DataFrame) -> Dict[str, Dict[str, float]]:
    numeric_df = df.select_dtypes(include=["number"])
    if numeric_df.empty:
        return {}

    summary = numeric_df.describe().to_dict()
    clean_summary: Dict[str, Dict[str, float]] = {}
    for col, stats in summary.items():
        clean_summary[str(col)] = {
            str(k): round(float(v), 4) for k, v in stats.items() if pd.notna(v)
        }
    return clean_summary


def _get_missing_summary(df: pd.DataFrame) -> Dict[str, int]:
    missing = df.isna().sum()
    return {str(col): int(count) for col, count in missing.items() if int(count) > 0}


def _build_parse_result(
    file_name: str,
    file_type: str,
    file_size: int,
    sheet_name: Optional[str] = None,
    df: Optional[pd.DataFrame] = None,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "file_name": file_name,
        "file_type": file_type,
        "file_size": _format_size(file_size),
        "sheet_name": sheet_name,
    }

    if error or df is None:
        result.update(
            {
                "parse_status": "error",
                "error_message": error or "No dataframe parsed.",
                "row_count": 0,
                "column_count": 0,
                "columns": [],
                "missing_values_summary": {},
                "numeric_summary": {},
            }
        )
        return result

    result.update(
        {
            "parse_status": "success",
            "error_message": "",
            "row_count": int(len(df)),
            "column_count": int(len(df.columns)),
            "columns": [str(col) for col in df.columns],
            "missing_values_summary": _get_missing_summary(df),
            "numeric_summary": _get_numeric_summary(df),
        }
    )
    return result


def parse_csv(uploaded_file) -> Dict[str, Any]:
    """解析 CSV 文件，返回结构化信息。"""
    file_name = _safe_file_name(uploaded_file)
    file_size = _get_file_size(uploaded_file)

    try:
        uploaded_file.seek(0)
        try:
            df = pd.read_csv(uploaded_file)
        except pd.errors.EmptyDataError:
            uploaded_file.seek(0)
            return _build_parse_result(
                file_name,
                "csv",
                file_size,
                error="CSV 文件为空或没有可读取的数据。",
            )
        except UnicodeDecodeError:
            uploaded_file.seek(0)
            df = pd.read_csv(uploaded_file, encoding="gbk")
        uploaded_file.seek(0)
        if df.empty and len(df.columns) == 0:
            return _build_parse_result(
                file_name,
                "csv",
                file_size,
                error="CSV 文件为空或没有可读取的数据。",
            )
        return _build_parse_result(file_name, "csv", file_size, df=df)
    except Exception as exc:  # noqa: BLE001
        try:
            uploaded_file.seek(0)
        except Exception:  # noqa: BLE001
            pass
        return _build_parse_result(file_name, "csv", file_size, error=str(exc))


def parse_xlsx(uploaded_file) -> List[Dict[str, Any]]:
    """解析 XLSX 文件，按 sheet 返回结构化信息列表。"""
    file_name = _safe_file_name(uploaded_file)
    file_size = _get_file_size(uploaded_file)

    try:
        uploaded_file.seek(0)
        raw = uploaded_file.read()
        uploaded_file.seek(0)
        workbook = pd.ExcelFile(io.BytesIO(raw), engine="openpyxl")
    except Exception as exc:  # noqa: BLE001
        return [_build_parse_result(file_name, "xlsx", file_size, error=str(exc))]

    results: List[Dict[str, Any]] = []
    for sheet_name in workbook.sheet_names:
        try:
            df = pd.read_excel(io.BytesIO(raw), sheet_name=sheet_name, engine="openpyxl")
            results.append(
                _build_parse_result(
                    file_name=file_name,
                    file_type="xlsx",
                    file_size=file_size,
                    sheet_name=sheet_name,
                    df=df,
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                _build_parse_result(
                    file_name=file_name,
                    file_type="xlsx",
                    file_size=file_size,
                    sheet_name=sheet_name,
                    error=str(exc),
                )
            )
    return results


def _bytes_to_named_file(content: bytes, name: str) -> io.BytesIO:
    file_obj = io.BytesIO(content)
    file_obj.name = name
    file_obj.size = len(content)
    return file_obj


def parse_zip(uploaded_file) -> Dict[str, Any]:
    """解析 ZIP：列出内部文件，并尝试解析其中的 CSV/XLSX。"""
    file_name = _safe_file_name(uploaded_file)
    file_size = _get_file_size(uploaded_file)
    result: Dict[str, Any] = {
        "file_name": file_name,
        "file_type": "zip",
        "file_size": _format_size(file_size),
        "sheet_name": None,
        "parse_status": "success",
        "error_message": "",
        "inner_files": [],
        "parsed_tables": [],
    }

    try:
        uploaded_file.seek(0)
        raw = uploaded_file.read()
        uploaded_file.seek(0)

        with zipfile.ZipFile(io.BytesIO(raw)) as zip_file:
            for info in zip_file.infolist():
                if info.is_dir():
                    continue

                result["inner_files"].append(
                    {
                        "name": info.filename,
                        "size": _format_size(info.file_size),
                        "compressed_size": _format_size(info.compress_size),
                    }
                )

                _, ext = os.path.splitext(info.filename)
                ext = ext.lower().lstrip(".")
                if ext not in {"csv", "xlsx"}:
                    continue

                content = zip_file.read(info.filename)
                inner_file = _bytes_to_named_file(content, info.filename)
                if ext == "csv":
                    result["parsed_tables"].append(parse_csv(inner_file))
                elif ext == "xlsx":
                    result["parsed_tables"].extend(parse_xlsx(inner_file))
    except zipfile.BadZipFile:
        result["parse_status"] = "error"
        result["error_message"] = "ZIP 文件损坏，无法解压。"
    except Exception as exc:
        result["parse_status"] = "error"
        result["error_message"] = f"ZIP 解析失败: {exc}"

    if result["parse_status"] == "success" and not result["parsed_tables"]:
        if result["inner_files"]:
            result["error_message"] = "ZIP 内未发现可解析的 CSV/XLSX 表格。"

    return result


def parse_source_data(uploaded_files: List) -> List[Dict[str, Any]]:
    """批量解析 source data 文件。"""
    all_results: List[Dict[str, Any]] = []

    for uploaded_file in uploaded_files or []:
        _, ext = os.path.splitext(_safe_file_name(uploaded_file))
        file_type = ext.lower().lstrip(".")

        if file_type == "csv":
            all_results.append(parse_csv(uploaded_file))
        elif file_type == "xlsx":
            all_results.extend(parse_xlsx(uploaded_file))
        elif file_type == "zip":
            all_results.append(parse_zip(uploaded_file))
        else:
            all_results.append(
                _build_parse_result(
                    file_name=_safe_file_name(uploaded_file),
                    file_type=file_type or "unknown",
                    file_size=_get_file_size(uploaded_file),
                    error="Unsupported file type.",
                )
            )

    return all_results
