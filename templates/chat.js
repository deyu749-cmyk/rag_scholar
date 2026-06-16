// ===== RAG Scholar Chat =====

const STORAGE_KEY = 'rag_scholar_chat';
const STORAGE_LIBS_KEY = 'rag_scholar_chat_libs';
const STORAGE_FILES_KEY = 'rag_scholar_chat_files';
const STORAGE_CONVS_KEY = 'rag_scholar_conversations';
const STORAGE_ACTIVE_CONV = 'rag_scholar_active_conv';

let chatMessages = [];
let selectedLibs = [];
let selectedFiles = [];  // source_filter for per-paper selection
let allLibraries = [];
let allPapers = {};  // {lib_name: [filename, ...]}
let isLoading = false;
let activeConversationId = null;

// ===== Init =====
document.addEventListener('DOMContentLoaded', () => {
    loadLibs();
    loadConversationList();
    autoResizeInput();
    document.addEventListener('click', (e) => {
        const dd = document.getElementById('conv-dropdown');
        const mgr = document.getElementById('conv-manager');
        if (dd && mgr && !mgr.contains(e.target)) {
            dd.classList.remove('show');
        }
    });
});

// ===== Load Libraries =====
async function loadLibs() {
    try {
        const res = await fetch('/api/libs');
        const data = await res.json();
        allLibraries = data.libs || [];
        renderLibChips();
        restoreSelectedLibs();
        loadActiveConversation();
    } catch (e) {
        console.error('加载文献库失败:', e);
    }
}

function renderLibChips() {
    const bar = document.getElementById('lib-bar');
    // Clear all chips, keep label and hint
    bar.querySelectorAll('.lib-chip, .paper-toggle-btn').forEach(c => c.remove());

    allLibraries.forEach(lib => {
        const chip = document.createElement('span');
        chip.className = 'lib-chip';
        chip.dataset.lib = lib.name;
        chip.innerHTML = `${lib.name} <span class="chip-count">${lib.file_count}篇</span>`;
        chip.onclick = (e) => {
            e.stopPropagation();
            toggleLib(lib.name, chip);
        };

        if (selectedLibs.includes(lib.name)) {
            chip.classList.add('active');
        }

        bar.appendChild(chip);
    });

    // Add paper toggle button
    if (allLibraries.length > 0) {
        const toggleBtn = document.createElement('span');
        toggleBtn.className = 'paper-toggle-btn';
        toggleBtn.textContent = '📋 筛选文献';
        toggleBtn.title = '按具体文献筛选';
        toggleBtn.onclick = togglePaperPanel;
        bar.appendChild(toggleBtn);
    }

    updateLibBarHint();
}

function updateLibBarHint() {
    const hint = document.getElementById('lib-bar-hint');
    if (!hint) return;
    if (selectedLibs.length === 0) {
        hint.textContent = '请选择文献库以开始';
        hint.style.color = '#ef4444';
    } else {
        const n = selectedFiles.length > 0 ? selectedFiles.length : '全部';
        hint.textContent = `已选 ${selectedLibs.length} 个库 · ${n} 篇文献`;
        hint.style.color = '#f59e0b';
    }
}

function toggleLib(libName, chipEl) {
    const idx = selectedLibs.indexOf(libName);
    if (idx >= 0) {
        selectedLibs.splice(idx, 1);
        if (chipEl) chipEl.classList.remove('active');
        // Clear selected files for this lib
        selectedFiles = selectedFiles.filter(f => !allPapers[libName] || !allPapers[libName].includes(f));
    } else {
        selectedLibs.push(libName);
        if (chipEl) chipEl.classList.add('active');
        // When selecting a lib, auto-load its papers if not cached
        if (!allPapers[libName]) loadLibFiles(libName);
    }
    saveLibSelection();
    updateLibBarHint();
    // Rebuild paper list if panel is open
    if (document.getElementById('paper-panel').style.display !== 'none') {
        buildPaperList();
    }
}

function restoreSelectedLibs() {
    try {
        const saved = localStorage.getItem(STORAGE_LIBS_KEY);
        if (saved) {
            selectedLibs = JSON.parse(saved);
        }
        const savedFiles = localStorage.getItem(STORAGE_FILES_KEY);
        if (savedFiles) {
            selectedFiles = JSON.parse(savedFiles);
        }
        // Re-apply active class
        document.querySelectorAll('.lib-chip').forEach(chip => {
            if (selectedLibs.includes(chip.dataset.lib)) {
                chip.classList.add('active');
            }
        });
        // Preload paper lists for selected libs
        selectedLibs.forEach(lib => loadLibFiles(lib));
    } catch (e) {
        selectedLibs = [];
        selectedFiles = [];
    }
}

