import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import {
  Bell,
  ChevronRight,
  Cctv,
  Factory,
  FileText,
  Footprints,
  LayoutDashboard,
  ListVideo,
  Settings2,
  Video,
  VideoOff,
  Wifi,
  WifiOff,
} from 'lucide-react';
import { api } from '../api/client';
import { useLiveVideo } from '../lib/liveVideo';
import { useLive, useLiveStates } from '../context/LiveContext';
import { usePageTitleValue } from '../context/PageTitleContext';
import { usePolling } from '../hooks/usePolling';
import { lineTag } from '../lib/format';
import { RangeSelector } from './RangeSelector';
import { StateDot } from './StateBadge';
import type { StationState } from '../api/types';

const NAV: { to: string; label: string; icon: ReactNode; end?: boolean }[] = [
  { to: '/', label: 'Overview', icon: <LayoutDashboard className="size-[18px]" />, end: true },
  { to: '/analysis', label: 'Cycle analysis', icon: <ListVideo className="size-[18px]" /> },
  { to: '/movement', label: 'Movement & waste', icon: <Footprints className="size-[18px]" /> },
  { to: '/reports', label: 'Reports', icon: <FileText className="size-[18px]" /> },
  { to: '/cameras', label: 'Cameras', icon: <Cctv className="size-[18px]" /> },
  { to: '/alerts', label: 'Alerts', icon: <Bell className="size-[18px]" /> },
  { to: '/setup', label: 'Lines & cameras', icon: <Settings2 className="size-[18px]" /> },
];

