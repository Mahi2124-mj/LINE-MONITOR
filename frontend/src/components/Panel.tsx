import type { ReactNode } from 'react';

interface PanelProps {
  title?: ReactNode;
  subtitle?: ReactNode;
  icon?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  className?: string;
  bodyClassName?: string;
  /** remove body padding (tables, media) */
  flush?: boolean;
  id?: string;
}

export function Panel({ title, subtitle, icon, actions, children, className = '', bodyClassName = '', flush, id }: PanelProps) {
  return (
    <section id={id} className={`min-w-0 rounded-xl border border-edge bg-panel ${className}`}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 border-b border-edge px-4 py-2.5">
          <div className="flex min-w-0 items-center gap-2">
            {icon && <span className="text-ink-3">{icon}</span>}
            <div className="min-w-0">
              {title && <h2 className="truncate text-sm font-semibold tracking-wide text-ink">{title}</h2>}
              {subtitle && <p className="truncate text-xs text-ink-3">{subtitle}</p>}
            </div>
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={`${flush ? '' : 'p-4'} ${bodyClassName}`}>{children}</div>
    </section>
  );
}
