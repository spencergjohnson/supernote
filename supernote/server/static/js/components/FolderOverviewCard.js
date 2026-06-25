import { ref, computed, watch } from 'vue';
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
    name: 'FolderOverviewCard',
    props: {
        folderId: {
            required: true
        }
    },
    setup(props) {
        const item = ref(null);
        const isLoading = ref(false);
        const collapsed = ref(false);

        const load = async () => {
            item.value = null;
            // Root ("0") has no folder summary.
            if (!props.folderId || String(props.folderId) === '0') return;
            isLoading.value = true;
            try {
                const summaries = await fetchSummaries(props.folderId);
                item.value =
                    summaries.find((s) => (s.dataSource || '').toUpperCase() === 'FOLDER') || null;
            } catch (e) {
                console.error('Failed to load folder summary', e);
                item.value = null;
            } finally {
                isLoading.value = false;
            }
        };

        watch(() => props.folderId, load, { immediate: true });

        const meta = computed(() => parseMeta(item.value?.metadata));
        const title = computed(() => meta.value.title || '');
        const topics = computed(() => meta.value.topics || []);
        const body = computed(() => {
            if (!item.value || !item.value.content) return '';
            let text = item.value.content;
            if (title.value && text.startsWith(title.value)) {
                text = text.slice(title.value.length);
            }
            return text.trim();
        });
        const formatContent = (text) => (text ? text.replace(/\n/g, '<br/>') : '');

        return { item, isLoading, collapsed, title, topics, body, formatContent };
    },
    template: `
    <div v-if="item" class="mb-6 rounded-xl border border-indigo-100 bg-gradient-to-br from-indigo-50 to-white shadow-sm">
        <button @click="collapsed = !collapsed"
            class="w-full flex items-center gap-2 px-4 py-3 text-left">
            <svg class="w-4 h-4 text-indigo-500 flex-none" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path></svg>
            <span class="text-xs font-semibold uppercase tracking-wide text-indigo-600">Folder overview</span>
            <span v-if="title" class="text-sm font-semibold text-slate-800 truncate">— {{ title }}</span>
            <svg class="w-4 h-4 text-slate-400 ml-auto flex-none transition-transform" :class="{'rotate-180': !collapsed}" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path></svg>
        </button>
        <div v-show="!collapsed" class="px-4 pb-4">
            <div class="prose prose-sm prose-slate max-w-none text-slate-600" v-html="formatContent(body)"></div>
            <div v-if="topics.length" class="flex flex-wrap gap-1.5 mt-3">
                <span v-for="t in topics" :key="t" class="text-xs px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-700">{{ t }}</span>
            </div>
        </div>
    </div>
    `
};
