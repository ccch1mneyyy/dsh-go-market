# 宠物与适配表市场（公开协议 1 / 批准协议 2）

C903 在市场固定基底 `0816c5cf585116d63f2b4bcd26c76c8a104c9058` 上整合 C700/C710，并对齐 dsh-go `c76c0db2d83573895f240307179e19802f674b1d`。这里规定纯数据宠物/适配表投稿、完整语义批准和 Worker 目录合同；App 当前运行时以 c76 的 `companion_adapt.dart`、`stage.js` 为准。既有插件协议保持独立。

## 1. 投稿与版本身份

一次 PR 只新增以下一组两个普通文件。提交者的 GitHub 登录名必须等于 `entry.json.owner`（小写）；不允许修改历史版本、工作流、政策、脚本、既有条目或混合插件投稿。

| 类型 | 目录 | 两个文件 |
| --- | --- | --- |
| 雪碧图宠物 | `pets/<id>/<version>/` | `entry.json`、`pack.zip` |
| Live2D 适配表 | `adapters/<moc-sha256>/<version>/` | `entry.json`、`adapter.json` |

`id` 是至多 40 个 ASCII 小写字母、数字和单个分隔连字符，匹配 `^[a-z0-9]+(?:-[a-z0-9]+)*$`，不能以 `user-` 开头。建议 `<owner>-<slug>`，避免导入 App 后归一化、截断产生身份碰撞。`moc` 是原始 `.moc3` 字节的 64 位小写 SHA-256；同一模型换目录或压缩方式仍复用同一份适配表，模型字节变化则使用新指纹。

版本与 `minApp` 使用最多 80 字符的精确 SemVer：`1.2.3` 或 `1.2.3-rc.1`；拒绝范围、标签、前导零和 `+build`。升级新增目录并严格高于历史最高版本；数值比较使用任意精度整数。普通投稿不能编辑已存在版本；已发布制品/预览不能同版改写。元数据更正必须走维护者审查并重新批准完整 release（§3）。新身份由首个被维护者批准的 owner 预留；已有身份的投稿者必须与可信 base 的 owner 相同。转让、重命名、多人共同维护、冲突裁决属于维护者政策变更，不能由投稿者绕过。

宠物 `entry.json` 示例（`pack.json` 的 id、author、license、source 必须与它一致）：

```json
{
  "schema": 1,
  "id": "someone-cat",
  "owner": "someone",
  "version": "1.0.0",
  "title": {"zh": "小猫", "en": "Little cat"},
  "author": "Some Artist",
  "license": "CC-BY-4.0",
  "source": "https://example.org/original-artwork",
  "minApp": "1.0.13",
  "rights": {"redistribute": true, "generalAudience": true}
}
```

适配表元数据用 `moc` 替代 `id`，不需要 `title`；其余字段相同。`source` 使用小写 `https://` 前缀，不含凭据、原始空白或反斜线；主机是合法 ASCII DNS 名（国际域名填 Punycode）、IPv4 或括号 IPv6，显式端口须可解析且在 0–65535。此保守语法是 Worker URL 接受范围的子集；构建器不做 DNS 或网络请求。author 最多 256、中文/英文标题各 120、source 最多 2048 个 Unicode 码点；整个原值计长，首尾空格不能用于绕过限制，拒绝空白文本、C0 控制字符与不配对代理项。owner 使用 GitHub 登录名形状，最多 39 字符。声明 `rights` 只是投稿者承诺，不构成授权证明。

首版市场许可清单为 CC0-1.0、CC-BY-4.0、CC-BY-SA-4.0、MIT、Apache-2.0、BSD-2-Clause、BSD-3-Clause。其他许可先由维护者评估并修改政策，不能填一个相近名称代替原许可。市场不收色情、血腥及无权再分发的商业角色。

## 2. 与 App 一致的校验及市场附加要求

