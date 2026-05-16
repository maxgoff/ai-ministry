import { useState, useEffect, useRef } from 'react';
import { api } from '../api';
import './GlobalSettings.css';

export default function GlobalSettings({ settings, onChange }) {
  const [isExpanded, setIsExpanded] = useState(false);
  const saveTimeoutRef = useRef(null);

  const updateField = (key, value) => {
    const updated = { ...settings, [key]: value };
    onChange(updated);

    // Debounced auto-save
    if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
    saveTimeoutRef.current = setTimeout(() => {
      api.saveTradingSettings(updated).catch(err =>
        console.error('Failed to save settings:', err)
      );
    }, 1000);
  };

  useEffect(() => {
    return () => {
      if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
    };
  }, []);

  return (
    <div className="global-settings">
      <div className="global-settings-header" onClick={() => setIsExpanded(!isExpanded)}>
        <span className="collapse-icon">{isExpanded ? '▼' : '▶'}</span>
        <h3>Global Settings</h3>
      </div>

      {isExpanded && (
        <div className="global-settings-content">
          <div className="gs-field">
            <label>Watchlist</label>
            <textarea
              value={settings.watchlist || ''}
              onChange={(e) => updateField('watchlist', e.target.value)}
              placeholder="AAPL, TSLA, NVDA, SPY..."
              rows={2}
            />
          </div>

          <div className="gs-field">
            <label>Account Size</label>
            <input
              type="text"
              value={settings.account_size || ''}
              onChange={(e) => updateField('account_size', e.target.value)}
              placeholder="$100,000"
            />
          </div>

          <div className="gs-field">
            <label>Open Positions</label>
            <textarea
              value={settings.open_positions || ''}
              onChange={(e) => updateField('open_positions', e.target.value)}
              placeholder="AAPL 100 shares, TSLA 50 shares..."
              rows={2}
            />
          </div>

          <div className="gs-field">
            <label>Risk Tolerance</label>
            <select
              value={settings.risk_tolerance || ''}
              onChange={(e) => updateField('risk_tolerance', e.target.value)}
            >
              <option value="">Select...</option>
              <option value="CONSERVATIVE">Conservative</option>
              <option value="MODERATE">Moderate</option>
              <option value="AGGRESSIVE">Aggressive</option>
            </select>
          </div>

          <div className="gs-field">
            <label>Risk Per Trade</label>
            <input
              type="text"
              value={settings.risk_per_trade || ''}
              onChange={(e) => updateField('risk_per_trade', e.target.value)}
              placeholder="1% or $1,000"
            />
          </div>

          <div className="gs-field">
            <label>Trading Style</label>
            <select
              value={settings.trading_style || ''}
              onChange={(e) => updateField('trading_style', e.target.value)}
            >
              <option value="">Select...</option>
              <option value="DAY TRADER">Day Trader</option>
              <option value="SWING TRADER">Swing Trader</option>
              <option value="POSITION TRADER">Position Trader</option>
            </select>
          </div>

          <div className="gs-field">
            <label>Markets</label>
            <select
              value={settings.markets || ''}
              onChange={(e) => updateField('markets', e.target.value)}
            >
              <option value="">Select...</option>
              <option value="US EQUITIES">US Equities</option>
              <option value="OPTIONS">Options</option>
              <option value="CRYPTO">Crypto</option>
              <option value="FOREX">Forex</option>
              <option value="FUTURES">Futures</option>
            </select>
          </div>
        </div>
      )}
    </div>
  );
}
