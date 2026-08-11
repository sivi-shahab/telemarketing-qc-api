# Assign Ticket dari tickets-daily — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Halaman `/qc/assign` menampilkan baris dari feed harian hulu `tickets-daily` (H-1), bukan lagi dari tabel `results` lokal, sambil tetap menampilkan data assignment QC dari sistem ini.

**Architecture:** Logika murni (pengelompokan, penentuan status, penggabungan data lokal) dipisah ke modul `assignTicketData.js` tanpa Vue dan tanpa jaringan, sehingga bisa diuji dengan test runner bawaan Node. `AssignTicketView.vue` hanya mengurus pengambilan data dan tampilan.

**Tech Stack:** Vue 3 `<script setup>`, `fetch` + `X-API-Key` untuk API eksternal, `apiClient` (axios) untuk API internal, `node:test` + `node:assert` untuk unit test (bawaan Node v22, tanpa dependency baru).

## Global Constraints

- Backend TIDAK disentuh. Perubahan hanya di `dashboard/src/`.
- `tickets-daily` menolak `limit > 100` dengan HTTP 422. `FETCH_LIMIT = 100`, `MAX_FETCH_PAGES = 100`.
- Tanpa parameter `load_date`, API memakai `mode: "yesterday"`. Jangan menghitung tanggal H-1 di sisi klien.
- Kolom Campaign diisi dari field `context`, BUKAN `campaign`. Ini keputusan eksplisit pemilik fitur meski payload punya keduanya.
- Status `done` hanya bila SELURUH tiket dalam satu grup punya `processed_at`; selain itu `belum diproses`.
- `processed_at` bernilai integer epoch. Gunakan pemeriksaan `!= null`, bukan truthiness — nilai `0` harus dihitung sebagai sudah diproses.
- **Commit sedang terblokir.** Repo punya merge yang belum selesai (`.git/MERGE_HEAD` ada, 32 file ter-staged). `git commit` apa pun akan menjadi merge commit yang menyapu seluruh file itu. Setiap langkah commit di bawah WAJIB memeriksa `.git/MERGE_HEAD` lebih dulu dan melewati commit bila file itu masih ada.

## File Structure

| File | Tanggung jawab |
|---|---|
| `dashboard/src/views/qc/assignTicketData.js` (baru) | Transformasi murni: kelompokkan item per ticket id, turunkan status, gabungkan data lokal. Tanpa Vue, tanpa jaringan. |
| `dashboard/src/views/qc/assignTicketData.test.mjs` (baru) | Unit test untuk modul di atas. |
| `dashboard/src/views/qc/AssignTicketView.vue` (ubah) | Pengambilan data (`tickets-daily` + `/list_results`), input tanggal, tampilan. |

---

### Task 1: Modul transformasi — pengelompokan dan status

**Files:**
- Create: `dashboard/src/views/qc/assignTicketData.js`
- Test: `dashboard/src/views/qc/assignTicketData.test.mjs`

**Interfaces:**
- Consumes: tidak ada (task pertama)
- Produces:
  - `groupTickets(items: object[]): Group[]` dengan `Group = { id: string, contexts: string[], tickets: object[], latest: string|null }`, terurut `latest` menurun
  - `groupStatus(group: Group): 'done' | 'belum diproses'`

- [ ] **Step 1: Tulis test yang gagal**

Buat `dashboard/src/views/qc/assignTicketData.test.mjs`:

