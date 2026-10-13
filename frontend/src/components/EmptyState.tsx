import type { ReactNode } from 'react';
import { Inbox, PlugZap, RefreshCw, TriangleAlert } from 'lucide-react';
import { errorMessage, isBackendDown } from '../lib/format';

interface EmptyStateProps {
  icon?: ReactNode;
  title: ReactNode;
  message?: ReactNode;
  action?: ReactNode;
  compact?: boolean;
  className?: string;
}

export function EmptyState({ icon, title, message, action, compact, className = '' }: EmptyStateProps) {
  return (
    <div className={`flex flex-col items-center justify-center text-center ${compact ? 'gap-1.5 py-6' : 'gap-2 py-12'} ${className}`}>
      <div className="text-ink-3">{icon ?? <Inbox className={compact ? 'size-6' : 'size-9'} strokeWidth={1.5} />}</div>
      <div className={`font-medium text-ink-2 ${compact ? 'text-sm' : 'text-base'}`}>{title}</div>
      {message && <div className="max-w-md text-sm text-ink-3">{message}</div>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

/** Friendly error with a special message when the backend is not running. */
export function ErrorState({ error, onRetry, compact, className }: { error: unknown; onRetry?: () => void; compact?: boolean; className?: string }) {
  const down = isBackendDown(error);
  const status = (error as { status?: number } | null)?.status;
  return (
    <EmptyState
      compact={compact}
      className={className}
      icon={
        down ? (
          <PlugZap className={compact ? 'size-6 text-amber-400' : 'size-9 text-amber-400'} strokeWidth={1.5} />
        ) : (
          <TriangleAlert className={compact ? 'size-6 text-rose-400' : 'size-9 text-rose-400'} strokeWidth={1.5} />
        )
      }
      title={down ? 'Line Monitor server is not running' : status === 404 ? 'Not found' : 'Something went wrong'}
      message={
        down ? (
          <>
            The Line Monitor server is not running. Double-click <span className="font-semibold text-ink-2">Line Monitor</span> on the Desktop (or <span className="font-mono text-ink-2">Start Line Monitor.bat</span>) and open <span className="font-mono text-ink-2">http://localhost:6010</span>. This page retries automatically.
          </>
        ) : (
          errorMessage(error)
        )
      }
      action={
        onRetry && (
          <button type="button" className="btn btn-sm" onClick={onRetry}>
            <RefreshCw className="size-3.5" /> Retry
          </button>
        )
      }
    />
  );
}

export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse rounded-md bg-panel-3/70 ${className}`} />;
}

export function SkeletonTiles({ count = 4, className = '' }: { count?: number; className?: string }) {
  return (
    <div className={`grid grid-cols-2 gap-3 lg:grid-cols-4 ${className}`}>
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="rounded-xl border border-edge bg-panel p-4">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="mt-3 h-7 w-20" />
          <Skeleton className="mt-3 h-1.5 w-full" />
        </div>
      ))}
    </div>
  );
}

export function SkeletonPanel({ className = 'h-64' }: { className?: string }) {
  return (
    <div className={`rounded-xl border border-edge bg-panel p-4 ${className}`}>
      <Skeleton className="h-4 w-40" />
      <Skeleton className="mt-4 h-[calc(100%-2rem)] w-full" />
    </div>
  );
}

/** Inline banner for errors that happen while stale data is still shown. */
export function StaleBanner({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <div className="flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
      <PlugZap className="size-4 shrink-0" />
      {isBackendDown(error) ? 'Server not reachable – showing last known data. Retrying…' : `Refresh failed: ${errorMessage(error)}`}
    </div>
  );
}
