import Stage0 from './Stage0';
import TraderResult from './TraderResult';
import MasterSynthesis from './MasterSynthesis';
import './TradingResults.css';

const TRADER_COLORS = [
  '#4a90e2', '#e2725b', '#38a169', '#d69e2e',
  '#805ad5', '#dd6b20', '#319795', '#e53e3e',
];

export default function TradingResults({ liveResults, currentSession, isRunning }) {
  // Determine data source: live streaming results or loaded session
  const hasLive = liveResults !== null;
  const hasSession = currentSession !== null;

  if (!hasLive && !hasSession) {
    return (
      <div className="trading-results">
        <div className="trading-empty-state">
          <h2>Trading Advisory</h2>
          <p>Select traders and configure settings to begin analysis.</p>
          <p>Each selected trader will run through the full 4-stage Ministry pipeline.</p>
        </div>
      </div>
    );
  }

  // --- Render from live results (streaming) ---
  if (hasLive) {
    const traderEntries = Object.values(liveResults.traders || {});

    return (
      <div className="trading-results">
        <div className="trading-results-scroll">
          {/* Stage 0 */}
          {(liveResults.stage0Loading || liveResults.stage0) && (
            <div className="trading-stage0-block">
              {liveResults.stage0Loading && !liveResults.stage0 && (
                <div className="stage-loading">
                  <div className="spinner" />
                  <span>Researching market conditions...</span>
                </div>
              )}
              <Stage0 briefing={liveResults.stage0} />
            </div>
          )}

          {/* Individual traders */}
          {traderEntries.map((trader, idx) => (
            <TraderResult
              key={trader.trader_id}
              traderId={trader.trader_id}
              traderName={trader.trader_name}
              stage1={trader.stage1}
              stage2={trader.stage2}
              stage3={trader.stage3}
              metadata={trader.metadata}
              loading={trader.loading}
              color={TRADER_COLORS[idx % TRADER_COLORS.length]}
            />
          ))}

          {/* Master Synthesis */}
          {liveResults.master && (
            <MasterSynthesis
              stage1={liveResults.master.stage1}
              stage2={liveResults.master.stage2}
              stage3={liveResults.master.stage3}
              metadata={liveResults.master.metadata}
              loading={liveResults.master.loading}
            />
          )}

          {isRunning && traderEntries.length === 0 && !liveResults.stage0Loading && (
            <div className="stage-loading">
              <div className="spinner" />
              <span>Starting analysis...</span>
            </div>
          )}
        </div>
      </div>
    );
  }

  // --- Render from saved session ---
  if (hasSession) {
    return (
      <div className="trading-results">
        <div className="trading-results-scroll">
          <div className="session-header-block">
            <h2>{currentSession.title}</h2>
            <span className={`session-badge ${currentSession.status}`}>
              {currentSession.status}
            </span>
          </div>

          {/* Stage 0 from first analysis */}
          {currentSession.analyses?.[0]?.stage0 && (
            <Stage0 briefing={currentSession.analyses[0].stage0} />
          )}

          {/* Individual trader analyses */}
          {currentSession.analyses?.map((analysis, idx) => (
            <TraderResult
              key={analysis.trader_id}
              traderId={analysis.trader_id}
              traderName={analysis.trader_name}
              stage1={analysis.stage1}
              stage2={analysis.stage2}
              stage3={analysis.stage3}
              metadata={analysis.metadata}
              loading={null}
              color={TRADER_COLORS[idx % TRADER_COLORS.length]}
            />
          ))}

          {/* Master Synthesis */}
          {currentSession.master_synthesis && (
            <MasterSynthesis
              stage1={currentSession.master_synthesis.stage1}
              stage2={currentSession.master_synthesis.stage2}
              stage3={currentSession.master_synthesis.stage3}
              metadata={currentSession.master_synthesis.metadata}
              loading={null}
            />
          )}
        </div>
      </div>
    );
  }

  return null;
}
