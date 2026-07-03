/* ───────────────────────────────────────────────────────────────
 * build-premium-website-twist-threejs — random roll (this round)
 *   WebGL effect : Text rendered as particles that assemble/scatter (trend-confirmed: Codrops Gommage 2026-01, dissolve particles 2025-02)
 *   Motion       : Page transition wipe/preloader · Horizontal scroll rail (app-adapted)
 *   Visual       : Grainy/noise texture overlay (re-rolled from Editorial — ledger conflict LumisLinks)
 *   Anchor       : Lusion / Locomotive agency style
 *   Refs adapted : tympanus.net Gommage → noise-driven progress; codrops dissolve → per-particle seed ease; existing login r128 field → replaced
 *   Date         : 2026-07-03
 * ─────────────────────────────────────────────────────────────── */
import * as THREE from 'three';

const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
const canvas = document.getElementById('gl');
const isMobile = matchMedia('(max-width: 768px)').matches;

// Card entrance (dipertahankan dari login lama — GSAP UMD global)
if (window.gsap && !reduce) {
  gsap.from('#card', { y: 24, opacity: 0, duration: .9, ease: 'power3.out', delay: .12 });
  gsap.from('.auth-card h1 .kin', { opacity: 0, y: 16, duration: .9, ease: 'power3.out', delay: .26 });
}

function bail(cls) { document.documentElement.classList.add(cls); }
if (reduce) { bail('reduced'); }
else {
  let renderer = null;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: false, alpha: true, powerPreference: 'high-performance' });
  } catch (e) { renderer = null; }
  if (!renderer) { bail('no-webgl'); }
  else {
    // Zodiak harus loaded sebelum sampling — kalau tidak, canvas merasterisasi serif fallback (glyph salah).
    Promise.race([
      document.fonts.load('700 150px Zodiak'),
      new Promise((res) => setTimeout(res, 800)),
    ]).then(() => init(renderer), () => init(renderer)); // fonts.load bisa REJECT (fetch font gagal) — tetap init; sampling serif fallback lebih baik daripada hero kosong
  }
}

function sampleText(text) {
  const W = 2048, H = 512, c = document.createElement('canvas');
  c.width = W; c.height = H;
  const x = c.getContext('2d');
  // Fit font ke lebar canvas dulu supaya teks penuh ("TRUTH OF AUDITOR") tak terpotong di tepi canvas.
  let fs = 300;
  x.font = `700 ${fs}px Zodiak, Georgia, serif`;
  while (x.measureText(text).width > W * 0.92 && fs > 40) { fs -= 6; x.font = `700 ${fs}px Zodiak, Georgia, serif`; }
  x.fillStyle = '#fff';
  x.textAlign = 'center'; x.textBaseline = 'middle';
  x.fillText(text, W / 2, H / 2);
  const img = x.getImageData(0, 0, W, H).data, pts = [];
  const step = isMobile ? 5 : 3;                       // kepadatan sampling (canvas lebih besar → step longgar)
  let halfW = 1;                                        // extent teks (px) untuk fit ke viewport di init()
  for (let y = 0; y < H; y += step) for (let px = 0; px < W; px += step)
    if (img[(y * W + px) * 4 + 3] > 128) {
      const wx = px - W / 2, wy = -(y - H / 2);
      pts.push([wx, wy]);
      if (Math.abs(wx) > halfW) halfW = Math.abs(wx);
    }
  return { pts, halfW };
}

