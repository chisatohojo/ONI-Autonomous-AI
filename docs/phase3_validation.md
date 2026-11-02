# Phase 3 検証記録

履歴補足：d0e3d5b3b5dfd028dbd31f2670613db10caa0236はユーザー承認後にpush済みです。以下は当時の検証記録として保持します。

2026-11-02（Asia/Tokyo）。開始HEAD：27fb339b9d9508630e3216debe4f3f02650f18fe。開始時clean、mainのupstreamはorigin/main、既存originを継続使用しています。Phase 2は承認後push済みです。今回pushは実施せず、ローカルコミット後に承認を求めます。

## 検証結果

| 項目 | 結果 |
| --- | --- |
| 開始前pytest / ruff | 147 passed / check・format PASS |
| 全pytest | **199 passed**（既存147 + 追加52） |
| ruff check / format --check | PASS、38 Python files |
| uv sync --frozen --extra dev --offline | PASS、版0.3.0、追加依存0 |
| CLI開発比較 | 6環境seed×3 Policy seed×2 Policy = 36件、全件replay |
| 開発固定後の回帰比較 | 6×3×2 = 36件、全件replay |
| 開発固定後の保留比較 | 8×3×2 = 48件、全件replay |
| comparison-verify | 3群、120件の条件・JSON・CSV・Markdownすべて一致 |
| Phase 2の旧ログ | 開発/評価の既存12件、全件replay |
| wheelのoffline build / 別venvへの--no-deps導入 | PASS |
| wheelからの全report検証 | PASS |
| wheelの新プロセスで両Policyを再実行 | 2件とも元のreceiptとバイト単位一致 |

Windows x64、Python 3.12.12、pytest 8.4.2、ruff 0.14.3、uv 0.9.7、setuptools 80.9.0。実行時の追加依存、モデルSDK、モデルダウンロード、外部LLM呼出し、課金、実ゲーム接続はありません。

単体テストでは、構造化主張の改変/未取得/欠落、status昇格、観測のcontext/tick/digest、未対応操作、UNKNOWN未申告、子プロセスのハング・例外・ネットワーク遮断・起動失敗・総時間・呼出し/入出力予算、終了と一時ファイル削除、実行例外時の状態保持、ログ予算/途中終了/改変、浮動小数・複数tickの消費台帳、開発固定、CSV改変、モデルの予約予算・不正応答・再試行を検証しました。既存の反復・資源不足・エラー/進展停止テストも維持しています。

## 事前登録と評価の扱い

実験ディレクトリ：data/local/phase3-study-20261102（Git対象外）。各群にreport.json、metrics.csv、summary.md、episode JSONLがあります。

- plan_digest：9a6e358c5e1eeb977396217074ed619b1cac164f3c3146ff91261b268ceb837d
- 開発固定のsource_digest：d713b1227f5ee87676089691c48619e41b044a161a867cbc5980ed142b339f64
- 開発と回帰の環境seed：0,1,2,17,42,101（それぞれ別分布）
- 保留seed：203,307,409,503,607,709,811,907
- Policy seed：0,1,2。max_steps=30、no_progress=12、repeat=6、error=4、memory=16。1呼出し2秒/episode全体60秒、起動10秒、400呼出し、入力1MB、出力65,536 bytes。

保留集合は実装前に列挙し、比較単体テストでは別seedの1000/2000/3000だけを使いました。開発結果を固定してから回帰・保留を実行し、その後Policy/評価式/予算/ソースを変更していません。Phase 2で公開済みの評価6 seedは回帰評価と明記しています。新seedでも生成分布とモデル仕様は既知です。保留結果を公開した後の調整には、別の新しい保留集合を用意する必要があります。

## 比較結果

mean±SDはepisode間の記述統計です。Policy seedの反復を独立な環境標本とは見なしません。詳細な分布・欠損数・資源別の消費/残量・ペア差は[抜粋JSON](phase3_results.json)とローカルの全reportにあります。

| 群 | Policy | 目標達成 | 無効試行率 mean±SD | 試行数 mean±SD | 需要proxy true / known（UNKNOWN） |
| --- | --- | --- | --- | --- | --- |
| 開発 | exploration | 8/18 | 3.63±7.41% | 15.56±5.66 | 3/18（0） |
| 開発 | lookahead | 18/18 | 0±0% | 12.06±3.36 | 18/18（0） |
| 回帰 | exploration | 3/18 | 43.54±21.31% | 11.17±5.21 | 0/15（3） |
| 回帰 | lookahead | 6/18 | 0.93±2.62% | 10.83±3.59 | 0/18（0） |
| 保留 | exploration | 0/24 | 55.84±19.21% | 10.25±4.06 | 2/24（0） |
| 保留 | lookahead | 3/24 | 0.30±1.43% | 12.08±1.58 | 0/24（0） |

保留の目標差はseed607での3反復だけに由来し、残る7環境では両者とも目標未達です。環境内平均後の達成率ペア差はmean=0.125、SD=0.331、範囲0..1、環境n=8です。有意差や一般的な性能向上を主張しません。無効行動は少なくなりましたが、需要proxyは新Policyの方が低く、総合改善とは結論しません。proxyは実際の生存ではなく、今回の合成結果からONIの攻略性能は分かりません。

保留での終了は探索がERROR_LIMIT 8 / NO_PROGRESS 16、新PolicyがGOAL_REACHED 3 / NO_PROGRESS 20 / REPEATED_ACTION 1でした。通常の120件でプロセス/予算エラーは0件です。未申告UNKNOWNとclaim拒否も全件0ですが、UNKNOWNにより停止するprocessは残ります。UNKNOWNを既知値へ変換して動かした結果ではありません。

失敗履歴後の意図変更・適用、失敗理由数の減少・作業進捗を別に保存しています。これらは機会数や終了時点の違いに左右され、計画の改善能力の因果的な証明ではありません。資源消費も終了tick・目標到達の有無と合わせて読む必要があります。到達不能かもしれないUNKNOWN/研究制約条件も含み、全未達をPolicyだけの失敗とは断定しません。

## 制限・Phase 4へ

新Policyは人が決めた短い探索と評価式で、LLM・学習済みPolicyではありません。長期計画や実ゲーム物理を扱いません。根拠検証は構造化主張との一致であり、自由文全体の意味・最適性の証明ではありません。プロセス期限は信頼済みコードの停止であり、OS sandboxや子孫プロセス全般の隔離ではありません。replayの故障イベントとcleanup記録は元の故障原因・終了操作を再実行する証明ではありません。ログ署名は未実装です。

[Phase 4計画](phase4_model_plan.md)に、モデル非依存のJSON入力/出力、token・時間・費用の予約、期限・再試行、異常応答、ローカル/クラウドの比較を記載しました。実transport、実tokenizer・請求式との校正、鍵の除去、ローカルモデルのハードウェア実測は次の課題です。実ゲーム知識DBのUNKNOWN、OniMcp manifestと文書差異、互換性、Steam/Kleiの適用条件は未解決のままです。

コミット対象は24変更ファイル、全75テキストファイルです。秘密情報パターン・禁止生成物の点検で検出0件、ローカルMarkdownリンク68件も存在を確認しました。DB、raw JSONL、全量の生成レポート/CSV、wheel、ツール、仮想環境はGit対象外です。公開する結果JSONは独自の合成集約値だけの抜粋です。Phase 0/1 DBのSHA256、Phase 1/2コア実装・旧147テスト、開発固定のソースdigestが変わっていないことも確認しました。

ローカルコミットに記録し、最終IDとclean状態は完了報告に記載します。GitHub pushは新たな承認を待ちます。
