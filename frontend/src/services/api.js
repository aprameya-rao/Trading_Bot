import { useSnackbar } from 'notistack';

const API_BASE_URL = 'http://localhost:8000/api';

/**
 * A helper function to handle fetch requests and responses.
 * @param {string} endpoint The API endpoint to call.
 * @param {object} options The options for the fetch call (method, headers, body).
 * @returns {Promise<any>} The JSON response from the API.
 * @throws {Error} If the network response is not ok.
 */
async function apiRequest(endpoint, options = {}) {
    try {
        const response = await fetch(`${API_BASE_URL}${endpoint}`, options);
        const data = await response.json();
        if (!response.ok) {
            // Use the detailed error message from the backend if available
            throw new Error(data.detail || 'An unknown API error occurred.');
        }
        return data;
    } catch (error) {
        console.error(`API request to ${endpoint} failed:`, error);
        // Re-throw the error so the calling component can handle it
        throw error;
    }
}

// --- Authentication ---
export const getStatus = () => apiRequest('/status');
export const authenticate = (request_token) => apiRequest('/authenticate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ request_token }),
});

// --- Bot Control ---
export const startBot = (params, selectedIndex) => apiRequest('/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ params, selectedIndex }),
});
export const stopBot = () => apiRequest('/stop', { method: 'POST' });
export const manualExit = () => apiRequest('/manual_exit', { method: 'POST' });

// --- Intelligence & Parameters ---
export const runOptimizer = () => apiRequest('/optimize', { method: 'POST' });
export const resetParams = () => apiRequest('/reset_params', { method: 'POST' });

// --- Data Fetching ---
export const getTradeHistory = () => apiRequest('/trade_history');
export const getTradeHistoryAll = () => apiRequest('/trade_history_all');