```js
import test from 'node:test'
import assert from 'node:assert/strict'
import { groupTickets, groupStatus } from './assignTicketData.js'

test('groupTickets mengelompokkan beberapa tiket ke satu ticket id', () => {
  const groups = groupTickets([
    { id: 'A1', tiket_id: 'A1_1', context: 'card', created_time: '2026-07-28T10:00:00', processed_at: 1 },
    { id: 'A1', tiket_id: 'A1_2', context: 'card', created_time: '2026-07-28T12:00:00', processed_at: 2 },
    { id: 'B2', tiket_id: 'B2_1', context: 'ntb', created_time: '2026-07-28T11:00:00', processed_at: 3 },
  ])
  assert.equal(groups.length, 2)
  const a1 = groups.find((g) => g.id === 'A1')
  assert.equal(a1.tickets.length, 2)
  assert.deepEqual(a1.contexts, ['card'])
})

test('groupTickets menggabungkan context yang berbeda dalam satu grup', () => {
  const [g] = groupTickets([
    { id: 'A1', context: 'cashline', created_time: '2026-07-28T10:00:00', processed_at: 1 },
    { id: 'A1', context: 'ntb', created_time: '2026-07-28T11:00:00', processed_at: 2 },
    { id: 'A1', context: 'cashline', created_time: '2026-07-28T12:00:00', processed_at: 3 },
  ])
  assert.deepEqual(g.contexts, ['cashline', 'ntb'])
})

test('groupTickets memakai tiket_id sebagai kunci bila id kosong', () => {
  const [g] = groupTickets([{ tiket_id: 'X9_1', context: 'card', created_time: null, processed_at: 1 }])
  assert.equal(g.id, 'X9_1')
})

test('groupTickets mengurutkan grup dari yang terbaru', () => {
  const groups = groupTickets([
    { id: 'LAMA', context: 'card', created_time: '2026-07-28T08:00:00', processed_at: 1 },
    { id: 'BARU', context: 'card', created_time: '2026-07-28T20:00:00', processed_at: 1 },
  ])
  assert.deepEqual(groups.map((g) => g.id), ['BARU', 'LAMA'])
})

test('groupTickets mengabaikan context kosong', () => {
  const [g] = groupTickets([
    { id: 'A1', context: '', created_time: '2026-07-28T10:00:00', processed_at: 1 },
    { id: 'A1', context: null, created_time: '2026-07-28T11:00:00', processed_at: 1 },
  ])
  assert.deepEqual(g.contexts, [])
})

test('groupStatus done bila semua tiket punya processed_at', () => {
  const [g] = groupTickets([
    { id: 'A1', context: 'card', created_time: '2026-07-28T10:00:00', processed_at: 1785249460 },
    { id: 'A1', context: 'card', created_time: '2026-07-28T11:00:00', processed_at: 1785249999 },
  ])
  assert.equal(groupStatus(g), 'done')
})

test('groupStatus belum diproses bila ada satu processed_at null', () => {
  const [g] = groupTickets([
    { id: 'A1', context: 'card', created_time: '2026-07-28T10:00:00', processed_at: 1785249460 },
    { id: 'A1', context: 'card', created_time: '2026-07-28T11:00:00', processed_at: null },
  ])
  assert.equal(groupStatus(g), 'belum diproses')
})

test('groupStatus memperlakukan processed_at 0 sebagai sudah diproses', () => {
  const [g] = groupTickets([
    { id: 'A1', context: 'card', created_time: '2026-07-28T10:00:00', processed_at: 0 },
  ])
  assert.equal(groupStatus(g), 'done')
})

test('groupStatus belum diproses untuk grup tanpa tiket', () => {
  assert.equal(groupStatus({ id: 'A1', contexts: [], tickets: [], latest: null }), 'belum diproses')
})
```

- [ ] **Step 2: Jalankan test, pastikan GAGAL**

Run: `cd dashboard && node --test src/views/qc/assignTicketData.test.mjs`
Expected: FAIL — `Cannot find module './assignTicketData.js'`

- [ ] **Step 3: Tulis implementasi minimal**

Buat `dashboard/src/views/qc/assignTicketData.js`:

```js
// Transformasi murni untuk halaman Assign Ticket. Tanpa Vue dan tanpa jaringan
// supaya bisa diuji langsung dengan `node --test`.

/**
 * Kelompokkan item tickets-daily menjadi satu baris per ticket id.
 * Satu `id` bisa memuat beberapa `tiket_id` (rekaman terpisah).
 * Hasil diurutkan dari `created_time` terbaru.
 */
export function groupTickets(items) {
  const map = new Map()
  for (const it of items || []) {
    const key = it.id ?? it.tiket_id
    if (key == null) continue
    let g = map.get(key)
    if (!g) {
      g = { id: key, contexts: [], tickets: [], latest: it.created_time ?? null }
      map.set(key, g)
    }
    g.tickets.push(it)
    if (it.context && !g.contexts.includes(it.context)) g.contexts.push(it.context)
    const ts = it.created_time ?? null
    if (ts && (!g.latest || ts > g.latest)) g.latest = ts
  }
  return Array.from(map.values()).sort((a, b) => String(b.latest ?? '').localeCompare(String(a.latest ?? '')))
}

/**
 * Status satu baris. `done` HANYA bila seluruh tiket dalam grup sudah diproses
 * hulu. `processed_at` adalah epoch integer, jadi 0 pun berarti sudah diproses —
 * karena itu pemeriksaannya `!= null`, bukan truthiness.
 */
export function groupStatus(group) {
  const tickets = group?.tickets || []
  if (!tickets.length) return 'belum diproses'
  return tickets.every((t) => t.processed_at != null) ? 'done' : 'belum diproses'
}
```

