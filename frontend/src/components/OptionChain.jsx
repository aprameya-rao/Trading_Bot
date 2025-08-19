import React from 'react';
import { Paper, Typography, TableContainer, Table, TableHead, TableBody, TableRow, TableCell } from '@mui/material';

export default function OptionChain({ data, indexPrice }) {
    const getRowStyle = (strike) => {
        const diff = Math.abs(strike - indexPrice);
        if (diff < 100) return { backgroundColor: 'rgba(255, 255, 0, 0.1)' }; // ATM
        return {};
    };
    
    return (
        <Paper elevation={3} sx={{ p: 2 }}>
            <Typography variant="body2" sx={{ mb: 1 }}>Option Chain</Typography>
            <TableContainer sx={{ maxHeight: 250 }}>
                <Table stickyHeader size="small">
                    <TableHead>
                        <TableRow>
                            <TableCell align="center" sx={{color: 'success.main'}}>LTP (CE)</TableCell>
                            <TableCell align="center">Strike</TableCell>
                            <TableCell align="center" sx={{color: 'error.main'}}>LTP (PE)</TableCell>
                        </TableRow>
                    </TableHead>
                    <TableBody>
                        {data.map((row) => (
                            <TableRow key={row.strike} sx={getRowStyle(row.strike)}>
                                <TableCell align="center" sx={{backgroundColor: row.strike < indexPrice ? 'rgba(0, 255, 0, 0.05)' : 'rgba(255, 0, 0, 0.05)'}}>
                                    {row.ce_ltp}
                                </TableCell>
                                <TableCell align="center" sx={{ fontWeight: 'bold' }}>{row.strike}</TableCell>
                                <TableCell align="center" sx={{backgroundColor: row.strike > indexPrice ? 'rgba(0, 255, 0, 0.05)' : 'rgba(255, 0, 0, 0.05)'}}>
                                    {row.pe_ltp}
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </TableContainer>
        </Paper>
    );
}