/**
 * API Client for Supernote Backend
 */

let authToken = localStorage.getItem('supernote_token');

export function setToken(token) {
    authToken = token;
    localStorage.setItem('supernote_token', token);
}

export function getToken() {
    return authToken;
}

export function logout() {
    authToken = null;
    localStorage.removeItem('supernote_token');
    window.location.reload();
}

/**
 * Secure Login Flow
 */
export async function login(email, password) {
    // 1. Wakeup / Get Token (Using query/token endpoint as a pre-check/wakeup)
    // This step in the CLI client ensures a clean session/CSRF token if needed,
    // although for the Web API we primarily rely on the random code flow.
    await fetch('/api/user/query/token', { method: 'POST', body: '{}' });

    // 2. Get Random Code (Challenge)
    const randomCodeResp = await fetch('/api/official/user/query/random/code', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account: email })
    });

    if (!randomCodeResp.ok) throw new Error("Failed to get login challenge");
    const { randomCode, timestamp } = await randomCodeResp.json();

    // 3. Hash Password
    // Schema: SHA256(MD5(password) + randomCode)

    // Step 3a: MD5(password)
    // Using SparkMD5 global from CDN
    const md5Password = SparkMD5.hash(password);

    // Step 3b: SHA256(md5Password + randomCode)
    const contentToHash = md5Password + randomCode;
    const sha256Hash = await sha256(contentToHash);

    // 4. Authenticate
    const loginResp = await fetch('/api/official/user/account/login/new', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            account: email,
            password: sha256Hash,
            timestamp: timestamp,
            loginMethod: "2", // Email
            equipment: 1 // WEB
        })
    });

    if (!loginResp.ok) {
        if (loginResp.status === 401) throw new Error("Invalid credentials");
        throw new Error("Login failed");
    }

    const loginData = await loginResp.json();
    setToken(loginData.token);
    return loginData;
}

// Helper: SHA-256.
// Prefer the native Web Crypto API, but it is only available in "secure
// contexts" (HTTPS or localhost/127.0.0.1). When the UI is served over plain
// HTTP to a LAN IP, `crypto.subtle` is undefined, so fall back to a pure-JS
// implementation instead of crashing.
async function sha256(message) {
    if (typeof crypto !== 'undefined' && crypto.subtle && crypto.subtle.digest) {
        const msgBuffer = new TextEncoder().encode(message);
        const hashBuffer = await crypto.subtle.digest('SHA-256', msgBuffer);
        const hashArray = Array.from(new Uint8Array(hashBuffer));
        return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
    }
    return sha256Fallback(message);
}

