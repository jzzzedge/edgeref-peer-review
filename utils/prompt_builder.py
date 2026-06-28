#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prompt 构建模块 — 根据不同评审模式生成结构化 AI 评审 Prompt."""

from typing import Any, Dict, List, Optional
from .journal_profile import summarize_journal_profile
from .journal_database import get_journal_match_summary, match_chinese_core_journal


# 各评审模式的专家角色设定

_ROLE_INSTRUCTIONS = {
    "编辑初审": {
        "role": "期刊责任编辑",
        "context": (
            "你是一位资深期刊责任编辑。请从期刊编辑的角度对以下投稿论文进行初审评估。"
            "\n\n"
            "## 本模式重点审查方向\n"
            "1. **Scope & Novelty**: 稿件主题是否在期刊收稿范围内？创新性是否足以上升到送审标准？\n"
            "2. **Desk Reject Risk**: 摘要是否清晰、引言是否明确研究空白？是否有 desk reject 风险？\n"
            "3. **Overall Quality Gate**: 整体语言质量、结构完整度是否达到同行评议送审门槛？\n"
            "\n"
            "请在 Editorial Summary 中明确评估 desk reject 风险，并在 Overall Recommendation 中给出送审建议。"
        ),
    },
    "同行专家评审": {
        "role": "同行评审专家",
        "context": (
            "你是一位同行评审专家（peer reviewer）。请对以下论文进行同行评议。"
            "\n\n"
            "## 本模式重点审查方向\n"
            "1. **Contribution**: 研究对所在领域的实质性贡献是什么？是否足以发表？\n"
            "2. **Logic & Argumentation**: 论文的逻辑链条是否连贯？claim 是否有充分证据支撑？\n"
            "3. **Literature**: 文献综述是否全面？是否遗漏关键近期工作？\n"
            "4. **Discussion**: 讨论是否公正？局限性是否充分承认？对结果的解释是否过度？\n"
            "\n"
            "请在 Major Concerns 中逐条给出 Concern / Evidence / Why It Matters / Suggested Revision / Severity。"
        ),
    },
    "统计与方法学审查": {
        "role": "统计与方法学专家",
        "context": (
            "你是一位生物统计与方法学专家（Statistical / Methodological Reviewer）。"
            "\n\n"
            "## 本模式重点审查方向\n"
            "1. **Study Design**: 研究设计是否合理？是否适合回答提出的研究问题？\n"
            "2. **Sample Size**: 样本量是否充足？是否提供了功效分析（power analysis）？\n"
            "3. **Statistical Methods**: 统计方法选择是否恰当？前提假设是否经过验证？\n"
            "4. **Bias & Confounders**: 是否存在未控制的选择偏倚、信息偏倚或混杂因素？\n"
            "5. **Reporting**: 是否完整报告了效应量、置信区间？p 值使用是否合理？\n"
            "\n"
            "请以 Methodological and Statistical Review 为首要输出重点。"
        ),
    },
    "数据完整性审查": {
        "role": "数据审查专家",
        "context": (
            "你是一位数据完整性审查专家（Data Integrity Reviewer）。"
            "\n\n"
            "## 本模式重点审查方向\n"
            "1. **Source Data Completeness**: source data 是否完整？是否覆盖了论文中所有分析？\n"
            "2. **Reproducibility**: 是否可以在仅有 source data 和方法描述的情况下重现结果？\n"
            "3. **Missing Values**: 缺失值的数量、分布和处理方式是否合理？\n"
            "4. **Data Quality**: 数据文件中是否存在异常值、不一致、列名混乱等问题？\n"
            "5. **Metadata**: 数据文件命名是否规范？是否包含数据字典或说明文档？\n"
            "\n"
            "请以 Source Data and Reproducibility Review 为首要输出重点。"
        ),
    },
    "综合预评审": {
        "role": "综合审稿专家",
        "context": (
            "你是一位综合审稿专家，请分别从编辑视角、同行评审视角、"
            "统计与方法学视角、数据完整性视角对以下论文进行全面评估。"
            "\n\n"
            "## 本模式要求覆盖所有维度\n"
            "1. **Editorial Perspective**: scope, novelty, desk reject risk\n"
            "2. **Peer Review Perspective**: contribution, logic, literature, discussion\n"
            "3. **Statistical/Methodological Perspective**: design, statistics, sample size, bias\n"
            "4. **Data Integrity Perspective**: source data, reproducibility, missing values\n"
            "\n"
            "特别注意交叉领域的问题（如方法学选择对结果解释的影响、数据质量对统计结论的影响）。"
        ),
    },
}