- [ ] **Step 4: Jalankan test, pastikan LULUS**

Run: `cd dashboard && node --test src/views/qc/assignTicketData.test.mjs`
Expected: PASS — 9 test lulus, 0 gagal

- [ ] **Step 5: Commit (lewati bila merge belum selesai)**

```bash
cd /data/scorecard_v2/telemarketing-qc-system
if [ -e .git/MERGE_HEAD ]; then
  echo "LEWATI commit: merge belum selesai, commit akan menyapu 32 file ter-staged"
else
  git add dashboard/src/views/qc/assignTicketData.js dashboard/src/views/qc/assignTicketData.test.mjs
  git commit -m "feat(assign-ticket): tambah transformasi grouping dan status dari tickets-daily"
fi
```

---

### Task 2: Penggabungan dengan data assignment lokal

**Files:**
- Modify: `dashboard/src/views/qc/assignTicketData.js`
- Test: `dashboard/src/views/qc/assignTicketData.test.mjs`

**Interfaces:**
- Consumes: `groupTickets()` dan tipe `Group` dari Task 1
- Produces: `joinLocalResults(groups: Group[], localItems: object[]): Row[]` dengan `Row = Group & { status: string, assigned_qc: string|null, assigned_at: string|null, qc_checked_at: string|null, qc_checked_by: string|null }`

Item `/list_results` memakai field `id` sebagai ticket id (hasil `_customer_id_from_files()` di backend), sehingga bisa langsung dicocokkan dengan `group.id`.

- [ ] **Step 1: Tulis test yang gagal**

Tambahkan ke `dashboard/src/views/qc/assignTicketData.test.mjs` (dan perbarui baris import di paling atas menjadi `import { groupTickets, groupStatus, joinLocalResults } from './assignTicketData.js'`):

```js
test('joinLocalResults mengisi data QC dari hasil lokal yang cocok', () => {
  const groups = groupTickets([
    { id: 'A1', context: 'card', created_time: '2026-07-28T10:00:00', processed_at: 1 },
  ])
  const [row] = joinLocalResults(groups, [
    { id: 'A1', assigned_qc: 'qc01', assigned_at: '2026-07-29T03:00:00', qc_checked_at: '2026-07-30T04:00:00', qc_checked_by: 'qc01' },
  ])
  assert.equal(row.assigned_qc, 'qc01')
  assert.equal(row.assigned_at, '2026-07-29T03:00:00')
  assert.equal(row.qc_checked_at, '2026-07-30T04:00:00')
  assert.equal(row.qc_checked_by, 'qc01')
})

test('joinLocalResults memberi null bila ticket belum ada di sistem ini', () => {
  const groups = groupTickets([
    { id: 'BARU', context: 'ntb', created_time: '2026-07-28T10:00:00', processed_at: 1 },
  ])
  const [row] = joinLocalResults(groups, [{ id: 'LAIN', assigned_qc: 'qc01' }])
  assert.equal(row.assigned_qc, null)
  assert.equal(row.assigned_at, null)
  assert.equal(row.qc_checked_at, null)
  assert.equal(row.qc_checked_by, null)
})

test('joinLocalResults memakai hasil lokal PERTAMA saat satu ticket punya banyak result', () => {
  // /list_results terurut uploaded_at menurun, jadi yang pertama adalah yang terbaru.
  const groups = groupTickets([
    { id: 'A1', context: 'card', created_time: '2026-07-28T10:00:00', processed_at: 1 },
  ])
  const [row] = joinLocalResults(groups, [
    { id: 'A1', assigned_qc: 'baru', assigned_at: '2026-07-30T00:00:00' },
    { id: 'A1', assigned_qc: 'lama', assigned_at: '2026-07-01T00:00:00' },
  ])
  assert.equal(row.assigned_qc, 'baru')
})

test('joinLocalResults menyertakan status hasil groupStatus', () => {
  const groups = groupTickets([
    { id: 'A1', context: 'card', created_time: '2026-07-28T10:00:00', processed_at: null },
  ])
  const [row] = joinLocalResults(groups, [])
  assert.equal(row.status, 'belum diproses')
})

test('joinLocalResults tetap jalan bila daftar lokal kosong atau null', () => {
  const groups = groupTickets([
    { id: 'A1', context: 'card', created_time: '2026-07-28T10:00:00', processed_at: 1 },
  ])
  assert.equal(joinLocalResults(groups, null)[0].assigned_qc, null)
  assert.equal(joinLocalResults(groups, [])[0].status, 'done')
})
```

