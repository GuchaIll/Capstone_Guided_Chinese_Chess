import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import App from './App.tsx'
import AgentsPage from './pages/AgentsPage.tsx'
import HardwarePage from './pages/HardwarePage.tsx'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />} />
        <Route path="/agents" element={<AgentsPage />} />
        <Route path="/hardware" element={<HardwarePage />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
)
