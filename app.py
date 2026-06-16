"""
Flask 主应用
"""

import os
import json
import queue
import threading
from flask import Flask, request, jsonify, Response, send_from_directory
from flask_cors import CORS

from config import PAPERS_DIR, LIBRARIES, SUMMARY_COLLECTION_SUFFIX
from indexer import (
    index_library, generate_summaries,
    chroma_client, get_collection, get_summary_collection
)
from retriever import (
    search_and_analyze, summarize_conversation, recheck_analysis
)
from writer import academic_rewrite, writing_chat, generate_literature_review, annotate_citations
from chat_router import handle_chat_message

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

app = Flask(__name__, static_folder=TEMPLATES_DIR, static_url_path="")
CORS(app)

@app.route("/")
def serve_index():
    return send_from_directory(TEMPLATES_DIR, "chat.html")


@app.route("/index-admin")
def serve_index_admin():
    return send_from_directory(TEMPLATES_DIR, "index-admin.html")


# ===== 文献库列表 =====
@app.route("/api/libs", methods=["GET"])
def get_libs():
    libs = []
    for lib_name in LIBRARIES:
        lib_path = os.path.join(PAPERS_DIR, lib_name)
        file_count = 0
        if os.path.exists(lib_path):
            file_count = len([
                f for f in os.listdir(lib_path)
                if f.lower().endswith(('.pdf', '.docx')) and not f.startswith('.')
            ])

        indexed_chunks = 0
        try:
            collection = get_collection(lib_name)
            count = collection.count()
            indexed_chunks = max(0, count - file_count)
        except Exception:
            pass

        summary_count = 0
        try:
            summary_col = get_summary_collection(lib_name)
            summary_count = summary_col.count()
        except Exception:
            pass

        libs.append({
            "name":           lib_name,
            "file_count":     file_count,
            "indexed_chunks": indexed_chunks,
            "summary_count":  summary_count,
            "has_index":      indexed_chunks > 0,
            "has_summaries":  summary_count > 0,
        })

    return jsonify({"libs": libs})


# ===== 获取库中的文件列表（仅返回已索引的文件）=====
@app.route("/api/libs/<lib_name>/files", methods=["GET"])
def get_lib_files(lib_name):
    lib_path = os.path.join(PAPERS_DIR, lib_name)
    if not os.path.exists(lib_path):
        return jsonify({"error": f"库 {lib_name} 不存在"}), 404

    all_files = sorted([
        f for f in os.listdir(lib_path)
        if f.lower().endswith(('.pdf', '.docx')) and not f.startswith('.')
    ])

    # 查询 ChromaDB 中有哪些文件已索引（有向量块）
    indexed_sources = set()
    try:
        collection = get_collection(lib_name)
        existing = collection.get(include=["metadatas"])
        if existing and existing["metadatas"]:
            for meta in existing["metadatas"]:
                if meta and meta.get("type") != "file_hash":
                    src = meta.get("source", "")
                    if src:
                        indexed_sources.add(src)
    except Exception:
        pass

    # 只返回有向量块的文件
    files = [f for f in all_files if f in indexed_sources]
    skipped = len(all_files) - len(files)

    return jsonify({
        "lib": lib_name,
        "files": files,
        "total_in_dir": len(all_files),
        "indexed": len(files),
        "skipped": skipped
    })


# ===== SSE 索引进度 =====
@app.route("/api/index", methods=["POST"])
def start_indexing():
    data = request.get_json()
    lib_names      = data.get("libs", [])
    force_rebuild  = data.get("force_rebuild", False)
    do_summaries   = data.get("generate_summaries", False)

    if not lib_names:
        return jsonify({"error": "请选择至少一个文献库"}), 400

    for lib in lib_names:
        if lib not in LIBRARIES:
            return jsonify({"error": f"未知文献库: {lib}"}), 400

    progress_queue = queue.Queue()

    def run_indexing():
        try:
            for lib_name in lib_names:
                progress_queue.put({
                    "stage": "lib_start", "lib": lib_name,
                    "message": f"===== 开始处理: {lib_name} ====="
                })

                stats = index_library(
                    lib_name=lib_name,
                    force_rebuild=force_rebuild,
                    progress_callback=lambda d: progress_queue.put(d)
                )
                progress_queue.put({
                    "stage": "lib_index_done", "lib": lib_name, "stats": stats,
                    "message": f"{lib_name} 向量索引完成"
                })

                if do_summaries:
                    summary_stats = generate_summaries(
                        lib_name=lib_name,
                        progress_callback=lambda d: progress_queue.put(d)
                    )
                    progress_queue.put({
                        "stage": "lib_summary_done", "lib": lib_name,
                        "stats": summary_stats,
                        "message": f"{lib_name} 摘要生成完成"
                    })

            progress_queue.put({"stage": "all_done", "message": "所有任务完成"})

        except Exception as e:
            progress_queue.put({"stage": "error", "message": f"索引错误: {str(e)}"})

        progress_queue.put(None)

    threading.Thread(target=run_indexing, daemon=True).start()

    def generate():
        while True:
            try:
                msg = progress_queue.get(timeout=300)
                if msg is None:
                    yield f"event: done\ndata: {json.dumps({'message': '完成'})}\n\n"
                    break
                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
            except queue.Empty:
                yield ": heartbeat\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":       "keep-alive",
        }
    )


