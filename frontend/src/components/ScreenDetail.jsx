import React from 'react';

export default function ScreenDetail({ conversation, onBack }) {
  if (!conversation) {
    return (
      <div className="transcript-card" style={{ textAlign: 'center', padding: '40px' }}>
        Loading conversation details...
      </div>
    );
  }

  const { id, subtitle, top_badge, abandoned_notice, transcript = [], outcome = {} } = conversation;

  return (
    <div className="detail-screen">
      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">
            <button
              type="button"
              className="back-btn"
              onClick={onBack}
              title="Back to Handoff Queue"
              aria-label="Back to Handoff Queue"
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <line x1="19" y1="12" x2="5" y2="12" />
                <polyline points="12 19 5 12 12 5" />
              </svg>
            </button>
            <span>Conversation {id}</span>
          </h1>
          <p className="page-subtitle">{subtitle}</p>
        </div>
        <div className="badge-escalated-clinical">
          {top_badge}
        </div>
      </div>

      {/* 2-Column Asymmetric Grid */}
      <div className="detail-grid">
        {/* Left Column: Transcript and tool calls */}
        <div className="transcript-card">
          <h2 className="card-title">Transcript and tool calls</h2>

          <div className="transcript-list">
            {transcript.map((item, idx) => {
              const role = item.role?.toUpperCase();
              return (
                <div key={idx} className="transcript-row">
                  <div className="gutter-role">{role}</div>
                  <div className="bubble-wrapper" style={{ flex: 1 }}>
                    {role === 'TOOL' ? (
                      <div className="bubble bubble-tool">
                        <div className="tool-code">{item.code}</div>
                        {item.result && <div className="tool-result">{item.result}</div>}
                      </div>
                    ) : role === 'CALLER' ? (
                      <div className="bubble bubble-caller">
                        {item.text}
                      </div>
                    ) : (
                      <div className="bubble bubble-agent">
                        {item.text}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Abandoned Notice Banner */}
          {abandoned_notice && (
            <div className="banner-abandoned">
              {abandoned_notice}
            </div>
          )}
        </div>

        {/* Right Column: Outcome */}
        <div className="outcome-card">
          <h2 className="card-title">Outcome</h2>

          <div className="outcome-list">
            <div className="outcome-row">
              <span className="outcome-key">terminal_state</span>
              <span className="outcome-val">{outcome.terminal_state}</span>
            </div>

            <div className="outcome-row">
              <span className="outcome-key">escalation_reason</span>
              <span className="outcome-val">{outcome.escalation_reason}</span>
            </div>

            <div className="outcome-row">
              <span className="outcome-key">patient_id</span>
              <span className="outcome-val">{outcome.patient_id}</span>
            </div>

            <div className="outcome-row">
              <span className="outcome-key">appointment_id</span>
              <span className="outcome-val">{outcome.appointment_id}</span>
            </div>

            <div className="outcome-row">
              <span className="outcome-key">tool_calls</span>
              <span className="outcome-val">{outcome.tool_calls}</span>
            </div>

            <div className="outcome-row">
              <span className="outcome-key">turns</span>
              <span className="outcome-val">{outcome.turns}</span>
            </div>

            <div className="outcome-row">
              <span className="outcome-key">tokens</span>
              <span className="outcome-val">{outcome.tokens}</span>
            </div>

            <div className="outcome-row" style={{ borderBottom: 'none' }}>
              <span className="outcome-key">latency</span>
              <span className="outcome-val">{outcome.latency}</span>
            </div>
          </div>

          {/* Determinism */}
          <div className="determinism-section">
            <div className="determinism-label">DETERMINISM</div>
            <div className="determinism-row">
              <span>{outcome.determinism_text || 'Same terminal state across 3 runs.'}</span>
              <span className="badge-stable">{outcome.determinism_badge || 'STABLE'}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
