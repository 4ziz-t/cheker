export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function extractMessage(data, fallback) {
  if (!data) return fallback;
  const { detail } = data;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => String(d.msg || '').replace(/^Value error, /, ''))
      .filter(Boolean)
      .join('; ');
  }
  return fallback;
}

export async function request(method, path, body) {
  const init = { method, credentials: 'same-origin', headers: {} };
  if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }

  let res;
  try {
    res = await fetch(`/api${path}`, init);
  } catch {
    throw new ApiError(0, 'Нет связи с сервером');
  }

  if (res.status === 401 && !path.startsWith('/auth/')) {
    window.dispatchEvent(new Event('auth:logout'));
  }

  if (!res.ok) {
    let data = null;
    try {
      data = await res.json();
    } catch {
      /* не JSON */
    }
    throw new ApiError(res.status, extractMessage(data, `Ошибка ${res.status}`));
  }

  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  get: (p) => request('GET', p),
  post: (p, b) => request('POST', p, b ?? {}),
  put: (p, b) => request('PUT', p, b),
  patch: (p, b) => request('PATCH', p, b),
  del: (p) => request('DELETE', p),
};
