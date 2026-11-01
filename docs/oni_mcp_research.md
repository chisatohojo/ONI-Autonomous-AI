# OniMcp調査報告書

Phase 1追記（2026-11-01）：同じ固定コミットを継続使用しています。新しい操作別の証跡は[operation_catalog.json](../src/oni_ai/data/operation_catalog.json)に記録しました。GameControlTools/GameSpeedToolsのpause/resume/step_until経路、OrdersToolsの診断経路、ResearchToolsの内部操作を静的確認しています。すべて実機未検証・live_execution_allowed=falseです。

特にBuildingControlTools.cs L87-L94には、仮想ファイル編集文脈以外の直接build_areaを拒否するガードがあります。本報告の下位build_areaハンドラのconfirm/dryRun説明は、直接tools/callで建設できるという意味ではありません。操作catalogではDIRECT_PUBLIC_ROUTE_FORBIDDENと記録しました。protocolの文書/コード不一致はUNRESOLVEDで、実行時manifestは未取得です。

調査日：2026-11-01（Asia/Tokyo）。方式：GitHub接続ツールによる固定ソースの静的読解。インストール・ビルド・外部コード実行・ゲーム接続は実施していません。

## 対象と結論

対象：[LIghtJUNction/OniMods](https://github.com/LIghtJUNction/OniMods)。
参照コミット：[`14c08591cbd0bf66cd0f53b37bfb498bdef4abf6`](https://github.com/LIghtJUNction/OniMods/commit/14c08591cbd0bf66cd0f53b37bfb498bdef4abf6)、コミット日時：2026-10-30T09:51:07Z。
`OniMcp.csproj` のModVersionは0.2.6、Rust CLIのonimは0.1.8です。mainやタグを追従せず、このハッシュを調査基準にします。

**1.0未満ではツール名・パラメータ・応答・HTTP動作に破壊的変更があり得ます。実行時の `oni://tools/manifest` と `tools/list`、実際のcapabilityが最終的な仕様です。** ソース中に存在する内部APIと、クライアントから利用できるAPIは区別します。

必須確認資料：[README_EN.md](https://github.com/LIghtJUNction/OniMods/blob/14c08591cbd0bf66cd0f53b37bfb498bdef4abf6/mods/OniMcp/README_EN.md)、[mcp-tools-reference.md](https://github.com/LIghtJUNction/OniMods/blob/14c08591cbd0bf66cd0f53b37bfb498bdef4abf6/docs/mcp-tools-reference.md)、[api-developer-guide.md](https://github.com/LIghtJUNction/OniMods/blob/14c08591cbd0bf66cd0f53b37bfb498bdef4abf6/docs/api-developer-guide.md)、[LICENSE](https://github.com/LIghtJUNction/OniMods/blob/14c08591cbd0bf66cd0f53b37bfb498bdef4abf6/LICENSE)。その他の読解対象・blob SHA・取得テキストSHA256は [source_evidence.json](source_evidence.json) に記録しています。ハッシュは接続ツールから得たUTF-8テキストをLFで保存したものです。

## 文書と実装の差異（重要）

| 対象 | 文書の説明 | 固定コードから確認した動作 |
| --- | --- | --- |
| MCP 2026-07-28 | stateless、server/discover、リソースとbenchmarkのみ | 廃止済みとして拒否する実装 |
| MCP 2025-06-18 | initialize/session互換 | サポート版リストに存在せず拒否 |
| MCP 2025-11-25 | initialize/session、公開ツール群 | 唯一のサポート版 |

根拠：[McpHttpServerProtocolTasks.cs L66-L84](https://github.com/LIghtJUNction/OniMods/blob/14c08591cbd0bf66cd0f53b37bfb498bdef4abf6/mods/OniMcp/Server/McpHttpServerProtocolTasks.cs#L66) は `CurrentProtocolVersion=2025-11-25`、サポート配列はその1件です。[RetiredProtocolRegression.cs](https://github.com/LIghtJUNction/OniMods/blob/14c08591cbd0bf66cd0f53b37bfb498bdef4abf6/tests/OniMcp.Server.Tests/RetiredProtocolRegression.cs) は2026系の意図的廃止を明記し、2025-06-18等の拒否も検証対象としています。`ModernProtocol.Tests.csproj` もこの拒否テストを起動します。テストは読解のみで、こちらでは.NETテストを実行していません。

したがって文書にある「新しいクライアントは2026系から試す」をそのまま実装しません。実際の配布DLLが固定ソースと一致するかも未確認です。採用時は実行時応答を確認して差分を保存します。この文書不一致はローカル記録のみで、Issue投稿や外部への連絡はしていません。

## 取得可能な情報

以下はリソース登録と文書から確認した面です。稼働中の値、完全性、全DLC・全ゲーム版での動作は未検証です。

| 情報 | 代表URI | 主な用途と注意 |
| --- | --- | --- |
| 殖民地 | oni://colony/status / diagnostics / alerts / summary | 周期、人数、速度、停止状態、警報、診断 |
| 複製人間 | oni://dupes / oni://dupes/status-check | 位置、差事、需要、到達困難の兆候 |
| 資源 | oni://resources/inventory / food | 在庫、食料・鮮度。発見済み等の範囲に注意 |
| 地形 | oni://world/text-map | テキスト地図、可視範囲・世界IDの区別 |
| 電力 | oni://power/summary / ports | 電池、電網、端子、接続状態 |
| 設備 | oni://buildings/defs / materials / configurables | 定義検索、材料候補、配置・設定 |
| 生産・環境 | oni://production/recipes / fabricators、oni://rooms/list、oni://thermal/overheat-risk | レシピ、キュー、部屋、過熱リスク |
| メタ情報 | oni://tools/manifest / guide | ツール・能力・操作案内 |

根拠：[OniResourceRegistry.cs](https://github.com/LIghtJUNction/OniMods/blob/14c08591cbd0bf66cd0f53b37bfb498bdef4abf6/mods/OniMcp/Tools/Core/OniResourceRegistry.cs)、[BuildingAndSpaceRoutes](https://github.com/LIghtJUNction/OniMods/blob/14c08591cbd0bf66cd0f53b37bfb498bdef4abf6/mods/OniMcp/Tools/Core/OniResourceRegistryBuildingAndSpaceRoutes.cs)、[ツール参考](https://github.com/LIghtJUNction/OniMods/blob/14c08591cbd0bf66cd0f53b37bfb498bdef4abf6/docs/mcp-tools-reference.md)。リソースは内部ハンドラへ読み取り引数をルーティングする実装です。`oni://` という文字列だけで安全とは判定せず、将来のアダプタでもURIとクエリを個別に監査します。

設備定義の実装：[BuildPlanningCatalog.cs](https://github.com/LIghtJUNction/OniMods/blob/14c08591cbd0bf66cd0f53b37bfb498bdef4abf6/mods/OniMcp/Tools/Impl/Build/BuildPlanningCatalog.cs#L45)。取得項目はprefabId、name、width/height、buildLocationRule、placement、categories、materialCategories、resolvedMaterialCategories、defaultMaterials、availableMaterials（上位20）、recommendedMaterial、requiresPower、powerWatts、unlocked、availableNow等です。

`powerWatts` は `EnergyConsumptionWhenActive` の丸め値であり、発電出力ではありません。`unlocked` は現在の研究状態であり、研究前提ツリーではありません。推奨材料・在庫・availableNowは観測時点と世界に依存するため、恒久設備仕様と分離します。この定義辞書だけでは建設資材の全質量、全入出力レート、温度制限、研究ID、DLC適用範囲などを埋められません。

## 公開操作API

[OniToolRegistry.Initialize](https://github.com/LIghtJUNction/OniMods/blob/14c08591cbd0bf66cd0f53b37bfb498bdef4abf6/mods/OniMcp/Tools/Core/OniToolRegistry.cs#L25) の登録は7件です。

| tools/call名 | 主な操作 | 分類 |
| --- | --- | --- |
| benchmark | ツール経路のベンチマーク | ゲーム状態についてread-only |
| world_editor | cd/ls/read/search、仮想ファイルedit、plan/connect | 読み取りから実行まで混在 |
| game_control | state、pause/resume/speed、save/load、新規開始、DLC/UI等 | 読み取り・変更・危険操作 |
| navigation_control | get_view、移動、ズーム、世界切替、overlay、screenshot | 観測・UI変更・ファイル生成 |
| building_control | planning、config、storage/filter、production、side_surface、rocket | 読み取り・建設・設定変更 |
| orders_control | dig/sweep/mop/deconstruct、priority、conduit切断 | 変更・破壊的操作 |
| server_control | catalog/manifest、診断、batch、program、管理 | 読み取りと実行が混在 |

`colony_control`、`dupes_control`、`read_control`、`search_control`、`coordinate_control` は内部ルーティング専用です。直接tools/call名として固定しません。各集約ツールが読み取り専用という意味でもありません。

## MCP / HTTP / 設定

- エンドポイントは既定 `http://localhost:8788/mcp/`。HTTP JSON-RPC 2.0 / Streamable HTTP、SSE経路があります。stdioサーバーではありません。
- 固定実装では2025-11-25でinitializeし、応答のMcp-Session-Idを後続に付与します。notifications/initializedも送ります。バージョンヘッダを明示し、セッション不明・期限切れ・不一致時は停止して再初期化する設計にします。
- tools/list、tools/call、resources/list、resources/templates/list、resources/read、Tasks関連の処理があります。JSON-RPCエラーとtoolのisError、resource内容内errorを別々に判定します。HTTP 200でも成功とは限りません。
- legacyのJSON応答をAcceptで許可する必要があります。JSON-RPC batch配列は拒否されます。server_controlのbatchとは別概念です。
- tools/callのarguments.taskは空でない文字列が必須です。ゲーム内マウス付近の説明表示に使われます。これは人間の承認そのものではありません。resources/readは別経路でtask不要です。
- 設定はOniMcpConfig.json。`Host=localhost`、`Port=8788`、`AuthEnabled=false`。認証を有効化した場合、BearerまたはX-Oni-Mcp-Tokenを検証します。非loopbackは認証必須のチェックがありますがHTTP自体は平文です。
- ツールcontentの既定形式はTOONで、プロトコルのJSONとは別です。将来のクライアントはMIMEと形式を確認し、文字列を無条件にjson.loadsしません。

根拠：[HTTP本体](https://github.com/LIghtJUNction/OniMods/blob/14c08591cbd0bf66cd0f53b37bfb498bdef4abf6/mods/OniMcp/Server/McpHttpServer.cs)、[PostTransport](https://github.com/LIghtJUNction/OniMods/blob/14c08591cbd0bf66cd0f53b37bfb498bdef4abf6/mods/OniMcp/Server/McpHttpServerPostTransport.cs)、[ProtocolTasks](https://github.com/LIghtJUNction/OniMods/blob/14c08591cbd0bf66cd0f53b37bfb498bdef4abf6/mods/OniMcp/Server/McpHttpServerProtocolTasks.cs)、[Validation](https://github.com/LIghtJUNction/OniMods/blob/14c08591cbd0bf66cd0f53b37bfb498bdef4abf6/mods/OniMcp/Server/McpHttpServerValidation.cs)、[ToolCallMiddleware](https://github.com/LIghtJUNction/OniMods/blob/14c08591cbd0bf66cd0f53b37bfb498bdef4abf6/mods/OniMcp/Tools/Core/ToolCallMiddleware.cs)、[Options](https://github.com/LIghtJUNction/OniMods/blob/14c08591cbd0bf66cd0f53b37bfb498bdef4abf6/mods/OniMcp/Config/OniMcpOptions.cs)。

## 確認操作と実装制限

資料上の基本手順はpause → read/plan → dry-run → 人間のconfirm → 再読して検証です。今回この手順を実ゲームに対して行ってはいません。

- 建設の `build_area` はdryRunでもconfirmでもない呼び出しを拒否します。ただし `confirm=true` は呼出側が送るboolであり、サーバーが独立した人間承認を証明する仕組みではありません。全操作共通の権限ゲートと見なせません。
- 仮想セーブはディレクトリで、latestが現在セーブの別名。editはSEARCH/REPLACE方式です。複数blockはallowPartialが必要で、トランザクションによる全体rollbackを保証しません。
- 通常の建設・注文はquery/target/areaId等を使い、raw座標は拒否。精密建設はmap/viewportのtoken編集、精密注文はtyped ops経由。navigation_controlの対応するカメラ操作には座標例外があります。
- build_areaは既定maxAnchors=100（最大500）、実書込みは既定32（最大128）に制限し、残りをremainingActionとして返します。建設予定が成功しても設備が完成したとは限りません。自動掘削・接続の副作用も確認対象です。
- previewToken registryは5分で失効する実装ですが、全操作がtokenを要求するわけではありません。dryRun結果だけで時間の経った操作を無条件実行しません。
- 電力のnetworkPending時はconnected/circuitIdがnullであり「未接続」と断定できません。温度のsamplePending時もゼロ温度と解釈できません。
- Unity APIの処理はMainThreadBridgeに移送。キュー、セッション、セーブ切替世代、非同期完了、タイムアウトを考慮する必要があります。再試行で変更を重複適用しない設計が必要です。
- MODロード時からサーバーが起動します。Optionsでは自動消毒の全体無効化とチュートリアル通知自動消去が既定trueです。「読み取りクライアントだけ」でもMOD導入自体が無影響とは言えません。

根拠：[BuildArea](https://github.com/LIghtJUNction/OniMods/blob/14c08591cbd0bf66cd0f53b37bfb498bdef4abf6/mods/OniMcp/Tools/Impl/Build/BuildPlanningActionBuildArea.cs)、[PreviewTokenRegistry](https://github.com/LIghtJUNction/OniMods/blob/14c08591cbd0bf66cd0f53b37bfb498bdef4abf6/mods/OniMcp/Tools/Shared/PreviewTokenRegistry.cs)、[WorldEditorBatchSafety](https://github.com/LIghtJUNction/OniMods/blob/14c08591cbd0bf66cd0f53b37bfb498bdef4abf6/mods/OniMcp/Tools/WorldEditor/WorldEditorBatchSafety.cs)、[ModInfo](https://github.com/LIghtJUNction/OniMods/blob/14c08591cbd0bf66cd0f53b37bfb498bdef4abf6/mods/OniMcp/ModInfo.cs)、[MainThreadBridge](https://github.com/LIghtJUNction/OniMods/blob/14c08591cbd0bf66cd0f53b37bfb498bdef4abf6/mods/OniMcp/Server/MainThreadBridge.cs)、[Options](https://github.com/LIghtJUNction/OniMods/blob/14c08591cbd0bf66cd0f53b37bfb498bdef4abf6/mods/OniMcp/Config/OniMcpOptions.cs)、[ツール参考](https://github.com/LIghtJUNction/OniMods/blob/14c08591cbd0bf66cd0f53b37bfb498bdef4abf6/docs/mcp-tools-reference.md)。

## 依存と互換性

| 層 | 固定ソースで確認した要件 | Phase 0の判断 |
| --- | --- | --- |
| OniMcp MOD | net48 / C# 7.3、ONI/Unity/Harmony/NewtonsoftのゲームDLL | 調査のみ。導入しない |
| NuGet | PLib 4.25.0、Toon.Format 1.0.0、Markdig 1.4.2、System.ValueTuple 4.6.1 | Pythonクライアントの直接依存ではない |
| ビルド | ILRepack.Lib.MSBuild.Task 2.0.48、ReferenceAssemblies 1.0.3、ゲームManagedPath | .NET SDK導入なし |
| 上流回帰テスト | net10.0のテストプロジェクト | こちらでは未実行 |
| onim CLI | Rust edition 2024、別の開発・導入ツール | Python側に不要。Rust導入なし |
| MODメタデータ | supportedContent ALL、minimumSupportedBuild 525812、APIVersion 2 | 宣言値であり全版動作保証ではない |

根拠：[OniMcp.csproj](https://github.com/LIghtJUNction/OniMods/blob/14c08591cbd0bf66cd0f53b37bfb498bdef4abf6/mods/OniMcp/OniMcp.csproj)、[Directory.Build.props.example](https://github.com/LIghtJUNction/OniMods/blob/14c08591cbd0bf66cd0f53b37bfb498bdef4abf6/Directory.Build.props.example)、[Cargo.toml](https://github.com/LIghtJUNction/OniMods/blob/14c08591cbd0bf66cd0f53b37bfb498bdef4abf6/Cargo.toml)、[ModernProtocol.Tests.csproj](https://github.com/LIghtJUNction/OniMods/blob/14c08591cbd0bf66cd0f53b37bfb498bdef4abf6/tests/OniMcp.ModernProtocol.Tests/OniMcp.ModernProtocol.Tests.csproj)。mod_info.yamlはソース直置きでなくビルド生成です。

ゲーム実ビルド、DLC組合せ、他MOD、Windowsでの実稼働、配布物とコミットの対応は未確認です。SDKとMODのランタイムは区別します。将来HTTPクライアントを作るだけならRustや.NETの新規導入は必須ではありません。

## ライセンス

現行ルートLICENSEは**Agent Upstream License 1.0-draft.1（LicenseRef-AUL-1.0-draft.1）**です。標準MITでもOSI承認済みでもありません。[LICENSING.md](https://github.com/LIghtJUNction/OniMods/blob/14c08591cbd0bf66cd0f53b37bfb498bdef4abf6/LICENSING.md) は過去のMIT許諾を遡及撤回しないこと、他者由来の素材は別条件であることを説明しています。[LICENSE.MIT](https://github.com/LIghtJUNction/OniMods/blob/14c08591cbd0bf66cd0f53b37bfb498bdef4abf6/LICENSE.MIT) が存在しても現行全体をMITと扱いません。

AULは利用・調査・複製・改変等を条件付きで認め、Forkで確認した問題の報告や保持した改良の提出、通知・出典の保持等を規定します。非公開Forkにも関わる条項があり、実際の採用時は全文と適用範囲の確認が必要です。単なる受領・無改変利用では貢献を要求しない条項もあります。ライセンスはアカウント権限や外部公開の承認を与えません。

本プロジェクトは独立に作成し、OniMcpのコード・文書本文を組み込み・改変していません。参照URL・メタデータと最小限の識別子を記録しています。Fork作成・上流改良の保持は行わず、この作業から上流への提出義務が生じたとは判断していません。文書不一致の指摘はローカル調査記録です。将来fork/移植を選ぶ際に、義務の発生と承認済み送信経路を再評価します。

[THIRD_PARTY_NOTICES](https://github.com/LIghtJUNction/OniMods/blob/14c08591cbd0bf66cd0f53b37bfb498bdef4abf6/mods/OniMcp/THIRD_PARTY_NOTICES.txt) はPLib・TOON等のMIT、MarkdigのBSD型条件などを別掲しています。ONI本体・Valve/Kleiの条件はOniModsライセンスで置き換わりません。