- [ ] **Step 2: Jalankan test, pastikan GAGAL**

Run: `cd dashboard && node --test src/views/qc/assignTicketData.test.mjs`
Expected: FAIL — `joinLocalResults is not a function`

- [ ] **Step 3: Tulis implementasi minimal**

Tambahkan ke `dashboard/src/views/qc/assignTicketData.js`:

```js
/**
 * Gabungkan grup tickets-daily dengan item /list_results, dicocokkan lewat
 * ticket id. Ticket yang belum masuk sistem ini mendapat nilai null — kolom QC
 * akan tampil "— belum —" dan ticket tetap bisa di-assign.
 *
 * Bila satu ticket id punya lebih dari satu result (upload ulang), yang dipakai
 * adalah kemunculan PERTAMA: /list_results terurut uploaded_at menurun.
 */
export function joinLocalResults(groups, localItems) {
  const byTicket = new Map()
  for (const it of localItems || []) {
    if (it?.id != null && !byTicket.has(it.id)) byTicket.set(it.id, it)
  }
  return (groups || []).map((g) => {
    const local = byTicket.get(g.id) || null
    return {
      ...g,
      status: groupStatus(g),
      assigned_qc: local?.assigned_qc ?? null,
      assigned_at: local?.assigned_at ?? null,
      qc_checked_at: local?.qc_checked_at ?? null,
      qc_checked_by: local?.qc_checked_by ?? null,
    }
  })
}
```

- [ ] **Step 4: Jalankan test, pastikan LULUS**

Run: `cd dashboard && node --test src/views/qc/assignTicketData.test.mjs`
Expected: PASS — 14 test lulus, 0 gagal

- [ ] **Step 5: Commit (lewati bila merge belum selesai)**

```bash
cd /data/scorecard_v2/telemarketing-qc-system
if [ -e .git/MERGE_HEAD ]; then
  echo "LEWATI commit: merge belum selesai"
else
  git add dashboard/src/views/qc/assignTicketData.js dashboard/src/views/qc/assignTicketData.test.mjs
  git commit -m "feat(assign-ticket): gabungkan data assignment lokal per ticket id"
fi
```

---

### Task 3: Sambungkan view ke tickets-daily

**Files:**
- Modify: `dashboard/src/views/qc/AssignTicketView.vue`

**Interfaces:**
- Consumes: `groupTickets()`, `joinLocalResults()` dari Task 1 dan 2
- Produces: tidak ada (task terakhir)

- [ ] **Step 1: Ganti blok state dan import**

Ganti `AssignTicketView.vue:78-91` (dari `<script setup>` sampai baris `const busy = ref(null)`) menjadi:

