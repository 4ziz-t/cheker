import { useSearchParams } from 'react-router-dom';
import { IconX } from './Icons.jsx';

/** ?only=id1,id2&title=… — показать только перечисленные записи (переход с дашборда). */
export function useOnlyFilter() {
  const [params, setParams] = useSearchParams();
  const raw = params.get('only');
  const ids = raw ? raw.split(',').filter(Boolean) : null;
  return {
    only: ids ? new Set(ids) : null,
    title: params.get('title') || '',
    clear: () => setParams({}, { replace: true }),
  };
}

export function onlyLink(path, ids, title) {
  const q = new URLSearchParams({ only: ids.join(','), title });
  return `${path}?${q.toString()}`;
}

export default function OnlyBanner({ title, count, onClear }) {
  return (
    <div className="only-banner">
      <span className="only-banner__text">
        Показаны только: <b>{title || 'выбранные'}</b>
        <span className="muted"> · {count}</span>
      </span>
      <button type="button" className="btn btn--sm btn--ghost" onClick={onClear}>
        <IconX size={15} />
        <span>Показать все</span>
      </button>
    </div>
  );
}
