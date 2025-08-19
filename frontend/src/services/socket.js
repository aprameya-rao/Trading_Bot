// frontend/src/services/socket.js
let socket = null;
let reconnectInterval = null;

const connect = (onMessageCallback) => {
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
        if (!reconnectInterval) {
            reconnectInterval = setInterval(() => {
                console.log("Attempting to reconnect WebSocket...");
                connect(onMessageCallback);
            }, 5000); // Attempt to reconnect every 5 seconds
        }
    };

    socket.onerror = (error) => {
        console.error("WebSocket error:", error);
        socket.close();
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
        socket.close();
    }
};

export const sendWebSocketMessage = (message) => {
    if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify(message));
    }
};