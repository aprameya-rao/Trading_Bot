import React, { useState } from 'react';
import { Paper, Box, Tabs, Tab, TableContainer, Table, TableHead, TableRow, TableCell, TableBody } from '@mui/material';

function TabPanel(props) {
    const { children, value, index, ...other } = props;
    return (
        <div role="tabpanel" hidden={value !== index} {...other}>
            {value === index && <Box sx={{ height: '100%' }}>{children}</Box>}
        </div>
    );
}

export default function LogTabs({ debugLogs, tradeHistory }) {
    const [value, setValue] = useState(0);
    const handleChange = (event, newValue) => setValue(newValue);

    const debugCols = ["Time", "Source", "Message"];
    const tradeCols = ["Symbol", "Entry Time", "Reason", "Entry", "Exit", "P&L", "Exit Reason"];

    return (
        <Paper elevation={3} sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
            <Box sx={{ borderBottom: 1, borderColor: 'divider' }}>
                <Tabs value={value} onChange={handleChange}>
                    <Tab label="Debug Log" />
                    <Tab label="Trade History" />
                </Tabs>
            </Box>
            <TabPanel value={value} index={0}>
                <TableContainer sx={{flexGrow: 1}}>
                    <Table stickyHeader size="small">
                        <TableHead><TableRow>{debugCols.map(c => <TableCell key={c}>{c}</TableCell>)}</TableRow></TableHead>
                        <TableBody>
                            {debugLogs.map((log, i) => (
                                <TableRow key={i}>
                                    <TableCell>{log.time}</TableCell>
                                    <TableCell>{log.source}</TableCell>
                                    <TableCell>{log.message}</TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                </TableContainer>
            </TabPanel>
            <TabPanel value={value} index={1}>
                 <TableContainer sx={{flexGrow: 1}}>
                    <Table stickyHeader size="small">
                        <TableHead><TableRow>{tradeCols.map(c => <TableCell key={c}>{c}</TableCell>)}</TableRow></TableHead>
                        <TableBody>
                            {tradeHistory.map((trade, i) => (
                                <TableRow key={i}>
                                    {trade.map((item, j) => <TableCell key={j}>{item}</TableCell>)}
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                </TableContainer>
            </TabPanel>
        </Paper>
    );
}