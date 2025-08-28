// frontend/src/components/ParametersPanel.jsx
import React, { useState, useEffect, useCallback } from 'react';
import { Paper, Typography, Grid, TextField, Select, MenuItem, Button, FormControl, InputLabel, CircularProgress, Box, Checkbox, FormControlLabel } from '@mui/material';
import { useSnackbar } from 'notistack';

// --- CHANGE: Component now accepts `isBotRunning` as a prop ---
export default function ParametersPanel({ isMock = false, isBotRunning }) {
    const { enqueueSnackbar } = useSnackbar();
    
    const [auth, setAuth] = useState({ 
        status: 'loading', 
        login_url: '', 
        user: '' 
    });
    
    // --- CHANGE: `useState` initializer now reads from localStorage ---
    const [params, setParams] = useState(() => {
        const savedParams = localStorage.getItem('tradingParams');
        return savedParams ? JSON.parse(savedParams) : {
            selectedIndex: 'SENSEX', 
            trading_mode: 'Paper Trading', 
            aggressiveness: 'Moderate', 
            start_capital: 50000,
            risk_per_trade_percent: 2.0,
            trailing_sl_points: 5, 
            trailing_sl_percent: 2.5, 
            daily_sl: -20000, 
            daily_pt: 40000, 
            partial_profit_pct: 3,
            partial_exit_pct: 30,
            auto_scan_uoa: false
        };
    });
    
    const [loading, setLoading] = useState(false);
    // --- CHANGE: Local `botRunning` state has been removed ---
    const [reqToken, setReqToken] = useState('');

    // --- CHANGE: New useEffect hook to save params to localStorage on any change ---
    useEffect(() => {
        localStorage.setItem('tradingParams', JSON.stringify(params));
    }, [params]);

    const fetchStatus = useCallback(async () => {
        try {
            const res = await fetch('http://localhost:8000/api/status');
            const data = await res.json();
            
            if (data.status === 'unauthenticated' && !data.login_url) {
                console.error("Login URL not received from backend!", data);
                enqueueSnackbar('Error: Login URL not provided by the server.', { variant: 'error' });
            }
            
            setAuth(data);
        } catch (error) {
            console.error("Failed to fetch API status", error);
            setAuth({ status: 'error', login_url: '' });
            enqueueSnackbar('Failed to connect to the backend server.', { variant: 'error' });
        }
    }, [enqueueSnackbar]);

    useEffect(() => {
        if (isMock) { 
            setAuth({ status: 'authenticated' }); 
            return; 
        }
        fetchStatus();
    }, [isMock, fetchStatus]);

    const handleManualAuthenticate = async () => {
        if (!reqToken.trim()) {
            enqueueSnackbar('Please paste the request token from Kite.', { variant: 'warning' });
            return;
        }
        setLoading(true);
        try {
            const response = await fetch('http://localhost:8000/api/authenticate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ request_token: reqToken })
            });
            
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.detail || 'Authentication failed.');
            }
            
            enqueueSnackbar('Authentication successful!', { variant: 'success' });
            setAuth({ status: 'authenticated', user: data.user, login_url: '' });

        } catch (error) {
            console.error("Auth failed", error);
            enqueueSnackbar(error.message, { variant: 'error' });
            await fetchStatus();
        }
        setLoading(false);
    };

    const handleChange = (e) => {
        const { name, value, type, checked } = e.target;
        setParams(prev => ({ 
            ...prev, 
            [name]: type === 'checkbox' ? checked : value 
        }));
    };
    
    const handleStartStop = async () => {
        if (isMock) { return; }
        setLoading(true);
        // --- CHANGE: Use `isBotRunning` prop to determine the endpoint ---
        const endpoint = isBotRunning ? '/api/stop' : '/api/start';
        try {
            const res = await fetch(`http://localhost:8000${endpoint}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                // --- CHANGE: Use `isBotRunning` prop to determine the body ---
                body: isBotRunning ? '' : JSON.stringify({ params, selectedIndex: params.selectedIndex })
            });
            const data = await res.json();
            if (!res.ok) { throw new Error(data.detail || 'Action failed.'); }
            
            // --- CHANGE: Local state update is removed. The WebSocket message will handle it. ---
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
                <Typography variant="h6" sx={{mb: 2}}>Authentication Required</Typography>
                <Typography variant="body2" sx={{mb: 1}}>1. Click the button below to log in with Kite in a new tab.</Typography>
                <Button 
                    fullWidth 
                    variant="contained" 
                    href={auth.login_url} 
                    target="_blank"
                    disabled={!auth.login_url}
                >
                    Login with Kite
                </Button>

                <Typography variant="body2" sx={{mt: 3, mb: 1}}>2. After logging in, copy the `request_token` from the URL and paste it here.</Typography>
                <TextField 
                    fullWidth
                    margin="normal"
                    label="Paste Request Token here"
                    value={reqToken}
                    onChange={e => setReqToken(e.target.value)}
                    variant="outlined"
                    size="small"
                />

                <Button 
                    fullWidth 
                    variant="contained" 
                    color="primary" 
                    sx={{ mt: 1 }}
                    onClick={handleManualAuthenticate} 
                    disabled={loading || !reqToken}
                >
                    {loading ? <CircularProgress size={24} /> : 'Authenticate'}
                </Button>
            </Paper>
        );
    }
    
    const fields = [
        { label: 'Select Index', name: 'selectedIndex', type: 'select', options: ['SENSEX', 'NIFTY'] },
        { label: 'Trading Mode', name: 'trading_mode', type: 'select', options: ['Paper Trading', 'Live Trading'] },
        { label: 'Aggressiveness', name: 'aggressiveness', type: 'select', options: ['Conservative', 'Moderate'] },
        { label: 'Capital', name: 'start_capital', type: 'number' },
        { label: 'Risk Per Trade (%)', name: 'risk_per_trade_percent', type: 'number'},
        { label: 'SL (Points)', name: 'trailing_sl_points', type: 'number' },
        { label: 'SL (%)', name: 'trailing_sl_percent', type: 'number' },
        { label: 'Daily SL (₹)', name: 'daily_sl', type: 'number' },
        { label: 'Daily PT (₹)', name: 'daily_pt', type: 'number' },
        { label: 'Partial Profit %', name: 'partial_profit_pct', type: 'number'},
        { label: 'Partial Exit %', name: 'partial_exit_pct', type: 'number'},
    ];

    return (
        <Paper elevation={3} sx={{ p: 2 }}>
            <Typography variant="body2" sx={{ mb: 2 }}>Parameters (User: {auth.user})</Typography>
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
                                    // --- CHANGE: Use isBotRunning prop ---
                                    disabled={isBotRunning}
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
                                // --- CHANGE: Use isBotRunning prop ---
                                disabled={isBotRunning}
                            />
                        )}
                    </Grid>
                ))}
                <Grid item xs={12}>
                    <FormControlLabel 
                        control={<Checkbox name="auto_scan_uoa" checked={params.auto_scan_uoa} onChange={handleChange} disabled={isBotRunning} />} 
                        label="Enable Auto-Scan for UOA" 
                    />
                </Grid>
            </Grid>
            {/* The "Apply Changes" button has been removed as changes are now saved automatically */}
            <Button
                fullWidth
                sx={{ mt: 2 }}
                variant="contained"
                // --- CHANGE: Use isBotRunning prop ---
                color={isBotRunning ? "error" : "success"}
                onClick={handleStartStop}
                disabled={loading}
            >
                {/* --- CHANGE: Use isBotRunning prop --- */}
                {loading ? <CircularProgress size={24} /> : (isBotRunning ? 'Stop Trading Bot' : 'Start Trading Bot')}
            </Button>
        </Paper>
    );
}
