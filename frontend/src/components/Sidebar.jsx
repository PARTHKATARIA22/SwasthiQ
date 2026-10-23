import React from 'react';

export default function Sidebar({ currentScreen, onSelectQueue }) {
  return (
    <aside className="sidebar">
      {/* 1. Top Circle Ring */}
      <button className="sidebar-icon-btn" title="SwasthiQ Clinic" aria-label="Home">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="12" r="9" />
        </svg>
      </button>

      {/* 2. Grid Dashboard Icon */}
      <button className="sidebar-icon-btn" title="Dashboard" aria-label="Dashboard">
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <rect x="3" y="3" width="7" height="7" rx="1" />
          <rect x="14" y="3" width="7" height="7" rx="1" />
          <rect x="14" y="14" width="7" height="7" rx="1" />
          <rect x="3" y="14" width="7" height="7" rx="1" />
        </svg>
      </button>

      {/* 3. Active Handoff Queue Icon (Blue circle-dot in rounded square) */}
      <button
        className={`sidebar-icon-btn ${currentScreen === 'queue' ? 'active' : ''}`}
        onClick={onSelectQueue}
        title="Handoff Queue"
        aria-label="Handoff Queue"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
          <circle cx="12" cy="12" r="8" />
          <circle cx="12" cy="12" r="2.5" fill="currentColor" />
        </svg>
      </button>

      {/* 4. Patients / Users Icon */}
      <button className="sidebar-icon-btn" title="Patients" aria-label="Patients">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" />
          <circle cx="12" cy="7" r="4" />
        </svg>
      </button>

      {/* 5. Clock / History Icon */}
      <button className="sidebar-icon-btn" title="Call History" aria-label="History">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="12" r="9" />
          <polyline points="12 7 12 12 15 15" />
        </svg>
      </button>

      {/* 6. Settings / Sliders Icon */}
      <button className="sidebar-icon-btn" title="Settings" aria-label="Settings">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <line x1="4" y1="21" x2="4" y2="14" />
          <line x1="4" y1="10" x2="4" y2="3" />
          <line x1="12" y1="21" x2="12" y2="12" />
          <line x1="12" y1="8" x2="12" y2="3" />
          <line x1="20" y1="21" x2="20" y2="16" />
          <line x1="20" y1="12" x2="20" y2="3" />
          <line x1="1" y1="14" x2="7" y2="14" />
          <line x1="9" y1="8" x2="15" y2="8" />
          <line x1="17" y1="16" x2="23" y2="16" />
        </svg>
      </button>
    </aside>
  );
}
