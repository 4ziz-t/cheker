import { formatDateTime, formatRelative } from '../utils/format.js';

export default function EventItem({ event, compact, showTags }) {
  return (
    <li className={`event event--${event.level}`}>
      <span className="event__bar" />
      <div className="event__body">
        <div className="event__head">
          <span className="event__title">{event.title}</span>
          <time className="event__time" title={formatDateTime(event.created_at)}>
            {compact ? formatRelative(event.created_at) : formatDateTime(event.created_at)}
          </time>
        </div>
        {event.message && <p className="event__msg">{event.message}</p>}
        {showTags && (event.domain || event.node || event.ip) && (
          <div className="event__tags">
            {event.domain && <span className="tag">{event.domain}</span>}
            {event.node && <span className="tag">нода: {event.node}</span>}
            {event.ip && <span className="tag mono">{event.ip}</span>}
          </div>
        )}
      </div>
    </li>
  );
}
