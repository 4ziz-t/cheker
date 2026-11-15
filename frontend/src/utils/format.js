export const DOMAIN_STATUS = {
  ok: { label: 'В порядке', tone: 'ok' },
  blocked: { label: 'IP в бане', tone: 'bad' },
  no_ips: { label: 'Нет свободных IP', tone: 'bad' },
  error: { label: 'Ошибка', tone: 'warn' },
  no_record: { label: 'Нет A-записи', tone: 'warn' },
  unknown: { label: 'Не проверен', tone: 'muted' },
};

export const LEVEL_LABEL = {
  info: 'Инфо',
  success: 'Успех',
  warning: 'Внимание',
  error: 'Ошибка',
};

export function ipState(ip) {
  if (ip.is_blocked === true) return { label: 'В бане', tone: 'bad' };
  if (ip.is_blocked === false) return { label: 'Доступен', tone: 'ok' };
  if (ip.last_error) return { label: 'Ошибка проверки', tone: 'warn' };
  return { label: 'Не проверен', tone: 'muted' };
}

function plural(n, one, few, many) {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
}

export function formatDateTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function formatRelative(iso) {
  if (!iso) return '—';
  const diff = (new Date(iso).getTime() - Date.now()) / 1000;
  const abs = Math.abs(diff);
  const future = diff > 0;
  let text;
  if (abs < 45) return future ? 'через несколько секунд' : 'только что';
  if (abs < 3600) {
    const m = Math.round(abs / 60);
    text = `${m} ${plural(m, 'минуту', 'минуты', 'минут')}`;
  } else if (abs < 86400) {
    const h = Math.round(abs / 3600);
    text = `${h} ${plural(h, 'час', 'часа', 'часов')}`;
  } else {
    const d = Math.round(abs / 86400);
    text = `${d} ${plural(d, 'день', 'дня', 'дней')}`;
  }
  return future ? `через ${text}` : `${text} назад`;
}

export function formatDuration(iso) {
  if (!iso) return '';
  const sec = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const parts = [];
  if (d) parts.push(`${d} д`);
  if (h) parts.push(`${h} ч`);
  if (m || !parts.length) parts.push(`${m} мин`);
  return parts.join(' ');
}

export function pluralize(n, one, few, many) {
  return `${n} ${plural(n, one, few, many)}`;
}

const IPV4 = /^(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}$/;

export function isIPv4(value) {
  return IPV4.test(String(value).trim());
}

/** Разбирает текст со списком IP (через пробел, запятую или с новой строки). */
export function parseIpList(text) {
  const items = String(text)
    .split(/[\s,;]+/)
    .map((s) => s.trim())
    .filter(Boolean);
  const valid = [];
  const invalid = [];
  items.forEach((ip) => {
    if (!isIPv4(ip)) invalid.push(ip);
    else if (!valid.includes(ip)) valid.push(ip);
  });
  return { valid, invalid };
}
