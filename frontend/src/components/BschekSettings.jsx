import { useEffect, useMemo, useState } from 'react';
import { settingsApi } from '../api/index.js';
import Spinner from './Spinner.jsx';

const GROUPS = [
  {
    dpi: 'off',
    title: 'Без Белого списка',
    hint: 'Обычный мобильный интернет — по ним видно бан ТСПУ. Рекомендую.',
  },
  {
    dpi: 'on',
    title: 'С Белым списком (БС)',
    hint: 'Оператор пропускает только разрешённые адреса — зарубежный IP почти всегда будет «недоступен».',
  },
];

/** Ключ оператора во всех округах для группы: "mts|*|off" */
const opKey = (operator, dpi) => `${operator}|*|${dpi}`;

export default function BschekSettings({ form, set }) {
  const [units, setUnits] = useState(null);
  const [error, setError] = useState('');
  const [text, setText] = useState('');
  const selected = form.bschek_units || [];

  useEffect(() => {
    settingsApi
      .bschekUnits()
      .then(setUnits)
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    setText(selected.join(', '));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.bschek_units]);

  // операторы по группам: {off: [{operator, name, total, live, regions}], on: [...]}
  const groups = useMemo(() => {
    const res = { on: {}, off: {} };
    (units || []).forEach((u) => {
      const g = res[u.dpi];
      if (!g) return;
      const item = g[u.operator] || { operator: u.operator, name: u.name || u.operator, total: 0, live: 0, regions: [] };
      item.total += 1;
      if (u.probeable) {
        item.live += 1;
        item.regions.push(u.region);
      }
      g[u.operator] = item;
    });
    return {
      on: Object.values(res.on).sort((a, b) => b.live - a.live),
      off: Object.values(res.off).sort((a, b) => b.live - a.live),
    };
  }, [units]);

  const update = (list) => {
    const uniq = [...new Set(list)];
    set('bschek_units', uniq);
  };

  const toggleOperator = (operator, dpi) => {
    const key = opKey(operator, dpi);
    update(selected.includes(key) ? selected.filter((k) => k !== key) : [...selected, key]);
  };

  const allKey = (dpi) => `*|*|${dpi}`;
  const toggleAll = (dpi) => {
    const key = allKey(dpi);
    if (selected.includes(key)) {
      update(selected.filter((k) => k !== key));
    } else {
      // «все операторы» заменяет отдельных операторов этой группы
      update([...selected.filter((k) => !k.endsWith(`|${dpi}`) || k.split('|')[1] !== '*'), key]);
    }
  };

  const applyText = () =>
    update(
      text
        .split(/[,\s]+/)
        .map((s) => s.trim())
        .filter(Boolean),
    );

  const liveUnits = (units || []).filter((u) => u.probeable);
  const coveredCount = (() => {
    // сколько живых единиц покрывает текущий выбор (оценка списаний за одну проверку)
    const match = (u, key) => {
      const [op = '*', reg = '*', bs = '*'] = key.split('|');
      const okOp = !op || op === '*' || op === u.operator;
      const okReg =
        !reg || reg === '*' || reg.toLowerCase() === String(u.region).toLowerCase() || reg === u.region_code;
      const okBs = !bs || bs === '*' || bs === u.dpi;
      return okOp && okReg && okBs;
    };
    return liveUnits.filter((u) => selected.some((k) => match(u, k))).length;
  })();

  return (
    <div className="form">
      {error && <span className="field__hint text-warn">Список операторов недоступен: {error}</span>}
      {!units && !error && <Spinner size={16} />}

      {units &&
        GROUPS.map((g) => {
          const ops = groups[g.dpi];
          const allSelected = selected.includes(allKey(g.dpi));
          return (
            <div key={g.dpi} className={`bs-group bs-group--${g.dpi}`}>
              <div className="bs-group__head">
                <span className="field__label">{g.title}</span>
                <button
                  type="button"
                  className={`chip chip--sm ${allSelected ? 'is-active' : ''}`}
                  onClick={() => toggleAll(g.dpi)}
                >
                  Все операторы
                </button>
              </div>
              <span className="field__hint">{g.hint}</span>
              {ops.length === 0 ? (
                <span className="field__hint">Сейчас нет операторов в этой группе</span>
              ) : (
                <div className="city-chips">
                  {ops.map((o) => {
                    const active = allSelected || selected.includes(opKey(o.operator, g.dpi));
                    return (
                      <button
                        key={o.operator}
                        type="button"
                        disabled={allSelected}
                        className={`chip chip--sm ${active ? 'is-active' : ''} ${o.live ? '' : 'is-stale'}`}
                        title={o.live ? `Округа: ${o.regions.join(', ')}` : 'Сейчас недоступен'}
                        onClick={() => toggleOperator(o.operator, g.dpi)}
                      >
                        <span className={`dot ${o.live ? 'dot--ok' : 'dot--off'}`} />
                        {o.name}
                        <span className="chip__count">{o.live}</span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}

      <p className="field__hint">
        Цифра у оператора — сколько его округов сейчас доступно. Каждый округ — отдельное списание. Под текущий выбор
        подходит единиц: <b>{coveredCount}</b>
        {!selected.length && ' — ничего не выбрано, проверка не пойдёт'}.
      </p>

      <details className="bs-advanced">
        <summary>Точная настройка (ключи оператор|округ|БС)</summary>
        <label className="field">
          <input
            className="input mono"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onBlur={applyText}
            placeholder="mts|*|off, beeline|цфо|on"
            spellCheck={false}
          />
          <span className="field__hint">
            Через запятую. Например «mts|цфо|off» — только МТС в ЦФО без БС, «*|*|on» — все операторы с БС.
          </span>
        </label>
      </details>

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
