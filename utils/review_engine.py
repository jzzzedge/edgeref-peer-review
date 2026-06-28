"""模拟审稿引擎 - 生成结构化 Markdown 报告. (升级版: 9段 peer review 结构)"""

from typing import Optional, List, Dict, Any

# Mock 报告只基于上传文件概况和 Preflight Check 生成，不编造论文证据。

# -- helper functions --

def _build_file_table(files):
    if not files:
        return "_(无上传文件)_"
    lines = ["| 文件名 | 类型 | 大小 |", "|-------|------|------|"]
    for f in files:
        lines.append("| {} | {} | {} |".format(f["name"], f["type"], f["size"]))
    return "\n".join(lines)


def _safe_sum(values):
    total = 0
    for value in values:
        try:
            total += int(float(value))
        except (TypeError, ValueError):
            continue
    return total


def _build_source_data_summary(parsed_data):
    if not parsed_data:
        return "_(无已解析的源数据)_"
    lines = []
    for item in parsed_data:
        ft = item.get("file_type", "unknown")
        status = item.get("parse_status", "unknown")
        fname = item.get("file_name", "?")
        fsize = item.get("file_size", "?")
        if ft == "zip":
            inner = item.get("inner_files", [])
            lines.append("- **{}** ({}) - ZIP {}个文件".format(fname, fsize, len(inner)))
            tables = item.get("parsed_tables", [])
            for t in tables:
                if t.get("parse_status") == "success":
                    sheet = t.get("sheet_name") or "-"
                    rows = t.get("row_count", 0)
                    cols = t.get("column_count", 0)
                    lines.append("  - {} [{}] - {} x {}".format(t["file_name"], sheet, rows, cols))
        elif status == "success":
            sheet = item.get("sheet_name") or "-"
            rows = item.get("row_count", 0)
            cols = item.get("column_count", 0)
            mv = item.get("missing_values_summary", {})
            mv_str = ", {}个缺失值".format(_safe_sum(mv.values())) if mv else ""
            lines.append("- **{}** ({}) [{}] - {}x{}{}".format(fname, fsize, sheet, rows, cols, mv_str))
        else:
            err = item.get("error_message", "解析失败")
            lines.append("- **{}** ({}) - {}".format(fname, fsize, err))
    return "\n".join(lines)


def _count_parsed_tables(parsed_data):
    if not parsed_data:
        return 0
    count = 0
    for item in parsed_data:
        if item.get("file_type") == "zip":
            for table in item.get("parsed_tables", []):
                if table.get("parse_status") == "success":
                    count += 1
        elif item.get("parse_status") == "success":
            count += 1
    return count


def _sum_missing_values(parsed_data):
    total = 0
    if not parsed_data:
        return total
    for item in parsed_data:
        targets = item.get("parsed_tables", []) if item.get("file_type") == "zip" else [item]
        for table in targets:
            mv = table.get("missing_values_summary", {}) or {}
            for value in mv.values():
                try:
                    total += int(value)
                except (TypeError, ValueError):
                    continue
    return total


def _count_parse_failures(parsed_data):
    if not parsed_data:
        return 0
    failures = 0
    for item in parsed_data:
        if item.get("file_type") == "zip":
            for table in item.get("parsed_tables", []):
                if table.get("parse_status") != "success":
                    failures += 1
        elif item.get("parse_status") not in ("success", None):
            failures += 1
    return failures


def _build_preflight_section(parsed_manuscript=None, parsed_source_data=None):
    from .preflight_checker import run_preflight_check, build_preflight_summary
    pf = run_preflight_check(parsed_manuscript, parsed_source_data)
    return build_preflight_summary(pf)


# -- journal fit assessment for mock mode --

def _build_journal_fit_assessment(journal_profile, parsed_manuscript):
    """Generate a mock Target Journal Fit Assessment section."""
    if not journal_profile:
        return "Target journal information not provided"

    lines = []
    jn = journal_profile.get("journal_name", "the target journal")
    lines.append("Based on the information provided for **{}**:".format(jn))
    lines.append("")
    lines.append('* **Scope fit**: The mock mode cannot verify actual scope fit. Please check the journal\'s aims and scope page manually.')
    at = journal_profile.get("article_type", "Not provided")
    lines.append("* **Article type fit**: Article type is set to \"{}\". Verify this format is accepted by {}.".format(at, jn))
    lines.append("* **Potential desk reject risk**: Mock mode cannot assess actual desk reject risk. Use real AI review for a substantive assessment.")
    lines.append("* **Suggested revisions before submission to {}**:".format(jn))
    lines.append("  - Review: Complete all preflight check items first")
    lines.append("  - Verify submission guidelines for format and scope requirements")
    lines.append("")
    lines.append("*This assessment is generated in Mock mode. It does not reflect actual editorial judgment.*")
    return "\n".join(lines)


