-- gerbang.sql — laporan verifikasi restore Truth of Auditor.
-- Dijalankan IDENTIK di dua sisi (produksi Railway & restore VPS); keluarannya
-- teks deterministik yang dibandingkan dengan `diff`, bukan dengan mata.
--
-- Variabel psql (WAJIB di-set pemanggil):
--   :full   'true'  = mode FINAL (Fase 4, penulisan produksi SUDAH dihentikan)
--           'false' = mode LIVE  (Fase 2, produksi masih menulis)
--   :ceil   batas id transactions_transaction (dari sisi RESTORE)
--   :ceilmr batas id reconciliation_matchresult (dari sisi RESTORE)
--
-- Konvensi keluaran:
--   baris diawali '~' = INFORMASI saja, TIDAK digerbang di mode live
--   baris lain        = DIGERBANG (harus identik dua sisi)

\set ON_ERROR_STOP on
\pset format unaligned
\pset tuples_only on
\pset footer off
\pset null '~NULL'
\timing off

\echo '=== 01 IDENTITAS SERVER (informasi) ==='
SELECT '~server_version_num=' || current_setting('server_version_num');
SELECT '~encoding=' || pg_encoding_to_char(encoding)
       || ' collate=' || datcollate || ' ctype=' || datctype
  FROM pg_database WHERE datname = current_database();

\echo '=== 02 EKSTENSI (digerbang) ==='
SELECT 'ext ' || extname || ' ' || extversion FROM pg_extension ORDER BY 1;

\echo '=== 03 INVENTARIS TABEL — NAMA SAJA (digerbang) ==='
-- Menangkap tabel yang HILANG total. Tidak ada angka 29 yang di-hardcode:
-- daftar kedua sisi dibandingkan apa adanya.
SELECT 'tabel ' || table_name
  FROM information_schema.tables
 WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
 ORDER BY 1;

\echo '=== 04 JUMLAH BARIS SEMUA TABEL (digerbang utk tabel referensi) ==='
-- Inti temuan: rencana lama hanya memeriksa SATU tabel. Ini memeriksa semuanya.
-- Tabel yang tumbuh tiap hari diberi awalan '~' supaya mode live tidak gagal
-- karena produksi memang bertambah; mode final menggerbang SEMUANYA.
WITH n AS (
  SELECT t.table_name,
         (xpath('/row/c/text()',
                query_to_xml(format('SELECT count(*) AS c FROM %I.%I',
                                    t.table_schema, t.table_name),
                             false, true, '')))[1]::text::bigint AS baris
    FROM information_schema.tables t
   WHERE t.table_schema = 'public' AND t.table_type = 'BASE TABLE'
)
SELECT CASE
         WHEN :full THEN ''
         -- Tabel yang bertambah/berubah sepanjang hari kerja: informasi saja
         -- selama produksi masih hidup.
         WHEN table_name IN (
              'transactions_transaction', 'reconciliation_matchresult',
              'reconciliation_matchrun', 'reconciliation_reconbatch',
              'reconciliation_reviewaction', 'sources_upload',
              'sources_upload_duplicate_transactions', 'core_auditlog',
              'django_session', 'django_admin_log',
              'web_frkoreksi', 'web_rekapmanual', 'web_hutangmanual',
              'web_rekappenyebab')
           THEN '~'
         ELSE ''
       END || 'baris ' || table_name || ' ' || baris
  FROM n ORDER BY table_name;

\echo '=== 05 TABEL REFERENSI TIDAK BOLEH KOSONG (digerbang, kedua mode) ==='
-- Asersi mandiri: benar/salah tanpa perlu membandingkan dua sisi.
-- Tabel-tabel ini di produksi diisi DATA MIGRATION yang di dump sudah
-- TERCATAT SELESAI di django_migrations — kalau kosong setelah restore,
-- `migrate` TIDAK akan pernah mengisinya ulang.
SELECT 'wajib-isi ' || t || ' ' ||
       CASE WHEN n > 0 THEN 'OK(' || n || ')' ELSE 'KOSONG-FATAL' END
  FROM (
    SELECT 'sources_sourcetype' t, count(*) n FROM sources_sourcetype
    UNION ALL SELECT 'sources_toko', count(*) FROM sources_toko
    UNION ALL SELECT 'reconciliation_toleranceprofile', count(*) FROM reconciliation_toleranceprofile
    UNION ALL SELECT 'accounts_user', count(*) FROM accounts_user
    UNION ALL SELECT 'django_content_type', count(*) FROM django_content_type
    UNION ALL SELECT 'auth_permission', count(*) FROM auth_permission
    UNION ALL SELECT 'django_migrations', count(*) FROM django_migrations
  ) s ORDER BY t;

