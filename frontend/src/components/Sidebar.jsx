import { useState } from 'react';
import { api } from '../api';
import ModelConfig from './ModelConfig';
import './Sidebar.css';

export default function Sidebar({
  conversations,
  currentConversationId,
  onSelectConversation,
  onNewConversation,
  onMinistryConfigChange,
  user,
  onLogout,
}) {
  const [exporting, setExporting] = useState(null);

  const handleExportMarkdown = async () => {
    if (!currentConversationId) return;
    setExporting('md');
    try {
      await api.exportMarkdown(currentConversationId);
    } catch (error) {
      alert('Export failed: ' + error.message);
    } finally {
      setExporting(null);
    }
  };

  const handleExportPDF = async () => {
    if (!currentConversationId) return;
    setExporting('pdf');
    try {
      await api.exportPDF(currentConversationId);
    } catch (error) {
      alert('Export failed: ' + error.message);
    } finally {
      setExporting(null);
    }
  };

  const currentConversation = conversations.find(c => c.id === currentConversationId);
  const hasMessages = currentConversation?.message_count > 0;

  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <h1>AI Ministry</h1>
        <button className="new-conversation-btn" onClick={onNewConversation}>
          + New Conversation
        </button>
      </div>

      {hasMessages && (
        <div className="export-section">
          <div className="export-header">Export Conversation</div>
          <div className="export-buttons">
            <button
              className="export-btn"
              onClick={handleExportMarkdown}
              disabled={exporting !== null}
            >
              {exporting === 'md' ? 'Exporting...' : 'Markdown'}
            </button>
            <button
              className="export-btn"
              onClick={handleExportPDF}
              disabled={exporting !== null}
            >
              {exporting === 'pdf' ? 'Exporting...' : 'PDF'}
            </button>
          </div>
        </div>
      )}

      <ModelConfig onConfigChange={onMinistryConfigChange} />

      <div className="conversations-section">
        <div className="conversations-header">Conversations</div>
        <div className="conversation-list">
          {conversations.length === 0 ? (
            <div className="no-conversations">No conversations yet</div>
          ) : (
            conversations.map((conv) => (
              <div
                key={conv.id}
                className={`conversation-item ${
                  conv.id === currentConversationId ? 'active' : ''
                }`}
                onClick={() => onSelectConversation(conv.id)}
              >
                <div className="conversation-title">
                  {conv.title || 'New Conversation'}
                </div>
                <div className="conversation-meta">
                  {conv.message_count} messages
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {user && (
        <div className="user-section">
          <div className="user-info">
            <div className="user-email" title={user.email}>
              {user.email}
            </div>
          </div>
          <button className="logout-btn" onClick={onLogout}>
            Logout
          </button>
        </div>
      )}
    </div>
  );
}
