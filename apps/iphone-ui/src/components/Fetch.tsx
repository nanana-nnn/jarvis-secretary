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
  { facts, link, glow, sweep }: { facts: Facts; link: string; glow?: boolean; sweep?: boolean },
) {
  const body = ROWS.map(({ key, icon }) => row(icon, key, String(facts[key]))).join("\n");
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