\echo '=== 06 GAGAL-TERBUKA: web_allowedip & RBAC (digerbang) ==='
-- IPAllowlistMiddleware DORMAN saat daftar aktif kosong -> auditor/supervisor
-- tak lagi digerbang IP. Kosongnya tabel ini adalah regresi keamanan SENYAP,
-- bukan halaman error. Angkanya wajib sama dua sisi.
SELECT 'ip-aktif ' || count(*) FROM web_allowedip WHERE aktif;
SELECT 'rbac-grant ' || count(*) FROM accounts_user_allowed_tokos;
SELECT 'user-aktif ' || count(*) FROM accounts_user WHERE is_active;
SELECT 'user-peran ' || role || ' ' || count(*) FROM accounts_user GROUP BY role ORDER BY 1;

\echo '=== 07 OVERLAY KOREKSI MANUAL (digerbang) ==='
-- Hilangnya baris di sini TIDAK memunculkan error apa pun — angka Control
-- Bracket & Rekap Bulanan hanya berubah diam-diam. Wajib dijumlah, bukan
-- sekadar dihitung.
SELECT 'koreksi web_frkoreksi ' || count(*) || ' ' || coalesce(sum(nilai)::text,'0') FROM web_frkoreksi;
SELECT 'koreksi web_rekapmanual ' || count(*) || ' ' || coalesce(sum(nilai)::text,'0') FROM web_rekapmanual;
SELECT 'koreksi web_hutangmanual ' || count(*) || ' ' || coalesce(sum(nilai)::text,'0') FROM web_hutangmanual;
SELECT 'koreksi web_rekappenyebab ' || count(*) FROM web_rekappenyebab;
SELECT 'koreksi reviewaction ' || count(*) FROM reconciliation_reviewaction;

\echo '=== 08 CENSUS KOLOM PENENTU PERILAKU (digerbang, dibatasi id) ==='
-- Checksum SUM buta terhadap ini semua. Kalau `occurred_at` hilang, mesin
-- (yang menyaring occurred_at__date) berhenti mencocokkan; kalau `raw` kosong
-- seluruh halaman laporan jadi kosong; kalau `row_hash` rusak idempotensi
-- ingest hilang. Tak satu pun menggeser SUM(amount).
SELECT 'census tx_total ' || count(*) FROM transactions_transaction WHERE id <= :ceil;
SELECT 'census occurred_at_null ' || count(*) FROM transactions_transaction WHERE id <= :ceil AND occurred_at IS NULL;
SELECT 'census posted_date_null ' || count(*) FROM transactions_transaction WHERE id <= :ceil AND posted_date IS NULL;
SELECT 'census raw_kosong ' || count(*) FROM transactions_transaction WHERE id <= :ceil AND (raw IS NULL OR raw = '{}'::jsonb);
SELECT 'census row_hash_kosong ' || count(*) FROM transactions_transaction WHERE id <= :ceil AND (row_hash IS NULL OR row_hash = '');
SELECT 'census ticket_isi ' || count(*) FROM transactions_transaction WHERE id <= :ceil AND ticket_no <> '';
SELECT 'census reference_isi ' || count(*) FROM transactions_transaction WHERE id <= :ceil AND reference <> '';
SELECT 'census username_isi ' || count(*) FROM transactions_transaction WHERE id <= :ceil AND username <> '';
SELECT 'census counterparty_isi ' || count(*) FROM transactions_transaction WHERE id <= :ceil AND counterparty <> '';
SELECT 'census toko_null ' || count(*) FROM transactions_transaction WHERE id <= :ceil AND toko_id IS NULL;
SELECT 'census jenis ' || jenis || ' ' || count(*) FROM transactions_transaction WHERE id <= :ceil GROUP BY jenis ORDER BY 1;

\if :full
\echo '=== 08b KOLOM MUTABEL — hanya mode FINAL (digerbang) ==='
-- `consumed_by_batch_id` bergerak tiap run_batch, jadi hanya bisa digerbang
-- setelah penulisan produksi dihentikan. Kalau kolom ini kembali NULL,
-- 9 juta baris jadi "aktif" lagi dan run berikutnya memproses ulang semuanya.
SELECT 'mutabel consumed_notnull ' || count(*) FROM transactions_transaction WHERE consumed_by_batch_id IS NOT NULL;
SELECT 'mutabel is_duplicate ' || count(*) FROM transactions_transaction WHERE is_duplicate;
SELECT 'mutabel mr_bucket ' || bucket || ' ' || count(*) FROM reconciliation_matchresult GROUP BY bucket ORDER BY 1;
SELECT 'mutabel mr_resolved ' || count(*) FROM reconciliation_matchresult WHERE resolved_by_batch_id IS NOT NULL;
SELECT 'mutabel upload_tiban ' || count(*) FROM sources_upload WHERE superseded_by_id IS NOT NULL;
\endif

