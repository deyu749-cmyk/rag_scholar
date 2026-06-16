"""
写作模式
- 学术润色/改写
- 结合文献库提供论证方向参考
- 降低查重风险的改写策略
"""

from typing import Optional

from config import (
    LEVOLINK_API_BASE, LEVOLINK_API_KEY,
    CHAT_MODEL, CHAT_MAX_TOKENS,
    WRITING_SYSTEM_PROMPT
)
from indexer import call_claude, get_single_embedding
from retriever import search_chunks, search_summaries, cohere_rerank


def academic_rewrite(user_text: str, lib_names: list[str],
                     style: str = "polish",
                     source_filter: Optional[list[str]] = None) -> dict:
    """
    学术写作：润色/改写/扩写，结合文献库

    Args:
        user_text: 用户贴入的原始文本
        lib_names: 关联的文献库
        style: 写作模式
            - "polish": 润色（保持原意，提升表达）
            - "rewrite": 改写（重新组织语言，降低查重）
            - "expand": 扩写（基于文献扩展论述）
            - "condense": 压缩（精简表达）
        source_filter: 文件名过滤（可选）

    Returns:
        {
            "rewritten_text": str,
            "references_used": list[dict],
            "style": str
        }
    """
    # 从文献库检索相关段落作为参考
    references = []
    if lib_names:
        # 用用户文本的前 500 字作为查询
        query_text = user_text[:500] if len(user_text) > 500 else user_text
        try:
            references = search_chunks(
                query=query_text,
                lib_names=lib_names,
                source_filter=source_filter,
                initial_k=30,
                final_k=8
            )
        except Exception as e:
            print(f"写作模式检索文献失败: {e}")
            references = []

    # 构建文献参考上下文
    ref_context = ""
    if references:
        ref_parts = []
        for i, r in enumerate(references):
            source = r["metadata"].get("source", "未知来源")
            ref_parts.append(f"[参考{i + 1}] 来源: {source}\n{r['document'][:600]}")
        ref_context = "\n\n---\n\n".join(ref_parts)

    # 根据 style 构建具体指令
    style_instructions = {
        "polish": """【润色模式】
请对以下学术文本进行润色：
- 事实核查：检查文中涉及的作家姓名、作品名称、出版年份、文学流派归属、获奖记录等事实信息是否准确；如发现错误或存疑，在文末以【事实核查】单独列出
- 消除口语化表达，提升学术规范性
- 增强逻辑连贯性和论证严密性
- 保持作者原有观点和论证结构不变
- 优化句式，使表达更加精炼
- 保留所有专业术语（含非洲本土语言术语如 négritude、Ubuntu、griot 等）
- 注意非洲人名、地名、语言名称的规范拼写
- 不要增加新的论点或大幅扩展内容""",

        "rewrite": """【改写模式】
请对以下学术文本进行深度改写：
- 事实核查：检查文中涉及的作家姓名、作品名称、出版年份、文学流派归属等事实信息是否准确；如发现错误或存疑，在文末以【事实核查】单独列出
- 完全重新组织语言表达，确保与原文表述差异度高
- 保持核心观点和论证逻辑不变
- 替换非术语性表达，调整句式结构；保留非洲本土语言术语的规范拼写
- 如果参考文献中有相关观点，以"学界认为……""有学者指出……"等方式融入
- 绝不直接复制参考文献原文
- 目标：改写后文本与原文及任何单一来源的文字重复率低于15%""",

        "expand": """【扩写模式】
请对以下学术文本进行扩写：
- 事实核查：检查文中涉及的作家姓名、作品名称、出版年份、文学流派归属等事实信息是否准确；如发现错误或存疑，在文末以【事实核查】单独列出
- 基于作者的核心论点进行深化和展开
- 结合参考文献中的相关观点，丰富论证层次
- 增加学理性分析和理论支撑（可引入后殖民理论、非洲中心主义等相关理论框架）
- 补充必要的学术背景和语境
- 引用文献时使用正式引文格式（"某某指出……"）
- 保留并正确使用非洲本土语言术语
- 扩写幅度：约为原文的 2-3 倍
- 不要偏离作者原有的论证方向""",

        "condense": """【压缩模式】
请对以下学术文本进行精简：
- 提炼核心论点，删除冗余表述
- 保留关键论据和重要引用
- 压缩至原文的 40-60%
- 确保逻辑完整性不受损
- 保持学术表达规范"""
    }

    style_instruction = style_instructions.get(style, style_instructions["polish"])

    # 构建完整 prompt
    user_content = f"""{style_instruction}

===== 用户原文 =====

{user_text}

"""

    if ref_context:
        user_content += f"""===== 相关文献参考（仅供论证方向参考，不可直接复制）=====

{ref_context}

"""

    user_content += """===== 输出要求 =====
请直接输出改写后的文本，不需要解释改写策略。
如果引用了参考文献的观点，请在文中标注来源。"""

    # 调用 Claude
    rewritten = call_claude(
        system_prompt=WRITING_SYSTEM_PROMPT,
        user_content=user_content,
        max_tokens=CHAT_MAX_TOKENS
    )

    return {
        "rewritten_text": rewritten,
        "references_used": [
            {"source": r["metadata"].get("source", ""), "score": r.get("score", 0)}
            for r in references
        ],
        "style": style
    }


