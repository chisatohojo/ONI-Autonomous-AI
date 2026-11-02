# Phase 4A：クラウド候補と費用

確認日：**2026-11-02（Asia/Tokyo）**。標準の同期テキストAPI、通常地域、非キャッシュ入力・通常出力で比較します。ブラウザで公式資料を閲覧しただけで、生成API・token計数API・管理APIへは接続していません。アカウントの利用可能モデル、個別レート上限、契約条件はUNKNOWNです。

## 候補

| モデルID | 選定上の役割（性能は未実測） | 構造化出力 | 入力 / 出力 USD per 1M tokens |
| --- | --- | --- | --- |
| **gpt-6-luna** | 大量比較の低費用候補。複数制約や長期計画の精度は要検証 | 対応と公式記載 | **0.10 / 0.50** |
| **gpt-6.1-sol** | **クラウドの第一参照候補**。費用と複雑な判断能力の均衡を検証する | 対応と公式記載 | **2.00 / 10.00** |
| gpt-6-astra | 複雑な判断の高費用な参照上限候補。最初の大量試行には選ばない | 対応と公式記載 | 10.00 / 50.00 |
| **claude-sonnet-5-5** | 別系列の比較候補。長い履歴と構造化判断を検証する | JSON outputs / strict tool use。API subsetの検査が必要 | **2.00 / 10.00** |
| **gemini-3.8-flash** | 別系列の費用/遅延比較候補。agent用途の公称能力を検証する | JSON Schema subsetに対応 | **0.75 / 3.75**（2026-12-31までの表示） |