\echo '=== 09 CHECKSUM NILAI (digerbang, dibatasi id) ==='
SELECT 'jumlah amount ' || coalesce(sum(amount)::text,'0')
       || ' credit ' || coalesce(sum(credit_delta)::text,'0')
       || ' money '  || coalesce(sum(money_delta)::text,'0')
       || ' fee '    || coalesce(sum(fee)::text,'0')
       || ' bonus '  || coalesce(sum(bonus)::text,'0')
  FROM transactions_transaction WHERE id <= :ceil;

\echo '=== 10 SEBARAN BULANAN posted_date DAN occurred_at (digerbang) ==='
-- Lewat subquery: GROUP BY 1 pada ekspresi gabungan yang MEMUAT count(*) adalah
-- galat sintaks ("aggregate functions are not allowed in GROUP BY") — tertangkap
-- saat gladi FASE 2 pertama, 01-09-2026.
SELECT 'bulan-posted ' || bulan || ' ' || n FROM (
  SELECT coalesce(to_char(posted_date,'YYYY-MM'),'~NULL') AS bulan, count(*) AS n
    FROM transactions_transaction WHERE id <= :ceil GROUP BY 1
) x ORDER BY 1;
SELECT 'bulan-occurred ' || bulan || ' ' || n FROM (
  SELECT coalesce(to_char(occurred_at,'YYYY-MM'),'~NULL') AS bulan, count(*) AS n
    FROM transactions_transaction WHERE id <= :ceil GROUP BY 1
) x ORDER BY 1;

\echo '=== 11 SEBARAN PER TOKO x SUMBER (digerbang) ==='
-- Menangkap restore yang benar totalnya tapi timpang isinya.
SELECT 'toko-sumber ' || coalesce(toko_id::text,'~') || ' ' || source_type_id || ' '
       || count(*) || ' ' || coalesce(sum(amount)::text,'0')
  FROM transactions_transaction WHERE id <= :ceil
 GROUP BY toko_id, source_type_id ORDER BY 1;

\echo '=== 12 SIDIK JARI BARIS PER BLOK 1 JUTA id (digerbang) ==='
-- md5 atas KOLOM IMUTABEL termasuk teks & jsonb. Inilah satu-satunya cek yang
-- menangkap kerusakan encoding / jsonb / pergeseran nilai antar baris — semua
-- tak terlihat oleh SUM. Dipecah per blok supaya ketidakcocokan terlokalisasi.
SELECT 'sidik-tx ' || blok || ' ' || n || ' ' || cap FROM (
  SELECT (id / 1000000) AS blok, count(*) AS n,
         md5(string_agg(sig, E'\n' ORDER BY id)) AS cap
    FROM (
      SELECT id, concat_ws('|',
               id::text,
               coalesce(occurred_at::text,'~'), coalesce(posted_date::text,'~'),
               jenis, amount::text, credit_delta::text, money_delta::text,
               fee::text, bonus::text, coalesce(balance_after::text,'~'),
               ticket_no, username, reference, counterparty,
               md5(description), md5(raw::text), row_hash,
               source_type_id::text, upload_id::text,
               coalesce(toko_id::text,'~'), coalesce(account_id::text,'~'),
               bank_title, player_bank) AS sig
        FROM transactions_transaction WHERE id <= :ceil
    ) x GROUP BY 1
) y ORDER BY blok;

\echo '=== 13 SIDIK JARI MatchResult (digerbang, imutabel saja di mode live) ==='
SELECT 'sidik-mr ' || blok || ' ' || n || ' ' || cap FROM (
  SELECT (id / 1000000) AS blok, count(*) AS n,
         md5(string_agg(sig, E'\n' ORDER BY id)) AS cap
    FROM (
      -- Sengaja TANPA bucket/reason_code/reason_detail/resolved_by_batch_id:
      -- late settlement & override manual mengubahnya pada baris LAMA, jadi
      -- kolom itu digerbang terpisah di blok 08b (mode final saja).
      SELECT id, concat_ws('|', id::text, run_id::text,
               coalesce(left_id::text,'~'), coalesce(right_id::text,'~'),
               coalesce(score::text,'~')
             ) AS sig
        FROM reconciliation_matchresult WHERE id <= :ceilmr
    ) x GROUP BY 1
) y ORDER BY blok;