权威规则文件是 [`schema/pet-pack.rules.json`](schema/pet-pack.rules.json)，规则版本 3，对照 dsh-go `c76c0db2d83573895f240307179e19802f674b1d` 的 `app/lib/pets/pet_pack.dart`、`pet_library.dart` 与 Android `PetPack.kt`。C901 与市场使用完全相同字节，SHA-256 为 `e14e27013d7a766293bdf385dcab966dea22afcb4f995b88d15ef07124922e04`；规则修改需要同步共享夹具和两端对照。`scripts/pet_pack.py:validate(pack, market=False)` 是 JSON 兼容入口，返回解析出的 animations/states，失败抛出 `Denied(code, path)`。

本地兼容 profile 保留 Dart 的既有行为：author/license/source 可缺，name 非字符串回落 id；scale 非数值默认 1；frameW/frameH/cols/帧 i/ms 按 Dart 半值远离零取整；缺数值 i/ms 的帧被忽略，但每个动画仍需至少一帧；非 list 或空的状态被忽略，idle 必须存在；pixelArt 与 loop 仅显式 false 才关闭。动画额外 `ms` 字段允许保留。source 与 license 在本地包仍可使用自由文本。这是底层 parser 的兼容行为，不等于当前 App 导入接受集。当前 App 另外检查严格整数/范围/几何门；市场元数据限制只用于市场发布。

| 项目 | App 既有限值 / 市场遵守的值 |
| --- | --- |
| pack.json 字节数 | 256 KiB |
| 单张引用 PNG 的编码字节数 | 8 MiB |
| 唯一引用 PNG 数量 | 64 |
| 引用 PNG 编码字节合计 | 48 MiB；不是 ZIP 大小上限 |
| 每张 PNG 宽或高 | 4096 像素 |
| 每张 PNG 按 RGBA 解码占用 | 16 MiB，即 width × height × 4 |
| sheet 文件名 | 扁平 PNG 名；至多 120 个 UTF-16 code units；拒绝路径、NUL、点开头 |
| 雪碧图单元 | 正尺寸、帧索引非负、cols 为正，引用单元完全落在图中 |

共同归档资源上限：导入 ZIP 64 MiB、声明展开量 64 MiB、ZIP 条目 256；规范化制品 50 MiB；静态 PNG 和 GIF 预览分别 4 MiB；适配 JSON 256 KiB；每个索引 2 MiB、当前条目 1000、撤回记录 4000，每只宠物 blockedVersions 最多 1000。KiB/MiB 均按 1024 计。

市场包还必须满足 Android/Flutter 共同可解释的几何：输出显式 scale 和 pixelArt、整数 canvas/cell/frame/timing 字段，并要求 frameW/H 等于 Android Float32 的 box.w/h × scale 向零取整。来源不满足关系时拒绝，不自动缩放原图。Dart 与 Android 的历史默认值、截断/取整差异没有被误称为完全相同；市场在取整规范化之后还调用 `app_import_compatible`：输出深度 ≤60，scale/frameW/frameH/cols 为 1..4096 整数，canvas 为 1..2^30 整数，每帧 i 为 0..2^30、ms 为 1..2^30 整数，且无异常帧被遗留。该门来自当前 App overlayPackProblem。原稿的小数可按既有规则规范化，但输出不能再以 parser 宽容性绕过安装限制。

严格 JSON 读取另外拒绝重复键、非有限数值（含转 binary64 溢出的超长整数）、深度超过 64、不合法 UTF-8 和不配对代理项。取整先转 binary64，再按半值远离零并钳到 native Dart int64，避免先加 0.5 的浮点临界偏差。归档拒绝加密、不支持的压缩方法、符号链接、路径穿越、绝对路径、NFC/忽略大小写后的别名冲突和多个 pack 候选。这些属于市场输入加固，不代表旧本地解析器此前已实施同样检查。

### 完整解码与规范化

