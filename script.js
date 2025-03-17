marked.setOptions({
    breaks: true,
    gfm: true,
    langPrefix: 'language-'
});

let BASE_URL = 'ws://127.0.0.1:8000';
(function configurePort() {
    const port = prompt('请输入后端端口号（默认8000）：', '8000');
    const parsedPort = port ? parseInt(port) : 8000;
    if (!isNaN(parsedPort) && parsedPort >= 1 && parsedPort <= 65535) {
        BASE_URL = `ws://127.0.0.1:${parsedPort}`;
    } else {
        alert('端口无效，使用默认端口8000');
    }
    console.log(`WebSocket URL配置为: ${BASE_URL}`);
})();

let ws;
let currentStreamContent = '';
let currentStreamBubble = null;
let isStreaming = false;
let isStreamingEnabled = false;
let uploadedFiles = [];
const inputBox = document.getElementById('messageInput');
const dragOverlay = document.getElementById('dragOverlay');

function initWebSocket() {
    ws = new WebSocket(`${BASE_URL}/ws`);
    ws.onopen = () => {
        console.log("WebSocket 已连接");
        addServerMessage("已连接到服务器");
    };
    ws.onmessage = async (event) => {
        const data = event.data;
        console.log("收到 WebSocket 消息:", data);
        if (data.startsWith('data: ')) {
            await handleStreamingMessage(data);
        } else {
            try {
                const messageData = JSON.parse(data);
                console.log("解析后的非流式消息:", messageData);
                renderServerMessage(messageData);
            } catch (e) {
                console.error("解析非流式消息失败:", e, "原始数据:", data);
                addServerMessage(`解析错误: ${e.message}`);
            }
        }
    };
    ws.onerror = (error) => {
        console.error("WebSocket 错误:", error);
        if (isStreaming && currentStreamBubble) {
            currentStreamBubble.remove();
            currentStreamContent = '';
            currentStreamBubble = null;
            isStreaming = false;
            addServerMessage("流式输出中断，因连接错误");
        }
        addServerMessage("WebSocket 连接错误，请刷新页面重试");
    };
    ws.onclose = () => {
        if (isStreaming && currentStreamBubble) {
            currentStreamBubble.remove();
            currentStreamContent = '';
            currentStreamBubble = null;
            isStreaming = false;
            addServerMessage("流式输出中断，因连接断开");
        }
        console.log("WebSocket 已断开，尝试重连...");
        addServerMessage("WebSocket 已断开，正在尝试重连...");
        setTimeout(initWebSocket, 1000);
    };
}
initWebSocket();

(function initMode() {
    if (localStorage.getItem('dark-mode') === 'true') {
        document.body.classList.add('dark-mode');
        document.getElementById('mode-toggle').textContent = '切换到白天模式';
    }
})();

// 防抖函数
function debounce(func, wait) {
    let timeout;
    return function (...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), wait);
    };
}

function adjustInputHeight() {
    const input = document.getElementById('messageInput');
    const inputArea = document.querySelector('.input-area');
    const chatContainer = document.getElementById('chatContainer');

    input.style.transition = 'none';
    input.style.height = 'auto';
    const inputScrollHeight = input.scrollHeight;
    const minHeight = 45;
    const maxHeight = 200;
    const newInputHeight = Math.max(minHeight, Math.min(inputScrollHeight, maxHeight));
    input.style.height = `${newInputHeight}px`;

    requestAnimationFrame(() => {
        input.style.transition = 'height 0.3s ease';
        const realInputHeight = input.offsetHeight;
        const paddingVertical = 30;
        const minInputAreaHeight = 75;
        const maxInputAreaHeight = 230;
        const newInputAreaHeight = Math.max(minInputAreaHeight, Math.min(realInputHeight + paddingVertical, maxInputAreaHeight));
        inputArea.style.height = `${newInputAreaHeight}px`;
        chatContainer.style.marginBottom = `${newInputAreaHeight + 10}px`;

        if (!input.textContent.trim() && input.childNodes.length === 0) {
            input.style.height = `${minHeight}px`;
            inputArea.style.height = `${minInputAreaHeight}px`;
            chatContainer.style.marginBottom = `${minInputAreaHeight + 10}px`;
        }

        console.log(`adjustInputHeight: inputHeight=${realInputHeight}, inputAreaHeight=${newInputAreaHeight}, chatMarginBottom=${chatContainer.style.marginBottom}`);
    });
}

const debouncedAdjustInputHeight = debounce(adjustInputHeight, 100);

// 初始化
adjustInputHeight();

// 输入事件
inputBox.addEventListener('input', () => {
    debouncedAdjustInputHeight();
});

// 粘贴事件
inputBox.addEventListener('paste', async (event) => {
    event.preventDefault();
    inputBox.focus();
    const items = event.clipboardData.items;
    let text = event.clipboardData.getData('text');
    if (text) {
        pasteToInputBox(text);
        debouncedAdjustInputHeight();
    }
    for (let item of items) {
        if (item.kind === 'file') {
            const file = item.getAsFile();
            if (file) {
                await uploadFile(file);
                debouncedAdjustInputHeight();
            } else {
                addServerMessage('粘贴的文件无效，请使用上传按钮选择文件');
            }
        }
    }
});

// 按键事件
inputBox.addEventListener('keydown', (event) => {
    if (event.ctrlKey && event.key === 'Enter') {
        sendMessage();
        event.preventDefault();
    } else if (event.key === 'Enter' && !event.ctrlKey) {
        event.preventDefault();
        const br = document.createElement('br');
        const range = window.getSelection().getRangeAt(0);
        range.insertNode(br);
        range.setStartAfter(br);
        range.setEndAfter(br);
        debouncedAdjustInputHeight();
    } else {
        debouncedAdjustInputHeight();
    }
});