def build_manuscript_summary(
    parsed_manuscript: Optional[Dict[str, Any]],
    max_chars: int = 8000,
) -> str:
    """构建论文摘要（用于放入 Prompt，节省 token）."""
    if not parsed_manuscript:
        return "_(未上传论文)_"
    if not (parsed_manuscript.get("full_text") or "").strip():
        return "Manuscript text not available (parse failed or empty file)"
    sections = dict(parsed_manuscript.get("detected_sections", {}) or {})
    if not sections:
        return "_(未检测到章节)_"
    parts = []
    char_used = 0
    title = sections.get("Title", "")
    if title:
        parts.append(f"[Title/标题]\n{title}\n")
        char_used += len(parts[-1])
    used_sections = {"Title"}
    for sec_name in ("Abstract", "Introduction", "Methods", "Results", "Discussion", "Conclusion", "References"):
        text = sections.get(sec_name, "")
        used_sections.add(sec_name)
        if text:
            remaining = max_chars - char_used
            if remaining <= 0:
                parts.append("\n[... 剩余章节因 token 限制已截断 ...]")
                break
            if len(text) > remaining:
                text = text[:remaining] + "\n[... 截断 ...]"
            labels = {"Abstract": "Abstract/摘要", "Introduction": "Introduction/引言",
                     "Methods": "Methods/方法", "Results": "Results/结果",
                     "Discussion": "Discussion/讨论", "Conclusion": "Conclusion/结论",
                     "References": "References/参考文献"}
            label = labels.get(sec_name, sec_name)
            parts.append(f"[{label}]\n{text}\n")
            char_used += len(parts[-1])
    for sec_name, text in sections.items():
        if sec_name in used_sections:
            continue
        remaining = max_chars - char_used
        if remaining <= 0:
            break
        if len(text) > remaining:
            text = text[:remaining] + "\n[... 截断 ...]"
        parts.append(f"[{sec_name}]\n{text}\n")
        char_used += len(parts[-1])
    summary = "**论文信息**\n"
    summary += f"- 文件名: {parsed_manuscript.get('file_name', '?')}\n"
    summary += f"- 字符数: {parsed_manuscript.get('char_count', 0):,}\n"
    summary += f"- 词数: {parsed_manuscript.get('word_count', 0):,}\n"
    summary += f"- 检测到章节: {list(parsed_manuscript.get('detected_sections', {}).keys())}\n"
    summary += "\n---\n\n"
    summary += "".join(parts)
    return summary



def _format_stat_value(value: Any, decimals: int = 2) -> str:
    """安全格式化统计值，避免字符串/空值触发 f-string 数字格式错误。"""
    try:
        if value is None:
            return "?"
        number = float(value)
        if decimals <= 0:
            return f"{number:.0f}"
        return f"{number:.{decimals}f}"
    except (TypeError, ValueError):
        text = str(value).strip()
        return text if text else "?"



def _sum_numeric_values(values) -> int:
    """安全统计缺失值数量，兼容 int/float/str/None。"""
    total = 0
    for value in values:
        try:
            total += int(float(value))
        except (TypeError, ValueError):
            continue
    return total

