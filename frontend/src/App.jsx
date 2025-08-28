// frontend/src/App.jsx

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Howl } from 'howler';
import { Grid, ThemeProvider, createTheme, CssBaseline, Box } from '@mui/material';
import { useSnackbar } from 'notistack';
import StatusPanel from './components/StatusPanel';
import ParametersPanel from './components/ParametersPanel';
import IntelligencePanel from './components/IntelligencePanel';
import PerformancePanel from './components/PerformancePanel';
import CurrentTradePanel from './components/CurrentTradePanel';
import IndexChart from './components/IndexChart';
import OptionChain from './components/OptionChain';
import LogTabs from './components/LogTabs';
import { createSocketConnection } from './services/socket';

const MOCK_MODE = false;

const sounds = {
  entry: new Howl({ src: ['/sound/entry.mp3'], volume: 0.7 }),
  profit: new Howl({ src: ['/sound/profit.mp3'], volume: 0.7 }),
  loss: new Howl({ src: ['/sound/loss.mp3'], volume: 0.7 }),
  warning: new Howl({ src: ['/sound/warning.mp3'], volume: 1.0 }),
};

const lightTheme = createTheme({
    palette: {
        mode: 'light', primary: { main: '#1976d2' }, success: { main: '#2e7d32' }, error: { main: '#d32f2f' },
    },
});

function App() {
    const { enqueueSnackbar } = useSnackbar();
    const socketRef = useRef(null);
    const reconnectTimerRef = useRef(null); // Ref to hold the reconnection timer

    // All application state
    const [chartData, setChartData] = useState(null);
    const [botStatus, setBotStatus] = useState({ connection: 'DISCONNECTED', mode: 'NOT STARTED', indexPrice: 0, trend: '---', indexName: 'INDEX' });
    const [dailyPerformance, setDailyPerformance] = useState({ netPnl: 0, grossProfit: 0, grossLoss: 0, wins: 0, losses: 0 });
    const [currentTrade, setCurrentTrade] = useState(null);
    const [debugLogs, setDebugLogs] = useState([]);
    const [tradeHistory, setTradeHistory] = useState([]);
    const [optionChain, setOptionChain] = useState([]);
    const [uoaList, setUoaList] = useState([]);
    const [socketStatus, setSocketStatus] = useState('DISCONNECTED');
    
    // --- CHANGE: State for bot running status, controlled by backend ---
    const [isBotRunning, setIsBotRunning] = useState(false);

    const sendSocketMessage = useCallback((message) => {
        if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
            socketRef.current.send(JSON.stringify(message));
        } else {
            console.error("Cannot send message, WebSocket is not open.");
        }
    }, []);
    
    // --- CHANGE: Replaced original useEffect with one that handles reconnection ---
    useEffect(() => {
        const connect = () => {
            const handleMessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    // The main dispatcher for all incoming messages
                    switch (data.type) {
                        case 'status_update':
                            setBotStatus(data.payload);
                            // Update the running state from the backend's single source of truth
                            setIsBotRunning(data.payload.is_running);
                            break;
                        case 'daily_performance_update': setDailyPerformance(data.payload); break;
                        case 'trade_status_update': setCurrentTrade(data.payload); break;
                        case 'debug_log': setDebugLogs(prev => [data.payload, ...prev]); break;
                        case 'trade_log_update': setTradeHistory(data.payload); break;
                        case 'option_chain_update': setOptionChain(data.payload); break;
                        case 'uoa_list_update': setUoaList(data.payload); break;
                        case 'chart_data_update': setChartData(data.payload); break;
                        case 'play_sound':
                            if (sounds[data.payload]) {
                                sounds[data.payload].play();
                            }
                            break;
                    }
                } catch (error) {
                    console.error("Failed to parse socket message:", event.data, error);
                }
            };

            const handleClose = () => {
                setSocketStatus('DISCONNECTED');
                console.log("WebSocket closed. Attempting to reconnect in 5 seconds...");
                // Set a timer to reconnect
                reconnectTimerRef.current = setTimeout(connect, 5000);
            };

            // Clear any existing timer before trying to connect
            if (reconnectTimerRef.current) {
                clearTimeout(reconnectTimerRef.current);
            }

            // Close any existing socket before creating a new one
            if (socketRef.current) {
                socketRef.current.close();
            }

            socketRef.current = createSocketConnection(
                () => setSocketStatus('CONNECTED'),
                handleMessage,
                handleClose, // Use our new handler that triggers reconnection
                (error) => console.error('Socket error:', error)
            );
        };

        if (!MOCK_MODE) {
            connect(); // Initial connection attempt
        }

        // This is the crucial cleanup function
        return () => {
            console.log("Cleaning up WebSocket and reconnection timer.");
            // Clear the timer on component unmount
            if (reconnectTimerRef.current) {
                clearTimeout(reconnectTimerRef.current);
            }
            // Close the connection on component unmount
            if (socketRef.current) {
                socketRef.current.close();
            }
        };
    }, [MOCK_MODE]); // Empty dependency array ensures this runs only on mount and unmount

    const handleManualExit = async () => {
        if (window.confirm('Are you sure you want to manually exit the current trade?')) {
            try {
                const res = await fetch('http://localhost:8000/api/manual_exit', { method: 'POST' });
                const data = await res.json();
                if (!res.ok) { throw new Error(data.detail); }
                enqueueSnackbar(data.message, { variant: 'warning' });
            } catch (error) {
                console.error("Manual exit failed", error);
                enqueueSnackbar(error.message, { variant: 'error' });
            }
        }
    };

    return (
        <ThemeProvider theme={lightTheme}>
            <CssBaseline />
            <Box sx={{ p: 2 }}>
                <Grid container spacing={2}>
                    <Grid item xs={12} md={4} container direction="column" spacing={2} wrap="nowrap">
                        <Grid item><StatusPanel status={botStatus} socketStatus={socketStatus} /></Grid>
                        <Grid item><CurrentTradePanel trade={currentTrade} onManualExit={handleManualExit} /></Grid>
                        {/* --- CHANGE: Pass the isBotRunning state down as a prop --- */}
                        <Grid item><ParametersPanel isMock={MOCK_MODE} isBotRunning={isBotRunning} /></Grid>
                        <Grid item><IntelligencePanel /></Grid>
                        <Grid item><PerformancePanel data={dailyPerformance} /></Grid>
                    </Grid>
                    <Grid item xs={12} md={8} sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                        <Box><IndexChart data={chartData} /></Box>
                        <Box><OptionChain data={optionChain} indexPrice={botStatus.indexPrice} /></Box>
                        <Box sx={{ flexGrow: 1, minHeight: 0 }}><LogTabs debugLogs={debugLogs} tradeHistory={tradeHistory} /></Box>
                    </Grid>
                </Grid>
            </Box>
        </ThemeProvider>
    );
}

export default App;
