import express from 'express';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT) || 3000;
const { SUPABASE_URL, SUPABASE_KEY } = process.env;
if (!SUPABASE_URL || !SUPABASE_KEY) {
  console.error('.env dosyasında SUPABASE_URL ve SUPABASE_KEY olmalı.');
  process.exit(1);
}

const app = express();

// Tarayıcıya sadece herkese açık (publishable) anahtar gider.
app.get('/config.js', (_req, res) => {
  res.type('application/javascript').send(
    `export const SUPABASE_URL = ${JSON.stringify(SUPABASE_URL)};\n` +
    `export const SUPABASE_KEY = ${JSON.stringify(SUPABASE_KEY)};\n`,
  );
});
app.use(express.static(path.join(ROOT, 'public'), { extensions: ['html'] }));

app.listen(PORT, '0.0.0.0', () => {
  console.log(`Mobilya AR: http://localhost:${PORT}`);
  for (const nets of Object.values(os.networkInterfaces())) {
    for (const n of nets || []) {
      if (n.family === 'IPv4' && !n.internal) console.log(`Telefondan:  http://${n.address}:${PORT}`);
    }
  }
});
