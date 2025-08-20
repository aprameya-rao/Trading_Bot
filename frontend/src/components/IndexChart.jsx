import React, { useEffect, useRef } from 'react';
import { createChart, ColorType } from 'lightweight-charts';
import { Paper, Typography, Box, CircularProgress } from '@mui/material';

const getChartOptions = (containerRef) => ({
    width: containerRef.clientWidth,
    height: containerRef.clientHeight,
    layout: {
        background: { type: ColorType.Solid, color: '#ffffff' },
        textColor: '#333',
    },
    grid: { vertLines: { color: '#f0f0f0' }, horzLines: { color: '#f0f0f0' } },
    timeScale: {
        timeVisible: true,
        secondsVisible: false,
        borderColor: '#D1D4DC',
        tickMarkFormatter: (time) => {
            const date = new Date(time * 1000);
            return date.toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false });
        },
    },
    rightPriceScale: { borderColor: '#D1D4DC' },
    crosshair: { mode: 1 },
});

export default function IndexChart({ data }) {
    const mainChartContainerRef = useRef(null);
    const rsiChartContainerRef = useRef(null);
    // Use a single ref to hold all chart instances and series
    const chartRefs = useRef({});

    // --- EFFECT #1: Runs ONLY ONCE to CREATE the charts and series ---
    useEffect(() => {
        if (!mainChartContainerRef.current || !rsiChartContainerRef.current) return;

        // Create Main Chart
        const mainChart = createChart(mainChartContainerRef.current, getChartOptions(mainChartContainerRef.current));
        const candlestickSeries = mainChart.addCandlestickSeries({ upColor: '#26a69a', downColor: '#ef5350', borderVisible: false, wickUpColor: '#26a69a', wickDownColor: '#ef5350' });
        const wmaSeries = mainChart.addLineSeries({ color: '#2962FF', lineWidth: 2, title: 'WMA' });
        const smaSeries = mainChart.addLineSeries({ color: '#FF6D00', lineWidth: 2, title: 'SMA' });

        // Create RSI Chart
        const rsiChartOptions = getChartOptions(rsiChartContainerRef.current);
        rsiChartOptions.rightPriceScale.visible = false;
        const rsiChart = createChart(rsiChartContainerRef.current, rsiChartOptions);
        const rsiSeries = rsiChart.addLineSeries({ color: 'rgba(136, 132, 216, 0.7)', lineWidth: 2, title: 'RSI' });
        const rsiSmaSeries = rsiChart.addLineSeries({ color: '#f5a623', lineWidth: 2, title: 'RSI SMA' });

        // Synchronize scrolling and crosshair
        mainChart.timeScale().subscribeVisibleTimeRangeChange(param => {
            if (rsiChart && rsiChart.timeScale()) rsiChart.timeScale().setVisibleRange(param);
        });
        rsiChart.timeScale().subscribeVisibleTimeRangeChange(param => {
            if (mainChart && mainChart.timeScale()) mainChart.timeScale().setVisibleRange(param);
        });
        
        // Store all instances in the ref
        chartRefs.current = { mainChart, rsiChart, candlestickSeries, wmaSeries, smaSeries, rsiSeries, rsiSmaSeries };

        // Cleanup function to remove charts when the component unmounts
        return () => {
            if (chartRefs.current.mainChart) chartRefs.current.mainChart.remove();
            if (chartRefs.current.rsiChart) chartRefs.current.rsiChart.remove();
        };
    }, []); // <-- Empty dependency array means this runs only once

    // --- EFFECT #2: Runs whenever `data` changes to UPDATE the series ---
    useEffect(() => {
        if (!data || !chartRefs.current.candlestickSeries) {
            return; // Don't do anything if there's no data or the chart isn't ready
        }

        // Update each series with the new data
        if (data.candles) chartRefs.current.candlestickSeries.setData(data.candles);
        if (data.wma) chartRefs.current.wmaSeries.setData(data.wma);
        if (data.sma) chartRefs.current.smaSeries.setData(data.sma);
        if (data.rsi) chartRefs.current.rsiSeries.setData(data.rsi);
        if (data.rsi_sma) chartRefs.current.rsiSmaSeries.setData(data.rsi_sma);
        
        // Fit content after the first data load
        if(data.candles && data.candles.length > 0) {
            chartRefs.current.mainChart.timeScale().fitContent();
        }

    }, [data]); // <-- This effect depends only on the `data` prop

    // --- EFFECT #3: Handles window resizing ---
    useEffect(() => {
        const handleResize = () => {
            if (chartRefs.current.mainChart && mainChartContainerRef.current) {
                chartRefs.current.mainChart.resize(mainChartContainerRef.current.clientWidth, mainChartContainerRef.current.clientHeight);
            }
            if (chartRefs.current.rsiChart && rsiChartContainerRef.current) {
                chartRefs.current.rsiChart.resize(rsiChartContainerRef.current.clientWidth, rsiChartContainerRef.current.clientHeight);
            }
        };
        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    }, []); // <-- Runs only once

    return (
        <Paper elevation={3} sx={{ p: 2, height: '450px', display: 'flex', flexDirection: 'column' }}>
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2, mb: 1, alignItems: 'center', flexShrink: 0 }}>
                <Typography variant="body2">Index Chart</Typography>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}> <Box sx={{ width: 12, height: 12, backgroundColor: '#FF6D00' }} /> <Typography variant="caption">SMA</Typography> </Box>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}> <Box sx={{ width: 12, height: 12, backgroundColor: '#2962FF' }} /> <Typography variant="caption">WMA</Typography> </Box>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}> <Box sx={{ width: 12, height: 12, backgroundColor: 'rgba(136, 132, 216, 0.7)' }} /> <Typography variant="caption">RSI</Typography> </Box>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}> <Box sx={{ width: 12, height: 12, backgroundColor: '#f5a623' }} /> <Typography variant="caption">RSI SMA</Typography> </Box>
            </Box>

            {/* The spinner will show initially until the first `data` prop arrives */}
            {!data ? (
                <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
                    <CircularProgress />
                </Box>
            ) : (
                <Box sx={{ width: '100%', flexGrow: 1, display: 'flex', flexDirection: 'column' }}>
                    <Box ref={rsiChartContainerRef} sx={{ width: '100%', height: '30%' }} />
                    <Box ref={mainChartContainerRef} sx={{ width: '100%', height: '70%' }} />
                </Box>
            )}
        </Paper>
    );
}