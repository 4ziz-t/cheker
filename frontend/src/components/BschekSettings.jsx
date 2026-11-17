import { useEffect, useState } from 'react';
import { settingsApi } from '../api/index.js';
import Spinner from './Spinner.jsx';

const DPI = [
  { value: 'off', label: 'Только без Белого списка (рекомендую для поиска бана)' },
  { value: 'on', label: 'Только с Белым списком' },
  { value: 'any', label: 'Любые' },
];

export default function BschekSettings({ form, set }) {
  const [units, setUnits] = useState(null);
  const [error, setError] = useState('');
  const [text, setText] = useState((form.bschek_units || []).join(', '));

  useEffect(() => {
    settingsApi
      .bschekUnits()
      .then(setUnits)
      .catch((e) => setError(e.message));
  }, []);

  // поле с селекторами синхронизируется с настройкой
  useEffect(() => {
    setText((form.bschek_units || []).join(', '));
  }, [form.bschek_units]);

  const selected = form.bschek_units || [];
  const apply = (value) =>
    set(
      'bschek_units',
      value
        .split(/[,\s]+/)
        .map((s) => s.trim())
        .filter(Boolean),
    );
  const toggle = (key) =>
    set('bschek_units', selected.includes(key) ? selected.filter((k) => k !== key) : [...selected, key]);

  const dpi = form.bschek_dpi || 'off';
  const visible = (units || []).filter((u) => u.probeable && (dpi === 'any' || u.dpi === dpi));

  return (
    <div className="form">
      <label className="field">
        <span className="field__label">Белый список (БС)</span>
        <select className="input select select--wide" value={dpi} onChange={(e) => set('bschek_dpi', e.target.value)}>
          {DPI.map((d) => (
            <option key={d.value} value={d.value}>
              {d.label}
            </option>
          ))}
        </select>
        <span className="field__hint">
          С включённым Белым списком оператор режет почти все зарубежные IP — для поиска бана нужны единицы без БС.
        </span>
      </label>

      <label className="field">
        <span className="field__label">Единицы (оператор|округ|БС)</span>
        <input
          className="input mono"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onBlur={() => apply(text)}
          placeholder="*|цфо|off"
          spellCheck={false}
        />
        <span className="field__hint">
          Через запятую. Можно селекторы: «*|цфо|off» — все операторы ЦФО без БС, «mts» — МТС во всех округах.
          Каждая подошедшая единица — отдельное списание.
        </span>
      </label>

      <div className="field">
        <span className="field__label">
          Доступные сейчас единицы <span className="muted">· нажмите, чтобы добавить</span>
        </span>
        {error && <span className="field__hint text-warn">Список недоступен: {error}</span>}
        {!units && !error && <Spinner size={16} />}
        {units && (
          <div className="city-chips">
            {visible.map((u) => (
              <button
                key={u.op_key}
                type="button"
                className={`chip chip--sm ${selected.includes(u.op_key) ? 'is-active' : ''}`}
                onClick={() => toggle(u.op_key)}
                title={u.op_key}
              >
                {u.name || u.operator} · {u.region}
                {u.dpi === 'on' && <span className="chip__count">БС</span>}
              </button>
            ))}
            {!visible.length && <span className="field__hint">Нет доступных единиц под этот фильтр</span>}
          </div>
        )}
      </div>

      <label className="field">
        <span className="field__label">Бан, если порт недоступен у</span>
        <div className="input-suffix">
          <input
            className="input"
            type="number"
            min={1}
            max={100}
            value={form.bschek_fail_percent ?? ''}
            onChange={(e) => set('bschek_fail_percent', e.target.value === '' ? '' : Number(e.target.value))}
          />
          <span>% единиц и более</span>
        </div>
      </label>
    </div>
  );
}