export function Layout() {
  // the sidebar is an icon rail; the Line Monitor icon opens the full menu and the page moves right with it (on a phone
  // the menu opens over the page instead, and closes when a page is picked). With the mouse over the rail the full menu
  // opens the same way until the mouse leaves.
  const [open, setOpen] = useState(false);
  const [peek, setPeek] = useState(false);
  const peekTimer = useRef<number | undefined>(undefined);
  const hover = (e: ReactPointerEvent, on: boolean) => {
    if (e.pointerType !== 'mouse') return; // a tap is a click
    window.clearTimeout(peekTimer.current);
    peekTimer.current = window.setTimeout(() => setPeek(on), on ? 120 : 250); // not for a mouse just passing by
  };
  useEffect(() => () => window.clearTimeout(peekTimer.current), []);
  const { pathname } = useLocation();
  useEffect(() => {
    if (window.matchMedia('(max-width: 639px)').matches) setOpen(false);
  }, [pathname]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  return (
    <div className="flex h-full min-h-0">
      <div
        className={`relative shrink-0 transition-[width] duration-200 ${open || peek ? 'w-[60px] sm:w-[240px]' : 'w-[60px]'}`}
        onPointerEnter={(e) => hover(e, true)}
        onPointerLeave={(e) => hover(e, false)}
      >
        <Sidebar
          collapsed={!open && !peek}
          onToggle={() => {
            window.clearTimeout(peekTimer.current);
            setPeek(false);
            setOpen((v) => !v);
          }}
        />
      </div>
      {open && <div className="fixed inset-0 z-30 bg-black/50 backdrop-blur-[1px] sm:hidden" onClick={() => setOpen(false)} aria-hidden />}
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden">
          <div className="mx-auto w-full max-w-[1800px] p-4 lg:p-5">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}

function Sidebar({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  const { openAlerts } = useLive();
  const { data: lines } = usePolling(() => api.lines(), [], 60_000);
  const { states } = useLiveStates();

  // worst live state per line for the small dot in the nav
  const lineState = (lineId: number): StationState | null => {
    const order: StationState[] = ['offline', 'idle', 'waiting', 'working', 'no_camera'];
    let best: StationState | null = null;
    for (const s of states.values()) {
      if (s.line_id !== lineId) continue;
      if (best === null || order.indexOf(s.state) < order.indexOf(best)) best = s.state;
    }
    return best;
  };

  const itemCls = ({ isActive }: { isActive: boolean }) =>
    `group relative flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm font-medium transition ${
      isActive ? 'bg-panel-3 text-ink ring-1 ring-edge-2' : 'text-ink-2 hover:bg-panel-2 hover:text-ink'
    } ${collapsed ? 'justify-center' : ''}`;

  return (
    <aside
      className={`absolute inset-y-0 left-0 z-40 flex flex-col overflow-hidden border-r border-edge bg-panel transition-[width] duration-200 ${
        collapsed ? 'w-[60px]' : 'w-[240px] max-sm:shadow-2xl max-sm:shadow-black/60'
      }`}
      aria-label="Main navigation"
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={!collapsed}
        title={collapsed ? 'Open menu' : 'Close menu'}
        className={`flex h-14 shrink-0 items-center gap-2.5 border-b border-edge text-left hover:bg-panel-2 ${collapsed ? 'justify-center px-0' : 'px-4'}`}
      >
        <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-emerald-500/30 to-sky-500/20 ring-1 ring-emerald-500/40">
          <Factory className="size-[18px] text-emerald-300" />
        </span>
        {!collapsed && (
          <span className="min-w-0 leading-tight">
            <span className="block truncate text-sm font-semibold tracking-wide text-ink">Line Monitor</span>
            <span className="block truncate text-[11px] text-ink-3">Assembly vision analytics</span>
          </span>
        )}
      </button>

      <nav className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto p-2">
        {NAV.slice(0, 1).map((n) => (
          <NavLink key={n.to} to={n.to} end={n.end} className={itemCls} title={collapsed ? n.label : undefined}>
            {n.icon}
            {!collapsed && <span className="truncate">{n.label}</span>}
          </NavLink>
        ))}

        {/* Lines quick nav */}
        {lines && lines.length > 0 && (
          <div className="my-1">
            {!collapsed && <div className="px-2.5 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-ink-3">Lines</div>}
            {collapsed && <div className="mx-3 my-2 border-t border-edge" />}
            {lines.map((l) => {
              const st = lineState(l.id);
              return (
                <NavLink
                  key={l.id}
                  to={`/lines/${l.id}`}
                  className={({ isActive }) =>
                    `flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[13px] transition ${
                      isActive ? 'bg-panel-3 text-ink ring-1 ring-edge-2' : 'text-ink-2 hover:bg-panel-2 hover:text-ink'
                    } ${collapsed ? 'justify-center' : ''} ${l.is_active ? '' : 'opacity-60'}`
                  }
                  title={l.name}
                >
                  {collapsed ? (
                    <span className="relative grid h-7 min-w-7 place-items-center rounded-md bg-panel-3 px-1 text-[10px] font-bold text-ink-2">
                      {lineTag(l).slice(0, 4)}
                      {st && (
                        <span className="absolute -top-0.5 -right-0.5">
                          <StateDot state={st} />
                        </span>
                      )}
                    </span>
                  ) : (
                    <>
                      {st ? <StateDot state={st} /> : <span className="size-2 rounded-full bg-panel-3" />}
                      <span className="min-w-0 flex-1 truncate">{l.name}</span>
                    </>
                  )}
                </NavLink>
              );
            })}
            {!collapsed && <div className="mx-2.5 mt-2 border-t border-edge" />}
          </div>
        )}

        {NAV.slice(1).map((n) => (
          <NavLink key={n.to} to={n.to} end={n.end} className={itemCls} title={collapsed ? n.label : undefined}>
            {n.icon}
            {!collapsed && <span className="truncate">{n.label}</span>}
            {n.to === '/alerts' && openAlerts > 0 && (
              <span
                className={`rounded-full bg-red-500 px-1.5 text-[10px] font-bold leading-4 text-white ${
                  collapsed ? 'absolute top-0.5 right-0.5' : 'ml-auto'
                }`}
              >
                {openAlerts > 99 ? '99+' : openAlerts}
              </span>
            )}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}

function TopBar() {
  const { title, crumbs } = usePageTitleValue();
  const { connected, retries, openAlerts } = useLive();
  const [videoOn, setVideoOn] = useLiveVideo();
  return (
    <header className="flex min-h-14 shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b border-edge bg-panel/80 px-3 py-2 backdrop-blur sm:flex-nowrap sm:px-4 sm:py-0 lg:px-5">
      <div className="flex min-w-0 flex-1 items-center gap-1.5">
        {crumbs.map((c, i) => (
          <span key={i} className="hidden min-w-0 shrink items-center gap-1.5 text-sm text-ink-3 md:flex">
            {c.to ? (
              <Link to={c.to} className="truncate hover:text-ink">
                {c.label}
              </Link>
            ) : (
              <span className="truncate">{c.label}</span>
            )}
            <ChevronRight className="size-3.5 shrink-0" />
          </span>
        ))}
        <h1 className="truncate text-base font-semibold tracking-wide text-ink">{title}</h1>
      </div>
      <RangeSelector className="order-last w-full justify-between sm:order-none sm:w-auto sm:shrink-0" />
      <button
        type="button"
        role="switch"
        aria-checked={videoOn}
        onClick={() => setVideoOn(!videoOn)}
        className={`flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset transition ${
          videoOn ? 'bg-sky-500/10 text-sky-300 ring-sky-500/30 hover:bg-sky-500/20' : 'bg-zinc-500/10 text-zinc-300 ring-zinc-500/40 hover:bg-zinc-500/20'
        }`}
        title={videoOn ? 'Live video is on – click to stop all camera video (cameras keep analysing)' : 'Live video is off – click to show camera video'}
      >
        {videoOn ? <Video className="size-3.5" /> : <VideoOff className="size-3.5" />}
        <span className="hidden sm:inline">Video {videoOn ? 'on' : 'off'}</span>
      </button>
      <div
        className={`hidden shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset sm:flex ${
          connected ? 'bg-emerald-500/10 text-emerald-300 ring-emerald-500/30' : 'bg-zinc-500/10 text-zinc-300 ring-zinc-500/40'
        }`}
        title={connected ? 'Live updates connected (WebSocket)' : `Live updates disconnected – reconnecting (attempt ${retries})`}
      >
        {connected ? <Wifi className="size-3.5" /> : <WifiOff className="size-3.5 animate-pulse-soft" />}
        {connected ? 'Live' : 'Offline'}
      </div>
      <Link
        to="/alerts"
        className="relative shrink-0 rounded-lg p-2 text-ink-2 hover:bg-panel-3 hover:text-ink"
        title={`${openAlerts} open alert${openAlerts === 1 ? '' : 's'}`}
        aria-label={`${openAlerts} open alerts`}
      >
        <Bell className="size-5" />
        {openAlerts > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-[18px] rounded-full bg-red-500 px-1 text-center text-[10px] font-bold leading-[18px] text-white">
            {openAlerts > 99 ? '99+' : openAlerts}
          </span>
        )}
      </Link>
    </header>
  );
}