// 文件上传后调整高度
document.getElementById('fileInput').addEventListener('change', async () => {
    const files = document.getElementById('fileInput').files;
    for (let file of files) {
        if (file) {
            await uploadFile(file);
            debouncedAdjustInputHeight(); // 使用防抖
        } else {
            console.error('选择的文件无效');
            addServerMessage('选择的文件无效，请重新选择');
        }
    }
    document.getElementById('fileInput').value = '';
});

let dragCounter = 0;
document.body.addEventListener('dragenter', (e) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter++;
    dragOverlay.classList.add('active');
    console.log("Drag enter, counter:", dragCounter);
});

document.body.addEventListener('dragover', (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (!dragOverlay.classList.contains('active')) {
        dragOverlay.classList.add('active');
    }
});

document.body.addEventListener('dragleave', (e) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter--;
    if (dragCounter <= 0) {
        dragCounter = 0;
        dragOverlay.classList.remove('active');
    }
    console.log("Drag leave, counter:", dragCounter);
});

document.body.addEventListener('drop', async (e) => {
    e.preventDefault();
    e.stopPropagation();
    dragOverlay.classList.remove('active');
    dragCounter = 0; // 直接重置
    const files = e.dataTransfer.files;
    for (let file of files) {
        await uploadFile(file);
    }
    debouncedAdjustInputHeight(); // 添加高度调整
    console.log("File dropped, uploading...");
});

async function uploadFile(file) {
    if (!file) {
        console.error('文件无效');
        addServerMessage('文件无效，请重新上传');
        return;
    }

    inputBox.focus();
    const placeholder = document.createElement('span');
    placeholder.textContent = `${file.name} 上传中...`;
    const placeholderNode = pasteToInputBox(placeholder);

    try {
        const reader = new FileReader();
        reader.onload = (e) => {
            const base64Data = e.target.result.split(',')[1];
            const mimeType = file.type || "application/octet-stream";
            const fileId = Date.now() + Math.random().toString(36).substr(2, 5);
            uploadedFiles.push({ fileId, file, type: mimeType, base64: base64Data });

            const fileChip = document.createElement('span');
            fileChip.classList.add('file-chip');
            if (document.body.classList.contains('dark-mode')) {
                fileChip.classList.add('dark-mode');
            }
            fileChip.setAttribute('contenteditable', 'false'); // 恢复原始设计
            fileChip.dataset.fileId = fileId;

            const fileNameSpan = document.createElement('span');
            fileNameSpan.classList.add('file-name');
            fileNameSpan.textContent = file.name;

            const deleteBtn = document.createElement('button');
            deleteBtn.classList.add('delete-btn');
            deleteBtn.textContent = '×';
            deleteBtn.onclick = (e) => {
                e.stopPropagation();
                const fileIndex = uploadedFiles.findIndex(f => f.fileId === fileId);
                if (fileIndex !== -1) {
                    uploadedFiles.splice(fileIndex, 1);
                }
                fileChip.remove();
                debouncedAdjustInputHeight();
            };

            fileChip.onclick = (e) => {
                e.stopPropagation();
                const uploadedFile = uploadedFiles.find(f => f.fileId === fileId);
                if (uploadedFile) {
                    const { type, base64 } = uploadedFile;
                    const url = `data:${type};base64,${base64}`;
                    let previewType = 'file';
                    if (type.startsWith('image/')) previewType = 'image';
                    else if (type.startsWith('video/')) previewType = 'video';
                    else if (type.startsWith('audio/')) previewType = 'audio';
                    openModal(previewType, url, file.name);
                }
            };

            fileChip.appendChild(fileNameSpan);
            fileChip.appendChild(deleteBtn);
            replaceInInputBox(placeholderNode, fileChip);
            debouncedAdjustInputHeight();
        };
        reader.onerror = () => {
            const errorText = document.createTextNode(`${file.name} 读取失败`);
            replaceInInputBox(placeholderNode, errorText);
            addServerMessage(`文件读取失败: ${file.name}`);
        };
        reader.readAsDataURL(file);
    } catch (error) {
        console.error('文件处理失败:', error);
        const errorText = document.createTextNode(`${file.name} 处理失败: ${error.message}`);
        replaceInInputBox(placeholderNode, errorText);
        addServerMessage(`文件处理失败: ${error.message}`);
    }
}

function pasteToInputBox(content) {
    const input = document.getElementById('messageInput');
    input.focus();
    const selection = window.getSelection();
    if (!selection.rangeCount) {
        const range = document.createRange();
        range.selectNodeContents(input);
        range.collapse(false);
        selection.removeAllRanges();
        selection.addRange(range);
    }
    const range = selection.getRangeAt(0);
    const node = content instanceof Node ? content : document.createTextNode(content);
    range.deleteContents();
    range.insertNode(node);
    range.setStartAfter(node);
    range.setEndAfter(node);
    debouncedAdjustInputHeight();
    return node;
}

function replaceInInputBox(oldNode, newContent) {
    const input = document.getElementById('messageInput');
    input.focus();
    const range = document.createRange();
    range.selectNode(oldNode);
    range.deleteContents();
    const node = newContent instanceof Node ? newContent : document.createTextNode(newContent);
    range.insertNode(node);
    range.setStartAfter(node);
    range.setEndAfter(node);
    debouncedAdjustInputHeight();
}

