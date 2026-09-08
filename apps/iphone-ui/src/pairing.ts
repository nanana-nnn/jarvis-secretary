/**
 * 端末の登録（DESIGN.md §13）。
 *
 * **同じ Wi-Fi にいるだけでは繋げない。** PC で `scripts/show-qr.py` を走らせて
 * 出た URL（`?pair=コード`）を開くと、ここが1回だけトークンへ引き換えて保存する。
 * 以後の WebSocket・承認・画像は、このトークンを持っていく。
 *
 * トークンは端末内（localStorage）にだけ置く。**URL に残さない**
 * （履歴・共有・スクショから漏れる）。引き換えたらクエリを消す。
 */
const KEY = "device-token";

export function deviceToken(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;                      // プライベートモードは読めない。未登録として扱う
  }
}

function keep(token: string): void {
  try {
    localStorage.setItem(KEY, token);
  } catch {
    /* 保存できなくても、この画面が開いているあいだは動く */
  }
}

/** `?t=` を足す。`<img src>` と WebSocket はヘッダを足せないため。 */
export function withToken(url: string): string {
  const token = deviceToken();
  if (!token) return url;
  return `${url}${url.includes("?") ? "&" : "?"}t=${encodeURIComponent(token)}`;
}

/** 承認・却下など fetch のヘッダ。 */
export function tokenHeaders(): Record<string, string> {
  const token = deviceToken();
  return token ? { "X-Device-Token": token } : {};
}

/**
 * URL に合図があれば引き換える。**引き換えても失敗しても、クエリからは消す。**
 * 合図は1回きりなので、再読み込みで撃ち直しても通らない。
 */
export async function claimPairingCode(): Promise<string | null> {
  const code = new URLSearchParams(location.search).get("pair");
  if (!code) return deviceToken();
  history.replaceState(null, "", location.pathname);
  try {
    const response = await fetch("/pair", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code, name: navigator.userAgent.slice(0, 40) }),
    });
    const body = await response.json();
    if (!response.ok || !body?.token) return deviceToken();
    keep(String(body.token));
    return String(body.token);
  } catch {
    return deviceToken();
  }
}
