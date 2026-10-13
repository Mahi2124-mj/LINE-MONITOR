import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { X } from 'lucide-react';

export function Field({ label, hint, children, className = '' }: { label: ReactNode; hint?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <label className={`block min-w-0 ${className}`}>
      <span className="label">{label}</span>
      {children}
      {hint && <span className="hint block">{hint}</span>}
    </label>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
  description,
  disabled,
  badge,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
  badge?: ReactNode;
}) {
  const id = useId();
  return (
    <div className={`flex items-start gap-3 ${disabled ? 'opacity-60' : ''}`}>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative mt-0.5 inline-flex h-5 w-9 shrink-0 items-center rounded-full transition disabled:cursor-not-allowed ${checked ? 'bg-emerald-500' : 'bg-edge-2'}`}
      >
        <span className={`inline-block size-4 rounded-full bg-white shadow transition ${checked ? 'translate-x-[18px]' : 'translate-x-0.5'}`} />
      </button>
      <label htmlFor={id} className={`min-w-0 ${disabled ? 'cursor-not-allowed' : 'cursor-pointer'}`}>
        <span className="flex flex-wrap items-center gap-2 text-sm font-medium text-ink">
          {label}
          {badge}
        </span>
        {description && <span className="block text-xs leading-snug text-ink-3">{description}</span>}
      </label>
    </div>
  );
}

/** Free-text tags (Enter / comma to add, Backspace to remove last). */
export function TagInput({ value, onChange, placeholder = 'Add part…' }: { value: string[]; onChange: (v: string[]) => void; placeholder?: string }) {
  const [draft, setDraft] = useState('');
  const add = (raw: string) => {
    const parts = raw
      .split(',')
      .map((p) => p.trim())
      .filter(Boolean)
      .filter((p) => !value.includes(p));
    if (parts.length) onChange([...value, ...parts]);
    setDraft('');
  };
  return (
    <div className="flex min-h-[34px] w-full flex-wrap items-center gap-1 rounded-md border border-edge bg-canvas px-1.5 py-1 focus-within:border-sky-500/70 focus-within:ring-2 focus-within:ring-sky-500/20">
      {value.map((t) => (
        <span key={t} className="inline-flex items-center gap-1 rounded bg-sky-500/15 px-1.5 py-0.5 text-xs text-sky-200 ring-1 ring-sky-500/30">
          {t}
          <button type="button" onClick={() => onChange(value.filter((v) => v !== t))} className="text-sky-300/70 hover:text-white" aria-label={`Remove ${t}`}>
            <X className="size-3" />
          </button>
        </span>
      ))}
      <input
        className="min-w-[90px] flex-1 bg-transparent px-1 py-0.5 text-sm text-ink outline-none placeholder:text-ink-3"
        value={draft}
        placeholder={value.length ? '' : placeholder}
        onChange={(e) => {
          const v = e.target.value;
          if (v.includes(',')) add(v);
          else setDraft(v);
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            add(draft);
          } else if (e.key === 'Backspace' && !draft && value.length) {
            onChange(value.slice(0, -1));
          }
        }}
        onBlur={() => draft && add(draft)}
      />
    </div>
  );
}

/** Number input that keeps the raw text while typing and reports parsed numbers. */
export function NumberInput({
  value,
  onChange,
  min,
  max,
  step = 'any',
  className = '',
  disabled,
  suffix,
}: {
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number | 'any';
  className?: string;
  disabled?: boolean;
  suffix?: string;
}) {
  const [text, setText] = useState(String(value));
  const lastValue = useRef(value);
  useEffect(() => {
    if (value !== lastValue.current) {
      lastValue.current = value;
      setText(String(value));
    }
  }, [value]);
  return (
    <div className="relative">
      <input
        type="number"
        className={`input ${suffix ? 'pr-8' : ''} ${className}`}
        value={text}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        onChange={(e) => {
          setText(e.target.value);
          const n = Number(e.target.value);
          if (e.target.value !== '' && Number.isFinite(n)) {
            lastValue.current = n;
            onChange(n);
          }
        }}
      />
      {suffix && <span className="pointer-events-none absolute top-1/2 right-2.5 -translate-y-1/2 text-xs text-ink-3">{suffix}</span>}
    </div>
  );
}

export function Modal({ open, title, children, onClose, footer, width = 'max-w-lg' }: { open: boolean; title: ReactNode; children: ReactNode; onClose: () => void; footer?: ReactNode; width?: string }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[90] grid place-items-center bg-black/60 p-4 backdrop-blur-sm" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" className={`w-full ${width} animate-slide-in rounded-xl border border-edge-2 bg-panel shadow-2xl shadow-black/60`}>
        <div className="flex items-center justify-between border-b border-edge px-4 py-3">
          <h3 className="text-sm font-semibold text-ink">{title}</h3>
          <button type="button" onClick={onClose} className="rounded p-1 text-ink-3 hover:bg-panel-3 hover:text-ink" aria-label="Close">
            <X className="size-4" />
          </button>
        </div>
        <div className="max-h-[70vh] overflow-y-auto p-4">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-edge px-4 py-3">{footer}</div>}
      </div>
    </div>
  );
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = 'Confirm',
  danger,
  busy,
  onConfirm,
  onCancel,
  requireText,
}: {
  open: boolean;
  title: ReactNode;
  message: ReactNode;
  confirmLabel?: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  /** user must type this text to enable the button */
  requireText?: string;
}) {
  const [typed, setTyped] = useState('');
  useEffect(() => {
    if (open) setTyped('');
  }, [open]);
  const ok = !requireText || typed.trim() === requireText;
  return (
    <Modal
      open={open}
      title={title}
      onClose={onCancel}
      footer={
        <>
          <button type="button" className="btn" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button type="button" className={`btn ${danger ? 'btn-danger' : 'btn-primary'}`} onClick={onConfirm} disabled={!ok || busy}>
            {busy ? 'Working…' : confirmLabel}
          </button>
        </>
      }
    >
      <div className="text-sm text-ink-2">{message}</div>
      {requireText && (
        <label className="mt-3 block">
          <span className="label">
            Type <span className="font-mono text-ink">{requireText}</span> to confirm
          </span>
          <input className="input" value={typed} onChange={(e) => setTyped(e.target.value)} autoFocus />
        </label>
      )}
    </Modal>
  );
}
