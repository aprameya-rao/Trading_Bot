// frontend/src/components/StatusPanel.jsx
import React from 'react';
import { Paper, Typography, Box } from '@mui/material';

export default function StatusPanel({ status, socketStatus }) {
    const isConnected = status.connection === 'CONNECTED';
    const modeColor = status.mode.includes("PAPER") ? 'success.main' : 'error.main';

    return (
        // CHANGE 1: Reduced overall padding from p: 2 to p: 1.5 to make the box smaller.
        <Paper elevation={3} sx={{ p: 1.5 }}>
            <Typography variant="body2" sx={{ mb: 1 }}>Live Status</Typography>
            <Box sx={{ pl: 1 }}>

                {/* CHANGE 2: Reduced text size for "Status" from h6 to body1. */}
                <Typography variant="body1" sx={{ color: socketStatus === 'CONNECTED' ? 'success.main' : 'error.main', fontWeight: 'bold' }}>
                    Status: {status.connection}
                </Typography>

                {/* CHANGE 3: Reduced text size for "MODE" from h5 to h6 and less vertical margin. */}
                <Typography variant="h6" sx={{ my: 0.5, fontWeight: 'bold', color: modeColor }}>
                    MODE: {status.mode}
                </Typography>

                {/* CHANGE 4: Reduced text size for "SENSEX" from h4 to h5. */}
                <Typography variant="h5" color="primary" sx={{ fontWeight: 'bold' }}>
                    SENSEX: {status.indexPrice?.toFixed(2) ?? '0.00'}
                </Typography>

                {/* CHANGE 5: Reduced text size for "Trend" from h6 to body1. */}
                <Typography variant="body1" sx={{ fontWeight: 'bold', mt: 0.5 }}>
                    Trend: <Typography component="span" sx={{ color: status.trend === 'BULLISH' ? 'success.main' : status.trend === 'BEARISH' ? 'error.main' : 'text.primary', fontWeight: 'bold' }}>{status.trend}</Typography>
                </Typography>
            </Box>
        </Paper>
    );
}