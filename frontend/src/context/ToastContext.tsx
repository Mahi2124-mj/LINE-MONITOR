import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { CircleCheck, Info, OctagonAlert, TriangleAlert, X } from 'lucide-react';
import type { Severity } from '../api/types';

export type ToastKind = Severity | 'success';

export interface ToastInput {
  title: string;
  message?: string;
  kind?: ToastKind;
  /** in-app link shown as "View" */
  to?: string;
  durationMs?: number;
}

interface ToastItem extends ToastInput {
  id: number;
  kind: ToastKind;
}

interface ToastCtx {
  push: (t: ToastInput) => void;
}

const Ctx = createContext<ToastCtx | null>(null);
const MAX_TOASTS = 4;

const KIND_STYLE: Record<ToastKind, { icon: typeof Info; cls: string }> = {
  info: { icon: Info, cls: 'border-l-sky-500 text-sky-300' },
  warning: { icon: TriangleAlert, cls: 'border-l-amber-500 text-amber-300' },
  critical: { icon: OctagonAlert, cls: 'border-l-red-500 text-red-300' },
  success: { icon: CircleCheck, cls: 'border-l-emerald-500 text-emerald-300' },
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => setItems((list) => list.filter((t) => t.id !== id)), []);

  const push = useCallback((t: ToastInput) => {
    const id = nextId.current++;
    setItems((list) => [...list, { ...t, id, kind: t.kind ?? 'info' }].slice(-MAX_TOASTS));
  }, []);

  const value = useMemo(() => ({ push }), [push]);

  return (
    <Ctx.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed right-4 bottom-4 z-[100] flex w-[360px] max-w-[calc(100vw-2rem)] flex-col gap-2" aria-live="polite">
        {items.map((t) => (
          <ToastView key={t.id} item={t} onDismiss={dismiss} />
        ))}
      </div>
    </Ctx.Provider>
  );
}

function ToastView({ item, onDismiss }: { item: ToastItem; onDismiss: (id: number) => void }) {
  const { icon: Icon, cls } = KIND_STYLE[item.kind];
  const duration = item.durationMs ?? (item.kind === 'critical' ? 10_000 : 6_000);
  const onClose = () => onDismiss(item.id);
  useEffect(() => {
    const id = setTimeout(() => onDismiss(item.id), duration);
    return () => clearTimeout(id);
  }, [onDismiss, item.id, duration]);
  return (
    <div
      role="status"
      className={`pointer-events-auto flex animate-slide-in items-start gap-3 rounded-lg border border-l-4 border-edge-2 bg-panel-2/95 p-3 shadow-xl shadow-black/40 backdrop-blur ${cls}`}
    >
      <Icon className="mt-0.5 size-4 shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-semibold text-ink">{item.title}</div>
        {item.message && <div className="mt-0.5 line-clamp-3 text-xs text-ink-2">{item.message}</div>}
        {item.to && (
          <Link to={item.to} onClick={onClose} className="mt-1 inline-block text-xs font-medium link">
            View
          </Link>
        )}
      </div>
      <button type="button" onClick={onClose} className="rounded p-0.5 text-ink-3 hover:bg-panel-3 hover:text-ink" aria-label="Dismiss">
        <X className="size-4" />
      </button>
    </div>
  );
}

export function useToast(): ToastCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error('useToast must be used inside <ToastProvider>');
  return v;
}
