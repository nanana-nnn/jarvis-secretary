import { afterEach, expect, it, vi } from 'vitest';
import { ReconnectingSocket } from './socket';

class FakeSocket extends EventTarget {
  static OPEN = 1;
  static instances: FakeSocket[] = [];
  readyState = 1;
  constructor(public url: string) { super(); FakeSocket.instances.push(this); }
  send() {}
  close() {}
}
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); FakeSocket.instances = []; });
it.each([4000, 1006])('handles close %s without a reconnect fight', code => {
  vi.useFakeTimers();
  vi.stubGlobal('window', globalThis);
  vi.stubGlobal('WebSocket', FakeSocket);
  const status = vi.fn();
  const client = new ReconnectingSocket('ws://test', status);
  client.start();
  FakeSocket.instances[0].dispatchEvent(Object.assign(new Event('close'), { code }));
  vi.advanceTimersByTime(31000);
  expect(FakeSocket.instances).toHaveLength(code === 4000 ? 1 : 2);
  expect(status).toHaveBeenCalledWith('closed');
  client.stop();
});
