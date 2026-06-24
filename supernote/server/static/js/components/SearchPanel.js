import { search } from '../api/client.js';

export default {
    name: 'SearchPanel',
    emits: ['close', 'open-file'],
    template: `
        <div class="fixed inset-0 bg-slate-900/40 backdrop-blur-sm flex items-start justify-center z-[60] p-4 sm:pt-24" @click.self="$emit('close')">
            <div class="bg-white rounded-2xl shadow-2xl w-full max-w-3xl max-h-[85vh] flex flex-col animate-in zoom-in-95">
                <!-- Search Input -->
                <div class="flex items-center gap-3 p-4 border-b border-slate-100">
                    <svg class="w-5 h-5 text-slate-400 flex-none" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path>
                    </svg>
                    <input ref="input" v-model="query" @keyup.enter="runSearch" type="text"
                        placeholder="Search your notes by meaning, not just words..."
                        class="flex-1 text-lg outline-none placeholder-slate-400 text-slate-800 bg-transparent" />
                    <button @click="$emit('close')" class="text-slate-400 hover:text-slate-600 flex-none">
                        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                        </svg>
                    </button>
                </div>

                <!-- Results -->
                <div class="flex-1 overflow-y-auto p-2">
                    <div v-if="loading" class="flex flex-col items-center justify-center p-16 text-slate-400">
                        <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600 mb-3"></div>
                        <p class="text-sm animate-pulse">Embedding query &amp; searching…</p>
                    </div>

                    <div v-else-if="error" class="m-2 p-4 bg-rose-50 text-rose-700 rounded-xl text-sm">{{ error }}</div>

                    <div v-else-if="hasSearched && results.length === 0" class="p-16 text-center text-slate-400">
                        <p class="font-medium text-slate-500">No matches found</p>
                        <p class="text-sm mt-1">Try different phrasing, or check that your notes have finished indexing.</p>
                    </div>

                    <ul v-else class="divide-y divide-slate-50">
                        <li v-for="(r, i) in results" :key="i">
                            <button @click="openResult(r)"
                                class="w-full text-left p-3 rounded-xl hover:bg-indigo-50/60 transition-colors group">
                                <div class="flex items-center justify-between gap-3 mb-1">
                                    <span class="font-medium text-slate-800 truncate group-hover:text-indigo-700">{{ r.fileName }}</span>
                                    <span class="flex-none flex items-center gap-2 text-xs text-slate-400">
                                        <span v-if="r.date">{{ r.date }}</span>
                                        <span class="px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-500">p.{{ r.pageIndex + 1 }}</span>
                                        <span class="px-1.5 py-0.5 rounded-full" :class="scoreClass(r.score)">{{ Math.round(r.score * 100) }}%</span>
                                    </span>
                                </div>
                                <p class="text-sm text-slate-500 line-clamp-2">{{ r.textPreview || '(no preview)' }}</p>
                            </button>
                        </li>
                    </ul>

                    <div v-if="!hasSearched && !loading" class="p-16 text-center text-slate-300">
                        <svg class="w-12 h-12 mx-auto mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path>
                        </svg>
                        <p class="text-sm text-slate-400">Semantic search across every transcribed page.</p>
                    </div>
                </div>
            </div>
        </div>
    `,
    data() {
        return {
            query: '',
            results: [],
            loading: false,
            error: null,
            hasSearched: false
        };
    },
    mounted() {
        this.$nextTick(() => this.$refs.input?.focus());
    },
    methods: {
        async runSearch() {
            const q = this.query.trim();
            if (!q) return;
            this.loading = true;
            this.error = null;
            try {
                this.results = await search(q, { topN: 20 });
                this.hasSearched = true;
            } catch (e) {
                this.error = e.message;
            } finally {
                this.loading = false;
            }
        },
        openResult(r) {
            this.$emit('open-file', {
                id: String(r.fileId),
                name: r.fileName,
                isDirectory: false,
                extension: 'note'
            });
        },
        scoreClass(score) {
            if (score >= 0.6) return 'bg-emerald-100 text-emerald-700';
            if (score >= 0.4) return 'bg-amber-100 text-amber-700';
            return 'bg-slate-100 text-slate-500';
        }
    }
};
