/* toko-picker.js — kotak cari untuk <select> panjang (Toko + jenis parser upload).
 *
 * Instalasi ini memakai 16+ toko dgn nama pendek dan mirip (MUL MXW M25 K25 …),
 * jadi menggulir <select> bawaan menyiksa. Modul ini membangun kontrol bertema
 * DI SEBELAH select asli: tombol pemicu + popover berisi kotak cari dan daftar
 * role="listbox" yang tersaring saat diketik.
 *
 * SELECT ASLI TETAP SUMBER KEBENARAN. Markup server sengaja TIDAK diubah isinya —
 * enhancement murni klien. Select hanya disembunyikan (kelas .tp-native) SETELAH
 * kontrol berhasil dibangun; bila apa pun gagal, select bawaan tetap tampil.
 *
 * Mode:
 * - `select[name=toko_id]` → pilih = set value + form.submit() (bilah atas / modal)
 * - `select.parser-pick` → pilih = set value saja (preview Upload & Parse; form
 *   commit nanti). Placeholder "Cari jenis…".
 *
 * Vanilla JS, tanpa dependensi & tanpa build step — gaya sama dgn range-select.js.
 */
(function () {
  'use strict';

  var AMBANG_CARI = 7; // kotak cari muncul bila jumlah opsi LEBIH dari ini
  // Chevron statis (tanpa data pengguna) — meniru .side details.grp>summary>.chev.
  var CHEV = '<svg class="tp-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" ' +
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6 9 12 15 18 9"/></svg>';

  var seq = 0;      // penomor id unik antar-kontrol di satu halaman
  var terbuka = null; // kontrol yang popovernya sedang terbuka (maksimal satu)

  function buat(tag, cls, teks) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    // Nama toko = data pengguna: SELALU lewat textContent, tak pernah innerHTML.
    if (teks != null) n.textContent = teks;
    return n;
  }

  // Batas bawah area yang masih terlihat: induk terdekat yang memotong/menggulir
  // (kartu modal Pengingat Toko punya max-height:90vh + overflow-y:auto), atau
  // tepi layar. Dipakai untuk memangkas tinggi daftar agar popover tak terpotong.
  function batasBawah(node) {
    for (var p = node.parentElement; p && p !== document.body; p = p.parentElement) {
      var ov = getComputedStyle(p).overflowY;
      if (ov === 'auto' || ov === 'scroll' || ov === 'hidden') {
        return Math.min(p.getBoundingClientRect().bottom, window.innerHeight);
      }
    }
    return window.innerHeight;
  }

  // Baca struktur <select> apa adanya: optgroup beserta isinya, plus option
  // lepas di luar optgroup ("Semua Toko" milik admin, dan daftar rata saat
  // hanya ada satu panel).
  function bacaOpsi(select) {
    var grup = [], anak = select.children, i, j, lepas = null;
    for (i = 0; i < anak.length; i++) {
      var n = anak[i];
      if (n.tagName === 'OPTGROUP') {
        var g = { label: n.getAttribute('label') || '', opsi: [] };
        for (j = 0; j < n.children.length; j++) {
          if (n.children[j].tagName === 'OPTION') g.opsi.push(satu(n.children[j]));
        }
        if (g.opsi.length) { grup.push(g); lepas = null; }
      } else if (n.tagName === 'OPTION') {
        if (!lepas) { lepas = { label: '', opsi: [] }; grup.push(lepas); }
        lepas.opsi.push(satu(n));
      }
    }
    return grup;
  }

  function satu(o) {
    return {
      nilai: o.value,
      teks: (o.textContent || '').trim(),
      terpilih: o.selected,
      disabled: !!o.disabled,
    };
  }

  function bangun(select) {
    if (select.dataset.tpDone) return;
    var form = select.form;
    // Mode submit (toko) butuh form. Mode value (parser) cukup parent.
    var modeValue = select.classList.contains('parser-pick');
    if (!modeValue && (!form || !select.parentNode)) return;
    if (!select.parentNode) return;

    var grup = bacaOpsi(select), jumlah = 0, i, k;
    for (i = 0; i < grup.length; i++) jumlah += grup[i].opsi.length;
    if (!jumlah) return;

    var id = 'tp' + (++seq);
    // parser-pick di sel tabel = medan penuh; toko di bilah atas = ringkas
    var host = buat(
      'div',
      'tp-host' + (modeValue || !select.closest('.toko-pick') ? ' tp-field' : '')
    );
    var trigger = buat('button', 'tp-trigger');
    trigger.type = 'button';
    trigger.setAttribute('aria-haspopup', 'listbox');
    trigger.setAttribute('aria-expanded', 'false');
    var kini = buat('span', 'tp-cur');
    trigger.appendChild(kini);
    trigger.insertAdjacentHTML('beforeend', CHEV);
    host.appendChild(trigger);

    var pop = buat('div', 'tp-pop');
    pop.hidden = true;
    host.appendChild(pop);
    var daftar = buat('div', 'tp-list');
    daftar.id = id + '-list';
    daftar.setAttribute('role', 'listbox');
    daftar.tabIndex = -1;

    var cari = null;
    if (jumlah > AMBANG_CARI) {
      cari = buat('input', 'tp-cari');
      cari.type = 'text';
      cari.placeholder = modeValue ? 'Cari jenis…' : 'Cari toko…';
      cari.autocomplete = 'off';
      cari.setAttribute('role', 'combobox');
      cari.setAttribute('aria-controls', daftar.id);
      cari.setAttribute('aria-expanded', 'true');
      cari.setAttribute('aria-autocomplete', 'list');
      cari.setAttribute('aria-label', modeValue ? 'Cari jenis file' : 'Cari toko');
      pop.appendChild(cari);
    }
    pop.appendChild(daftar);
    var kosong = buat(
      'div',
      'tp-kosong',
      modeValue ? 'Jenis tidak ditemukan.' : 'Toko tidak ditemukan.'
    );
    // role="status" (aria-live sopan): saringan yang nihil harus TERDENGAR juga,
    // bukan cuma terlihat — pesannya muncul tanpa fokus pindah ke mana pun.
    kosong.setAttribute('role', 'status');
    kosong.hidden = true;
    pop.appendChild(kosong);

    var item = [], terpilih = null;
    for (i = 0; i < grup.length; i++) {
      var wadah = daftar;
      if (grup[i].label) {
        wadah = buat('div', 'tp-grup');
        wadah.setAttribute('role', 'group');
        wadah.setAttribute('aria-label', grup[i].label);
        wadah.appendChild(buat('div', 'tp-grup-lbl', grup[i].label));
        daftar.appendChild(wadah);
      }
      for (k = 0; k < grup[i].opsi.length; k++) {
        var o = grup[i].opsi[k];
        // Opsi placeholder disabled (value="") tidak masuk daftar pilih —
        // labelnya tetap di trigger bila belum ada deteksi.
        if (o.disabled && !o.nilai) {
          if (o.terpilih && !terpilih) {
            kini.textContent = o.teks || '—';
          }
          continue;
        }
        var node = buat('div', 'tp-opt', o.teks);
        node.id = id + '-o' + item.length;
        node.setAttribute('role', 'option');
        node.setAttribute('aria-selected', o.terpilih ? 'true' : 'false');
        node.dataset.v = o.nilai;
        node.dataset.q = o.teks.toLowerCase();
        wadah.appendChild(node);
        item.push(node);
        if (o.terpilih) terpilih = node;
      }
    }
    if (terpilih) {
      kini.textContent = terpilih.textContent;
    } else if (!kini.textContent) {
      kini.textContent = '—';
    }
    trigger.title = modeValue
      ? ('Jenis: ' + kini.textContent + ' — klik untuk mencari/ganti')
      : ('Toko aktif: ' + kini.textContent + ' — klik untuk mengganti');

    var ctl = { host: host, sorot: null, tutup: null };
    var fokusAria = cari || daftar; // pembawa aria-activedescendant

    function tampak() {
      var v = [];
      for (var x = 0; x < item.length; x++) if (!item[x].hidden) v.push(item[x]);
      return v;
    }

    function setSorot(node) {
      if (ctl.sorot) ctl.sorot.classList.remove('tp-on');
      ctl.sorot = node || null;
      if (!node) { fokusAria.removeAttribute('aria-activedescendant'); return; }
      node.classList.add('tp-on');
      fokusAria.setAttribute('aria-activedescendant', node.id);
      // Gulirkan di dalam daftar saja — jangan sampai menggeser halaman.
      var atas = node.offsetTop, bawah = atas + node.offsetHeight;
      if (atas < daftar.scrollTop) daftar.scrollTop = atas;
      else if (bawah > daftar.scrollTop + daftar.clientHeight) daftar.scrollTop = bawah - daftar.clientHeight;
    }

    function saring() {
      var q = cari ? cari.value.trim().toLowerCase() : '', n = 0, x;
      for (x = 0; x < item.length; x++) {
        var ok = !q || item[x].dataset.q.indexOf(q) > -1;
        item[x].hidden = !ok;
        if (ok) n++;
      }
      var judul = daftar.querySelectorAll('.tp-grup'); // grup yang jadi kosong ikut hilang
      for (x = 0; x < judul.length; x++) judul[x].hidden = !judul[x].querySelector('.tp-opt:not([hidden])');
      kosong.hidden = n > 0;
      setSorot(n ? tampak()[0] : null);
    }

    // Popover: parser di sel tabel pakai position:fixed agar lolos overflow
    // .twrap (overflow-x:auto → clipping). Kotak cari di luar .tp-list (flex)
    // supaya tidak ikut gulir. Toko bilah atas tetap absolute di host.
    function tempatkan() {
      daftar.style.maxHeight = '';
      if (modeValue) {
        var r = trigger.getBoundingClientRect();
        var lebar = Math.max(Math.ceil(r.width), 220);
        var left = Math.min(r.left, window.innerWidth - lebar - 8);
        if (left < 8) left = 8;
        pop.classList.add('tp-pop-fixed');
        pop.style.position = 'fixed';
        pop.style.left = left + 'px';
        pop.style.right = 'auto';
        pop.style.width = lebar + 'px';
        pop.style.minWidth = lebar + 'px';
        pop.style.zIndex = '200';
        var ruangBawah = window.innerHeight - r.bottom - 12;
        var ruangAtas = r.top - 12;
        var headH = cari ? 48 : 8; // perkiraan tinggi kotak cari + margin
        var maxList = 260;
        if (ruangBawah < 160 && ruangAtas > ruangBawah) {
          // buka ke atas
          pop.style.top = 'auto';
          pop.style.bottom = (window.innerHeight - r.top + 6) + 'px';
          maxList = Math.min(260, Math.max(120, ruangAtas - headH));
        } else {
          pop.style.bottom = 'auto';
          pop.style.top = (r.bottom + 6) + 'px';
          maxList = Math.min(260, Math.max(120, ruangBawah - headH));
        }
        daftar.style.maxHeight = maxList + 'px';
        return;
      }
      pop.classList.remove('tp-pop-fixed');
      pop.style.position = '';
      pop.style.left = '';
      pop.style.right = '';
      pop.style.top = '';
      pop.style.bottom = '';
      pop.style.width = '';
      pop.style.minWidth = '';
      pop.style.zIndex = '';
      var luber = pop.getBoundingClientRect().bottom + 8 - batasBawah(host);
      if (luber > 0) daftar.style.maxHeight = Math.max(140, daftar.clientHeight - luber) + 'px';
    }

    function onScrollOrResize() {
      if (!pop.hidden && modeValue) tempatkan();
    }

    function buka() {
      if (terbuka && terbuka !== ctl) terbuka.tutup(false);
      pop.hidden = false;
      trigger.setAttribute('aria-expanded', 'true');
      terbuka = ctl;
      if (cari) cari.value = '';
      saring();
      // Tinggi final dulu, baru sorot: menggulir toko aktif ke dalam pandangan
      // butuh tinggi daftar yang sudah dipangkas, kalau tidak ia meleset.
      tempatkan();
      if (terpilih && !terpilih.hidden) setSorot(terpilih);
      fokusAria.focus();
      if (modeValue) {
        window.addEventListener('scroll', onScrollOrResize, true);
        window.addEventListener('resize', onScrollOrResize);
      }
    }

    function tutup(kembalikanFokus) {
      if (pop.hidden) return;
      pop.hidden = true;
      trigger.setAttribute('aria-expanded', 'false');
      if (terbuka === ctl) terbuka = null;
      if (modeValue) {
        window.removeEventListener('scroll', onScrollOrResize, true);
        window.removeEventListener('resize', onScrollOrResize);
        pop.classList.remove('tp-pop-fixed');
        pop.style.position = '';
        pop.style.left = '';
        pop.style.right = '';
        pop.style.top = '';
        pop.style.bottom = '';
        pop.style.width = '';
        pop.style.minWidth = '';
        pop.style.zIndex = '';
        daftar.style.maxHeight = '';
      }
      if (kembalikanFokus) trigger.focus();
    }
    ctl.tutup = tutup;

    function pilih(node) {
      var nilai = node.dataset.v;
      // Memilih nilai yang sedang aktif = tak ada perubahan.
      if (select.value === nilai) { tutup(true); return; }
      select.value = nilai;
      // Segarkan label + aria pada opsi
      for (var x = 0; x < item.length; x++) {
        item[x].setAttribute('aria-selected', item[x] === node ? 'true' : 'false');
      }
      terpilih = node;
      kini.textContent = node.textContent;
      trigger.title = modeValue
        ? ('Jenis: ' + kini.textContent + ' — klik untuk mencari/ganti')
        : ('Toko aktif: ' + kini.textContent + ' — klik untuk mengganti');
      try {
        select.dispatchEvent(new Event('change', { bubbles: true }));
      } catch (err) { /* IE tua — abaikan */ }
      if (modeValue) {
        tutup(true);
        return;
      }
      tutup(false);
      if (form) form.submit();
    }

    trigger.addEventListener('click', function () {
      if (pop.hidden) buka(); else tutup(true);
    });

    // Handler panah di bawah menempel di popover, jadi saat popover tertutup
    // pemicu tuli terhadap panah — padahal <select> bawaan membuka daftarnya
    // dgn ArrowDown/ArrowUp. Samakan.
    trigger.addEventListener('keydown', function (e) {
      if (pop.hidden && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
        e.preventDefault(); // jangan menggulir halaman
        buka();
      }
    });

    daftar.addEventListener('click', function (e) {
      var node = e.target.closest ? e.target.closest('.tp-opt') : null;
      if (node) pilih(node);
    });

    if (cari) cari.addEventListener('input', saring);

    pop.addEventListener('keydown', function (e) {
      var v, i2;
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        v = tampak();
        if (!v.length) return;
        i2 = v.indexOf(ctl.sorot);
        setSorot(e.key === 'ArrowDown' ? v[(i2 + 1) % v.length] : v[(i2 - 1 + v.length) % v.length]);
      } else if (e.key === 'Enter') {
        e.preventDefault(); // kotak cari ada DI DALAM form — jangan submit implisit
        if (ctl.sorot) pilih(ctl.sorot);
      } else if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation(); // jangan ikut menutup modal Pengingat Toko
        tutup(true);
      } else if (e.key === 'Tab') {
        // Fokus keluar → popover tak boleh tertinggal terbuka. Fokus WAJIB
        // dikembalikan ke pemicu di sini juga (masih sebelum aksi bawaan Tab
        // jalan): menyembunyikan popover saat fokus masih di dalamnya membuat
        // Firefox membuang fokus ke <body>, jadi Tab melempar pengguna ke puncak
        // halaman. Dgn pemicu yang kembali berfokus, Tab lanjut ke kontrol
        // berikutnya persis seperti <select> bawaan.
        tutup(true);
      }
    });

    // Host baru menyentuh halaman di baris ini — dan select bawaan baru
    // disembunyikan setelahnya: bila ada yang meledak di atas, pemilih lama utuh.
    select.parentNode.insertBefore(host, select.nextSibling);
    select.classList.add('tp-native');
    select.dataset.tpDone = '1';
  }

  // pointerdown, bukan mousedown: iOS Safari hanya mensintesis event tetikus
  // untuk target yang dianggapnya bisa diklik, jadi ketukan di latar halaman
  // yang inert tak akan menutup popover. pointerdown menyeragamkan tetikus,
  // sentuh, dan pena — dan 375px adalah viewport kelas satu di app ini.
  document.addEventListener('pointerdown', function (e) {
    if (terbuka && !terbuka.host.contains(e.target)) terbuka.tutup(false);
  });

  function init() {
    var s = document.querySelectorAll(
      'select[name="toko_id"]:not([data-tp-done]), select.parser-pick:not([data-tp-done])'
    );
    for (var i = 0; i < s.length; i++) {
      // Kegagalan satu kontrol tidak boleh mematikan pemilih: diam saja,
      // select bawaannya masih tampil. Halaman tanpa select ini (mis. login)
      // sama sekali tak terpengaruh.
      try { bangun(s[i]); } catch (err) { /* sengaja diabaikan */ }
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
  // htmx bisa mengganti potongan halaman setelah skrip ini jalan.
  document.addEventListener('htmx:afterSettle', init);
})();
