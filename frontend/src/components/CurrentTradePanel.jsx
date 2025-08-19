import React from 'react';
import { Paper, Typography, Box, Grid, Button } from '@mui/material';

export default function CurrentTradePanel({ trade }) {
    if (!trade) {
        return (
            <Paper elevation={3} sx={{ p: 2 }}>
                <Typography variant="body2" sx={{ mb: 1 }}>Current Trade</Typography>
                <Typography sx={{ fontWeight: 'bold' }}>STATUS: No Active Trade</Typography>
            </Paper>
        );
    }
    const pnlColor = trade.pnl > 0 ? 'success.main' : trade.pnl < 0 ? 'error.main' : 'text.primary';
    return (
        <Paper elevation={3} sx={{ p: 2 }}>
            <Typography variant="body2" sx={{ mb: 1 }}>Current Trade</Typography>
            <Typography sx={{ fontWeight: 'bold', mb: 2 }}>{trade.symbol} @ {trade.entry_price.toFixed(2)}</Typography>
            <Grid container spacing={1}>
                <Grid item xs={6}><Typography sx={{color: pnlColor}}>P&L: ₹ {trade.pnl.toFixed(2)}</Typography></Grid>
                <Grid item xs={6}><Typography sx={{color: pnlColor}}>Profit: {trade.profit_pct.toFixed(2)} %</Typography></Grid>
                <Grid item xs={6}><Typography>Trail SL: {trade.trail_sl.toFixed(2)}</Typography></Grid>
                <Grid item xs={6}><Typography>Max Price: {trade.max_price.toFixed(2)}</Typography></Grid>
            </Grid>
            <Button fullWidth variant="contained" color="error" sx={{ mt: 2 }}>Manual Exit Trade</Button>
        </Paper>
    );
}