def writing_chat(user_text: str, instruction: str, lib_names: list[str],
                 conversation_history: Optional[list[dict]] = None) -> str:
    """
    写作模式下的自由对话
    用户可以对改写结果提出修改意见

    Args:
        user_text: 当前文本（可能是已改写的版本）
        instruction: 用户的修改指令
        lib_names: 关联文献库
        conversation_history: 对话历史

    Returns:
        修改后的文本
    """
    system_prompt = """你是一位学术写作助手。用户会给你一段学术文本和修改指令。
请按照指令修改文本。

核心原则：
1. 严格按照用户指令修改，不要自作主张
2. 保持学术规范性
3. 如果用户要求增加引用，使用正式引文格式
4. 确保修改后文本的查重安全性
5. 直接输出修改后的完整文本"""

    # 构建对话上下文
    messages_context = ""
    if conversation_history:
        for msg in conversation_history[-6:]:  # 保留最近 6 轮
            role = "用户" if msg["role"] == "user" else "助手"
            messages_context += f"{role}: {msg['content']}\n\n"

    user_content = f"""当前文本：
{user_text}

修改指令：
{instruction}"""

    if messages_context:
        user_content = f"对话历史：\n{messages_context}\n\n{user_content}"

    return call_claude(
        system_prompt=system_prompt,
        user_content=user_content,
        max_tokens=CHAT_MAX_TOKENS
    )


def generate_literature_review(topic: str, lib_names: list[str],
                               source_filter: Optional[list[str]] = None,
                               scope: str = "review") -> dict:
    """
    根据主题从文献库生成文献综述或概论

    Args:
        topic: 用户给出的主题/研究问题
        lib_names: 关联的文献库
        source_filter: 文件名过滤（可选）
        scope: 生成类型
            - "review": 文献综述（梳理研究脉络、观点分歧、发展趋势）
            - "overview": 概论（概括性介绍该领域核心议题和主要成果）

    Returns:
        {
            "text": str,
            "references_used": list[dict],
            "scope": str
        }
    """
    # 检索摘要层（获取全局视野）
    summaries = []
    if lib_names:
        try:
            summaries = search_summaries(
                query=topic,
                lib_names=lib_names,
                source_filter=source_filter,
                initial_k=30,
                final_k=15
            )
        except Exception:
            summaries = []

    # 检索向量块层（获取具体论述细节）
    chunks = []
    if lib_names:
        try:
            chunks = search_chunks(
                query=topic,
                lib_names=lib_names,
                source_filter=source_filter,
                initial_k=50,
                final_k=12
            )
        except Exception:
            chunks = []

    # 构建摘要上下文
    summary_context = ""
    if summaries:
        parts = []
        for i, s in enumerate(summaries):
            source = s["metadata"].get("source", "未知来源")
            parts.append(f"[文献{i+1}] {source}\n{s['document']}")
        summary_context = "\n\n---\n\n".join(parts)

    # 构建段落上下文
    chunk_context = ""
    if chunks:
        parts = []
        for i, c in enumerate(chunks):
            source = c["metadata"].get("source", "未知来源")
            parts.append(f"[段落{i+1}] 来源: {source}\n{c['document'][:800]}")
        chunk_context = "\n\n---\n\n".join(parts)

    scope_instructions = {
        "review": """请基于以下文献材料，围绕用户给出的主题撰写一篇学术文献综述。

要求：
1. 梳理该主题的研究脉络和发展阶段
2. 归纳主要学术观点，标明观点的持有者/来源
3. 指出学界的共识与分歧
4. 分析研究趋势和尚待探索的方向
5. 所有引用必须标注来源，格式为 [文献X] 或 [段落X]
6. 结构：引言 → 研究脉络 → 主要观点与争论 → 研究空白与展望
7. 保持学术规范性，避免主观臆断""",

        "overview": """请基于以下文献材料，围绕用户给出的主题撰写一篇学术概论。

要求：
1. 概括该领域的核心议题和基本框架
2. 介绍主要理论视角和代表性学者
3. 概述重要研究成果和关键结论
4. 语言清晰、结构完整，适合作为研究的起点性文献
5. 所有引用必须标注来源，格式为 [文献X] 或 [段落X]
6. 结构：导论 → 核心概念 → 主要理论与学者 → 重要成果 → 小结"""
    }

    instruction = scope_instructions.get(scope, scope_instructions["review"])

    system_prompt = """你是一位专精非洲文学研究的学术写作助手。你的任务是基于用户提供的文献材料生成高质量的学术文献综述或概论。

核心原则：
- 只使用提供的文献材料中的信息，不要凭空捏造观点或引用
- 如果材料不足以支撑完整综述，明确标注哪些部分需要补充文献
- 注意非洲文学相关术语、人名、作品名的规范表达
- 引用必须标注来源编号"""

    user_content = f"""{instruction}

===== 研究主题 =====
{topic}

"""
    if summary_context:
        user_content += f"""===== 文献摘要（全局视野）=====
{summary_context}

"""
    if chunk_context:
        user_content += f"""===== 文献段落（具体论述）=====
{chunk_context}

"""

    if not summary_context and not chunk_context:
        user_content += "【注意】未检索到相关文献材料，请基于主题给出框架建议并标注需要补充的文献方向。\n"

    text = call_claude(
        system_prompt=system_prompt,
        user_content=user_content,
        max_tokens=CHAT_MAX_TOKENS
    )

    all_refs = []
    seen_sources = set()
    for r in summaries + chunks:
        src = r["metadata"].get("source", "")
        if src and src not in seen_sources:
            seen_sources.add(src)
            all_refs.append({"source": src, "score": r.get("score", 0)})

    return {
        "text": text,
        "references_used": all_refs,
        "scope": scope
    }


