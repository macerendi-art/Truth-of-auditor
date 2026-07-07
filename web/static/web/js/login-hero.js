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
    return { visW, visH, scale: (visW * 0.44) / halfW, yOff: visH * 0.30 };
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
        vec3 bone  = vec3(.914, .894, .839);   // #E9E4D6 --text  (badan wordmark)
        vec3 azure = vec3(.145, .388, .922);   // #2563eb --brand  (partikel "matched")
        vec3 cyan  = vec3(.133, .827, .933);   // #22d3ee --brand2 (aksen sekunder, selaras interior)
        vec3 col = bone;
        col = mix(col, azure, step(.92, vSeed));   // ~8% biru "matched"
        col = mix(col, cyan,  step(.96, vSeed));   // ~4% cyan di atasnya → mirror duo biru+cyan interior
        gl_FragColor = vec4(col, smoothstep(.5, .15, d) * .9);
      }`
  });
  const word = new THREE.Points(geo, mat); word.renderOrder = 0; scene.add(word);

  // ── Bintang kelap-kelip (starfield jauh, tiap bintang berkedip independen) ──
  //    Selaras palet interior: mayoritas bone/cream, sebagian kecil kilau biru/cyan.
  const STAR_N = isMobile ? 300 : 620;
  const sPos = new Float32Array(STAR_N * 3), sSeed = new Float32Array(STAR_N), sTone = new Float32Array(STAR_N);
  for (let i = 0; i < STAR_N; i++) {
    sPos[i * 3]     = (Math.random() - .5) * 52;      // sebar jauh melebihi viewport → kepadatan rendah
    sPos[i * 3 + 1] = (Math.random() - .5) * 32;
    sPos[i * 3 + 2] = -7 - Math.random() * 16;         // jauh di belakang wordmark (z=0)
    sSeed[i] = Math.random();
    const r = Math.random();
    sTone[i] = r > .94 ? 2 : (r > .86 ? 1 : 0);        // ~6% cyan, ~8% biru, sisanya bone
  }
  const starGeo = new THREE.BufferGeometry();
  starGeo.setAttribute('position', new THREE.BufferAttribute(sPos, 3));
  starGeo.setAttribute('aSeed', new THREE.BufferAttribute(sSeed, 1));
  starGeo.setAttribute('aTone', new THREE.BufferAttribute(sTone, 1));
  const starUni = { uTime: { value: 0 }, uPr: { value: renderer.getPixelRatio() * .5 } };
  const starMat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: starUni,
    vertexShader: `
      attribute float aSeed; attribute float aTone;
      uniform float uTime; uniform float uPr;
      varying float vTw; varying float vTone;
      void main(){
        vTone = aTone;
        float sp = .6 + aSeed * 1.7;                          // kecepatan kedip per bintang
        float tw = .5 + .5 * sin(uTime * sp + aSeed * 6.283);  // 0..1 independen (fase acak)
        vTw = tw;
        vec4 mv = modelViewMatrix * vec4(position, 1.);
        float sz = (.35 + aSeed * .8) * (1. + tw * .35);       // pinpoint kecil, berkedip halus
        gl_PointSize = sz * uPr * ${isMobile ? '54.' : '70.'} / -mv.z;
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: `
      varying float vTw; varying float vTone;
      void main(){
        float d = length(gl_PointCoord - .5); if (d > .5) discard;
        vec3 bone  = vec3(.914, .894, .839);
        vec3 azure = vec3(.145, .388, .922);
        vec3 cyan  = vec3(.133, .827, .933);
        vec3 col = vTone > 1.5 ? cyan : (vTone > .5 ? azure : bone);
        float a = smoothstep(.5, .08, d) * (.18 + .55 * vTw);  // faint→terang, kedip lembut
        gl_FragColor = vec4(col, a);
      }`
  });
  const stars = new THREE.Points(starGeo, starMat); stars.renderOrder = -1; scene.add(stars);

  // ── Komet berinterval (seperti di luar angkasa) ──
  //    Satu komet melintas tiap COMET_EVERY (± jitter). Ekor memudar putih→cyan (dingin).
  const COMET_EVERY = 9.0;     // detik antar komet — diatur di sini
  const COMET_JITTER = 3.0;    // ± variasi acak
  const COMET_DUR = 1.7;       // durasi satu lintasan
  const TRAIL_N = 44;
  const tIdx = new Float32Array(TRAIL_N);
  for (let i = 0; i < TRAIL_N; i++) tIdx[i] = i;
  const cometGeo = new THREE.BufferGeometry();
  cometGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(TRAIL_N * 3), 3)); // dihitung di shader dari uHead
  cometGeo.setAttribute('aIdx', new THREE.BufferAttribute(tIdx, 1));
  const cometUni = {
    uHead: { value: new THREE.Vector3(0, 0, -1.5) }, uDir: { value: new THREE.Vector3(1, 0, 0) },
    uSpacing: { value: .032 }, uN: { value: TRAIL_N }, uActive: { value: 0 },
    uPr: { value: renderer.getPixelRatio() * .5 }
  };
  const cometMat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending,
    uniforms: cometUni,
    vertexShader: `
      attribute float aIdx;
      uniform vec3 uHead; uniform vec3 uDir; uniform float uSpacing; uniform float uN; uniform float uPr;
      varying float vT;
      void main(){
        float f = aIdx / (uN - 1.);                  // 0 kepala → 1 ekor
        vT = f;
        vec3 p = uHead - uDir * (aIdx * uSpacing);    // ekor tertinggal di belakang kepala
        vec4 mv = modelViewMatrix * vec4(p, 1.);
        gl_PointSize = mix(4.6, .3, f) * uPr * 40. / -mv.z;  // kepala besar → ekor kecil
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: `
      uniform float uActive;
      varying float vT;
      void main(){
        float d = length(gl_PointCoord - .5); if (d > .5) discard;
        vec3 headCol = vec3(.86, .94, 1.0);           // kepala putih-biru dingin
        vec3 cyan    = vec3(.133, .827, .933);        // ekor cyan
        vec3 col = mix(headCol, cyan, vT);
        float a = uActive * pow(1. - vT, 1.6) * smoothstep(.5, .05, d);  // ekor memudar
        gl_FragColor = vec4(col, a);
      }`
  });
  const comet = new THREE.Points(cometGeo, cometMat); comet.renderOrder = 2; comet.frustumCulled = false; scene.add(comet);

  let cometActive = false, cometT0 = 0, cometNext = 4.0;   // komet pertama ~4 dtk (biar wordmark rakit dulu)
  const cStart = new THREE.Vector3(), cEnd = new THREE.Vector3();
  function spawnComet() {
    const vw = lay.visW, vh = lay.visH, fromLeft = Math.random() < .5;
    const sx = (fromLeft ? -1 : 1) * vw * (.45 + Math.random() * .2);
    const sy = vh * (.44 + Math.random() * .12);                        // mulai di langit atas
    cStart.set(sx, sy, -1.5);
    cEnd.set(-sx * (.5 + Math.random() * .45), vh * (.30 + Math.random() * .12), -1.5); // turun landai, tetap di atas wordmark
    cometUni.uDir.value.copy(cEnd).sub(cStart).normalize();
    cometActive = true; cometUni.uActive.value = 0;
  }
  function updateComet(t) {
    if (!cometActive) { if (t >= cometNext) { cometT0 = t; spawnComet(); } return; }
    const p = (t - cometT0) / COMET_DUR;
    if (p >= 1) {
      cometActive = false; cometUni.uActive.value = 0;
      cometNext = t + COMET_EVERY + (Math.random() * 2 - 1) * COMET_JITTER;
      return;
    }
    const e = p < .5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;   // easeInOut halus
    cometUni.uHead.value.lerpVectors(cStart, cEnd, e);
    cometUni.uActive.value = Math.min(1, Math.min(p * 6, (1 - p) * 6)); // fade in/out di ujung lintasan
  }

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
    const et = clock.getElapsedTime();
    uni.uTime.value = et;
    starUni.uTime.value = et;
    updateComet(et);
    renderer.render(scene, cam);
    raf = requestAnimationFrame(tick);
  }
  // load di background tab: jangan start loop dulu — start di visible pertama (hindari chain RAF beku menumpuk)
  if (!document.hidden) { running = true; raf = requestAnimationFrame(tick); }
  addEventListener('pagehide', () => { cancelAnimationFrame(raf); running = false;
    geo.dispose(); mat.dispose(); starGeo.dispose(); starMat.dispose(); cometGeo.dispose(); cometMat.dispose(); renderer.dispose(); });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { cancelAnimationFrame(raf); running = false; }
    else if (!running) { running = true; raf = requestAnimationFrame(tick); } // guard: satu chain saja
  });
}