// Pure-JS SHA-256 (FIPS 180-4) used only when Web Crypto is unavailable.
// Operates on the UTF-8 bytes of the input string.
function sha256Fallback(message) {
    const rotr = (x, n) => (x >>> n) | (x << (32 - n));

    const K = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
        0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
        0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
        0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
        0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
        0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
        0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
    ];

    let h0 = 0x6a09e667, h1 = 0xbb67ae85, h2 = 0x3c6ef372, h3 = 0xa54ff53a;
    let h4 = 0x510e527f, h5 = 0x9b05688c, h6 = 0x1f83d9ab, h7 = 0x5be0cd19;

    const bytes = Array.from(new TextEncoder().encode(message));
    const bitLen = bytes.length * 8;

    bytes.push(0x80);
    while (bytes.length % 64 !== 56) bytes.push(0x00);

    // 64-bit big-endian length (high 32 bits are 0 for realistic inputs).
    for (let i = 7; i >= 0; i--) bytes.push((bitLen / Math.pow(2, 8 * i)) & 0xff);

    const w = new Uint32Array(64);
    for (let i = 0; i < bytes.length; i += 64) {
        for (let t = 0; t < 16; t++) {
            w[t] = (bytes[i + t * 4] << 24) | (bytes[i + t * 4 + 1] << 16) |
                   (bytes[i + t * 4 + 2] << 8) | (bytes[i + t * 4 + 3]);
        }
        for (let t = 16; t < 64; t++) {
            const s0 = rotr(w[t - 15], 7) ^ rotr(w[t - 15], 18) ^ (w[t - 15] >>> 3);
            const s1 = rotr(w[t - 2], 17) ^ rotr(w[t - 2], 19) ^ (w[t - 2] >>> 10);
            w[t] = (w[t - 16] + s0 + w[t - 7] + s1) | 0;
        }

        let a = h0, b = h1, c = h2, d = h3, e = h4, f = h5, g = h6, h = h7;

        for (let t = 0; t < 64; t++) {
            const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
            const ch = (e & f) ^ (~e & g);
            const temp1 = (h + S1 + ch + K[t] + w[t]) | 0;
            const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
            const maj = (a & b) ^ (a & c) ^ (b & c);
            const temp2 = (S0 + maj) | 0;

            h = g; g = f; f = e; e = (d + temp1) | 0;
            d = c; c = b; b = a; a = (temp1 + temp2) | 0;
        }

        h0 = (h0 + a) | 0; h1 = (h1 + b) | 0; h2 = (h2 + c) | 0; h3 = (h3 + d) | 0;
        h4 = (h4 + e) | 0; h5 = (h5 + f) | 0; h6 = (h6 + g) | 0; h7 = (h7 + h) | 0;
    }

    const toHex = (x) => (x >>> 0).toString(16).padStart(8, '0');
    return toHex(h0) + toHex(h1) + toHex(h2) + toHex(h3) +
           toHex(h4) + toHex(h5) + toHex(h6) + toHex(h7);
}

/**
 * Fetch files for a given directory.
 */
export async function fetchFiles(directoryId = "0", pageNo = 1, pageSize = 50) {
    const headers = {
        'Content-Type': 'application/json'
    };
    if (authToken) {
        headers['x-access-token'] = authToken;
    }

    const response = await fetch('/api/file/list/query', {
        method: 'POST',
        headers,
        body: JSON.stringify({
            directoryId: directoryId, // Pass as string/raw to preserve precision
            pageNo,
            pageSize,
            order: "filename",
            sequence: "asc"
        })
    });

    if (!response.ok) {
        if (response.status === 401) {
            // If the token is invalid, clear it
            if (authToken) {
                logout();
                throw new Error("Unauthorized");
            }
            throw new Error("Unauthorized");
        }
        throw new Error(`Failed to fetch files: ${response.statusText}`);
    }

    const data = await response.json();

    // Map backend VO to frontend interface
    return (data.userFileVOList || []).map(file => ({
        id: file.id,
        name: file.fileName,
        isDirectory: file.isFolder === "Y" || file.isFolder === true || file.isFolder === 1,
        size: file.size,
        updatedAt: file.updateTime,
        extension: file.isFolder === "Y" ? null : getExtension(file.fileName)
    }));
}

function getExtension(filename) {
    if (!filename) return null;
    const parts = filename.split('.');
    return parts.length > 1 ? parts.pop().toLowerCase() : null;
}

/**
 * Convert Note to PNG
 * @param {string} fileId
 * @returns {Promise<Array<{pageNo: number, url: string}>>}
 */
export async function convertNoteToPng(fileId) {
    // 1. Get Token
    const currentToken = getToken();
    if (!currentToken) throw new Error("Unauthorized");

    // 2. Call API
    const response = await fetch('/api/file/note/to/png', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'x-access-token': currentToken
        },
        body: JSON.stringify({ id: fileId }) // Pass as string to preserve 64-bit precision
    });

    if (!response.ok) {
        if (response.status === 401) {
            logout();
            throw new Error("Unauthorized");
        }
        throw new Error(`Conversion failed: ${response.statusText}`);
    }

    const data = await response.json();
    return data.pngPageVOList || [];
}

/**
 * Fetch summaries for a file
 * @param {string} fileId
 * @returns {Promise<Array<Object>>}
 */