```js
<script setup>
import { ref, computed, onMounted } from 'vue'
import SidebarLayout from '../../components/SidebarLayout.vue'
import apiClient from '../../api/client.js'
import { groupTickets, joinLocalResults } from './assignTicketData.js'

// Same-origin call-qc; nginx mem-proxy /tickets-daily ke App C (:8008).
// Pola dan konstanta menyalin TranscriptsView.vue yang sudah dipakai produksi.
const C_API_BASE = (import.meta.env.VITE_TMS_API_URL || 'https://call-qc.bankmega.local').replace(/\/+$/, '')
const X_API_KEY = import.meta.env.VITE_TMS_API_KEY || 'zTkQMeKmvq9D59z0NhWczv9o9KrPSfnSs8hLJ0J4r1s'
const FETCH_LIMIT = 100      // /tickets-daily menolak limit > 100
const MAX_FETCH_PAGES = 100  // pengaman loop

const tickets = ref([])
const qcUsers = ref([])
const loading = ref(true)
const errorMsg = ref('')
const search = ref('')
const assigneeFilter = ref('')
const loadDate = ref('')   // kosong -> tidak dikirim -> API pakai mode "yesterday"
const pick = ref({})       // ticket_id -> selected qc username
const busy = ref(null)     // ticket_id currently mutating

let inFlight = null        // AbortController permintaan tickets-daily terakhir
let requestId = 0          // penanda anti balapan antar-permintaan
```

- [ ] **Step 2: Ganti fungsi pengambilan data**

Ganti `loadAll()` (`AssignTicketView.vue:118-135`) menjadi tiga fungsi berikut:

```js
// Tarik seluruh halaman tickets-daily. Dibatalkan bila ada permintaan baru,
// dan hanya permintaan TERAKHIR yang boleh menulis ke state.
async function fetchTicketsDaily(signal) {
  const collected = []
  let p = 1
  while (p <= MAX_FETCH_PAGES) {
    const url = new URL(`${C_API_BASE}/tickets-daily`)
    if (loadDate.value) url.searchParams.set('load_date', loadDate.value)
    url.searchParams.set('page', String(p))
    url.searchParams.set('limit', String(FETCH_LIMIT))
    const res = await fetch(url, {
      headers: { Accept: 'application/json', 'X-API-Key': X_API_KEY },
      signal,
    })
    if (!res.ok) throw new Error(`Gagal memuat tickets-daily (HTTP ${res.status})`)
    const data = await res.json()
    const items = data.items || []
    collected.push(...items)
    if (collected.length >= (data.total || 0) || items.length === 0) break
    p += 1
  }
  return collected
}

// Data assignment lokal. Dipaginasi penuh: satu hari saja sudah >100 ticket,
// jadi sekali tembak limit=100 akan memotong data secara diam-diam.
async function fetchLocalResults() {
  const collected = []
  let p = 1
  while (p <= MAX_FETCH_PAGES) {
    const res = await apiClient.get('/list_results', { params: { page: p, limit: FETCH_LIMIT } })
    const items = res.data.items || []
    collected.push(...items)
    if (collected.length >= (res.data.total || 0) || items.length === 0) break
    p += 1
  }
  return collected
}

async function loadAll() {
  if (inFlight) inFlight.abort()
  const ctrl = new AbortController()
  inFlight = ctrl
  const myId = ++requestId

  loading.value = true
  errorMsg.value = ''
  try {
    const [daily, users] = await Promise.all([
      fetchTicketsDaily(ctrl.signal),
      apiClient.get('/qc_assignment/qc_users'),
    ])
    // Kegagalan /list_results TIDAK membatalkan tabel: assign hanya butuh ticket
    // id, jadi baris tetap tampil dengan kolom QC kosong.
    let local = []
    try {
      local = await fetchLocalResults()
    } catch {
      local = []
    }
    if (myId !== requestId) return
    tickets.value = joinLocalResults(groupTickets(daily), local)
    qcUsers.value = users.data || []
  } catch (e) {
    if (e.name === 'AbortError') return
    if (myId !== requestId) return
    tickets.value = []
    errorMsg.value = e.response?.status === 403
      ? 'Akses hanya untuk Team Leader QC atau SPQ Head.'
      : (e.message || 'Gagal memuat data.')
  } finally {
    if (myId === requestId) {
      loading.value = false
      inFlight = null
    }
  }
}
```

- [ ] **Step 3: Ubah template**

Tiga perubahan di `AssignTicketView.vue`:

Baris 40 — key baris (baris tickets-daily tidak punya `result_id`):

```html
<tr v-for="t in filtered" :key="t.id">
```

Baris 42 — Campaign dari `contexts`:

