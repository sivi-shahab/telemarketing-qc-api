// Ekspor preset audit BERBOBOT qc-collection menjadi tiga berkas Upload Campaign.
// Jalankan: node --experimental-strip-types scripts/export_collection_weighted_preset.mjs
import { writeFileSync, mkdirSync } from 'node:fs'
import { presetFor } from '/data/qc-collection/src/data/analysisPresets.ts'

const out = new URL('../campaigns/collection_weighted/', import.meta.url)
mkdirSync(out, { recursive: true })
const p = presetFor('weighted')
writeFileSync(new URL('prompt.txt', out), p.systemPrompt)
writeFileSync(new URL('scorecard.json', out), p.scorecardJson)
writeFileSync(new URL('kb.json', out), p.kbJson)
console.log('ok', JSON.parse(p.scorecardJson).length, 'item scorecard')
