// frontend/src/services/socket.js

let socket = null;
let reconnectInterval = null;
let isIntentionalClose = false; // Add this flag

const connect = (onMessageCallback) => {
    // Prevent multiple connections
    if (socket && socket.readyState === WebSocket.OPEN) {
        console.log("WebSocket is already connected.");
        return;
    }

    isIntentionalClose = false; // Reset flag on new connection attempt
    socket = new WebSocket(`ws://localhost:8000/ws`);

    socket.onopen = () => {
        console.log("WebSocket connected");
        onMessageCallback({type: 'socket_status', payload: 'CONNECTED'});
        if (reconnectInterval) {
            clearInterval(reconnectInterval);
            reconnectInterval = null;
        }
    };

    socket.onmessage = (event) => {
        // This is the log we added for debugging
        console.log("--- RAW SOCKET MESSAGE RECEIVED IN socket.js ---", event.data); 
        
        try {
            const data = JSON.parse(event.data);
            onMessageCallback(data);
        } catch (error) {
            console.error("Failed to parse socket message:", event.data);
        }
    };

    socket.onclose = () => {
        console.log("WebSocket disconnected");
        onMessageCallback({type: 'socket_status', payload: 'DISCONNECTED'});

        // Only reconnect if the disconnection was NOT intentional
        if (!isIntentionalClose && !reconnectInterval) {
            reconnectInterval = setInterval(() => {
                console.log("Attempting to reconnect WebSocket...");
                // Use the main connect function to handle the logic
                connectWebSocket(onMessageCallback);
            }, 5000);
        }
    };

    socket.onerror = (error) => {
        console.error("WebSocket error:", error);
        socket.close(); // This will trigger onclose
    };
};

export const connectWebSocket = (onMessageCallback) => {
    if (!socket || socket.readyState === WebSocket.CLOSED) {
        connect(onMessageCallback);
    }
};

export const disconnectWebSocket = () => {
    if (reconnectInterval) {
        clearInterval(reconnectInterval);
        reconnectInterval = null;
    }
    if (socket) {
        isIntentionalClose = true; // Set the flag before closing
        socket.close();
        socket = null; // Clean up the socket object reference
    }
};

export const sendWebSocketMessage = (message) => {
    if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify(message));
    } else {
        console.error("Cannot send message, WebSocket is not open.");
    }
};