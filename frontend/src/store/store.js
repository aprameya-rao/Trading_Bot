import { create } from 'zustand';

// ===== Parameters Slice =====
const createParametersSlice = (set) => ({
    params: {}, // Initial state will be loaded by an action
    loadParams: () => {
        const savedParams = localStorage.getItem('tradingParams');
        const defaultParams = {
            selectedIndex: 'SENSEX', trading_mode: 'Paper Trading', aggressiveness: 'Moderate', 
            start_capital: 50000, risk_per_trade_percent: 2.0, trailing_sl_points: 5, 
            trailing_sl_percent: 2.5, daily_sl: -20000, daily_pt: 40000, 
            partial_profit_pct: 3, partial_exit_pct: 30, auto_scan_uoa: false
        };
        set({ params: savedParams ? JSON.parse(savedParams) : defaultParams });
    },
    setParams: (newParams) => {
        localStorage.setItem('tradingParams', JSON.stringify(newParams));
        set({ params: newParams });
    },
    updateParam: (name, value) => set((state) => {
        const updatedParams = { ...state.params, [name]: value };
        localStorage.setItem('tradingParams', JSON.stringify(updatedParams));
        return { params: updatedParams };
    }),
});

// ===== Real-time Data Slice =====
const createRealtimeDataSlice = (set) => ({
    chartData: null,
    botStatus: { connection: 'DISCONNECTED', mode: 'NOT STARTED', indexPrice: 0, trend: '---', indexName: 'INDEX', is_running: false },
    dailyPerformance: { netPnl: 0, grossProfit: 0, grossLoss: 0, wins: 0, losses: 0 },
    currentTrade: null,
    debugLogs: [],
    tradeHistory: [],
    optionChain: [],
    uoaList: [],
    socketStatus: 'DISCONNECTED',
    
    setSocketStatus: (status) => set({ socketStatus: status }),
    updateBotStatus: (payload) => set({ botStatus: payload }),
    updateDailyPerformance: (payload) => set({ dailyPerformance: payload }),
    updateCurrentTrade: (payload) => set({ currentTrade: payload }),
    addDebugLog: (payload) => set(state => ({ debugLogs: [payload, ...state.debugLogs] })),
    updateTradeHistory: (payload) => set({ tradeHistory: payload }),
    updateOptionChain: (payload) => set({ optionChain: payload }),
    updateUoaList: (payload) => set({ uoaList: payload }),
    updateChartData: (payload) => set({ chartData: payload }),
});

export const useStore = create((...a) => ({
    ...createParametersSlice(...a),
    ...createRealtimeDataSlice(...a),
}));

useStore.getState().loadParams();