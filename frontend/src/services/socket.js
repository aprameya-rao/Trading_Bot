// frontend/src/services/socket.js

// This function now simply creates and returns a configured socket instance.
// The management of this instance will be handled by the React component.
export const createSocketConnection = (onOpen, onMessage, onClose, onError) => {
    const socket = new WebSocket(`${import.meta.env.VITE_API_WS_URL}/ws`);

    socket.onopen = (event) => {
        console.log("WebSocket connected");
        onOpen(event);
    };

    socket.onmessage = (event) => {
        onMessage(event);
    };

    socket.onclose = (event) => {
        console.log("WebSocket disconnected");
        onClose(event);
    };

    socket.onerror = (error) => {
        console.error("WebSocket error:", error);
        onError(error);
    };

    return socket;
};