// Copies Stockfish's single-threaded "lite" WebAssembly build into public/stockfish/
// so the browser can start it as a Web Worker.
//
// Why this build: single-threaded needs no SharedArrayBuffer, so the site needs no
// special cross-origin-isolation headers and works on any host. "Lite" uses a
// smaller neural network (~7 MB instead of ~75 MB), so the first load is quick.
// Files are renamed to stockfish.js / stockfish.wasm because the engine finds its
// .wasm by swapping the extension of its own URL.
import { copyFileSync, existsSync, mkdirSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const pkgDir = path.dirname(require.resolve('stockfish/package.json'));
const srcDir = path.join(pkgDir, 'src');
const outDir = path.resolve(here, '../public/stockfish');

const js = readdirSync(srcDir).find((f) => /^stockfish-.*-lite-single-[0-9a-f]+\.js$/.test(f));
if (!js) throw new Error('Could not find the lite single-threaded Stockfish build in node_modules/stockfish');

mkdirSync(outDir, { recursive: true });
copyFileSync(path.join(srcDir, js), path.join(outDir, 'stockfish.js'));
copyFileSync(path.join(srcDir, js.replace(/\.js$/, '.wasm')), path.join(outDir, 'stockfish.wasm'));
// Stockfish is GPLv3: its licence is served next to the engine.
if (existsSync(path.join(pkgDir, 'Copying.txt'))) {
  copyFileSync(path.join(pkgDir, 'Copying.txt'), path.join(outDir, 'COPYING.txt'));
}
console.log(`Stockfish ready: ${js} -> public/stockfish/stockfish.js`);
