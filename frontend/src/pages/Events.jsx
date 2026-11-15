import { useCallback, useEffect, useState } from 'react';
import { eventsApi } from '../api/index.js';
import EventItem from '../components/EventItem.jsx';
import { IconSearch } from '../components/Icons.jsx';
import PageHeader, { EmptyState, ErrorBox } from '../components/PageHeader.jsx';
import Spinner from '../components/Spinner.jsx';
import { LEVEL_LABEL } from '../utils/format.js';
import '../styles/events.css';

const PAGE = 50;

export default function Events() {
  const [types, setTypes] = useState({});
  const [type, setType] = useState('');
  const [level, setLevel] = useState('');
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    eventsApi.types().then(setTypes).catch(() => {});
  }, []);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search.trim()), 350);
    return () => clearTimeout(t);
  }, [search]);

  const load = useCallback(
    async (offset = 0) => {
      setLoading(true);
      try {
        const res = await eventsApi.list({ type, level, search: debounced, limit: PAGE, offset });
        setItems((prev) => (offset ? [...prev, ...res.items] : res.items));
        setTotal(res.total);
        setError(null);
      } catch (e) {
        setError(e);
      } finally {
        setLoading(false);
      }
    },
    [type, level, debounced],
  );

  useEffect(() => {
    load(0);
  }, [load]);

  return (
    <div className="page">
      <PageHeader title="События" subtitle={`Найдено: ${total}`} />

      <div className="toolbar toolbar--events">
        <div className="search">
          <IconSearch size={18} />
          <input
            className="input"
            placeholder="Домен, IP, нода…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <select className="input select" value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">Все типы</option>
          {Object.entries(types).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
        <select className="input select" value={level} onChange={(e) => setLevel(e.target.value)}>
          <option value="">Любой уровень</option>
          {Object.entries(LEVEL_LABEL).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </div>

      <ErrorBox error={error} onRetry={() => load(0)} />

      {!items.length && loading ? (
        <div className="page-loading">
          <Spinner size={28} />
        </div>
      ) : !items.length ? (
        <EmptyState title="Событий не найдено" />
      ) : (
        <section className="card panel">
          <ul className="event-list">
            {items.map((e) => (
              <EventItem key={e.id} event={e} showTags />
            ))}
          </ul>
          {items.length < total && (
            <div className="row-center">
              <button type="button" className="btn btn--ghost" disabled={loading} onClick={() => load(items.length)}>
                {loading ? <Spinner size={16} /> : null}
                <span>Показать ещё</span>
              </button>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
