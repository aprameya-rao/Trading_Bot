import React, { useEffect, useRef } from 'react';
import { createChart, ColorType } from 'lightweight-charts';
import { Paper, Typography, Box, CircularProgress } from '@mui/material';

// This function creates the chart with all its settings.
const createMyChart = (container) => {
    const chart = createChart(container, {
        width: container.clientWidth,
        height: container.clientHeight,
        layout: {
            background: { type: ColorType.Solid, color: '#ffffff' },
            textColor: '#333',
        },
        grid: { 
            vertLines: { color: '#f0f0f0' }, 
            horzLines: { color: '#f0f0f0' } 
        },
        timeScale: {
            timeVisible: true,
            secondsVisible: false,
            borderColor: '#D1D4DC',
            tickMarkFormatter: (time) => {
                const date = new Date(time * 1000);
                return date.toLocaleTimeString('en-IN', { 
                    timeZone: 'Asia/Kolkata', 
                    hour: '2-digit', 
                    minute: '2-digit', 
                    hour12: false 
                });
            },
        },
        rightPriceScale: { 
            borderColor: '#D1D4DC' 
        },
        crosshair: { 
            mode: 1 
        },
    });
    return chart;
};

export default function IndexChart({ data }) {
    const chartContainerRef = useRef(null);
    const chartRef = useRef(null);
    const seriesRef = useRef({});

    // This effect handles the INITIALIZATION and CLEANUP of the chart.
    // It runs only when the component mounts.
    useEffect(() => {
        if (!chartContainerRef.current) return;

        const chart = createMyChart(chartContainerRef.current);
        chartRef.current = chart;

        // Add all the series to the chart
        seriesRef.current.candlestickSeries = chart.addCandlestickSeries({ 
            upColor: '#26a69a', 
            downColor: '#ef5350', 
            borderVisible: false, 
            wickUpColor: '#26a69a', 
            wickDownColor: '#ef5350' 
        });
        seriesRef.current.wmaSeries = chart.addLineSeries({ color: '#2962FF', lineWidth: 2, title: 'WMA', priceLineVisible: false, lastValueVisible: false });
        seriesRef.current.smaSeries = chart.addLineSeries({ color: '#FF6D00', lineWidth: 2, title: 'SMA', priceLineVisible: false, lastValueVisible: false });
        seriesRef.current.rsiSeries = chart.addLineSeries({ color: 'rgba(136, 132, 216, 0.7)', lineWidth: 2, title: 'RSI', priceScaleId: 'rsi', priceLineVisible: false, lastValueVisible: false });
        seriesRef.current.rsiSmaSeries = chart.addLineSeries({ color: '#f5a623', lineWidth: 2, title: 'RSI SMA', priceScaleId: 'rsi', priceLineVisible: false, lastValueVisible: false });

        // Create a separate pane for the RSI
        chart.priceScale('rsi').applyOptions({
            scaleMargins: { top: 0.8, bottom: 0 },
            height: 225
        });

        // This is the crucial cleanup function. It will be called when the component unmounts.
        return () => {
            if (chartRef.current) {
                chartRef.current.remove();
                chartRef.current = null;
            }
            seriesRef.current = {};
        };
    }, []);

    // This effect handles DATA UPDATES.
    // It runs whenever the `data` prop changes.
    useEffect(() => {
        if (!chartRef.current || Object.keys(seriesRef.current).length === 0 || !data) {
            return; // Exit if the chart isn't ready or there's no data
        }

        // Pass the new data to each respective chart series
        if (data.candles) seriesRef.current.candlestickSeries.setData(data.candles);
        if (data.wma) seriesRef.current.wmaSeries.setData(data.wma);
        if (data.sma) seriesRef.current.smaSeries.setData(data.sma);
        if (data.rsi) seriesRef.current.rsiSeries.setData(data.rsi);
        if (data.rsi_sma) seriesRef.current.rsiSmaSeries.setData(data.rsi_sma);
        
        // Fit the content to the screen after the first data load
        if(data.candles && data.candles.length > 0) {
            chartRef.current.timeScale();
        }

    }, [data]);

    // This effect handles WINDOW RESIZING.
    useEffect(() => {
        const handleResize = () => {
            if (chartRef.current && chartContainerRef.current) {
                chartRef.current.resize(chartContainerRef.current.clientWidth, chartContainerRef.current.clientHeight);
            }
        };
        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    }, []);

    return (
        <Paper 
            elevation={3} 
            sx={{ 
                p: 2, 
                height: '450px', 
                display: 'flex', 
                flexDirection: 'column' 
            }}
        >
            <Box 
                sx={{ 
                    display: 'flex', 
                    flexWrap: 'wrap', 
                    gap: 2, 
                    mb: 1, 
                    alignItems: 'center', 
                    flexShrink: 0 
                }}
            >
                <Typography variant="body2">Index Chart</Typography>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                    <Box sx={{ width: 12, height: 12, backgroundColor: '#FF6D00' }} />
                    <Typography variant="caption">SMA</Typography>
                </Box>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                    <Box sx={{ width: 12, height: 12, backgroundColor: '#2962FF' }} />
                    <Typography variant="caption">WMA</Typography>
                </Box>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                    <Box sx={{ width: 12, height: 12, backgroundColor: 'rgba(136, 132, 216, 0.7)' }} />
                    <Typography variant="caption">RSI</Typography>
                </Box>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                    <Box sx={{ width: 12, height: 12, backgroundColor: '#f5a623' }} />
                    <Typography variant="caption">RSI SMA</Typography>
                </Box>
            </Box>

            <Box sx={{ width: '100%', flexGrow: 1, position: 'relative' }}>
                {!data && (
                    <Box 
                        sx={{ 
                            position: 'absolute', 
                            top: 0, 
                            left: 0, 
                            right: 0, 
                            bottom: 0, 
                            display: 'flex', 
                            alignItems: 'center', 
                            justifyContent: 'center' 
                        }}
                    >
                        <CircularProgress />
                    </Box>
                )}
                <Box ref={chartContainerRef} sx={{ width: '100%', height: '100%' }} />
            </Box>
        </Paper>
    );
}