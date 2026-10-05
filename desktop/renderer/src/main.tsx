import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import '@fontsource-variable/instrument-sans/wght.css';
import '@fontsource/instrument-serif/latin-400.css';
import './styles.css';
import './workbench.css';

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>);