def annotate_citations(article_text: str, lib_names: list[str],
                       source_filter: Optional[list[str]] = None) -> dict:
    """
    对用户已写完的文章进行引用标注：找出可以引用外部文献的句子，
    标记具体文献和匹配的切片段落

    Args:
        article_text: 用户已完成的文章全文
        lib_names: 关联的文献库
        source_filter: 文件名过滤（可选）

    Returns:
        {
            "annotated_text": str,  # 标注后的文章
            "citations": list[dict],  # 每条引用建议
            "total_suggestions": int
        }
    """
    # 将文章按段落拆分，逐段检索匹配文献
    paragraphs = [p.strip() for p in article_text.split("\n") if p.strip()]

    # 对每个段落检索相关文献块
    paragraph_matches = []
    all_matched_chunks = []

    for i, para in enumerate(paragraphs):
        if len(para) < 30:
            paragraph_matches.append({"paragraph_idx": i, "chunks": []})
            continue

        try:
            chunks = search_chunks(
                query=para,
                lib_names=lib_names,
                source_filter=source_filter,
                initial_k=20,
                final_k=5
            )
            # 只保留相关度较高的
            relevant = [c for c in chunks if c.get("score", 0) > 0.5]
            paragraph_matches.append({"paragraph_idx": i, "chunks": relevant})
            all_matched_chunks.extend(relevant)
        except Exception:
            paragraph_matches.append({"paragraph_idx": i, "chunks": []})

    # 构建上下文供 Claude 标注
    context_parts = []
    chunk_registry = {}
    chunk_counter = 0

    for pm in paragraph_matches:
        for c in pm["chunks"]:
            chunk_id = c["id"]
            if chunk_id not in chunk_registry:
                chunk_counter += 1
                chunk_registry[chunk_id] = {
                    "ref_id": chunk_counter,
                    "source": c["metadata"].get("source", "未知来源"),
                    "text": c["document"][:600],
                    "score": c.get("score", 0)
                }

    if chunk_registry:
        for cid, info in chunk_registry.items():
            context_parts.append(
                f"[参考{info['ref_id']}] 来源: {info['source']} (相关度: {info['score']:.3f})\n{info['text']}"
            )

    ref_context = "\n\n---\n\n".join(context_parts) if context_parts else ""

    system_prompt = """你是一位专精非洲文学研究的学术引用标注助手。你的任务是审读用户的文章，找出适合引用外部文献来支撑的句子或观点，并标注具体应引用哪篇文献的哪个段落。

工作原则：
- 只建议确实能被提供的文献段落所支撑的引用
- 标注位置应是：事实性陈述、他人观点转述、可被文献佐证的论断
- 不要为纯主观判断或过渡句建议引用
- 输出格式要清晰，便于用户直接采纳"""

    user_content = f"""请审读以下文章，找出可以引用外部文献的位置，并标注具体文献。

===== 用户文章 =====
{article_text}

"""

    if ref_context:
        user_content += f"""===== 可引用的文献段落 =====
{ref_context}

"""

    user_content += """===== 输出要求 =====
请按以下格式输出：

对文章中每个可引用的位置：
1. 【原文句子】：摘出文章中的原句
2. 【建议引用】：[参考X] — 来源文件名
3. 【匹配理由】：简述为何该文献段落可以支撑此句（1-2句话）
4. 【引用建议】：给出具体的引文整合方式（如"可改写为：……（某某, 年份）"）

最后给出一个总结：共标注了多少处可引用位置，涉及多少篇文献。"""

    annotated = call_claude(
        system_prompt=system_prompt,
        user_content=user_content,
        max_tokens=CHAT_MAX_TOKENS
    )

    citations = [
        {
            "ref_id": info["ref_id"],
            "source": info["source"],
            "text_preview": info["text"][:200],
            "score": info["score"]
        }
        for info in chunk_registry.values()
    ]

    return {
        "annotated_text": annotated,
        "citations": citations,
        "total_suggestions": len(chunk_registry)
    }