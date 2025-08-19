import React from 'react';
import { Paper, Typography, Box } from '@mui/material';

export default function StatusPanel({ status, socketStatus }) {
    const isConnected = status.connection === 'CONNECTED';
    const modeColor = status.mode.includes("PAPER") ? 'success.main' : 'error.main';

    return (
        <Paper elevation={3} sx={{ p: 1.5 }}>
            <Typography variant="body2" sx={{ mb: 1 }}>Live Status</Typography>
            <Box sx={{ pl: 1 }}>

                <Typography variant="body1" sx={{ color: socketStatus === 'CONNECTED' ? 'success.main' : 'error.main', fontWeight: 'bold' }}>
                    Status: {status.connection}
                </Typography>

                <Typography variant="h6" sx={{ my: 0.5, fontWeight: 'bold', color: modeColor }}>
                    MODE: {status.mode}
                </Typography>

                {/* --- FIXED: Index name is now dynamic --- */}
                <Typography variant="h5" color="primary" sx={{ fontWeight: 'bold' }}>
                    {status.indexName || 'INDEX'}: {status.indexPrice?.toFixed(2) ?? '0.00'}
                </Typography>

                <Typography variant="body1" sx={{ fontWeight: 'bold', mt: 0.5 }}>
                    Trend: <Typography component="span" sx={{ color: status.trend === 'BULLISH' ? 'success.main' : status.trend === 'BEARISH' ? 'error.main' : 'text.primary', fontWeight: 'bold' }}>{status.trend}</Typography>
                </Typography>
            </Box>
        </Paper>
    );
}