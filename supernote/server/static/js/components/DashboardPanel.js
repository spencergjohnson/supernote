import { fetchDashboard } from '../api/client.js';

export default {
    name: 'DashboardPanel',
    emits: ['close', 'open-file'],
    template: `
        <div class="fixed inset-0 bg-slate-900/40 backdrop-blur-sm flex items-center justify-center z-[60] p-4" @click.self="$emit('close')">
            <div class="bg-slate-50 rounded-2xl shadow-2xl w-full max-w-5xl max-h-[90vh] flex flex-col animate-in zoom-in-95">
                <!-- Header -->
                <div class="flex items-center justify-between p-4 border-b border-slate-200 bg-white rounded-t-2xl">
                    <h2 class="text-xl font-bold text-slate-800 flex items-center gap-2">
                        <svg class="w-6 h-6 text-indigo-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"></path>
                        </svg>
                        Insights
                    </h2>
                    <button @click="$emit('close')" class="text-slate-400 hover:text-slate-600">
                        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                        </svg>
                    </button>
                </div>

                <!-- Content -->
                <div class="flex-1 overflow-y-auto p-5 space-y-6">
                    <div v-if="loading" class="flex justify-center p-20">
                        <div class="animate-spin rounded-full h-10 w-10 border-b-2 border-indigo-600"></div>
                    </div>
                    <div v-else-if="error" class="p-4 bg-rose-50 text-rose-700 rounded-xl">{{ error }}</div>

                    <template v-else-if="stats">
                        <!-- Stat cards -->
                        <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
                            <div class="bg-white rounded-xl p-4 shadow-sm border border-slate-100">
                                <p class="text-3xl font-bold text-slate-800">{{ stats.notebookCount }}</p>
                                <p class="text-sm text-slate-500 mt-1">Notebooks</p>
                            </div>
                            <div class="bg-white rounded-xl p-4 shadow-sm border border-slate-100">
                                <p class="text-3xl font-bold text-slate-800">{{ stats.pageCount }}</p>
                                <p class="text-sm text-slate-500 mt-1">Pages</p>
                            </div>
                            <div class="bg-white rounded-xl p-4 shadow-sm border border-slate-100">
                                <p class="text-3xl font-bold text-slate-800">{{ stats.pagesWithText }}</p>
                                <p class="text-sm text-slate-500 mt-1">Transcribed</p>
                            </div>
                            <div class="bg-white rounded-xl p-4 shadow-sm border border-slate-100">
                                <p class="text-3xl font-bold text-slate-800">{{ stats.summaryCount }}</p>
                                <p class="text-sm text-slate-500 mt-1">Summaries</p>
                            </div>
                        </div>

                        <!-- Coverage -->
                        <div class="bg-white rounded-xl p-5 shadow-sm border border-slate-100">
                            <h3 class="text-sm font-semibold text-slate-700 mb-3">Indexing coverage</h3>
                            <div class="space-y-3">
                                <div>
                                    <div class="flex justify-between text-xs text-slate-500 mb-1">
                                        <span>Transcribed (OCR)</span>
                                        <span>{{ stats.pagesWithText }} / {{ stats.pageCount }} ({{ pct(stats.pagesWithText) }}%)</span>
                                    </div>
                                    <div class="w-full bg-slate-100 rounded-full h-2">
                                        <div class="bg-indigo-500 h-2 rounded-full transition-all" :style="{ width: pct(stats.pagesWithText) + '%' }"></div>
                                    </div>
                                </div>
                                <div>
                                    <div class="flex justify-between text-xs text-slate-500 mb-1">
                                        <span>Embedded (searchable)</span>
                                        <span>{{ stats.pagesEmbedded }} / {{ stats.pageCount }} ({{ pct(stats.pagesEmbedded) }}%)</span>
                                    </div>
                                    <div class="w-full bg-slate-100 rounded-full h-2">
                                        <div class="bg-emerald-500 h-2 rounded-full transition-all" :style="{ width: pct(stats.pagesEmbedded) + '%' }"></div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- Activity over time -->
                        <div class="bg-white rounded-xl p-5 shadow-sm border border-slate-100">
                            <h3 class="text-sm font-semibold text-slate-700 mb-4">Writing activity by month
                                <span class="font-normal text-slate-400">(inferred from page dates)</span>
                            </h3>
                            <div v-if="stats.activityByMonth.length === 0" class="text-sm text-slate-400 py-6 text-center">
                                Not enough dated pages yet.
                            </div>
                            <div v-else class="flex items-end gap-1 h-40">
                                <div v-for="b in stats.activityByMonth" :key="b.period"
                                    class="flex-1 flex flex-col items-center justify-end group min-w-0" :title="b.period + ': ' + b.count + ' pages'">
                                    <span class="text-[10px] text-slate-400 mb-1 opacity-0 group-hover:opacity-100 transition-opacity">{{ b.count }}</span>
                                    <div class="w-full bg-indigo-400 group-hover:bg-indigo-600 rounded-t transition-all"
                                        :style="{ height: barHeight(b.count) + '%' }"></div>
                                    <span class="text-[9px] text-slate-400 mt-1 truncate w-full text-center">{{ shortMonth(b.period) }}</span>
                                </div>
                            </div>
                        </div>

                        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
                            <!-- Top notebooks -->
                            <div class="bg-white rounded-xl p-5 shadow-sm border border-slate-100">
                                <h3 class="text-sm font-semibold text-slate-700 mb-4">Largest notebooks</h3>
                                <div v-if="stats.topNotebooks.length === 0" class="text-sm text-slate-400">No notebooks yet.</div>
                                <ul v-else class="space-y-2">
                                    <li v-for="nb in stats.topNotebooks" :key="nb.fileId">
                                        <button @click="openNotebook(nb)" class="w-full text-left group">
                                            <div class="flex justify-between text-xs mb-1">
                                                <span class="truncate text-slate-600 group-hover:text-indigo-700">{{ nb.fileName }}</span>
                                                <span class="text-slate-400 flex-none ml-2">{{ nb.pageCount }}p</span>
                                            </div>
                                            <div class="w-full bg-slate-100 rounded-full h-1.5">
                                                <div class="bg-indigo-400 group-hover:bg-indigo-600 h-1.5 rounded-full transition-all"
                                                    :style="{ width: notebookPct(nb.pageCount) + '%' }"></div>
                                            </div>
                                        </button>
                                    </li>
                                </ul>
                            </div>

                            <!-- Top tags -->
                            <div class="bg-white rounded-xl p-5 shadow-sm border border-slate-100">
                                <h3 class="text-sm font-semibold text-slate-700 mb-4">Top tags</h3>
                                <div v-if="stats.topTags.length === 0" class="text-sm text-slate-400">No tags yet.</div>
                                <div v-else class="flex flex-wrap gap-2">
                                    <span v-for="t in stats.topTags" :key="t.name"
                                        class="px-3 py-1 rounded-full bg-indigo-50 text-indigo-700 text-sm"
                                        :style="{ fontSize: tagSize(t.count) + 'rem' }">
                                        {{ t.name }} <span class="text-indigo-400">{{ t.count }}</span>
                                    </span>
                                </div>
                            </div>
                        </div>
                    </template>
                </div>

                <!-- Footer -->
                <div class="p-4 border-t border-slate-200 bg-white rounded-b-2xl flex justify-end">
                    <button @click="loadData" class="mr-2 px-4 py-2 bg-white border border-slate-300 rounded-lg shadow-sm text-sm font-medium text-slate-700 hover:bg-slate-50">Refresh</button>
                    <button @click="$emit('close')" class="px-4 py-2 bg-indigo-600 rounded-lg shadow-sm text-sm font-medium text-white hover:bg-indigo-700">Close</button>
                </div>
            </div>
        </div>
    `,
    data() {
        return {
            loading: true,
            error: null,
            stats: null
        };
    },
    computed: {
        maxActivity() {
            if (!this.stats?.activityByMonth?.length) return 1;
            return Math.max(1, ...this.stats.activityByMonth.map(b => b.count));
        },
        maxNotebook() {
            if (!this.stats?.topNotebooks?.length) return 1;
            return Math.max(1, ...this.stats.topNotebooks.map(n => n.pageCount));
        },
        maxTag() {
            if (!this.stats?.topTags?.length) return 1;
            return Math.max(1, ...this.stats.topTags.map(t => t.count));
        }
    },
    async mounted() {
        await this.loadData();
    },
    methods: {
        async loadData() {
            this.loading = true;
            this.error = null;
            try {
                this.stats = await fetchDashboard();
            } catch (e) {
                this.error = e.message;
            } finally {
                this.loading = false;
            }
        },
        pct(n) {
            if (!this.stats || !this.stats.pageCount) return 0;
            return Math.round((n / this.stats.pageCount) * 100);
        },
        barHeight(count) {
            return Math.max(4, Math.round((count / this.maxActivity) * 100));
        },
        notebookPct(count) {
            return Math.max(3, Math.round((count / this.maxNotebook) * 100));
        },
        tagSize(count) {
            return (0.75 + (count / this.maxTag) * 0.5).toFixed(2);
        },
        shortMonth(period) {
            const parts = (period || '').split('-');
            if (parts.length !== 2) return period;
            return parts[1] + "/" + parts[0].slice(2);
        },
        openNotebook(nb) {
            this.$emit('open-file', {
                id: String(nb.fileId),
                name: nb.fileName,
                isDirectory: false,
                extension: 'note'
            });
        }
    }
};
