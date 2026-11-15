import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react';

const ToastContext = createContext(null);

export function ToastProvider({ children }) {
  const [items, setItems] = useState([]);
  const idRef = useRef(0);

  const remove = useCallback((id) => {
    setItems((list) => list.filter((t) => t.id !== id));
  }, []);

  const push = useCallback(
    (text, tone = 'info', timeout = 4000) => {
      idRef.current += 1;
      const id = idRef.current;
      setItems((list) => [...list.slice(-3), { id, text, tone }]);
      setTimeout(() => remove(id), timeout);
    },
    [remove],
  );

  const api = useMemo(
    () => ({
      info: (t) => push(t, 'info'),
      success: (t) => push(t, 'ok'),
      error: (t) => push(t, 'bad', 6000),
    }),
    [push],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => (
          <button key={t.id} type="button" className={`toast toast--${t.tone}`} onClick={() => remove(t.id)}>
            {t.text}
          </button>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