PNG 规则 v2 在像素解码前显式核对四个 ASCII 字母构成的 chunk type、合法 IHDR/color/depth、PLTE/tRNS 顺序及唯一性、连续 IDAT、Adam7/普通扫描行精确长度、filter 0–4、zlib 真实 EOF/Adler32/无尾随，以及全部 chunk 的边界和 CRC。APNG 拒绝。iCCP/zTXt/iTXt 压缩 metadata 每块实际解压最多 1 MiB，全部文本/ICC 实际内容合计最多 64 MiB；未压缩 tEXt/iTXt 不另加单块 1 MiB 限制。校验后仅 IHDR/PLTE/tRNS/IDAT/IEND 交固定版本 Pillow 实际解码，避免依赖两端 decoder 对辅助 chunk 的不同宽容度。尺寸先验检查，每次只持有一张完整解码图；16 MiB 是 width × height × 4 的 RGBA 载荷上限，不是全进程峰值。App 本地导入保留已验证的原 PNG；市场按下面规则重新编码。

规范化 ZIP 只包含根目录 `pack.json` 与被引用的 PNG。pack.json 是第一个条目；其余按名称排序。PNG 重新编码以移除非像素 metadata，原画布和像素不缩放；ZIP 时间、权限、顺序固定。读取成员不使用 ZipExtFile 的 read/flush：原始 DEFLATE 每次输入和输出最多 64 KiB，实际展开量一旦超过声明/资源预算即拒绝，并核对真实 EOF、无尾随压缩数据、精确长度和 CRC；stored 成员也核对真实压缩跨度与长度。归档中未引用文件不解压且不会进入发布包，`reports/companions.json` 的 dropped 列出它们。

**再分发需要的完整许可证、版权声明、署名、NOTICE 和修改说明必须在投稿前转入 pack.json 的 `licenseText`、`notice` 或其他保留的纯数据字段。** PNG metadata 中的权利信息也适用。简短 author/license/source 不足以代替原许可要求；维护者必须核对 dropped 列表与原始许可，缺少所需完整声明时不得批准。程序保留这些 JSON 字段，有回归测试；程序不能自行判断许可义务是否已满足。适配表需保留必要声明在 `notes`，超过其 4000 码点或 256 KiB 限制时先扩展已审查的数据协议，不能删掉声明以通过检查。

静态透明 PNG 取首个 idle 动画的首帧；浅灰底短 GIF 按 idle 优先、随后其余动画取帧，最多 48 帧、4 秒、256 × 256。像素画放大采用整数倍 nearest，其他图用 Lanczos；预览变化不会缩放制品中的原雪碧图。预览只是代表性展示，维护者仍须查看所有引用图，避免遗漏其他动画内容。

## 3. 发布权限、approval v2 与治理

技术校验通过产生 `technical-ready`，公开目录只收录 `approved` 且未撤回的版本。维护者批准的是**最终可发布语义的记录**，包括规范化制品、全部预览和实际生效元数据；单独的 ZIP/adapter SHA 无法批准展示内容。

### 精确记录和 canonical 摘要

可信政策必须是 schema 2：

```json
{
  "schema": 2,
  "pets": {
    "someone-cat": {
      "owner": "someone",
      "approved": {
        "1.0.0": {"schema": 2, "releaseSha256": "<64位小写SHA256>"}
      }
    }
  },
  "adapters": {},
  "withdrawnPets": [],
  "withdrawnAdapters": []
}
```

每条 `release` 的形状：

```json
{
  "schema": 2,
  "kind": "pets",
  "owner": "someone",
  "rights": {"redistribute": true, "generalAudience": true},
  "entry": {
    "id": "someone-cat",
    "version": "1.0.0",
    "author": "Some Artist",
    "license": "CC-BY-4.0",
    "source": "https://example.org/original-artwork",
    "minApp": "1.0.13",
    "url": "/market/pets/someone-cat/1.0.0/<sha>.zip",
    "sha256": "<sha>",
    "size": 123,
    "title": {"zh": "小猫", "en": "Little cat"},
    "pixelArt": true,
    "preview": {
      "png": {"url": "/market/pets/someone-cat/1.0.0/<sha>.png", "sha256": "<sha>", "size": 123},
      "gif": {"url": "/market/pets/someone-cat/1.0.0/<sha>.gif", "sha256": "<sha>", "size": 123}
    },
    "risk": {"level": "low", "flags": ["data-only", "maintainer-reviewed"]}
  }
}
```

