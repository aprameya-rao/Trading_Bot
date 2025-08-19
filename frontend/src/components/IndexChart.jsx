import React, { useEffect, useRef } from 'react';
import { createChart, ColorType } from 'lightweight-charts';
import { Paper, Typography, Box, CircularProgress } from '@mui/material';

// A helper function to apply common styles to both charts
const getChartOptions = (container) => ({
    width: container.clientWidth,
    height: container.clientHeight,
    layout: { background: { type: ColorType.Solid, color: '#ffffff' }, textColor: '#333' },
    grid: { vertLines: { color: '#f0f0f0' }, horzLines: { color: '#f0f0f0' } },
    timeScale: { timeVisible: true, secondsVisible: false, borderColor: '#D1D4DC' },
    rightPriceScale: { borderColor: '#D1D4DC' },
    crosshair: { mode: 1 },
});

export default function IndexChart({ data }) {
    const mainChartContainerRef = useRef(null);
    const rsiChartContainerRef = useRef(null);
    const mainChartRef = useRef(null);
    const rsiChartRef = useRef(null);

    useEffect(() => {
        if (!data || !mainChartContainerRef.current || !rsiChartContainerRef.current) {
            return;
        }

        // === Create RSI Chart (RSI, RSI SMA) - THIS IS CREATED FIRST NOW ===
        const rsiChart = createChart(rsiChartContainerRef.current, getChartOptions(rsiChartContainerRef.current));
        const rsiSeries = rsiChart.addLineSeries({ color: 'rgba(136, 132, 216, 0.7)', lineWidth: 2 });
        const rsiSmaSeries = rsiChart.addLineSeries({ color: '#f5a623', lineWidth: 2 });

        rsiSeries.setData(data.rsi || []);
        rsiSmaSeries.setData(data.rsi_sma || []);

        // === Create Main Chart (Candles, WMA, SMA) - THIS IS CREATED SECOND NOW ===
        const mainChart = createChart(mainChartContainerRef.current, getChartOptions(mainChartContainerRef.current));
        const candlestickSeries = mainChart.addCandlestickSeries({ upColor: '#26a69a', downColor: '#ef5350', borderVisible: false, wickUpColor: '#26a69a', wickDownColor: '#ef5350' });
        const wmaSeries = mainChart.addLineSeries({ color: '#2962FF', lineWidth: 2 });
        const smaSeries = mainChart.addLineSeries({ color: '#FF6D00', lineWidth: 2 });

        candlestickSeries.setData(data.candles || []);
        wmaSeries.setData(data.wma || []);
        smaSeries.setData(data.sma || []);

        // === Synchronize the two charts ===
        const syncCharts = (sourceChart, targetChart) => (param) => {
            if (param.from && param.to) {
                targetChart.timeScale().setVisibleRange(param);
            }
        };
        mainChart.timeScale().subscribeVisibleTimeRangeChange(syncCharts(mainChart, rsiChart));
        rsiChart.timeScale().subscribeVisibleTimeRangeChange(syncCharts(rsiChart, mainChart));

        mainChartRef.current = { chart: mainChart, candles: candlestickSeries, wma: wmaSeries, sma: smaSeries };
        rsiChartRef.current = { chart: rsiChart, rsi: rsiSeries, rsiSma: rsiSmaSeries };

        mainChart.timeScale().fitContent();

        // Handle resizing
        const handleResize = () => {
            if (mainChartRef.current) mainChartRef.current.chart.resize(mainChartContainerRef.current.clientWidth, mainChartContainerRef.current.clientHeight * 0.7); // Adjust height if needed
            if (rsiChartRef.current) rsiChartRef.current.chart.resize(rsiChartContainerRef.current.clientWidth, mainChartContainerRef.current.clientHeight * 0.3); // Adjust height if needed
        };
        window.addEventListener('resize', handleResize);

        // Cleanup
        return () => {
            window.removeEventListener('resize', handleResize);
            if (mainChartRef.current) mainChartRef.current.chart.remove();
            if (rsiChartRef.current) rsiChartRef.current.chart.remove();
        };
    }, [data]);

    return (
        <Paper elevation={3} sx={{ p: 2, height: '450px', display: 'flex', flexDirection: 'column' }}>
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2, mb: 1, alignItems: 'center', flexShrink: 0 }}>
                <Typography variant="body2">Index Chart</Typography>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}> <Box sx={{ width: 12, height: 12, backgroundColor: '#FF6D00' }} /> <Typography variant="caption">SMA</Typography> </Box>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}> <Box sx={{ width: 12, height: 12, backgroundColor: '#2962FF' }} /> <Typography variant="caption">WMA</Typography> </Box>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}> <Box sx={{ width: 12, height: 12, backgroundColor: 'rgba(136, 132, 216, 0.7)' }} /> <Typography variant="caption">RSI</Typography> </Box>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}> <Box sx={{ width: 12, height: 12, backgroundColor: '#f5a623' }} /> <Typography variant="caption">RSI SMA (3MA)</Typography> </Box>
            </Box>

            {!data ? (
                <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
                    <CircularProgress />
                </Box>
            ) : (
                <Box sx={{ width: '100%', flexGrow: 1, display: 'flex', flexDirection: 'column' }}>
                    {/* Top Pane: RSI (takes 30% of the space) - NOW FIRST */}
                    <Box ref={rsiChartContainerRef} sx={{ width: '100%', height: '30%' }} />
                    {/* Bottom Pane: Candles (takes 70% of the space) - NOW SECOND */}
                    <Box ref={mainChartContainerRef} sx={{ width: '100%', height: '70%' }} />
                </Box>
            )}
        </Paper>
    );
}