export async function fetchSummaries(fileId) {
    const currentToken = getToken();
    if (!currentToken) throw new Error("Unauthorized");

    const response = await fetch('/api/extended/file/summary/list', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'x-access-token': currentToken
        },
        // Extension endpoint expects { fileId: ... }
        body: JSON.stringify({ fileId: fileId })
    });

    if (!response.ok) {
        if (response.status === 401) {
            logout();
            throw new Error("Unauthorized");
        }
        throw new Error(`Summary fetch failed: ${response.statusText}`);
    }

    const data = await response.json();
    return data.summaryDOList || [];
}

/**
 * Fetch system tasks (Extended API).
 * @returns {Promise<Object>} The system task list response.
 */
export async function fetchSystemTasks() {
    const currentToken = getToken();
    if (!currentToken) throw new Error("Unauthorized");

    const response = await fetch('/api/extended/system/tasks', {
        method: 'GET',
        headers: {
            'Content-Type': 'application/json',
            'x-access-token': currentToken
        }
    });

    if (response.status === 401) {
        logout();
        throw new Error("Unauthorized");
    }

    if (!response.ok) {
        throw new Error(`Failed to fetch system tasks: ${response.statusText}`);
    }

    return await response.json();
}

/**
 * Fetch storage capacity/quota.
 * @returns {Promise<{usedCapacity: number, totalCapacity: number}>}
 */
export async function fetchCapacity() {
    const currentToken = getToken();
    if (!currentToken) throw new Error("Unauthorized");

    const response = await fetch('/api/file/capacity/query', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'x-access-token': currentToken
        },
        body: JSON.stringify({})
    });

    if (response.status === 401) {
        logout();
        throw new Error("Unauthorized");
    }

    if (!response.ok) {
        throw new Error(`Failed to fetch capacity: ${response.statusText}`);
    }

    return await response.json();
}

/**
 * Create a new folder.
 */
export async function createFolder(directoryId, folderName) {
    const currentToken = getToken();
    if (!currentToken) throw new Error("Unauthorized");

    const response = await fetch('/api/file/folder/add', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'x-access-token': currentToken
        },
        body: JSON.stringify({
            directoryId: directoryId,
            fileName: folderName
        })
    });

    if (!response.ok) {
        throw new Error(`Failed to create folder: ${response.statusText}`);
    }

    return await response.json();
}

/**
 * Delete items (files or folders).
 */
export async function deleteItems(directoryId, idList) {
    const currentToken = getToken();
    if (!currentToken) throw new Error("Unauthorized");

    const response = await fetch('/api/file/delete', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'x-access-token': currentToken
        },
        body: JSON.stringify({
            directoryId: directoryId,
            idList: idList
        })
    });

    if (!response.ok) {
        throw new Error(`Failed to delete items: ${response.statusText}`);
    }

    return await response.json();
}

/**
 * Move items to a new directory.
 */
export async function moveItems(idList, targetDirectoryId) {
    const currentToken = getToken();
    if (!currentToken) throw new Error("Unauthorized");

    const response = await fetch('/api/file/move', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'x-access-token': currentToken
        },
        body: JSON.stringify({
            idList: idList,
            directoryId: "0", // Not strictly required for move but good for DTO compliance if needed
            goDirectoryId: targetDirectoryId
        })
    });

    if (!response.ok) {
        throw new Error(`Failed to move items: ${response.statusText}`);
    }

    return await response.json();
}

/**
 * Rename an item.
 */
export async function renameItem(id, newName) {
    const currentToken = getToken();
    if (!currentToken) throw new Error("Unauthorized");

    const response = await fetch('/api/file/rename', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'x-access-token': currentToken
        },
        body: JSON.stringify({
            id: id,
            newName: newName
        })
    });

    if (!response.ok) {
        throw new Error(`Failed to rename item: ${response.statusText}`);
    }

    return await response.json();
}

/**
 * File Upload: Step 1 - Apply
 */
async function uploadApply(directoryId, fileName, size, md5) {
    const currentToken = getToken();
    if (!currentToken) throw new Error("Unauthorized");

    const response = await fetch('/api/file/upload/apply', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'x-access-token': currentToken
        },
        body: JSON.stringify({
            directoryId: directoryId,
            fileName: fileName,
            size: size,
            md5: md5
        })
    });

    if (!response.ok) {
        throw new Error(`Upload apply failed: ${response.statusText}`);
    }

    return await response.json();
}