function saveLibSelection() {
    try {
        localStorage.setItem(STORAGE_LIBS_KEY, JSON.stringify(selectedLibs));
        localStorage.setItem(STORAGE_FILES_KEY, JSON.stringify(selectedFiles));
    } catch (e) {}
}

// ===== Paper Selection =====
async function loadLibFiles(libName) {
    if (allPapers[libName]) return;
    try {
        const res = await fetch(`/api/libs/${encodeURIComponent(libName)}/files`);
        const data = await res.json();
        allPapers[libName] = data.files || [];
    } catch (e) {
        allPapers[libName] = [];
    }
}

function togglePaperPanel() {
    const panel = document.getElementById('paper-panel');
    const isVisible = panel.style.display !== 'none';
    if (isVisible) {
        panel.style.display = 'none';
    } else {
        panel.style.display = 'block';
        // Ensure paper lists are loaded
        Promise.all(selectedLibs.map(lib => loadLibFiles(lib))).then(() => buildPaperList());
    }
}

function buildPaperList(filterText = '') {
    const container = document.getElementById('paper-list');
    container.innerHTML = '';

    const allFiles = [];
    for (const lib of selectedLibs) {
        const files = allPapers[lib] || [];
        files.forEach(f => allFiles.push({ lib, name: f }));
    }

    const filtered = filterText
        ? allFiles.filter(f => f.name.toLowerCase().includes(filterText.toLowerCase()))
        : allFiles;

    if (filtered.length === 0) {
        container.innerHTML = '<div style="color:#57534e;padding:12px;text-align:center;">暂无文献</div>';
    }

    filtered.forEach(({ lib, name }) => {
        const item = document.createElement('label');
        item.className = 'paper-item';
        const checked = selectedFiles.includes(name);
        item.innerHTML = `
            <input type="checkbox" value="${escapeHtml(name)}" ${checked ? 'checked' : ''}
                onchange="togglePaper('${escapeHtml(name)}', this.checked)">
            <span class="paper-item-name">${escapeHtml(name)}</span>
            <span class="paper-item-lib">${escapeHtml(lib)}</span>
        `;
        container.appendChild(item);
    });

    updatePaperCount();
}

function togglePaper(filename, checked) {
    if (checked) {
        if (!selectedFiles.includes(filename)) {
            selectedFiles.push(filename);
        }
    } else {
        selectedFiles = selectedFiles.filter(f => f !== filename);
    }
    saveLibSelection();
    updatePaperCount();
    updateLibBarHint();
}

function selectAllPapers() {
    for (const lib of selectedLibs) {
        const files = allPapers[lib] || [];
        files.forEach(f => {
            if (!selectedFiles.includes(f)) selectedFiles.push(f);
        });
    }
    saveLibSelection();
    buildPaperList(document.getElementById('paper-search-input')?.value || '');
    updateLibBarHint();
}

function deselectAllPapers() {
    selectedFiles = [];
    saveLibSelection();
    buildPaperList(document.getElementById('paper-search-input')?.value || '');
    updateLibBarHint();
}

function filterPapers() {
    const text = document.getElementById('paper-search-input').value;
    buildPaperList(text);
}

function updatePaperCount() {
    const el = document.getElementById('paper-count');
    if (el) el.textContent = `已选 ${selectedFiles.length} 篇`;
}

// ===== Voice Input =====
let recognition = null;
let isListening = false;

function initRecognition() {
    if (recognition) return;
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        showToast('您的浏览器不支持语音识别');
        return;
    }
    recognition = new SpeechRecognition();
    recognition.lang = 'zh-CN';
    recognition.interimResults = true;
    recognition.continuous = true;
    recognition.maxAlternatives = 1;

    recognition.onresult = (event) => {
        let transcript = '';
        for (let i = event.resultIndex; i < event.results.length; i++) {
            transcript += event.results[i][0].transcript;
        }
        const input = document.getElementById('chat-input');
        if (transcript) {
            input.value = transcript;
            input.style.height = 'auto';
            input.style.height = Math.min(input.scrollHeight, 200) + 'px';
        }
    };

    recognition.onerror = (event) => {
        console.error('语音识别错误:', event.error);
        stopListening();
        if (event.error === 'not-allowed') {
            showToast('请允许使用麦克风');
        }
    };

    recognition.onend = () => {
        if (isListening) {
            // Auto-restart if still listening
            try { recognition.start(); } catch (e) {}
        }
    };
}

