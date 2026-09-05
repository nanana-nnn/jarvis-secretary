/**
 * Caelestia のログイン画面に出ている fastfetch 表示の移植。ロゴだけ JARVIS に差し替える。
 *
 * 書式は推測せず `~/.config/fastfetch/config.jsonc` から起こした。
 * アイコンのコードポイントも同じ（設定の key に直接埋まっている）。
 *
 * ロゴは figlet の slant フォント。実物と同じであることは pyfiglet に
 * `Caelestia` を描かせて突き合わせて確認済み。幅は枠と同じ37桁。
 *
 * 枠は罫線文字で描く。字送りが揃っていないと桁が崩れるので、
 * 送り 0.6em で揃った Nerd Font のサブセットを同梱して当てている
 * （public/fonts/。当たらないと崩れるが、同一オリジンなので取りこぼさない）。
 */

import { ABSOLUTE_MIN_RMS } from "../audio/clap-detector";
import type { ClapLog } from "../audio/types";

export type Facts = {
  kernel: string;
  uptime: string;
  shell: string;
  mem: string;
  pkgs: number;
  user: string;
  hname: string;
  distro: string;
};

const LOGO = [
  "       _____    ____ _    ___________",
  "      / /   |  / __ \\ |  / /  _/ ___/",
  " __  / / /| | / /_/ / | / // / \\__ \\",
  "/ /_/ / ___ |/ _, _/| |/ // / ___/ /",
  "\\____/_/  |_/_/ |_| |___/___//____/",
].join("\n");

/**
 * 並び・ラベル・アイコンは config.jsonc の modules と同じ。
 * 実物は端末での見え方に合わせてアイコンの後ろの空白を1〜2個で書き分けているが、
 * ここは Mono 版（全字が同じ送り）を当てるので一律にして桁を揃える。
 */
// user と distro は表示から外した（本人の判断、2026-09-01）。
// 単一ユーザー・単一機種の常設端末では毎回同じ値しか出ず、5段目・6段目として
// 場所を取るだけだった。Facts 型と telemetry の送信自体は変えていない
// （他で使う可能性があるため）。
const ROWS: { key: keyof Facts; icon: string }[] = [
  { key: "kernel", icon: "\uf473" },
  { key: "uptime", icon: "\ue385" },
  { key: "shell", icon: "\uf489" },
  { key: "mem", icon: "\uefc5" },
  { key: "pkgs", icon: "\uf487" },
];

/**
 * 待機中に聞こえた音を1行で見せる（2026-09-05）。
 *
 * 検出器が残している直近30件のうち、右端が最新。**実測しか出さない。**
 * 高さは「起動のしきい値（ABSOLUTE_MIN_RMS）に対する比」で決める。
 * 生の RMS を出すと静かな部屋では棒がほとんど動かず、指パッチンも伸びない。
 * 比にすると、部屋の静かさに関係なく「越えたかどうか」がそのまま高さになる。
 *
 * 受理した1回は必ず満杯（█）にする。棒の高さでは他の大きな音と見分けが付かない。
 *
 * **使えるのはこの3字だけ。** 同梱の Nerd Font サブセットで送りが揃うことを
 * 実測して選んである（2026-09-05、基準9pxに対して ▁▂▃▅▆▇ ░▒▓ ▏▎▍▌ 点字は
 * すべて15.2pxの別フォントへ落ちて、箱の右の罫線が壊れた）。
 * **字を増やすときは必ず送りを測ること。** 見た目で選ばない。
 */
const QUIET = "_";      // しきい値に届かない音
const NOISE = "▄";      // しきい値は越えたが、起動条件に合わなかった音
const WAKE = "█";       // 起こした1回
export const WAKE_GLYPHS = QUIET + NOISE + WAKE;

export function wakeRow(logs: ClapLog[], width: number): string {
  const bars = logs.slice(-width).map(log => {
    if (log.accepted) return WAKE;
    // 検出器と同じ関門で分ける（clap-detector の threshold）。
    // 別の基準で描くと、画面の棒と実際の判定がずれる
    return log.rms >= ABSOLUTE_MIN_RMS ? NOISE : QUIET;
  }).join("");
  // 足りないぶんは静けさで左を埋める。空白にすると桁が空いて見える
  return bars.padStart(width, QUIET);
}

const WIDTH = 37;        // 枠の総桁数。ロゴ(slant)の幅と揃えてある
const LABEL = 6;         // 最長ラベル "kernel" / "uptime" / "distro"
const VALUE = 22;        // config.jsonc の `{...>22}` と同じ
const LINE = "─".repeat(WIDTH - 2);

// `│ ` + アイコン + `  ` + ラベル(6) + `  ` + 値(右詰め22) + ` │` = 37桁
function row(icon: string, label: string, value: string): string {
  const shown = value.length > VALUE ? value.slice(0, VALUE) : value;
  return `│ ${icon}  ${label.padEnd(LABEL)}  ${shown.padStart(VALUE)} │`;
}

/**
 * `glow` は聞き取り中の呼吸（2026-09-02）。LISTENING のあいだ 1段目は
 * このカードのままにする（本人の指定：聞いている間は上のカードを変えない）
 * ので、呼吸の演出だけをここへ乗せる。答えを出すときは AnswerCard 側が
 * 同じ見た目を引き継ぐ。
 *
 * `sweep` は聞き始めた瞬間だけ true になり、光が縁を1周してから呼吸へ渡す
 * （本人の指定・2026-09-03）。sweep が立っているあいだは glow-active を
 * 出さない（両方同時に付けると呼吸と1周が重なって喧嘩する）。
 */
export function Fetch(
  { facts, link, glow, sweep, wake }:
  { facts: Facts; link: string; glow?: boolean; sweep?: boolean; wake?: ClapLog[] },
) {
  const rows = ROWS.map(({ key, icon }) => row(icon, key, String(facts[key])));
  // **アイコンは空白にする。** 同梱しているのは Nerd Font のサブセットで、
  // 表に無いコードポイントを足すと豆腐になり、送りが変わって37桁が崩れる。
  // 既存の5行が使っている字だけが当たることを確認済み（2026-09-02）
  if (wake) rows.push(row(" ", "wake", wakeRow(wake, VALUE)));
  const body = rows.join("\n");
  const glowClass = sweep ? "glow-sweep" : glow ? "glow-active" : "";
  return <section className={`fetch panel card-glow ${glowClass}`} aria-label="JARVIS system information">
    {/* 高さの切り落としは この内側の div が持つ。section 側で overflow:hidden に
        すると .card-glow の発光層まで切られて光が消える（style.css .fetch-clip）*/}
    <div className="fetch-clip">
      <pre className="fetch-logo">{LOGO}</pre>
      <pre className="fetch-box">{`╭${LINE}╮\n${body}\n╰${LINE}╯`}</pre>
    </div>
    <span className="sr-only">link {link}</span>
  </section>;
}