适配表记录用 `kind:"adapters"`、`entry.moc`；没有 title、pixelArt、preview、risk。entry 的资源 URL、SHA、size 均是**实际生成的**描述符。owner 与 rights 虽不展示在公开索引，仍被批准摘要绑定。

`releaseSha256 = SHA256(canonical(release))`。canonical 固定为 UTF-8、递归按键排序、无多余空格的 JSON，结尾**一个 LF**；Python 用 `ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False`。记录键为固定 ASCII 字段，数值字段为有限安全整数；字符串保留原始标量文字，不 trim、不做 NFC。拒绝不配对 surrogate，record 编码最多 **65,536 bytes**。Node gate 以同一规则重算；字节上限不是 JavaScript String.length 上限。单纯空白/转义/对象键排列变化，经解析后同语义的输入保持批准；组合/分解 Unicode 字符仍是不同的原始文字，摘要不同。

`generatedAt`、顶层 `withdrawn` 和宠物 `blockedVersions` 不属于作者 release 内容，它们来自可信政策的运行时治理状态，单独校验。构建器从 release.entry 拷贝公开行后再附 blockedVersions，不反向修改已批准记录。这里不允许投稿者修改这些政策字段。

### 审查工件与 CI 的闭环

1. 普通投稿只新增两份数据文件。带权限的工作流只 checkout 已捕获的可信 base，沿 PR 固定 head 的 commit → tree → blob 读取普通文件；不执行 PR 提供的脚本。
2. 构建器生成短期 review：`release.json`、`approval.json`、规范化 pack.zip 或 adapter.json，以及宠物的 preview.png/preview.gif。审核报告 schema 2 的对应行包含同一 release、approval、身份、版本、制品 SHA 和状态。
3. 维护者核查来源、许可、全部图像/动画和声明，核对**完整 release 记录与审核工件**；在独立受审维护变更中，把 approval 对象写入可信 policy。技术结果不能证明版权、角色授权或内容适宜。
4. 投稿更新到新的 base 后重跑。任意有效元数据、owner/rights、制品或预览变更都会失去旧批准资格：符合其他校验但 release 摘要不同的重建报 `approved-release-mismatch`；owner 冲突或 rights 不再为 true 等情况会在更早的输入门拒绝。它们均没有 approved/自动合并资格。旧 schema 1 policy 和旧单 SHA 字符串会直接拒绝，不能静默升级。
5. 实际 CI gate 调用 `readCompanionReview` 检查工件普通文件、大小和真实 SHA，然后 `companionApproved` 重算 release 摘要，交叉核对 trusted policy、报告和同一 review；报告里一个 approved 字样不足以放行。身份/owner/版本与撤回也必须一致。
6. CLI 构建开始清理上次生成的 review；失败写 `passed:false` 报告，不保留旧 PASS。entry 步骤成功后，即使构建失败，Actions 也上传本次已有的报告/review 便于新一轮审查；失败不会运行成功的自动合并 gate。
7. 自动合并仍受严格最新 base、已核 head 与所有 required checks 约束。维护者的 policy 变更不走普通两文件投稿自动合并通道。

同版本的 author/license/source/minApp/title 等更正，需维护者审查并重新批准完整 release。若规范化制品及预览 url/sha/size 未变，Worker 可更新元数据而保持原资源 binding；普通投稿仍不能编辑已存在版本。任何制品/预览字节或其身份改变则需新版本，不能因重新批准而覆写已发布资源。每个新版本也需单独批准。

### 从单摘要 policy 迁移

