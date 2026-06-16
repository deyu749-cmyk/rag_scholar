"""
检索器
- AI 自动路由（chunks vs summaries）
- Cohere Rerank 重排序
- 双层检索（向量块 + 摘要）
- 深度分析
"""

import requests
from typing import Optional

from config import (
    LEVOLINK_API_BASE, LEVOLINK_API_KEY,
    COHERE_API_KEY, COHERE_RERANK_MODEL,
    CHAT_MODEL, CHAT_MAX_TOKENS,
    INITIAL_RETRIEVE_K, FINAL_TOP_K,
    SUMMARY_COLLECTION_SUFFIX,
    ROUTE_SYSTEM_PROMPT, ANALYSIS_SYSTEM_PROMPT,
    GAP_ANALYSIS_SYSTEM_PROMPT
)
from indexer import (
    chroma_client, get_collection, get_summary_collection,
    get_single_embedding, call_claude
)

import os
import requests

# 配置代理（从环境变量读取或使用默认值）
proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or "http://127.0.0.1:7897"
proxies = {
    "http": proxy_url,
    "https": proxy_url,
}

# 创建全局 Session（连接复用）
cohere_session = requests.Session()
cohere_session.proxies.update(proxies)


# ===== Cohere Rerank =====
def cohere_rerank(query: str, documents: list[str], top_n: int = FINAL_TOP_K) -> list[dict]:
    """
    调用 Cohere Rerank API 重排序

    Args:
        query: 用户查询
        documents: 待重排的文档列表
        top_n: 返回前 N 条

    Returns:
        [{"index": int, "relevance_score": float}, ...]
    """
    if not documents:
        return []

    # Cohere 限制单次最多 1000 条
    documents = documents[:1000]

    headers = {
        "Authorization": f"Bearer {COHERE_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": COHERE_RERANK_MODEL,
        "query": query,
        "documents": documents,
        "top_n": top_n,
        "return_documents": False
    }

    response = cohere_session.post(
        "https://api.cohere.com/v2/rerank",
        headers=headers,
        json=payload,
        timeout=30
    )
    response.raise_for_status()
    data = response.json()

    return [
        {"index": r["index"], "relevance_score": r["relevance_score"]}
        for r in data["results"]
    ]


# ===== 查询路由 =====
def route_query(query: str) -> str:
    """
    AI 判断查询类型
    返回 "chunks" 或 "summaries"
    """
    try:
        result = call_claude(
            system_prompt=ROUTE_SYSTEM_PROMPT,
            user_content=query,
            max_tokens=10
        )
        result = result.strip().upper()
        if "B" in result:
            return "summaries"
        return "chunks"
    except Exception:
        # 默认走 chunks
        return "chunks"


# ===== 向量块检索 =====
def search_chunks(query: str, lib_names: list[str],
                  source_filter: Optional[list[str]] = None,
                  initial_k: int = INITIAL_RETRIEVE_K,
                  final_k: int = FINAL_TOP_K) -> list[dict]:
    """
    向量块检索 + Cohere Rerank

    Args:
        query: 用户查询
        lib_names: 要检索的库名列表
        source_filter: 文件名过滤（可选）
        initial_k: 初检数量
        final_k: Rerank 后最终数量

    Returns:
        [{"id": str, "document": str, "metadata": dict, "score": float}, ...]
    """
    # 生成查询向量
    query_embedding = get_single_embedding(query)

    # 从多个库检索
    all_results = []

    for lib_name in lib_names:
        try:
            collection = get_collection(lib_name)
        except Exception:
            continue

        # 构建 where 过滤条件
        where_filter = None
        if source_filter:
            if len(source_filter) == 1:
                where_filter = {"source": source_filter[0]}
            else:
                where_filter = {"source": {"$in": source_filter}}

        # 排除 file_hash 类型的记录
        where_base = {"type": {"$ne": "file_hash"}}
        if where_filter:
            where_filter = {"$and": [where_base, where_filter]}
        else:
            where_filter = where_base

        try:
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=initial_k,
                where=where_filter,
                include=["documents", "metadatas", "distances"]
            )
        except Exception:
            # 如果 where 过滤失败（比如 collection 为空），尝试不带过滤
            try:
                results = collection.query(
                    query_embeddings=[query_embedding],
                    n_results=initial_k,
                    include=["documents", "metadatas", "distances"]
                )
            except Exception:
                continue

        if results and results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                metadata = results["metadatas"][0][i] if results["metadatas"] else {}
                # 跳过 hash 记录
                if metadata.get("type") == "file_hash":
                    continue
                all_results.append({
                    "id": doc_id,
                    "document": results["documents"][0][i],
                    "metadata": metadata,
                    "distance": results["distances"][0][i] if results["distances"] else 0
                })

    if not all_results:
        return []

    # Cohere Rerank
    documents_for_rerank = [r["document"] for r in all_results]

    try:
        rerank_results = cohere_rerank(
            query=query,
            documents=documents_for_rerank,
            top_n=min(final_k, len(all_results))
        )

        # 按 rerank 结果重排
        final_results = []
        for rr in rerank_results:
            idx = rr["index"]
            item = all_results[idx].copy()
            item["score"] = rr["relevance_score"]
            final_results.append(item)

        return final_results

    except Exception as e:
        # Rerank 失败时，按原始距离排序返回
        print(f"Cohere Rerank 失败，使用原始排序: {e}")
        all_results.sort(key=lambda x: x["distance"])
        for item in all_results:
            item["score"] = 1 - item["distance"]  # 转换为相似度分数
        return all_results[:final_k]