def build_source_data_summary(
    parsed_source_data: Optional[List[Dict[str, Any]]],
    max_chars: int = 4000,
) -> str:
    """构建 Source Data 摘要，只放结构信息，不放完整原始数据。"""
    if not parsed_source_data:
        return "Source data not provided"
    if all(item.get("parse_status") != "success" for item in parsed_source_data):
        return "Source data not available or failed to parse"

    lines = []
    char_used = 0

    def add_entry(entry: str) -> bool:
        nonlocal char_used
        remaining = max_chars - char_used
        if remaining <= 0:
            lines.append("[... 剩余数据因 token 限制已截断 ...]")
            return False
        if len(entry) > remaining:
            entry = entry[:remaining] + "\n[... 截断 ...]\n"
        lines.append(entry)
        char_used += len(entry)
        return True

    def table_summary(table: Dict[str, Any], indent: str = "") -> str:
        fname = table.get("file_name", "?")
        sheet = table.get("sheet_name") or "-"
        status = table.get("parse_status", "?")
        entry = f"{indent}- {fname} [{sheet}] — {status}\n"
        if status == "success":
            entry += f"{indent}  行数: {table.get('row_count', 0):,}; 列数: {table.get('column_count', 0):,}\n"
            cols = table.get("columns", []) or []
            if cols:
                col_str = ", ".join(str(c) for c in cols[:12])
                if len(cols) > 12:
                    col_str += f" ... (共 {len(cols)} 列)"
                entry += f"{indent}  列名: {col_str}\n"
            mv = table.get("missing_values_summary", {}) or {}
            if mv:
                total_mv = _sum_numeric_values(mv.values())
                mv_items = list(mv.items())[:8]
                mv_cols = ", ".join(f"{k}({v})" for k, v in mv_items)
                entry += f"{indent}  缺失值: 共 {total_mv} 个；{mv_cols}\n"
            ns = table.get("numeric_summary", {}) or {}
            if ns:
                entry += f"{indent}  数值列统计 count/mean/min/max:\n"
                for col, stats in list(ns.items())[:4]:
                    c = _format_stat_value(stats.get("count", "?"), decimals=0)
                    m = _format_stat_value(stats.get("mean", "?"), decimals=2)
                    mn = _format_stat_value(stats.get("min", "?"), decimals=2)
                    mx = _format_stat_value(stats.get("max", "?"), decimals=2)
                    entry += f"{indent}    - {col}: n={c}, mean={m}, range=[{mn}, {mx}]\n"
        else:
            entry += f"{indent}  错误: {table.get('error_message', '解析失败')}\n"
        return entry

    for item in parsed_source_data:
        fname = item.get("file_name", "?")
        ftype = item.get("file_type", "?")
        fsize = item.get("file_size", "?")
        status = item.get("parse_status", "?")

        if ftype == "zip":
            inner = item.get("inner_files", []) or []
            tables = item.get("parsed_tables", []) or []
            entry = f"### {fname} (zip, {fsize})\n"
            entry += f"状态: {status}; ZIP 内文件数: {len(inner)}; 可解析表格: {len(tables)}\n"
            for table in tables[:8]:
                entry += table_summary(table, indent="")
            if len(tables) > 8:
                entry += f"... 还有 {len(tables) - 8} 个表格未展示\n"
            entry += "\n---\n\n"
        else:
            entry = f"### {fname} ({ftype}, {fsize})\n"
            entry += table_summary(item, indent="")
            entry += "\n---\n\n"

        if not add_entry(entry):
            break

    return "".join(lines)


def _build_preflight_for_prompt(parsed_manuscript, parsed_source_data):
    from .preflight_checker import run_preflight_check, build_preflight_summary
    pf = run_preflight_check(parsed_manuscript, parsed_source_data)
    return build_preflight_summary(pf)



def _build_language_instruction(parsed_manuscript):
    """Build output language instruction based on detected manuscript language."""
    if not parsed_manuscript:
        return "Language: English (default)\n\nPlease write the review report in English."
    
    detected = parsed_manuscript.get("detected_language", "Unknown")
    output_lang = parsed_manuscript.get("output_language", "English")
    
    lines = []
    lines.append(f"## Language Instruction")
    lines.append("")
    lines.append(f"The manuscript language has been detected as: {detected}")
    lines.append(f"The review must be written in: {output_lang}")
    lines.append("")
    lines.append("Rules:")
    lines.append("- If manuscript language is English, write the review report in English.")
    lines.append("- If manuscript language is Chinese, write the review report in Chinese.")
    lines.append("- If manuscript language is Mixed, use the dominant language.")
    lines.append("- Do NOT translate the manuscript content itself.")
    lines.append("- Only adapt the review report language.")
    lines.append("")
    return "\n".join(lines)


