/**
 * A worker's service that fails to start (tests/support/process/servers.ts) says why: its error
 * carries what the service wrote, which the worker's failed fixture keeps nowhere else. No
 * browser and no backend: the plain test of @playwright/test, so that the worker starts no
 * services for it.
 */

import { createServer, type Server } from 'node:net';
import { expect, test } from '@playwright/test';
import { createFrontendLogCollector } from '../support/process/backend-logs';
import { startFrontend } from '../support/process/servers';

function listen(server: Server): Promise<number> {
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      if (address === null || typeof address === 'string') {
        reject(new Error(`No port for ${String(address)}`));
        return;
      }
      resolve(address.port);
    });
  });
}

test.describe('A service that fails to start', () => {
  test('says why: its exit and, below it, its own output, the dev server’s on a taken port', async () => {
    const taken = createServer();
    const port = await listen(taken);
    const logs = createFrontendLogCollector({ workerIndex: test.info().workerIndex, streamToConsole: false });

    try {
      await expect(
        startFrontend({ workerIndex: test.info().workerIndex, backendUrl: 'http://127.0.0.1:9', logs, port })
      ).rejects.toThrow(
        new RegExp(
          String.raw`frontend\] process exited before ready \(code=1, signal=null\)\n` +
            String.raw`[\s\S]*\[stderr\] Port: ${port}\n` +
            String.raw`[\s\S]*\[stderr\] .*Port ${port} is already in use`
        )
      );
    } finally {
      logs.dispose();
      taken.close();
    }
  });
});
