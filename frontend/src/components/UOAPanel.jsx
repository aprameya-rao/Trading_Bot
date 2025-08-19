import React from 'react';
import { Paper, Typography, Box, TextField, Button, TableContainer, Table, TableHead, TableRow, TableCell, TableBody } from '@mui/material';

export default function UOAPanel({ list }) {
    return (
        <Paper elevation={3} sx={{ p: 2 }}>
            <Typography variant="body2">UOA Watchlist</Typography>
            <Box sx={{ display: 'flex', gap: 1, my: 1 }}>
                <TextField size="small" label="Strike" />
                <Button variant="outlined" size="small">Watch CE</Button>
                <Button variant="outlined" size="small">Watch PE</Button>
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