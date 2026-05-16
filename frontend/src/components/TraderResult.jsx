import Stage1 from './Stage1';
import Stage2 from './Stage2';
import Stage3 from './Stage3';
import './TraderResult.css';

export default function TraderResult({
  traderId,
  traderName,
  stage1,
  stage2,
  stage3,
  metadata,
  loading,
  color,
}) {
  const labelToModel = metadata?.label_to_model || null;
  const aggregateRankings = metadata?.aggregate_rankings || null;

  return (
    <div className="trader-result" style={{ borderLeftColor: color }}>
      <div className="trader-result-header">
        <span className="trader-result-dot" style={{ background: color }} />
        <h3>{traderName}</h3>
      </div>

      {loading?.stage1 && !stage1 && (
        <div className="stage-loading">
          <div className="spinner" />
          <span>Collecting individual responses...</span>
        </div>
      )}
      <Stage1 responses={stage1} />

      {loading?.stage2 && !stage2 && (
        <div className="stage-loading">
          <div className="spinner" />
          <span>Peer ranking responses...</span>
        </div>
      )}
      <Stage2
        rankings={stage2}
        labelToModel={labelToModel}
        aggregateRankings={aggregateRankings}
      />

      {loading?.stage3 && !stage3 && (
        <div className="stage-loading">
          <div className="spinner" />
          <span>Synthesizing final answer...</span>
        </div>
      )}
      <Stage3 finalResponse={stage3} />
    </div>
  );
}
