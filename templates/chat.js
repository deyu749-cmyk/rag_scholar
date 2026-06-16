// ===== RAG Scholar Chat =====

const STORAGE_KEY = 'rag_scholar_chat';
const STORAGE_LIBS_KEY = 'rag_scholar_chat_libs';

let chatMessages = [];
let selectedLibs = [];
let allLibraries = [];
let isLoading = false;

// ===== Init =====
document.addEventListener('DOMContentLoaded', () => {
    loadLibs();
    loadChatHistory();
    autoResizeInput();
});

// ===== Load Libraries =====
async function loadLibs() {
    try {
        const res = await fetch('/api/libs');
        const data = await res.json();
        allLibraries = data.libs || [];
        renderLibChips();
        restoreSelectedLibs();
    } catch (e) {
        console.error('加载文献库失败:', e);
    }
}

function renderLibChips() {
    const container = document.getElementById('lib-bar');
    // Keep the label span, remove chips
    const chips = container.querySelectorAll('.lib-chip');
    chips.forEach(c => c.remove());

    allLibraries.forEach(lib => {
        const chip = document.createElement('span');
        chip.className = 'lib-chip';
        chip.dataset.lib = lib.name;
        chip.innerHTML = `${lib.name} <span class="chip-count">${lib.file_count}篇</span>`;
        chip.onclick = () => toggleLib(lib.name, chip);

        if (selectedLibs.includes(lib.name)) {
            chip.classList.add('active');
        }

        container.appendChild(chip);
    });
}

function toggleLib(libName, chipEl) {
    const idx = selectedLibs.indexOf(libName);
    if (idx >= 0) {
        selectedLibs.splice(idx, 1);
        chipEl.classList.remove('active');
    } else {
        selectedLibs.push(libName);
        chipEl.classList.add('active');
    }
    saveLibSelection();
}

function restoreSelectedLibs() {
    try {
        const saved = localStorage.getItem(STORAGE_LIBS_KEY);
        if (saved) {
            selectedLibs = JSON.parse(saved);
            // Re-apply active class
            document.querySelectorAll('.lib-chip').forEach(chip => {
                if (selectedLibs.includes(chip.dataset.lib)) {
                    chip.classList.add('active');
                }
            });
        }
        // Default to all if nothing saved
        if (selectedLibs.length === 0 && allLibraries.length > 0) {
            allLibraries.forEach(l => {
                if (!selectedLibs.includes(l.name)) {
                    selectedLibs.push(l.name);
                }
            });
            document.querySelectorAll('.lib-chip').forEach(chip => {
                chip.classList.add('active');
            });
            saveLibSelection();
        }
    } catch (e) {
        selectedLibs = allLibraries.map(l => l.name);
        saveLibSelection();
    }
}

function saveLibSelection() {
    try {
        localStorage.setItem(STORAGE_LIBS_KEY, JSON.stringify(selectedLibs));
    } catch (e) {}
}

// ===== Chat =====
function handleInputKey(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
}

function autoResizeInput() {
    const input = document.getElementById('chat-input');
    input.addEventListener('input', () => {
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 200) + 'px';
    });
}

async function sendMessage() {
    const input = document.getElementById('chat-input');
    const text = input.value.trim();
    if (!text || isLoading) return;

    if (selectedLibs.length === 0) {
        showToast('请先选择至少一个文献库');
        return;
    }

    // Add user message
    chatMessages.push({ role: 'user', content: text });
    input.value = '';
    input.style.height = 'auto';
    hideEmptyState();
    renderAllMessages();

    // Show loading
    isLoading = true;
    document.getElementById('send-btn').disabled = true;
    const loadingId = showTypingIndicator();

    try {
        const res = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                messages: chatMessages,
                libs: selectedLibs
            })
        });
        const data = await res.json();

        if (data.error) {
            showErrorBanner(data.error);
            // Remove the user message we just added
            chatMessages.pop();
            renderAllMessages();
        } else {
            chatMessages.push({
                role: 'assistant',
                content: data.content,
                metadata: data.metadata
            });
            renderAllMessages();
        }
    } catch (e) {
        showErrorBanner('网络错误: ' + e.message);
        chatMessages.pop();
        renderAllMessages();
    } finally {
        isLoading = false;
        document.getElementById('send-btn').disabled = false;
        removeTypingIndicator(loadingId);
        saveChatHistory();

        // Scroll to bottom
        const chatArea = document.getElementById('chat-area');
        chatArea.scrollTop = chatArea.scrollHeight;
    }
}

function renderAllMessages() {
    const chatArea = document.getElementById('chat-area');
    // Remove all message rows (keep chat-empty if it exists)
    const rows = chatArea.querySelectorAll('.message-row, .typing-indicator-row, .error-banner');
    rows.forEach(r => r.remove());

    if (chatMessages.length === 0) {
        document.getElementById('chat-empty').style.display = '';
        return;
    }

    chatMessages.forEach((msg, idx) => {
        const row = createMessageRow(msg, idx);
        chatArea.appendChild(row);
    });

    // Scroll
    chatArea.scrollTop = chatArea.scrollHeight;
}