# ===== 摘要集合检索 =====
def search_summaries(query: str, lib_names: list[str],
                     source_filter: Optional[list[str]] = None,
                     initial_k: int = 30,
                     final_k: int = 15) -> list[dict]:
    """
    摘要集合检索 + Cohere Rerank

    Args:
        query: 用户查询
        lib_names: 要检索的库名列表
        initial_k: 初检数量
        final_k: Rerank 后最终数量

    Returns:
        [{"id": str, "document": str, "metadata": dict, "score": float}, ...]
    """
    query_embedding = get_single_embedding(query)

    all_results = []

    for lib_name in lib_names:
        try:
            summary_collection = get_summary_collection(lib_name)
        except Exception:
            continue

        where_filter = None
        if source_filter:
            if len(source_filter) == 1:
                where_filter = {"source": source_filter[0]}
            else:
                where_filter = {"source": {"$in": source_filter}}

        try:
            kwargs = {
                "query_embeddings": [query_embedding],
                "n_results": initial_k,
                "include": ["documents", "metadatas", "distances"]
            }
            if where_filter:
                kwargs["where"] = where_filter
            results = summary_collection.query(**kwargs)
        except Exception:
            continue

        if results and results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                all_results.append({
                    "id": doc_id,
                    "document": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "distance": results["distances"][0][i] if results["distances"] else 0
                })

    if not all_results:
        return []

    # Cohere Rerank
    documents_for_rerank = [r["document"] for r in all_results]

    try:
        rerank_results = cohere_rerank(
            query=query,
            documents=documents_for_rerank,
            top_n=min(final_k, len(all_results))
        )

        final_results = []
        for rr in rerank_results:
            idx = rr["index"]
            item = all_results[idx].copy()
            item["score"] = rr["relevance_score"]
            final_results.append(item)

        return final_results

    except Exception as e:
        print(f"Cohere Rerank 失败（摘要），使用原始排序: {e}")
        all_results.sort(key=lambda x: x["distance"])
        for item in all_results:
            item["score"] = 1 - item["distance"]
        return all_results[:final_k]


# ===== 深度分析（基于向量块）=====
def analyze_with_chunks(query: str, results: list[dict]) -> str:
    """
    基于检索到的向量块，调用 Claude 进行深度学术分析

    Args:
        query: 用户问题
        results: 检索结果列表

    Returns:
        Claude 的分析文本
    """
    if not results:
        return "未检索到相关文献段落，请尝试调整查询或选择其他文献库。"

    # 构建上下文
    context_parts = []
    for i, r in enumerate(results):
        source = r["metadata"].get("source", "未知来源")
        score = r.get("score", 0)
        context_parts.append(
            f"[段落{i + 1}] 来源: {source} | 相关度: {score:.3f}\n{r['document']}"
        )

    context = "\n\n---\n\n".join(context_parts)

    user_content = f"""用户问题：{query}

以下是检索到的相关文献段落：

{context}
引用规则：当参考上述文献段落时，必须使用 [段落X] 或 [文献X] 的格式标注来源，例如：“如[段落3]所述...”
请基于以上文献段落，对用户的问题进行深度学术分析。"""

    return call_claude(
        system_prompt=ANALYSIS_SYSTEM_PROMPT,
        user_content=user_content,
        max_tokens=CHAT_MAX_TOKENS
    )