function toggleVoice() {
    initRecognition();
    if (!recognition) return;

    if (isListening) {
        stopListening();
    } else {
        startListening();
    }
}

function startListening() {
    isListening = true;
    const btn = document.getElementById('mic-btn');
    btn.classList.add('listening');
    btn.title = '正在聆听... (点击停止)';
    document.getElementById('chat-input').placeholder = '🎤 正在聆听...';
    try {
        recognition.start();
        showToast('正在聆听...');
    } catch (e) {
        // Already started
    }
}

function stopListening() {
    isListening = false;
    const btn = document.getElementById('mic-btn');
    btn.classList.remove('listening');
    btn.title = '语音输入';
    document.getElementById('chat-input').placeholder = '输入你的问题或粘贴需要处理的文本...';
    try { recognition.stop(); } catch (e) {}
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

    stopListening();
    chatMessages.push({ role: 'user', content: text });
    input.value = '';
    input.style.height = 'auto';
    hideEmptyState();
    renderAllMessages();

    isLoading = true;
    document.getElementById('send-btn').disabled = true;
    const loadingId = showTypingIndicator();

    try {
        const body = {
            messages: chatMessages,
            libs: selectedLibs
        };
        // Only send source_filter if user has selected specific papers
        if (selectedFiles.length > 0) {
            body.files = selectedFiles;
        }

        const res = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        const data = await res.json();

        if (data.error) {
            showErrorBanner(data.error);
            chatMessages.pop();
            renderAllMessages();
        } else {
            chatMessages.push({
                role: 'assistant',
                content: data.content,
                metadata: data.metadata
            });
            renderAllMessages();
            // Auto-save conversation
            saveActiveConversation();
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
        const chatArea = document.getElementById('chat-area');
        chatArea.scrollTop = chatArea.scrollHeight;
    }
}

function renderAllMessages() {
    const chatArea = document.getElementById('chat-area');
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

    chatArea.scrollTop = chatArea.scrollHeight;
}

function createMessageRow(msg, idx) {
    const row = document.createElement('div');
    row.className = 'message-row ' + msg.role;

    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = msg.role === 'user' ? '我' : 'AI';

    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';

    // Use references metadata if available
    const refs = (msg.metadata && msg.metadata.references) ? msg.metadata.references : {};
    bubble.innerHTML = formatContent(msg.content, refs);

    row.appendChild(avatar);
    row.appendChild(bubble);

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

function formatContent(text, refs) {
    let html = escapeHtml(text);

    // Parse [来源N] markers — the primary citation format
    // These match references from the backend metadata
    html = html.replace(/\[来源(\d+)\]/g, (match, num) => {
        const key = `[来源${num}]`;
        const ref = refs[key];
        if (ref) {
            const source = escapeHtml(ref.source || '未知来源');
            const snippet = escapeHtml((ref.text || '').substring(0, 500));
            const score = ref.score ? ` (相关度: ${ref.score.toFixed(3)})` : '';
            return `<span class="ref-toggle" onclick="toggleRef(this)">📎 ${source}${score}</span>`
                + `<div class="ref-block"><div class="ref-source-label">出处: ${source}${score}</div>`
                + (snippet ? `<div class="ref-content">${snippet}</div>` : '')
                + `</div>`;
        }
        return `<span class="ref-toggle" onclick="toggleRef(this)">[来源${num}]</span>`
            + `<div class="ref-block">文献来源 ${num}</div>`;
    });

    // Parse legacy [段落N] markers
    html = html.replace(/\[段落(\d+)\]/g, (match, num) => {
        return `<span class="ref-toggle" onclick="toggleRef(this)">[段落${num}]</span><div class="ref-block">文献段落 ${num}</div>`;
    });

    // Parse legacy [文献N] markers
    html = html.replace(/\[文献(\d+)\]/g, (match, num) => {
        return `<span class="ref-toggle" onclick="toggleRef(this)">[文献${num}]</span><div class="ref-block">文献来源 ${num}</div>`;
    });

    // Parse legacy [参考N] markers
    html = html.replace(/\[参考(\d+)\]/g, (match, num) => {
        return `<span class="ref-toggle" onclick="toggleRef(this)">[参考${num}]</span><div class="ref-block">引用文献 ${num}</div>`;
    });

    // Also try to match source filenames that appear as clickable refs (e.g., "戈迪默——《七月的人民》.pdf")
    // This handles cases where Claude directly outputs filenames
    html = html.replace(/([^<>]+\.(pdf|docx))/gi, (match) => {
        const trimmed = match.trim();
        // Check if this filename is in our references
        for (const [key, ref] of Object.entries(refs)) {
            if (ref.source && ref.source.includes(trimmed.replace(/\.(pdf|docx)$/i, ''))) {
                return `<span class="ref-toggle file-ref" onclick="toggleRef(this)">📄 ${escapeHtml(trimmed)}</span>`
                    + `<div class="ref-block"><div class="ref-source-label">出处: ${escapeHtml(ref.source)}</div>`
                    + (ref.text ? `<div class="ref-content">${escapeHtml(ref.text.substring(0, 500))}</div>` : '')
                    + `</div>`;
            }
        }
        return match;
    });

    return html;
}

function toggleRef(el) {
    const block = el.nextElementSibling;
    if (block && block.classList.contains('ref-block')) {
        block.classList.toggle('show');
    }
}

// ===== Conversation Management =====
function loadConversationList() {
    try {
        const saved = localStorage.getItem(STORAGE_CONVS_KEY);
        const convs = saved ? JSON.parse(saved) : {};
        renderConvDropdown(Object.values(convs));
    } catch (e) {
        renderConvDropdown([]);
    }
}

function renderConvDropdown(convs) {
    const list = document.getElementById('conv-list');
    if (!list) return;
    list.innerHTML = '';

    if (convs.length === 0) {
        list.innerHTML = '<div class="conv-item-empty">暂无保存的对话</div>';
    }

    // Sort by updated time desc
    convs.sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));

    convs.forEach(conv => {
        const item = document.createElement('div');
        item.className = 'conv-item' + (conv.id === activeConversationId ? ' active' : '');
        const title = conv.title || '未命名对话';
        const date = conv.updatedAt ? new Date(conv.updatedAt).toLocaleString('zh-CN') : '';
        const msgCount = conv.messages ? conv.messages.length : 0;
        item.innerHTML = `
            <div class="conv-item-main" onclick="switchConversation('${conv.id}')">
                <span class="conv-item-title">${escapeHtml(title)}</span>
                <span class="conv-item-meta">${msgCount} 条消息 · ${date}</span>
            </div>
            <button class="conv-item-del" onclick="event.stopPropagation();deleteConversation('${conv.id}')" title="删除">✕</button>
        `;
        list.appendChild(item);
    });

    // Update label
    const label = document.getElementById('conv-label');
    if (label && activeConversationId) {
        const active = convs.find(c => c.id === activeConversationId);
        label.textContent = active ? (active.title || '未命名') : '新对话';
    }
}