def build_review_prompt(
    mode: str,
    parsed_manuscript: Optional[Dict[str, Any]] = None,
    parsed_source_data: Optional[List[Dict[str, Any]]] = None,
    journal_profile: Optional[Dict[str, str]] = None,
) -> str:
    """构建完整的 AI 评审 Prompt."""
    rd = _ROLE_INSTRUCTIONS.get(mode, _ROLE_INSTRUCTIONS["综合预评审"])
    lines = []
    lines.append("# AI 论文评审 Prompt")
    lines.append("")
    lines.append(f"## 评审模式: {mode}")
    lines.append(f"## 专家角色: {rd['role']}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 评审指令")
    lines.append("")
    lines.append(rd["context"])
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Journal Fit Assessment Instructions")
    lines.append("")
    lines.append("If the user provided Target Journal information below, you MUST assess:")
    lines.append("1. Scope fit: Does the manuscript topic match the journal\'s stated scope?")
    lines.append("2. Article type fit: Is the article type accepted and formatted correctly?")
    lines.append("3. Novelty expectation: Does the novelty level meet expected standards for this journal?")
    lines.append("4. Desk reject risk: Is this manuscript at risk of desk rejection at this specific journal?")
    lines.append("5. Key pre-submission changes: What format/scoping adjustments are needed?")
    lines.append("")
    lines.append("Important constraints:")
    lines.append("- Do NOT search the internet for journal information.")
    lines.append("- Only use the information provided by the user in the Target Journal Profile below.")
    lines.append("- If specific journal guidelines are not provided, state \"Not available in uploaded files\".")
    lines.append('- If no Target Journal Profile is provided, still include this section and write "Target journal information not provided."')
    lines.append("- Your role is limited to technical format and scope matching; you are not the actual journal editor.")
    lines.append("")
    lines.append("### Journal Catalog Match Instructions")
    lines.append("")
    lines.append("If a Journal Catalog Match result is provided below:")
    lines.append("- If matched to SCIE / SSCI / AHCI / CSSCI / PKU Core / CSCD / AMI / Chinese Science and Technology Core / EI Compendex or another local catalog, evaluate manuscript submission fit based only on the matched local record(s) such as database, database type, subject area and version.")
    lines.append("- If not matched, do NOT state or imply that the journal is not a core journal. Only write: \"Not found in the local sample database.\"")
    lines.append("- Do NOT fabricate journal directory information. Only use the match result provided.")
    lines.append("- Always remind the user: Please verify with the latest official directory or your institution\"s research management office before submission.")
    lines.append("")
    lines.append("---")
    lines.append("")
    # -- anti-hallucination instructions --
    anti_hallucination = (
        "## Anti-hallucination Rules (Must Follow)\n\n"
        "The following rules must be strictly obeyed:\n\n"
        "1. **Do not fabricate information**: Only analyze based on the uploaded manuscript text and source data.\n"
        "2. **Mark missing info explicitly**: If the manuscript or source data does not provide certain information, "
        "you MUST write \"Not available in uploaded files\". Do not guess.\n"
        "3. **Do not claim image inspection**: This system only processes text and data tables. "
        "Do NOT claim to have checked image authenticity, image integrity, or Western blot bands.\n"
        "4. **Do not impersonate human experts**: You are an AI pre-submission assistance tool. "
        "Do NOT claim to have performed human expert-level review or formal journal peer review.\n"
        "5. **Clarify tool positioning**: Your output serves only as a pre-submission self-check "
        "and revision aid for authors. It CANNOT replace formal journal peer review.\n"
        "6. **Evidence-based**: Each concern must cite manuscript section names, direct short phrases, or source data table names when available. "
        "If no supporting evidence is available, write \"Not available in uploaded files\" instead of inventing evidence.\n"
        "7. **Do not fabricate journal information**: Only use the journal information provided by the user in the Target Journal Profile. "
        "Do not guess or search for journal scope, aims, or submission guidelines. "
        "If the user did not provide target journal information, write \"Target journal information not provided\".\n"
    )