# -- main generation function --


def _statement_check(full_text: str, patterns) -> str:
    low = (full_text or "").lower()
    for pat in patterns:
        if pat.lower() in low:
            return "Detected in manuscript text"
    return "Not available in uploaded files"


def _mock_recommendation_from_preflight(pf_result):
    score = (pf_result or {}).get("risk_score", 100)
    status = (pf_result or {}).get("overall_status", "High Risk")
    if status == "High Risk":
        return "High risk / Not ready for submission"
    if status == "Pass" and score <= 20:
        return "Low risk / Ready for submission"
    if score <= 40:
        return "Minor revision recommended"
    if score <= 70:
        return "Major revision recommended"
    return "High risk / Not ready for submission"


def _build_mock_concerns(pf_result, level="major"):
    checks = (pf_result or {}).get("manuscript_checks", []) + (pf_result or {}).get("source_data_checks", [])
    if level == "major":
        selected = [c for c in checks if c.get("status") == "Fail"]
        fallback = "No critical failure was detected by the automated preflight checks."
        severity = "High"
    else:
        selected = [c for c in checks if c.get("status") == "Warning"]
        fallback = "No minor warning was detected by the automated preflight checks."
        severity = "Medium"

    if not selected:
        return [
            {
                "concern": fallback,
                "evidence": "Automated Preflight Check Summary",
                "why_matters": "Mock mode only verifies basic file and structure signals; it does not perform a real scholarly assessment.",
                "suggested_revision": "Use a real AI review engine or human expert review for substantive peer-review comments.",
                "severity": "Low",
            }
        ]

    concerns = []
    for c in selected[:5]:
        check = c.get("check", "检查项")
        detail = c.get("detail", "Not available in uploaded files")
        concerns.append(
            {
                "concern": f"{check} 需要处理",
                "evidence": detail or "Not available in uploaded files",
                "why_matters": "该问题可能影响投稿前完整性检查、审稿人理解或结果可重复性。",
                "suggested_revision": "请根据 Preflight Check 提示补充、修正或解释该项内容。",
                "severity": severity,
            }
        )
    return concerns


def _append_concern(lines, item, heading_style="###"):
    lines.append(f"{heading_style} Concern: {item.get('concern', '')}")
    lines.append(f"* **Evidence from manuscript or source data**: {item.get('evidence', 'Not available in uploaded files')}")
    lines.append(f"* **Why it matters**: {item.get('why_matters', '')}")
    lines.append(f"* **Suggested revision**: {item.get('suggested_revision', '')}")
    lines.append(f"* **Severity**: {item.get('severity', '')}")
    lines.append("")