# ===== 检索 + 分析 =====
@app.route("/api/search", methods=["POST"])
def search():
    data          = request.get_json()
    query         = data.get("query", "").strip()
    lib_names     = data.get("libs", [])
    source_filter = data.get("source_filter", None)
    mode          = data.get("mode", None)

    if not query:
        return jsonify({"error": "请输入查询内容"}), 400
    if not lib_names:
        return jsonify({"error": "请选择至少一个文献库"}), 400

    try:
        result = search_and_analyze(
            query=query,
            lib_names=lib_names,
            source_filter=source_filter,
            mode=mode
        )

        formatted_results = []
        for r in result["results"]:
            formatted_results.append({
                "document":    r["document"],
                "source":      r["metadata"].get("source", "未知来源"),
                "library":     r["metadata"].get("library", ""),
                "score":       round(r.get("score", 0), 4),
                "chunk_index": r["metadata"].get("chunk_index", -1),
            })

        return jsonify({
            "query":        result["query"],
            "mode":         result["mode"],
            "analysis":     result["analysis"],
            "results":      formatted_results,
            "result_count": len(formatted_results),
        })

    except Exception as e:
        return jsonify({"error": f"检索失败: {str(e)}"}), 500


# ===== 总结对话 =====
@app.route("/api/summarize", methods=["POST"])
def summarize():
    data    = request.get_json()
    history = data.get("history", [])
    if not history:
        return jsonify({"error": "对话历史为空"}), 400

    try:
        summary = summarize_conversation(history)
        return jsonify({"summary": summary})
    except Exception as e:
        return jsonify({"error": f"总结失败: {str(e)}"}), 500


# ===== 重新检查 =====
@app.route("/api/recheck", methods=["POST"])
def recheck():
    data              = request.get_json()
    original_query    = data.get("query", "")
    original_analysis = data.get("analysis", "")
    results           = data.get("results", [])

    if not original_analysis:
        return jsonify({"error": "缺少原始分析内容"}), 400

    try:
        review = recheck_analysis(original_query, original_analysis, results)
        return jsonify({"review": review})
    except Exception as e:
        return jsonify({"error": f"审查失败: {str(e)}"}), 500


# ===== 写作模式 =====
@app.route("/api/write", methods=["POST"])
def write():
    data          = request.get_json()
    text          = data.get("text", "").strip()
    lib_names     = data.get("libs", [])
    style         = data.get("style", "polish")
    source_filter = data.get("source_filter", None)

    if not text:
        return jsonify({"error": "请输入需要处理的文本"}), 400

    valid_styles = ["polish", "rewrite", "expand", "condense"]
    if style not in valid_styles:
        return jsonify({"error": f"无效的写作模式，可选: {valid_styles}"}), 400

    try:
        result = academic_rewrite(
            user_text=text,
            lib_names=lib_names,
            style=style,
            source_filter=source_filter
        )
        return jsonify({
            "rewritten_text":  result["rewritten_text"],
            "references_used": result["references_used"],
            "style":           result["style"],
        })
    except Exception as e:
        return jsonify({"error": f"写作处理失败: {str(e)}"}), 500


# ===== 写作对话式修改 =====
@app.route("/api/write/chat", methods=["POST"])
def write_chat():
    data        = request.get_json()
    text        = data.get("text", "").strip()
    instruction = data.get("instruction", "").strip()
    lib_names   = data.get("libs", [])
    history     = data.get("history", None)

    if not text or not instruction:
        return jsonify({"error": "请提供文本和修改指令"}), 400

    try:
        result = writing_chat(
            user_text=text,
            instruction=instruction,
            lib_names=lib_names,
            conversation_history=history
        )
        return jsonify({"result": result})
    except Exception as e:
        return jsonify({"error": f"修改失败: {str(e)}"}), 500


