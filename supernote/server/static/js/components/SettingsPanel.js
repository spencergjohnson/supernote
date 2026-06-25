import { ref, computed, onMounted } from 'vue';
import { fetchModels, fetchSystemConfig, saveSystemConfig } from '../api/client.js';

export default {
    name: 'SettingsPanel',
    emits: ['close'],
    setup(_props, { emit }) {
        const isLoading = ref(true);
        const isSaving = ref(false);
        const error = ref(null);
        const success = ref(false);

        const models = ref([]);
        const config = ref({
            vision: '', summary: '', chat: '', embedding: '',
            summaryEffective: '', chatEffective: ''
        });
        const draft = ref({ vision: '', summary: '', chat: '', embedding: '' });

        const visionModels = computed(() =>
            models.value.filter(m => m.vision || m.text).sort((a, b) => (b.vision ? 1 : 0) - (a.vision ? 1 : 0))
        );
        const textModels = computed(() => models.value.filter(m => m.text));
        const embeddingModels = computed(() => models.value.filter(m => m.embedding));

        const load = async () => {
            isLoading.value = true;
            error.value = null;
            try {
                const [mData, cData] = await Promise.all([fetchModels(), fetchSystemConfig()]);
                models.value = mData.models || [];
                config.value = {
                    vision: cData.vision || '',
                    summary: cData.summary ?? '',
                    chat: cData.chat ?? '',
                    embedding: cData.embedding || '',
                    summaryEffective: cData.summaryEffective || '',
                    chatEffective: cData.chatEffective || ''
                };
                draft.value = {
                    vision: config.value.vision,
                    summary: config.value.summary,
                    chat: config.value.chat,
                    embedding: config.value.embedding
                };
            } catch (e) {
                error.value = e.message || 'Failed to load settings';
            } finally {
                isLoading.value = false;
            }
        };

        onMounted(load);

        const save = async () => {
            isSaving.value = true;
            error.value = null;
            success.value = false;
            try {
                const updated = await saveSystemConfig({
                    vision: draft.value.vision || null,
                    summary: draft.value.summary,
                    chat: draft.value.chat,
                    embedding: draft.value.embedding || null
                });
                config.value = {
                    vision: updated.vision || '',
                    summary: updated.summary ?? '',
                    chat: updated.chat ?? '',
                    embedding: updated.embedding || '',
                    summaryEffective: updated.summaryEffective || '',
                    chatEffective: updated.chatEffective || ''
                };
                draft.value = {
                    vision: config.value.vision,
                    summary: config.value.summary,
                    chat: config.value.chat,
                    embedding: config.value.embedding
                };
                success.value = true;
                setTimeout(() => { success.value = false; }, 3000);
            } catch (e) {
                error.value = e.message || 'Failed to save settings';
            } finally {
                isSaving.value = false;
            }
        };

        const isDirty = computed(() =>
            draft.value.vision !== config.value.vision ||
            draft.value.summary !== config.value.summary ||
            draft.value.chat !== config.value.chat ||
            draft.value.embedding !== config.value.embedding
        );

        const capBadge = (model) => {
            if (model.vision && model.text) return 'vision · text';
            if (model.vision) return 'vision';
            if (model.embedding) return 'embedding';
            return 'text';
        };

        return {
            isLoading, isSaving, error, success, models, config, draft, isDirty,
            visionModels, textModels, embeddingModels, save, capBadge
        };
    },
    template: `
<div class="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 backdrop-blur-sm" @click.self="$emit('close')">
    <div class="bg-white dark:bg-slate-800 w-full sm:max-w-lg sm:mx-4 sm:rounded-2xl shadow-2xl overflow-hidden">

        <!-- Header -->
        <div class="flex items-center gap-3 px-5 py-4 border-b border-slate-100 dark:border-slate-700">
            <svg class="w-5 h-5 text-slate-500 dark:text-slate-400 flex-none" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                    d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/>
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
            </svg>
            <h2 class="font-semibold text-slate-800 dark:text-slate-100 flex-1">AI Model Settings</h2>
            <button @click="$emit('close')" class="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200">
                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                </svg>
            </button>
        </div>

        <div class="px-5 py-5 space-y-5 max-h-[70vh] overflow-y-auto">

            <div v-if="isLoading" class="flex items-center justify-center py-12 text-slate-400">
                <svg class="w-5 h-5 animate-spin mr-2" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                </svg>
                Loading models…
            </div>

            <template v-else>
                <p class="text-xs text-slate-500 dark:text-slate-400">
                    Select which model to use for each AI task. Changes take effect immediately without restarting.
                    Leave unchanged to keep the current selection.
                </p>

                <!-- Vision / OCR -->
                <div>
                    <label class="block text-sm font-medium text-slate-700 dark:text-slate-200 mb-1">
                        Vision / OCR
                        <span class="ml-1 text-xs font-normal text-slate-400 dark:text-slate-500">— must support images</span>
                    </label>
                    <select v-model="draft.vision"
                        class="w-full rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-sm text-slate-700 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-300">
                        <option v-for="m in visionModels" :key="m.id" :value="m.id">
                            {{ m.id }} ({{ capBadge(m) }})
                        </option>
                    </select>
                </div>

                <!-- Summary -->
                <div>
                    <label class="block text-sm font-medium text-slate-700 dark:text-slate-200 mb-1">
                        Summaries
                        <span class="ml-1 text-xs font-normal text-slate-400 dark:text-slate-500">— note &amp; folder summaries (text only)</span>
                    </label>
                    <select v-model="draft.summary"
                        class="w-full rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-sm text-slate-700 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-300">
                        <option value="">Same as Vision/OCR</option>
                        <option v-for="m in textModels" :key="m.id" :value="m.id">
                            {{ m.id }} ({{ capBadge(m) }})
                        </option>
                    </select>
                    <p v-if="!draft.summary && config.summaryEffective"
                        class="mt-1 text-xs text-slate-400 dark:text-slate-500">
                        Inherits: <span class="font-medium text-slate-500 dark:text-slate-400">{{ config.summaryEffective }}</span>
                    </p>
                </div>

                <!-- Chat -->
                <div>
                    <label class="block text-sm font-medium text-slate-700 dark:text-slate-200 mb-1">
                        Chat / Q&amp;A
                        <span class="ml-1 text-xs font-normal text-slate-400 dark:text-slate-500">— RAG answers (text only)</span>
                    </label>
                    <select v-model="draft.chat"
                        class="w-full rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-sm text-slate-700 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-300">
                        <option value="">Same as Summary</option>
                        <option v-for="m in textModels" :key="m.id" :value="m.id">
                            {{ m.id }} ({{ capBadge(m) }})
                        </option>
                    </select>
                    <p v-if="!draft.chat && config.chatEffective"
                        class="mt-1 text-xs text-slate-400 dark:text-slate-500">
                        Inherits: <span class="font-medium text-slate-500 dark:text-slate-400">{{ config.chatEffective }}</span>
                    </p>
                </div>

                <!-- Embedding -->
                <div>
                    <label class="block text-sm font-medium text-slate-700 dark:text-slate-200 mb-1">
                        Embedding
                        <span class="ml-1 text-xs font-normal text-slate-400 dark:text-slate-500">— semantic search</span>
                    </label>
                    <select v-if="embeddingModels.length > 0" v-model="draft.embedding"
                        class="w-full rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-sm text-slate-700 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-300">
                        <option v-for="m in embeddingModels" :key="m.id" :value="m.id">
                            {{ m.id }} ({{ capBadge(m) }})
                        </option>
                    </select>
                    <div v-else class="mt-1 flex items-start gap-2 p-3 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800">
                        <svg class="w-4 h-4 text-amber-500 flex-none mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                        </svg>
                        <p class="text-xs text-amber-700 dark:text-amber-400">
                            No embedding-capable model detected. Make sure your llama-swap config includes
                            <code class="font-mono bg-amber-100 dark:bg-amber-900/40 px-1 rounded">capabilities: [embedding]</code>
                            for the embedding model and it is running.
                        </p>
                    </div>
                    <p v-if="embeddingModels.length > 0 && config.embedding"
                        class="mt-1 text-xs text-slate-400 dark:text-slate-500">
                        Active: <span class="font-medium text-slate-500 dark:text-slate-400">{{ config.embedding }}</span>
                    </p>
                </div>
            </template>
        </div>

        <!-- Footer -->
        <div class="flex items-center gap-3 px-5 py-4 border-t border-slate-100 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 sm:rounded-b-2xl">
            <div class="flex-1 text-sm">
                <span v-if="success" class="text-green-600 dark:text-green-400 font-medium">Saved successfully.</span>
                <span v-else-if="error" class="text-red-500">{{ error }}</span>
            </div>
            <button @click="$emit('close')"
                class="px-4 py-2 rounded-lg text-sm text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors">
                Cancel
            </button>
            <button @click="save" :disabled="!isDirty || isSaving || isLoading"
                class="px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
                <span v-if="isSaving">Saving…</span>
                <span v-else>Save</span>
            </button>
        </div>
    </div>
</div>
    `
};