迁移不是把旧 SHA 放入 `releaseSha256`，也不是仅把 schema 改成 2。维护者应保留 owner 和撤回记录，把待复核 approval 暂设为空，在固定构建环境重新生成完整 review，逐条核对真实 metadata/owner/rights、制品与预览，审核后填入**新记录的** approval。旧发布版本必须与已发布资源三元组一致；依赖/编码升级改变资源时要发新版本。政策迁移与 Worker 历史状态迁移是两个独立必做步骤。
### 举报、下架与冲突

使用仓库“宠物 / 适配表举报”模板，提供 id/moc、精确版本、制品 SHA、问题类别及可公开的证据链接。涉及隐私或权利文件的材料请通过维护者另行公布的私密渠道提交；未配置私密渠道时不要把个人证件发到公开 Issue。CI 不会自动发消息或裁定投诉。

维护者确认紧急风险后把 `{id, version, reason}` 加入 withdrawnPets（适配表改为 moc/withdrawnAdapters）；原因最多 1000 码点。撤回记录永久保留，不能通过新版本、改名或重建移除。Worker 拒绝丢失旧撤回记录的新索引，目录时间不得回退；同一时间戳只接受完全相同的目录字节。旧版本不重新上架；修复后提交更高版本。要整只下架，需将其所有已批准版本加入撤回，避免构建器选择仍未撤回的旧版。

合并撤回后手动触发发布并确认 Worker 同步成功。源站下一次构建不再输出已撤回版本的制品；Worker 先核当前索引，再允许下载。已撤回宠物版本返回 410，旧 adapter 文件 URL 的 404/410 边界见 §4。已发行静态对象、浏览器缓存和公共 CDN 不能承诺即时消失；内容投诉/紧急删除还需维护者按索引中的确切 URL 删除 R2 对象，执行 Cloudflare cache purge，核查 Pages、go 和 dl 三个入口，再记录完成时间。不要删除撤回账本或永久资源 bindings。不同 owner 同时抢同一身份时，严格更新 base 后再次检查，维护者明确归属后只批准一方；GitHub 账户改名/转让需一并更新 owner 记录。

## 4. App / Worker 接口合同

公开目录 schema 仍为 1，机器定义为 `schema/pets-index.schema.json` 与 `schema/adapters-index.schema.json`。两个 `test/fixtures/*-index.example.json` 来自当前 Python 构建器生成的 1 pet + 3 adapters 合成资料，不表示真实模型或商业内容已经上架。

| 路由 | 响应 |
| --- | --- |
| `/market/pets.json` | 当前宠物目录 |
| `/market/adapters.json` | 当前适配表目录 |
| `/market/adapters/<moc>.json` | 当前指纹的目录条目；再下载其不可变文件 |
| `/market/pets/<id>/<version>/<sha>.zip` | 规范化宠物包 |
| 同一路径的 `<sha>.png` / `<sha>.gif` | 独立摘要预览 |
| `/market/adapters/<moc>/<sha>.json` | 不可变 market-v1 适配表 |

**目录权威来源是 Worker（部署目标 go 的上述路径）**。dl 默认仅用于不可变制品；如果维护者要继续提供 dl 的目录路径，其 origin 必须指向该 Worker。裸 R2 的旧 `market/pets.json` / `adapters.json` 不能用作目录，也不能成为失败回退源。代码不另写第二份非事务性目录。本合同不声明任何当前域名已配置。

`MARKET_SOURCE_URL` 为管理员设定的可信 Pages 构建根，例如市场仓库的 Pages 根；文件是根下的 pets.json、pets/...，不再嵌套一层 market/。索引 URL 固定根相对 `/market/...`，App 只解析到配置的可信目录/制品域；投稿 source 是展示与审核来源，构建器和 Worker 不抓取该地址。

### 字段、完整性与 App 安装

