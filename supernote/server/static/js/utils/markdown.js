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
 * If `text` looks like a raw JSON blob, try to extract a human-readable string
 * from it (summary, overview.summary, content, body — in that order).
 * Returns the original text unchanged when it is not JSON.
 * @param {string} text
 * @returns {string}
 */
function sanitizeRawJson(text) {
    const trimmed = text.trim();
    if (!(trimmed.startsWith('{') || trimmed.startsWith('['))) return text;
    try {
        const data = JSON.parse(trimmed);
        if (typeof data !== 'object' || data === null) return text;
        // Prefer the most useful human-readable field
        const candidates = [
            data.summary,
            data.overview?.summary,
            data.content,
            data.body,
            data.text,
        ];
        for (const c of candidates) {
            if (typeof c === 'string' && c.trim()) return c.trim();
        }
        return '(Summary not available)';
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
            html.push('<hr class="my-2 border-slate-200"/>');
            continue;
        }

        // ATX headings: ## ... and # ...
        const headingMatch = line.match(/^(#{1,3})\s+(.+)$/);
        if (headingMatch) {
            closeList();
            const level = headingMatch[1].length;
            const content = inlineMarkdown(escapeHtml(headingMatch[2]));
            const cls = level === 1
                ? 'text-base font-bold text-slate-800 mt-3 mb-1'
                : level === 2
                    ? 'text-sm font-semibold text-slate-700 mt-2 mb-0.5'
                    : 'text-sm font-medium text-slate-600 mt-1';
            html.push(`<p class="${cls}">${content}</p>`);
            continue;
        }

        // Unordered list item: "- " or "* "
        const ulMatch = line.match(/^[\s]*[-*]\s+(.+)$/);
        if (ulMatch) {
            if (!inUl) { closeList(); html.push('<ul class="list-disc list-inside space-y-0.5 my-1">'); inUl = true; }
            html.push(`<li class="text-slate-600">${inlineMarkdown(escapeHtml(ulMatch[1]))}</li>`);
            continue;
        }

        // Ordered list item: "1. " etc.
        const olMatch = line.match(/^[\s]*\d+\.\s+(.+)$/);
        if (olMatch) {
            if (!inOl) { closeList(); html.push('<ol class="list-decimal list-inside space-y-0.5 my-1">'); inOl = true; }
            html.push(`<li class="text-slate-600">${inlineMarkdown(escapeHtml(olMatch[1]))}</li>`);
            continue;
        }

        // Plain paragraph line
        closeList();
        html.push(`<p class="text-slate-600 leading-relaxed">${inlineMarkdown(escapeHtml(line))}</p>`);
    }

    closeList();
    return html.join('\n');
}
