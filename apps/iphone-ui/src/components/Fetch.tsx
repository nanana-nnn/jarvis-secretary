/**
 * Caelestia のログイン画面に出ている fastfetch 表示の移植。
 * ロゴを `Caelestia` から `JARVIS` に差し替えただけで、並びと書式は実物に合わせてある。
 *
 * ロゴは figlet の slant フォント（実物と同じ。pyfiglet で描かせて突き合わせ済み）。
 *
 * 実物は各項目の頭に Nerd Font のアイコンが付くが、iPhone Safari には Nerd Font が無く
 * 豆腐になるので落とした（DESIGN.md §15.1「確認できない字形は使わない」）。
 *
 * 枠は `╭─│╯` で描かない。罫線文字は等幅フォントに無いと別フォントへ落ち、
 * ASCIIと送り幅が変わって桁がずれる（実測: ASCII 4.58px/字 に対し罫線 9.16px/字）。
 * 見た目は同じ角丸の矩形なので、CSS の border で描けばフォントに依存しない。
 * 同じ理由で値の右寄せも padStart ではなく grid に任せる。
 */

const LOGO = [
  "       _____    ____ _    ___________",
  "      / /   |  / __ \\ |  / /  _/ ___/",
  " __  / / /| | / /_/ / | / // / \\__ \\",
  "/ /_/ / ___ |/ _, _/| |/ // / ___/ /",
  "\\____/_/  |_/_/ |_| |___/___//____/",
].join("\n");

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

// 実物と同じ並び
const ROWS: (keyof Facts)[] = ["kernel", "uptime", "shell", "mem", "pkgs", "user", "hname", "distro"];

export function Fetch({ facts, link }: { facts: Facts; link: string }) {
  return <section className="fetch" aria-label="JARVIS system information">
    <pre className="fetch-logo">{LOGO}</pre>
    <dl className="fetch-box">
      {ROWS.map(key => <div key={key}><dt>{key}</dt><dd>{String(facts[key])}</dd></div>)}
      <div><dt>link</dt><dd>{link}</dd></div>
    </dl>
  </section>;
}