generatedAt 为有效 UTC 时间，使用秒或恰好 3 位毫秒；目录不得回退。每类目录至多 1000 个当前身份，版本为精确 SemVer。minApp 是安装最低版本门；每个资源有实际下载字节的 sha256/size，URL 中的身份/版本/摘要必须一致；当前项不能已被撤回。withdrawn 为追加保留的治理记录，blockedVersions 从可信宠物撤回记录推导。

JSON Schema 负责形状和范围；唯一身份、跨字段路径、资源散列、撤回连续性和历史绑定由运行时语义检查。客户端先限制响应大小，再验目录/最低版本/撤回，再下载并验证 size/SHA。宠物走实际 PetLibrary 导入入口，不能绕开 PNG/ZIP/当前 App 门。

market-v1 adapter 仍是 `{"adapter":1,"moc":"<sha>",...}` 的纯数据表，与 C810/App 本地的当前适配状态分开。它使用当前 c76 `companion_adapt.dart` / `stage.js` 已消费的 18 参数、10 情绪、12 动作、5 zone 词表。支持完整 target id 列表、pose、xFrom/xTo；拒绝旧 C700 提案的任意语义名和未实现 toggles。scale 非零、绝对值 ≤1000，offset/face/pose 为市场预算 ±1000；zoom 0.3–3、y ±1、x 范围 ±1.5，区间须有序。notes 至多 4000 码点，App 本地检查器会缩短显示文字。

index 只验证 envelope 的目录与历史结构，不逐条读取资源。adapter 指纹查找与文件 GET/HEAD/条件请求先有界读取最多 256 KiB 的完整对象，核声明 size、实际字节数、SHA、UTF-8 JSON 和现行 profile；失败为 503 artifact_unavailable，不因 ETag 命中而 304。文件响应直接使用已验证的 bytes，保留单 Range、HEAD、ETag/If-Modified-Since 和 416；HEAD 忽略 Range。因此旧 C700 对象不能仅凭已存 R2 或旧目录记录绕过现行语法。

市场没有用户的模型和当前 probe。App 仍须验证 moc、目标参数/表情/动作是否存在、范围、开关/水印含义及实际效果；不得把列表截成首个 target，也不得将无 probe 的表直接宣称可安装或已适配成功。本补丁没有新增页面或 stage 接线，也不复制 C720 的旧平行 runtime/schema/skill。

### 一个 envelope 提交目录和全部历史

Worker 的每类权威对象是 `market/_publication-v1/{pets|adapters}.json`：

```json
{
  "publication": 1,
  "kind": "adapters",
  "catalogText": "<原样公开 schema-1 目录>",
  "releases": [
    {"moc": "<moc>", "version": "1.0.0",
     "artifact": {"url": "/market/adapters/<moc>/<sha>.json", "sha256": "<sha>", "size": 123}}
  ]
}
```

宠物 binding 用 id，并增加 preview.png/gif 的相同三元组。每个 (kind,identity,version) **首次实际提交**的资源绑定随升级、撤回、当前条目消失、回退、进程重启永久保留；从 A→B→仍符合现行数据 profile 的原 A 允许，从 A→B→同版资源 A′ 拒绝。可重新批准的元数据变化不改变这条资源绑定。

读取和校验当前 envelope → 验证历史及源目录 → 暂存资源 → 单个条件 PUT 一次提交完整目录和 ledger。adapter 在缓存对象复用、沿用当前资源或完全相同目录的同步中，也重新读取有界完整 JSON，核真实 size/SHA 与现行 profile；只匹配 native HEAD checksum 不足以通过。相同目录重验后不另写状态。已有状态用 If-Match，首次用 If-None-Match: *；不会先写 ledger 再写另一个目录。条件失败和确定未提交的写失败不产生新 binding；可以留下未列出的校验资源。结果未知/确认丢失的 PUT 可能仍实际提交，但提交的必是完整 envelope，重试必须重读；同 key 的晚到条件写不能绕过获胜状态。pets/adapters 与插件分区没有跨分区事务。

