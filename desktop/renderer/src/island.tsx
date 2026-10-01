import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { Island } from './components/Island';
import './island.css';

createRoot(document.getElementById('island-root')!).render(<StrictMode><Island /></StrictMode>);
