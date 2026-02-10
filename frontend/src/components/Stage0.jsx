import ReactMarkdown from 'react-markdown';
import './Stage0.css';

export default function Stage0({ briefing }) {
  if (!briefing) {
    return null;
  }

  const modelName = briefing.model
    ? briefing.model.split('/').pop() || briefing.model
    : 'Researcher';

  return (
    <div className="stage stage0">
      <h3 className="stage-title">Stage 0: Research Briefing</h3>

      <div className="research-meta">
        <span className="researcher-model">{modelName}</span>
        {briefing.date && <span className="research-date">{briefing.date}</span>}
      </div>

      {briefing.key_facts && (
        <div className="research-section">
          <h4 className="research-section-title">Key Facts</h4>
          <div className="research-content markdown-content">
            <ReactMarkdown>{briefing.key_facts}</ReactMarkdown>
          </div>
        </div>
      )}

      {briefing.summary && (
        <div className="research-section">
          <h4 className="research-section-title">Summary</h4>
          <div className="research-content markdown-content">
            <ReactMarkdown>{briefing.summary}</ReactMarkdown>
          </div>
        </div>
      )}

      {briefing.citations && briefing.citations.length > 0 && (
        <div className="research-section">
          <h4 className="research-section-title">Sources</h4>
          <div className="research-sources">
            {briefing.citations.map((citation, i) => (
              citation.url && (
                <a
                  key={i}
                  href={citation.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="source-link"
                >
                  {citation.title || citation.url}
                </a>
              )
            ))}
          </div>
        </div>
      )}

      {briefing.search_queries && briefing.search_queries.length > 0 && (
        <div className="research-queries">
          {briefing.search_queries.map((query, i) => (
            <span key={i} className="search-query-tag">{query}</span>
          ))}
        </div>
      )}
    </div>
  );
}
