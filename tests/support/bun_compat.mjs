// Test-only shim for restricted hosts where Bun aborts before executing scripts.
// Production and native CI use Bun. Vendored files are never changed on disk.
import { registerHooks } from 'node:module';
import { readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';

globalThis.Bun = {
  stdin: { text: async () => readFileSync(0, 'utf8') },
  sleepSync: ms => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms),
  spawnSync: (argv, options = {}) => {
    const result = spawnSync(argv[0], argv.slice(1), {
      ...options, encoding: undefined,
      stdio: ['ignore', options.stdout === 'inherit' ? 'inherit' : 'pipe', options.stderr === 'inherit' ? 'inherit' : 'pipe'],
    });
    return { ...result, stdout: result.stdout ?? Buffer.alloc(0), stderr: result.stderr ?? Buffer.alloc(0), exitCode: result.status ?? 1, success: result.status === 0 };
  },
};
registerHooks({
  load(url, context, nextLoad) {
    const loaded = nextLoad(url, context);
    if (url.endsWith('.ts') && loaded.source) {
      return { ...loaded, source: loaded.source.toString().replace(/import\.meta\.dir\b/g, 'import.meta.dirname') };
    }
    return loaded;
  },
});
