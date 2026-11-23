import { useEffect, useState } from 'react';

const DISMISS_KEY = 'cheker.install.dismissed';

function readDismissed() {
  try {
    return localStorage.getItem(DISMISS_KEY) === '1';
  } catch {
    return false;
  }
}

/** Предложение установить Cheker как приложение (PWA). Работает в Chrome/Edge/Android. */
export default function useInstallPrompt() {
  const [event, setEvent] = useState(null);
  const [dismissed, setDismissed] = useState(readDismissed);

  useEffect(() => {
    const onPrompt = (e) => {
      e.preventDefault(); // показываем свою кнопку вместо стандартного баннера
      setEvent(e);
    };
    const onInstalled = () => setEvent(null);
    window.addEventListener('beforeinstallprompt', onPrompt);
    window.addEventListener('appinstalled', onInstalled);
    return () => {
      window.removeEventListener('beforeinstallprompt', onPrompt);
      window.removeEventListener('appinstalled', onInstalled);
    };
  }, []);

  const install = async () => {
    if (!event) return;
    event.prompt();
    try {
      await event.userChoice;
    } finally {
      setEvent(null);
    }
  };

  const dismiss = () => {
    setDismissed(true);
    try {
      localStorage.setItem(DISMISS_KEY, '1');
    } catch {
      /* хранилище недоступно — просто скрываем до перезагрузки */
    }
  };

  return { canInstall: Boolean(event), dismissed, install, dismiss };
}
