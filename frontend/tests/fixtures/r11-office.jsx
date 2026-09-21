// Synthetic fixture only. Run Vite with VITE_API_PROXY_TARGET=http://127.0.0.1:5293.
import React from 'react';
import { createRoot } from 'react-dom/client';
import { GenOfficeFrame } from '../../src/features/medical-writing/protocol-workbench/office/GenOfficeFrame';
import { createProtocolWorkspaceApi } from '../../src/features/medical-writing/protocol-workbench/protocolWorkspaceApi.mjs';
const response = await fetch('/api/r11-fixture');
if (!response.ok) throw new Error('Start the isolated r11 fixture service first.');
const props = await response.json();
createRoot(document.getElementById('root')).render(<GenOfficeFrame {...props} api={createProtocolWorkspaceApi()}/>);
