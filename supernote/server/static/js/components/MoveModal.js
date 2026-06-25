import { fetchFiles } from '../api/client.js';

export default {
    name: 'MoveModal',
    props: ['itemIds'],
    template: `
        <div class="fixed inset-0 z-[110] flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm" @click.self="$emit('close')">
            <div class="bg-white dark:bg-slate-800 rounded-2xl shadow-2xl w-full max-w-md flex flex-col max-h-[80vh] animate-in zoom-in-95">
                <div class="p-6 border-b border-slate-100 dark:border-slate-700 flex items-center justify-between">
                    <h3 class="text-lg font-bold text-slate-900 dark:text-slate-100">Move {{ itemIds.length }} items to...</h3>
                    <button @click="$emit('close')" class="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200">
                        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
                    </button>
                </div>

                <div class="flex-1 overflow-y-auto p-2">
                    <div @click="selectTarget('0')" class="flex items-center gap-3 p-3 rounded-xl hover:bg-slate-50 dark:hover:bg-slate-700 cursor-pointer transition-colors" :class="{'bg-indigo-50 dark:bg-indigo-900/20 border border-indigo-100 dark:border-indigo-800': targetDirId === '0'}">
                        <div class="w-10 h-10 bg-indigo-100 dark:bg-indigo-900/40 text-indigo-600 dark:text-indigo-400 rounded-lg flex items-center justify-center">
                            <svg class="w-6 h-6" fill="currentColor" viewBox="0 0 20 20"><path d="M10.707 2.293a1 1 0 00-1.414 0l-7 7a1 1 0 001.414 1.414L4 10.414V17a1 1 0 001 1h2a1 1 0 001-1v-2a1 1 0 011-1h2a1 1 0 011 1v2a1 1 0 001 1h2a1 1 0 001-1v-6.586l.293.293a1 1 0 001.414-1.414l-7-7z"></path></svg>
                        </div>
                        <span class="font-medium text-slate-700 dark:text-slate-200">Cloud Root</span>
                    </div>

                    <div v-for="folder in folders" :key="folder.id" @click="selectTarget(folder.id)" class="flex items-center gap-3 p-3 rounded-xl hover:bg-slate-50 dark:hover:bg-slate-700 cursor-pointer transition-colors" :class="{'bg-indigo-50 dark:bg-indigo-900/20 border border-indigo-100 dark:border-indigo-800': targetDirId === folder.id}">
                        <div class="w-10 h-10 bg-amber-100 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400 rounded-lg flex items-center justify-center">
                            <svg class="w-6 h-6" fill="currentColor" viewBox="0 0 20 20"><path d="M2 6a2 2 0 012-2h5l2 2h5a2 2 0 012 2v6a2 2 0 01-2 2H4a2 2 0 01-2-2V6z"></path></svg>
                        </div>
                        <span class="font-medium text-slate-700 dark:text-slate-200">{{ folder.name }}</span>
                    </div>
                </div>

                <div class="p-6 border-t border-slate-100 dark:border-slate-700 flex justify-end gap-3">
                    <button @click="$emit('close')" class="px-4 py-2 text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 font-medium">Cancel</button>
                    <button @click="confirmMove" :disabled="!targetDirId"
                        class="px-6 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white rounded-xl font-bold shadow-lg shadow-indigo-200 transition-all">
                        Move Here
                    </button>
                </div>
            </div>
        </div>
    `,
    data() {
        return {
            folders: [],
            targetDirId: null,
            isLoading: false
        }
    },
    async mounted() {
        await this.loadFolders();
    },
    methods: {
        async loadFolders() {
            this.isLoading = true;
            try {
                const files = await fetchFiles("0");
                this.folders = files.filter(f => f.isDirectory);
            } catch (e) {
                console.error(e);
            } finally {
                this.isLoading = false;
            }
        },
        selectTarget(id) {
            this.targetDirId = id;
        },
        confirmMove() {
            this.$emit('confirm', this.targetDirId);
        }
    }
}
