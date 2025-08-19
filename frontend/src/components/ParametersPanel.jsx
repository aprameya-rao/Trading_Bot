import React, { useState, useEffect, useCallback } from 'react'; // <-- Import useCallback
import { Paper, Typography, Grid, TextField, Select, MenuItem, Button, FormControl, InputLabel, CircularProgress, Box, Checkbox, FormControlLabel } from '@mui/material';
import { useSnackbar } from 'notistack';

export default function ParametersPanel({ isMock = false }) {
    const { enqueueSnackbar } = useSnackbar();
    const [params, setParams] = useState({ 
        selectedIndex: 'SENSEX', 
        trading_mode: 'Paper Trading', 
        aggressiveness: 'Moderate', 
        start_capital: 50000, 
        trailing_sl_points: 2, 
        trailing_sl_percent: 1, 
        daily_sl: -2000, 
        daily_pt: 4000, 
        auto_scan_uoa: false 
    });
    const [auth, setAuth] = useState({ status: 'loading', url: '', user: '' });
    const [loading, setLoading] = useState(false);
    const [botRunning, setBotRunning] = useState(false);

    // --- UPDATED: Wrapped in useCallback for stability ---
    const fetchStatus = useCallback(async () => {
        try {
            const res = await fetch('http://localhost:8000/api/status');
            const data = await res.json();
            setAuth(data);
        } catch (error) {
            console.error("Failed to fetch API status", error);
            setAuth({ status: 'error' });
            enqueueSnackbar('Failed to connect to the backend server.', { variant: 'error' });
        }
    }, [enqueueSnackbar]); // Dependency on enqueueSnackbar

    // --- UPDATED: Wrapped in useCallback for stability ---
    const handleAuthenticate = useCallback(async (token) => {
        setLoading(true);
        try {
            const response = await fetch('http://localhost:8000/api/authenticate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ request_token: token })
            });
            
            const data = await response.json();
            if (!response.ok || data.status === 'error') {
                throw new Error(data.message || 'Authentication failed.');
            }
            
            enqueueSnackbar('Authentication successful!', { variant: 'success' });
            // This now correctly calls the stable fetchStatus function
            await fetchStatus();

        } catch (error) {
            console.error("Auth failed", error);
            enqueueSnackbar(error.message, { variant: 'error' });
        }
        setLoading(false);
    }, [enqueueSnackbar, fetchStatus]); // Dependency on its own used functions

    // --- UPDATED: useEffect with correct dependencies ---
    useEffect(() => {
        if (isMock) { 
            setAuth({ status: 'authenticated' }); 
            return; 
        }
        
        const autoAuthenticate = async () => {
            const urlParams = new URLSearchParams(window.location.search);
            const requestTokenFromUrl = urlParams.get('request_token');
            const statusFromUrl = urlParams.get('status');

            if(requestTokenFromUrl || statusFromUrl) {
                window.history.replaceState({}, document.title, window.location.pathname);
            }

            if (requestTokenFromUrl && statusFromUrl === 'success') {
                await handleAuthenticate(requestTokenFromUrl);
            } else if (statusFromUrl) {
                const errorMessage = `Kite login failed or was cancelled. (Status: ${statusFromUrl})`;
                enqueueSnackbar(errorMessage, { variant: 'error' });
                await fetchStatus();
            } else {
                await fetchStatus();
            }
        };
        
        autoAuthenticate();
    }, [isMock, handleAuthenticate, fetchStatus, enqueueSnackbar]); // <-- Correct dependency array

    const handleChange = (e) => {
        const { name, value, type, checked } = e.target;
        setParams(prev => ({ 
            ...prev, 
            [name]: type === 'checkbox' ? checked : value 
        }));
    };
    
    const handleStartStop = async () => {
        if (isMock) { setBotRunning(!botRunning); return; }
        setLoading(true);
        const endpoint = botRunning ? '/api/stop' : '/api/start';
        try {
            const res = await fetch(`http://localhost:8000${endpoint}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: botRunning ? '' : JSON.stringify({ params, selectedIndex: params.selectedIndex })
            });
            
            const data = await res.json();
            if (!res.ok) {
                 throw new Error(data.detail || 'Action failed.');
            }

            setBotRunning(!botRunning);
            enqueueSnackbar(data.message, { variant: 'info' });

        } catch (error) {
            console.error("Action failed", error);
            enqueueSnackbar(error.message, { variant: 'error' });
        }
        setLoading(false);
    };

    if (auth.status === 'loading') {
        return <Paper sx={{ p: 2, textAlign: 'center' }}><CircularProgress /></Paper>;
    }

    if (auth.status !== 'authenticated') {
        return (
            <Paper elevation={3} sx={{ p: 2 }}>
                <Typography sx={{mb: 2}}>Authentication Required</Typography>
                <Button fullWidth variant="contained" href={auth.login_url}>
                    Login with Kite
                </Button>
                <Box sx={{mt: 2, p: 1, border: '1px dashed grey', borderRadius: 1}}>
                    <Typography variant="caption">
                        After logging in with Kite, you will be redirected back here. The app will attempt to authenticate automatically.
                    </Typography>
                </Box>
            </Paper>
        );
    }
    
    const fields = [
        { label: 'Select Index', name: 'selectedIndex', type: 'select', options: ['SENSEX', 'NIFTY'] },
        { label: 'Trading Mode', name: 'trading_mode', type: 'select', options: ['Paper Trading', 'Live Trading'] },
        { label: 'Aggressiveness', name: 'aggressiveness', type: 'select', options: ['Conservative', 'Moderate'] },
        { label: 'Capital', name: 'start_capital', type: 'number' },
        { label: 'SL (Points)', name: 'trailing_sl_points', type: 'number' },
        { label: 'SL (%)', name: 'trailing_sl_percent', type: 'number' },
        { label: 'Daily SL (₹)', name: 'daily_sl', type: 'number' },
        { label: 'Daily PT (₹)', name: 'daily_pt', type: 'number' },
    ];

    return (
        <Paper elevation={3} sx={{ p: 2 }}>
            <Typography variant="body2" sx={{ mb: 2 }}>Parameters</Typography>
            <Grid container spacing={2}>
                {fields.map(field => (
                    <Grid item xs={12} key={field.name}>
                        {field.type === 'select' ? (
                            <FormControl fullWidth size="small">
                                <InputLabel>{field.label}</InputLabel>
                                <Select
                                    name={field.name}
                                    value={params[field.name]}
                                    label={field.label}
                                    onChange={handleChange}
                                    disabled={botRunning}
                                >
                                    {field.options.map(opt => <MenuItem key={opt} value={opt}>{opt}</MenuItem>)}
                                </Select>
                            </FormControl>
                        ) : (
                            <TextField
                                name={field.name}
                                label={field.label}
                                type="number"
                                value={params[field.name]}
                                onChange={handleChange}
                                size="small"
                                fullWidth
                                disabled={botRunning}
                            />
                        )}
                    </Grid>
                ))}
                <Grid item xs={12}>
                    <FormControlLabel 
                        control={<Checkbox name="auto_scan_uoa" checked={params.auto_scan_uoa} onChange={handleChange} disabled={botRunning} />} 
                        label="Enable Auto-Scan for UOA" 
                    />
                </Grid>
            </Grid>
            <Button fullWidth sx={{ mt: 2 }} variant="outlined" disabled={botRunning}>Apply Changes</Button>
            <Button
                fullWidth
                sx={{ mt: 1 }}
                variant="contained"
                color={botRunning ? "error" : "success"}
                onClick={handleStartStop}
                disabled={loading}
            >
                {loading ? <CircularProgress size={24} /> : (botRunning ? 'Stop Trading Bot' : 'Start Trading Bot')}
            </Button>
        </Paper>
    );
}