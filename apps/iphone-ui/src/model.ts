/** 画面が持つ値の形。コンポーネントとフックで共有する。 */
import type { Facts } from "./components/Fetch";

/** PC の実測値（5秒間隔で届く）。host だけは Fetch の Facts に無いので足す。 */
export type Telemetry = Facts & { host: string };

/** 承認待ちの提案（DESIGN.md §11）。押す前に読めないと意味がないので diff まで持つ。 */
export type Approval = {
  id: string;
  summary: string;
  files: string[];
  diff: string;
  warnings: string[];
};
