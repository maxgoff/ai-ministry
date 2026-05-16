import GlobalSettings from './GlobalSettings';
import TraderSelector from './TraderSelector';
import ModelConfig from './ModelConfig';
import './TradingSidebar.css';

export default function TradingSidebar({
  templates,
  globalSettings,
  onGlobalSettingsChange,
  selectedTraders,
  onSelectedTradersChange,
  traderFields,
  onTraderFieldsChange,
  onMinistryConfigChange,
  sessions,
  currentSessionId,
  onSelectSession,
  onRunAnalysis,
  isRunning,
  user,
  onLogout,
}) {
  return (
    <div className="trading-sidebar">
      <div className="trading-sidebar-header">
        <h1>Trading Advisory</h1>
        <button
          className="run-analysis-btn"
          onClick={onRunAnalysis}
          disabled={isRunning || selectedTraders.length === 0}
        >
          {isRunning ? 'Running...' : 'Run Analysis'}
        </button>
      </div>

      <div className="trading-sidebar-scroll">
        <GlobalSettings
          settings={globalSettings}
          onChange={onGlobalSettingsChange}
        />

        <TraderSelector
          templates={templates}
          selectedTraders={selectedTraders}
          onSelectedTradersChange={onSelectedTradersChange}
          traderFields={traderFields}
          onTraderFieldsChange={onTraderFieldsChange}
          globalSettings={globalSettings}
        />

        <ModelConfig onConfigChange={onMinistryConfigChange} />

        <div className="trading-sessions-section">
          <div className="trading-sessions-header">Session History</div>
          <div className="trading-session-list">
            {sessions.length === 0 ? (
              <div className="no-sessions">No sessions yet</div>
            ) : (
              sessions.map((session) => (
                <div
                  key={session.id}
                  className={`trading-session-item ${session.id === currentSessionId ? 'active' : ''}`}
                  onClick={() => onSelectSession(session.id)}
                >
                  <div className="trading-session-title">{session.title}</div>
                  <div className="trading-session-meta">
                    {session.selected_traders.length} traders
                    <span className={`session-status ${session.status}`}>
                      {session.status}
                    </span>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {user && (
        <div className="trading-user-section">
          <div className="trading-user-info">
            <div className="trading-user-email" title={user.email}>
              {user.email}
            </div>
          </div>
          <button className="trading-logout-btn" onClick={onLogout}>
            Logout
          </button>
        </div>
      )}
    </div>
  );
}
