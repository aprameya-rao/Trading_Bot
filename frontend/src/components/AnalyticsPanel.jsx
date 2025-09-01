import React, { useEffect, useRef, useMemo } from 'react';
import { Paper, Typography, Box, Grid, CircularProgress, Table, TableBody, TableCell, TableContainer, TableHead, TableRow } from '@mui/material';
import { createChart, ColorType } from 'lightweight-charts';
import { useStore } from '../store/store'; // Use the global store

// This small, reusable chart component for the equity curve remains the same
const ChartComponent = ({ data }) => {
    const chartContainerRef = useRef();

    useEffect(() => {
        if (!chartContainerRef.current || data.length < 2) return;

        const chart = createChart(chartContainerRef.current, {
            width: chartContainerRef.current.clientWidth,
            height: 200,
            layout: { textColor: '#333', background: { type: ColorType.Solid, color: 'white' } },
            grid: { vertLines: { color: '#f0f0f0' }, horzLines: { color: '#f0f0f0' } },
            timeScale: { timeVisible: true, secondsVisible: false },
        });

        const areaSeries = chart.addAreaSeries({
            lineColor: '#2962FF', topColor: 'rgba(41, 98, 255, 0.4)', bottomColor: 'rgba(41, 98, 255, 0)',
        });
        areaSeries.setData(data);
        chart.timeScale().fitContent();
        
        const handleResize = () => chart.resize(chartContainerRef.current.clientWidth, 200);
        window.addEventListener('resize', handleResize);

        return () => {
            window.removeEventListener('resize', handleResize);
            chart.remove();
        };
    }, [data]);

    return <div ref={chartContainerRef} style={{ width: '100%', height: '200px' }} />;
};

// The main reusable AnalyticsPanel component, now powered by the store
export default function AnalyticsPanel({ scope = 'all' }) {
    // Get all trades from the global Zustand store
    const allTrades = useStore(state => state.tradeHistory);
    
    // useMemo will re-run the calculations only when the trade history changes
    const stats = useMemo(() => {
        // Filter trades based on the 'scope' prop ('today' or 'all')
        const trades = scope === 'today' 
            ? allTrades.filter(t => new Date(t.timestamp).toDateString() === new Date().toDateString())
            : allTrades;

        if (trades.length === 0) {
            return null;
        }

        let totalPnl = 0, grossProfit = 0, grossLoss = 0, winningTrades = 0, losingTrades = 0, peakEquity = 0, maxDrawdown = 0;
        const equityCurve = [];

        // Sort trades by timestamp to calculate equity curve correctly
        const sortedTrades = [...trades].sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));

        sortedTrades.forEach((trade) => {
            totalPnl += trade.pnl;
            if (trade.pnl > 0) { winningTrades++; grossProfit += trade.pnl; } else { losingTrades++; grossLoss += Math.abs(trade.pnl); }
            const unixTime = Math.floor(new Date(trade.timestamp).getTime() / 1000);
            equityCurve.push({ time: unixTime, value: totalPnl });
            if (totalPnl > peakEquity) peakEquity = totalPnl;
            const drawdown = peakEquity - totalPnl;
            if (drawdown > maxDrawdown) maxDrawdown = drawdown;
        });

        const totalTrades = trades.length;
        const winRate = totalTrades > 0 ? (winningTrades / totalTrades) * 100 : 0;
        const profitFactor = grossLoss > 0 ? grossProfit / grossLoss : Infinity;

        return {
            trades, equityCurve,
            summary: { totalPnl, profitFactor, totalTrades, winRate, maxDrawdown, avgTrade: totalTrades > 0 ? totalPnl / totalTrades : 0 },
        };
    }, [allTrades, scope]);

    // Conditional rendering for different states
    if (!stats) return <Typography sx={{ p: 2 }}>No trade data found for this period.</Typography>;

    const { summary, trades, equityCurve } = stats;

    const StatBox = ({ title, value }) => (
        <Grid item xs={6} sm={4} md={2.4}>
            <Paper sx={{ p: 1, textAlign: 'center' }}>
                <Typography variant="caption" display="block">{title}</Typography>
                <Typography variant="h6">{value}</Typography>
            </Paper>
        </Grid>
    );

    // --- COMPLETE JSX RETURN BLOCK ---
    return (
        <Box>
            <Grid container spacing={2} sx={{ mb: 2 }}>
                <StatBox title="Total Net P&L" value={`₹${summary.totalPnl.toFixed(2)}`} />
                <StatBox title="Profit Factor" value={summary.profitFactor.toFixed(2)} />
                <StatBox title="Total Trades" value={summary.totalTrades} />
                <StatBox title="Win Rate" value={`${summary.winRate.toFixed(1)}%`} />
                <StatBox title="Max Drawdown" value={`₹${summary.maxDrawdown.toFixed(2)}`} />
            </Grid>
            <Paper sx={{ p: 2, mb: 2 }}>
                <Typography variant="body2" sx={{ mb: 1 }}>Equity Curve</Typography>
                <ChartComponent data={equityCurve} />
            </Paper>
            <TableContainer component={Paper} sx={{ maxHeight: 350 }}>
                 <Table stickyHeader size="small">
                    <TableHead>
                        <TableRow>
                            <TableCell>Timestamp</TableCell><TableCell>Symbol</TableCell><TableCell>Qty</TableCell>
                            <TableCell>Trigger</TableCell><TableCell align="right">Entry</TableCell>
                            <TableCell align="right">Exit</TableCell><TableCell align="right">P&L</TableCell>
                        </TableRow>
                    </TableHead>
                    <TableBody>
                        {[...trades].map((trade) => (
                            <TableRow key={trade.id}>
                                <TableCell>{new Date(trade.timestamp).toLocaleString()}</TableCell>
                                <TableCell>{trade.symbol}</TableCell><TableCell>{trade.quantity}</TableCell>
                                <TableCell>{trade.trigger_reason}</TableCell>
                                <TableCell align="right">{trade.entry_price.toFixed(2)}</TableCell>
                                <TableCell align="right">{trade.exit_price.toFixed(2)}</TableCell>
                                <TableCell align="right" sx={{ color: trade.pnl > 0 ? 'success.main' : 'error.main' }}>{trade.pnl.toFixed(2)}</TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </TableContainer>
        </Box>
    );
}