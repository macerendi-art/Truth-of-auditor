/* range-select.js — seleksi PERSEGI ala Excel + salin TSV untuk tabel angka.
 *
 * Dipasang global (app_base.html) dan hanya aktif pada <table class="selectable">.
 * Tujuan: klien bisa "drag B6:C20" tanpa menyapu kolom sebelahnya seperti seleksi
 * teks browser bawaan, lalu Cmd/Ctrl+C menyalin blok sebagai TSV yang rapi
 * ditempel ke Excel (baris = \n, kolom = \t).
 *
 * Desain menghormati sel koreksi FRControl (td[hx-get], klik → popup): kita TIDAK
 * preventDefault di mousedown. Klik-tunggal tetap lolos ke htmx; hanya drag NYATA
 * (lewat ambang gerak) yang menelan klik berikutnya, jadi popup tak keliru terbuka.
 *
 * Vanilla JS, tanpa dependensi. Semua listener didelegasikan ke document, jadi
 * aman terhadap swap htmx (mis. refresh #fr-control) — tak ada listener per-sel.
 */
(function () {
  'use strict';

  var DRAG_THRESHOLD = 4; // px — bedakan klik dari drag
  // Elemen interaktif di dalam sel yang harus tetap berfungsi (klik normal).
  var INTERACTIVE = 'a,button,input,select,textarea,label,[contenteditable=""],[contenteditable="true"]';

  var anchor = null;      // { table, tbody, r, c }
  var rect = null;        // { tbody, r1, r2, c1, c2 } — seleksi terkunci/terpaint
  var startX = 0, startY = 0;
  var dragging = false;
  var suppressClick = false;

  // --- util ------------------------------------------------------------------

  function tbodyRowIndex(tbody, tr) {
    return Array.prototype.indexOf.call(tbody.rows, tr);
  }

  // Sel data yang sah untuk di-anchor: td di dalam tbody table.selectable,
  // bukan baris placeholder (colSpan>1), bukan di atas elemen interaktif.
  function dataCell(el) {
    if (!el) return null;
    var td = el.closest ? el.closest('td') : null;
    if (!td) return null;
    var table = td.closest('table.selectable');
    if (!table) return null;
    var tbody = td.parentElement && td.parentElement.parentElement;
    if (!tbody || tbody.tagName !== 'TBODY') return null; // abaikan thead/tfoot
    if (td.colSpan && td.colSpan > 1) return null;         // baris "tidak ada data"
    return { td: td, table: table, tbody: tbody };
  }

  function clearPaint() {
    if (!rect) return;
    var rows = rect.tbody.rows;
    for (var r = rect.r1; r <= rect.r2 && r < rows.length; r++) {
      var cells = rows[r].cells;
      for (var c = rect.c1; c <= rect.c2 && c < cells.length; c++) {
        cells[c].classList.remove('rng-sel');
      }
    }
    rect = null;
  }

  function paint(a, focusTd) {
    // focusTd harus di tbody yang sama dengan anchor.
    var tbody = a.tbody;
    var fr = tbodyRowIndex(tbody, focusTd.parentElement);
    var fc = focusTd.cellIndex;
    if (fr < 0) return;
    var r1 = Math.min(a.r, fr), r2 = Math.max(a.r, fr);
    var c1 = Math.min(a.c, fc), c2 = Math.max(a.c, fc);

    // Sama dgn rect sekarang? jangan repaint.
    if (rect && rect.tbody === tbody && rect.r1 === r1 && rect.r2 === r2 &&
        rect.c1 === c1 && rect.c2 === c2) return;

    clearPaint();
    var rows = tbody.rows;
    for (var r = r1; r <= r2 && r < rows.length; r++) {
      var cells = rows[r].cells;
      for (var c = c1; c <= c2 && c < cells.length; c++) {
        cells[c].classList.add('rng-sel');
      }
    }
    rect = { tbody: tbody, r1: r1, r2: r2, c1: c1, c2: c2 };
  }

  function cellText(td) {
    var t = (td.innerText || td.textContent || '').trim();
    // Placeholder kosong ("—", "·") → string kosong agar tempel di Excel bersih.
    if (t === '—' || t === '·' || t === '-') return '';
    // Rapikan spasi/enter berlebih dalam satu sel.
    return t.replace(/\s+/g, ' ');
  }

  function selectionToTSV() {
    if (!rect) return '';
    var rows = rect.tbody.rows;
    var out = [];
    for (var r = rect.r1; r <= rect.r2 && r < rows.length; r++) {
      var cells = rows[r].cells;
      var line = [];
      for (var c = rect.c1; c <= rect.c2 && c < cells.length; c++) {
        line.push(cellText(cells[c]));
      }
      out.push(line.join('\t'));
    }
    return out.join('\n');
  }

  // --- listeners -------------------------------------------------------------

  document.addEventListener('mousedown', function (e) {
    if (e.button !== 0) return; // hanya klik kiri
    // Elemen interaktif di dalam sel → lepas, biar klik normalnya jalan.
    // clearPaint() juga: kalau seleksi persegi lama masih 'nyala', ia akan
    // membajak Ctrl+C berikutnya (mis. saat user menyalin teks dari link/input).
    if (e.target.closest && e.target.closest(INTERACTIVE)) { clearPaint(); anchor = null; return; }
    var cell = dataCell(e.target);
    if (!cell) {
      // mousedown di luar tabel selectable → batalkan seleksi lama.
      clearPaint();
      anchor = null;
      return;
    }
    // Mulai anchor baru; JANGAN preventDefault (klik htmx koreksi masih mungkin).
    clearPaint();
    anchor = {
      table: cell.table, tbody: cell.tbody,
      r: tbodyRowIndex(cell.tbody, cell.td.parentElement), c: cell.td.cellIndex,
    };
    startX = e.clientX; startY = e.clientY;
    dragging = false;
  });

  document.addEventListener('mousemove', function (e) {
    if (!anchor) return;
    if (!dragging) {
      if (Math.abs(e.clientX - startX) < DRAG_THRESHOLD &&
          Math.abs(e.clientY - startY) < DRAG_THRESHOLD) return;
      dragging = true;
      document.body.style.userSelect = 'none';
      document.body.style.webkitUserSelect = 'none';
    }
    e.preventDefault(); // stop seleksi teks native selama drag
    var under = document.elementFromPoint(e.clientX, e.clientY);
    var td = under && under.closest ? under.closest('td') : null;
    if (!td || !anchor.table.contains(td)) return;
    if (td.parentElement.parentElement !== anchor.tbody) return; // tbody yg sama
    if (td.colSpan && td.colSpan > 1) return;
    paint(anchor, td);
  });

  document.addEventListener('mouseup', function () {
    if (anchor && dragging) {
      // Drag nyata: pertahankan seleksi, dan telan click berikutnya (mis. htmx).
      suppressClick = true;
    } else if (anchor) {
      // Klik biasa (tanpa drag): jangan tinggalkan seleksi, biarkan htmx fire.
      clearPaint();
    }
    anchor = null;
    dragging = false;
    document.body.style.userSelect = '';
    document.body.style.webkitUserSelect = '';
  });

  // Telan click hasil drag di fase CAPTURE agar tak sampai ke htmx/link.
  document.addEventListener('click', function (e) {
    if (suppressClick) {
      e.preventDefault();
      e.stopPropagation();
      suppressClick = false;
    }
  }, true);

  // Cmd/Ctrl+C: pakai event 'copy' native — tak butuh izin clipboard.
  document.addEventListener('copy', function (e) {
    if (!rect) return; // biarkan copy normal bila tak ada seleksi persegi
    var tsv = selectionToTSV();
    if (!tsv) return;
    e.preventDefault();
    if (e.clipboardData) {
      e.clipboardData.setData('text/plain', tsv);
    } else if (window.clipboardData) { // IE lama
      window.clipboardData.setData('Text', tsv);
    }
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && rect) clearPaint();
  });
})();
