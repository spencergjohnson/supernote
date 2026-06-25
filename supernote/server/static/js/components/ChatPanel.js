import { ref, computed, nextTick } from 'vue';
import { chat } from '../api/client.js';
import { renderMarkdown } from '../utils/markdown.js';

export default {
    name: 'ChatPanel',
    props: {
        currentFolderId: { default: '0' },
        currentFileId: { default: null },
        currentFileName: { default: null }
    },
    emits: ['close', 'open-file'],
    setup(props, { emit }) {
        const query = ref('');
        const isLoading = ref(false);
        const error = ref(null);

        // scope: 'library' | 'folder' | 'note'
        const scopeMode = ref('library');

        const effectiveScope = computed(() => {
            if (scopeMode.value === 'folder' && props.currentFolderId && String(props.currentFolderId) !== '0') {
                return `folder:${props.currentFolderId}`;
            }
            if (scopeMode.value === 'note' && props.currentFileId) {
                return `note:${props.currentFileId}`;
            }
            return 'library';
        });

        const scopeLabel = computed(() => {
            if (effectiveScope.value.startsWith('folder:')) return 'This folder';
            if (effectiveScope.value.startsWith('note:')) return props.currentFileName || 'This note';
            return 'Whole library';
        });

        const messages = ref([]); // {role, content, sources?}

        const scrollEl = ref(null);
        const scrollToBottom = async () => {
            await nextTick();
            if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight;
        };

        const send = async () => {
            const q = query.value.trim();
            if (!q || isLoading.value) return;

            messages.value.push({ role: 'user', content: q });
            query.value = '';
            isLoading.value = true;
            error.value = null;
            await scrollToBottom();

            const historyForApi = messages.value
                .filter(m => m.role === 'user' || m.role === 'assistant')
                .slice(-10)
                .map(m => ({ role: m.role, content: m.content }));

            try {
                const data = await chat(q, historyForApi.slice(0, -1), effectiveScope.value);
                messages.value.push({
                    role: 'assistant',
                    content: data.answer || '',
                    sources: data.sources || []
                });
            } catch (e) {
                error.value = e.message || 'Request failed';
            } finally {
                isLoading.value = false;
                await scrollToBottom();
            }
        };

        const handleKey = (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                send();
            }
        };

        const openSource = (source) => {
            emit('open-file', {
                id: source.fileId,
                name: source.fileName,
                isDirectory: false
            });
        };

        const formatAnswer = (text) => renderMarkdown(text);

        return {
            query, isLoading, error, messages, scopeMode, scopeLabel, effectiveScope,
            scrollEl, send, handleKey, openSource, formatAnswer
        };
    },
    template: `
<div class="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 backdrop-blur-sm" @click.self="$emit('close')">
    <div class="bg-white w-full sm:max-w-2xl sm:mx-4 sm:rounded-2xl shadow-2xl flex flex-col" style="height:80vh;max-height:700px;">

        <!-- Header -->
        <div class="flex items-center gap-3 px-4 py-3 border-b border-slate-100">
            <svg class="w-5 h-5 text-indigo-500 flex-none" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                    d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-3 3v-3z"/>
            </svg>
            <h2 class="font-semibold text-slate-800 flex-1">Ask your notes</h2>

            <!-- Scope selector -->
            <div class="flex items-center gap-1 bg-slate-100 rounded-lg p-1 text-xs">
                <button @click="scopeMode = 'library'"
                    :class="['px-2 py-1 rounded-md transition-colors', scopeMode === 'library' ? 'bg-white shadow text-indigo-600 font-medium' : 'text-slate-500 hover:text-slate-700']">
                    Library
                </button>
                <button v-if="currentFolderId && String(currentFolderId) !== '0'"
                    @click="scopeMode = 'folder'"
                    :class="['px-2 py-1 rounded-md transition-colors', scopeMode === 'folder' ? 'bg-white shadow text-indigo-600 font-medium' : 'text-slate-500 hover:text-slate-700']">
                    Folder
                </button>
                <button v-if="currentFileId"
                    @click="scopeMode = 'note'"
                    :class="['px-2 py-1 rounded-md transition-colors', scopeMode === 'note' ? 'bg-white shadow text-indigo-600 font-medium' : 'text-slate-500 hover:text-slate-700']">
                    Note
                </button>
            </div>

            <button @click="$emit('close')" class="text-slate-400 hover:text-slate-600 ml-1">
                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                </svg>
            </button>
        </div>

        <!-- Scope label -->
        <div class="px-4 py-1.5 bg-indigo-50 border-b border-indigo-100 text-xs text-indigo-600 font-medium">
            Scope: {{ scopeLabel }}
        </div>

        <!-- Messages -->
        <div ref="scrollEl" class="flex-1 overflow-y-auto px-4 py-4 space-y-4">
            <div v-if="messages.length === 0" class="text-center py-12">
                <svg class="w-10 h-10 text-slate-200 mx-auto mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
                        d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-3 3v-3z"/>
                </svg>
                <p class="text-slate-400 text-sm">Ask anything about your handwritten notes.</p>
                <p class="text-slate-300 text-xs mt-1">e.g. "What did I write about last month?" or "Summarise my meeting notes."</p>
            </div>

            <template v-for="(msg, i) in messages" :key="i">
                <!-- User bubble -->
                <div v-if="msg.role === 'user'" class="flex justify-end">
                    <div class="max-w-xs sm:max-w-md bg-indigo-600 text-white rounded-2xl rounded-tr-sm px-4 py-2.5 text-sm shadow-sm">
                        {{ msg.content }}
                    </div>
                </div>

                <!-- Assistant bubble -->
                <div v-else class="flex flex-col gap-2">
                    <div class="max-w-none bg-slate-50 border border-slate-100 rounded-2xl rounded-tl-sm px-4 py-3 text-sm text-slate-700 shadow-sm prose prose-sm prose-slate"
                        v-html="formatAnswer(msg.content)">
                    </div>
                    <!-- Source chips -->
                    <div v-if="msg.sources && msg.sources.length" class="flex flex-wrap gap-1.5 pl-1">
                        <button v-for="(src, si) in msg.sources" :key="si"
                            @click="openSource(src)"
                            class="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-white border border-slate-200 text-slate-500 hover:border-indigo-300 hover:text-indigo-600 transition-colors shadow-sm">
                            <svg class="w-3 h-3 flex-none" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                                    d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
                            </svg>
                            {{ src.fileName }} p.{{ src.pageIndex + 1 }}
                        </button>
                    </div>
                </div>
            </template>

            <!-- Loading indicator -->
            <div v-if="isLoading" class="flex items-center gap-2 text-slate-400 text-sm pl-1">
                <svg class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                </svg>
                Thinking…
            </div>

            <div v-if="error" class="text-red-500 text-sm px-1">{{ error }}</div>
        </div>

        <!-- Input -->
        <div class="px-4 py-3 border-t border-slate-100 bg-white sm:rounded-b-2xl">
            <div class="flex items-end gap-2">
                <textarea v-model="query" @keydown="handleKey" rows="1"
                    :disabled="isLoading"
                    placeholder="Ask a question about your notes…"
                    class="flex-1 resize-none rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-700 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-300 disabled:opacity-50"
                    style="max-height:120px;overflow-y:auto;">
                </textarea>
                <button @click="send" :disabled="!query.trim() || isLoading"
                    class="flex-none p-2.5 rounded-xl bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shadow-sm">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"/>
                    </svg>
                </button>
            </div>
            <p class="text-xs text-slate-400 mt-1.5">Enter to send · Shift+Enter for newline</p>
        </div>
    </div>
</div>
    `
};
