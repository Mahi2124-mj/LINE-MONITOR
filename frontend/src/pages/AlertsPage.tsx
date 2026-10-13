import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { BellOff, Check, CheckCheck, CircleAlert, Info, OctagonAlert, TriangleAlert } from 'lucide-react';
import { api } from '../api/client';
import type { Alert, Severity } from '../api/types';
import { EmptyState, ErrorState, Skeleton, StaleBanner } from '../components/EmptyState';
import { ConfirmDialog } from '../components/Form';
import { Panel } from '../components/Panel';
import { Segmented } from '../components/RangeSelector';
import { SeverityBadge } from '../components/StateBadge';
import { useAlertEvents, useLive } from '../context/LiveContext';
import { usePageTitle } from '../context/PageTitleContext';
import { useToast } from '../context/ToastContext';
import { usePolling } from '../hooks/usePolling';
import { errorMessage, fmtDateTime, fmtRelative } from '../lib/format';
import { ALERT_TYPE_LABEL, SEVERITY_STYLE } from '../lib/meta';

const SEV_ICON: Record<Severity, typeof Info> = { info: Info, warning: TriangleAlert, critical: OctagonAlert };

export default function AlertsPage() {
  usePageTitle('Alerts');
  const { push } = useToast();
  const { refreshAlertCount } = useLive();
  const [status, setStatus] = useState<'open' | 'all'>('open');
  const [sevFilter, setSevFilter] = useState<Severity | 'any'>('any');
  const alerts = usePolling(() => api.alerts(status, 200), [status], 20_000);
  const lines = usePolling(() => api.lines(), [], 60_000);
  const stations = usePolling(() => api.stations(), [], 60_000);
  const [busy, setBusy] = useState<number | 'all' | null>(null);
  const [confirmAll, setConfirmAll] = useState(false);
  const [fresh, setFresh] = useState<Set<number>>(new Set());

  useAlertEvents((a) => {
    alerts.setData((prev) => (prev && !prev.some((x) => x.id === a.id) ? [a, ...prev] : prev));
    setFresh((f) => new Set(f).add(a.id));
  });

  const lineName = (id: number | null) => (id === null ? null : (lines.data?.find((l) => l.id === id)?.name ?? `Line #${id}`));
  const stationName = (id: number | null) => {
    if (id === null) return null;
    const s = stations.data?.find((x) => x.id === id);
    return s ? `Step ${s.sequence} · ${s.name}` : `Station #${id}`;
  };

  const list = useMemo(
    () =>
      [...(alerts.data ?? [])]
        .filter((a) => sevFilter === 'any' || a.severity === sevFilter)
        .sort((a, b) => (a.created_at < b.created_at ? 1 : -1)),
    [alerts.data, sevFilter],
  );
  const openCount = (alerts.data ?? []).filter((a) => !a.acknowledged).length;
  const counts = { critical: 0, warning: 0, info: 0 } as Record<Severity, number>;
  (alerts.data ?? []).forEach((a) => !a.acknowledged && (counts[a.severity] += 1));

  const ack = async (a: Alert) => {
    setBusy(a.id);
    try {
      const updated = await api.ackAlert(a.id);
      alerts.setData((prev) => (status === 'open' ? prev?.filter((x) => x.id !== a.id) : prev?.map((x) => (x.id === a.id ? updated : x))));
      refreshAlertCount();
    } catch (err) {
      push({ kind: 'critical', title: 'Acknowledge failed', message: errorMessage(err) });
    } finally {
      setBusy(null);
    }
  };

  const ackAll = async () => {
    setBusy('all');
    try {
      const r = await api.ackAllAlerts();
      push({ kind: 'success', title: `${r.acknowledged} alert${r.acknowledged === 1 ? '' : 's'} acknowledged` });
      alerts.reload();
      refreshAlertCount();
    } catch (err) {
      push({ kind: 'critical', title: 'Acknowledge all failed', message: errorMessage(err) });
    } finally {
      setBusy(null);
      setConfirmAll(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3 md:max-w-xl">
        {(['critical', 'warning', 'info'] as Severity[]).map((s) => {
          const Icon = SEV_ICON[s];
          return (
            <button
              key={s}
              type="button"
              onClick={() => setSevFilter((cur) => (cur === s ? 'any' : s))}
              className={`rounded-xl border bg-panel px-3 py-2 text-left transition ${sevFilter === s ? 'border-sky-500/60 ring-1 ring-sky-500/30' : 'border-edge hover:border-edge-2'}`}
            >
              <div className={`flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider ${SEVERITY_STYLE[s].text}`}>
                <Icon className="size-3.5" /> {SEVERITY_STYLE[s].label}
              </div>
              <div className="text-2xl font-semibold text-ink tabular-nums">{counts[s]}</div>
              <div className="text-[10px] text-ink-3">open</div>
            </button>
          );
        })}
      </div>

      <StaleBanner error={alerts.data ? alerts.error : null} />

      <Panel
        title={status === 'open' ? 'Open alerts' : 'All alerts'}
        subtitle={sevFilter !== 'any' ? `Filtered: ${SEVERITY_STYLE[sevFilter].label}` : 'New alerts appear live'}
        icon={<CircleAlert className="size-4" />}
        flush
        actions={
          <>
            <Segmented
              size="xs"
              value={status}
              onChange={setStatus}
              options={[
                { value: 'open', label: 'Open' },
                { value: 'all', label: 'All' },
              ]}
            />
            <button type="button" className="btn btn-sm" disabled={openCount === 0 || busy !== null} onClick={() => setConfirmAll(true)}>
              <CheckCheck className="size-3.5" /> Acknowledge all
            </button>
          </>
        }
      >
        {!alerts.data ? (
          alerts.loading ? (
            <div className="space-y-2 p-4">
              {Array.from({ length: 5 }, (_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : (
            <ErrorState error={alerts.error} onRetry={alerts.reload} />
          )
        ) : list.length === 0 ? (
          <EmptyState
            icon={<BellOff className="size-8" strokeWidth={1.5} />}
            title={status === 'open' ? 'No open alerts' : 'No alerts'}
            message={status === 'open' ? 'All clear – the lines are running within limits.' : undefined}
          />
        ) : (
          <ul className="divide-y divide-edge">
            {list.map((a) => {
              const Icon = SEV_ICON[a.severity];
              const sev = SEVERITY_STYLE[a.severity];
              const ln = lineName(a.line_id);
              const sn = stationName(a.station_id);
              return (
                <li
                  key={a.id}
                  className={`flex items-start gap-3 border-l-4 px-4 py-3 ${sev.border} ${a.acknowledged ? 'opacity-55' : ''} ${fresh.has(a.id) ? 'animate-slide-in bg-sky-500/5' : ''}`}
                >
                  <Icon className={`mt-0.5 size-4 shrink-0 ${sev.text}`} />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <SeverityBadge severity={a.severity} />
                      <span className="text-sm font-semibold text-ink">{ALERT_TYPE_LABEL[a.type] ?? a.type}</span>
                      {fresh.has(a.id) && <span className="rounded bg-sky-500/20 px-1.5 text-[10px] font-bold text-sky-300">NEW</span>}
                    </div>
                    <p className="mt-0.5 text-sm text-ink-2">{a.message}</p>
                    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-ink-3">
                      <span title={fmtDateTime(a.created_at)}>
                        {fmtDateTime(a.created_at)} · {fmtRelative(a.created_at)}
                      </span>
                      {ln && a.line_id !== null && (
                        <Link to={`/lines/${a.line_id}`} className="link">
                          {ln}
                        </Link>
                      )}
                      {sn && a.station_id !== null && (
                        <Link to={`/stations/${a.station_id}`} className="link">
                          {sn}
                        </Link>
                      )}
                      {a.camera_id !== null && (
                        <Link to={`/cameras/${a.camera_id}`} className="link">
                          Camera #{a.camera_id}
                        </Link>
                      )}
                    </div>
                  </div>
                  {a.acknowledged ? (
                    <span className="flex shrink-0 items-center gap-1 text-xs text-ink-3">
                      <Check className="size-3.5" /> Acknowledged
                    </span>
                  ) : (
                    <button type="button" className="btn btn-sm shrink-0" disabled={busy !== null} onClick={() => void ack(a)}>
                      <Check className="size-3.5" /> {busy === a.id ? '…' : 'Acknowledge'}
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Panel>

      <ConfirmDialog
        open={confirmAll}
        title="Acknowledge all open alerts?"
        message={`This marks all ${openCount} open alert${openCount === 1 ? '' : 's'} as acknowledged.`}
        confirmLabel="Acknowledge all"
        busy={busy === 'all'}
        onCancel={() => setConfirmAll(false)}
        onConfirm={() => void ackAll()}
      />
    </div>
  );
}