\echo '=== 14 INDEX SELURUH SKEMA + VALIDITAS (digerbang) ==='
-- Rencana lama tidak memeriksa index sama sekali; `periksa_index` pun hanya
-- melihat transactions_transaction dan hanya 2 index bernama di model.
-- Ini membandingkan DEFINISI setiap index di setiap tabel, plus indisvalid.
SELECT 'index ' || c.relname || ' valid=' || i.indisvalid || ' ' || pg_get_indexdef(i.indexrelid)
  FROM pg_index i
  JOIN pg_class c ON c.oid = i.indexrelid
  JOIN pg_class t ON t.oid = i.indrelid
  JOIN pg_namespace ns ON ns.oid = t.relnamespace
 WHERE ns.nspname = 'public'
 ORDER BY 1;

\echo '=== 15 CONSTRAINT SELURUH SKEMA (digerbang) ==='
-- unique/FK/check. Hilangnya uniq_reconbatch_toko_recon_date atau
-- uniq_tx_source_toko_rowhash tidak terlihat sampai data ganda tercipta.
SELECT 'constraint ' || t.relname || ' ' || con.conname || ' ' || con.contype::text
       || ' ' || pg_get_constraintdef(con.oid)
  FROM pg_constraint con
  JOIN pg_class t ON t.oid = con.conrelid
  JOIN pg_namespace ns ON ns.oid = t.relnamespace
 WHERE ns.nspname = 'public'
 ORDER BY 1;

\echo '=== 16 SEQUENCE vs max(id) (asersi mandiri + digerbang) ==='
-- pg_restore MEMANG memulihkan setval, tapi kalau satu setval gagal (restore
-- paralel yang errornya diabaikan) INSERT berikutnya menabrak PK yang ada.
-- Ini memeriksanya secara mandiri, tak perlu membandingkan dua sisi.
WITH s AS (
  SELECT t.table_name,
         pg_get_serial_sequence('public.' || quote_ident(t.table_name), 'id') AS seq,
         (xpath('/row/c/text()',
                query_to_xml(format('SELECT max(id) AS c FROM %I.%I',
                                    t.table_schema, t.table_name),
                             true, true, '')))[1]::text::bigint AS maxid
    FROM information_schema.tables t
    JOIN information_schema.columns c
      ON c.table_schema = t.table_schema AND c.table_name = t.table_name
     AND c.column_name = 'id'
   WHERE t.table_schema = 'public' AND t.table_type = 'BASE TABLE'
)
SELECT 'sequence ' || s.table_name || ' max=' || coalesce(s.maxid::text,'~')
       || ' last=' || coalesce(pgs.last_value::text,'~')
       || ' ' || CASE
            WHEN s.seq IS NULL              THEN 'TANPA-SEQUENCE'
            WHEN s.maxid IS NULL            THEN 'OK-tabel-kosong'
            WHEN pgs.last_value IS NULL     THEN 'BAHAYA-BELUM-PERNAH-DIPANGGIL'
            WHEN pgs.last_value >= s.maxid  THEN 'OK'
            ELSE 'BAHAYA-TABRAKAN-PK'
          END
  FROM s LEFT JOIN pg_sequences pgs
    ON pgs.schemaname = 'public' AND ('public.' || quote_ident(pgs.sequencename)) = s.seq
 ORDER BY 1;

\echo '=== 17 STATISTIK PLANNER (informasi — cek sisi restore) ==='
-- Restore segar TIDAK punya pg_statistic. Aplikasi ini punya sensitivitas
-- planner terukur (dashboard 14,6 dtk -> 2,1 dtk lewat index+setelan), jadi
-- mengukur waktu halaman sebelum ANALYZE = mengukur derau.
SELECT '~stats ' || relname || ' analyzed=' ||
       coalesce(greatest(last_analyze, last_autoanalyze)::text, 'BELUM-PERNAH') ||
       ' reltuples=' || (SELECT reltuples::bigint FROM pg_class WHERE oid = st.relid)
  FROM pg_stat_user_tables st
 WHERE relname IN ('transactions_transaction','reconciliation_matchresult',
                   'sources_upload','reconciliation_reconbatch')
 ORDER BY 1;
SELECT '~stats-kolom transactions_transaction ' || count(*)
  FROM pg_stats WHERE schemaname='public' AND tablename='transactions_transaction';

\echo '=== SELESAI ==='
