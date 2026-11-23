import { NavLink } from 'react-router-dom';
import useInstallPrompt from '../hooks/useInstallPrompt.js';
import {
  IconDashboard,
  IconDownload,
  IconGlobe,
  IconList,
  IconLogout,
  IconServer,
  IconSettings,
  IconX,
} from './Icons.jsx';
import '../styles/layout.css';

const NAV = [
  { to: '/', label: 'Дашборд', icon: IconDashboard, end: true },
  { to: '/domains', label: 'Домены', icon: IconGlobe },
  { to: '/nodes', label: 'Ноды', icon: IconServer },
  { to: '/events', label: 'События', icon: IconList },
  { to: '/settings', label: 'Настройки', icon: IconSettings },
];

export default function Layout({ children, onLogout }) {
  const { canInstall, dismissed, install, dismiss } = useInstallPrompt();

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand__mark" />
          <span className="brand__name">Cheker</span>
        </div>
        <nav className="sidebar__nav">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} className="nav-link">
              <Icon />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        {canInstall && (
          <button type="button" className="nav-link nav-link--install" onClick={install}>
            <IconDownload />
            <span>Установить приложение</span>
          </button>
        )}
        <button type="button" className="nav-link nav-link--logout" onClick={onLogout}>
          <IconLogout />
          <span>Выйти</span>
        </button>
      </aside>

      <main className="content">
        {canInstall && !dismissed && (
          <div className="install-bar">
            <img src="/icon-192.png" alt="" className="install-bar__icon" />
            <div className="install-bar__text">
              <b>Установить Cheker</b>
              <span>Откроется отдельным приложением, без адресной строки</span>
            </div>
            <button type="button" className="btn btn--primary btn--sm" onClick={install}>
              Установить
            </button>
            <button type="button" className="icon-btn" aria-label="Скрыть" onClick={dismiss}>
              <IconX size={18} />
            </button>
          </div>
        )}
        {children}
      </main>

      <nav className="tabbar">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink key={to} to={to} end={end} className="tab-link">
            <Icon size={22} />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