/**
 * File Upload: Step 2 - Finish
 */
async function uploadFinish(directoryId, fileName, size, md5, innerName) {
    const currentToken = getToken();
    if (!currentToken) throw new Error("Unauthorized");

    const response = await fetch('/api/file/upload/finish', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'x-access-token': currentToken
        },
        body: JSON.stringify({
            directoryId: directoryId,
            fileName: fileName,
            fileSize: size,
            md5: md5,
            innerName: innerName,
            type: "2" // CLOUD
        })
    });

    if (!response.ok) {
        throw new Error(`Upload finish failed: ${response.statusText}`);
    }

    return await response.json();
}

/**
 * Upload a file (orchestrates apply, put, and finish).
 */
export async function uploadFile(directoryId, file, onProgress) {
    // 1. Calculate MD5 (optional but good for finish)
    const md5 = await calculateFileMd5(file);

    // 2. Apply
    const applyData = await uploadApply(directoryId, file.name, file.size, md5);
    const { fullUploadUrl, innerName } = applyData;

    // The upload endpoint is always the same origin as this app. The server
    // builds `fullUploadUrl` from the request's scheme/host, which can be an
    // http:// URL when sitting behind a TLS-terminating proxy (e.g.
    // `tailscale serve`). Posting to an http:// URL from an https:// page would
    // be blocked as mixed content, so reduce it to a same-origin relative URL
    // (path + signed query) and let the browser resolve it against the page.
    let uploadUrl = fullUploadUrl;
    try {
        const parsed = new URL(fullUploadUrl);
        uploadUrl = parsed.pathname + parsed.search;
    } catch (e) {
        // Already relative (or unparseable); use as-is.
    }

    // 3. POST/PUT file to blob storage as multipart
    // We use FormData to ensure the server receives a multipart request.
    const formData = new FormData();
    formData.append('file', file);

    const uploadResp = await fetch(uploadUrl, {
        method: 'POST', // Both POST and PUT are supported by our oss.py handle_oss_upload
        body: formData,
        // Note: Do NOT set Content-Type header; fetch will set it with the correct boundary
    });

    if (!uploadResp.ok) {
        throw new Error(`File binary upload failed: ${uploadResp.statusText}`);
    }

    // 4. Finish
    return await uploadFinish(directoryId, file.name, file.size, md5, innerName);
}

/**
 * Helper to calculate file MD5.
 */
function calculateFileMd5(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = (e) => {
            const hash = SparkMD5.ArrayBuffer.hash(e.target.result);
            resolve(hash);
        };
        reader.onerror = reject;
        reader.readAsArrayBuffer(file);
    });
}
/**
 * Fetch processing status for a list of files.
 * @param {Array<number>} fileIds
 * @returns {Promise<{success: boolean, statusMap: Object}>}
 */
export async function fetchProcessingStatus(fileIds) {
    const currentToken = getToken();
    if (!currentToken) throw new Error("Unauthorized");

    const response = await fetch('/api/extended/file/processing/status', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'x-access-token': currentToken
        },
        body: JSON.stringify({ fileIds: fileIds })
    });

    if (response.status === 401) {
        logout();
        throw new Error("Unauthorized");
    }

    if (!response.ok) {
        throw new Error(`Failed to fetch processing status: ${response.statusText}`);
    }

    const data = await response.json();
    return {
        success: true,
        statusMap: data.statusMap
    };
}

/**
 * Fetch aggregate sync/indexing progress across all processing tasks.
 * @returns {Promise<Object>} The system progress VO.
 */
export async function fetchProgress() {
    const currentToken = getToken();
    if (!currentToken) throw new Error("Unauthorized");

    const response = await fetch('/api/extended/system/progress', {
        method: 'GET',
        headers: {
            'Content-Type': 'application/json',
            'x-access-token': currentToken
        }
    });

    if (response.status === 401) {
        logout();
        throw new Error("Unauthorized");
    }

    if (!response.ok) {
        throw new Error(`Failed to fetch progress: ${response.statusText}`);
    }

    return await response.json();
}