# -- output format --
    output_format = (
        "## Output Format\n\n"
        "Please output the review report in the following Markdown structure strictly. "
        "Use the language specified in the Language Instruction section. "
        "If the output language is English, write the narrative review in English. "
        "If the output language is Chinese, write the narrative review in Chinese. "
        "Section headings and standard peer-review terms may remain in English when useful.\n\n"
        "```markdown\n"
        "# AI Pre-submission Peer Review Report\n\n"
        "## 1. Editorial Summary\n"
        "* Assess whether the manuscript is suitable for submission\n"
        "* Evaluate desk reject risk\n\n"
        "## 2. Overall Recommendation\n"
        "Choose exactly one from:\n"
        "* Low risk / Ready for submission\n"
        "* Minor revision recommended\n"
        "* Major revision recommended\n"
        "* High risk / Not ready for submission\n\n"
        "## 3. Major Concerns\n"
        "Each concern MUST include:\n"
        "* **Concern**: [brief description]\n"
        "* **Evidence from manuscript or source data**: [direct quote or data reference]\n"
        "* **Why it matters**: [why this issue is important]\n"
        "* **Suggested revision**: [specific revision suggestion]\n"
        "* **Severity**: High / Medium / Low\n\n"
        "## 4. Minor Concerns\n"
        "Same format as above, can be shorter.\n\n"
        "## 5. Methodological and Statistical Review\n"
        "* Study design evaluation\n"
        "* Sample size evaluation\n"
        "* Statistical method evaluation\n"
        "* Whether results are over-interpreted\n"
        "* Whether conclusions are supported by data\n\n"
        "## 6. Source Data and Reproducibility Review\n"
        "* Whether source data is sufficient\n"
        "* Whether table structure is clear\n"
        "* Whether missing values exist\n"
        "* Whether data supports figures/tables and conclusions\n"
        "* Where additional data documentation is needed\n\n"
        "## 7. Reporting and Ethics Check\n"
        "* Data Availability Statement\n"
        "* Ethics / IRB Approval\n"
        "* Conflict of Interest\n"
        "* Author Contributions\n"
        "* Limitations\n\n"
        "## 8. Revision Checklist\n"
        "Provide an actionable revision checklist for the author using checkbox format:\n"
        "* [ ] ...\n\n"
        "## 9. Final Pre-submission Advice\n"
        "Briefly state the top 3 priority items to address before submission.\n\n"
        "## 10. Target Journal Fit Assessment\n"
        "Include the following ONLY if the user provided Target Journal Profile:\n"
        "* Scope fit: How well does the manuscript match the journal\'s scope\n"
        "* Article type fit: Does the manuscript format match the article type\n"
        "* Novelty expectation: Would the novelty meet this journal\'s bar\n"
        "* Potential desk reject risk: For this specific journal\n"
        "* Key changes before submission: What the author should revise to fit this journal\n"
        "If the user did not provide target journal information, output this section as:\n"
        "\"## 10. Target Journal Fit Assessment\n"
        "Target journal information not provided.\n"
        "```\n"
        "\n"
        "---\n"
    )

    lines.append(anti_hallucination)
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(_build_language_instruction(parsed_manuscript))
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Manuscript Summary")
    lines.append("")
    lines.append(build_manuscript_summary(parsed_manuscript))
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Source Data Summary")
    lines.append("")
    lines.append(build_source_data_summary(parsed_source_data))
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Preflight Check Summary")
    lines.append("")
    lines.append(_build_preflight_for_prompt(parsed_manuscript, parsed_source_data))
    lines.append("")
    lines.append("")
    lines.append("---")
    lines.append("")
    journal_summary = summarize_journal_profile(journal_profile)
    if journal_profile:
        lines.append(journal_summary)
    else:
        lines.append("## Target Journal Profile")
        lines.append("")
        lines.append(journal_summary)
    lines.append("")
    
    # Add journal match section
    journal_name = (journal_profile or {}).get("journal_name", "")
    if journal_name:
        match_result = match_chinese_core_journal(journal_name)
        lines.append(get_journal_match_summary(match_result))
        lines.append("")
    else:
        lines.append("### Journal Catalog Match")
        lines.append("")
        lines.append("- **Match status**: Not checked (journal name not provided)")
        lines.append("")
    
    lines.append("---")
    lines.append("")
    lines.append(output_format)
    lines.append("")
    lines.append("Please begin the review and follow the required output language exactly.")
    return "\n".join(lines)
