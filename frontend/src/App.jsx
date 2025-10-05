import React, { useEffect, useRef, useCallback } from 'react';
import { Howl } from 'howler';
import { Grid, ThemeProvider, createTheme, CssBaseline, Box, Typography } from '@mui/material';
import ErrorBoundary from './ErrorBoundary.jsx';
import StatusPanel from './components/StatusPanel';
import ParametersPanel from './components/ParametersPanel';
import IntelligencePanel from './components/IntelligencePanel';
import NetPerformancePanel from './components/NetPerformancePanel';
import CurrentTradePanel from './components/CurrentTradePanel';
import IndexChart from './components/IndexChart';
import OptionChain from './components/OptionChain';
import LogTabs from './components/LogTabs';
import StraddleMonitor from './components/StraddleMonitor'; // IMPORT the new component
import { createSocketConnection } from './services/socket';
import { manualExit, getTradeHistory, getTradeHistoryAll } from './services/api';
import { useStore } from './store/store';
import { useSnackbar } from 'notistack';

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
    // Debug: Check if App component is even being called
    console.log("🚀 App function called!");
    
    const { enqueueSnackbar } = useSnackbar();
    const socketRef = useRef(null);
    const reconnectTimerRef = useRef(null);
    const pingIntervalRef = useRef(null);
    const pongTimeoutRef = useRef(null);
    const lastPongRef = useRef(Date.now());
    const isConnectingRef = useRef(false);
    const reconnectAttemptsRef = useRef(0);

    // Debug: Try to get store state
    let storeState;
    try {
        storeState = useStore();
        console.log("✅ Store state retrieved:", storeState);
    } catch (error) {
        console.error("❌ Error getting store state:", error);
        return <div style={{padding: '20px', color: 'red'}}>Store Error: {error.message}</div>;
    }

    const { 
        botStatus, dailyPerformance, currentTrade, debugLogs, 
        optionChain, chartData, socketStatus
    } = storeState;
    
    // Debug: Log to console to verify App is rendering
    console.log("📊 App component rendering with data:", { botStatus, socketStatus });

    const sendSocketMessage = useCallback((message) => {
        if (socketRef.current?.readyState === WebSocket.OPEN) {
            socketRef.current.send(JSON.stringify(message));
        } else {
            console.error("Cannot send message, WebSocket is not open.");
        }
    }, []);
    
    useEffect(() => {
        const { getState, setState } = useStore;

        const connect = async () => {
            if (isConnectingRef.current || socketRef.current?.readyState === WebSocket.OPEN) {
                console.log('Already connecting or connected, skipping...');
                return;
            }
            
            isConnectingRef.current = true;
            setState({ socketStatus: 'CONNECTING' });
            
            const handleOpen = async () => {
                console.log('WebSocket connected successfully');
                setState({ socketStatus: 'CONNECTED' });
                isConnectingRef.current = false;
                reconnectAttemptsRef.current = 0; // Reset reconnect attempts on successful connection
                
                // Reset loaded flags to allow fresh data load
                await getState().resetLoadingFlags();
                
                try {
                    const [todayHistory, allTimeHistory] = await Promise.all([
                        getTradeHistory(),
                        getTradeHistoryAll()
                    ]);
                    
                    getState().setTradeHistory(todayHistory);
                    getState().setAllTimeTradeHistory(allTimeHistory);
                    
                    console.log(`Loaded ${todayHistory.length} trades from today.`);
                    console.log(`Loaded ${allTimeHistory.length} trades from all-time history.`);
                } catch (error) {
                    enqueueSnackbar('Could not load trade history.', { variant: 'error' });
                }
                
                if (pingIntervalRef.current) clearInterval(pingIntervalRef.current);
                if (pongTimeoutRef.current) clearTimeout(pongTimeoutRef.current);
                
                lastPongRef.current = Date.now();
                
                pingIntervalRef.current = setInterval(() => {
                    if (socketRef.current?.readyState === WebSocket.OPEN) {
                        const timeSinceLastPong = Date.now() - lastPongRef.current;
                        
                        // Only disconnect if no pong received for 45 seconds (increased from 30)
                        if (timeSinceLastPong > 45000) {
                            console.warn('No pong received for 45 seconds, reconnecting...');
                            if (socketRef.current) {
                                socketRef.current.close(1000, 'Ping timeout');
                            }
                            return;
                        }
                        
                        // Send ping
                        try {
                            socketRef.current.send(JSON.stringify({ type: 'ping' }));
                        } catch (error) {
                            console.error('Failed to send ping:', error);
                        }
                    }
                }, 20000); // Increased ping frequency to every 20 seconds 
            };
            
            const handleMessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    switch (data.type) {
                        case 'status_update': getState().updateBotStatus(data.payload); break;
                        case 'daily_performance_update': getState().updateDailyPerformance(data.payload); break;
                        case 'trade_status_update': getState().updateCurrentTrade(data.payload); break;
                        case 'debug_log': getState().addDebugLog(data.payload); break;
                        case 'new_trade_log': getState().addTradeToHistory(data.payload); break;
                        case 'option_chain_update': getState().updateOptionChain(data.payload); break;
                        case 'uoa_list_update': getState().updateUoaList(data.payload); break;
                        case 'chart_data_update': getState().updateChartData(data.payload); break;
                        // ADDED: Handle straddle monitor updates
                        case 'straddle_update': getState().updateStraddleData(data.payload); break;
                        case 'play_sound': if (sounds[data.payload]) sounds[data.payload].play(); break;
                        case 'pong': 
                            lastPongRef.current = Date.now();
                            break;
                        // ADDED: Handle system warnings like open positions
                        case 'system_warning':
                            enqueueSnackbar(data.payload.message, { 
                                variant: 'warning',
                                persist: true, // Keep message visible
                            });
                            break;
                    }
                } catch (error) {
                    console.error("Failed to parse socket message:", event.data, error);
                }
            };

            const handleClose = (event) => {
                console.log('WebSocket closed:', event.code, event.reason);
                setState({ socketStatus: 'DISCONNECTED' });
                isConnectingRef.current = false;
                
                // Clear intervals
                if (pingIntervalRef.current) {
                    clearInterval(pingIntervalRef.current);
                    pingIntervalRef.current = null;
                }
                if (pongTimeoutRef.current) {
                    clearTimeout(pongTimeoutRef.current);
                    pongTimeoutRef.current = null;
                }
                
                // Exponential backoff for reconnection
                reconnectAttemptsRef.current++;
                const delay = Math.min(1000 * Math.pow(2, reconnectAttemptsRef.current), 30000);
                
                console.log(`Will reconnect in ${delay/1000} seconds (attempt ${reconnectAttemptsRef.current})...`);
                
                if (reconnectTimerRef.current) {
                    clearTimeout(reconnectTimerRef.current);
                }
                
                reconnectTimerRef.current = setTimeout(() => {
                    if (!isConnectingRef.current) {
                        connect();
                    }
                }, delay);
            };

            // Clean up existing connections
            if (reconnectTimerRef.current) {
                clearTimeout(reconnectTimerRef.current);
                reconnectTimerRef.current = null;
            }
            if (pingIntervalRef.current) {
                clearInterval(pingIntervalRef.current);
                pingIntervalRef.current = null;
            }
            if (socketRef.current && socketRef.current.readyState !== WebSocket.CLOSED) {
                socketRef.current.close(1000, 'Reconnecting');
            }

            try {
                socketRef.current = createSocketConnection(
                    handleOpen, 
                    handleMessage, 
                    handleClose, 
                    (error) => {
                        console.error('Socket error:', error);
                        isConnectingRef.current = false;
                        setState({ socketStatus: 'DISCONNECTED' });
                    }
                );
            } catch (error) {
                console.error('Failed to create WebSocket connection:', error);
                isConnectingRef.current = false;
                setState({ socketStatus: 'DISCONNECTED' });
            }
        };

        if (!MOCK_MODE) connect();

        return () => {
            console.log('Cleaning up WebSocket connections...');
            isConnectingRef.current = false;
            
            if (reconnectTimerRef.current) {
                clearTimeout(reconnectTimerRef.current);
                reconnectTimerRef.current = null;
            }
            if (pingIntervalRef.current) {
                clearInterval(pingIntervalRef.current);
                pingIntervalRef.current = null;
            }
            if (pongTimeoutRef.current) {
                clearTimeout(pongTimeoutRef.current);
                pongTimeoutRef.current = null;
            }
            if (socketRef.current && socketRef.current.readyState !== WebSocket.CLOSED) {
                socketRef.current.close(1000, 'Component unmounting');
            }
        };
    }, [MOCK_MODE, enqueueSnackbar]);

    const handleManualExit = async () => {
        if (window.confirm('Are you sure you want to manually exit the current trade?')) {
            try {
                const data = await manualExit();
                enqueueSnackbar(data.message, { variant: 'warning' });
            } catch (error) {
                enqueueSnackbar(error.message, { variant: 'error' });
            }
        }
    };

    // Debug: Add a safety check
    if (!botStatus) {
        console.warn("⚠️ botStatus is undefined, using defaults");
    }

    return (
        <ThemeProvider theme={lightTheme}>
            <CssBaseline />
            <Box sx={{ p: 2, minHeight: '100vh', bgcolor: '#f4f6f8' }}>
                <Typography variant="h4" sx={{ mb: 2, color: 'primary.main', fontWeight: 'bold' }}>
                    🤖 Trading Bot Dashboard
                </Typography>
                <Typography variant="body2" sx={{ mb: 2, color: 'text.secondary' }}>
                    Socket: {socketStatus || 'DISCONNECTED'} | Bot: {botStatus?.connection || 'DISCONNECTED'}
                </Typography>
                <Grid container spacing={2}>
                    <Grid item xs={12} md={4} container direction="column" spacing={2} wrap="nowrap">
                        <ErrorBoundary name="StatusPanel"><Grid item><StatusPanel status={botStatus} socketStatus={socketStatus} /></Grid></ErrorBoundary>
                        <ErrorBoundary name="CurrentTradePanel"><Grid item><CurrentTradePanel trade={currentTrade} onManualExit={handleManualExit} /></Grid></ErrorBoundary>
                        <ErrorBoundary name="ParametersPanel"><Grid item><ParametersPanel isMock={MOCK_MODE} /></Grid></ErrorBoundary>
                        <ErrorBoundary name="IntelligencePanel"><Grid item><IntelligencePanel /></Grid></ErrorBoundary>
                        <ErrorBoundary name="StraddleMonitor"><Grid item><StraddleMonitor /></Grid></ErrorBoundary>
                        <ErrorBoundary name="NetPerformancePanel"><Grid item><NetPerformancePanel data={dailyPerformance} /></Grid></ErrorBoundary>
                    </Grid>
                    <Grid item xs={12} md={8} sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                        <ErrorBoundary name="IndexChart"><Box><IndexChart data={chartData} /></Box></ErrorBoundary>
                        <ErrorBoundary name="OptionChain"><Box><OptionChain data={optionChain} /></Box></ErrorBoundary>
                        <ErrorBoundary name="LogTabs"><Box sx={{ flexGrow: 1, minHeight: 0 }}><LogTabs debugLogs={debugLogs}/></Box></ErrorBoundary>
                    </Grid>
                </Grid>
            </Box>
        </ThemeProvider>
    );
}

export default App;

