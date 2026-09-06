import { afterEach, expect, it, vi } from 'vitest';
import { ReconnectingSocket } from './socket';
import { handle, type SocketActions } from '../hooks/useSecretarySocket';

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

it('壁紙変更後は成功表示を残し、すぐ待機へ戻さない', () => {
  const actions: SocketActions = {
    send: vi.fn(), setCaption: vi.fn(), setSpeaking: vi.fn(), setHeardNothingAt: vi.fn(),
    setPapers: vi.fn(), setWallpaperPending: vi.fn(), setApplyingPaper: vi.fn(), setApproval: vi.fn(),
    setLive: vi.fn(), setTelemetry: vi.fn(), qaUpdate: vi.fn(),
    qaAddLine: vi.fn(), qaAddLines: vi.fn(),
  };

  handle({ type: 'wallpaper.applied', ok: true }, actions);

  expect(actions.setCaption).toHaveBeenCalledWith('壁紙を変えたよ');
  expect(actions.qaAddLine).toHaveBeenCalledWith('壁紙を変えたよ');
  expect(actions.qaUpdate).toHaveBeenCalledWith({ phase: 'done' });
  expect(actions.send).not.toHaveBeenCalledWith('IDLE');
});
