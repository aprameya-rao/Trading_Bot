import React, { useState } from 'react';
import { Paper, Typography, Box, TextField, Button, TableContainer, Table, TableHead, TableRow, TableCell, TableBody } from '@mui/material';
import { useSnackbar } from 'notistack';

// The 'sendWebSocketMessage' function is now passed in as a prop
export default function UOAPanel({ list, sendSocketMessage }) {
    const { enqueueSnackbar } = useSnackbar();
    const [strike, setStrike] = useState('');

    const handleAddWatchlist = (side) => {
        const strikeNum = parseInt(strike, 10);
        if (!strike || isNaN(strikeNum)) {
            enqueueSnackbar('Please enter a valid numeric strike price.', { variant: 'warning' });
            return;
        }

        const message = {
            type: 'add_to_watchlist',
            payload: {
                strike: strikeNum,
                side: side
            }
        };
        
        // This now calls the function passed down from App.jsx
        sendSocketMessage(message); 
        
        enqueueSnackbar(`Sent request to watch ${strikeNum} ${side}.`, { variant: 'info' });
        setStrike(''); // Clear the input field
    };

    return (
        <Paper elevation={3} sx={{ p: 2 }}>
            <Typography variant="body2">UOA Watchlist</Typography>
            <Box sx={{ display: 'flex', gap: 1, my: 1 }}>
                <TextField 
                    size="small" 
                    label="Strike" 
                    value={strike}
                    onChange={(e) => setStrike(e.target.value)}
                    onKeyPress={(e) => { if (e.key === 'Enter') handleAddWatchlist('CE'); }}
                />
                <Button variant="outlined" size="small" onClick={() => handleAddWatchlist('CE')}>Watch CE</Button>
                <Button variant="outlined" size="small" onClick={() => handleAddWatchlist('PE')}>Watch PE</Button>
            </Box>
            <TableContainer>
                <Table size="small">
                    <TableHead>
                        <TableRow>
                            <TableCell>Symbol</TableCell>
                            <TableCell>Type</TableCell>
                            <TableCell>Strike</TableCell>
                        </TableRow>
                    </TableHead>
                    <TableBody>
                        {list.map((item, index) => (
                            <TableRow key={index}>
                                <TableCell>{item.symbol}</TableCell>
                                <TableCell>{item.type}</TableCell>
                                <TableCell>{item.strike}</TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </TableContainer>
        </Paper>
    );
}