/* toko-picker.js — kotak cari untuk <select> panjang
 * (Toko + jenis parser upload + file mutasi bank).
 *
 * SELECT ASLI TETAP SUMBER KEBENARAN. Enhancement murni klien; select disembunyikan
 * (.tp-native) HANYA setelah kontrol berhasil dibangun.
 *
 * Mode:
 * - `select[name=toko_id]` → tombol + popover (+ cari bila opsi banyak) → form.submit()
 * - `select.parser-pick` → SATU input combobox (ketik = saring, pilih = set value).
 * - `select.file-pick` → SATU input combobox file mutasi (ketik = saring, pilih = submit GET).
 *
 * Vanilla JS, tanpa dependensi.
 */
(function () {
  'use strict';

  var AMBANG_CARI = 7;
  var CHEV = '<svg class="tp-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" ' +
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6 9 12 15 18 9"></polyline></svg>';

  var seq = 0;
  var terbuka = null;

  function buat(tag, cls, teks) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (teks != null) n.textContent = teks;
    return n;
  }

  function batasBawah(node) {
    for (var p = node.parentElement; p && p !== document.body; p = p.parentElement) {
      var ov = getComputedStyle(p).overflowY;
      if (ov === 'auto' || ov === 'scroll' || ov === 'hidden') {
        return Math.min(p.getBoundingClientRect().bottom, window.innerHeight);
      }
    }
    return window.innerHeight;
  }

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

  function norm(s) {
    return String(s || '').toLowerCase().replace(/[_\s\-\.]+/g, '');
  }

  function cocok(teks, nilai, raw) {
    var q = String(raw || '').trim().toLowerCase();
    var qn = norm(raw);
    if (!q) return true;
    var t = String(teks || '').toLowerCase();
    var v = String(nilai || '').toLowerCase();
    return t.indexOf(q) !== -1 || v.indexOf(q) !== -1
      || (qn && norm(t).indexOf(qn) !== -1)
      || (qn && norm(v).indexOf(qn) !== -1);
  }

  /* ─── Mode combobox satu field: parser-pick | file-pick ─── */
  function bangunParser(select) {
    if (select.dataset.tpDone) return;
    if (!select.parentNode) return;

    var modeFile = select.classList.contains('file-pick');
    var form = select.form;
    var grup = bacaOpsi(select), jumlah = 0, i, k;
    for (i = 0; i < grup.length; i++) jumlah += grup[i].opsi.length;
    if (!jumlah) return;

    var id = 'tp' + (++seq);
    var host = buat('div', 'tp-host tp-field tp-combo' + (modeFile ? ' tp-combo-file' : ''));
    var wrap = buat('div', 'tp-combo-wrap');
    var input = buat('input', 'tp-combo-input');
    input.type = 'text';
    input.autocomplete = 'off';
    input.spellcheck = false;
    input.setAttribute('role', 'combobox');
    input.setAttribute('aria-autocomplete', 'list');
    input.setAttribute('aria-expanded', 'false');
    input.setAttribute(
      'aria-label',
      modeFile ? 'File mutasi — ketik untuk mencari' : 'Jenis file — ketik untuk mencari'
    );
    input.placeholder = modeFile ? 'Cari file…' : 'Cari jenis…';
    wrap.appendChild(input);
    var chevBtn = buat('button', 'tp-combo-chev');
    chevBtn.type = 'button';
    chevBtn.tabIndex = -1;
    chevBtn.setAttribute('aria-label', modeFile ? 'Buka daftar file' : 'Buka daftar jenis');
    chevBtn.insertAdjacentHTML('beforeend', CHEV);
    wrap.appendChild(chevBtn);
    host.appendChild(wrap);

    var pop = buat('div', 'tp-pop tp-pop-fixed');
    pop.hidden = true;
    var daftar = buat('div', 'tp-list');
    daftar.id = id + '-list';
    daftar.setAttribute('role', 'listbox');
    input.setAttribute('aria-controls', daftar.id);
    pop.appendChild(daftar);
    var kosong = buat(
      'div',
      'tp-kosong',
      modeFile ? 'File tidak ditemukan.' : 'Jenis tidak ditemukan.'
    );
    kosong.setAttribute('role', 'status');
    kosong.hidden = true;
    pop.appendChild(kosong);
    // pop di body lewat fixed; tetap child host untuk contains()
    host.appendChild(pop);

    var item = [], terpilih = null, labelTerpilih = '';
    for (i = 0; i < grup.length; i++) {
      for (k = 0; k < grup[i].opsi.length; k++) {
        var o = grup[i].opsi[k];
        // Placeholder disabled value="" (parser gagal deteksi) — label di input saja
        if (o.disabled && !o.nilai) {
          if (o.terpilih && !labelTerpilih) {
            labelTerpilih = o.teks || '';
            input.placeholder = o.teks || input.placeholder;
          }
          continue;
        }
        // value="" aktif ("Semua file") tetap masuk daftar
        var node = buat('div', 'tp-opt', o.teks);
        node.id = id + '-o' + item.length;
        node.setAttribute('role', 'option');
        node.setAttribute('aria-selected', o.terpilih ? 'true' : 'false');
        node.setAttribute('data-v', o.nilai);
        node.setAttribute('data-q', o.teks.toLowerCase());
        daftar.appendChild(node);
        item.push(node);
        if (o.terpilih) {
          terpilih = node;
          labelTerpilih = o.teks;
        }
      }
    }
    // Tampilkan nilai terpilih di input
    if (labelTerpilih) {
      input.value = labelTerpilih;
    } else {
      input.value = '';
    }

    var ctl = { host: host, sorot: null, tutup: null };
    var ignoreBlur = false;

    function tampak() {
      var v = [], x;
      for (x = 0; x < item.length; x++) {
        if (!item[x].classList.contains('tp-hide')) v.push(item[x]);
      }
      return v;
    }

    function setSorot(node) {
      if (ctl.sorot) ctl.sorot.classList.remove('tp-on');
      ctl.sorot = node || null;
      if (!node) {
        input.removeAttribute('aria-activedescendant');
        return;
      }
      node.classList.add('tp-on');
      input.setAttribute('aria-activedescendant', node.id);
      try { node.scrollIntoView({ block: 'nearest' }); } catch (e) { /* */ }
    }

    function saring(qraw) {
      var q = qraw != null ? qraw : input.value;
      var n = 0, x;
      for (x = 0; x < item.length; x++) {
        var hay = item[x].getAttribute('data-q') || '';
        var hayV = item[x].getAttribute('data-v') || '';
        var ok = cocok(hay, hayV, q);
        item[x].classList.toggle('tp-hide', !ok);
        item[x].hidden = !ok;
        if (ok) n++;
      }
      kosong.hidden = n > 0;
      daftar.scrollTop = 0;
      setSorot(n ? tampak()[0] : null);
      return n;
    }

    function tempatkan() {
      var r = wrap.getBoundingClientRect();
      var lebar = Math.max(Math.ceil(r.width), modeFile ? 280 : 200);
      var left = Math.min(r.left, window.innerWidth - lebar - 8);
      if (left < 8) left = 8;
      pop.style.position = 'fixed';
      pop.style.left = left + 'px';
      pop.style.width = lebar + 'px';
      pop.style.minWidth = lebar + 'px';
      pop.style.right = 'auto';
      pop.style.zIndex = '200';
      var ruangBawah = window.innerHeight - r.bottom - 12;
      var ruangAtas = r.top - 12;
      var maxList = modeFile ? 320 : 260;
      if (ruangBawah < 140 && ruangAtas > ruangBawah) {
        pop.style.top = 'auto';
        pop.style.bottom = (window.innerHeight - r.top + 4) + 'px';
        maxList = Math.min(maxList, Math.max(100, ruangAtas - 12));
      } else {
        pop.style.bottom = 'auto';
        pop.style.top = (r.bottom + 4) + 'px';
        maxList = Math.min(maxList, Math.max(100, ruangBawah - 12));
      }
      daftar.style.maxHeight = maxList + 'px';
    }

    function onScrollOrResize(e) {
      if (pop.hidden) return;
      if (e && e.type === 'scroll' && pop.contains(e.target)) return;
      tempatkan();
    }

    function showPop() {
      pop.hidden = false;
      pop.removeAttribute('hidden');
      pop.style.display = 'flex';
      // Portal ke body: hindari clipping/offset aneh dari <table>/<td>
      if (pop.parentNode !== document.body) {
        document.body.appendChild(pop);
      }
    }

    function hidePop() {
      pop.hidden = true;
      pop.setAttribute('hidden', '');
      pop.style.display = 'none';
      // Kembalikan ke host agar DOM rapih saat baris di-render ulang
      if (pop.parentNode !== host) {
        host.appendChild(pop);
      }
    }

    function buka(keepQuery) {
      if (terbuka && terbuka !== ctl) terbuka.tutup(false);
      showPop();
      input.setAttribute('aria-expanded', 'true');
      host.classList.add('tp-open');
      terbuka = ctl;
      if (!keepQuery) {
        // Buka: tampilkan semua; biarkan user ketik (select-all mengganti query)
        saring('');
        try { input.select(); } catch (e) { /* */ }
      } else {
        saring(input.value);
      }
      tempatkan();
      if (!String(input.value || '').trim() && terpilih && !terpilih.classList.contains('tp-hide')) {
        setSorot(terpilih);
      }
      window.addEventListener('scroll', onScrollOrResize, true);
      window.addEventListener('resize', onScrollOrResize);
    }

    function tutup(restore) {
      // Jangan early-return hanya dari .hidden — CSS lama bisa menipu
      var wasOpen = !pop.hasAttribute('hidden') || pop.style.display === 'flex' || terbuka === ctl;
      hidePop();
      input.setAttribute('aria-expanded', 'false');
      host.classList.remove('tp-open');
      if (terbuka === ctl) terbuka = null;
      window.removeEventListener('scroll', onScrollOrResize, true);
      window.removeEventListener('resize', onScrollOrResize);
      setSorot(null);
      if (restore) {
        var lab = labelTerpilih;
        if (!lab && select.value) {
          for (var x = 0; x < item.length; x++) {
            if (item[x].getAttribute('data-v') === select.value) {
              lab = item[x].textContent;
              break;
            }
          }
        }
        if (!lab) {
          for (var y = 0; y < item.length; y++) {
            if (item[y].getAttribute('data-v') === '') {
              lab = item[y].textContent;
              break;
            }
          }
        }
        input.value = lab || '';
      }
      return wasOpen;
    }
    ctl.tutup = function () { tutup(true); };
    ctl.pop = pop;
    ctl.host = host;

    function pilih(node) {
      if (!node || node.classList.contains('tp-hide')) return;
      var nilai = node.getAttribute('data-v');
      var teks = (node.textContent || '').trim();
      select.value = nilai;
      labelTerpilih = teks;
      terpilih = node;
      input.value = teks;
      for (var x = 0; x < item.length; x++) {
        item[x].setAttribute('aria-selected', item[x] === node ? 'true' : 'false');
      }
      try { select.dispatchEvent(new Event('change', { bubbles: true })); } catch (e) { /* */ }
      ignoreBlur = true;
      tutup(false);
      input.value = teks;
      // File mutasi: langsung terapkan filter GET
      if (modeFile && form) {
        try { form.submit(); } catch (e3) { /* */ }
        return;
      }
      setTimeout(function () {
        ignoreBlur = false;
        try { input.blur(); } catch (e2) { /* */ }
      }, 0);
    }

    input.addEventListener('focus', function () {
      buka(false);
    });

    input.addEventListener('click', function () {
      if (pop.hidden || pop.style.display === 'none') buka(false);
      else try { input.select(); } catch (e) { /* */ }
    });

    chevBtn.addEventListener('mousedown', function (e) {
      e.preventDefault();
    });
    chevBtn.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      if (pop.hidden || pop.style.display === 'none') {
        input.focus();
        buka(false);
      } else {
        tutup(true);
      }
    });

    input.addEventListener('input', function () {
      if (pop.hidden || pop.style.display === 'none') buka(true);
      saring(input.value);
      tempatkan();
    });

    input.addEventListener('keydown', function (e) {
      var v, i2;
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        if (pop.hidden || pop.style.display === 'none') buka(true);
        v = tampak();
        if (!v.length) return;
        i2 = v.indexOf(ctl.sorot);
        if (i2 < 0) i2 = e.key === 'ArrowDown' ? -1 : 0;
        setSorot(e.key === 'ArrowDown' ? v[(i2 + 1) % v.length] : v[(i2 - 1 + v.length) % v.length]);
      } else if (e.key === 'Enter') {
        e.preventDefault();
        e.stopPropagation();
        if (ctl.sorot) pilih(ctl.sorot);
        else {
          v = tampak();
          if (v.length === 1) pilih(v[0]);
        }
      } else if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        tutup(true);
        input.blur();
      } else if (e.key === 'Tab') {
        tutup(true);
      }
    });

    input.addEventListener('blur', function () {
      if (ignoreBlur) return;
      setTimeout(function () {
        if (ignoreBlur) return;
        var a = document.activeElement;
        if (a && (host.contains(a) || pop.contains(a))) return;
        tutup(true);
      }, 150);
    });

    daftar.addEventListener('mousedown', function (e) {
      e.preventDefault();
      ignoreBlur = true;
    });
    daftar.addEventListener('click', function (e) {
      var node = e.target.closest ? e.target.closest('.tp-opt') : null;
      if (node) pilih(node);
      setTimeout(function () { ignoreBlur = false; }, 0);
    });

    // pastikan state awal tertutup
    hidePop();

    select.parentNode.insertBefore(host, select.nextSibling);
    select.classList.add('tp-native');
    select.dataset.tpDone = '1';
  }

  /* ─── Mode toko (tombol + popover) — perilaku lama ─── */
  function bangunToko(select) {
    if (select.dataset.tpDone) return;
    var form = select.form;
    if (!form || !select.parentNode) return;

    var grup = bacaOpsi(select), jumlah = 0, i, k;
    for (i = 0; i < grup.length; i++) jumlah += grup[i].opsi.length;
    if (!jumlah) return;

    var id = 'tp' + (++seq);
    var host = buat('div', 'tp-host' + (select.closest('.toko-pick') ? '' : ' tp-field'));
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
    pop.style.display = 'none';
    host.appendChild(pop);
    var daftar = buat('div', 'tp-list');
    daftar.id = id + '-list';
    daftar.setAttribute('role', 'listbox');
    daftar.tabIndex = -1;

    var cari = null;
    if (jumlah > AMBANG_CARI) {
      cari = buat('input', 'tp-cari');
      cari.type = 'text';
      cari.placeholder = 'Cari toko…';
      cari.autocomplete = 'off';
      cari.setAttribute('role', 'combobox');
      cari.setAttribute('aria-controls', daftar.id);
      cari.setAttribute('aria-expanded', 'true');
      cari.setAttribute('aria-autocomplete', 'list');
      cari.setAttribute('aria-label', 'Cari toko');
      pop.appendChild(cari);
    }
    pop.appendChild(daftar);
    var kosong = buat('div', 'tp-kosong', 'Toko tidak ditemukan.');
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
        if (o.disabled && !o.nilai) continue;
        var node = buat('div', 'tp-opt', o.teks);
        node.id = id + '-o' + item.length;
        node.setAttribute('role', 'option');
        node.setAttribute('aria-selected', o.terpilih ? 'true' : 'false');
        node.setAttribute('data-v', o.nilai);
        node.setAttribute('data-q', o.teks.toLowerCase());
        wadah.appendChild(node);
        item.push(node);
        if (o.terpilih) terpilih = node;
      }
    }
    kini.textContent = terpilih ? terpilih.textContent : '—';
    trigger.title = 'Toko aktif: ' + kini.textContent + ' — klik untuk mengganti';

    var ctl = { host: host, pop: pop, sorot: null, tutup: null };
    var fokusAria = cari || daftar;

    function tampak() {
      var v = [], x;
      for (x = 0; x < item.length; x++) {
        if (!item[x].classList.contains('tp-hide')) v.push(item[x]);
      }
      return v;
    }

    function setSorot(node) {
      if (ctl.sorot) ctl.sorot.classList.remove('tp-on');
      ctl.sorot = node || null;
      if (!node) { fokusAria.removeAttribute('aria-activedescendant'); return; }
      node.classList.add('tp-on');
      fokusAria.setAttribute('aria-activedescendant', node.id);
      try { node.scrollIntoView({ block: 'nearest' }); } catch (e) { /* */ }
    }

    function saring() {
      var q = cari ? cari.value : '';
      var n = 0, x;
      for (x = 0; x < item.length; x++) {
        var hay = item[x].getAttribute('data-q') || '';
        var hayV = item[x].getAttribute('data-v') || '';
        var ok = cocok(hay, hayV, q);
        item[x].classList.toggle('tp-hide', !ok);
        item[x].hidden = !ok;
        if (ok) n++;
      }
      var judul = daftar.querySelectorAll('.tp-grup');
      for (x = 0; x < judul.length; x++) {
        var ada = !!judul[x].querySelector('.tp-opt:not(.tp-hide)');
        judul[x].classList.toggle('tp-hide', !ada);
        judul[x].hidden = !ada;
      }
      kosong.hidden = n > 0;
      daftar.scrollTop = 0;
      setSorot(n ? tampak()[0] : null);
    }

    function tempatkan() {
      daftar.style.maxHeight = '';
      var luber = pop.getBoundingClientRect().bottom + 8 - batasBawah(host);
      if (luber > 0) daftar.style.maxHeight = Math.max(140, daftar.clientHeight - luber) + 'px';
    }

    function buka() {
      if (terbuka && terbuka !== ctl) terbuka.tutup(false);
      pop.hidden = false;
      pop.removeAttribute('hidden');
      pop.style.display = 'flex';
      trigger.setAttribute('aria-expanded', 'true');
      terbuka = ctl;
      if (cari) cari.value = '';
      saring();
      tempatkan();
      if (terpilih && !terpilih.classList.contains('tp-hide')) setSorot(terpilih);
      setTimeout(function () {
        if (cari) cari.focus();
        else daftar.focus();
      }, 0);
    }

    function tutup(kembalikanFokus) {
      pop.hidden = true;
      pop.setAttribute('hidden', '');
      pop.style.display = 'none';
      trigger.setAttribute('aria-expanded', 'false');
      if (terbuka === ctl) terbuka = null;
      if (kembalikanFokus) trigger.focus();
    }
    ctl.tutup = tutup;

    function pilih(node) {
      var nilai = node.getAttribute('data-v');
      if (select.value === nilai) { tutup(true); return; }
      select.value = nilai;
      tutup(false);
      form.submit();
    }

    trigger.addEventListener('mousedown', function (e) {
      if (pop.hidden) e.preventDefault();
    });
    trigger.addEventListener('click', function () {
      if (pop.hidden || pop.style.display === 'none') buka();
      else tutup(true);
    });
    trigger.addEventListener('keydown', function (e) {
      if ((pop.hidden || pop.style.display === 'none') && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
        e.preventDefault();
        buka();
      }
    });
    daftar.addEventListener('click', function (e) {
      var node = e.target.closest ? e.target.closest('.tp-opt') : null;
      if (node && !node.classList.contains('tp-hide')) pilih(node);
    });
    if (cari) {
      cari.addEventListener('input', saring);
      cari.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
          e.preventDefault();
          if (ctl.sorot) pilih(ctl.sorot);
        }
      });
    }
    pop.addEventListener('keydown', function (e) {
      var v, i2;
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        v = tampak();
        if (!v.length) return;
        i2 = v.indexOf(ctl.sorot);
        setSorot(e.key === 'ArrowDown' ? v[(i2 + 1) % v.length] : v[(i2 - 1 + v.length) % v.length]);
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (ctl.sorot) pilih(ctl.sorot);
      } else if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        tutup(true);
      } else if (e.key === 'Tab') {
        tutup(true);
      }
    });

    select.parentNode.insertBefore(host, select.nextSibling);
    select.classList.add('tp-native');
    select.dataset.tpDone = '1';
  }

  function bangun(select) {
    if (select.dataset.tpDone) return;
    try {
      if (select.classList.contains('parser-pick') || select.classList.contains('file-pick')) {
        bangunParser(select);
      } else {
        bangunToko(select);
      }
    } catch (err) { /* biarkan select bawaan */ }
  }

  document.addEventListener('pointerdown', function (e) {
    if (!terbuka) return;
    var t = e.target;
    if (terbuka.host && terbuka.host.contains(t)) return;
    if (terbuka.pop && terbuka.pop.contains(t)) return;
    terbuka.tutup();
  });

  // Escape global menutup dropdown yang terbuka
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && terbuka) {
      terbuka.tutup();
    }
  });

  function init() {
    var s = document.querySelectorAll(
      'select[name="toko_id"]:not([data-tp-done]), ' +
      'select.parser-pick:not([data-tp-done]), ' +
      'select.file-pick:not([data-tp-done])'
    );
    for (var i = 0; i < s.length; i++) bangun(s[i]);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
  document.addEventListener('htmx:afterSettle', init);
})();
