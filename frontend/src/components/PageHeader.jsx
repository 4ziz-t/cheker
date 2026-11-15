export default function PageHeader({ title, subtitle, actions, back }) {
  return (
    <header className="page-header">
      <div className="page-header__main">
        {back}
        <div>
          <h1>{title}</h1>
          {subtitle && <p className="page-header__sub">{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="page-header__actions">{actions}</div>}
    </header>
  );
}

export function EmptyState({ title, text, action }) {
  return (
    <div className="empty">
      <p className="empty__title">{title}</p>
      {text && <p className="empty__text">{text}</p>}
      {action}
    </div>
  );
}

export function ErrorBox({ error, onRetry }) {
  if (!error) return null;
  return (
    <div className="alert alert--bad">
      <span>{error.message || String(error)}</span>
      {onRetry && (
        <button type="button" className="btn btn--sm btn--ghost" onClick={onRetry}>
          Повторить
        </button>
      )}
    </div>
  );
}
