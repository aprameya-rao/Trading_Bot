import React, { useState, useEffect, useRef } from 'react';
import { Paper, Typography, Box, Grid, CircularProgress, Table, TableBody, TableCell, TableContainer, TableHead, TableRow } from '@mui/material';
import { createChart, ColorType } from 'lightweight-charts';
import { getTradeHistory, getTradeHistoryAll } from '../services/api'; // Use our API service

// A small, reusable chart component for the equity curve
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

// The main reusable AnalyticsPanel component
export default function AnalyticsPanel({ scope = 'all' }) {
    const [stats, setStats] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        const fetchAndCalculateStats = async () => {
            setLoading(true);
            try {
                // CHANGED: Select the API call based on the 'scope' prop
                const fetcher = scope === 'today' ? getTradeHistory : getTradeHistoryAll;
                const trades = await fetcher();

                if (trades.length === 0) {
                    setStats({ trades: [], summary: {}, equityCurve: [] });
                    return;
                }

                // --- All calculations remain the same ---
                let totalPnl = 0, grossProfit = 0, grossLoss = 0, winningTrades = 0, losingTrades = 0, peakEquity = 0, maxDrawdown = 0;
                const equityCurve = [];

                trades.forEach((trade) => {
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

                setStats({
                    trades, equityCurve,
                    summary: { totalPnl, profitFactor, totalTrades, winRate, maxDrawdown, avgTrade: totalTrades > 0 ? totalPnl / totalTrades : 0 },
                });

            } catch (err) {
                setError(err.message);
            } finally {
                setLoading(false);
            }
        };

        fetchAndCalculateStats();
    }, [scope]); // Re-run effect if the scope changes

    if (loading) return <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}><CircularProgress /></Box>;
    if (error) return <Typography color="error" sx={{ p: 2 }}>Error: {error}</Typography>;
    if (!stats || stats.trades.length === 0) return <Typography sx={{ p: 2 }}>No trade data found for this period.</Typography>;

    const { summary, trades, equityCurve } = stats;

    const StatBox = ({ title, value }) => (
        <Grid item xs={6} sm={4} md={2.4}>
            <Paper sx={{ p: 1, textAlign: 'center' }}>
                <Typography variant="caption" display="block">{title}</Typography>
                <Typography variant="h6">{value}</Typography>
            </Paper>
        </Grid>
    );

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
                        {[...trades].reverse().map((trade) => (
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