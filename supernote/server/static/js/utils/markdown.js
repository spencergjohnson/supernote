/**
 * Minimal dependency-free Markdown → HTML renderer for summary content.
 *
 * Handles the subset produced by the LLM summariser:
 *   - ATX headings: ## heading, # heading
 *   - Bold: **text**
 *   - Unordered lists: lines starting with "- " or "* "
 *   - Ordered lists: lines starting with "1. " etc.
 *   - Horizontal rules: "---"
 *   - Paragraph breaks (blank lines)
 *   - Line breaks within paragraphs
 *
 * Also guards against raw JSON blobs that may have been stored by older
 * pipeline runs: if the content looks like a JSON object/array, it attempts
 * to extract a human-readable field before rendering, and falls back to a
 * neutral placeholder if nothing useful is found.
 */

/**
 * HTML-escape a plain-text string.
 * @param {string} str
 * @returns {string}
 */
function escapeHtml(str) {
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

/**
 * Strip Markdown code fences (```json ... ``` or ``` ... ```) and slice to the
 * outermost JSON object/array, mirroring the backend `_extract_json` helper.
 * Returns the original text when no fences/braces are detected.
 * @param {string} text
 * @returns {string}
 */
function stripJsonFences(text) {
    let stripped = text.trim();
    if (stripped.startsWith('```')) {
        const lines = stripped.split('\n');
        let end = lines.length;
        for (let i = lines.length - 1; i > 0; i--) {
            if (lines[i].trim() === '```') { end = i; break; }
        }
        stripped = lines.slice(1, end).join('\n').trim();
    }
    return stripped;
}

/**
 * Recursively pull a human-readable string out of a parsed JSON value produced
 * by the summary pipeline (folder/overview/note-timeline shapes).
 * @param {*} data
 * @returns {string|null}
 */
function readableFromJson(data) {
    if (data == null) return null;
    if (typeof data === 'string') return data.trim() || null;
    if (Array.isArray(data)) {
        const parts = data.map(readableFromJson).filter(Boolean);
        return parts.length ? parts.join('\n\n') : null;
    }
    if (typeof data !== 'object') return null;

    // Direct human-readable fields, in priority order.
    const direct = data.summary ?? data.content ?? data.body ?? data.text ?? data.description;
    if (typeof direct === 'string' && direct.trim()) return direct.trim();

    // Nested overview object (full note summary shape).
    if (data.overview) {
        const o = readableFromJson(data.overview);
        if (o) return o;
    }

    // Timeline segments (note summary shape).
    if (Array.isArray(data.segments)) {
        const segs = data.segments
            .map((s) => {
                if (!s) return null;
                const head = s.date_range ? `## ${s.date_range}\n` : '';
                const body = (s.summary || '').trim();
                return body ? head + body : null;
            })
            .filter(Boolean);
        if (segs.length) return segs.join('\n\n');
    }

    return null;
}

/**
 * If `text` looks like a raw JSON blob (optionally wrapped in code fences), try
 * to extract a human-readable string from it. Returns the original text
 * unchanged when it is not JSON.
 * @param {string} text
 * @returns {string}
 */
function sanitizeRawJson(text) {
    const candidate = stripJsonFences(text);
    if (!(candidate.startsWith('{') || candidate.startsWith('['))) return text;
    try {
        const data = JSON.parse(candidate);
        if (typeof data !== 'object' || data === null) return text;
        const readable = readableFromJson(data);
        return readable || '(Summary not available)';
    } catch {
        return text;
    }
}

/**
 * Apply inline Markdown rules (bold) to an already-escaped line.
 * Called after escapeHtml so we can safely emit <strong> tags.
 * @param {string} escaped
 * @returns {string}
 */
function inlineMarkdown(escaped) {
    // Bold: **text** or __text__
    return escaped
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/__(.*?)__/g, '<strong>$1</strong>');
}

/**
 * Render a Markdown string to an HTML string.
 * @param {string|null|undefined} text
 * @returns {string} Safe HTML ready for v-html / innerHTML
 */
export function renderMarkdown(text) {
    if (!text) return '';

    // Guard: extract human-readable content from raw JSON blobs
    const cleaned = sanitizeRawJson(text);

    const lines = cleaned.split('\n');
    const html = [];
    let inUl = false;
    let inOl = false;

    const closeList = () => {
        if (inUl) { html.push('</ul>'); inUl = false; }
        if (inOl) { html.push('</ol>'); inOl = false; }
    };

    for (let i = 0; i < lines.length; i++) {
        const raw = lines[i];
        const line = raw.trimEnd();

        // Blank line → close any open list, mark paragraph break
        if (line.trim() === '') {
            closeList();
            // Avoid stacking multiple <br> for consecutive blank lines
            if (html.length > 0 && html[html.length - 1] !== '<br/>') {
                html.push('<br/>');
            }
            continue;
        }

        // Horizontal rule
        if (/^-{3,}$/.test(line.trim()) || /^\*{3,}$/.test(line.trim())) {
            closeList();
            html.push('<hr class="my-2 border-slate-200 dark:border-slate-600"/>');
            continue;
        }

        // ATX headings: ## ... and # ...
        const headingMatch = line.match(/^(#{1,3})\s+(.+)$/);
        if (headingMatch) {
            closeList();
            const level = headingMatch[1].length;
            const content = inlineMarkdown(escapeHtml(headingMatch[2]));
            const cls = level === 1
                ? 'text-base font-bold text-slate-800 dark:text-slate-200 mt-3 mb-1'
                : level === 2
                    ? 'text-sm font-semibold text-slate-700 dark:text-slate-300 mt-2 mb-0.5'
                    : 'text-sm font-medium text-slate-600 dark:text-slate-400 mt-1';
            html.push(`<p class="${cls}">${content}</p>`);
            continue;
        }

        // Unordered list item: "- " or "* "
        const ulMatch = line.match(/^[\s]*[-*]\s+(.+)$/);
        if (ulMatch) {
            if (!inUl) { closeList(); html.push('<ul class="list-disc list-inside space-y-0.5 my-1">'); inUl = true; }
            html.push(`<li class="text-slate-600 dark:text-slate-300">${inlineMarkdown(escapeHtml(ulMatch[1]))}</li>`);
            continue;
        }

        // Ordered list item: "1. " etc.
        const olMatch = line.match(/^[\s]*\d+\.\s+(.+)$/);
        if (olMatch) {
            if (!inOl) { closeList(); html.push('<ol class="list-decimal list-inside space-y-0.5 my-1">'); inOl = true; }
            html.push(`<li class="text-slate-600 dark:text-slate-300">${inlineMarkdown(escapeHtml(olMatch[1]))}</li>`);
            continue;
        }

        // Plain paragraph line
        closeList();
        html.push(`<p class="text-slate-600 dark:text-slate-300 leading-relaxed">${inlineMarkdown(escapeHtml(line))}</p>`);
    }

    closeList();
    return html.join('\n');
}