/**
 * Semantic search across notebook content.
 * @param {string} query
 * @param {Object} [opts] Optional filters: { topN, nameFilter, dateAfter, dateBefore }
 * @returns {Promise<Array<Object>>} List of search result VOs.
 */
export async function search(query, opts = {}) {
    const currentToken = getToken();
    if (!currentToken) throw new Error("Unauthorized");

    const response = await fetch('/api/extended/search', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'x-access-token': currentToken
        },
        body: JSON.stringify({
            query,
            topN: opts.topN ?? 15,
            nameFilter: opts.nameFilter ?? null,
            dateAfter: opts.dateAfter ?? null,
            dateBefore: opts.dateBefore ?? null
        })
    });

    if (response.status === 401) {
        logout();
        throw new Error("Unauthorized");
    }

    if (!response.ok) {
        throw new Error(`Search failed: ${response.statusText}`);
    }

    const data = await response.json();
    return data.results || [];
}

/**
 * Fetch recycle bin contents.
 * @returns {Promise<Object>} RecycleFileListVO with items and totalSize.
 */
export async function fetchRecycleList(pageNo = 1, pageSize = 50) {
    const currentToken = getToken();
    if (!currentToken) throw new Error("Unauthorized");

    const response = await fetch('/api/file/recycle/list/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'x-access-token': currentToken },
        body: JSON.stringify({ pageNo, pageSize })
    });
    if (response.status === 401) { logout(); throw new Error("Unauthorized"); }
    if (!response.ok) throw new Error(`Failed to fetch recycle bin: ${response.statusText}`);
    return await response.json();
}

/**
 * Restore items from the recycle bin.
 * @param {number[]} idList - Recycle entry IDs to restore.
 */
export async function revertRecycle(idList) {
    const currentToken = getToken();
    if (!currentToken) throw new Error("Unauthorized");

    const response = await fetch('/api/file/recycle/revert', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'x-access-token': currentToken },
        body: JSON.stringify({ idList })
    });
    if (response.status === 401) { logout(); throw new Error("Unauthorized"); }
    if (!response.ok) throw new Error(`Failed to restore items: ${response.statusText}`);
    return await response.json();
}

/**
 * Permanently delete items from the recycle bin.
 * @param {number[]} idList - Recycle entry IDs to permanently delete.
 */
export async function deleteRecycle(idList) {
    const currentToken = getToken();
    if (!currentToken) throw new Error("Unauthorized");

    const response = await fetch('/api/file/recycle/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'x-access-token': currentToken },
        body: JSON.stringify({ idList })
    });
    if (response.status === 401) { logout(); throw new Error("Unauthorized"); }
    if (!response.ok) throw new Error(`Failed to delete items: ${response.statusText}`);
    return await response.json();
}

/**
 * Empty the entire recycle bin.
 */
export async function clearRecycle() {
    const currentToken = getToken();
    if (!currentToken) throw new Error("Unauthorized");

    const response = await fetch('/api/file/recycle/clear', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'x-access-token': currentToken },
        body: JSON.stringify({})
    });
    if (response.status === 401) { logout(); throw new Error("Unauthorized"); }
    if (!response.ok) throw new Error(`Failed to clear recycle bin: ${response.statusText}`);
    return await response.json();
}

/**
 * Fetch aggregated dashboard/insights stats for the current user.
 * @returns {Promise<Object>} The dashboard stats VO.
 */
export async function fetchDashboard() {
    const currentToken = getToken();
    if (!currentToken) throw new Error("Unauthorized");

    const response = await fetch('/api/extended/dashboard', {
        method: 'GET',
        headers: {
            'Content-Type': 'application/json',
            'x-access-token': currentToken
        }
    });

    if (response.status === 401) {
        logout();
        throw new Error("Unauthorized");
    }

    if (!response.ok) {
        throw new Error(`Failed to fetch dashboard: ${response.statusText}`);
    }

    return await response.json();
}
