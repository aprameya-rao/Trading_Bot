import React, { useState } from 'react';
import { Paper, Typography, Button, CircularProgress } from '@mui/material';
import { useSnackbar } from 'notistack';
import { runOptimizer, resetParams } from '../services/api'; // --- CHANGED: Import from api.js

export default function IntelligencePanel() {
    const [loading, setLoading] = useState(false);
    const [resetLoading, setResetLoading] = useState(false);
    const { enqueueSnackbar } = useSnackbar();

    const handleOptimize = async () => {
        setLoading(true);
        enqueueSnackbar('Starting optimization... This may take a moment.', { variant: 'info' });
        try {
            // --- CHANGED: Use the service function ---
            const data = await runOptimizer();
            enqueueSnackbar(data.report.join(' | '), { 
                variant: 'success', 
                style: { whiteSpace: 'pre-line' },
                autoHideDuration: 8000
            });
        } catch (error) {
            enqueueSnackbar(error.message, { variant: 'error', style: { whiteSpace: 'pre-line' } });
        }
        setLoading(false);
    };

    const handleReset = async () => {
        if (window.confirm('This will reset your strategy parameters to market standard defaults. Are you sure?')) {
            setResetLoading(true);
            try {
                // --- CHANGED: Use the service function ---
                const data = await resetParams();
                enqueueSnackbar(data.message, { variant: 'success' });
            } catch (error) {
                enqueueSnackbar(error.message, { variant: 'error' });
            }
            setResetLoading(false);
        }
    };

    // The JSX return block remains the same
    return (
        <Paper elevation={3} sx={{ p: 2 }}>
            <Typography variant="body2" sx={{ mb: 1 }}>Intelligence</Typography>
            <Button fullWidth variant="outlined" sx={{ mb: 1 }} onClick={handleOptimize} disabled={loading || resetLoading}>
                {loading ? <CircularProgress size={24} /> : 'Analyze & Optimize Now'}
            </Button>
            <Button fullWidth variant="outlined" color="warning" onClick={handleReset} disabled={loading || resetLoading}>
                {resetLoading ? <CircularProgress size={24} color="inherit" /> : 'Reset to Market Standards'}
            </Button>
        </Paper>
    );
}