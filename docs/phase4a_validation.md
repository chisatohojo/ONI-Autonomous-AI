# Phase 4A 検証記録

2026-11-02（Asia/Tokyo）。開始HEAD d0e3d5b3b5dfd028dbd31f2670613db10caa0236、main/upstream origin/main、開始時作業ツリーclean。既存originを継続使用し、Git履歴を書き換えていません。

## 成果物と範囲

- [PC報告](phase4a_pc_environment.md)：指定したCIMプロパティ、NVML、64bit VRAM値、Vulkan/DLL、対象runtimeの有無。私的識別子・固有パスを除外。
- [ローカル候補](phase4a_local_models.md)：Qwen3.5-4B/2B、Gemma4 E2B、Phi4-mini等とruntime比較。容量・KV・contextを分け、推定とUNKNOWNを明示。
- [cloud/費用](phase4a_cloud_models.md)：公式資料による主要3社5モデル、構造/保存/料金/運用条件。S/M/L×100/1,000/10,000判断。
- [費用JSON](phase4a_cost_estimates.json)：Decimalで算出した45の合計、単価・仮定・確認日・参照URL・Geminiの価格期間。
- [Phase 4B案](phase4b_implementation_plan.md)：A/B/C選定、既存Protocolの接続、broker・schema・token/費用・停止、互換性、新しい保留条件、長期計画/記憶。

今回は調査・設計だけです。モデル・tokenizer・追加ソフト・runtimeを取得/導入せず、APIキーを作成/保存せず、生成APIや有料サービスを利用していません。PC/driver/Steam/ONI/MOD/セーブは変更せず、モデルサービスも起動していません。vulkaninfoはGPU列挙だけで、推論benchmarkではありません。新しい保留seedは文書に列挙しただけで生成/実行していません。

## 検証

| チェック | 結果 |
| --- | --- |
| 開始前pytest | 199 passed |
| 開始前ruff check / format | PASS（38 Python files） |
| 最終pytest | 199 passed |
| 最終ruff check / format | PASS（38 Python files） |
| src/tests/依存・lock・既存データ | 開始HEADから変更なし、実装版0.3.0維持 |
| 費用式 | 5モデル×3条件×3回数の45合計とMarkdown表を照合 |
| hardware数値 | 単位換算を照合。CIM AdapterRAMの不一致を記録し、NVML/64bit値を優先 |
| 文書/公開対象 | ローカルリンク、秘密情報・私的パス・識別子・禁止生成物の点検 |

ソフトウェアは既存のPython3.12.12、pytest8.4.2、ruff0.14.3を使用。バージョン更新や依存追加はありません。OpenAI候補の確認にはOpenAI Docsスキルを使い、公式APIドキュメントを参照しました。他社も公式モデルカード/料金/利用条件を優先し、本文や重みの転載はせず、独自の短い比較と計算を保存しました。

## 結論・未確認

GPUはRTX4060、NVML専用VRAM8,188MiB、RAM16GiB。空きRAM約3.6GiB/VRAM約5.4GiBの調査時点の条件では、ローカル小型量子化＋短contextを条件付きで評価するAを第一案とします。推論成功・速度・ピークメモリ・日英の判断精度はUNKNOWNです。適合しなければ小型化または承認されたBを再検討し、Cは独立比較後に段階導入します。

cloudの個別アクセス/quota/契約、完全なmodel digest、正確なtokenizerとprompt分の計数、provider別のreasoning/usage/請求校正は未確認です。費用試算は支出承認でも上限保証でもありません。既存workerのsocket遮断、spawnの環境継承、v1比較の固定定数という実装上の差分も次Phase案に明記しました。実ゲームの知識・互換性・規約/許諾の課題は引き続き別問題です。

最終点検では全81テキストファイル、変更11文書、ローカルMarkdownリンク97件を確認し、秘密情報・私的パス/識別子・禁止生成物のパターン検出は0件でした。費用45合計の一致、新seed案12件の非重複、src/tests/依存等が開始HEADと同一であることも確認しています。全文のシステムdumpや実行ログは追加していません。

ローカルコミットに記録し、完了報告でIDとclean状態を示します。Phase 4Aのpushは新たな承認を待ちます。