```html
<td>{{ t.contexts.join(', ') || '—' }}</td>
```

Baris 72 — catatan lama menyebut batas `LIMIT` yang sudah tidak dipakai:

```html
<div class="note">Sumber: tickets-daily (H-1). Kosongkan tanggal untuk memakai data kemarin.</div>
```

- [ ] **Step 4: Tambah input tanggal di toolbar**

Sisipkan tepat setelah input pencarian (`AssignTicketView.vue:12`):

```html
<input v-model="loadDate" class="text-input filter" type="date" title="Kosongkan = data kemarin (H-1)" @change="loadAll" />
```

- [ ] **Step 5: Jalankan unit test dan pemeriksaan komponen**

```bash
cd /data/scorecard_v2/telemarketing-qc-system/dashboard
node --test src/views/qc/assignTicketData.test.mjs
grep -n "LIMIT" src/views/qc/AssignTicketView.vue
```

Expected: 14 test PASS. `grep` hanya menemukan `FETCH_LIMIT` dan `MAX_FETCH_PAGES` — tidak ada lagi `LIMIT` lama yang menggantung (kalau masih ada, hapus rujukannya).

- [ ] **Step 6: Build ulang dan verifikasi bundle**

```bash
cd /data/scorecard_v2/telemarketing-qc-system
docker compose up -d --build dashboard
docker exec telemarketing-qc-system-dashboard-1 \
  sh -c 'ls /usr/share/nginx/html/assets/AssignTicketView-*.js'
docker exec telemarketing-qc-system-dashboard-1 \
  sh -c 'grep -oE "[a-zA-Z_$][a-zA-Z0-9_$]*\(.[A-Z][A-Za-z]+.\)" /usr/share/nginx/html/assets/AssignTicketView-*.js | sort -u'
```

Expected: perintah pertama menampilkan satu file chunk. Perintah kedua tidak
menghasilkan baris apa pun — artinya tidak ada `resolveComponent` yang tersisa.
Komponen yang gagal di-resolve adalah regresi yang pernah terjadi di
`ResultsView.vue` dan tidak terlihat saat build, hanya saat halaman dibuka.

- [ ] **Step 7: Verifikasi data lewat HTTP**

```bash
KEY='zTkQMeKmvq9D59z0NhWczv9o9KrPSfnSs8hLJ0J4r1s'
curl -s -H "X-API-Key: $KEY" "http://localhost:8008/tickets-daily?load_date=2026-07-28&page=1&limit=100" \
  | grep -o '"total":[0-9]*' | head -1
curl -s -H "X-API-Key: $KEY" "http://localhost:8008/tickets-daily?page=1&limit=1" \
  | grep -o '"mode":"[a-z]*"'
```

Expected: baris pertama `"total":192` (yang setelah dikelompokkan menjadi 112 baris tabel), baris kedua `"mode":"yesterday"`.

- [ ] **Step 8: Pemeriksaan manual di browser**

Buka `/qc/assign` dengan hard refresh (Ctrl+Shift+R).

1. Kosongkan tanggal → tabel memakai mode `yesterday`. Per 2026-08-02 ini KOSONG karena hulu belum mengirim data; itu benar, bukan kerusakan.
2. Isi tanggal `2026-07-28` → muncul 112 baris.
3. Kolom Campaign berisi `card`/`usage`/`cashline`/`ntb`/`tbfu`/`alloblast`, dan ada baris bernilai `cashline, ntb` (grup campuran).
4. Kolom Status seluruhnya `done` untuk tanggal ini.
5. Assign satu ticket ke QC → kolom "QC ditugaskan" dan "Assign Date" terisi. Muat ulang halaman, nilainya bertahan.
6. Tekan "Lepas" pada ticket tadi → kembali ke "— belum —".

- [ ] **Step 9: Commit (lewati bila merge belum selesai)**

```bash
cd /data/scorecard_v2/telemarketing-qc-system
if [ -e .git/MERGE_HEAD ]; then
  echo "LEWATI commit: merge belum selesai"
else
  git add dashboard/src/views/qc/AssignTicketView.vue
  git commit -m "feat(assign-ticket): ambil baris tabel dari tickets-daily dengan filter tanggal"
fi
```
