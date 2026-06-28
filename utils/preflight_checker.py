#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""投稿前自动质检 / Preflight Check 模块."""

from typing import Any, Dict, List, Optional


def check_manuscript_completeness(parsed_manuscript: Optional[Dict[str, Any]]) -> List[Dict[str, str]]:
    """检查论文完整性和章节覆盖情况."""
    results = []
    if parsed_manuscript and parsed_manuscript.get("parse_status") == "failed":
        err = parsed_manuscript.get("error_message", "解析失败")
        results.append({"check": "论文解析状态", "status": "Fail", "detail": f"论文解析失败: {err}"})
        return results
    sections = dict(parsed_manuscript.get("detected_sections", {}) or {}) if parsed_manuscript else {}
    full_text = (parsed_manuscript or {}).get("full_text", "") or ""
    char_count = (parsed_manuscript or {}).get("char_count", 0) or 0

    text_ok = bool(full_text.strip()) if full_text else False
    results.append({
        "check": "正文提取",
        "status": "Pass" if text_ok else "Fail",
        "detail": f"成功提取 {char_count:,} 字符" if text_ok else "未能提取到正文内容",
    })

    char_ok = char_count >= 500
    results.append({
        "check": "字符数",
        "status": "Pass" if char_ok else "Warning",
        "detail": f"共 {char_count:,} 字符" + ("" if char_ok else "，建议不少于 500 字符"),
    })

    section_names = {
        "Abstract": "Abstract/摘要", "Introduction": "Introduction/引言",
        "Methods": "Methods/方法", "Results": "Results/结果",
        "Discussion": "Discussion/讨论", "References": "References/参考文献",
    }
    for sec_key, sec_label in section_names.items():
        found = sec_key in sections
        if not found:
            for k in sections:
                if k.lower().startswith(sec_key.lower()):
                    found = True
                    break
        results.append({
            "check": sec_label,
            "status": "Pass" if found else "Warning",
            "detail": "已检测到" if found else "未检测到",
        })

    return results


def check_source_data_status(parsed_source_data: Optional[List[Dict[str, Any]]]) -> List[Dict[str, str]]:
    """检查 Source Data 上传与解析情况."""
    results = []
    uploaded = bool(parsed_source_data)

    results.append({
        "check": "Source Data 上传",
        "status": "Pass" if uploaded else "Warning",
        "detail": f"已上传 {len(parsed_source_data)} 个数据文件" if uploaded else "未上传 Source Data",
    })

    if not uploaded:
        return results

    success_count = sum(1 for item in parsed_source_data if item.get("parse_status") == "success")
    results.append({
        "check": "成功解析",
        "status": "Pass" if success_count > 0 else "Fail",
        "detail": f"成功解析 {success_count}/{len(parsed_source_data)} 个文件",
    })

    fail_count = sum(1 for item in parsed_source_data if item.get("parse_status") != "success")
    total = len(parsed_source_data)
    if fail_count > 0:
        status = "Fail" if fail_count == total else "Warning"
        results.append({
            "check": "解析失败",
            "status": status,
            "detail": f"有 {fail_count}/{total} 个文件解析失败",
        })

    total_mv = 0
    for item in parsed_source_data:
        targets = item.get("parsed_tables", []) if item.get("file_type") == "zip" else [item]
        for table in targets:
            mv = table.get("missing_values_summary", {}) or {}
            for v in mv.values():
                try:
                    total_mv += int(v)
                except (TypeError, ValueError):
                    pass

    results.append({
        "check": "缺失值",
        "status": "Pass" if total_mv == 0 else "Warning",
        "detail": "未检测到缺失值" if total_mv == 0 else f"检测到 {total_mv} 个缺失值",
    })

    low_rows = []
    for item in parsed_source_data:
        targets = item.get("parsed_tables", []) if item.get("file_type") == "zip" else [item]
        for table in targets:
            if table.get("parse_status") == "success" and (table.get("row_count", 0) or 0) < 10:
                low_rows.append(table.get("file_name", "?"))
    if low_rows:
        results.append({
            "check": "表格行数",
            "status": "Warning",
            "detail": f"以下表格行数过少（<10）：{', '.join(low_rows)}",
        })

    for item in parsed_source_data:
        if item.get("file_type") == "zip" and item.get("parse_status") == "success":
            tables = item.get("parsed_tables", [])
            if not tables:
                results.append({
                    "check": f"ZIP({item.get('file_name', '?')})",
                    "status": "Warning",
                    "detail": "ZIP 内未发现可解析的 CSV/XLSX 表格",
                })

    return results


def calculate_risk_score(manuscript_checks, source_data_checks) -> int:
    """计算综合风险分数 (0-100)."""
    score = 0
    total = 0
    for c in manuscript_checks:
        total += 1
        if c["status"] == "Fail":
            score += 25
        elif c["status"] == "Warning":
            score += 15
    for c in source_data_checks:
        total += 1
        if c["status"] == "Fail":
            score += 20
        elif c["status"] == "Warning":
            score += 10
    if total == 0:
        return 0
    return min(100, score)


def run_preflight_check(
    parsed_manuscript: Optional[Dict[str, Any]] = None,
    parsed_source_data: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """运行投稿前自动质检，返回包含所有检查结果和风险评分的字典."""
    if not parsed_manuscript:
        return {
            "overall_status": "High Risk",
            "risk_score": 100,
            "manuscript_checks": [],
            "source_data_checks": [],
            "key_warnings": ["未上传论文文件"],
            "suggested_actions": ["请先上传论文文件"],
        }

    mc = check_manuscript_completeness(parsed_manuscript)
    sc = check_source_data_status(parsed_source_data)
    score = calculate_risk_score(mc, sc)

    fails = sum(1 for c in mc + sc if c["status"] == "Fail")
    warns = sum(1 for c in mc + sc if c["status"] == "Warning")

    if fails > 0:
        overall = "High Risk"
    elif warns > 0:
        overall = "Warning"
    else:
        overall = "Pass"

    key_warnings = [c.get("detail", "") for c in mc + sc if c.get("status") != "Pass"]

    suggested = []
    for c in mc:
        if c["status"] == "Fail":
            suggested.append(f"修复论文问题：{c.get('detail', '')}")
    for c in sc:
        if c["status"] == "Fail":
            suggested.append(f"修复源数据问题：{c.get('detail', '')}")
    if warns > 0:
        suggested.append("检查以上警告项，确保不影响投稿质量")
    if overall == "Pass":
        suggested.append("稿件整体状态良好，建议完成最终排版和语言检查后投稿")

    return {
        "overall_status": overall,
        "risk_score": score,
        "manuscript_checks": mc,
        "source_data_checks": sc,
        "key_warnings": key_warnings,
        "suggested_actions": suggested,
    }


def build_preflight_summary(preflight_result: Optional[Dict[str, Any]]) -> str:
    """构建简短的质检摘要，用于嵌入 Prompt 或报告中（节省 token）."""
    if not preflight_result:
        return ""

    lines = []
    lines.append(f"投稿前质检状态: {preflight_result['overall_status']}")
    lines.append(f"风险评分: {preflight_result['risk_score']}/100")
    if preflight_result["key_warnings"]:
        lines.append("警告项:")
        for w in preflight_result["key_warnings"][:3]:
            lines.append(f"- {w}")
    return "\n".join(lines)