function getInputContent() {
    const input = document.getElementById('messageInput');
    const content = [];
    let currentText = '';
    for (const child of input.childNodes) {
        if (child.nodeType === Node.TEXT_NODE) {
            currentText += child.textContent;
        } else if (child.nodeName === 'BR') {
            if (currentText) {
                content.push({ type: 'text', content: currentText });
                currentText = '';
            }
            content.push({ type: 'text', content: '\n' });
        } else if (child.classList?.contains('file-chip')) {
            if (currentText) {
                content.push({ type: 'text', content: currentText });
                currentText = '';
            }
            const fileId = child.dataset.fileId;
            const uploadedFile = uploadedFiles.find(f => f.fileId === fileId);
            if (uploadedFile) {
                const { type, base64 } = uploadedFile;
                let msgType = "file";
                if (type.startsWith('image/')) msgType = "image";
                else if (type.startsWith('video/')) msgType = "video";
                else if (type.startsWith('audio/')) msgType = "audio";
                content.push({
                    type: msgType,
                    source: {
                        base64: base64,
                        mime_type: type,
                        filename: uploadedFile.file.name
                    }
                });
            }
        }
    }
    if (currentText) {
        content.push({ type: 'text', content: currentText });
    }
    return content;
}

function createMediaElementFromBase64(type, base64Data, mimeType, name) {
    const container = document.createElement('div');
    container.classList.add('media-container');

    const media = document.createElement(type);
    media.src = `data:${mimeType};base64,${base64Data}`;
    media.preload = 'metadata';

    const fileNameSpan = document.createElement('span');
    fileNameSpan.textContent = name;
    fileNameSpan.style.fontSize = '14px';
    fileNameSpan.style.color = '#666';
    fileNameSpan.style.marginBottom = '5px';

    const controls = document.createElement('div');
    controls.classList.add('controls');

    const playPauseBtn = document.createElement('button');
    playPauseBtn.textContent = '播放';
    playPauseBtn.classList.add('play-pause-btn');
    playPauseBtn.onclick = () => {
        if (media.paused) {
            media.play();
            playPauseBtn.textContent = '暂停';
        } else {
            media.pause();
            playPauseBtn.textContent = '播放';
        }
    };

    const downloadBtn = document.createElement('button');
    downloadBtn.textContent = '下载';
    downloadBtn.classList.add('download-btn');
    downloadBtn.onclick = () => {
        const a = document.createElement('a');
        a.href = media.src;
        a.download = name;
        a.click();
    };

    const progressBar = document.createElement('div');
    progressBar.classList.add('progress-bar');
    const progress = document.createElement('div');
    progress.classList.add('progress');
    progressBar.appendChild(progress);

    media.ontimeupdate = () => {
        const percent = (media.currentTime / media.duration) * 100;
        progress.style.width = `${percent}%`;
    };

    const cleanupListeners = () => {
        document.onmousemove = null;
        document.onmouseup = null;
    };

    progressBar.onmousedown = (e) => {
        const rect = progressBar.getBoundingClientRect();
        const updateProgress = (event) => {
            const offsetX = event.clientX - rect.left;
            const percent = Math.min(Math.max(offsetX / rect.width, 0), 1);
            media.currentTime = percent * media.duration;
            progress.style.width = `${percent * 100}%`;
        };
        updateProgress(e);

        document.onmousemove = (event) => updateProgress(event);
        document.onmouseup = cleanupListeners;
    };

    controls.appendChild(playPauseBtn);
    controls.appendChild(downloadBtn);
    container.appendChild(fileNameSpan);
    container.appendChild(media);
    container.appendChild(progressBar);
    container.appendChild(controls);
    return container;
}

function renderMediaFromBase64(base64Data, mimeType, alt = "Media", name = "unnamed_image") {
    const container = document.createElement('div');
    container.classList.add('media-container');

    const img = document.createElement('img');
    img.src = `data:${mimeType};base64,${base64Data}`;
    img.alt = alt;
    img.style.maxWidth = "100%";

    const fileNameSpan = document.createElement('span');
    fileNameSpan.textContent = name;
    fileNameSpan.style.fontSize = '14px';
    fileNameSpan.style.color = '#666';
    fileNameSpan.style.marginBottom = '5px';

    img.onclick = () => openModal('image', img.src, name);
    container.appendChild(fileNameSpan);
    container.appendChild(img);
    return container;
}

function createAudioInteraction(base64Data, mimeType, name) {
    const container = document.createElement('div');
    container.classList.add('audio-interaction');
    container.onclick = () => openModal('audio', `data:${mimeType};base64,${base64Data}`, name);

    const icon = document.createElement('div');
    icon.classList.add('audio-icon');

    const audioName = document.createElement('span');
    audioName.classList.add('audio-name');
    audioName.textContent = name;

    container.appendChild(icon);
    container.appendChild(audioName);
    return container;
}

function renderFile(base64Data, mimeType, name) {
    const container = document.createElement('div');
    container.classList.add('file-container');

    const icon = document.createElement('div');
    icon.classList.add('file-icon');

    const fileName = document.createElement('span');
    fileName.classList.add('file-name');
    fileName.textContent = name;

    const controls = document.createElement('div');
    controls.classList.add('controls');

    const downloadBtn = document.createElement('button');
    downloadBtn.textContent = '下载';
    downloadBtn.classList.add('download-btn');
    downloadBtn.onclick = () => {
        const a = document.createElement('a');
        a.href = `data:${mimeType};base64,${base64Data}`;
        a.download = name;
        a.click();
    };

    controls.appendChild(downloadBtn);
    container.appendChild(icon);
    container.appendChild(fileName);
    container.appendChild(controls);
    return container;
}

