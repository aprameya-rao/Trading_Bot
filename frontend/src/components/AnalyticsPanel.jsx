import React, { useEffect, useRef, useMemo } from 'react';
import { Paper, Typography, Box, Grid, Table, TableBody, TableCell, TableContainer, TableHead, TableRow } from '@mui/material';
import { createChart, ColorType } from 'lightweight-charts';
import { useStore } from '../store/store';

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

export default function AnalyticsPanel({ scope = 'all' }) {
    // Read the correct data slice from the central store based on the 'scope' prop.
    const tradesToAnalyze = useStore(state => 
        scope === 'today' ? state.tradeHistory : state.allTimeTradeHistory
    );
    
    const stats = useMemo(() => {
        if (tradesToAnalyze.length === 0) {
            return null;
        }

        let totalPnl = 0, grossProfit = 0, grossLoss = 0, winningTrades = 0, losingTrades = 0, maxLoss = 0;
        const equityCurve = [];
        
        // Sort trades chronologically to build the equity curve correctly.
        const sortedTrades = [...tradesToAnalyze].sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));

        sortedTrades.forEach((trade) => {
            totalPnl += trade.net_pnl; // Use net_pnl for accurate equity curve
            if (trade.pnl > 0) { 
                winningTrades++; 
                grossProfit += trade.pnl; 
            } else { 
                losingTrades++; 
                grossLoss += Math.abs(trade.pnl);
                maxLoss = Math.max(maxLoss, Math.abs(trade.pnl));
            }
            const unixTime = Math.floor(new Date(trade.timestamp).getTime() / 1000);
            equityCurve.push({ time: unixTime, value: totalPnl });
        });

        const totalTrades = tradesToAnalyze.length;
        const winRate = totalTrades > 0 ? (winningTrades / totalTrades) * 100 : 0;
        const profitFactor = grossLoss > 0 ? grossProfit / grossLoss : Infinity;

        return {
            trades: sortedTrades.reverse(), // Reverse for latest-first display in the table
            equityCurve,
            summary: { totalPnl, profitFactor, totalTrades, winRate, maxLoss },
        };
    }, [tradesToAnalyze]);

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

    return (
        <Box>
            <Grid container spacing={2} sx={{ mb: 2 }}>
                <StatBox title="Total Gross P&L" value={`₹${summary.totalPnl.toFixed(2)}`} />
                <StatBox title="Profit Factor" value={summary.profitFactor.toFixed(2)} />
                <StatBox title="Total Trades" value={summary.totalTrades} />
                <StatBox title="Win Rate" value={`${summary.winRate.toFixed(1)}%`} />
                <StatBox title="Biggest Loss" value={`₹${summary.maxLoss.toFixed(2)}`} />
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
                            <TableCell align="right">Exit</TableCell><TableCell align="right">P&L (Gross)</TableCell>
                        </TableRow>
                    </TableHead>
                    <TableBody>
                        {trades.map((trade) => (
                            <TableRow key={trade.id || trade.timestamp}>
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