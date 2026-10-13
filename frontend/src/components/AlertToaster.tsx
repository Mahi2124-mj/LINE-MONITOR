import { useAlertEvents } from '../context/LiveContext';
import { useToast } from '../context/ToastContext';
import { ALERT_TYPE_LABEL } from '../lib/meta';

/** Shows a toast for every new alert received over the WebSocket. Renders nothing. */
export function AlertToaster() {
  const { push } = useToast();
  useAlertEvents((a) => {
    if (a.acknowledged) return;
    push({
      kind: a.severity,
      title: ALERT_TYPE_LABEL[a.type] ?? 'Alert',
      message: a.message,
      to: a.station_id ? `/stations/${a.station_id}` : a.line_id ? `/lines/${a.line_id}` : '/alerts',
    });
  });
  return null;
}
