import { useCallback, useEffect, useRef, useState, type SyntheticEvent } from 'react';
import { VideoOff } from 'lucide-react';
import { api } from '../api/client';
import { useInView } from '../hooks/useInView';
import { useLiveVideo } from '../lib/liveVideo';

const BLANK_GIF = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';

interface LiveStreamProps {
  cameraId: number;
  overlay?: boolean;
  className?: string;
  /** css aspect ratio, default 16/9 */
  aspect?: string;
  alt?: string;
  /** retry interval after an error */
  retryMs?: number;
  /** called when stream fails / recovers */
  onStatus?: (ok: boolean) => void;
  fit?: 'cover' | 'contain';
  /**
   * 'mjpeg'    continuous stream: smooth, but holds one HTTP connection open (browsers allow only 6 per host).
   * 'snapshot' polls short JPEG requests: use for grids of many cameras so API calls never get starved.
   */
  mode?: 'mjpeg' | 'snapshot';
  /** snapshot mode: target refresh interval */
  intervalMs?: number;
}

export function LiveStream(props: LiveStreamProps) {
  const [videoOn, setVideoOn] = useLiveVideo();
  if (!videoOn) return <LiveVideoOff aspect={props.aspect} className={props.className} onEnable={() => setVideoOn(true)} />;
  return props.mode === 'snapshot' ? <SnapshotStream {...props} /> : <MjpegStream {...props} />;
}

/** Shown instead of the stream while live video is switched off (no requests are made). */
function LiveVideoOff({ aspect = '16 / 9', className = '', onEnable }: { aspect?: string; className?: string; onEnable: () => void }) {
  return (
    <div className={`relative grid place-items-center overflow-hidden bg-[#0b0d10] ${className}`} style={{ aspectRatio: aspect }}>
      <div className="flex flex-col items-center gap-2 text-ink-3">
        <VideoOff className="size-6" />
        <span className="text-xs">Live video is off</span>
        <button
          type="button"
          className="btn btn-sm"
          onClick={(e) => {
            e.preventDefault(); // tiles are links
            e.stopPropagation();
            onEnable();
          }}
        >
          Turn on
        </button>
      </div>
    </div>
  );
}

function Placeholder({ failed, inView }: { failed: boolean; inView: boolean }) {
  return (
    <div className="absolute inset-0 grid place-items-center bg-[repeating-linear-gradient(135deg,#0d1014_0_10px,#11151a_10px_20px)]">
      <div className="flex flex-col items-center gap-1.5 text-ink-3">
        {failed ? (
          <>
            <VideoOff className="size-6" />
            <span className="text-xs">Stream offline – retrying…</span>
          </>
        ) : (
          <span className="text-xs animate-pulse-soft">{inView ? 'Connecting…' : 'Paused (not visible)'}</span>
        )}
      </div>
    </div>
  );
}

/** Refreshes a JPEG snapshot in a loop while visible (one short request at a time per tile). */
function SnapshotStream({ cameraId, overlay = true, className = '', aspect = '16 / 9', alt, retryMs = 5000, onStatus, fit = 'contain', intervalMs = 400 }: LiveStreamProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const inView = useInView(wrapRef);
  const [frame, setFrame] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const onStatusRef = useRef(onStatus);
  useEffect(() => {
    onStatusRef.current = onStatus;
  });

  useEffect(() => {
    if (!inView) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let current: string | null = null;
    const ctrl = new AbortController();
    const tick = async () => {
      const t0 = performance.now();
      let ok = false;
      try {
        const res = await fetch(api.snapshotUrl(cameraId, overlay), { cache: 'no-store', signal: ctrl.signal });
        if (res.ok) {
          const url = URL.createObjectURL(await res.blob());
          if (stopped) {
            URL.revokeObjectURL(url);
            return;
          }
          if (current) URL.revokeObjectURL(current);
          current = url;
          setFrame(url);
          ok = true;
        }
      } catch {
        /* network error / aborted */
      }
      if (stopped) return;
      setFailed(!ok);
      onStatusRef.current?.(ok);
      timer = setTimeout(tick, ok ? Math.max(50, intervalMs - (performance.now() - t0)) : retryMs);
    };
    void tick();
    return () => {
      stopped = true;
      ctrl.abort();
      if (timer) clearTimeout(timer);
      if (current) URL.revokeObjectURL(current);
      setFrame(null);
    };
  }, [inView, cameraId, overlay, intervalMs, retryMs]);

  return (
    <div ref={wrapRef} className={`relative overflow-hidden bg-black ${className}`} style={{ aspectRatio: aspect }}>
      {frame && (
        <img src={frame} alt={alt ?? `Camera ${cameraId} live`} className={`absolute inset-0 h-full w-full ${fit === 'cover' ? 'object-cover' : 'object-contain'}`} />
      )}
      {(!frame || failed) && <Placeholder failed={failed} inView={inView} />}
    </div>
  );
}

