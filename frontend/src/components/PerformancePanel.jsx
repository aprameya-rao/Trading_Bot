import React from 'react';
import { Paper, Typography, Box } from '@mui/material';

const PnlText = ({ children, color }) => (
    <Typography sx={{ color, fontWeight: 'bold' }}>{children}</Typography>
);

export default function PerformancePanel({ data }) {
    const netPnlColor = data.netPnl > 0 ? 'success.main' : data.netPnl < 0 ? 'error.main' : 'text.primary';
    
    return (
        <Paper elevation={3} sx={{ p: 2 }}>
            <Typography variant="body2" sx={{ mb: 1 }}>Daily Performance</Typography>
            <Box sx={{ pl: 1 }}>
                <PnlText color={netPnlColor}>Net P&L: ₹ {data.netPnl.toFixed(2)}</PnlText>
                <PnlText color="success.main">Gross Profit: ₹ {data.grossProfit.toFixed(2)}</PnlText>
                <PnlText color="error.main">Gross Loss: ₹ {data.grossLoss.toFixed(2)}</PnlText>
                <Typography>Wins: {data.wins} | Losses: {data.losses}</Typography>
            </Box>
        </Paper>
    );
}