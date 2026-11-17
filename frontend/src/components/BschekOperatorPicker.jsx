import { useMemo } from 'react';

const GROUPS = [
  {
    dpi: 'off',
    title: 'Без Белого списка',
    hint: 'Обычный мобильный интернет — по ним видно бан ТСПУ.',
  },
  {
    dpi: 'on',
    title: 'С Белым списком (БС)',
    hint: 'Оператор пропускает только разрешённые адреса — зарубежный IP почти всегда «недоступен».',
  },
];

const opKey = (operator, dpi) => `${operator}|*|${dpi}`;
const allKey = (dpi) => `*|*|${dpi}`;

/** Сколько живых единиц покрывает набор ключей (= число списаний за одну проверку). */
export function countCovered(units, keys) {
  const match = (u, key) => {
    const [op = '*', reg = '*', bs = '*'] = key.split('|');
    const okOp = !op || op === '*' || op === u.operator;
    const okReg =
      !reg || reg === '*' || reg.toLowerCase() === String(u.region).toLowerCase() || reg === u.region_code;
    const okBs = !bs || bs === '*' || bs === u.dpi;
    return okOp && okReg && okBs;
  };
  return (units || []).filter((u) => u.probeable && keys.some((k) => match(u, k))).length;
}

/**
 * Выбор операторов bschekbot в двух группах: без Белого списка и с ним.
 * value — список ключей единиц ("mts|*|off", "*|*|on", "beeline|цфо|off"…).
 */
export default function BschekOperatorPicker({ units, value, onChange, compact }) {
  const selected = value || [];

  const groups = useMemo(() => {
    const res = { on: {}, off: {} };
    (units || []).forEach((u) => {
      const g = res[u.dpi];
      if (!g) return;
      const item = g[u.operator] || { operator: u.operator, name: u.name || u.operator, live: 0, regions: [] };
      if (u.probeable) {
        item.live += 1;
        item.regions.push(u.region);
      }
      g[u.operator] = item;
    });
    const sort = (list) => list.sort((a, b) => b.live - a.live || a.name.localeCompare(b.name));
    return { on: sort(Object.values(res.on)), off: sort(Object.values(res.off)) };
  }, [units]);

  const update = (list) => onChange([...new Set(list)]);

  const toggleOperator = (operator, dpi) => {
    const key = opKey(operator, dpi);
    update(selected.includes(key) ? selected.filter((k) => k !== key) : [...selected, key]);
  };

  const toggleAll = (dpi) => {
    const key = allKey(dpi);
    if (selected.includes(key)) {
      update(selected.filter((k) => k !== key));
    } else {
      // «все операторы группы» заменяют отдельных операторов этой группы
      update([...selected.filter((k) => !(k.endsWith(`|${dpi}`) && k.split('|')[1] === '*')), key]);
    }
  };

  return (
    <div className={`bs-picker ${compact ? 'bs-picker--compact' : ''}`}>
      {GROUPS.map((g) => {
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
                Все
              </button>
            </div>
            {!compact && <span className="field__hint">{g.hint}</span>}
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
    </div>
  );
}
