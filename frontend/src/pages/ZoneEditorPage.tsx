import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, CircleAlert, CircleCheck, ScanEye, Shapes } from 'lucide-react';
import { api } from '../api/client';
import type { Station } from '../api/types';
import { EmptyState, ErrorState, SkeletonPanel } from '../components/EmptyState';
import { Panel } from '../components/Panel';
import { ZoneEditor } from '../components/ZoneEditor';
import { usePageTitle } from '../context/PageTitleContext';
import { useToast } from '../context/ToastContext';
import { usePolling } from '../hooks/usePolling';
import { errorMessage } from '../lib/format';

/** Full-page zone editor for one camera (separate from the camera's live view / settings page). */
export default function ZoneEditorPage() {
  const params = useParams();
  const id = Number(params.id);
  const valid = Number.isInteger(id) && id > 0;
  const cam = usePolling(() => api.camera(id), [id], 0);
  const camera = cam.data;
  const stations = usePolling(() => (camera ? api.stations(camera.line_id) : Promise.resolve<Station[]>([])), [camera?.line_id], 0);
  const { push } = useToast();
  const [capturing, setCapturing] = useState(false);

  usePageTitle('Zone editor', [
    { label: 'Cameras', to: '/cameras' },
    ...(camera ? [{ label: camera.name, to: `/cameras/${camera.id}` }] : []),
  ]);

  if (!valid) return <EmptyState title="Invalid camera id" action={<Link to="/cameras" className="btn">Back to cameras</Link>} />;
  if (!camera) return cam.loading ? <SkeletonPanel className="h-[32rem]" /> : <ErrorState error={cam.error} onRetry={cam.reload} />;

  const capture = async () => {
    setCapturing(true);
    try {
      cam.setData(await api.captureReference(camera.id));
      push({ kind: 'success', title: 'Empty reference captured' });
    } catch (e) {
      push({ kind: 'critical', title: 'Could not capture reference', message: errorMessage(e) });
    } finally {
      setCapturing(false);
    }
  };

  const partZones = camera.zones.filter((z) => z.type === 'part_zone').length;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link to={`/cameras/${camera.id}`} className="inline-flex items-center gap-1.5 text-sm text-ink-3 hover:text-ink">
          <ArrowLeft className="size-4" /> Back to {camera.name}
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <span className={`inline-flex items-center gap-1.5 text-xs ${camera.has_reference ? 'text-emerald-300' : 'text-amber-300'}`}>
            {camera.has_reference ? <CircleCheck className="size-3.5" /> : <CircleAlert className="size-3.5" />}
            {camera.has_reference ? 'Empty reference captured' : 'No empty reference yet'}
          </span>
          <button type="button" className="btn btn-sm" disabled={capturing || !camera.enabled} onClick={() => void capture()} title="Take it while every part fixture is empty">
            <ScanEye className="size-3.5" /> {capturing ? 'Capturing…' : 'Capture empty reference'}
          </button>
        </div>
      </div>

      <Panel
        title={`Zones · ${camera.name}`}
        subtitle={
          partZones > 1
            ? `${partZones} part fixtures: a unit leaving any fixture counts as one finished cycle of the step`
            : 'Draw the part fixture(s), normal work area, bins and areas to ignore. You can draw more than one part zone if the step has several fixtures.'
        }
        icon={<Shapes className="size-4" />}
      >
        <ZoneEditor camera={camera} stations={stations.data ?? []} onSaved={(c) => cam.setData(c)} />
      </Panel>
    </div>
  );
}
