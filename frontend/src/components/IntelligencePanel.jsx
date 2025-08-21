// frontend/src/components/IntelligencePanel.jsx
import React, { useState } from 'react';
import { Paper, Typography, Button, CircularProgress } from '@mui/material';
import { useSnackbar } from 'notistack';

export default function IntelligencePanel() {
    const [loading, setLoading] = useState(false);
    const [resetLoading, setResetLoading] = useState(false);
    const { enqueueSnackbar } = useSnackbar();

    const handleOptimize = async () => {
        setLoading(true);
        enqueueSnackbar('Starting optimization... This may take a moment.', { variant: 'info' });
        try {
            const response = await fetch('http://localhost:8000/api/optimize', {
                method: 'POST',
            });
            const data = await response.json();

            if (!response.ok || data.status === 'error') {
                throw new Error(data.report.join('\n') || 'Optimization failed.');
            }

            // --- MODIFIED: Removed "persist: true" to allow the snackbar to auto-hide ---
            enqueueSnackbar(data.report.join(' | '), { 
                variant: 'success', 
                style: { whiteSpace: 'pre-line' },
                autoHideDuration: 8000 // Optional: give it 8 seconds before hiding
            });

        } catch (error) {
            enqueueSnackbar(error.message, { variant: 'error' });
        }
        setLoading(false);
    };

    const handleReset = async () => {
        if (window.confirm('This will reset your strategy parameters to market standard defaults. Are you sure?')) {
            setResetLoading(true);
            try {
                const response = await fetch('http://localhost:8000/api/reset_params', {
                    method: 'POST',
                });
                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.detail || 'Failed to reset parameters.');
                }
                enqueueSnackbar(data.message, { variant: 'success' });
            } catch (error) {
                enqueueSnackbar(error.message, { variant: 'error' });
            }
            setResetLoading(false);
        }
    };

    return (
        <Paper elevation={3} sx={{ p: 2 }}>
            <Typography variant="body2" sx={{ mb: 1 }}>Intelligence</Typography>
            <Button 
                fullWidth 
                variant="outlined" 
                sx={{ mb: 1 }} 
                onClick={handleOptimize}
                disabled={loading || resetLoading}
            >
                {loading ? <CircularProgress size={24} /> : 'Analyze & Optimize Now'}
            </Button>
            <Button
                fullWidth
                variant="outlined"
                color="warning"
                onClick={handleReset}
                disabled={loading || resetLoading}
            >
                {resetLoading ? <CircularProgress size={24} color="inherit" /> : 'Reset to Market Standards'}
            </Button>
        </Paper>
    );
}
