# Frontend dependency lock status

PlantShift v7 keeps every frontend dependency pinned to an exact version and adds
`typescript-eslint==8.24.0` (npm syntax: `"typescript-eslint": "8.24.0"`) so the
ESLint 9 flat configuration parses and lints TypeScript/TSX using TypeScript-aware
recommended rules.

A genuine `package-lock.json` is intentionally **not** included because the npm
registry was unreachable in the verification environment (`EAI_AGAIN` while
resolving `registry.npmjs.org`). No lockfile was fabricated.

On a network-enabled machine, run:

```bash
cd frontend
npm install
npm ci
npm run lint
npm test
npm run build
```

After `npm install` generates the real lockfile, commit `package-lock.json`. The
existing frontend Dockerfile detects that lockfile and uses `npm ci`.
