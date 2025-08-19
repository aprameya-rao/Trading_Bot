// frontend/src/components/IntelligencePanel.jsx
import React, { useState } from 'react';
import { Paper, Typography, Button, CircularProgress } from '@mui/material';
import { useSnackbar } from 'notistack';

export default function IntelligencePanel() {
    const [loading, setLoading] = useState(false);
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

            // Display the report in a persistent snackbar for readability
            enqueueSnackbar(data.report.join(' | '), { 
                variant: 'success', 
                persist: true,
                style: { whiteSpace: 'pre-line' }
            });

        } catch (error) {
            enqueueSnackbar(error.message, { variant: 'error' });
        }
        setLoading(false);
    };

    return (
        <Paper elevation={3} sx={{ p: 2 }}>
            <Typography variant="body2" sx={{ mb: 1 }}>Intelligence</Typography>
            <Button 
                fullWidth 
                variant="outlined" 
                sx={{ mb: 1 }} 
                onClick={handleOptimize}
                disabled={loading}
            >
                {loading ? <CircularProgress size={24} /> : 'Analyze & Optimize Now'}
            </Button>
        </Paper>
    );
}