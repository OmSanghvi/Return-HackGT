// The DOM side of the painted window. A Stage is a transparent frame the WebGL world paints into;
// without WebGL (or with reduced motion) it shows the painting as a plain drifting image instead.
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type * as React from 'react';
import { SCENES, type SceneKey } from './scenes';
import { immersive, useWorld } from './state';

interface StageProps { scene: SceneKey; mist?: number; zoom?: number; blur?: number; petals?: boolean; fast?: boolean; scrim?: 'center' | 'bottom' | 'none'; className?: string; style?: React.CSSProperties; children?: React.ReactNode; label?: string }

export function Stage({ scene, mist = 0, zoom = 0, blur = 0, petals = false, fast, scrim = 'bottom', className, style, children, label }: StageProps) {
  const ref = useRef<HTMLElement>(null);
  const ready = useWorld((w) => w.ready);
  useLayoutEffect(() => {
    useWorld.setState({ stage: ref.current });
    return () => { if (useWorld.getState().stage === ref.current) useWorld.setState({ stage: null }); };
  }, []);
  useEffect(() => {
    useWorld.setState({ scene, mist, zoom, blur, petals, fast: !!fast });
    document.documentElement.dataset.theme = SCENES[scene].dusk ? 'dusk' : 'day';
  }, [scene, mist, zoom, blur, petals, fast]);
  const painted = immersive && ready;
  const fallbackFilter = mist || blur ? `blur(${blur * 14}px) blur(${mist * 16}px) saturate(${1 - mist * 0.6})` : undefined;
  return (
    <section ref={ref} className={'rt-hero rt-hero-drift app-stage ' + (className || '')} style={style} aria-label={label}>
      <div className="rt-hero-media" aria-hidden>
        {!painted && <div className="rt-drift"><img className="rt-img" src={SCENES[scene].image} alt="" style={{ filter: fallbackFilter }} /></div>}
        {scrim !== 'none' && <div className={scrim === 'center' ? 'rt-scrim-center' : 'rt-scrim-bottom'} />}
      </div>
      {children}
    </section>
  );
}

/** An arched window onto a room, painted by the WebGL world (CSS arch as fallback). */
export function PortalWindow({ src, depth, entering, className, onClick, label }: { src: string; depth?: string; entering?: boolean; className?: string; onClick?: () => void; label: string }) {
  const ref = useRef<HTMLButtonElement>(null);
  const ready = useWorld((w) => w.ready);
  const [painted] = useState(() => immersive);
  useLayoutEffect(() => {
    if (!painted || !ref.current) return;
    useWorld.setState({ portal: { el: ref.current, src, depth } });
    return () => useWorld.setState({ portal: null });
  }, [src, depth, painted]);
  return (
    <button ref={ref} type="button" className={'app-portal ' + (className || '')} data-state={entering ? 'entering' : 'idle'} onClick={onClick} aria-label={label}>
      {!(painted && ready) && <img className="rt-img" src={src} alt="" />}
    </button>
  );
}
