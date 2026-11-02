# Phase 4：LLM Policy接続計画（今回は設計とmockのみ）

Phase 4A補足（2026-11-02）：本書はPhase 3で定めたmock契約の履歴です。現在の候補・PC適合性・費用は[Phase 4A調査](phase4a_pc_environment.md)と[モデル比較](phase4a_cloud_models.md)、具体的な次Phase案は[Phase 4B計画](phase4b_implementation_plan.md)を参照してください。実接続・導入は未実施です。

Phase 3ではモデルをダウンロードせず、モデルサービス・実ゲームへ接続せず、API課金も行いません。[model_adapter.py](../src/oni_ai/model_adapter.py)は注入されたoffline mockでだけ検証しています。

## アダプタと予算

StructuredModelはmodel_id、tokenizer_revision、入力/出力の100万token当たり整数micro-USD単価、count_tokens、completeを持つProtocolです。completeはtextと入力/出力の実使用token数を含むModelReplyを返します。実際のHTTP/SDK実装はありません。

BudgetedModelAdapterは共通の知識検索、匿名化観測、目標、根拠、UNKNOWN、履歴を入力JSONへまとめ、Phase 3のenvelopeだけを受け付けます。自由文の任意ツール呼出しを実行しません。根拠の値・statusと行動前提の最終検査はrunnerに残します。

ModelLimitsの既定は入力8,000、出力2,000、累積20,000 tokens、累積100,000 micro-USD（$0.10）、1提案2試行、10秒です。これはmock検証用の予算例であり、実モデルの料金や実験への費用承認ではありません。試行前に最大出力を含めたtoken/費用を予約し、失敗や不正応答も返金しない保守的な台帳とします。料金UNKNOWNを無料へ置換しません。再試行時には例外本文や秘密情報でなく、短いエラーコードを返します。

token数はモデルの正しいtokenizerで数え、入力上限を超える履歴/知識は明示的な選別・要約または停止にします。テストのtoken counterは人工値であり、実tokenの精度を検証したものではありません。応答の使用数・サイズ・構造が予約範囲外なら拒否します。実APIではreasoning token、キャッシュ、ツール、地域課金等も料金式へ含め、非対応の請求体系は接続を拒否する必要があります。現実の請求を常に上限内に保証する機能は未実装です。

同期completeのtimeout_secondsだけで強制終了を保証しません。実接続時にはPolicy全体をPhase 3の専用プロセスに入れ、SDK期限・runner期限・安全な終了を併用します。呼出しを止めても既に送ったクラウド要求の課金が取り消されるとは扱いません。モデル名・版・温度・tokenizer・prompt/schema digest・sampling seed・実使用量・待ち時間・再試行・失敗を記録し、キーや認証headerは親プロセスの設定へ隔離し、ログ/Policy観測へ含めません。

## ローカルとクラウドの違い

確認日：2026-11-02（Asia/Tokyo）。下表の性能判断は選定時の比較方針です。今回モデルの速度・正確性・必要メモリを実測したわけではありません。

| 項目 | ローカルLLM | クラウドLLM |
| --- | --- | --- |
| 判断性能 | モデル規模・量子化・contextで変わる。小型だから必ず劣る/十分とは断定しない | 提供モデルごとに異なる。大規模モデルを利用できても、この課題での優位は測定する |
| ハードウェア | RAM/VRAMに重み・KV cache・実行時領域が必要。contextと並列数も効く | 推論GPUを自分で保有しない。ネットワークとクライアント実行環境は必要 |
| 費用 | 機器・電力・保守・モデルライセンスを含める。API単価0でも無料とは扱わない | 入出力token等の従量課金、上限・為替・追加機能を管理する |
| 運用 | モデル版・量子化・ランタイム・ドライバの固定、メモリと速度の測定が必要 | 認証、送信データ、保存条件、レート制限、可用性、モデル更新を管理する |
| 比較 | 同じ合成環境・情報・操作予算に加え、実機構成とtoken/s・遅延を記録 | 同じ条件に加え、モデル版・料金日付・使用量・遅延・再試行を記録 |

Ollamaの公式資料では、contextを増やすと必要メモリが増え、CPU/GPUへの配置を確認する必要があるとしています。[context資料](https://docs.ollama.com/context-length)、[FAQ](https://docs.ollama.com/faq)。たとえば8Bパラメータ×4bitは重みだけで理論上約4GBですが、これは計算上の下限であってVRAM要件ではありません。具体的な購入推奨や最低構成は、モデルを選び、KV cache等を含む実測をしてから判断します。

クラウドの一例としてAnthropicの[公式料金表](https://platform.claude.com/docs/en/about-claude/pricing)は入力/出力・キャッシュ等を区別します。今回は特定モデルの価格や順位をコードへ固定せず、導入時に最新の単価・対象版と請求範囲を確認します。

## 実接続の前に決めること

1. 使用するモデル/提供元、ローカル配布物のライセンス、送信許可範囲、ユーザーの費用上限を決定する。今回の承認からAPI利用を推定しない。
2. offline mockの契約テストに、遅延、途中出力、過大使用量、429/5xx相当、切断、期限、キー除去を追加する。実transportは別の明示承認後に実装する。
3. モデルごとに同じ情報・操作/step上限で比較する。token数はtokenizerに依存するため、同tokenだけで公平とせず、実token・費用・時間の別軸と共通の操作予算を示す。
4. まず新しい開発集合で調整し、新しい保留seed/条件と設定・promptを固定してから比較する。Phase 3で公開した保留seedを再び未知評価とは呼ばない。
5. 実ゲームの設備知識・OniMcp manifest・規約/許諾の課題は別途扱い、Phase 4のLLM試験も合成環境に限定する。