根拠：[OpenAI公式モデル一覧](https://developers.openai.com/api/docs/models)、[Luna](https://developers.openai.com/api/docs/models/gpt-6-luna)、[Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol)、[Astra](https://developers.openai.com/api/docs/models/gpt-6-astra)、[標準料金](https://developers.openai.com/api/docs/pricing)、[Claude Sonnet 5.5](https://platform.claude.com/docs/en/models/sonnet-5-5/overview)、[Claude料金](https://platform.claude.com/docs/en/about-claude/pricing)、[Gemini 3.8 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash)、[Gemini料金](https://ai.google.dev/gemini-api/docs/pricing)。

各社の計画/agent性能は提供者の用途説明であり、同じONI合成課題での順位ではありません。OpenAI/Claudeの主要候補とGemini Flashはいずれも長contextを公称しますが、既存入力の絞込みを省略する理由にはしません。日本語・英語の指示追従、事実の引用、UNKNOWN、失敗後の修正を同一条件で実測します。

Geminiの上記料金は期間付きです。公式表示では**2027-01-01から入力1.50/出力7.50**となり、同条件の試算は2倍です。OpenAIの表はStandardとFlex/Batch/Fast等が別であり、低いBatch料金やキャッシュ割引を通常の自律ループへ流用していません。税・為替・決済手数料は未算入です。

## 構造・時間・レート・運用

| 項目 | OpenAI | Anthropic | Google Gemini |
| --- | --- | --- | --- |
| schema指定 | Responsesの構造化JSON。モデルごとの対応subsetを検査 | Messagesのoutput_config.format。既知のsubset/制限を検査 | JSON MIME/schema設定。subsetを検査 |
| 処理時間 | 実測UNKNOWN。reasoning設定・入力/出力長で変わる | 実測UNKNOWN。公称Fastでも秒数保証ではない | 実測UNKNOWN。thinking・出力長で変わる |
| 個別quota | UNKNOWN。organization/project/model/tierに依存 | UNKNOWN。tierとRPM/input/output TPM等に依存 | UNKNOWN。project単位のRPM/TPM/RPD等 |
| キー | 今回作成/取得しない。将来はbrokerだけに供給 | 同左。ログのheader・エラーからも除去 | 同左。APIキーをURL queryや評価入力へ混ぜない |
| 更新リスク | alias/モデル廃止、API形状、単価変更を監視 | model ID/版・retirement・thinking仕様を記録 | stable IDでも更新/廃止と期間料金を監視 |

根拠：[OpenAI schema](https://developers.openai.com/api/docs/guides/structured-outputs)・[rate limits](https://developers.openai.com/api/docs/guides/rate-limits)・[deprecations](https://developers.openai.com/api/docs/deprecations)、[Claude schema](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)・[rate limits](https://platform.claude.com/docs/en/api/rate-limits)、[Gemini schema](https://ai.google.dev/gemini-api/docs/structured-output)・[rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)・[deprecations](https://ai.google.dev/gemini-api/docs/deprecations)。

初回は並列1とし、実測p50/p95遅延・token使用・失敗率を開発集合で測ります。再試行はrunner側の予算に数え、SDKの暗黙retryを無効化するか明示計上します。429等へのbackoffにも全体期限を適用します。schema準拠でも資源不足や架空の根拠は別のローカルvalidatorで拒否します。

## 送信・保存条件

| サービス | 確認できた一般条件 | 未確認/導入前に確定すること |
| --- | --- | --- |
| OpenAI API | 明示opt-inがなければ学習利用しない。abuse logは通常最大30日等の例外あり。Responsesのstate保存はstore等の設定/機能に依存 | store=falseを設計しても無保存とは断定しない。ZDRは適格性・承認が必要。個別契約/地域はUNKNOWN |
| Anthropic API | 標準では入力/出力を通常30日以内に削除、法令/規約等の例外あり。ZDRは別条件。Covered Modelsには別の保持要件がある | 今回のアカウント/契約はUNKNOWN。選定したモデルとMessages/schema機能を単位に確認し、他モデルの条件を流用しない |
| Gemini Developer API | Paid Servicesではprompt/responseを製品改善に使わない。abuse監視等の限定保持あり。無料枠とはデータ条件が違う | 無料枠を「無送信/無保存」と扱わない。保証されたZDR等が必要なら公式のVertex等の条件を別途確認 |

根拠：[OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data)、[Anthropic標準保持](https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data)・[機能別保持](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention)、[Gemini ZDR説明](https://ai.google.dev/gemini-api/docs/zdr)・[追加利用条件](https://ai.google.dev/gemini-api/terms)。これは閲覧時点の整理で、個別契約への法的判断ではありません。将来送信するのは承認された合成観測・必要な独自要約だけとし、PC調査結果・ユーザーパス・秘密情報・ゲーム/セーブデータを送信対象にしません。

## 判断回数ごとの費用試算

各1判断＝1生成要求と仮定します。出力tokenには**JSON本文だけでなく課金対象のthinking/reasoningも含める**想定です。モデル間で同じ文字列が同じtoken数になるという意味ではありません。

| シナリオ | 入力token | 課金出力token | 想定用途 |
| --- | ---: | ---: | --- |
| S | 2,000 | 500 | 小さい観測と最小の根拠・履歴 |
| M | 8,000 | 1,500 | 履歴と検索知識を多めに含める |
| L | 16,000 | 3,000 | 長い履歴。現行既定input=8,000を超えるため別設定が必要 |

`USD = 判断数 × (入力token × 入力単価 + 課金出力token × 出力単価) / 1,000,000`

| モデル | シナリオ | 100判断 USD | 1,000判断 USD | 10,000判断 USD |
| --- | --- | ---: | ---: | ---: |
| GPT-6 Luna | S | 0.045 | 0.45 | 4.50 |
| GPT-6 Luna | M | 0.155 | 1.55 | 15.50 |
| GPT-6 Luna | L | 0.31 | 3.10 | 31.00 |
| GPT-6.1 Sol | S | 0.90 | 9.00 | 90.00 |
| GPT-6.1 Sol | M | 3.10 | 31.00 | 310.00 |
| GPT-6.1 Sol | L | 6.20 | 62.00 | 620.00 |
| GPT-6 Astra | S | 4.50 | 45.00 | 450.00 |
| GPT-6 Astra | M | 15.50 | 155.00 | 1,550.00 |
| GPT-6 Astra | L | 31.00 | 310.00 | 3,100.00 |
| Claude Sonnet 5.5 | S | 0.90 | 9.00 | 90.00 |
| Claude Sonnet 5.5 | M | 3.10 | 31.00 | 310.00 |
| Claude Sonnet 5.5 | L | 6.20 | 62.00 | 620.00 |
| Gemini 3.8 Flash | S | 0.3375 | 3.375 | 33.75 |
| Gemini 3.8 Flash | M | 1.1625 | 11.625 | 116.25 |
| Gemini 3.8 Flash | L | 2.325 | 23.25 | 232.50 |

Decimalで式を検算し、[機械可読な前提・結果](phase4a_cost_estimates.json)も保存します。キャッシュ・Batch・tools・画像・検索・保存費・税・為替・再試行はこの表に含めません。2回とも同程度を生成するなら概算2倍ですが、実際はrepair入力や追加思考で変わります。出力が想定を超えれば増額します。この表は見積もりであり課金の承認ではありません。

選定：まずローカルのみを試験し、課金と送信が別途承認された場合の品質参照をGPT-6.1 Sol、低費用比較をGPT-6 Lunaとします。今回の資料だけでは各社のこの課題での優劣は確定できません。Anthropic/Geminiの追加は、単一transportの検証が通ってから比較対象として検討します。