function init(renderer) {
  const CAP = isMobile ? 7000 : 20000;
  const sampled = sampleText('TRUTH OF AUDITOR');
  const halfW = sampled.halfW;
  let pts = sampled.pts;
  if (pts.length > CAP) pts = pts.filter((_, i) => i % Math.ceil(pts.length / CAP) === 0);
  const N = pts.length;
  // Fit wordmark ke viewport (~88% lebar) + naikkan dari tengah; responsif terhadap aspect.
  const CAM_Z = 9, VFOV = 45 * Math.PI / 180;
  function layout() {
    const visH = 2 * CAM_Z * Math.tan(VFOV / 2);
    const visW = visH * (innerWidth / innerHeight);
    return { visW, visH, scale: (visW * 0.44) / halfW, yOff: visH * 0.18 };
  }
  let lay = layout();

  const scene = new THREE.Scene();
  const cam = new THREE.PerspectiveCamera(45, innerWidth / innerHeight, .1, 50);
  cam.position.z = 9;
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setSize(innerWidth, innerHeight);

  const pos = new Float32Array(N * 3), tgt = new Float32Array(N * 3), seed = new Float32Array(N);
  for (let i = 0; i < N; i++) {
    pos[i * 3] = (Math.random() - .5) * 22; pos[i * 3 + 1] = (Math.random() - .5) * 14; pos[i * 3 + 2] = (Math.random() - .5) * 8;
    tgt[i * 3] = pts[i][0] * lay.scale; tgt[i * 3 + 1] = pts[i][1] * lay.scale + lay.yOff; tgt[i * 3 + 2] = 0;
    seed[i] = Math.random();
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('aTarget', new THREE.BufferAttribute(tgt, 3));
  geo.setAttribute('aSeed', new THREE.BufferAttribute(seed, 1));

  // uPr: gl_PointSize dalam device px — tanpa kompensasi, layar dpr=1 melihat partikel
  // 2× ukuran CSS yang di-tune di retina (blob buram, QA Task 9). Normalisasi ke baseline dpr=2.
  const uni = { uProgress: { value: 0 }, uPointer: { value: new THREE.Vector2(99, 99) }, uTime: { value: 0 },
    uPr: { value: renderer.getPixelRatio() * .5 } };
  const mat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false,
    uniforms: uni,
    vertexShader: `
      attribute vec3 aTarget; attribute float aSeed;
      uniform float uProgress; uniform float uTime; uniform vec2 uPointer; uniform float uPr;
      varying float vSeed;
      void main(){
        vSeed = aSeed;
        float p = clamp(uProgress * (1.2 - aSeed * .4), 0., 1.);
        p = 1. - pow(1. - p, 3.);                       // ease-out cubic per partikel
        vec3 base = mix(position, aTarget, p);
        base.x += sin(uTime * .6 + aSeed * 6.28) * .015; // idle breathing
        base.y += cos(uTime * .5 + aSeed * 6.28) * .015;
        vec2 d = base.xy - uPointer;                     // cursor repulsion
        float r = length(d);
        if (r < 1.2) base.xy += normalize(d) * (1.2 - r) * .7;
        vec4 mv = modelViewMatrix * vec4(base, 1.);
        gl_PointSize = (2.4 - aSeed) * (3.2 / -mv.z) * uPr * ${isMobile ? '55.' : '80.'};
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: `
      varying float vSeed;
      void main(){
        float d = length(gl_PointCoord - .5); if (d > .5) discard;
        vec3 bone = vec3(.914, .894, .839);
        vec3 verdigris = vec3(.247, .642, .471);
        vec3 col = mix(bone, verdigris, step(.93, vSeed));  // ~7% partikel "matched"
        gl_FragColor = vec4(col, smoothstep(.5, .15, d) * .9);
      }`
  });
  scene.add(new THREE.Points(geo, mat));

  const ndc = new THREE.Vector2(99, 99);
  addEventListener('pointermove', (e) => {
    ndc.set((e.clientX / innerWidth) * 2 - 1, -(e.clientY / innerHeight) * 2 + 1);
    // proyeksikan ke plane z=0 kamera sederhana:
    uni.uPointer.value.set(ndc.x * lay.visW / 2, ndc.y * lay.visH / 2);
  });
  addEventListener('resize', () => {
    cam.aspect = innerWidth / innerHeight; cam.updateProjectionMatrix();
    renderer.setSize(innerWidth, innerHeight);
    lay = layout();                                    // refit wordmark ke ukuran/aspect baru
    for (let i = 0; i < N; i++) { tgt[i * 3] = pts[i][0] * lay.scale; tgt[i * 3 + 1] = pts[i][1] * lay.scale + lay.yOff; }
    geo.attributes.aTarget.needsUpdate = true;
  });

  // assemble saat load (GSAP UMD sudah ada di halaman)
  let assembled = false;
  if (window.gsap) gsap.to(uni.uProgress, { value: 1, duration: 2.2, ease: 'power2.inOut', delay: .3, onComplete: () => { assembled = true; } });
  else { uni.uProgress.value = 1; assembled = true; }

  // reaktif: partikel "scan"/settle ulang saat user fokus ke field (setelah assemble; autofocus awal tidak memicu)
  document.querySelectorAll('form input').forEach((f) => f.addEventListener('focus', () => {
    if (assembled && window.gsap) gsap.fromTo(uni.uProgress, { value: .9 }, { value: 1, duration: .9, ease: 'power2.out', overwrite: true });
  }));

  // scatter + wipe saat submit login
  const form = document.querySelector('form');
  if (form) form.addEventListener('submit', () => {
    if (window.gsap) gsap.to(uni.uProgress, { value: 0, duration: .8, ease: 'power3.in' });
  });

  let raf = null, running = false;
  const clock = new THREE.Clock();
  function tick() {
    uni.uTime.value = clock.getElapsedTime();
    renderer.render(scene, cam);
    raf = requestAnimationFrame(tick);
  }
  // load di background tab: jangan start loop dulu — start di visible pertama (hindari chain RAF beku menumpuk)
  if (!document.hidden) { running = true; raf = requestAnimationFrame(tick); }
  addEventListener('pagehide', () => { cancelAnimationFrame(raf); running = false; geo.dispose(); mat.dispose(); renderer.dispose(); });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { cancelAnimationFrame(raf); running = false; }
    else if (!running) { running = true; raf = requestAnimationFrame(tick); } // guard: satu chain saja
  });
}