# ===== 研究空白分析（基于摘要）=====
def analyze_with_summaries(query: str, results: list[dict]) -> str:
    """
    基于检索到的文献摘要，调用 Claude 进行全局分析

    Args:
        query: 用户问题
        results: 摘要检索结果列表

    Returns:
        Claude 的分析文本
    """
    if not results:
        return "未检索到相关文献摘要。请确认已为该库生成 AI 摘要。"

    # 构建上下文
    context_parts = []
    for i, r in enumerate(results):
        source = r["metadata"].get("source", "未知来源")
        context_parts.append(
            f"[文献{i + 1}] {source}\n{r['document']}"
        )

    context = "\n\n---\n\n".join(context_parts)

    user_content = f"""用户问题：{query}

以下是相关文献的 AI 摘要（共 {len(results)} 篇）：

{context}

请基于以上文献摘要集合，回答用户的问题。"""

    return call_claude(
        system_prompt=GAP_ANALYSIS_SYSTEM_PROMPT,
        user_content=user_content,
        max_tokens=CHAT_MAX_TOKENS
    )


def translate_query(query: str, target_lang: str) -> str:
    """使用 Claude 翻译查询"""
    system_prompt = f"将以下文本翻译为{target_lang}，只返回译文，不要解释。"
    return call_claude(system_prompt=system_prompt, user_content=query, max_tokens=200)

def search_and_analyze(query, lib_names, source_filter=None, mode=None):
    # 判断是否需要翻译（简单检测是否包含中文）
    if any('\u4e00' <= c <= '\u9fff' for c in query):
        try:
            en_query = translate_query(query, "英文")
        except:
            en_query = query
    else:
        en_query = query

    # 确定检索模式
    if mode:
        search_mode = mode
    else:
        search_mode = route_query(query)  # 可以用中文 query 路由

    if search_mode == "summaries":
        # 摘要检索也支持双查询
        results_cn = search_summaries(query, lib_names, source_filter=source_filter)
        if en_query != query:
            results_en = search_summaries(en_query, lib_names, source_filter=source_filter)
            # 合并去重（根据 id）
            seen = {r['id'] for r in results_cn}
            for r in results_en:
                if r['id'] not in seen:
                    results_cn.append(r)
        results = results_cn
        analysis = analyze_with_summaries(query, results)
    else:
        results_cn = search_chunks(query, lib_names, source_filter=source_filter)
        if en_query != query:
            results_en = search_chunks(en_query, lib_names, source_filter=source_filter)
            seen = {r['id'] for r in results_cn}
            for r in results_en:
                if r['id'] not in seen:
                    results_cn.append(r)
        results = results_cn
        analysis = analyze_with_chunks(query, results)

    return {"mode": search_mode, "results": results, "analysis": analysis, "query": query}

# ===== 总结功能 =====
def summarize_conversation(conversation_history: list[dict]) -> str:
    """
    总结对话历史

    Args:
        conversation_history: [{"role": "user"|"assistant", "content": str}, ...]

    Returns:
        总结文本
    """
    history_text = ""
    for msg in conversation_history:
        role = "用户" if msg["role"] == "user" else "AI"
        history_text += f"{role}: {msg['content']}\n\n"

    system_prompt = """你是一位学术研究助手。请对以下对话内容进行学术性总结。

要求：
1. 提炼核心研究问题和发现
2. 整理关键文献引用
3. 标注尚未解决的问题
4. 建议后续研究方向
5. 语言与对话主要语言一致
"""

    return call_claude(
        system_prompt=system_prompt,
        user_content=f"请总结以下研究对话：\n\n{history_text}",
        max_tokens=4096
    )


# ===== 重新检查（审稿人模式）=====
def recheck_analysis(original_query: str, original_analysis: str,
                     results: list[dict]) -> str:
    """
    以审稿人视角重新审视分析结果

    Args:
        original_query: 原始问题
        original_analysis: 原始分析
        results: 原始检索结果

    Returns:
        审查意见
    """
    context_parts = []
    for i, r in enumerate(results):
        source = r["metadata"].get("source", "未知来源")
        context_parts.append(f"[段落{i + 1}] {source}\n{r['document']}")

    context = "\n\n---\n\n".join(context_parts)

    system_prompt = """你是一位严格的学术审稿人。请审查以下 AI 生成的学术分析。

审查维度：
1. 事实准确性：分析中的观点是否有文献支撑？是否存在过度推断？
2. 逻辑严密性：论证链条是否完整？是否存在跳跃？
3. 引用规范性：引用标注是否准确？是否存在张冠李戴？
4. 遗漏检查：文献中是否有重要观点被忽略？
5. 平衡性：是否偏重某一视角而忽略其他？

请给出具体的修改建议和补充意见。"""

    user_content = f"""原始问题：{original_query}

AI 分析结果：
{original_analysis}

原始文献段落：
{context}

请以审稿人身份审查上述分析。"""

    return call_claude(
        system_prompt=system_prompt,
        user_content=user_content,
        max_tokens=CHAT_MAX_TOKENS
    )