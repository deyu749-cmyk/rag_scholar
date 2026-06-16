"""
统一聊天路由
- 意图分类（两阶段 call_claude）
- 分派到对应的后端函数
- 合成最终对话回复
"""

import json
import re
from typing import Optional

from config import (
    INTENT_ROUTER_PROMPT, CHAT_SYNTHESIS_PROMPT,
    CHAT_MODEL, CHAT_MAX_TOKENS
)
from indexer import call_claude, call_claude_multi
from retriever import search_and_analyze
from writer import academic_rewrite, generate_literature_review, annotate_citations


def _parse_intent_json(raw: str) -> dict:
    """从模型输出中提取 intent JSON，带容错回退"""
    # 尝试直接解析
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        pass

    # 尝试提取 { ... } 块
    match = re.search(r'\{[^{}]*\}', raw)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    # 回退为 CHAT
    return {"intent": "CHAT", "params": {}}


def _execute_intent(intent: str, params: dict,
                    lib_names: list[str]) -> dict:
    """根据意图执行对应的后端函数，返回结果字典"""
    result = {"intent": intent, "data": None, "error": None}

    try:
        if intent == "SEARCH":
            query = params.get("query", "")
            mode = params.get("mode", None)
            if not query:
                result["error"] = "检索查询为空"
            else:
                r = search_and_analyze(
                    query=query, lib_names=lib_names, mode=mode
                )
                result["data"] = {
                    "analysis": r["analysis"],
                    "results": [
                        {
                            "document": item["document"],
                            "source": item["metadata"].get("source", ""),
                            "score": round(item.get("score", 0), 4)
                        }
                        for item in r["results"]
                    ],
                    "mode": r["mode"]
                }

        elif intent == "REWRITE":
            text = params.get("text", "")
            style = params.get("style", "polish")
            if not text:
                result["error"] = "待处理文本为空"
            else:
                r = academic_rewrite(
                    user_text=text, lib_names=lib_names, style=style
                )
                result["data"] = {
                    "rewritten_text": r["rewritten_text"],
                    "references_used": r["references_used"],
                    "style": r["style"]
                }

        elif intent == "REVIEW":
            topic = params.get("topic", "")
            scope = params.get("scope", "review")
            if not topic:
                result["error"] = "综述主题为空"
            else:
                r = generate_literature_review(
                    topic=topic, lib_names=lib_names, scope=scope
                )
                result["data"] = {
                    "text": r["text"],
                    "references_used": r["references_used"],
                    "scope": r["scope"]
                }

        elif intent == "ANNOTATE":
            text = params.get("text", "")
            if not text:
                result["error"] = "待标注文章为空"
            else:
                r = annotate_citations(
                    article_text=text, lib_names=lib_names
                )
                result["data"] = {
                    "annotated_text": r["annotated_text"],
                    "citations": r["citations"],
                    "total_suggestions": r["total_suggestions"]
                }

        elif intent == "CHAT":
            result["data"] = None

        else:
            result["error"] = f"未知意图: {intent}"

    except Exception as e:
        result["error"] = str(e)

    return result


def _format_execution_result(exec_result: dict) -> str:
    """将函数执行结果格式化为文本，供合成阶段使用"""
    intent = exec_result["intent"]
    data = exec_result.get("data")

    if exec_result.get("error"):
        return f"执行失败: {exec_result['error']}"

    if intent == "CHAT" or data is None:
        return ""

    if intent == "SEARCH":
        refs = "\n".join([
            f"[段落{i+1}] 来源: {r['source']} | 相关度: {r['score']}\n{r['document'][:500]}"
            for i, r in enumerate(data.get("results", []))
        ])
        return f"检索模式: {data.get('mode', 'chunks')}\n分析结果:\n{data.get('analysis', '')}\n\n检索到的文献段落:\n{refs}"

    if intent == "REWRITE":
        refs = "\n".join([
            f"- {r['source']} (相关度: {r['score']})"
            for r in data.get("references_used", [])
        ])
        return f"风格: {data.get('style', 'polish')}\n改写结果:\n{data.get('rewritten_text', '')}\n\n参考文献:\n{refs}"

    if intent == "REVIEW":
        refs = "\n".join([
            f"- {r['source']}" for r in data.get("references_used", [])
        ])
        return f"类型: {data.get('scope', 'review')}\n生成结果:\n{data.get('text', '')}\n\n引用的文献:\n{refs}"

    if intent == "ANNOTATE":
        refs = "\n".join([
            f"[参考{r['ref_id']}] {r['source']} (相关度: {r['score']})\n{r['text_preview']}"
            for r in data.get("citations", [])
        ])
        return f"标注结果:\n{data.get('annotated_text', '')}\n\n可引用的文献段落:\n{refs}"

    return ""


def handle_chat_message(messages: list[dict],
                        lib_names: list[str]) -> dict:
    """
    统一聊天消息处理

    Args:
        messages: [{"role": "user|assistant", "content": "..."}, ...]
        lib_names: 用户选中的文献库列表

    Returns:
        {"content": str, "metadata": {"intent": str, ...}}
    """
    if not messages:
        return {"content": "请发送一条消息。", "metadata": {"intent": "CHAT"}}

    # 阶段 1：意图分类
    raw_intent = call_claude_multi(
        system_prompt=INTENT_ROUTER_PROMPT,
        messages=messages,
        max_tokens=300
    )
    intent_info = _parse_intent_json(raw_intent)
    intent = intent_info.get("intent", "CHAT")
    params = intent_info.get("params", {})

    # 阶段 2a：执行后端函数
    exec_result = _execute_intent(intent, params, lib_names)

    # 阶段 2b：合成最终回复
    if intent == "CHAT" and not exec_result.get("error"):
        # 直接以对话形式回复
        final = call_claude_multi(
            system_prompt=CHAT_SYNTHESIS_PROMPT,
            messages=messages,
            max_tokens=CHAT_MAX_TOKENS
        )
        return {
            "content": final,
            "metadata": {"intent": intent}
        }

    # 其他意图：拼接执行结果后再合成
    result_text = _format_execution_result(exec_result)

    synthesis_messages = list(messages)
    synthesis_messages.append({
        "role": "user",
        "content": f"【系统内部执行结果 — 不要直接输出原始JSON。请基于以下内容，用自然对话回复用户上一条消息】\n\n{result_text}"
    })

    final = call_claude_multi(
        system_prompt=CHAT_SYNTHESIS_PROMPT,
        messages=synthesis_messages,
        max_tokens=CHAT_MAX_TOKENS
    )

    return {
        "content": final,
        "metadata": {
            "intent": intent,
            "params": params,
            "error": exec_result.get("error")
        }
    }