function openModal(type, url, name) {
    const modal = document.getElementById('mediaModal');
    const modalContent = modal.querySelector('.modal-content');
    const modalMedia = document.getElementById('modalMedia');
    const modalControls = document.getElementById('modalControls');
    modalMedia.innerHTML = '';
    modalControls.innerHTML = '';

    const fileNameSpan = document.createElement('span');
    fileNameSpan.textContent = name;
    fileNameSpan.style.fontSize = '16px';
    fileNameSpan.style.marginBottom = '10px';
    fileNameSpan.style.display = 'block';
    modalMedia.appendChild(fileNameSpan);

    if (type === 'image') {
        const img = document.createElement('img');
        img.src = url;
        modalMedia.appendChild(img);
    } else if (type === 'video' || type === 'audio') {
        const media = document.createElement(type);
        media.src = url;
        media.controls = true;
        media.autoplay = false;
        modalMedia.appendChild(media);

        const playPauseBtn = document.createElement('button');
        playPauseBtn.textContent = '播放';
        playPauseBtn.classList.add('play-pause-btn');
        playPauseBtn.onclick = () => {
            if (media.paused) {
                media.play();
                playPauseBtn.textContent = '暂停';
            } else {
                media.pause();
                playPauseBtn.textContent = '播放';
            }
        };
        modalControls.appendChild(playPauseBtn);

        const progressBar = document.createElement('div');
        progressBar.classList.add('progress-bar');
        const progress = document.createElement('div');
        progress.classList.add('progress');
        progressBar.appendChild(progress);

        media.ontimeupdate = () => {
            const percent = (media.currentTime / media.duration) * 100;
            progress.style.width = `${percent}%`;
        };

        const cleanupListeners = () => {
            document.onmousemove = null;
            document.onmouseup = null;
        };

        progressBar.onmousedown = (e) => {
            const rect = progressBar.getBoundingClientRect();
            const updateProgress = (event) => {
                const offsetX = event.clientX - rect.left;
                const percent = Math.min(Math.max(offsetX / rect.width, 0), 1);
                media.currentTime = percent * media.duration;
                progress.style.width = `${percent * 100}%`;
            };
            updateProgress(e);

            document.onmousemove = (event) => updateProgress(event);
            document.onmouseup = cleanupListeners;
        };
        modalControls.appendChild(progressBar);
    }

    const downloadBtn = document.createElement('button');
    downloadBtn.textContent = '下载';
    downloadBtn.classList.add('download-btn');
    downloadBtn.onclick = () => {
        const a = document.createElement('a');
        a.href = url;
        a.download = name;
        a.click();
    };
    modalControls.appendChild(downloadBtn);

    modal.style.display = 'flex';
    setTimeout(() => modal.classList.add('show'), 10);
}

function closeModal() {
    const modal = document.getElementById('mediaModal');
    modal.classList.remove('show');
    modal.addEventListener('transitionend', function handler() {
        modal.style.display = 'none';
        modal.removeEventListener('transitionend', handler);
        document.onmousemove = null;
        document.onmouseup = null;
    }, { once: true });
}

function openNodeModal(messages) {
    const modal = document.getElementById('nodeModal');
    const modalContent = modal.querySelector('.node-modal-content');
    const modalContentDiv = document.getElementById('nodeModalContent');
    modalContentDiv.innerHTML = '';

    messages.forEach(message => {
        const wrapper = document.createElement('div');
        wrapper.classList.add('message-wrapper', 'server-wrapper');
        const messageDiv = document.createElement('div');
        messageDiv.classList.add('message', 'server-message');

        if (Array.isArray(message)) {
            message.forEach(item => {
                if (item.type === 'text') {
                    const htmlContent = marked.parse(item.content);
                    const textDiv = document.createElement('div');
                    textDiv.innerHTML = htmlContent;
                    messageDiv.appendChild(textDiv);
                } else if (item.type === 'image') {
                    const imgContainer = renderMediaFromBase64(item.source.base64, item.source.mime_type, "Image from server", item.source.filename || "unnamed_image");
                    messageDiv.appendChild(imgContainer);
                } else if (item.type === 'video') {
                    const videoContainer = createMediaElementFromBase64('video', item.source.base64, item.source.mime_type, item.source.filename || "unnamed_video");
                    const video = videoContainer.querySelector('video');
                    video.onclick = () => openModal('video', video.src, item.source.filename || "unnamed_video");
                    messageDiv.appendChild(videoContainer);
                } else if (item.type === 'audio') {
                    const audioInteraction = createAudioInteraction(item.source.base64, item.source.mime_type, item.source.filename || "unnamed_audio");
                    messageDiv.appendChild(audioInteraction);
                } else if (item.type === 'file') {
                    const fileContainer = renderFile(item.source.base64, item.source.mime_type, item.source.filename || "unnamed_file");
                    messageDiv.appendChild(fileContainer);
                }
            });
        } else {
            if (message.type === 'text') {
                const htmlContent = marked.parse(message.content);
                const textDiv = document.createElement('div');
                textDiv.innerHTML = htmlContent;
                messageDiv.appendChild(textDiv);
            } else if (message.type === 'image') {
                const imgContainer = renderMediaFromBase64(message.source.base64, message.source.mime_type, "Image from server", message.source.filename || "unnamed_image");
                messageDiv.appendChild(imgContainer);
            } else if (message.type === 'video') {
                const videoContainer = createMediaElementFromBase64('video', message.source.base64, message.source.mime_type, message.source.filename || "unnamed_video");
                const video = videoContainer.querySelector('video');
                video.onclick = () => openModal('video', video.src, message.source.filename || "unnamed_video");
                messageDiv.appendChild(videoContainer);
            } else if (message.type === 'audio') {
                const audioInteraction = createAudioInteraction(message.source.base64, message.source.mime_type, message.source.filename || "unnamed_audio");
                messageDiv.appendChild(audioInteraction);
            } else if (message.type === 'file') {
                const fileContainer = renderFile(message.source.base64, message.source.mime_type, message.source.filename || "unnamed_file");
                messageDiv.appendChild(fileContainer);
            }
        }

        wrapper.appendChild(messageDiv);
        modalContentDiv.appendChild(wrapper);

        const imgs = messageDiv.getElementsByTagName('img');
        for (let img of imgs) {
            img.onclick = () => openModal('image', img.src, img.parentElement.querySelector('span')?.textContent || img.src.split('/').pop());
        }

        const pres = messageDiv.getElementsByTagName('pre');
        for (let pre of pres) {
            if (!pre.querySelector('.copy-btn')) {
                const codeContent = pre.textContent;
                const copyBtn = document.createElement('button');
                copyBtn.textContent = '复制';
                copyBtn.classList.add('copy-btn');
                copyBtn.onclick = () => {
                    navigator.clipboard.writeText(codeContent.trim()).then(() => {
                        copyBtn.textContent = '已复制';
                        setTimeout(() => copyBtn.textContent = '复制', 2000);
                    });
                };
                pre.appendChild(copyBtn);
            }
        }
    });

    modal.style.display = 'flex';
    setTimeout(() => modal.classList.add('show'), 10);
}

