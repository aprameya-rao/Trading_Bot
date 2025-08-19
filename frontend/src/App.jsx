import React, { useState, useEffect } from 'react';
import { Grid, ThemeProvider, createTheme, CssBaseline, Box } from '@mui/material';
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

const MOCK_MODE = false;

const mockBotStatus = { connection: 'CONNECTED', mode: 'PAPER TRADING', indexPrice: 80690.87, trend: 'BEARISH' };
const mockDailyPerformance = { netPnl: 1250.75, grossProfit: 2500, grossLoss: -1249.25, wins: 2, losses: 1 };
const mockCurrentTrade = { symbol: 'SENSEX25SEP80700CE', entry_price: 268.25, pnl: 150.50, profit_pct: 10.5, trail_sl: 275.5, max_price: 290.0 };
const mockDebugLogs = [ { time: '12:15:00', source: 'System', message: 'Mock mode enabled. Multi-pane chart active.' }, ];
const mockTradeHistory = [ ['SENSEX25SEP80500PE', '10:15:32', 'Trend_Continuation', '150.20', '180.50', '454.50', 'Trailing SL'], ];
const mockOptionChain = [ { strike: 80400, ce_ltp: 561.8, pe_ltp: 197.6 }, { strike: 80500, ce_ltp: 494.05, pe_ltp: 229.25 }, ];
const mockUoaList = [{ symbol: 'SENSEX25SEP81000CE', type: 'CE', strike: '81000' }];
const mockChartData = {
    candles: [ { time: 1755502800, open: 80650, high: 80700, low: 80640, close: 80680 }, { time: 1755503100, open: 80680, high: 80720, low: 80670, close: 80690 } ],
    wma: [ { time: 1755502800, value: 80660 }, { time: 1755503100, value: 80675 } ],
    sma: [ { time: 1755502800, value: 80655 }, { time: 1755503100, value: 80670 } ],
    rsi: [ { time: 1755502800, value: 60 }, { time: 1755503100, value: 65 } ],
    rsi_sma: [ { time: 1755502800, value: 58 }, { time: 1755503100, value: 62 } ]
};

const lightTheme = createTheme({
    palette: {
        mode: 'light', primary: { main: '#1976d2' }, success: { main: '#2e7d32' }, error: { main: '#d32f2f' },
    },
});

function App() {
    const [chartData, setChartData] = useState(null);
    const [botStatus, setBotStatus] = useState({ connection: 'DISCONNECTED', mode: 'NOT STARTED', indexPrice: 0, trend: '---' });
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
                case 'debug_log': setDebugLogs(prev => [data.payload, ...prev].slice(0, 300)); break; case 'trade_log_update': setTradeHistory(data.payload); break;
                case 'option_chain_update': setOptionChain(data.payload); break; case 'uoa_list_update': setUoaList(data.payload); break;
                case 'chart_data_update': setChartData(data.payload); break;
            }
        };
        connectWebSocket(handleSocketMessage); return () => disconnectWebSocket();
    }, []);

    return (
        <ThemeProvider theme={lightTheme}>
            <CssBaseline />
            <Box sx={{ p: 2, height: '100vh', boxSizing: 'border-box' }}>
                <Grid container spacing={2} sx={{ height: '100%' }}>
                    {/* Left Pane */}
                    <Grid item xs={12} md={3.5} container direction="column" spacing={2} wrap="nowrap" sx={{ height: '100%', overflowY: 'auto', overflowX: 'hidden', '&::-webkit-scrollbar': { width: '8px' }, '&::-webkit-scrollbar-track': { background: '#f1f1f1' }, '&::-webkit-scrollbar-thumb': { background: '#aaa', borderRadius: '4px' }, '&::-webkit-scrollbar-thumb:hover': { background: '#888' },}}>
                        <Grid item><StatusPanel status={botStatus} socketStatus={socketStatus} /></Grid>
                        <Grid item><CurrentTradePanel trade={currentTrade} /></Grid>
                        <Grid item><ParametersPanel isMock={MOCK_MODE} /></Grid>
                        <Grid item><IntelligencePanel /></Grid>
                        <Grid item><PerformancePanel data={dailyPerformance} /></Grid>
                        <Grid item><UOAPanel list={uoaList} /></Grid>
                    </Grid>
                    {/* Right Pane */}
                    <Grid item xs={12} md={8.5} sx={{ height: '100%', display: 'flex', flexDirection: 'column', gap: 2 }}>
                        <Box sx={{ flexShrink: 0 }}>
                            {/* The IndexChart component now has a default height of 450px */}
                            <IndexChart data={chartData} />
                        </Box>
                        <Box sx={{ flexShrink: 0 }}>
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