内部 envelope 独立限制 **8 MiB UTF-8 / 10,000 lifetime bindings**，不同于公开索引 2 MiB。到限拒绝新提交，保留旧状态；不为压缩清理旧 bindings。维护者直接删/回滚权威对象不在正常发布协议的保证内。

### 故障和 HTTP 缓存

| 情况 | 目录响应 | 下载/指纹查询 |
| --- | --- | --- |
| 源站失败；R2 最后提交仍有效 | 200，stale=false，无 Warning，max-age=300 | 按提交目录继续授权 |
| R2 读/校验失败；warm Env 有已验证缓存 | 200，stale=true，Warning 110，max-age=60 | 503 |
| R2 读/校验失败；cold Env | 503 catalog_unavailable | 503 |
| state 与旧 bare key 均不存在，且初始化前置满足 | 404 not_published | 404 |
| state 缺失、旧 bare key 存在或检测失败 | warm Env 可用已验证缓存 200/304 stale 展示；cold Env 503；禁止补造历史 | 503 |
| envelope 有效，单个 adapter 缺失、读取失败、size/SHA 或当前 profile 不符 | index 仍可展示，stale=false | 该 adapter 查找/文件 503 artifact_unavailable |

**300 秒仅为 HTTP 缓存寿命，不是源站新鲜度保证。** stale 标志表示本次 R2 读/校验失败后的内存回退；不会自动表示 Cron/源站最后同步是否成功。读路径不抓源站；客户端或运维要监控 generatedAt/同步失败必须另做明确策略。这里不会声称缺失上游更新在 300 秒内必然可见。

索引/查询支持 ETag/304；制品支持 HEAD/Range。错误响应 no-store，503 带 Retry-After: 60。当前未列出资源是 404 not_found；已撤回宠物版本或无当前条目的撤回模型指纹为 410 withdrawn；列出的资源读取失败为 503 artifact_unavailable。旧 adapter 的不可变文件路径可能返回 404，不承诺从每个旧 URL 推导撤回原因。断点下载完成后必须再次校验整体 SHA。

### 迁移、旧入口与 writer 停止

旧 R1 bare catalog 没有完整历史，state 缺失时遇到它会触发内部 `history-migration-required`。cold 读请求为 503；warm Env 已有验证缓存时，目录可 200/304 stale 展示，下载/查找仍为 503。不能把当前版本拷进 ledger 就当历史完整。

1. **先停止所有旧宠物 writer，并确定每个在途/unknown PUT 的结果；即使旧 key 当前不存在也必须做。** 单次负 HEAD/GET 不会等待或取消旧 PUT，旧请求仍可能以后提交。此为部署前置；新旧状态是不同 key，单 key CAS 无法替代它。
2. 留存成功发布证据，证明每个历史 identity/version 的资源与预览三元组，保留全部撤回；由维护者审核构造并条件安装完整 envelope。禁止从当前条目猜全历史。当前 adapter 还须符合现行 profile；不合格旧版需撤回并发布合格新版本，不能删除它的历史 binding。
3. 历史证据不完整则停止原 namespace 发布；若要新建 authority/namespace，必须有明确产品/客户端迁移，不能删除旧 key 后在原身份下冒称首次发布。
4. 把公开目录切换到 Worker origin，清理旧裸目录/CDN 缓存；保留的 dl 目录别名也指向 Worker。不能双写旧公开目录。
5. 完成上述前置后才启用 PET_MARKET_ENABLED=1 并实际验收。既有插件市场的原路径和发布逻辑保持原状。

