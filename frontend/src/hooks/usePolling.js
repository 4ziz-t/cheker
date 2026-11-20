import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Загружает данные и обновляет их с интервалом (пока вкладка видима).
 */
export default function usePolling(loader, intervalMs = 0, deps = []) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  // номер последнего запроса: ответ, пришедший позже более нового, отбрасываем
  const seqRef = useRef(0);

  const reload = useCallback(async () => {
    const seq = ++seqRef.current;
    try {
      const result = await loaderRef.current();
      if (seq === seqRef.current) {
        setData(result);
        setError(null);
      }
      return result;
    } catch (e) {
      if (seq === seqRef.current) setError(e);
      return null;
    } finally {
      if (seq === seqRef.current) setLoading(false);
    }
  }, []);

  // ручная установка данных (например, после «Обновить») важнее ещё не вернувшегося опроса
  const setDataManual = useCallback((value) => {
    seqRef.current += 1;
    setData(value);
    setError(null);
    setLoading(false);
  }, []);

  useEffect(() => {
    setLoading(true);
    reload();
    if (!intervalMs) return undefined;
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') reload();
    }, intervalMs);
    const onVisible = () => {
      if (document.visibilityState === 'visible') reload();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisible);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reload, intervalMs, ...deps]);

  return { data, setData: setDataManual, error, loading, reload };
}
