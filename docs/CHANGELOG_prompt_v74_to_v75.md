# CHANGELOG prompt_cashline_mus v74 -> v75

**Tanggal:** 31 Agustus 2026
**Cakupan:** satu aturan baru pada verifikasi DINAMIS card holder. KB tetap v34,
scorecard tetap v3. Skor & AI Status TIDAK berubah — lihat "Dampak" di bawah.

---

## Satu sisi kosong pada field DINAMIS = SKIPPED_NULL, bukan MISMATCH

**Permintaan Bank Mega, 31 Agustus 2026.** Untuk 9 field dinamis card holder
(VD_1..VD_9), bila **isian Ascend ATAU nilai dari transkrip kosong**, barisnya
menjadi `SKIPPED_NULL` — bukan `MISMATCH`. Tidak ada dua sisi untuk dibandingkan,
jadi tidak ada dasar untuk menyalahkan agent, dan barisnya tidak menerbitkan B17.

Sebelum v75 hanya satu arah yang dikecualikan: **reference kosong** (field
reference-less) sudah `SKIPPED_NULL` sejak v35. Arah sebaliknya — **reference
terisi, extracted kosong** — masih `MISMATCH` dan menerbitkan B17. Itulah yang
diubah sekarang.

Paling sering terjadi pada `no_telpon_kantor` dan `nama_keluarga_relasi`: terisi
di Ascend, tidak pernah disebut sepanjang panggilan.

### Yang diubah di prompt (5 tempat, semuanya konsisten satu sama lain)

1. `EMPTINESS DECISION` — butir 2 dipecah menjadi butir 2 (DINAMIS) dan butir 3
   (STATIC), karena kedua kelas field kini berbeda perlakuan.
2. `TEXT SIMILARITY SCORE (LEVENSHTEIN)` — baris "EXACTLY ONE side is empty".
3. `MATCH DECISION BY SIMILARITY THRESHOLD` — carve-out baru untuk dinamis.
4. Blok kosakata `"MATCH" / "MISMATCH" / "SKIPPED_NULL"` (TASK C).
5. Contoh kalimat `reason` untuk SKIPPED_NULL arah baru.

### Field STATIC sengaja TIDAK ikut

`tanggal_lahir` dan `nama_ibu_kandung` WAJIB ditanyakan agent. Transkrip yang
kosong di situ justru kegagalan verifikasi yang sesungguhnya, jadi tetap
`MISMATCH` + B17 + propagasi ke SC_CL_23_1/SC_CL_23_2. Field CASHLINE (TASK D)
juga tidak berubah: satu sisi kosong tetap `MISMATCH` -> B02/B03/B05.

## Dampak: baris error berkurang, skor tetap

Aturan ini **tidak menaikkan** `verified_count` SC_CL_24. Yang dihitung
terverifikasi hanya `MATCH` atau `event_verified = true`; `SKIPPED_NULL` tidak
pernah termasuk, dulu maupun sekarang. Yang hilang hanya baris error yang tidak
punya dasar pembanding.

Pengukuran atas korpus 98 tiket saat aturan ini dibuat:

| | Jumlah |
|---|---|
| Baris dinamis yang turun ke SKIPPED_NULL | 146 (di 86 tiket) |
| Baris B17 yang hilang dari tabel Error Code | 9 (di 4 tiket) |
| `ai_status` berubah | 0 |
| `scorecard_score` berubah | 0 |
| Hasil aturan 2-match berubah | 0 |

Selisih 146 vs 9 bukan anomali: pada mayoritas tiket aturan 2-match sudah
terpenuhi, dan sisa MISMATCH dinamis memang sudah disembunyikan dari tabel Error
Code sejak v33 (`card_holder_two_match_satisfied`). Yang benar-benar terlihat
berubah adalah tiket yang aturan 2-match-nya GAGAL — di situ seluruh MISMATCH
dinamis tampil, termasuk yang tidak punya pembanding.

Contoh `180107uT48`: B17 turun dari 5 menjadi 3. Yang hilang `No Telpon Kantor`
(Ascend 0231248400, tidak pernah disebut) dan `Nama Keluarga Relasi` (Ascend
AZIZAH, tidak pernah disebut). Yang bertahan tiga MISMATCH dua sisi yang asli:
Alamat Rumah (18%), Alamat Kantor (29%), Alamat Email Terdaftar (48%).

## Penegakan di kode (berlaku juga untuk tiket LAMA)

Aturan yang sama ditegakkan deterministik di Python oleh
`compliance.error_codes.normalize_dynamic_verification`, dipanggil berdampingan
dengan `normalize_static_verification` di keenam tempat evaluasi dibaca (detail
tiket, Agent Error Summary, daftar Results, Statistik, XLSX export, agregat stats).

Artinya tiket lama pun ikut dinilai dengan aturan baru tanpa perlu diproses ulang,
dan prompt ini adalah **cerminnya** — persis pola `address_group_score`: bila salah
satunya diubah, yang lain WAJIB menyusul.
