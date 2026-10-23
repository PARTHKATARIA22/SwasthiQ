import React from 'react';

export default function ScreenQueue({
  stats,
  handoffs,
  onSelectConversation,
  onResolveHandoff,
  onResetQueue,
}) {
  return (
    <div className="queue-screen">
      {/* Page Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Handoff Queue</h1>
          <p className="page-subtitle">Sunrise Clinic, Dehradun — conversations the agent escalated</p>
        </div>
        <div className="badge-open">
          {stats?.still_open ?? handoffs.filter((h) => !h.resolved).length} OPEN
        </div>
      </div>

      {/* 4 Metric Cards */}
      <div className="metrics-grid">
        <div className="metric-card">
          <span className="metric-label">CONVERSATIONS</span>
          <span className="metric-value">{stats?.conversations ?? 37}</span>
          <span className="metric-sub">today</span>
        </div>

        <div className="metric-card">
          <span className="metric-label">COMPLETED BY AGENT</span>
          <span className="metric-value">{stats?.completed_by_agent ?? 31}</span>
          <span className="metric-sub">{stats?.completed_pct ?? '84%'}</span>
        </div>

        <div className="metric-card">
          <span className="metric-label">ESCALATED</span>
          <span className="metric-value">{stats?.escalated ?? 6}</span>
          <span className="metric-sub blue">
            {stats?.still_open ?? 4} still open
          </span>
        </div>

        <div className="metric-card">
          <span className="metric-label">URGENT</span>
          <span className="metric-value">{stats?.urgent ?? 1}</span>
          <span className="metric-sub red">
            {stats?.urgent_label ?? 'clinical, unresolved'}
          </span>
        </div>
      </div>

      {/* Open Handoffs Card */}
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Open handoffs</h2>
        </div>

        <table className="handoff-table">
          <thead>
            <tr>
              <th style={{ width: '15%' }}>CONVERSATION</th>
              <th style={{ width: '40%' }}>CALLER SAID</th>
              <th style={{ width: '22%' }}>REASON</th>
              <th style={{ width: '11%' }}>TIME</th>
              <th style={{ width: '12%', textAlign: 'right' }}></th>
            </tr>
          </thead>
          <tbody>
            {handoffs.length === 0 ? (
              <tr>
                <td colSpan={5} style={{ textAlign: 'center', padding: '32px', color: '#9ca3af' }}>
                  No open handoffs remaining in the queue.
                </td>
              </tr>
            ) : (
              handoffs.map((item, index) => {
                const isPrimary = item.is_primary_action && !item.resolved;
                return (
                  <tr
                    key={item.id}
                    onClick={() => onSelectConversation(item.id)}
                    title="Click to view conversation details and transcript"
                  >
                    <td className="cell-conversation">{item.id}</td>
                    <td className="cell-caller-said">{item.caller_said}</td>
                    <td>
                      <span className={`reason-badge ${item.reason_type}`}>
                        {item.reason_badge}
                      </span>
                    </td>
                    <td className="cell-time">{item.time}</td>
                    <td style={{ textAlign: 'right' }}>
                      {item.resolved ? (
                        <span className="btn-resolved-state">
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                            <polyline points="20 6 9 17 4 12" />
                          </svg>
                          Resolved
                        </span>
                      ) : (
                        <button
                          type="button"
                          className={isPrimary ? 'btn-resolve-primary' : 'btn-resolve-secondary'}
                          onClick={(e) => {
                            e.stopPropagation();
                            onResolveHandoff(item.id);
                          }}
                        >
                          Resolve
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Demo helper toolbar */}
      <div className="demo-bar">
        <span>Click any row to inspect conversation details, transcript, and grounded tool calls.</span>
        <button type="button" className="btn-reset" onClick={onResetQueue}>
          Reset Demo Queue
        </button>
      </div>
    </div>
  );
}
