import { ref, computed, onMounted, watch } from 'vue';
import { fetchSummaries } from '../api/client.js';

const parseMeta = (raw) => {
    if (!raw) return {};
    try {
        return JSON.parse(raw);
    } catch (e) {
        return {};
    }
};

export default {
    props: {
        fileId: {
            required: true
        }
    },
    setup(props) {
        const summaries = ref([]);
        const isLoading = ref(false);
        const error = ref(null);

        const loadSummaries = async () => {
            if (!props.fileId) return;

            isLoading.value = true;
            error.value = null;
            summaries.value = [];

            try {
                const result = await fetchSummaries(props.fileId);
                // Sort by creation time desc
                summaries.value = result.sort((a, b) => (b.creationTime || 0) - (a.creationTime || 0));
            } catch (e) {
                console.error(e);
                error.value = "Failed to load summaries.";
            } finally {
                isLoading.value = false;
            }
        };

        onMounted(loadSummaries);
        watch(() => props.fileId, loadSummaries);

        // The overarching note overview is pinned to the top, the rest follow.
        const overviewItem = computed(() =>
            summaries.value.find((s) => (s.dataSource || '').toUpperCase() === 'OVERVIEW') || null
        );
        const otherItems = computed(() =>
            summaries.value.filter((s) => (s.dataSource || '').toUpperCase() !== 'OVERVIEW')
        );

        const overviewTitle = computed(() => parseMeta(overviewItem.value?.metadata).title || '');
        const overviewTopics = computed(() => parseMeta(overviewItem.value?.metadata).topics || []);
        const overviewBody = computed(() => {
            const item = overviewItem.value;
            if (!item || !item.content) return '';
            const title = overviewTitle.value;
            let body = item.content;
            // Avoid showing the title twice (content is stored as "title\n\nsummary").
            if (title && body.startsWith(title)) {
                body = body.slice(title.length);
            }
            return body.trim();
        });

        // Helper to format text (simple line breaks)
        const formatContent = (text) => {
            if (!text) return "";
            return text.replace(/\n/g, '<br/>');
        };

        const sourceLabel = (src) => {
            const map = { OCR: 'Transcript', GEMINI: 'Timeline', OVERVIEW: 'Overview', USER: 'Note' };
            return map[(src || '').toUpperCase()] || src || 'Unknown';
        };

        const formatDate = (ts) => {
            if (!ts) return "";
            return new Date(ts).toLocaleString();
        };

        return {
            summaries,
            isLoading,
            error,
            overviewItem,
            otherItems,
            overviewTitle,
            overviewTopics,
            overviewBody,
            formatContent,
            sourceLabel,
            formatDate
        };
    },
    template: `
    <div class="h-full flex flex-col bg-white border-l border-slate-200 shadow-xl w-full md:w-96 transition-all duration-300">
        <!-- Header -->
        <div class="p-4 border-b border-slate-100 bg-slate-50 flex items-center justify-between">
            <h3 class="font-semibold text-slate-800 flex items-center gap-2">
                <svg class="w-5 h-5 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path></svg>
                AI Insights
            </h3>
            <button @click="$emit('close')" class="text-slate-400 hover:text-slate-600">
                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
            </button>
        </div>

        <!-- Content -->
        <div class="flex-1 overflow-y-auto p-4 space-y-4">
            <!-- Loading -->
            <div v-if="isLoading" class="flex flex-col items-center justify-center py-12">
                <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600 mb-3"></div>
                <p class="text-sm text-slate-500">Thinking...</p>
            </div>

            <!-- Error -->
            <div v-if="error" class="bg-red-50 text-red-600 p-4 rounded-lg text-sm">
                {{ error }}
            </div>

            <!-- Empty State -->
            <div v-if="!isLoading && !error && summaries.length === 0" class="text-center py-12">
                <p class="text-slate-400 mb-2">No insights yet.</p>
                <p class="text-xs text-slate-400">Summaries and transcripts will appear here once processed.</p>
            </div>

            <!-- Pinned Overview -->
            <div v-if="overviewItem" class="rounded-xl p-4 border border-indigo-100 bg-gradient-to-br from-indigo-50 to-white shadow-sm">
                <div class="flex items-center gap-2 mb-2">
                    <svg class="w-4 h-4 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path></svg>
                    <span class="text-xs font-semibold uppercase tracking-wide text-indigo-600">Overview</span>
                </div>
                <h4 v-if="overviewTitle" class="font-semibold text-slate-800 mb-1">{{ overviewTitle }}</h4>
                <div class="prose prose-sm prose-slate max-w-none text-slate-600" v-html="formatContent(overviewBody)"></div>
                <div v-if="overviewTopics.length" class="flex flex-wrap gap-1.5 mt-3">
                    <span v-for="t in overviewTopics" :key="t" class="text-xs px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-700">{{ t }}</span>
                </div>
            </div>

            <!-- List -->
            <div v-for="item in otherItems" :key="item.id" class="bg-slate-50 rounded-lg p-4 border border-slate-100">
                <div class="flex items-center justify-between mb-2">
                    <span class="text-xs font-semibold px-2 py-1 rounded bg-white text-slate-600 border border-slate-200">
                        {{ sourceLabel(item.dataSource) }}
                    </span>
                    <span class="text-xs text-slate-400">{{ formatDate(item.creationTime) }}</span>
                </div>
                <div class="prose prose-sm prose-slate max-w-none text-slate-600" v-html="formatContent(item.content)"></div>
            </div>
        </div>
    </div>
    `
};
