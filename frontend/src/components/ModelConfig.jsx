import { useState, useEffect } from 'react';
import { api } from '../api';
import './ModelConfig.css';

export default function ModelConfig({ onConfigChange }) {
  const [isExpanded, setIsExpanded] = useState(true);
  const [config, setConfig] = useState(null);
  const [modelsHealth, setModelsHealth] = useState(null);
  const [isCheckingHealth, setIsCheckingHealth] = useState(false);

  // Selected models and their personas
  const [selectedModels, setSelectedModels] = useState([]);
  const [modelPersonas, setModelPersonas] = useState({});
  const [primeMinister, setPrimeMinister] = useState('');

  // Load config on mount
  useEffect(() => {
    loadConfig();
  }, []);

  // Notify parent of config changes
  useEffect(() => {
    if (selectedModels.length > 0) {
      onConfigChange({
        ministry_models: selectedModels,
        model_personas: modelPersonas,
        prime_minister: primeMinister || null,
      });
    } else {
      onConfigChange(null);
    }
  }, [selectedModels, modelPersonas, primeMinister]);

  const loadConfig = async () => {
    try {
      const cfg = await api.getConfig();
      setConfig(cfg);
      // Initialize with defaults
      setSelectedModels(cfg.default_ministry_models || []);
      setModelPersonas(cfg.default_model_personas || {});
      setPrimeMinister(cfg.default_prime_minister || '');
    } catch (error) {
      console.error('Failed to load config:', error);
    }
  };

  const checkHealth = async () => {
    setIsCheckingHealth(true);
    try {
      const health = await api.checkModelsHealth();
      setModelsHealth(health);
    } catch (error) {
      console.error('Failed to check models health:', error);
    }
    setIsCheckingHealth(false);
  };

  const toggleModel = (model) => {
    setSelectedModels((prev) => {
      if (prev.includes(model)) {
        // Remove model and its persona
        const newPersonas = { ...modelPersonas };
        delete newPersonas[model];
        setModelPersonas(newPersonas);
        // If this was the prime minister, clear it
        if (primeMinister === model) {
          setPrimeMinister('');
        }
        return prev.filter((m) => m !== model);
      } else {
        return [...prev, model];
      }
    });
  };

  const setPersona = (model, personaId) => {
    setModelPersonas((prev) => ({
      ...prev,
      [model]: personaId,
    }));
  };

  const getModelHealth = (model) => {
    if (!modelsHealth) return null;
    return modelsHealth.models.find((m) => m.model === model);
  };

  const getModelDisplayName = (model) => {
    // Extract just the model name from provider/model format
    const parts = model.split('/');
    return parts[parts.length - 1];
  };

  if (!config) {
    return (
      <div className="model-config">
        <div className="model-config-header" onClick={() => setIsExpanded(!isExpanded)}>
          <span className="collapse-icon">{isExpanded ? '▼' : '▶'}</span>
          <h3>Ministry Configuration</h3>
        </div>
        <div className="model-config-loading">Loading...</div>
      </div>
    );
  }

  return (
    <div className="model-config">
      <div className="model-config-header" onClick={() => setIsExpanded(!isExpanded)}>
        <span className="collapse-icon">{isExpanded ? '▼' : '▶'}</span>
        <h3>Ministry Configuration</h3>
        <span className="model-count">{selectedModels.length} models</span>
      </div>

      {isExpanded && (
        <div className="model-config-content">
          <div className="health-check-row">
            <button
              className="refresh-health-btn"
              onClick={checkHealth}
              disabled={isCheckingHealth}
            >
              {isCheckingHealth ? 'Checking...' : 'Check Health'}
            </button>
            {modelsHealth && (
              <span className="health-summary">
                {modelsHealth.healthy_count}/{modelsHealth.total_count} healthy
              </span>
            )}
          </div>

          <div className="models-list">
            {config.available_models.map((model) => {
              const health = getModelHealth(model);
              const isSelected = selectedModels.includes(model);
              const isHealthy = health ? health.healthy : null;

              return (
                <div key={model} className={`model-item ${isSelected ? 'selected' : ''}`}>
                  <div className="model-row">
                    <label className="model-checkbox">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => toggleModel(model)}
                        disabled={isHealthy === false}
                      />
                      <span className={`model-name ${isHealthy === false ? 'unhealthy' : ''}`}>
                        {getModelDisplayName(model)}
                      </span>
                      {isHealthy === true && <span className="health-indicator healthy">●</span>}
                      {isHealthy === false && <span className="health-indicator unhealthy">●</span>}
                    </label>

                    {isSelected && (
                      <select
                        className="persona-select"
                        value={modelPersonas[model] || ''}
                        onChange={(e) => setPersona(model, e.target.value)}
                      >
                        <option value="">Default Persona</option>
                        {Object.entries(config.available_personas).map(([id, persona]) => (
                          <option key={id} value={id}>
                            {persona.name}
                          </option>
                        ))}
                      </select>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          <div className="prime-minister-section">
            <label className="pm-label">Prime Minister (Synthesizer):</label>
            <select
              className="pm-select"
              value={primeMinister}
              onChange={(e) => setPrimeMinister(e.target.value)}
            >
              <option value="">Use Default</option>
              {selectedModels.map((model) => (
                <option key={model} value={model}>
                  {getModelDisplayName(model)}
                </option>
              ))}
            </select>
          </div>
        </div>
      )}
    </div>
  );
}
