import { fetchSystemTasks, fetchCapacity } from '../api/client.js';

export default {
    name: 'SystemPanel',
    template: `
        <div class="fixed inset-0 bg-black/50 flex items-center justify-center z-50" @click.self="$emit('close')">
            <div class="bg-white dark:bg-slate-800 rounded-xl shadow-2xl w-full max-w-4xl max-h-[90vh] flex flex-col">
                <!-- Header -->
                <div class="flex items-center justify-between p-4 border-b border-slate-200 dark:border-slate-700">
                    <h2 class="text-xl font-bold text-slate-800 dark:text-slate-100">System Status</h2>
                    <button @click="$emit('close')" class="text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200">
                        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                        </svg>
                    </button>
                </div>

                <!-- Content -->
                <div class="flex-1 overflow-y-auto p-4 space-y-6">
                    <!-- Storage Quota -->
                    <div class="bg-slate-50 dark:bg-slate-700/50 p-4 rounded-lg">
                        <h3 class="text-lg font-medium text-slate-900 dark:text-slate-100 mb-2">Storage Usage</h3>
                        <div v-if="capacity" class="space-y-2">
                            <div class="flex justify-between text-sm text-slate-600 dark:text-slate-400">
                                <span>{{ formatSize(capacity.usedCapacity) }} used</span>
                                <span>{{ formatSize(capacity.totalCapacity) }} total</span>
                            </div>
                            <div class="w-full bg-slate-200 dark:bg-slate-600 rounded-full h-2.5">
                                <div class="bg-indigo-600 h-2.5 rounded-full transition-all duration-500" :style="{ width: usagePercent + '%' }"></div>
                            </div>
                            <div v-if="capacity.recycleSize > 0" class="text-xs text-slate-500 dark:text-slate-400 flex items-center gap-1 mt-1">
                                <svg class="w-3.5 h-3.5 text-slate-400 dark:text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                                        d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16">
                                    </path>
                                </svg>
                                {{ formatSize(capacity.recycleSize) }} in recycle bin (not counted toward quota)
                            </div>
                        </div>
                        <div v-else class="animate-pulse bg-slate-200 dark:bg-slate-600 h-10 rounded"></div>
                    </div>

                    <!-- Tasks -->
                    <div>
                        <h3 class="text-lg font-medium text-slate-900 dark:text-slate-100 mb-4">Processing Queue</h3>
                        <div v-if="loading" class="flex justify-center p-8">
                            <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600"></div>
                        </div>

                        <div v-else-if="error" class="p-4 bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400 rounded-lg">
                            {{ error }}
                        </div>

                        <div v-else class="overflow-x-auto border border-slate-200 dark:border-slate-700 rounded-lg">
                            <table class="min-w-full divide-y divide-slate-200 dark:divide-slate-700">
                                <thead class="bg-slate-50 dark:bg-slate-700">
                                    <tr>
                                        <th class="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">File ID</th>
                                        <th class="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">Type</th>
                                        <th class="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">Key</th>
                                        <th class="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">Status</th>
                                        <th class="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">Retries</th>
                                        <th class="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">Updated</th>
                                        <th class="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">Details</th>
                                    </tr>
                                </thead>
                                <tbody class="bg-white dark:bg-slate-800 divide-y divide-slate-200 dark:divide-slate-700">
                                    <tr v-for="task in tasks" :key="task.id" class="hover:bg-slate-50 dark:hover:bg-slate-700/50">
                                        <td class="px-6 py-4 whitespace-nowrap text-sm text-slate-900 dark:text-slate-100">{{ task.fileId }}</td>
                                        <td class="px-6 py-4 whitespace-nowrap text-sm text-slate-900 dark:text-slate-100">{{ task.taskType }}</td>
                                        <td class="px-6 py-4 whitespace-nowrap text-sm text-slate-500 dark:text-slate-400">{{ task.key }}</td>
                                        <td class="px-6 py-4 whitespace-nowrap">
                                            <span :class="statusClass(task.status)" class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full">
                                                {{ task.status }}
                                            </span>
                                        </td>
                                        <td class="px-6 py-4 whitespace-nowrap text-sm text-slate-500 dark:text-slate-400">{{ task.retryCount }}</td>
                                        <td class="px-6 py-4 whitespace-nowrap text-sm text-slate-500 dark:text-slate-400">{{ formatDate(task.updateTime) }}</td>
                                        <td class="px-6 py-4 text-sm text-red-600 dark:text-red-400 max-w-xs truncate" :title="task.lastError">
                                            {{ task.lastError }}
                                        </td>
                                    </tr>
                                    <tr v-if="tasks.length === 0">
                                        <td colspan="7" class="px-6 py-4 text-center text-sm text-slate-500 dark:text-slate-400">No active tasks</td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>

                <!-- Footer -->
                <div class="p-4 border-t border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 rounded-b-xl flex justify-end">
                    <button @click="loadData" class="mr-2 px-4 py-2 bg-white dark:bg-slate-700 border border-slate-300 dark:border-slate-600 rounded-lg shadow-sm text-sm font-medium text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-600">
                        Refresh
                    </button>
                    <button @click="$emit('close')" class="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 border border-transparent rounded-lg shadow-sm text-sm font-medium text-white transition-colors">
                        Close
                    </button>
                </div>
            </div>
        </div>
    `,
    data() {
        return {
            loading: true,
            error: null,
            tasks: [],
            capacity: null
        }
    },
    computed: {
        usagePercent() {
            if (!this.capacity || this.capacity.totalCapacity === 0) return 0;
            return Math.min(100, (this.capacity.usedCapacity / this.capacity.totalCapacity) * 100);
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
                const [tasksResult, capacityResult] = await Promise.all([
                    fetchSystemTasks(),
                    fetchCapacity()
                ]);

                if (tasksResult.success) {
                    this.tasks = tasksResult.tasks;
                } else {
                    this.error = "Failed to load tasks";
                }

                this.capacity = capacityResult;
            } catch (e) {
                this.error = e.message;
            } finally {
                this.loading = false;
            }
        },
        statusClass(status) {
            const classes = {
                'PENDING': 'bg-yellow-100 dark:bg-yellow-900/40 text-yellow-800 dark:text-yellow-400',
                'PROCESSING': 'bg-blue-100 dark:bg-blue-900/40 text-blue-800 dark:text-blue-400',
                'COMPLETED': 'bg-green-100 dark:bg-green-900/40 text-green-800 dark:text-green-400',
                'FAILED': 'bg-red-100 dark:bg-red-900/40 text-red-800 dark:text-red-400'
            };
            return classes[status] || 'bg-slate-100 dark:bg-slate-700 text-slate-800 dark:text-slate-300';
        },
        formatDate(timestamp) {
            if (!timestamp) return '-';
            return new Date(timestamp).toLocaleString();
        },
        formatSize(bytes) {
            if (!bytes) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        }
    }
}