function toggleConvMenu() {
    const dd = document.getElementById('conv-dropdown');
    dd.classList.toggle('show');
    loadConversationList(); // Refresh list
}

function newConversation() {
    if (chatMessages.length > 0) {
        if (!confirm('开始新对话前，是否保存当前对话？\n\n点击"确定"保存后新建，点击"取消"直接新建（不保存）。')) {
            // Just start fresh
        } else {
            saveConversationAs();
        }
    }

    chatMessages = [];
    activeConversationId = null;
    selectedLibs = [];
    selectedFiles = [];
    saveLibSelection();
    document.querySelectorAll('.lib-chip').forEach(c => c.classList.remove('active'));
    updateLibBarHint();
    document.getElementById('paper-panel').style.display = 'none';

    renderAllMessages();
    document.getElementById('chat-empty').style.display = '';
    saveChatHistory();

    const dd = document.getElementById('conv-dropdown');
    dd.classList.remove('show');
    document.getElementById('conv-label').textContent = '新对话';

    showToast('已开始新对话');
}

function saveConversationAs() {
    const title = prompt('请输入对话名称：', '对话 ' + new Date().toLocaleDateString('zh-CN'));
    if (!title) return;

    const id = activeConversationId || 'conv_' + Date.now();
    activeConversationId = id;

    const stored = getStoredConversations();
    stored[id] = {
        id,
        title,
        messages: chatMessages,
        libs: selectedLibs,
        files: selectedFiles,
        createdAt: stored[id]?.createdAt || Date.now(),
        updatedAt: Date.now()
    };
    saveStoredConversations(stored);

    document.getElementById('conv-label').textContent = title;
    showToast('对话已保存: ' + title);
}

