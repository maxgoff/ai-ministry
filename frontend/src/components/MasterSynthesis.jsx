import Stage1 from './Stage1';
import Stage2 from './Stage2';
import Stage3 from './Stage3';
import './MasterSynthesis.css';

export default function MasterSynthesis({
  stage1,
  stage2,
  stage3,
  metadata,
  loading,
}) {
  const labelToModel = metadata?.label_to_model || null;
  const aggregateRankings = metadata?.aggregate_rankings || null;

  return (
    <div className="master-synthesis">
      <div className="master-synthesis-header">
        <h3>Master Synthesis: Daily Trading Brief</h3>
      </div>

      {loading?.stage1 && !stage1 && (
        <div className="stage-loading">
          <div className="spinner" />
          <span>Master trader collecting responses...</span>
        </div>
      )}
      <Stage1 responses={stage1} />

      {loading?.stage2 && !stage2 && (
        <div className="stage-loading">
          <div className="spinner" />
          <span>Master trader peer ranking...</span>
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
          <span>Synthesizing final trading brief...</span>
        </div>
      )}
      <Stage3 finalResponse={stage3} />
    </div>
  );
}
