/**
 * iPhone 本体を寝かせない（DESIGN.md §16「iPhone での常設条件」）。
 *
 * 常設のAI秘書端末なので、画面が消えると指パッチンも聞けなくなる。
 * Screen Wake Lock API を使う（iOS Safari 16.4 以降）。
 *
 * 気をつける点が2つある。
 *   - **タブが背面に回ると OS が勝手に解放する。** `visibilitychange` で
 *     取り直さないと、一度ホームへ戻っただけで二度と効かなくなる
 *   - **ユーザー操作の文脈が要ることがある。** 取れなかったことを黙って
 *     飲み込まず、呼び出し側へ返す（画面に出して手を打てるようにする）
 *
 * この API が無い環境では何もしない。その場合は iOS の設定で
 * 「自動ロック → なし」にするか、アクセスガイドを使う（§16）。
 */
export class ScreenWakeLock {
  private lock: WakeLockSentinel | null = null;
  private wanted = false;
  private readonly onVisible = () => { if (this.wanted) void this.acquire(); };

  static get supported(): boolean {
    return typeof navigator !== "undefined" && "wakeLock" in navigator;
  }

  /** 取得を試みる。取れたら true */
  async enable(): Promise<boolean> {
    this.wanted = true;
    document.addEventListener("visibilitychange", this.onVisible);
    return this.acquire();
  }

  async disable(): Promise<void> {
    this.wanted = false;
    document.removeEventListener("visibilitychange", this.onVisible);
    try { await this.lock?.release(); } catch { /* すでに解放済み */ }
    this.lock = null;
  }

  get held(): boolean {
    return !!this.lock && !this.lock.released;
  }

  private async acquire(): Promise<boolean> {
    if (!ScreenWakeLock.supported || document.visibilityState !== "visible") return false;
    if (this.held) return true;
    try {
      this.lock = await navigator.wakeLock.request("screen");
      // OS 側の都合で解放されることがある。次に前面へ戻ったとき取り直す
      this.lock.addEventListener("release", () => { this.lock = null; });
      return true;
    } catch {
      this.lock = null;
      return false;
    }
  }
}