/**
 * Live MJPEG <img>. Only connects while visible (IntersectionObserver), shows an offline placeholder
 * on error and retries every few seconds. The src is cleared on unmount so the browser closes the stream.
 */
function MjpegStream({ cameraId, overlay = true, className = '', aspect = '16 / 9', alt, retryMs = 5000, onStatus, fit = 'contain' }: LiveStreamProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const inView = useInView(wrapRef);
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const onStatusRef = useRef(onStatus);
  useEffect(() => {
    onStatusRef.current = onStatus;
  });

  // retry loop after a failure
  useEffect(() => {
    if (!failed || !inView) return;
    const id = setTimeout(() => {
      setFailed(false);
      setLoaded(false);
      setAttempt((a) => a + 1);
    }, retryMs);
    return () => clearTimeout(id);
  }, [failed, inView, retryMs]);

  // Each src gets its own <img> (key=src). When one is detached we point it at a blank gif so the
  // browser closes the MJPEG connection right away instead of waiting for garbage collection.
  const attachImg = useCallback((el: HTMLImageElement | null) => {
    if (!el) return;
    imgRef.current = el;
    return () => {
      if (imgRef.current === el) imgRef.current = null;
      el.src = BLANK_GIF;
    };
  }, []);
  const isCurrent = (e: SyntheticEvent<HTMLImageElement>) => e.currentTarget === imgRef.current;

  const src = inView && !failed ? `${api.streamUrl(cameraId, overlay)}&_r=${attempt}` : undefined;

  useEffect(() => {
    setLoaded(false);
  }, [src]);

  // MJPEG streams do not fire `load` consistently across browsers -> detect the first frame by size.
  useEffect(() => {
    if (!src || loaded) return;
    const id = setInterval(() => {
      const img = imgRef.current;
      if (img && img.naturalWidth > 0) {
        setLoaded(true);
        onStatusRef.current?.(true);
      }
    }, 400);
    return () => clearInterval(id);
  }, [src, loaded]);

  return (
    <div ref={wrapRef} className={`relative overflow-hidden bg-black ${className}`} style={{ aspectRatio: aspect }}>
      {src && (
        <img
          key={src}
          ref={attachImg}
          src={src}
          alt={alt ?? `Camera ${cameraId} live`}
          loading="lazy"
          decoding="async"
          className={`absolute inset-0 h-full w-full ${fit === 'cover' ? 'object-cover' : 'object-contain'} transition-opacity ${loaded ? 'opacity-100' : 'opacity-0'}`}
          onLoad={(e) => {
            if (!isCurrent(e)) return;
            setLoaded(true);
            onStatusRef.current?.(true);
          }}
          onError={(e) => {
            if (!isCurrent(e)) return;
            setFailed(true);
            setLoaded(false);
            onStatusRef.current?.(false);
          }}
        />
      )}
      {(failed || !loaded) && <Placeholder failed={failed} inView={inView} />}
    </div>
  );
}
