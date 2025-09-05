import React, { useState, useEffect, useCallback } from 'react';
import { Paper, Typography, Grid, TextField, Select, MenuItem, Button, FormControl, InputLabel, CircularProgress, Box, Checkbox, FormControlLabel } from '@mui/material';
import { useSnackbar } from 'notistack';
import { useStore } from '../store/store';
import { getStatus, authenticate, startBot, stopBot } from '../services/api';

export default function ParametersPanel({ isMock = false }) {
    const { enqueueSnackbar } = useSnackbar();
    
    const isSpectator = useStore(state => state.isSpectatorMode);
    const isBotRunning = useStore(state => state.botStatus.is_running);
    const params = useStore(state => state.params);
    const updateParam = useStore(state => state.updateParam);

    const [auth, setAuth] = useState({ status: 'loading', login_url: '', user: '' });
    const [reqToken, setReqToken] = useState('');
    
    const [isStartLoading, setIsStartLoading] = useState(false);
    const [isStopLoading, setIsStopLoading] = useState(false);

    const fetchStatus = useCallback(async () => {
        try {
            const data = await getStatus();
            setAuth(data);
        } catch (error) {
            setAuth({ status: 'error', login_url: '' });
            enqueueSnackbar('Failed to connect to the backend server.', { variant: 'error' });
        }
    }, [enqueueSnackbar]);

    useEffect(() => {
        if (isMock) { setAuth({ status: 'authenticated' }); return; }
        fetchStatus();
    }, [isMock, fetchStatus]);

    const handleManualAuthenticate = async () => {
        if (!reqToken.trim()) {
            enqueueSnackbar('Please paste the request token from Kite.', { variant: 'warning' });
            return;
        }
        setIsStartLoading(true);
        try {
            const data = await authenticate(reqToken);
            enqueueSnackbar('Authentication successful!', { variant: 'success' });
            setAuth({ status: 'authenticated', user: data.user, login_url: '' });
        } catch (error) {
            enqueueSnackbar(error.message, { variant: 'error' });
            await fetchStatus();
        }
        setIsStartLoading(false);
    };

    const handleChange = (e) => {
        const { name, value, type, checked } = e.target;
        updateParam(name, type === 'checkbox' ? checked : value);
    };
    
    const handleStart = async () => {
        setIsStartLoading(true);
        try {
            const data = await startBot(params, params.selectedIndex);
            enqueueSnackbar(data.message, { variant: 'success' });
        } catch (error) {
            enqueueSnackbar(error.message, { variant: 'error' });
        }
        setIsStartLoading(false);
    };

    const handleStop = async () => {
        setIsStopLoading(true);
            try {
                const data = await stopBot();
                enqueueSnackbar(data.message, { variant: 'warning' });
                useStore.getState().resetRealtimeData();
            } catch (error) {
                enqueueSnackbar(error.message, { variant: 'error' });
            }
            setIsStopLoading(false);
    };

    if (auth.status === 'loading') {
        return <Paper sx={{ p: 2, textAlign: 'center' }}><CircularProgress /></Paper>;
    }
    
    if (auth.status !== 'authenticated' && !isBotRunning) {
        return (
            <Paper elevation={3} sx={{ p: 2 }}>
                <Typography variant="h6" sx={{mb: 2}}>Authentication Required</Typography>
                <Button fullWidth variant="contained" href={auth.login_url} target="_blank" disabled={!auth.login_url}>Login with Kite</Button>
                <TextField fullWidth margin="normal" label="Paste Request Token here" value={reqToken} onChange={e => setReqToken(e.target.value)} variant="outlined" size="small"/>
                <Button fullWidth variant="contained" color="primary" sx={{ mt: 1 }} onClick={handleManualAuthenticate} disabled={isStartLoading || !reqToken}>
                    {isStartLoading ? <CircularProgress size={24} /> : 'Authenticate'}
                </Button>
            </Paper>
        );
    }
    
    const fields = [
        { label: 'Select Index', name: 'selectedIndex', type: 'select', options: ['SENSEX', 'NIFTY'] },
        { label: 'Trading Mode', name: 'trading_mode', type: 'select', options: ['Paper Trading', 'Live Trading'] },
        { label: 'Capital', name: 'start_capital', type: 'number' },
        { label: 'Risk Per Trade (%)', name: 'risk_per_trade_percent', type: 'number'},
        { label: 'SL (Points)', name: 'trailing_sl_points', type: 'number' },
        { label: 'SL (%)', name: 'trailing_sl_percent', type: 'number' },
        { label: 'Daily SL (₹)', name: 'daily_sl', type: 'number' },
        { label: 'Daily PT (₹)', name: 'daily_pt', type: 'number' },
        { label: 'Partial Profit %', name: 'partial_profit_pct', type: 'number'},
        { label: 'Partial Exit %', name: 'partial_exit_pct', type: 'number'},
        // REMOVED: Recovery and Max Qty are no longer used by the backend logic
        // { label: 'Re-entry Thresh (%)', name: 'recovery_threshold_pct', type: 'number' },
        // { label: 'Max Qty / Order', name: 'max_lots_per_order', type: 'number' },
        // REMOVED: Volatility parameters are no longer used by the backend logic
        // { label: 'Vol Circuit Breaker (%)', name: 'vol_circuit_breaker_pct', type: 'number' },
        // { label: 'Max Vol for Reversal (%)', name: 'max_vol_for_reversal_pct', type: 'number' },
        // { label: 'Min Vol for Trend (%)', name: 'min_vol_for_trend_pct', type: 'number' },
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
                                <Select name={field.name} value={params[field.name] || ''} label={field.label} onChange={handleChange} disabled={isBotRunning || isSpectator}>
                                    {field.options.map(opt => <MenuItem key={opt} value={opt}>{opt}</MenuItem>)}
                                </Select>
                            </FormControl>
                        ) : (
                            <TextField name={field.name} label={field.label} type="number" value={params[field.name] || ''} onChange={handleChange} size="small" fullWidth disabled={isBotRunning || isSpectator}/>
                        )}
                    </Grid>
                ))}
                <Grid item xs={12}>
                    <FormControlLabel control={<Checkbox name="auto_scan_uoa" checked={!!params.auto_scan_uoa} onChange={handleChange} disabled={isBotRunning || isSpectator} />} label="Enable Auto-Scan for UOA" />
                </Grid>
            </Grid>
            <Box sx={{ mt: 2, display: 'flex', gap: 1 }}>
                <Button
                    fullWidth
                    variant="contained"
                    color="success"
                    onClick={handleStart}
                    disabled={isBotRunning || isStartLoading || isStopLoading || isSpectator}
                >
                    {isStartLoading ? <CircularProgress size={24} color="inherit" /> : 'Start Bot'}
                </Button>
                <Button
                    fullWidth
                    variant="contained"
                    color="error"
                    onClick={handleStop}
                    disabled={!isBotRunning || isStartLoading || isStopLoading || isSpectator}
                >
                    {isStopLoading ? <CircularProgress size={24} color="inherit" /> : 'Stop Bot'}
                </Button>
            </Box>
        </Paper>
    );
}
