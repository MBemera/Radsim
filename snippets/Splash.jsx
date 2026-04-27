const { useState: useStateSp, useEffect: useEffectSp } = React;

/* Full-screen splash: mascot + Enter Radsim button. Dismissed to localStorage. */
function Splash() {
  const [open, setOpen] = useStateSp(true);
  const [leaving, setLeaving] = useStateSp(false);

  useEffectSp(() => {
    document.body.style.overflow = open ? "hidden" : "";
    return () => { document.body.style.overflow = ""; };
  }, [open]);

  const enter = () => {
    setLeaving(true);
    setTimeout(() => setOpen(false), 650);
  };

  if (!open) return null;

  return (
    <div className={`splash ${leaving ? "is-leaving" : ""}`}>
      <div className="splash-bg" aria-hidden="true" />
      <div className="splash-grid" aria-hidden="true" />
      <div className="splash-inner">
        <div className="splash-mascot">
          <img src="assets/mascot.png" alt="Radsim mascot" />
        </div>
        <button className="splash-btn" onClick={enter}>
          <span>Enter Radsim</span>
          <span className="sb-arrow">→</span>
        </button>
      </div>
    </div>
  );
}

window.Splash = Splash;
