import { useState } from 'react';
import './TraderSelector.css';

export default function TraderSelector({
  templates,
  selectedTraders,
  onSelectedTradersChange,
  traderFields,
  onTraderFieldsChange,
  globalSettings,
}) {
  const [isExpanded, setIsExpanded] = useState(true);

  const toggleTrader = (traderId) => {
    if (selectedTraders.includes(traderId)) {
      onSelectedTradersChange(selectedTraders.filter(t => t !== traderId));
      const newFields = { ...traderFields };
      delete newFields[traderId];
      onTraderFieldsChange(newFields);
    } else {
      onSelectedTradersChange([...selectedTraders, traderId]);
    }
  };

  const updateTraderField = (traderId, fieldKey, value) => {
    onTraderFieldsChange({
      ...traderFields,
      [traderId]: {
        ...(traderFields[traderId] || {}),
        [fieldKey]: value,
      },
    });
  };

  const getFieldValue = (template, fieldKey) => {
    // Check per-trader override first
    const override = traderFields[template.id]?.[fieldKey];
    if (override) return override;

    // Then check global settings via field map
    const globalKey = template.global_field_map?.[fieldKey];
    if (globalKey && globalSettings[globalKey]) return globalSettings[globalKey];

    return '';
  };

  return (
    <div className="trader-selector">
      <div className="trader-selector-header" onClick={() => setIsExpanded(!isExpanded)}>
        <span className="collapse-icon">{isExpanded ? '▼' : '▶'}</span>
        <h3>Traders</h3>
        <span className="trader-count">{selectedTraders.length} selected</span>
      </div>

      {isExpanded && (
        <div className="trader-selector-content">
          {templates.map((template) => {
            const isSelected = selectedTraders.includes(template.id);
            return (
              <div key={template.id} className={`trader-card ${isSelected ? 'selected' : ''}`}>
                <label className="trader-checkbox">
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => toggleTrader(template.id)}
                  />
                  <div className="trader-info">
                    <span className="trader-name">{template.name}</span>
                    <span className="trader-desc">{template.description}</span>
                  </div>
                </label>

                {isSelected && template.fields && template.fields.length > 0 && (
                  <div className="trader-fields">
                    {template.fields.map((field) => (
                      <div key={field.key} className="trader-field">
                        <label>{field.label}</label>
                        {field.type === 'textarea' ? (
                          <textarea
                            value={getFieldValue(template, field.key)}
                            onChange={(e) => updateTraderField(template.id, field.key, e.target.value)}
                            placeholder={field.placeholder}
                            rows={2}
                          />
                        ) : field.type === 'select' ? (
                          <select
                            value={getFieldValue(template, field.key)}
                            onChange={(e) => updateTraderField(template.id, field.key, e.target.value)}
                          >
                            <option value="">Select...</option>
                            {field.options.map(opt => (
                              <option key={opt} value={opt}>{opt}</option>
                            ))}
                          </select>
                        ) : (
                          <input
                            type="text"
                            value={getFieldValue(template, field.key)}
                            onChange={(e) => updateTraderField(template.id, field.key, e.target.value)}
                            placeholder={field.placeholder}
                          />
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