function closeNodeModal() {
    const modal = document.getElementById('nodeModal');
    modal.classList.remove('show');
    modal.addEventListener('transitionend', function handler() {
        modal.style.display = 'none';
        modal.removeEventListener('transitionend', handler);
    }, { once: true });
}

document.getElementById('mediaModal').onclick = (e) => {
    if (e.target.classList.contains('modal')) {
        closeModal();
    }
};
document.getElementById('nodeModal').onclick = (e) => {
    if (e.target.classList.contains('node-modal')) {
        closeNodeModal();
    }
};

function containsMarkdown(content) {
    return /[!\[]|\[.*?\]\(.*?\)|`{3,}/.test(content);
}

function checkMarkdownAndAddClass(messageDiv) {
    if (containsMarkdown(messageDiv.textContent || messageDiv.innerText)) {
        messageDiv.classList.add('markdown');
    } else {
        messageDiv.classList.remove('markdown');
    }
}

function toggleStreaming() {
    isStreamingEnabled = !isStreamingEnabled;
    const toggleButton = document.getElementById('toggle-streaming');
    toggleButton.textContent = isStreamingEnabled ? '关闭流式输出' : '开启流式输出';
    console.log(`流式输出状态: ${isStreamingEnabled}`);
}

function renderMedia(container, content) {
    const videoRegex = /\[video\]\((.*?)\)/g;
    const audioRegex = /\[audio\]\((.*?)\)/g;
    const pdfRegex = /\[pdf\]\((.*?)\)/g;
    const imageRegex = /!\[(.*?)\]\((.*?)\)/g;

    let match;
    while ((match = imageRegex.exec(content)) !== null) {
        const altText = match[1];
        const url = match[2];
        if (url.startsWith('data:')) {
            const imgContainer = renderMediaFromBase64(url.split(',')[1], url.split(';')[0].split(':')[1], altText, altText || "image");
            container.appendChild(imgContainer);
        }
    }
    while ((match = videoRegex.exec(content)) !== null) {
        const url = match[1];
        if (url.startsWith('data:')) {
            const mimeType = url.split(';')[0].split(':')[1];
            const base64Data = url.split(',')[1];
            const videoContainer = createMediaElementFromBase64('video', base64Data, mimeType, "video." + mimeType.split('/')[1]);
            container.appendChild(videoContainer);
        }
    }
    while ((match = audioRegex.exec(content)) !== null) {
        const url = match[1];
        if (url.startsWith('data:')) {
            const mimeType = url.split(';')[0].split(':')[1];
            const base64Data = url.split(',')[1];
            const audioInteraction = createAudioInteraction(base64Data, mimeType, "audio." + mimeType.split('/')[1]);
            container.appendChild(audioInteraction);
        }
    }
    while ((match = pdfRegex.exec(content)) !== null) {
        const url = match[1];
        if (url.startsWith('data:')) {
            const fileContainer = renderFile(url.split(',')[1], 'application/pdf', "document.pdf");
            container.appendChild(fileContainer);
        }
    }
}

function autoScrollIfAtBottom(container) {
    requestAnimationFrame(() => {
        const isAtBottom = container.scrollTop + container.clientHeight >= container.scrollHeight - 10;
        if (isAtBottom) {
            container.scrollTop = container.scrollHeight;
        }
    });
}

// 发送消息
async function sendMessage() {
    const input = document.getElementById('messageInput');
    const inputArea = document.querySelector('.input-area');
    const chatContainer = document.getElementById('chatContainer');
    const content = getInputContent();
    if (content.length === 0) return;

    const hasFailedUploads = uploadedFiles.some(f => !f.base64);
    if (hasFailedUploads) {
        addServerMessage("存在上传失败的文件，请检查后重新发送");
        return;
    }

    addUserMessage(content);

    const messageData = {
        message: content,
        isStreaming: isStreamingEnabled
    };
    if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(messageData));
        if (isStreamingEnabled) {
            currentStreamContent = '';
            currentStreamBubble = null;
            isStreaming = true;
        }
    } else {
        addServerMessage("WebSocket 未连接，请刷新页面重试");
    }

    input.innerHTML = '';
    uploadedFiles = [];
    input.style.height = `${45}px`;
    inputArea.style.height = `${75}px`;
    chatContainer.style.marginBottom = `${75 + 10}px`;
    input.focus();
}

function createStreamingBubbleAsync() {
    return new Promise((resolve) => {
        console.log("创建流式消息气泡（异步）");
        try {
            const messageWrapper = document.createElement("div");
            messageWrapper.classList.add("message-wrapper", "server-wrapper");

            const messageWithButton = document.createElement("div");
            messageWithButton.classList.add("message-with-button");

            const messageDiv = document.createElement("div");
            messageDiv.classList.add("message", "server-message", "streaming-active");

            const streamingContainer = document.createElement("div");
            streamingContainer.classList.add("streaming-container");
            streamingContainer.dataset.content = "";

            const downloadBtn = document.createElement("button");
            downloadBtn.textContent = "下载 MD";
            downloadBtn.classList.add("download-md-btn");
            downloadBtn.onclick = () => downloadMarkdown(streamingContainer.dataset.content, "response.md");

            messageDiv.appendChild(streamingContainer);
            messageWithButton.appendChild(messageDiv);
            messageWithButton.appendChild(downloadBtn);
            messageWrapper.appendChild(messageWithButton);

            console.log("流式气泡创建完成（异步）:", messageWrapper);
            currentStreamBubble = messageWrapper;
            resolve(currentStreamBubble);
        } catch (error) {
            console.error("创建流式气泡错误（异步）:", error);
            currentStreamBubble = null;
            resolve(null);
        }
    });
}

function renderStreamingContent(fullContent) {
    if (!currentStreamBubble) {
        console.error("currentStreamBubble 不存在，无法渲染流式内容");
        return;
    }
    const streamingContainer = currentStreamBubble.querySelector(".streaming-container");
    if (!streamingContainer) {
        console.error("未找到 streaming-container 元素");
        return;
    }

    streamingContainer.innerHTML = '';
    try {
        const htmlContent = marked.parse(fullContent);
        streamingContainer.innerHTML = htmlContent;
        streamingContainer.dataset.content = fullContent;
    } catch (e) {
        console.error("Markdown 解析错误:", e);
        streamingContainer.textContent = fullContent;
        addServerMessage("Markdown 解析失败，已显示原始文本");
    }

    const pres = streamingContainer.getElementsByTagName("pre");
    for (let pre of pres) {
        if (!pre.querySelector(".copy-btn")) {
            const codeContent = pre.textContent;
            const copyBtn = document.createElement("button");
            copyBtn.textContent = "复制";
            copyBtn.classList.add("copy-btn");
            copyBtn.onclick = () => {
                navigator.clipboard.writeText(codeContent.trim()).then(() => {
                    copyBtn.textContent = "已复制";
                    setTimeout(() => (copyBtn.textContent = "复制"), 2000);
                });
            };
            pre.appendChild(copyBtn);
        }
    }

    autoScrollIfAtBottom(document.getElementById("chatContainer"));
}

async function handleStreamingMessage(data) {
    console.log("处理流式消息:", data);
    const jsonStr = data.slice(6).trim();
    try {
        const parsedData = JSON.parse(jsonStr);
        console.log("解析后的流式数据:", parsedData);

        if (parsedData.error) {
            addServerMessage(`错误: ${parsedData.error}`);
            if (currentStreamBubble) {
                currentStreamBubble.remove();
            }
            isStreaming = false;
            currentStreamBubble = null;
            return;
        }

        const content = parsedData.content || "";
        const isStart = parsedData.start_stream === true ||
                        (typeof parsedData.start_stream === "string" && parsedData.start_stream.toLowerCase() === "true") ||
                        parsedData.start_stream === 1;
        const isEnd = parsedData.end_stream === true ||
                      (typeof parsedData.end_stream === "string" && parsedData.end_stream.toLowerCase() === "true") ||
                      parsedData.end_stream === 1;

        if (isStart && !currentStreamBubble) {
            console.log("流式开始 - 创建新气泡");
            currentStreamContent = "";
            currentStreamBubble = await createStreamingBubbleAsync();
            if (!currentStreamBubble) {
                console.error("创建流式 bubble 失败");
                isStreaming = false;
                currentStreamBubble = null;
                renderFallbackStreamingMessage("流式消息初始化失败，请检查日志");
                return;
            }
            const chatContainer = document.getElementById("chatContainer");
            chatContainer.appendChild(currentStreamBubble);
            autoScrollIfAtBottom(chatContainer);
        }

        if (content && currentStreamBubble) {
            console.log("追加流式内容并重新渲染:", content);
            currentStreamContent += content;
            renderStreamingContent(currentStreamContent);
        }

        if (isEnd && currentStreamBubble) {
            console.log("流式结束");
            finalizeStreamingMessage();
            isStreaming = false;
            currentStreamContent = "";
            currentStreamBubble = null;
        }
    } catch (e) {
        console.error("解析流式消息错误:", e, "原始数据:", data);
        addServerMessage(`解析错误: ${e.message}`);
        if (currentStreamBubble) {
            currentStreamBubble.remove();
        }
        isStreaming = false;
        currentStreamBubble = null;
        renderFallbackStreamingMessage(`解析错误: ${e.message}`);
    }
}

function renderFallbackStreamingMessage(content) {
    if (!content) return;
    const chatContainer = document.getElementById("chatContainer");
    if (!chatContainer) {
        console.error("未找到 chatContainer 元素，无法渲染后备流式消息");
        return;
    }

    const messageWrapper = document.createElement("div");
    messageWrapper.classList.add("message-wrapper", "server-wrapper");
    const messageDiv = document.createElement("div");
    messageDiv.classList.add("message", "server-message", "streaming-active");

    const textDiv = document.createElement("div");
    try {
        const htmlContent = marked.parse(content);
        textDiv.innerHTML = htmlContent;
    } catch (e) {
        console.error("Markdown 解析错误:", e);
        textDiv.textContent = content;
    }

    messageDiv.appendChild(textDiv);
    messageWrapper.appendChild(messageDiv);
    chatContainer.appendChild(messageWrapper);
    autoScrollIfAtBottom(chatContainer);
}

function finalizeStreamingMessage() {
    if (!currentStreamBubble) return;

    const messageDiv = currentStreamBubble.querySelector(".message");
    const streamingContainer = currentStreamBubble.querySelector(".streaming-container");

    messageDiv.classList.remove("streaming-active");

    streamingContainer.innerHTML = '';
    try {
        const finalHtml = marked.parse(currentStreamContent);
        streamingContainer.innerHTML = finalHtml;
    } catch (e) {
        console.error("Markdown 最终渲染错误:", e);
        streamingContainer.textContent = currentStreamContent;
        addServerMessage("Markdown 解析失败，已显示原始文本");
    }

    const pres = streamingContainer.getElementsByTagName("pre");
    for (let pre of pres) {
        if (!pre.querySelector(".copy-btn")) {
            const codeContent = pre.textContent;
            const copyBtn = document.createElement("button");
            copyBtn.textContent = "复制";
            copyBtn.classList.add("copy-btn");
            copyBtn.onclick = () => {
                navigator.clipboard.writeText(codeContent.trim()).then(() => {
                    copyBtn.textContent = "已复制";
                    setTimeout(() => (copyBtn.textContent = "复制"), 2000);
                });
            };
            pre.appendChild(copyBtn);
        }
    }

    checkMarkdownAndAddClass(messageDiv);
    autoScrollIfAtBottom(document.getElementById("chatContainer"));
}

function renderServerMessage(data) {
    const messageWrapper = document.createElement("div");
    messageWrapper.classList.add("message-wrapper", "server-wrapper");
    const messageWithButton = document.createElement("div");
    messageWithButton.classList.add("message-with-button");

    const messageDiv = document.createElement("div");
    messageDiv.classList.add("message", "server-message");
    if (data.some(item => item.type === "node")) {
        messageDiv.classList.add("node");
        messageDiv.onclick = () => openNodeModal(data);
    }

    let combinedText = "";
    data.forEach(item => {
        if (item.type === "text") {
            combinedText += item.content;
            const textDiv = document.createElement('div');
            if (!item.content.trim()) {
                textDiv.style.minHeight = '1em';
                textDiv.innerHTML = item.content.replace(/\n/g, '<br>') || '&nbsp;';
            } else {
                const htmlContent = marked.parse(combinedText);
                textDiv.innerHTML = htmlContent;
            }
            messageDiv.appendChild(textDiv);
            renderMedia(messageDiv, combinedText); // 添加媒体渲染
        } else if (item.type === "image") {
            const imgContainer = renderMediaFromBase64(item.source.base64, item.source.mime_type, "Image from server", item.source.filename || "unnamed_image");
            messageDiv.appendChild(imgContainer);
        } else if (item.type === "video") {
            const videoContainer = createMediaElementFromBase64('video', item.source.base64, item.source.mime_type, item.source.filename || "unnamed_video");
            const video = videoContainer.querySelector('video');
            video.onclick = () => openModal('video', video.src, item.source.filename || "unnamed_video");
            messageDiv.appendChild(videoContainer);
        } else if (item.type === "audio") {
            const audioInteraction = createAudioInteraction(item.source.base64, item.source.mime_type, item.source.filename || "unnamed_audio");
            messageDiv.appendChild(audioInteraction);
        } else if (item.type === "file") {
            const fileContainer = renderFile(item.source.base64, item.source.mime_type, item.source.filename || "unnamed_file");
            messageDiv.appendChild(fileContainer);
        }
    });

    const pres = messageDiv.getElementsByTagName('pre');
    for (let pre of pres) {
        const codeContent = pre.textContent;
        const copyBtn = document.createElement('button');
        copyBtn.textContent = '复制';
        copyBtn.classList.add('copy-btn');
        copyBtn.onclick = () => {
            navigator.clipboard.writeText(codeContent.trim()).then(() => {
                copyBtn.textContent = '已复制';
                setTimeout(() => copyBtn.textContent = '复制', 2000);
            });
        };
        pre.appendChild(copyBtn);
    }

    checkMarkdownAndAddClass(messageDiv);

    const downloadBtn = document.createElement('button');
    downloadBtn.textContent = '下载 MD';
    downloadBtn.classList.add('download-md-btn');
    downloadBtn.onclick = () => downloadMarkdown(combinedText, 'response.md');

    messageWithButton.appendChild(messageDiv);
    messageWithButton.appendChild(downloadBtn);
    messageWrapper.appendChild(messageWithButton);
    const chatContainer = document.getElementById("chatContainer");
    chatContainer.appendChild(messageWrapper);
    autoScrollIfAtBottom(chatContainer);
}

function renderStreamingContent(fullContent) {
    if (!currentStreamBubble) {
        console.error("currentStreamBubble 不存在，无法渲染流式内容");
        return;
    }
    const streamingContainer = currentStreamBubble.querySelector(".streaming-container");
    if (!streamingContainer) {
        console.error("未找到 streaming-container 元素");
        return;
    }

    streamingContainer.innerHTML = '';
    try {
        const htmlContent = marked.parse(fullContent);
        streamingContainer.innerHTML = htmlContent;
        streamingContainer.dataset.content = fullContent;
        renderMedia(streamingContainer, fullContent); // 添加媒体渲染
    } catch (e) {
        console.error("Markdown 解析错误:", e);
        streamingContainer.textContent = fullContent;
        addServerMessage("Markdown 解析失败，已显示原始文本");
    }

    const pres = streamingContainer.getElementsByTagName("pre");
    for (let pre of pres) {
        if (!pre.querySelector(".copy-btn")) {
            const codeContent = pre.textContent;
            const copyBtn = document.createElement("button");
            copyBtn.textContent = "复制";
            copyBtn.classList.add("copy-btn");
            copyBtn.onclick = () => {
                navigator.clipboard.writeText(codeContent.trim()).then(() => {
                    copyBtn.textContent = "已复制";
                    setTimeout(() => (copyBtn.textContent = "复制"), 2000);
                });
            };
            pre.appendChild(copyBtn);
        }
    }

    autoScrollIfAtBottom(document.getElementById("chatContainer"));
}

function addUserMessage(content) {
    const chatContainer = document.getElementById("chatContainer");
    const messageWrapper = document.createElement("div");
    messageWrapper.classList.add("message-wrapper", "user-wrapper");
    const messageDiv = document.createElement("div");
    messageDiv.classList.add("message", "user-message");

    content.forEach(item => {
        if (item.type === 'text') {
            const textDiv = document.createElement('div');
            textDiv.textContent = item.content;
            if (!item.content.trim()) {
                textDiv.style.minHeight = '1em';
                textDiv.innerHTML = item.content.replace(/\n/g, '<br>') || '&nbsp;';
            }
            messageDiv.appendChild(textDiv);
        } else if (item.type === 'image') {
            const imgContainer = renderMediaFromBase64(item.source.base64, item.source.mime_type, "Image from user", item.source.filename);
            messageDiv.appendChild(imgContainer);
        } else if (item.type === 'video') {
            const videoContainer = createMediaElementFromBase64('video', item.source.base64, item.source.mime_type, item.source.filename);
            const video = videoContainer.querySelector('video');
            video.onclick = () => openModal('video', video.src, item.source.filename);
            messageDiv.appendChild(videoContainer);
        } else if (item.type === 'audio') {
            const audioInteraction = createAudioInteraction(item.source.base64, item.source.mime_type, item.source.filename);
            messageDiv.appendChild(audioInteraction);
        } else if (item.type === 'file') {
            const fileContainer = renderFile(item.source.base64, item.source.mime_type, item.source.filename);
            messageDiv.appendChild(fileContainer);
        }
    });

    messageWrapper.appendChild(messageDiv);
    chatContainer.appendChild(messageWrapper);
    autoScrollIfAtBottom(chatContainer);
}

function downloadMarkdown(content, filename) {
    const blob = new Blob([content], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

function toggleMode() {
    const body = document.body;
    const toggleButton = document.getElementById('mode-toggle');
    if (body.classList.contains('dark-mode')) {
        body.classList.remove('dark-mode');
        toggleButton.textContent = '切换到黑夜模式';
        localStorage.setItem('dark-mode', 'false');
        document.querySelectorAll('.file-chip').forEach(chip => chip.classList.remove('dark-mode'));
    } else {
        body.classList.add('dark-mode');
        toggleButton.textContent = '切换到白天模式';
        localStorage.setItem('dark-mode', 'true');
        document.querySelectorAll('.file-chip').forEach(chip => chip.classList.add('dark-mode'));
    }
}

async function clearChat() {
    if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
            message: [{ type: "text", content: "/clear" }],
            isStreaming: false
        }));
        document.getElementById('chatContainer').innerHTML = '';
        currentStreamContent = '';
        currentStreamBubble = null;
        isStreaming = false;
    } else {
        console.error("WebSocket 未连接，无法清除聊天记录");
        addServerMessage("WebSocket 未连接，请刷新页面重试");
    }
}

function addServerMessage(content) {
    const chatContainer = document.getElementById("chatContainer");
    const messageWrapper = document.createElement("div");
    messageWrapper.classList.add("message-wrapper", "server-wrapper");
    const messageWithButton = document.createElement("div");
    messageWithButton.classList.add("message-with-button");

    const messageDiv = document.createElement("div");
    messageDiv.classList.add("message", "server-message");
    if (containsMarkdown(content)) {
        messageDiv.classList.add("markdown");
    }
    const htmlContent = marked.parse(content);
    const textDiv = document.createElement('div');
    textDiv.innerHTML = htmlContent;
    messageDiv.appendChild(textDiv);

    const downloadBtn = document.createElement('button');
    downloadBtn.textContent = '下载 MD';
    downloadBtn.classList.add('download-md-btn');
    downloadBtn.onclick = () => downloadMarkdown(content, 'response.md');

    messageWithButton.appendChild(messageDiv);
    messageWithButton.appendChild(downloadBtn);
    messageWrapper.appendChild(messageWithButton);

    renderMedia(messageDiv, content);

    const pres = messageDiv.getElementsByTagName('pre');
    for (let pre of pres) {
        if (!pre.querySelector('.copy-btn')) {
            const codeContent = pre.textContent;
            const copyBtn = document.createElement('button');
            copyBtn.textContent = '复制';
            copyBtn.classList.add('copy-btn');
            copyBtn.onclick = () => {
                navigator.clipboard.writeText(codeContent.trim()).then(() => {
                    copyBtn.textContent = '已复制';
                    setTimeout(() => copyBtn.textContent = '复制', 2000);
                });
            };
            pre.appendChild(copyBtn);
        }
    }

    chatContainer.appendChild(messageWrapper);
    autoScrollIfAtBottom(chatContainer);

    currentStreamContent = '';
    currentStreamBubble = null;
    isStreaming = false;
}