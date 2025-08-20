import React, { useState, useEffect, useRef } from 'react';
import { Paper, Typography, Box, Grid, CircularProgress, Table, TableBody, TableCell, TableContainer, TableHead, TableRow } from '@mui/material';
import { createChart, ColorType } from 'lightweight-charts';

// Chart utility
const ChartComponent = ({ data }) => {
    const chartContainerRef = useRef();
    const chartRef = useRef();

    useEffect(() => {
        if (!chartContainerRef.current) return;

        chartRef.current = createChart(chartContainerRef.current, {
            width: chartContainerRef.current.clientWidth,
            height: 200,
            layout: { textColor: '#333', background: { type: ColorType.Solid, color: 'white' } },
            grid: { vertLines: { color: '#f0f0f0' }, horzLines: { color: '#f0f0f0' } },
        });

        const areaSeries = chartRef.current.addAreaSeries({
            lineColor: '#2962FF',
            topColor: 'rgba(41, 98, 255, 0.4)',
            bottomColor: 'rgba(41, 98, 255, 0)',
        });
        areaSeries.setData(data);
        chartRef.current.timeScale().fitContent();
        
        const handleResize = () => chartRef.current.resize(chartContainerRef.current.clientWidth, 200);
        window.addEventListener('resize', handleResize);

        return () => {
            window.removeEventListener('resize', handleResize);
            chartRef.current.remove();
        };
    }, [data]);

    return <div ref={chartContainerRef} />;
};


export default function AnalyticsPanel() {
    const [stats, setStats] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        const fetchAndCalculateStats = async () => {
            try {
                const response = await fetch('http://localhost:8000/api/trade_history');
                if (!response.ok) throw new Error('Failed to fetch trade history');
                
                const trades = await response.json();
                if (trades.length === 0) {
                    setStats({ trades: [], summary: {}, equityCurve: [] });
                    return;
                }

                let totalPnl = 0;
                let grossProfit = 0;
                let grossLoss = 0;
                let winningTrades = 0;
                let losingTrades = 0;
                let peakEquity = 0;
                let maxDrawdown = 0;
                const equityCurve = [];

                trades.forEach((trade, index) => {
                    totalPnl += trade.pnl;
                    if (trade.pnl > 0) {
                        grossProfit += trade.pnl;
                        winningTrades++;
                    } else {
                        grossLoss += Math.abs(trade.pnl);
                        losingTrades++;
                    }
                    
                    // For equity curve and drawdown
                    const tradeDate = new Date(trade.timestamp);
                    const unixTime = Math.floor(tradeDate.getTime() / 1000);
                    equityCurve.push({ time: unixTime, value: totalPnl });
                    
                    if (totalPnl > peakEquity) {
                        peakEquity = totalPnl;
                    }
                    const drawdown = peakEquity - totalPnl;
                    if (drawdown > maxDrawdown) {
                        maxDrawdown = drawdown;
                    }
                });

                const totalTrades = trades.length;
                const winRate = totalTrades > 0 ? (winningTrades / totalTrades) * 100 : 0;
                const profitFactor = grossLoss > 0 ? grossProfit / grossLoss : Infinity;

                setStats({
                    trades,
                    equityCurve,
                    summary: {
                        totalPnl,
                        profitFactor,
                        totalTrades,
                        winRate,
                        maxDrawdown,
                        avgTrade: totalTrades > 0 ? totalPnl / totalTrades : 0,
                    },
                });

            } catch (err) {
                setError(err.message);
            } finally {
                setLoading(false);
            }
        };

        fetchAndCalculateStats();
    }, []);

    if (loading) return <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}><CircularProgress /></Box>;
    if (error) return <Typography color="error" sx={{ p: 2 }}>Error: {error}</Typography>;
    if (!stats || stats.trades.length === 0) return <Typography sx={{ p: 2 }}>No trade history found in the database.</Typography>;

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
                {equityCurve.length > 1 && <ChartComponent data={equityCurve} />}
            </Paper>

            <TableContainer component={Paper}>
                 <Table stickyHeader size="small">
                    <TableHead>
                        <TableRow>
                            <TableCell>Timestamp</TableCell>
                            <TableCell>Symbol</TableCell>
                            <TableCell>Trigger</TableCell>
                            <TableCell align="right">Entry</TableCell>
                            <TableCell align="right">Exit</TableCell>
                            <TableCell align="right">P&L</TableCell>
                        </TableRow>
                    </TableHead>
                    <TableBody>
                        {trades.map((trade) => (
                            <TableRow key={trade.id}>
                                <TableCell>{new Date(trade.timestamp).toLocaleString()}</TableCell>
                                <TableCell>{trade.symbol}</TableCell>
                                <TableCell>{trade.trigger_reason}</TableCell>
                                <TableCell align="right">{trade.entry_price.toFixed(2)}</TableCell>
                                <TableCell align="right">{trade.exit_price.toFixed(2)}</TableCell>
                                <TableCell align="right" sx={{ color: trade.pnl > 0 ? 'success.main' : 'error.main' }}>
                                    {trade.pnl.toFixed(2)}
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </TableContainer>
        </Box>
    );
}