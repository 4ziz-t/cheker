import { NavLink } from 'react-router-dom';
import {
  IconDashboard,
  IconGlobe,
  IconList,
  IconLogout,
  IconServer,
  IconSettings,
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
        <button type="button" className="nav-link nav-link--logout" onClick={onLogout}>
          <IconLogout />
          <span>Выйти</span>
        </button>
      </aside>

      <main className="content">{children}</main>

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
