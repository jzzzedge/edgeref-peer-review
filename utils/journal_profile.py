"""目标期刊信息模块 — 构建和管理 Target Journal Profile。

提供两个函数：
  - build_journal_profile(): 构建目标期刊信息字典
  - summarize_journal_profile(): 格式化为文本摘要
"""

from typing import Any, Dict, Optional


def build_journal_profile(
    journal_name: Optional[str] = None,
    subject_area: Optional[str] = None,
    article_type: Optional[str] = None,
    journal_scope: Optional[str] = None,
    word_limit: Optional[str] = None,
    figure_limit: Optional[str] = None,
    table_limit: Optional[str] = None,
    reference_limit: Optional[str] = None,
    special_requirements: Optional[str] = None,
) -> Optional[Dict[str, str]]:
    """构建目标期刊信息字典。

    只包含用户实际填写的字段。如果没有任何字段被填写，返回 None。

    Args:
        journal_name: 目标期刊名称
        subject_area: 学科领域
        article_type: 文章类型 (如 Original Research Article, Review 等)
        journal_scope: 期刊 scope / aims 简述
        word_limit: 字数限制
        figure_limit: 图片数量限制
        table_limit: 表格数量限制
        reference_limit: 参考文献数量限制
        special_requirements: 特殊投稿要求

    Returns:
        字典或 None（如果用户未填写任何字段）。
    """
    profile: Dict[str, str] = {}

    if journal_name:
        val = journal_name.strip()
        if val:
            profile["journal_name"] = val
    if subject_area:
        val = subject_area.strip()
        if val:
            profile["subject_area"] = val
    if article_type:
        profile["article_type"] = article_type
    if journal_scope:
        val = journal_scope.strip()
        if val:
            profile["journal_scope"] = val
    if word_limit:
        val = word_limit.strip()
        if val:
            profile["word_limit"] = val
    if figure_limit:
        val = figure_limit.strip()
        if val:
            profile["figure_limit"] = val
    if table_limit:
        val = table_limit.strip()
        if val:
            profile["table_limit"] = val
    if reference_limit:
        val = reference_limit.strip()
        if val:
            profile["reference_limit"] = val
    if special_requirements:
        val = special_requirements.strip()
        if val:
            profile["special_requirements"] = val

    return profile if profile else None


def summarize_journal_profile(
    journal_profile: Optional[Dict[str, str]],
) -> str:
    """将目标期刊信息格式化为文本摘要，用于放入 AI Prompt 或报告中。

    Args:
        journal_profile: build_journal_profile 的返回值，或 None。

    Returns:
        格式化的 Markdown 文本摘要。
    """
    if not journal_profile:
        return "Target journal information not provided"

    lines = []
    lines.append("## Target Journal Profile")
    lines.append("")

    if journal_profile.get("journal_name"):
        lines.append(f"- Target journal: {journal_profile['journal_name']}")
    if journal_profile.get("subject_area"):
        lines.append(f"- Subject area: {journal_profile['subject_area']}")
    if journal_profile.get("article_type"):
        lines.append(f"- Article type: {journal_profile['article_type']}")
    if journal_profile.get("journal_scope"):
        lines.append(f"- Journal scope / aims: {journal_profile['journal_scope']}")

    # Collect submission limits
    limits = []
    limit_labels = {
        "word_limit": "Words",
        "figure_limit": "Figures",
        "table_limit": "Tables",
        "reference_limit": "References",
    }
    for key, label in limit_labels.items():
        if journal_profile.get(key):
            limits.append(f"{label}: {journal_profile[key]}")
    if limits:
        lines.append(f"- Submission limits: {'; '.join(limits)}")

    if journal_profile.get("special_requirements"):
        lines.append(f"- Special requirements: {journal_profile['special_requirements']}")

    return "\n".join(lines)
