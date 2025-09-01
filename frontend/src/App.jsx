import React, { useEffect, useRef, useCallback } from 'react';
import { Howl } from 'howler';
import { Grid, ThemeProvider, createTheme, CssBaseline, Box } from '@mui/material';
import StatusPanel from './components/StatusPanel';
import ParametersPanel from './components/ParametersPanel';
import IntelligencePanel from './components/IntelligencePanel';
import NetPerformancePanel from './components/NetPerformancePanel'; // MODIFIED: Import the new panel
import CurrentTradePanel from './components/CurrentTradePanel';
import IndexChart from './components/IndexChart';
import OptionChain from './components/OptionChain';
import LogTabs from './components/LogTabs';
import { createSocketConnection } from './services/socket';
import { manualExit, getTradeHistory } from './services/api';
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
    const { enqueueSnackbar } = useSnackbar();
    const socketRef = useRef(null);
    const reconnectTimerRef = useRef(null);
    const pingIntervalRef = useRef(null);

    const { 
        botStatus, dailyPerformance, currentTrade, debugLogs, 
        optionChain, chartData, socketStatus
    } = useStore();

    const sendSocketMessage = useCallback((message) => {
        if (socketRef.current?.readyState === WebSocket.OPEN) {
            socketRef.current.send(JSON.stringify(message));
        } else {
            console.error("Cannot send message, WebSocket is not open.");
        }
    }, []);
    
    useEffect(() => {
        const { getState, setState } = useStore;

        const connect = () => {
            const handleOpen = async () => {
                setState({ socketStatus: 'CONNECTED' });
                
                try {
                    console.log("Fetching today's trade history...");
                    const history = await getTradeHistory();
                    getState().setTradeHistory(history);
                    console.log(`Loaded ${history.length} trades from history.`);
                } catch (error) {
                    enqueueSnackbar('Could not load trade history.', { variant: 'error' });
                }
                
                if (pingIntervalRef.current) clearInterval(pingIntervalRef.current);
                pingIntervalRef.current = setInterval(() => {
                    sendSocketMessage({ type: 'ping' });
                }, 4000); 
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
                        case 'play_sound': if (sounds[data.payload]) sounds[data.payload].play(); break;
                        case 'pong': break;
                    }
                } catch (error) {
                    console.error("Failed to parse socket message:", event.data, error);
                }
            };

            const handleClose = () => {
                setState({ socketStatus: 'DISCONNECTED' });
                if (pingIntervalRef.current) clearInterval(pingIntervalRef.current);
                reconnectTimerRef.current = setTimeout(connect, 5000);
            };

            if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
            if (pingIntervalRef.current) clearInterval(pingIntervalRef.current);
            if (socketRef.current) socketRef.current.close();

            socketRef.current = createSocketConnection(
                handleOpen, 
                handleMessage, 
                handleClose, 
                (error) => console.error('Socket error:', error)
            );
        };

        if (!MOCK_MODE) connect();

        return () => {
            if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
            if (pingIntervalRef.current) clearInterval(pingIntervalRef.current);
            if (socketRef.current) socketRef.current.close();
        };
    }, [MOCK_MODE, sendSocketMessage, enqueueSnackbar]);

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

    return (
        <ThemeProvider theme={lightTheme}>
            <CssBaseline />
            <Box sx={{ p: 2 }}>
                <Grid container spacing={2}>
                    <Grid item xs={12} md={4} container direction="column" spacing={2} wrap="nowrap">
                        <Grid item><StatusPanel status={botStatus} socketStatus={socketStatus} /></Grid>
                        <Grid item><CurrentTradePanel trade={currentTrade} onManualExit={handleManualExit} /></Grid>
                        <Grid item><ParametersPanel isMock={MOCK_MODE} /></Grid>
                        <Grid item><IntelligencePanel /></Grid>
                        {/* MODIFIED: Replaced PerformancePanel with the new NetPerformancePanel */}
                        <Grid item><NetPerformancePanel data={dailyPerformance} /></Grid>
                    </Grid>
                    <Grid item xs={12} md={8} sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                        <Box><IndexChart data={chartData} /></Box>
                        <Box><OptionChain data={optionChain} /></Box>
                        <Box sx={{ flexGrow: 1, minHeight: 0 }}><LogTabs debugLogs={debugLogs}/></Box>
                    </Grid>
                </Grid>
            </Box>
        </ThemeProvider>
    );
}

export default App;

