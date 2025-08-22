import React, { useState, useEffect, useCallback } from 'react';
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
import UOAPanel from './components/UOAPanel';
import { connectWebSocket, disconnectWebSocket } from './services/socket';
import { Howl } from 'howler';

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
    const [chartData, setChartData] = useState(null);
    const [botStatus, setBotStatus] = useState({ connection: 'DISCONNECTED', mode: 'NOT STARTED', indexPrice: 0, trend: '---', indexName: 'INDEX' });
    const [dailyPerformance, setDailyPerformance] = useState({ netPnl: 0, grossProfit: 0, grossLoss: 0, wins: 0, losses: 0 });
    const [currentTrade, setCurrentTrade] = useState(null);
    const [debugLogs, setDebugLogs] = useState([]);
    const [tradeHistory, setTradeHistory] = useState([]);
    const [optionChain, setOptionChain] = useState([]);
    const [uoaList, setUoaList] = useState([]);
    const [socketStatus, setSocketStatus] = useState('DISCONNECTED');
    
    useEffect(() => {
        if (MOCK_MODE) {
            setSocketStatus('CONNECTED'); setBotStatus(mockBotStatus); setDailyPerformance(mockDailyPerformance);
            setCurrentTrade(mockCurrentTrade); setDebugLogs(mockDebugLogs); setTradeHistory(mockTradeHistory);
            setOptionChain(mockOptionChain); setUoaList(mockUoaList); setChartData(mockChartData);
            return;
        }
        const handleSocketMessage = (data) => {
            switch (data.type) {
                case 'socket_status': setSocketStatus(data.payload); break; case 'status_update': setBotStatus(data.payload); break;
                case 'daily_performance_update': setDailyPerformance(data.payload); break; case 'trade_status_update': setCurrentTrade(data.payload); break;
                // --- MODIFIED: Limit the debug logs to the latest 22 entries ---
                case 'debug_log': setDebugLogs(prev => [data.payload, ...prev].slice(0, 22)); break; case 'trade_log_update': setTradeHistory(data.payload); break;
                case 'option_chain_update': setOptionChain(data.payload); break; case 'uoa_list_update': setUoaList(data.payload); break;
                case 'chart_data_update': setChartData(data.payload); break;
            }
        };
        connectWebSocket(handleSocketMessage); return () => disconnectWebSocket();
    }, []);

    useEffect(() => {
        // ...
        const handleSocketMessage = (data) => {
            switch (data.type) {
                case 'socket_status': setSocketStatus(data.payload); break;
                // ... other cases
                case 'chart_data_update': setChartData(data.payload); break;
                
                // --- ADD THIS NEW CASE ---
                case 'play_sound':
    // We added the keyword "Sound:" to the log
    console.log(`--- Sound: Received event, trying to play: ${data.payload} ---`);

    if (sounds[data.payload]) {
        const sound = sounds[data.payload];

        // Add a specific error listener for this sound
        sound.once('playerror', function(id, error) {
          console.error(`--- Sound: Howler Playback Error ---`, error);
        });

        sound.play();

    } else {
        console.warn(`--- Sound: Howler sound not found for payload: ${data.payload} ---`);
    }
    break;
    }
        };
        connectWebSocket(handleSocketMessage);
        return () => disconnectWebSocket();
    }, []);

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
                    {/* Left Pane */}
                    <Grid item xs={12} md={4} container direction="column" spacing={2} wrap="nowrap">
                        <Grid item><StatusPanel status={botStatus} socketStatus={socketStatus} /></Grid>
                        <Grid item><CurrentTradePanel trade={currentTrade} onManualExit={handleManualExit} /></Grid>
                        <Grid item><ParametersPanel isMock={MOCK_MODE} /></Grid>
                        <Grid item><IntelligencePanel /></Grid>
                        <Grid item><PerformancePanel data={dailyPerformance} /></Grid>
                        <Grid item><UOAPanel list={uoaList} /></Grid>
                    </Grid>

                    {/* Right Pane */}
                    <Grid item xs={12} md={8} sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                        <Box>
                            <IndexChart data={chartData} />
                        </Box>
                        <Box>
                            <OptionChain data={optionChain} indexPrice={botStatus.indexPrice} />
                        </Box>
                        <Box sx={{ flexGrow: 1, minHeight: 0 }}>
                            <LogTabs debugLogs={debugLogs} tradeHistory={tradeHistory} />
                        </Box>
                    </Grid>
                </Grid>
            </Box>
        </ThemeProvider>
    );
}
export default App;
