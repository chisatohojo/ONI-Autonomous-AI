# Phase 4B1 検証記録

2026-11-06（Asia/Tokyo）。開始HEAD：8a96055655ca7307123af0cfcdba1c015aa3a086。実装版0.4.0b1。Phase 4Aの承認後pushを引き継ぎ、同じmain/originを使用しています。

## 検証結果

| 検査 | 結果 |
| --- | --- |
| 開始時pytest / ruff check / format | 199 passed / PASS / PASS（38 Python files） |
| 最終pytest | **257 passed**（既存199を維持、58件追加） |
| 最終ruff check / format | PASS / PASS（46 Python files） |
| 新しいmock比較v2 | 24エピソード（開発12＋validation12）、全件receipt/sidecar/report検証成功 |
| mock生成 | 40要求、usage未検証0、予約後の結果欠落0 |
| 旧Phase 2ログ | 開発6＋評価6、計12件replay成功 |
| 旧Phase 3比較v1 | 開発36＋回帰36＋旧保留48、計120件のreceipt/集約検証成功 |
| wheel | offline build、別venvへ自身のwheelのみ導入、`-I`起動の新規Policy/broker推論・後始末成功。旧132件と新24件の検証も成功 |
| SQLite | 既存DBを読み取り専用snapshotとして使用、元ファイルSHA256不変 |
| 実LLM・課金・導入 | いずれも未実施。外部runtime/モデル/tokenizerの追加なし、実行時外部依存0 |

Python3.12.12、pytest8.4.2、ruff0.14.3、uv0.9.7、setuptools80.9.0を維持しました。version/lockの自身のpackage metadataだけを0.4.0b1へ更新し、固定dependencyを追加・更新していません。

使用コマンド：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.tools\uv.exe build --wheel --offline --cache-dir .tools/uv-cache
```

wheel検証は既存Pythonから作成した`.tools/phase4b1-wheel-env`に、`--offline --no-deps`でプロジェクト自身だけを導入しています。初回buildでは既定cacheに固定setuptoolsがなくoffline解決が停止しました。ネット取得は行わず、既存のプロジェクト専用cacheを指定して成功しました。

## 異常系と停止

[推論テスト](../tests/test_inference.py)で不正JSON、部分出力、schema非対応/循環/型、モデル不一致、usage欠落/負数/bool/過大、未対応の正確counter、上限超過、接続失敗、期限、重複/競合ID、ticket再利用、秘密情報、観測不一致、架空根拠、UNKNOWNの昇格を検査します。対応しない実モデルはtransport呼出し0回で停止します。失敗分の予約保持と限定retryも確認しています。

実プロセスを起動するテストでは親の環境canary非継承、socket遮断、brokerとPolicy双方のhang/異常終了、両workerの停止と一時領域削除を検証しました。予約を生成前に原子的ファイルへ記録し、強制終了でusageが不明でも返金しないことを検査しています。架空の秘密canaryは監査にも保存しません。

[比較v2テスト](../tests/test_model_comparison.py)ではpaired条件、開発freeze、source不一致、group間の予算共有、sidecar/CSVの改変、CLI/replay、B2・実モデル実行口が未公開であることを確認します。旧199テストは変更していません。

検証途中にWindowsの一時的PermissionError（応答ファイルの共有拒否）を確認しました。期限を守るファイル操作retryと固定エラーコードへの変換を追加し、再現テストを追加しました。失敗した`data/local/phase4b1-smoke-20261106`の途中成果は削除・上書きせず保持し、修正後に別出力先で全件を実行しました。旧失敗planは修正前のsource hashのままです。

## 最終CLI実験

出力先はGit対象外の`data/local/phase4b1-verified-20261106`。READMEのmodel-compare-prepare→development→freeze→validation→verifyを実行しました。既存DBのreadonly snapshot付き、最大5step、共通memory上限2、同一観測/操作予算、Policy seed 0/1です。

plan digest：`7cc9b32cdd14354b856e3c735422e8dcfc24a68c1264cda04cbdad9b2266512c`

development digest：`def39c5eff1d531cbd7bea168e72ceeb8ef7d768ca0eda202aaee616fdcd2f87`

| group | 環境seed | episodes | mock生成 | 予約tokens | 検証済入力 | 検証済出力 | 不明usage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| mock-development | 4001/4003 | 12 | 20 | 2,795,147 | 1,484,427 | 310,224 | 0 |
| mock-validation | 5003/5009 | 12 | 20 | 2,836,556 | 1,525,836 | 310,766 | 0 |
| 合計 | 配線検証のみ | 24 | 40 | 5,631,703 | 3,010,263 | 620,990 | 0 |

study予約上限10,000,000人工tokens、100,000,000人工microUSDのうち、予約5,631,703 tokens／8,253,143人工microUSDを消費し、validationにも残予算を引き継ぎました。検証済usageの人工費用は4,252,243 microUSDです。成功分も予約を返金しないので一致しません。いずれも**人工byte仕様と価格によるテスト算術**で、実LLM token数・料金・課金結果ではありません。

exploration/lookahead/model-mock各8件。model-mockの返答は探索Policyによるtest doubleで、LLM推論やLLM品質順位の実験ではありません。JSON/CSV/Markdownと全sidecarはローカルに保持します。replayはPolicy/transportを呼び直さず合成遷移と構造化監査を照合します。

既存DBの不変hash：

- Phase 0：cf6de2574f95cf73b5a2c17018280a49109d41378bfd77d5794fcc3c8e404fa0
- Phase 1：01e160c86b7f0c241468b797a684d3a7b389aa2dc4253c0d00be503444e96eaf

## 未確認・次のgate

実モデルの正確tokenizer/template、schema互換、usage（thinking・切捨てを含む）、メモリ適合、速度、判断品質はUNKNOWNです。現在のworker遮断はOS sandboxではなく、秘密検出は固定パターンです。実runtimeのキャンセル・解放はmock停止から保証できません。replayは失敗事象/後始末の記録を照合しますが、物理的な停止を再演するものではありません。

[B2引継ぎ](phase4b2_handoff.md)にモデル候補、16GiBの計画予約枠、未作成の保存先、正確計数gate、実測項目、停止条件、新開発/保留の事前登録案を記載しました。B2のfixtureは生成・実行していません。モデル導入・実通信は今回の承認に含めず、ゲーム接続は引き続き禁止です。

公開対象はソース・テスト・文書・固定metadataのみを点検してローカルコミットします。生成DB、実験ログ、wheel、venv、download、秘密情報、個人パス/識別子、ゲーム資産は含めません。GitHubへのpushは別途承認を待ちます。

最終index点検：全93ファイル（変更23）、ローカルMarkdownリンク123件を確認し、禁止生成物・秘密token/private-key・個人パスのパターン検出は0件でした。credential URL検出の1件はtests内のexample.invalidを使った明示的な架空canaryです。自動検出の限界を踏まえ、stage差分も確認しています。旧テスト・設備データの変更はありません。
