import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { makeApi, resolveTransport } from './api/context';
import './styles.css';

const root = document.getElementById('root');
if (!root) throw new Error('Root element is missing');

resolveTransport().then(transport => {
  createRoot(root).render(
    <StrictMode>
      <App api={makeApi(transport)} />
    </StrictMode>,
  );
});