function createMessageRow(msg, idx) {
    const row = document.createElement('div');
    row.className = 'message-row ' + msg.role;

    // Avatar
    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = msg.role === 'user' ? '我' : 'AI';

    // Bubble
    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';
    bubble.innerHTML = formatContent(msg.content);

    row.appendChild(avatar);
    row.appendChild(bubble);

    // Actions (for assistant messages)
    if (msg.role === 'assistant') {
        const actions = document.createElement('div');
        actions.className = 'message-actions';
        actions.innerHTML = `
            <button class="msg-action-btn" onclick="copyMessage(${idx})" title="复制">复制</button>
            <button class="msg-action-btn" onclick="regenerateMessage(${idx})" title="重新生成">重新生成</button>
        `;
        bubble.appendChild(actions);
    }

    return row;
}

function formatContent(text) {
    let html = escapeHtml(text);

    // Parse [段落N]
    html = html.replace(/\[段落(\d+)\]/g, (match, num) => {
        return `<span class="ref-toggle" onclick="toggleRef(this)">[段落${num}]</span><div class="ref-block">文献段落 ${num}</div>`;
    });

    // Parse [文献N]
    html = html.replace(/\[文献(\d+)\]/g, (match, num) => {
        return `<span class="ref-toggle" onclick="toggleRef(this)">[文献${num}]</span><div class="ref-block">文献来源 ${num}</div>`;
    });

    // Parse [参考N]
    html = html.replace(/\[参考(\d+)\]/g, (match, num) => {
        return `<span class="ref-toggle" onclick="toggleRef(this)">[参考${num}]</span><div class="ref-block">引用文献 ${num}</div>`;
    });

    return html;
}

function toggleRef(el) {
    const block = el.nextElementSibling;
    if (block && block.classList.contains('ref-block')) {
        block.classList.toggle('show');
    }
}

function showTypingIndicator() {
    const id = 'typing-' + Date.now();
    const row = document.createElement('div');
    row.className = 'message-row assistant typing-indicator-row';
    row.id = id;
    row.innerHTML = `
        <div class="message-avatar" style="background:#292524;color:#f59e0b;border:1px solid #44403c;">AI</div>
        <div class="typing-indicator">
            <div class="dot"></div><div class="dot"></div><div class="dot"></div>
        </div>
    `;
    document.getElementById('chat-area').appendChild(row);
    document.getElementById('chat-area').scrollTop = document.getElementById('chat-area').scrollHeight;
    return id;
}

function removeTypingIndicator(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
}

function hideEmptyState() {
    const empty = document.getElementById('chat-empty');
    if (empty) empty.style.display = 'none';
}

function showErrorBanner(msg) {
    const chatArea = document.getElementById('chat-area');
    const banner = document.createElement('div');
    banner.className = 'error-banner';
    banner.textContent = '错误: ' + msg;
    chatArea.appendChild(banner);
    setTimeout(() => banner.remove(), 8000);
}

// ===== Actions =====
function copyMessage(idx) {
    const msg = chatMessages[idx];
    if (!msg) return;
    navigator.clipboard.writeText(msg.content).then(() => {
        showToast('已复制到剪贴板');
    }).catch(() => {
        const ta = document.createElement('textarea');
        ta.value = msg.content;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        showToast('已复制到剪贴板');
    });
}

async function regenerateMessage(idx) {
    if (isLoading) return;
    // Remove from idx onwards, keep up to idx-1
    chatMessages = chatMessages.slice(0, idx);
    renderAllMessages();

    // Re-send the request (simulate clicking send on the last user message)
    const lastUserMsg = chatMessages[chatMessages.length - 1];
    if (!lastUserMsg || lastUserMsg.role !== 'user') return;

    isLoading = true;
    document.getElementById('send-btn').disabled = true;
    const loadingId = showTypingIndicator();

    try {
        const res = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                messages: chatMessages,
                libs: selectedLibs
            })
        });
        const data = await res.json();

        if (data.error) {
            showErrorBanner(data.error);
        } else {
            chatMessages.push({
                role: 'assistant',
                content: data.content,
                metadata: data.metadata
            });
        }
    } catch (e) {
        showErrorBanner('网络错误: ' + e.message);
    } finally {
        isLoading = false;
        document.getElementById('send-btn').disabled = false;
        removeTypingIndicator(loadingId);
        renderAllMessages();
        saveChatHistory();
    }
}

function clearChat() {
    if (chatMessages.length === 0) return;
    if (!confirm('确定要清空当前对话吗？此操作不可撤销。')) return;
    chatMessages = [];
    renderAllMessages();
    document.getElementById('chat-empty').style.display = '';
    saveChatHistory();
    showToast('对话已清空');
}

// ===== Persistence =====
function saveChatHistory() {
    try {
        // Only persist last 50 messages
        const toSave = chatMessages.slice(-50);
        localStorage.setItem(STORAGE_KEY, JSON.stringify(toSave));
    } catch (e) {}
}

function loadChatHistory() {
    try {
        const saved = localStorage.getItem(STORAGE_KEY);
        if (saved) {
            chatMessages = JSON.parse(saved);
            if (chatMessages.length > 0) {
                hideEmptyState();
                renderAllMessages();
                // Scroll to bottom after render
                setTimeout(() => {
                    const chatArea = document.getElementById('chat-area');
                    chatArea.scrollTop = chatArea.scrollHeight;
                }, 100);
            }
        }
    } catch (e) {}
}

// ===== Toast =====
let toastTimer = null;
function showToast(msg) {
    const toast = document.getElementById('toast');
    toast.textContent = msg;
    toast.classList.add('show');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
        toast.classList.remove('show');
    }, 2000);
}

// ===== Escape HTML =====
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