# ===== 文献综述/概论生成 =====
@app.route("/api/write/review", methods=["POST"])
def literature_review():
    data          = request.get_json()
    topic         = data.get("topic", "").strip()
    lib_names     = data.get("libs", [])
    source_filter = data.get("source_filter", None)
    scope         = data.get("scope", "review")

    if not topic:
        return jsonify({"error": "请输入研究主题"}), 400
    if not lib_names:
        return jsonify({"error": "请选择至少一个文献库"}), 400

    valid_scopes = ["review", "overview"]
    if scope not in valid_scopes:
        return jsonify({"error": f"无效的生成类型，可选: {valid_scopes}"}), 400

    try:
        result = generate_literature_review(
            topic=topic,
            lib_names=lib_names,
            source_filter=source_filter,
            scope=scope
        )
        return jsonify({
            "text":            result["text"],
            "references_used": result["references_used"],
            "scope":           result["scope"],
        })
    except Exception as e:
        return jsonify({"error": f"文献综述生成失败: {str(e)}"}), 500


# ===== 引用标注 =====
@app.route("/api/write/annotate", methods=["POST"])
def citation_annotate():
    data          = request.get_json()
    text          = data.get("text", "").strip()
    lib_names     = data.get("libs", [])
    source_filter = data.get("source_filter", None)

    if not text:
        return jsonify({"error": "请输入需要标注的文章"}), 400
    if not lib_names:
        return jsonify({"error": "请选择至少一个文献库"}), 400

    try:
        result = annotate_citations(
            article_text=text,
            lib_names=lib_names,
            source_filter=source_filter
        )
        return jsonify({
            "annotated_text":    result["annotated_text"],
            "citations":         result["citations"],
            "total_suggestions": result["total_suggestions"],
        })
    except Exception as e:
        return jsonify({"error": f"引用标注失败: {str(e)}"}), 500


# ===== 统一聊天端点 =====
@app.route("/api/chat", methods=["POST"])
def unified_chat():
    data = request.get_json()
    messages = data.get("messages", [])
    lib_names = data.get("libs", [])
    source_filter = data.get("files", None)  # 可选，限定检索的文件名

    if not messages:
        return jsonify({"error": "消息列表不能为空"}), 400
    if not lib_names:
        return jsonify({"error": "请选择至少一个文献库"}), 400

    try:
        result = handle_chat_message(messages, lib_names, source_filter)
        return jsonify({
            "role": "assistant",
            "content": result["content"],
            "metadata": result.get("metadata", {})
        })
    except Exception as e:
        return jsonify({"error": f"处理失败: {str(e)}"}), 500


# ===== 删除索引 =====
@app.route("/api/libs/<lib_name>/delete_index", methods=["POST"])
def delete_index(lib_name):
    if lib_name not in LIBRARIES:
        return jsonify({"error": f"未知文献库: {lib_name}"}), 400

    try:
        try:
            chroma_client.delete_collection(lib_name)
        except Exception:
            pass
        try:
            chroma_client.delete_collection(f"{lib_name}{SUMMARY_COLLECTION_SUFFIX}")
        except Exception:
            pass
        return jsonify({"message": f"已删除 {lib_name} 的索引和摘要"})
    except Exception as e:
        return jsonify({"error": f"删除失败: {str(e)}"}), 500


# ===== 系统状态 =====
@app.route("/api/status", methods=["GET"])
def system_status():
    total_chunks = total_summaries = 0
    for lib_name in LIBRARIES:
        try:
            total_chunks += get_collection(lib_name).count()
        except Exception:
            pass
        try:
            total_summaries += get_summary_collection(lib_name).count()
        except Exception:
            pass

    return jsonify({
        "status":           "running",
        "total_chunks":     total_chunks,
        "total_summaries":  total_summaries,
        "libraries":        LIBRARIES,
        "papers_dir":       os.path.abspath(PAPERS_DIR),
    })


# ===== 启动 =====
if __name__ == "__main__":
    os.makedirs(PAPERS_DIR, exist_ok=True)
    for lib in LIBRARIES:
        os.makedirs(os.path.join(PAPERS_DIR, lib), exist_ok=True)

    print("=" * 50)
    print("  学术 RAG 系统 v2.0")
    print("  http://127.0.0.1:5000")
    print("=" * 50)

    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)