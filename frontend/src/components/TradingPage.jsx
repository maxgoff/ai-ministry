import { useState, useEffect, useRef } from 'react';
import TradingSidebar from './TradingSidebar';
import TradingResults from './TradingResults';
import { api } from '../api';
import './TradingPage.css';

export default function TradingPage({ user, onLogout }) {
  const [templates, setTemplates] = useState([]);
  const [globalSettings, setGlobalSettings] = useState({});
  const [selectedTraders, setSelectedTraders] = useState([]);
  const [traderFields, setTraderFields] = useState({});
  const [sessions, setSessions] = useState([]);
  const [currentSessionId, setCurrentSessionId] = useState(null);
  const [currentSession, setCurrentSession] = useState(null);
  const [isRunning, setIsRunning] = useState(false);
  const [liveResults, setLiveResults] = useState(null);
  const ministryConfigRef = useRef(null);

  // Load templates, settings, and sessions on mount
  useEffect(() => {
    loadTemplates();
    loadSettings();
    loadSessions();
  }, []);

  const loadTemplates = async () => {
    try {
      const t = await api.getTradingTemplates();
      setTemplates(t);
    } catch (err) {
      console.error('Failed to load templates:', err);
    }
  };

  const loadSettings = async () => {
    try {
      const s = await api.getTradingSettings();
      setGlobalSettings(s);
    } catch (err) {
      if (err.message === 'Not authenticated') { onLogout(); return; }
      console.error('Failed to load settings:', err);
    }
  };

  const loadSessions = async () => {
    try {
      const s = await api.listTradingSessions();
      setSessions(s);
    } catch (err) {
      if (err.message === 'Not authenticated') { onLogout(); return; }
      console.error('Failed to load sessions:', err);
    }
  };

  const loadSession = async (sessionId) => {
    try {
      const s = await api.getTradingSession(sessionId);
      setCurrentSession(s);
      setCurrentSessionId(sessionId);
      setLiveResults(null);
    } catch (err) {
      if (err.message === 'Not authenticated') { onLogout(); return; }
      console.error('Failed to load session:', err);
    }
  };

  const handleMinistryConfigChange = (config) => {
    ministryConfigRef.current = config;
  };

  const handleGlobalSettingsChange = (settings) => {
    setGlobalSettings(settings);
  };

  const runAnalysis = async () => {
    if (selectedTraders.length === 0 || isRunning) return;

    setIsRunning(true);
    setCurrentSession(null);
    setCurrentSessionId(null);
    setLiveResults({
      stage0: null,
      traders: {},
      master: null,
      stage0Loading: false,
    });

    const request = {
      selected_traders: selectedTraders,
      trader_fields: traderFields,
      global_settings: globalSettings,
    };
    if (ministryConfigRef.current) {
      request.ministry_config = ministryConfigRef.current;
    }

    try {
      await api.runTradingSession(request, (eventType, event) => {
        switch (eventType) {
          case 'session_created':
            setCurrentSessionId(event.session_id);
            break;

          case 'stage0_start':
            setLiveResults(prev => ({ ...prev, stage0Loading: true }));
            break;

          case 'stage0_complete':
            setLiveResults(prev => ({ ...prev, stage0: event.data, stage0Loading: false }));
            break;

          case 'trader_start':
            setLiveResults(prev => ({
              ...prev,
              traders: {
                ...prev.traders,
                [event.trader_id]: {
                  trader_id: event.trader_id,
                  trader_name: event.trader_name,
                  stage1: null, stage2: null, stage3: null,
                  metadata: null,
                  loading: { stage1: false, stage2: false, stage3: false },
                },
              },
            }));
            break;

          case 'trader_stage1_start':
            setLiveResults(prev => {
              const traders = { ...prev.traders };
              if (traders[event.trader_id]) {
                traders[event.trader_id] = { ...traders[event.trader_id], loading: { ...traders[event.trader_id].loading, stage1: true } };
              }
              return { ...prev, traders };
            });
            break;

          case 'trader_stage1_complete':
            setLiveResults(prev => {
              const traders = { ...prev.traders };
              if (traders[event.trader_id]) {
                traders[event.trader_id] = { ...traders[event.trader_id], stage1: event.data, loading: { ...traders[event.trader_id].loading, stage1: false } };
              }
              return { ...prev, traders };
            });
            break;

          case 'trader_stage2_start':
            setLiveResults(prev => {
              const traders = { ...prev.traders };
              if (traders[event.trader_id]) {
                traders[event.trader_id] = { ...traders[event.trader_id], loading: { ...traders[event.trader_id].loading, stage2: true } };
              }
              return { ...prev, traders };
            });
            break;

          case 'trader_stage2_complete':
            setLiveResults(prev => {
              const traders = { ...prev.traders };
              if (traders[event.trader_id]) {
                traders[event.trader_id] = { ...traders[event.trader_id], stage2: event.data, metadata: event.metadata, loading: { ...traders[event.trader_id].loading, stage2: false } };
              }
              return { ...prev, traders };
            });
            break;

          case 'trader_stage3_start':
            setLiveResults(prev => {
              const traders = { ...prev.traders };
              if (traders[event.trader_id]) {
                traders[event.trader_id] = { ...traders[event.trader_id], loading: { ...traders[event.trader_id].loading, stage3: true } };
              }
              return { ...prev, traders };
            });
            break;

          case 'trader_stage3_complete':
            setLiveResults(prev => {
              const traders = { ...prev.traders };
              if (traders[event.trader_id]) {
                traders[event.trader_id] = { ...traders[event.trader_id], stage3: event.data, loading: { ...traders[event.trader_id].loading, stage3: false } };
              }
              return { ...prev, traders };
            });
            break;

          case 'master_start':
            setLiveResults(prev => ({
              ...prev,
              master: {
                stage1: null, stage2: null, stage3: null, metadata: null,
                loading: { stage1: false, stage2: false, stage3: false },
              },
            }));
            break;

          case 'master_stage1_start':
            setLiveResults(prev => ({
              ...prev,
              master: { ...prev.master, loading: { ...prev.master.loading, stage1: true } },
            }));
            break;

          case 'master_stage1_complete':
            setLiveResults(prev => ({
              ...prev,
              master: { ...prev.master, stage1: event.data, loading: { ...prev.master.loading, stage1: false } },
            }));
            break;

          case 'master_stage2_start':
            setLiveResults(prev => ({
              ...prev,
              master: { ...prev.master, loading: { ...prev.master.loading, stage2: true } },
            }));
            break;

          case 'master_stage2_complete':
            setLiveResults(prev => ({
              ...prev,
              master: { ...prev.master, stage2: event.data, metadata: event.metadata, loading: { ...prev.master.loading, stage2: false } },
            }));
            break;

          case 'master_stage3_start':
            setLiveResults(prev => ({
              ...prev,
              master: { ...prev.master, loading: { ...prev.master.loading, stage3: true } },
            }));
            break;

          case 'master_stage3_complete':
            setLiveResults(prev => ({
              ...prev,
              master: { ...prev.master, stage3: event.data, loading: { ...prev.master.loading, stage3: false } },
            }));
            break;

          case 'complete':
            setIsRunning(false);
            loadSessions();
            break;

          case 'error':
            console.error('Trading session error:', event.message);
            setIsRunning(false);
            break;

          default:
            console.log('Unknown trading event:', eventType);
        }
      });
    } catch (err) {
      console.error('Trading session failed:', err);
      setIsRunning(false);
    }
  };

  return (
    <div className="trading-page">
      <TradingSidebar
        templates={templates}
        globalSettings={globalSettings}
        onGlobalSettingsChange={handleGlobalSettingsChange}
        selectedTraders={selectedTraders}
        onSelectedTradersChange={setSelectedTraders}
        traderFields={traderFields}
        onTraderFieldsChange={setTraderFields}
        onMinistryConfigChange={handleMinistryConfigChange}
        sessions={sessions}
        currentSessionId={currentSessionId}
        onSelectSession={loadSession}
        onRunAnalysis={runAnalysis}
        isRunning={isRunning}
        user={user}
        onLogout={onLogout}
      />
      <TradingResults
        liveResults={liveResults}
        currentSession={currentSession}
        isRunning={isRunning}
      />
    </div>
  );
}
