import { useEffect, useRef } from "react";

/**
 * 「壁紙かえたい」で1段目のカードと差し替わる、横スクロールのスライダー
 * （2026-09-05、本人の指定：PCの `>wallpaperde` と同じ感覚で選びたい）。
 *
 * **カードの大きさは変えない。** 文字回答カードと同じく `.fetch .panel` の枠を
 * そのまま使い、中身だけを横スクロールにする（枠は grid の minmax(0,1fr) の段で、
 * ここが伸び縮みすると3段の等分が崩れる。2026-09-02 に一度そうなっている）。
 *
 * タップしたら決定。実際にPCの壁紙が変わり、変わったことは
 * wallpaper.changed / scheme.changed で勝手に届くので、ここでは待たずに閉じる
 * 側（App.tsx）へ任せる。
 */

export type WallpaperChoice = { id: string; name: string };

export function WallpaperPicker(
  { items, applying, onPick, onCancel }:
  { items: WallpaperChoice[]; applying: string | null; onPick: (id: string) => void; onCancel: () => void },
) {
  const scrollRef = useRef<HTMLDivElement | null>(null);

  // 開いた瞬間は先頭から。前回の位置を覚えていると、どこを見ているか分からなくなる
  useEffect(() => { if (scrollRef.current) scrollRef.current.scrollLeft = 0; }, []);

  return <section className="fetch panel paper-card" aria-label="WALLPAPER">
    <div className="paper-head">
      <span>WALLPAPER</span>
      <button className="paper-cancel" onClick={onCancel}>やめる</button>
    </div>
    {/* 横スクロール。scroll-snap で1枚ずつ気持ちよく止める */}
    <div className="paper-strip" ref={scrollRef}>
      {items.map(item => (
        <button
          key={item.id}
          className={`paper-item ${applying === item.id ? "paper-applying" : ""}`}
          onClick={() => onPick(item.id)}
          disabled={applying !== null}
          aria-label={item.name}
        >
          {/* loading="lazy" で、見えている数枚だけ取りに行く（75枚を一度に
              取りに行かせない）。decoding=async で描画を止めない */}
          <img src={`/wallpapers/${item.id}/thumb.webp`} alt="" loading="lazy" decoding="async" />
        </button>
      ))}
      {items.length === 0 ? <p className="paper-empty">壁紙が見つからなかった</p> : null}
    </div>
  </section>;
}
