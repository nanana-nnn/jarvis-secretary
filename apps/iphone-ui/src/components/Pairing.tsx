/**
 * 未登録のときに出す画面（DESIGN.md §13）。
 *
 * **ここでは何も判定しない。** 合図の引き換えは `pairing.ts` が URL から行う。
 * この画面が出ているのは「トークンを持っていない」ときだけなので、
 * 出すのは次にやることだけにする。
 */
export function Pairing() {
  return <main className="pairing">
    <h1>JARVIS</h1>
    <p>この端末はまだ登録されていない。</p>
    <ol>
      <li>PC で <code>.venv/bin/python scripts/show-qr.py</code> を走らせる</li>
      <li>出てきた QR を読む（または URL をこの端末で開く）</li>
    </ol>
    <p className="pairing-note">登録は1回だけ。以後はこの画面は出ない。</p>
  </main>;
}