def generate_mock_review(
    mode,
    manuscript_info=None,
    source_data_info=None,
    parsed_source_data=None,
    parsed_manuscript=None,
    journal_profile=None,
):
    """生成数据感知的 Mock 审稿报告（Markdown）。

    Mock 模式只展示结构和自动质检结果，不编造具体论文证据。
    """
    from .preflight_checker import run_preflight_check, build_preflight_summary

    pf_result = run_preflight_check(parsed_manuscript, parsed_source_data)
    recommendation = _mock_recommendation_from_preflight(pf_result)
    major_concerns = _build_mock_concerns(pf_result, level="major")
    minor_concerns = _build_mock_concerns(pf_result, level="minor")

    full_text = (parsed_manuscript or {}).get("full_text", "") or ""
    sections = (parsed_manuscript or {}).get("detected_sections", {}) or {}
    parsed_table_count = _count_parsed_tables(parsed_source_data)
    missing_count = _sum_missing_values(parsed_source_data)
    parse_failures = _count_parse_failures(parsed_source_data)

    methods_status = "Detected" if any(k.lower().startswith("methods") for k in sections) else "Not available in uploaded files"
    results_status = "Detected" if any(k.lower().startswith("results") for k in sections) else "Not available in uploaded files"

    lines = []
    lines.append("> **注：这是 Mock 占位报告，不是真实 AI 评审。**")
    lines.append(">")
    lines.append("> 此报告仅用于测试页面、导出和报告结构。内容基于自动 Preflight Check，不代表真实学术审稿意见。")
    lines.append("")
    lines.append("# AI Pre-submission Peer Review Report (Mock)")
    lines.append("")
    lines.append("## 1. Editorial Summary")
    lines.append("")
    lines.append(f"当前为 **{mode}** 的 Mock 预览。系统已完成基础文件解析和 Preflight Check。")
    lines.append(f"Preflight 状态为 **{pf_result.get('overall_status')}**，风险评分为 **{pf_result.get('risk_score')}/100**。")
    lines.append("Mock 模式不会判断真实 novelty、scope 或 desk reject 风险；如需实质性审稿意见，请切换到真实 AI 评审。")
    lines.append("")
    lines.append("## 2. Overall Recommendation")
    lines.append("")
    lines.append(recommendation)
    lines.append("")
    lines.append("## 3. Major Concerns")
    lines.append("")
    for item in major_concerns:
        _append_concern(lines, item)
    lines.append("## 4. Minor Concerns")
    lines.append("")
    for item in minor_concerns:
        _append_concern(lines, item, heading_style="###")
    lines.append("## 5. Methodological and Statistical Review")
    lines.append("")
    lines.append(f"* Methods section: {methods_status}")
    lines.append(f"* Results section: {results_status}")
    lines.append("* Statistical appropriateness, sample size justification, bias control, and over-interpretation require real AI or human review. Mock mode does not infer these issues from incomplete evidence.")
    lines.append("* If these details are not present in the uploaded manuscript, treat them as **Not available in uploaded files**.")
    lines.append("")
    lines.append("## 6. Source Data and Reproducibility Review")
    lines.append("")
    if parsed_source_data:
        lines.append(f"系统检测到 source data，并成功解析 **{parsed_table_count}** 个表格。")
        lines.append(f"检测到缺失值数量：**{missing_count}**。解析失败项目：**{parse_failures}**。")
        lines.append("")
        lines.append(_build_source_data_summary(parsed_source_data))
    else:
        lines.append("Not available in uploaded files")
    lines.append("")
    lines.append("## 7. Reporting and Ethics Check")
    lines.append("")
    lines.append(f"* Data Availability Statement: {_statement_check(full_text, ['data availability', 'data are available', '数据可用', '数据获得'])}")
    lines.append(f"* Ethics / IRB Approval: {_statement_check(full_text, ['ethics', 'ethical approval', 'IRB', '伦理', '伦理审批'])}")
    lines.append(f"* Conflict of Interest: {_statement_check(full_text, ['conflict of interest', 'competing interest', '利益冲突'])}")
    lines.append(f"* Author Contributions: {_statement_check(full_text, ['author contributions', '作者贡献'])}")
    lines.append(f"* Limitations: {_statement_check(full_text, ['limitations', '局限性'])}")
    lines.append("")
    lines.append("## 8. Revision Checklist")
    lines.append("")
    actions = pf_result.get("suggested_actions", []) or []
    if not actions:
        actions = ["完成最终语言、格式和投稿声明检查", "使用真实 AI 评审或人工专家评审进行实质性审查"]
    for item in actions[:8]:
        lines.append(f"* [ ] {item}")
    lines.append("* [ ] 如需真实同行评议式意见，请使用 EdgeRef AI Review Engine 或人工专家评审。")
    lines.append("")
    lines.append("## 9. Final Pre-submission Advice")
    lines.append("")
    lines.append("优先处理以下 3 件事：")
    lines.append("1. 先修复 Preflight Check 中的 Fail / Warning 项。")
    lines.append("2. 确认 Methods、Results、References 和 source data 说明完整。")
    lines.append("3. 使用 EdgeRef AI Review Engine 或人工专家评审检查 novelty、方法学和结论支撑。")
    lines.append("")
    lines.append("## 10. Target Journal Fit Assessment")
    lines.append("")
    lines.append(_build_journal_fit_assessment(journal_profile, parsed_manuscript))
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Appendix - Uploaded Files and Preflight Summary")
    lines.append("")
    lines.append("### Manuscript")
    lines.append(_build_file_table(manuscript_info))
    lines.append("")
    lines.append("### Source Data")
    lines.append(_build_file_table(source_data_info))
    lines.append("")
    lines.append("### Preflight Check Summary")
    lines.append(build_preflight_summary(pf_result))
    lines.append("")
    lines.append("*以上为 Mock 占位报告。它不会替代正式期刊同行评议，也不会替代真实 AI 评审。*")

    return "\n".join(lines)