function saveActiveConversation() {
    if (!activeConversationId) return;
    const stored = getStoredConversations();
    if (stored[activeConversationId]) {
        stored[activeConversationId].messages = chatMessages;
        stored[activeConversationId].libs = selectedLibs;
        stored[activeConversationId].files = selectedFiles;
        stored[activeConversationId].updatedAt = Date.now();
        saveStoredConversations(stored);
    }
}

function switchConversation(id) {
    const stored = getStoredConversations();
    const conv = stored[id];
    if (!conv) return;

    if (chatMessages.length > 0 && activeConversationId !== id) {
        // Auto-save current before switching
        saveActiveConversation();
    }

    activeConversationId = id;
    chatMessages = conv.messages || [];
    selectedLibs = conv.libs || [];
    selectedFiles = conv.files || [];

    saveLibSelection();
    saveChatHistory();

    // Refresh UI
    document.querySelectorAll('.lib-chip').forEach(chip => {
        if (selectedLibs.includes(chip.dataset.lib)) {
            chip.classList.add('active');
        } else {
            chip.classList.remove('active');
        }
    });
    updateLibBarHint();
    document.getElementById('paper-panel').style.display = 'none';

    if (chatMessages.length > 0) {
        hideEmptyState();
    } else {
        document.getElementById('chat-empty').style.display = '';
    }
    renderAllMessages();
    document.getElementById('conv-label').textContent = conv.title || '未命名';

    const dd = document.getElementById('conv-dropdown');
    dd.classList.remove('show');

    showToast('已切换到: ' + (conv.title || '未命名'));
}

function deleteConversation(id) {
    const stored = getStoredConversations();
    const conv = stored[id];
    if (!conv) return;
    if (!confirm(`确定要删除对话"${conv.title || '未命名'}"吗？此操作不可撤销。`)) return;

    delete stored[id];
    saveStoredConversations(stored);

    if (activeConversationId === id) {
        activeConversationId = null;
        document.getElementById('conv-label').textContent = '新对话';
    }

    loadConversationList();
    document.getElementById('conv-dropdown').classList.add('show'); // Keep open
    showToast('对话已删除');
}

function getStoredConversations() {
    try {
        const saved = localStorage.getItem(STORAGE_CONVS_KEY);
        return saved ? JSON.parse(saved) : {};
    } catch (e) { return {}; }
}

function saveStoredConversations(stored) {
    try {
        localStorage.setItem(STORAGE_CONVS_KEY, JSON.stringify(stored));
        localStorage.setItem(STORAGE_ACTIVE_CONV, activeConversationId || '');
    } catch (e) {}
}

function loadActiveConversation() {
    try {
        const id = localStorage.getItem(STORAGE_ACTIVE_CONV);
        if (id) {
            const stored = getStoredConversations();
            if (stored[id]) {
                switchConversation(id);
                return;
            }
        }
    } catch (e) {}
    // Default: no active conversation, empty state
    chatMessages = [];
    activeConversationId = null;
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
    chatMessages = chatMessages.slice(0, idx);
    renderAllMessages();

    const lastUserMsg = chatMessages[chatMessages.length - 1];
    if (!lastUserMsg || lastUserMsg.role !== 'user') return;

    isLoading = true;
    document.getElementById('send-btn').disabled = true;
    const loadingId = showTypingIndicator();

    try {
        const body = {
            messages: chatMessages,
            libs: selectedLibs
        };
        if (selectedFiles.length > 0) {
            body.files = selectedFiles;
        }

        const res = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
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
        saveActiveConversation();
    }
}

function clearChat() {
    if (chatMessages.length === 0) return;
    if (!confirm('确定要清空当前对话吗？此操作不可撤销。')) return;
    chatMessages = [];
    activeConversationId = null;
    document.getElementById('conv-label').textContent = '新对话';
    renderAllMessages();
    document.getElementById('chat-empty').style.display = '';
    saveChatHistory();
    showToast('对话已清空');
}

// ===== Persistence =====
function saveChatHistory() {
    try {
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
