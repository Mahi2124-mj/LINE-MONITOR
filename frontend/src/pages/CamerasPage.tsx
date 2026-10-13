import { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Cctv, Eye, EyeOff, Settings2 } from 'lucide-react';
import { api } from '../api/client';
import type { Camera } from '../api/types';
import { CameraTile } from '../components/CameraTile';
import { EmptyState, ErrorState, StaleBanner } from '../components/EmptyState';
import { Panel } from '../components/Panel';
import { useLive } from '../context/LiveContext';
import { usePageTitle } from '../context/PageTitleContext';
import { usePolling } from '../hooks/usePolling';

export default function CamerasPage() {
  usePageTitle('Cameras');
  const [params, setParams] = useSearchParams();
  const lineId = params.get('line') ? Number(params.get('line')) : undefined;
  const [overlay, setOverlay] = useState(true);
  const { cameraStatus } = useLive();

  const lines = usePolling(() => api.lines(), [], 60_000);
  const stations = usePolling(() => api.stations(), [], 60_000);
  const cameras = usePolling(() => api.cameras(lineId), [lineId], 15_000);

  const stationLabel = useMemo(() => {
    const m = new Map<number, string>();
    stations.data?.forEach((s) => m.set(s.id, `Step ${s.sequence} · ${s.name}`));
    return (id: number | null) => (id === null ? null : (m.get(id) ?? `Station #${id}`));
  }, [stations.data]);

  const groups = useMemo(() => {
    const byLine = new Map<number, Camera[]>();
    for (const c of cameras.data ?? []) {
      const list = byLine.get(c.line_id) ?? [];
      list.push(c);
      byLine.set(c.line_id, list);
    }
    const lineName = (id: number) => lines.data?.find((l) => l.id === id)?.name ?? `Line #${id}`;
    return [...byLine.entries()]
      .map(([id, cams]) => ({
        id,
        name: lineName(id),
        cams: cams.sort((a, b) => {
          const sa = stations.data?.find((s) => s.id === a.station_id)?.sequence ?? 999;
          const sb = stations.data?.find((s) => s.id === b.station_id)?.sequence ?? 999;
          return sa - sb || a.name.localeCompare(b.name);
        }),
      }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [cameras.data, lines.data, stations.data]);

  const isOnline = (c: Camera) => c.enabled && (cameraStatus.get(c.id)?.online ?? c.status.online);
  const total = cameras.data?.length ?? 0;
  const online = cameras.data?.filter(isOnline).length ?? 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-sm text-ink-2">
          {cameras.data ? (
            <>
              <span className={`font-semibold tabular-nums ${online === total ? 'text-emerald-400' : 'text-amber-400'}`}>{online}</span>
              <span className="tabular-nums"> / {total}</span> cameras online
            </>
          ) : (
            'Loading cameras…'
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" className="btn btn-sm" onClick={() => setOverlay((v) => !v)} title="Toggle detection overlay on the live streams">
            {overlay ? <Eye className="size-3.5" /> : <EyeOff className="size-3.5" />} Overlay {overlay ? 'on' : 'off'}
          </button>
          <label className="flex items-center gap-2 text-sm text-ink-2">
            Line
            <select className="input w-auto" value={lineId ?? ''} onChange={(e) => setParams(e.target.value ? { line: e.target.value } : {}, { replace: true })}>
              <option value="">All lines</option>
              {lines.data?.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </select>
          </label>
          <Link to="/setup" className="btn btn-sm">
            <Settings2 className="size-3.5" /> Add camera
          </Link>
        </div>
      </div>

      <StaleBanner error={cameras.data ? cameras.error : null} />

      {!cameras.data ? (
        cameras.loading ? (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 2xl:grid-cols-4">
            {Array.from({ length: 8 }, (_, i) => (
              <div key={i} className="aspect-[4/3] animate-pulse rounded-xl bg-panel-3/60" />
            ))}
          </div>
        ) : (
          <ErrorState error={cameras.error} onRetry={cameras.reload} />
        )
      ) : groups.length === 0 ? (
        <div className="rounded-xl border border-edge bg-panel">
          <EmptyState
            icon={<Cctv className="size-9" strokeWidth={1.5} />}
            title="No cameras configured"
            message="Add cameras to a line on the Line setup page, then draw zones on the camera page."
            action={
              <Link to="/setup" className="btn btn-primary">
                Line setup
              </Link>
            }
          />
        </div>
      ) : (
        groups.map((g) => {
          const on = g.cams.filter(isOnline).length;
          return (
            <Panel
              key={g.id}
              title={
                <Link to={`/lines/${g.id}`} className="hover:text-sky-300">
                  {g.name}
                </Link>
              }
              subtitle={`${on} / ${g.cams.length} online`}
              icon={<Cctv className="size-4" />}
            >
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
                {g.cams.map((c) => (
                  <CameraTile
                    key={c.id}
                    camera={c}
                    stationLabel={stationLabel(c.station_id)}
                    overlay={overlay}
                    detailed
                    onEnabledChange={(updated) => cameras.setData((list) => list?.map((x) => (x.id === updated.id ? updated : x)))}
                  />
                ))}
              </div>
            </Panel>
          );
        })
      )}
    </div>
  );
}
