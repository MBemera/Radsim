# Radsim Snippets

Copied snippets from this site:

- `Mascot.jsx` contains `MascotSvg`, `Mascot`, and `MascotCursor`.
- `mascot-cursor.css` contains the cursor follower, bob, squish, glow, and trail styles.
- `Splash.jsx` contains the animated splash logo screen.
- `animated-logo-splash.css` contains the splash logo float, grid drift, enter button, and exit animation styles.
- `assets/mascot.png` and `assets/logotype.png` are copied logo assets.

Use the cursor by loading `Mascot.jsx` and `mascot-cursor.css`, then rendering:

```jsx
<MascotCursor enabled={true} />
```

Use the animated logo splash by loading `Splash.jsx` and `animated-logo-splash.css`, then rendering:

```jsx
<Splash />
```

`Splash.jsx` expects the mascot image at `assets/mascot.png`. If you move the snippet into another project, copy `assets/mascot.png` beside it or update the image path.
