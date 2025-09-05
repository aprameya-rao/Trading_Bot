import { create } from 'zustand';

const spectatorFlag = !!import.meta.env.VITE_MASTER_BACKEND_URL;

const initialRealtimeState = {
    chartData: null,
    botStatus: { connection: 'DISCONNECTED', mode: 'NOT STARTED', indexPrice: 0, trend: '---', indexName: 'INDEX', is_running: false },
    dailyPerformance: { grossPnl: 0, totalCharges: 0, netPnl: 0, wins: 0, losses: 0 },
    currentTrade: null,
    debugLogs: [],
    tradeHistory: [],
    allTimeTradeHistory: [], 
    optionChain: [],
    uoaList: [],
    straddleData: null,
    socketStatus: 'DISCONNECTED',
};

// ===== Parameters Slice =====
const createParametersSlice = (set) => ({
    params: {},
    loadParams: () => {
        const savedParams = localStorage.getItem('tradingParams');
        // MODIFIED: Added the new default parameters here
        const defaultParams = {
            selectedIndex: 'SENSEX', trading_mode: 'Paper Trading',
            start_capital: 50000, risk_per_trade_percent: 2.0, trailing_sl_points: 5, 
            trailing_sl_percent: 2.5, daily_sl: -20000, daily_pt: 40000, 
            partial_profit_pct: 3, partial_exit_pct: 30, auto_scan_uoa: false,
            // --- These are the new default values ---
            recovery_threshold_pct: 2.0, 
            max_lots_per_order: 1800
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
    ...initialRealtimeState,
    resetRealtimeData: () => set(initialRealtimeState),
    isSpectatorMode: spectatorFlag,
    setSocketStatus: (status) => set({ socketStatus: status }),
    setTradeHistory: (history) => set({ tradeHistory: history }),
    setAllTimeTradeHistory: (history) => set({ allTimeTradeHistory: history }),
    updateBotStatus: (payload) => set({ botStatus: payload }),
    updateDailyPerformance: (payload) => set({ dailyPerformance: payload }),
    updateCurrentTrade: (payload) => set({ currentTrade: payload }),
    addDebugLog: (payload) => set(state => ({ debugLogs: [payload, ...state.debugLogs].slice(0, 500) })),
    updateOptionChain: (payload) => set({ optionChain: payload }),
    updateUoaList: (payload) => set({ uoaList: payload }),
    updateChartData: (payload) => set({ chartData: payload }),
    updateStraddleData: (payload) => set({ straddleData: payload }),
    addTradeToHistory: (trade) => set(state => ({ 
        tradeHistory: [trade, ...state.tradeHistory],
        allTimeTradeHistory: [trade, ...state.allTimeTradeHistory]
    })),
});

export const useStore = create((...a) => ({
    ...createParametersSlice(...a),
    ...createRealtimeDataSlice(...a),
}));

useStore.getState().loadParams();

