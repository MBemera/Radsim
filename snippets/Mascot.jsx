/* ============================================================
   MASCOT — inline SVG of the Radsim bot + cursor follower
   ============================================================ */

const { useEffect: useEffectM, useState: useStateM, useRef: useRefM } = React;

/* Inline SVG of the Radsim mascot — neon cyan cube-head bot with lightning tail.
   Matches the glow character from the logo. Strokes-only so the glow filter
   reads cleanly on dark. */
function MascotSvg({ size = 44, eyes = "open" }) {
  // eye shapes for blink
  const eyeY = eyes === "closed" ? 44 : 38;
  const eyeH = eyes === "closed" ? 2 : 14;
  return (
    <svg viewBox="0 0 100 100" width={size} height={size} aria-hidden="true">
      <defs>
        <filter id="mx-glow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="1.2" result="b1" />
          <feGaussianBlur in="SourceGraphic" stdDeviation="0.4" result="b2" />
          <feMerge>
            <feMergeNode in="b1" />
            <feMergeNode in="b2" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      <g fill="none" stroke="#7af4ff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" filter="url(#mx-glow)">
        {/* head */}
        <rect x="28" y="22" width="44" height="36" rx="6" />
        {/* eyes */}
        <rect x="39" y={eyeY} width="4" height={eyeH} rx="2" fill="#7af4ff" stroke="none" />
        <rect x="57" y={eyeY} width="4" height={eyeH} rx="2" fill="#7af4ff" stroke="none" />
        {/* mouth (smile) */}
        <path d="M 42 50 Q 50 56 58 50" />
        {/* neck */}
        <line x1="46" y1="58" x2="46" y2="64" />
        <line x1="54" y1="58" x2="54" y2="64" />
        {/* body */}
        <rect x="38" y="64" width="24" height="18" rx="3" />
        {/* arms */}
        <rect x="22" y="68" width="14" height="16" rx="3" />
        <rect x="64" y="68" width="14" height="16" rx="3" />
        {/* lightning tail */}
        <path d="M 62 60 L 78 52 L 72 60 L 86 50 L 78 70 L 84 66" strokeWidth="2.2" />
      </g>
    </svg>
  );
}

/* Static mascot for inline usage (logo mark, stickers, etc.) */
function Mascot({ size = 64, float = true, className = "" }) {
  return (
    <span className={`mascot-static ${float ? "m-float" : ""} ${className}`} style={{ display: "inline-block", width: size, height: size, lineHeight: 0 }}>
      <MascotSvg size={size} />
    </span>
  );
}

/* Cursor follower — mascot chases the mouse with spring-like lag,
   bobs when idle, squishes on click, shows a trail behind. */
function MascotCursor({ enabled = true }) {
  const posRef = useRefM({ x: -100, y: -100, tx: -100, ty: -100 });
  const elRef = useRefM(null);
  const trailRef = useRefM([]);
  const trailElsRef = useRefM([]);
  const [hovering, setHovering] = useStateM(false);
  const [clicking, setClicking] = useStateM(false);
  const [blink, setBlink] = useStateM(false);

  useEffectM(() => {
    if (!enabled) return;

    const move = (e) => {
      posRef.current.tx = e.clientX;
      posRef.current.ty = e.clientY;
    };
    const hoverOn = (e) => {
      const t = e.target;
      if (t && t.closest && t.closest("a, button, [role='button'], .install-bar-copy, .nav-cta, .btn")) {
        setHovering(true);
      } else {
        setHovering(false);
      }
    };
    const down = () => setClicking(true);
    const up   = () => setClicking(false);

    window.addEventListener("mousemove", move, { passive: true });
    window.addEventListener("mousemove", hoverOn, { passive: true });
    window.addEventListener("mousedown", down);
    window.addEventListener("mouseup", up);

    // randomized blinking
    let blinkTimer;
    const scheduleBlink = () => {
      blinkTimer = setTimeout(() => {
        setBlink(true);
        setTimeout(() => setBlink(false), 130);
        scheduleBlink();
      }, 2200 + Math.random() * 3800);
    };
    scheduleBlink();

    let raf;
    const tick = () => {
      const p = posRef.current;
      // spring follow
      p.x += (p.tx - p.x) * 0.18;
      p.y += (p.ty - p.y) * 0.18;
      if (elRef.current) {
        elRef.current.style.transform = `translate(${p.x}px, ${p.y}px) translate(-50%, -50%)`;
      }

      // trail sampling
      trailRef.current.unshift({ x: p.x, y: p.y });
      if (trailRef.current.length > 10) trailRef.current.length = 10;
      trailElsRef.current.forEach((el, i) => {
        const t = trailRef.current[i + 1];
        if (!el) return;
        if (t) {
          el.style.transform = `translate(${t.x}px, ${t.y}px) translate(-50%, -50%) scale(${1 - i * 0.08})`;
          el.style.opacity = String(Math.max(0, 0.35 - i * 0.035));
        } else {
          el.style.opacity = "0";
        }
      });

      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);

    return () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mousemove", hoverOn);
      window.removeEventListener("mousedown", down);
      window.removeEventListener("mouseup", up);
      clearTimeout(blinkTimer);
      cancelAnimationFrame(raf);
    };
  }, [enabled]);

  if (!enabled) return null;

  const trails = Array.from({ length: 8 });

  return (
    <>
      {trails.map((_, i) => (
        <div
          key={i}
          ref={(el) => (trailElsRef.current[i] = el)}
          className="mascot-trail"
        />
      ))}
      <div
        ref={elRef}
        className={`mascot-cursor ${hovering ? "is-hovering" : ""} ${clicking ? "is-clicking" : ""}`}
        aria-hidden="true"
      >
        <div className="m-bob">
          <MascotSvg size={44} eyes={blink ? "closed" : "open"} />
        </div>
      </div>
    </>
  );
}

window.Mascot = Mascot;
window.MascotSvg = MascotSvg;
window.MascotCursor = MascotCursor;
