import { useCallback, useEffect, useState } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { authApi } from './api/index.js';
import Layout from './components/Layout.jsx';
import Spinner from './components/Spinner.jsx';
import Dashboard from './pages/Dashboard.jsx';
import DomainDetail from './pages/DomainDetail.jsx';
import Domains from './pages/Domains.jsx';
import Events from './pages/Events.jsx';
import Login from './pages/Login.jsx';
import Nodes from './pages/Nodes.jsx';
import Settings from './pages/Settings.jsx';

export default function App() {
  // null — проверяем, true/false — результат
  const [authed, setAuthed] = useState(null);

  useEffect(() => {
    authApi
      .me()
      .then(() => setAuthed(true))
      .catch(() => setAuthed(false));
    const onLogout = () => setAuthed(false);
    window.addEventListener('auth:logout', onLogout);
    return () => window.removeEventListener('auth:logout', onLogout);
  }, []);

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } finally {
      setAuthed(false);
    }
  }, []);

  if (authed === null) {
    return (
      <div className="fullscreen-center">
        <Spinner size={32} />
      </div>
    );
  }

  if (!authed) {
    return <Login onSuccess={() => setAuthed(true)} />;
  }

  return (
    <Layout onLogout={logout}>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/domains" element={<Domains />} />
        <Route path="/domains/:id" element={<DomainDetail />} />
        <Route path="/nodes" element={<Nodes />} />
        <Route path="/events" element={<Events />} />
        <Route path="/settings" element={<Settings onLogout={logout} />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}