第 1 步是依据 [Cloudflare R2 一致性、条件写与负读说明](https://developers.cloudflare.com/r2/reference/consistency/) 推导的迁移要求；Workers 的条件 PUT 不满足条件返回 null，见 [R2 Workers API](https://developers.cloudflare.com/r2/api/workers/workers-api-reference/)。本地模拟不是实际 Cloudflare 部署验收。
## 5. 构建、核验与上线

使用 Python 3.12、`requirements-companions.txt` 固定的 Pillow 13.0.0，以及 package-lock.json 固定的 Node 依赖。本次本地执行环境为 Python 3.12.14、Pillow 13.0.0、Node 24.22.1。规范化同一输入在这套环境重复生成同样字节；跨 Pillow/zlib/Python 升级的逐字节稳定性不作承诺，升级时必须重跑已批准摘要的构建检查。

```sh
npm ci --ignore-scripts
python -m pip install -r requirements-companions.txt
npm test
npm run check:companions
npm run build
# 可选：验证集成端真实 Python 输出的两个索引
COMPANION_CONTRACT_DIST=/absolute/path/to/dist node --test test/contracts.test.mjs
```

`check:companions` 离线构建规范化资料与目录；`build` 另包含原插件的在线扫描。报告在 reports，公开产物在 dist。技术通过但未获批准的资料只出现在审核报告/短期 review 工件，不出现在公开索引。仓库初始政策为空，所以初始公开宠物和适配表目录为空，不伪造首批上架资料。

上线需要维护者：合入并部署配套 Worker，配置 R2、源站和可信下载域，启用 Pages 与定时发布；要求严格 main 分支保护及受信 Actions 的 market/catalog 状态；禁止普通投稿修改 companion-policy.json；配置内容投诉和私密联系渠道；用完整合成制品实测 go/dl 的摘要、Range、缓存失败、撤回和 source-prefix。GitHub Actions、Cloudflare/R2、公共域名和真实模型人工体验均需在对应权限环境中验收，本地离线通过不能替代这些检查。

## C710 同步与验收

当前规则 v3 与 C901 的 App `tool/pet-pack.rules.json` 字节相同；Python 固定 Unicode 15.0.0（CI Python 3.12），App 由同版本数据生成 NFC/full-casefold 表并保留 Unicode 许可。ZIP 名称中的 U+FEFF 保留为字符，JSON 起始 UTF-8 BOM 拒绝。新增 `test/fixtures/pet-png-v2.json` 是 44 个原创 1×1 PNG 边界案例，两端共用；资源限制测试采用很小的替代预算，无需耗尽内存。`test/test_png_v2.py` 可重建这些夹具。C903 已包含原 C700/C710 的实现，直接应用到本轮固定市场基底，不再先叠加旧补丁；原 C700/C710 ZIP 仍保留为历史来源。

C710 规范化行为的既有迁移边界：旧 C700 的 Pillow convert/save 可能继续携带原图 ICC profile；v2 只把渲染 chunks 送解码，确实移除 ICC。因此含 ICC 的规范化 PNG、ZIP 与 SHA-256 可能改变，必须重新构建、查看预览并按新摘要完成维护者批准。已发布不可变对象不得原址覆盖；摘要改变须发布新版本或按治理流程处理。

market 必填元数据的非空判断固定为 Python 3.12 str.isspace 的29个码点；App生成相同常量。U+001C属于空白，U+FEFF不属于；该判断保留作者原始整段字符串，不trim重写。共享JSON夹具现为24例，完整覆盖这两项差异。

## C903 对旧合同的替代范围

- C700 单制品 SHA 批准被完整 release approval v2 替代，旧 schema/string 不能继续批准。
- 裸 R2 目录优先/Worker 后备被 Worker 权威目录替代；保留 dl 目录须指向 Worker origin。
- 相邻当前版本比较被同一 CAS envelope 内的永久资源历史替代；资源绑定不等于元数据永不可更正。
- 源站失败就标 stale 的表述废止；当前 stale 只表示 R2 读/验证失败后的内存回退。300 秒是 HTTP TTL。
- 任意 adapter 语义/toggles 提案被当前 c76 已消费词表和字段替代；C810/App-local 的 probe/效果验收仍必需。
- 底层 parser 兼容不能代替当前 App 导入；规范化产物须额外通过 revision3 的 appImportCompatibility。

共享规则中“normalized digest”的概括以本文 §3 的完整 release canonical 摘要为准，绝非旧单个制品 SHA 的授权接口。
