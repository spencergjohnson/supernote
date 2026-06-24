import { fetchRecycleList, revertRecycle, deleteRecycle, clearRecycle } from '../api/client.js';

export default {
    name: 'RecyclePanel',
    template: `
        <div class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" @click.self="$emit('close')">
            <div class="bg-white rounded-lg shadow-xl w-full max-w-3xl max-h-[90vh] flex flex-col">
                <!-- Header -->
                <div class="flex items-center justify-between p-4 border-b">
                    <div>
                        <h2 class="text-xl font-bold text-gray-800">Recycle Bin</h2>
                        <p v-if="totalSize > 0" class="text-sm text-gray-500 mt-0.5">
                            {{ formatSize(totalSize) }} on disk
                        </p>
                    </div>
                    <button @click="$emit('close')" class="text-gray-500 hover:text-gray-700">
                        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                        </svg>
                    </button>
                </div>

                <!-- Content -->
                <div class="flex-1 overflow-y-auto p-4">
                    <div v-if="loading" class="flex justify-center p-8">
                        <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600"></div>
                    </div>

                    <div v-else-if="error" class="p-4 bg-red-50 text-red-700 rounded-lg">{{ error }}</div>

                    <div v-else-if="items.length === 0" class="text-center py-12 text-gray-500">
                        <svg class="w-12 h-12 mx-auto mb-3 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
                                d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16">
                            </path>
                        </svg>
                        Recycle bin is empty
                    </div>

                    <div v-else class="overflow-x-auto border rounded-lg">
                        <table class="min-w-full divide-y divide-gray-200">
                            <thead class="bg-gray-50">
                                <tr>
                                    <th class="px-4 py-3 text-left">
                                        <input type="checkbox" @change="toggleSelectAll" :checked="allSelected"
                                            class="rounded border-gray-300 text-indigo-600">
                                    </th>
                                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Name</th>
                                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Size</th>
                                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Deleted</th>
                                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
                                </tr>
                            </thead>
                            <tbody class="bg-white divide-y divide-gray-200">
                                <tr v-for="item in items" :key="item.fileId" class="hover:bg-gray-50">
                                    <td class="px-4 py-3">
                                        <input type="checkbox" :value="parseInt(item.fileId)"
                                            v-model="selectedIds" class="rounded border-gray-300 text-indigo-600">
                                    </td>
                                    <td class="px-4 py-3">
                                        <div class="flex items-center gap-2">
                                            <svg v-if="item.isFolder === 'Y'" class="w-4 h-4 text-yellow-500 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                                                <path d="M2 6a2 2 0 012-2h5l2 2h5a2 2 0 012 2v6a2 2 0 01-2 2H4a2 2 0 01-2-2V6z"></path>
                                            </svg>
                                            <svg v-else class="w-4 h-4 text-gray-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                                                    d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z">
                                                </path>
                                            </svg>
                                            <span class="text-sm text-gray-900 truncate max-w-xs" :title="item.fileName">{{ item.fileName }}</span>
                                        </div>
                                    </td>
                                    <td class="px-4 py-3 text-sm text-gray-500 whitespace-nowrap">{{ item.isFolder === 'Y' ? '—' : formatSize(item.size) }}</td>
                                    <td class="px-4 py-3 text-sm text-gray-500 whitespace-nowrap">{{ formatDate(item.updateTime) }}</td>
                                    <td class="px-4 py-3 whitespace-nowrap">
                                        <button @click="restoreItem(item)" :disabled="busy"
                                            class="text-xs text-indigo-600 hover:text-indigo-800 font-medium mr-3 disabled:opacity-50">
                                            Restore
                                        </button>
                                        <button @click="deleteItem(item)" :disabled="busy"
                                            class="text-xs text-red-600 hover:text-red-800 font-medium disabled:opacity-50">
                                            Delete
                                        </button>
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>

                <!-- Footer -->
                <div class="p-4 border-t bg-gray-50 flex items-center justify-between gap-2">
                    <div class="flex gap-2">
                        <button v-if="selectedIds.length > 0" @click="restoreSelected" :disabled="busy"
                            class="px-3 py-2 bg-white border border-gray-300 rounded shadow-sm text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50">
                            Restore ({{ selectedIds.length }})
                        </button>
                        <button v-if="selectedIds.length > 0" @click="deleteSelected" :disabled="busy"
                            class="px-3 py-2 bg-white border border-red-300 rounded shadow-sm text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-50">
                            Delete ({{ selectedIds.length }})
                        </button>
                    </div>
                    <div class="flex gap-2">
                        <button @click="loadData" :disabled="busy"
                            class="px-4 py-2 bg-white border border-gray-300 rounded shadow-sm text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50">
                            Refresh
                        </button>
                        <button v-if="items.length > 0" @click="emptyBin" :disabled="busy"
                            class="px-4 py-2 bg-red-600 border border-transparent rounded shadow-sm text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50">
                            Empty Bin
                        </button>
                        <button @click="$emit('close')"
                            class="px-4 py-2 bg-indigo-600 border border-transparent rounded shadow-sm text-sm font-medium text-white hover:bg-indigo-700">
                            Close
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `,
    data() {
        return {
            loading: true,
            busy: false,
            error: null,
            items: [],
            totalSize: 0,
            selectedIds: []
        };
    },
    computed: {
        allSelected() {
            return this.items.length > 0 && this.selectedIds.length === this.items.length;
        }
    },
    async mounted() {
        await this.loadData();
    },
    methods: {
        async loadData() {
            this.loading = true;
            this.error = null;
            this.selectedIds = [];
            try {
                const data = await fetchRecycleList();
                this.items = data.recycleFileVOList || [];
                this.totalSize = data.totalSize || 0;
            } catch (e) {
                this.error = e.message;
            } finally {
                this.loading = false;
            }
        },
        toggleSelectAll(e) {
            this.selectedIds = e.target.checked
                ? this.items.map(i => parseInt(i.fileId))
                : [];
        },
        async restoreItem(item) {
            await this._withBusy(() => revertRecycle([parseInt(item.fileId)]));
        },
        async deleteItem(item) {
            if (!confirm(`Permanently delete "${item.fileName}"? This cannot be undone.`)) return;
            await this._withBusy(() => deleteRecycle([parseInt(item.fileId)]));
        },
        async restoreSelected() {
            if (this.selectedIds.length === 0) return;
            await this._withBusy(() => revertRecycle([...this.selectedIds]));
        },
        async deleteSelected() {
            if (this.selectedIds.length === 0) return;
            if (!confirm(`Permanently delete ${this.selectedIds.length} item(s)? This cannot be undone.`)) return;
            await this._withBusy(() => deleteRecycle([...this.selectedIds]));
        },
        async emptyBin() {
            if (!confirm('Permanently delete all items in the recycle bin? This cannot be undone.')) return;
            await this._withBusy(() => clearRecycle());
        },
        async _withBusy(fn) {
            this.busy = true;
            this.error = null;
            try {
                await fn();
                await this.loadData();
            } catch (e) {
                this.error = e.message;
            } finally {
                this.busy = false;
            }
        },
        formatSize(bytes) {
            if (!bytes) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        },
        formatDate(timestamp) {
            if (!timestamp) return '—';
            const ms = parseInt(timestamp);
            if (isNaN(ms)) return timestamp;
            return new Date(ms).toLocaleString();
        }
    }
};
