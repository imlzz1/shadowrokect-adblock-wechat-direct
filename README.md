# 小火箭规则：Top500 Banlist + 微信直连 + 小程序去广告（每天自动更新）

给 **Shadowrocket（小火箭）** 用的一套分流配置：

- 被墙的网站走代理；
- 普通网站、国内网站直连；
- 微信、微信支付、微信小程序基础服务 **国内直连**；
- 微信小程序 / 微信广告、广点通 GDT 广告域名 **拦截**；
- 基于每天更新的 Top500 Banlist + 去广告规则；
- 部署到 GitHub 后，**每天北京时间 08:30 自动重建**；
- 标准版 **不需要装证书、不需要 MITM、不含脚本**。

> 这不是机场/节点，也不提供翻墙服务。配置里没有服务器信息，`Proxy` 策略会自动使用你在小火箭里当前选中的节点。本项目没有自己的服务器；DNS 沿用上游配置里的阿里/腾讯 DoH。

> **懒人版流程：** 上传到 GitHub → Actions 跑一次 → 复制 `release` 分支的 raw 地址 → 小火箭“配置”里下载 → 全局路由选“配置” → 打开小火箭的配置自动更新。详细步骤见下面。

---

## 先看效果和边界

| 流量 | 策略 |
|---|---|
| 微信、微信支付、小程序基础服务 | `DIRECT` 直连 |
| 微信广告投放域、广点通/GDT 广告素材与上报 | `REJECT` 拦截 |
| Top500 黑名单里被墙的网站 | `Proxy`，走你当前节点 |
| 上游广告/追踪域名 | `REJECT` 拦截 |
| 其余未知流量 | `DIRECT` 直连 |

**能做到的：**

- 大部分微信小程序的开屏、Banner、插屏、激励视频广告请求会被拦截；
- 广告图片/视频不再下载，省流量，减少缓存；
- 微信聊天、支付、小程序打开等核心流量直连，不绕路；
- 每天自动跟进上游规则。

**做不到的（重要）：**

- 小程序自己用 JS 画的广告、已经缓存的广告，域名规则拦不掉；
- 视频贴片广告、部分 App 内置广告，无法保证 100% 去掉；
- 个别小程序可能因为广告 SDK 被拦而显示空白广告位，极少数会白屏；
- 广告 SDK 如果绕过域名、直接用 IP/HTTPDNS 连广告服务器，域名规则可能漏；
- 标准版不处理公众号文章里的广告（那需要 MITM 证书；本项目的重点是“小程序广告”）。

如果某个小程序出问题，见下面的 [出问题怎么回滚](#出问题怎么回滚)。

---

## 国外手机号注册的 WeChat，能直连吗？

**能，但要先定义“直连”是什么意思：**

- 规则是按域名/IP 匹配的，不看你绑定的是 +86、+1 还是 +44；
- 你的 WeChat 核心域名已经设为 `DIRECT`，未知流量最后也会落到 `FINAL,DIRECT`，所以正常情况下 **WeChat 不会走代理**；
- 但非 +86 账号经常会被微信分配到腾讯的海外接入点（常见是 `AS132203`，新加坡/香港等），这种情况下“直连”是**从国内直接连到海外机房**，物理延迟取决于你到那个机房的线路，规则没法把账号服务器改回国内。

针对国外手机号，我额外加了：

```text
DOMAIN-SUFFIX,weixin.qq.com.cn,DIRECT
DOMAIN-SUFFIX,wechatpay.cn,DIRECT
IP-ASN,45090,DIRECT,no-resolve      # 腾讯国内 IP
IP-ASN,132203,DIRECT,no-resolve     # 腾讯海外接入点（非 +86 账号常用）
```

这样即使 WeChat 走的是 IP 长连接（MMTLS），也不会被上游规则误代理/误拦。

**没有采用**网上常见的 `IP-ASN,132203,REJECT-DROP` 那种“强制国内”偏方：对非 +86 账号，它很可能让微信掉线或反复重连。
如果你人在国内、+1 账号直连新加坡实在太慢，那就不是规则能解决的，只能考虑让 WeChat 走香港/新加坡节点（这是另一种取舍，需要另做配置）。

---

## 项目文件

| 文件 | 用途 |
|---|---|
| `config/wechat-ad.list` | 微信小程序 / 微信广告拦截域名 |
| `config/wechat-direct.list` | 微信 / 微信支付 / 小程序基础服务直连域名 |
| `config/whitelist.list` | 防误杀白名单：上游广告列表如果误拦这些域名，构建时自动移除 |
| `scripts/build.py` | 下载上游、合并、去重、生成配置 |
| `scripts/rulekit.py` | 规则解析与优化 |
| `scripts/validate.py` | 静态校验 + 关键域名匹配模拟 |
| `.github/workflows/build.yml` | GitHub Actions：每天自动构建并发布 `release` 分支 |
| `NOTICE.md` | 上游署名与许可说明 |
| `dist/` | 生成结果（本地已生成；默认不提交到 `main`，由 Actions 发布到 `release`） |

> `dist/` 在 `.gitignore` 里，所以 GitHub 网页上看不到它是正常的；Actions 构建后会把内容发布到 `release` 分支。

生成出来的核心文件：

- `dist/shadowrocket-wechat.conf`：完整配置，导入小火箭用这个；
- `dist/wechat-ad.sgmodule`：只含微信广告拦截的模块，给“已有配置、只想加去广告”的人用；
- `dist/wechat-direct.list` / `dist/wechat-ad.list`：方便查看和二次使用；
- `dist/manifest.json` / `dist/build-report.txt`：本次构建的时间、上游版本、规则统计。

> `dist/wechat-ad.sgmodule` 是给“已经有自己的配置，只想加小程序去广告”的人用的。
> 模块规则会合并进现有规则列表，**必须确保它排在宽泛的 `qq.com` 直连规则之前**，否则不会生效。
> 如果你用的是本项目的完整配置，不需要再装这个模块。

---

## 相对上游做了什么优化

以最近一次构建为例（数字会随上游变化，以 `dist/build-report.txt` 为准）：

- 上游 `sr_top500_banlist_ad.conf` 有 83,072 条规则；
- 把 17 条微信广告拦截规则插到最前面；
- 把 33 条微信/支付/小程序直连规则（含 2 条腾讯 ASN）插到广告规则后面；
- 移除 3 条会覆盖微信广告/直连的上游冲突规则；
- 删除 68 条完全重复规则、1,242 条被更宽同策略规则覆盖的规则；
- 删掉过宽的 `DOMAIN-KEYWORD,gle`（容易误伤正常域名）；
- 不拦 `servicewechat.com`（小程序运行时）、`tenpay.com`（支付）等核心域，只拦广告域；
- 标准版去掉上游的 `[URL Rewrite]` / `[MITM]`（google.cn 跳转）和远程 AppleNews `RULE-SET`，保证“纯域名规则、不需要证书、不依赖远程规则集”；
- 最终 81,807 行，比上游少约 1,300 行，且微信/广告规则优先级明确。

---

## 5 分钟部署（推荐 GitHub Desktop）

你只需要一个 GitHub 账号，不需要写代码。

### 第 1 步：把项目放到 GitHub

#### 方法 A：GitHub Desktop（最推荐，不用敲命令）

1. 下载并安装 [GitHub Desktop](https://desktop.github.com/)，登录你的 GitHub 账号。
2. 打开 GitHub Desktop，菜单 **File → Add Local Repository**。
3. 选择本文件夹：`shadowrokect规则`。
4. 本项目文件夹已经初始化成 Git 仓库，正常情况下 GitHub Desktop 会直接显示右上角的 **Publish repository**，跳到第 5 步即可。
   如果它仍提示 “This directory does not appear to be a Git repository”，点下面的 **create a repository**。
   - Name 填 `shadowrocket-wechat`；
   - Local path 保持当前文件夹；
   - 不要勾选 “Initialize with README”；
   - 点 **Create Repository**。
5. 点右上角 **Publish repository**。
   - **取消勾选 “Keep this code private”**（必须是公开仓库，raw 链接才能免登录访问）；
   - 点 **Publish repository**。

等几十秒，浏览器打开 `https://github.com/你的用户名/shadowrocket-wechat` 能看到文件就成功了。

#### 方法 B：网页上传（不想装软件）

1. 在 GitHub 右上角 **+ → New repository**。
2. Repository name 填 `shadowrocket-wechat`（建议全英文，不要空格）；
3. 选择 **Public**；
4. 不要勾选 “Add a README file”；
5. 点 **Create repository**。
6. 在 Mac 的 Finder 里按 `Cmd + Shift + .` 显示隐藏文件。
7. 把 `README.md`、`LICENSE`、`NOTICE.md`、`.gitignore`、`config`、`scripts`、`tests`、`.github` 拖进网页的 “Upload files” 区域。
   - **不要上传** `dist` 和 `.cache`（生成文件，没必要）；
   - 如果 `.github` 拖不进去，看下一步。
8. 如果 `.github` 没上传成功：在仓库页 **Add file → Create new file**，文件名填：
   ```
   .github/workflows/build.yml
   ```
   然后把本机 `.github/workflows/build.yml` 的内容复制进去，点 **Commit changes**。

#### 方法 C：终端命令（会复制粘贴就行）

先在 GitHub 网页新建一个 **Public** 空仓库，然后在本文件夹打开“终端”，执行。

如果本文件夹已经有 `.git`（本项目已经初始化），跳过 `git init` 和 `git commit` 两行：

```bash
cd "/Users/wason/Desktop/shadowrokect规则"
git init
git config user.name "你的名字"
git config user.email "你的邮箱"
git add .
git commit -m "init"
git branch -M main
git remote add origin https://github.com/你的用户名/shadowrocket-wechat.git
git push -u origin main
```

如果 push 时要求密码，GitHub 现在不支持账号密码，需要用 Personal Access Token；不想折腾就用方法 A。

---

### 第 2 步：让 GitHub 生成第一版

1. 打开仓库页面，点顶部的 **Actions**。
2. 如果看到 “Workflows aren’t being run on this repository”，点 **I understand my workflows, go ahead and enable them**。
3. 左侧点 **Build Shadowrocket rules**。
4. 右侧点 **Run workflow** → 再点绿色的 **Run workflow**。
5. 等 1～2 分钟，出现绿色 ✓ 就成功了。
6. 回到仓库首页，点分支下拉框，应该能看到一个新的 **release** 分支。

> 如果失败，先看 [常见问题](#常见问题)。最常见的原因是仓库权限：
> **Settings → Actions → General → Workflow permissions** 选 **Read and write**，再重新 Run 一次。

---

### 第 3 步：拿到订阅地址

把下面地址里的 `你的用户名`、`shadowrocket-wechat` 换成你自己的：

**主地址（raw）：**

```text
https://raw.githubusercontent.com/你的用户名/shadowrocket-wechat/release/shadowrocket-wechat.conf
```

**加速地址（jsDelivr，国内通常更快）：**

```text
https://cdn.jsdelivr.net/gh/你的用户名/shadowrocket-wechat@release/shadowrocket-wechat.conf
```

例如你的用户名是 `yourname`，仓库名是 `shadowrocket-wechat`，地址就是：

```text
https://raw.githubusercontent.com/yourname/shadowrocket-wechat/release/shadowrocket-wechat.conf
```

注意：

- 这是 **“配置”地址，不是节点订阅地址**；不要加到小火箭首页的“订阅”里；
- 分支是 **release**，不是 `main`；
- 用户名和仓库名不要带空格；
- 两个地址内容一样，哪个能下载用哪个；
- 仓库必须是 **Public**，私有仓库的 raw 需要 token，小火箭里不方便用；
- 如果打开是 **404**：先确认 Actions 已经成功跑过、仓库里真的有 `release` 分支，并且地址里是 `release/` 而不是 `main/`；
- 不要直接编辑 `release` 分支，它是自动生成的，下次构建会被覆盖；要改规则请改 `main` 分支里的 `config/`。

如果上面两个地址都不稳定，可以再开一个 GitHub Pages 备用地址：

1. 仓库 **Settings → Pages**；
2. Source 选 **Deploy from a branch**；
3. Branch 选 **release**，目录选 **/(root)**，点 **Save**；
4. 等 1 分钟后，地址是：
   ```text
   https://你的用户名.github.io/shadowrocket-wechat/shadowrocket-wechat.conf
   ```

---

### 第 4 步：导入 Shadowrocket

1. 复制上面的地址。
2. 打开小火箭，底部点 **配置**。
3. 右上角 **+**，类型选 **URL**（有的版本叫“从 URL 下载”）。
4. 粘贴地址，点 **下载**。
5. 下载完成后，点这条配置 → **使用配置**。
6. 回到首页，把 **全局路由** 改成 **配置**。
   - 如果选成“代理”，所有流量（包括微信）都会走代理，规则就不会按预期分流；
7. 确认首页已经选中一个可用节点。

第一次导入 8 万多条规则，可能需要 10～30 秒，属于正常现象。

> 本机 `dist/shadowrocket-wechat.conf` 已经生成了一份，也可以先 AirDrop 到 iPhone，用“用小火箭打开”试用；但自动更新还是建议走 GitHub。

---

### 第 5 步：开启每天自动更新（两半都要做）

#### 5.1 GitHub 这一半：已经自动了

`.github/workflows/build.yml` 里已经设置：

- 每天北京时间 **08:30** 自动构建；
- 也可以随时在 **Actions → Build Shadowrocket rules → Run workflow** 手动运行；
- 修改 `config/` 或 `scripts/` 后，push 也会自动重建。

你不需要做任何操作。构建成功后，`release` 分支里的文件会被覆盖更新。

#### 5.2 手机这一半：让小火箭每天重新下载

小火箭需要打开自动更新，才会去 GitHub 拉新文件：

1. 小火箭 → 底部 **设置**；
2. 找到 **更新 → 配置**；
3. 打开 **自动后台更新**；
4. **更新间隔** 选 **1 天**；
5. 到 iOS 的 **设置 → 通用 → 后台 App 刷新**，确认小火箭是打开的。

之后小火箭会在后台按间隔检查更新。想立刻更新时：

> **配置 → 点一下这条配置 → 更新**

> 注意：自动更新会覆盖你直接在 App 里对这条远程配置做的修改。要自定义，请改 GitHub 仓库里的 `config/*.list`，不要改 App 里的本地副本。

---

## 怎么验证生效了

### 1. 看请求记录

打开小火箭的 **数据 / 请求记录**，可以按“全部 / 代理 / 直连 / 拒绝”筛选。然后：

- 打开微信，刷一下朋友圈、随便进一个小程序；
- 搜索 `wxs.qq.com`、`gdt.qq.com`，应该显示 **REJECT**；
- 搜索 `weixin.qq.com`、`servicewechat.com`，应该显示 **DIRECT**。

### 2. 看小程序广告

找一个带 Banner 或插屏广告的小程序/小游戏：

- 广告不再出现，或者广告位变成空白，说明广告请求被拦了；
- 如果广告还在，先确认配置已启用、全局路由是“配置”。

### 3. 看规则版本

`dist/build-report.txt` 或 `release` 分支里的 `manifest.json` 会记录：

- 本次构建时间；
- 上游构建时间；
- 规则数量；
- 跳过了多少冲突/白名单规则。

小火箭配置文件头部也会写生成时间和上游时间。

---

## 自定义规则（不用写代码）

在 GitHub 网页上直接改文件即可，改完提交后 Actions 会自动重建。

### 想让某个域名直连

编辑 `config/wechat-direct.list`，加一行：

```text
DOMAIN-SUFFIX,example.com,DIRECT
```

### 想拦某个广告域名

编辑 `config/wechat-ad.list`，加一行：

```text
DOMAIN-SUFFIX,ads.example.com,Reject
```

广告规则会排在直连规则前面，所以即使 `ads.example.com` 属于某个直连大域，也会被拦。

### 某个小程序被误杀，想放行

1. 在小火箭的请求记录里找到显示 **REJECT** 的域名；
2. 判断它来自哪里：
   - 如果域名在 `config/wechat-ad.list` 里（例如 `wxs.qq.com`、`gdt.qq.com`），**删除对应那一行**；
   - 如果不在 `wechat-ad.list` 里，说明是上游广告列表拦的，把域名加到 `config/whitelist.list`；
3. 提交，等 Actions 重建，或手动 Run workflow。

`whitelist.list` 只对“上游规则”生效：**上游要拦这个域名时，构建时把这条 Reject 删掉**。它不会强行把域名改成直连，也不会覆盖本项目 `wechat-ad.list` 里的广告规则。
要强行直连某个域名，请加到 `wechat-direct.list`；但如果它已经被 `wechat-ad.list` 的某个后缀覆盖，构建会按“广告优先”忽略直连规则。

### 不要做的事

- 不要加 `DOMAIN-SUFFIX,qq.com,DIRECT` 这种大范围直连：它会排在所有上游规则之前，把 `qq.com` 下本应拦截的广告子域放行；本项目自己的小程序广告规则虽然更靠前，但上游的其他广告会漏；
- 不要删除 `config/wechat-ad.list` 里的 `wxs.qq.com`，除非你确实要放行微信广告；
- 不要直接改 `dist/` 里的文件，因为下次构建会覆盖；要改 `config/`。

---

## 出问题怎么回滚

### 小程序打不开 / 白屏

1. 先在小火箭请求记录里找 `REJECT` 的域名；
2. 如果是 `wxs.qq.com`、`gdt.qq.com`、`gdtimg.com` 等广告域，说明这个小程序把广告 SDK 和业务逻辑绑在一起了；
3. 如果域名来自 `config/wechat-ad.list`，删除对应那一行；如果来自上游规则，才加到 `config/whitelist.list`（白名单不会覆盖本项目自己的广告规则）；
4. 提交后等重建；临时可以先在小火箭里停用配置。

### 微信支付 / 登录异常

理论上不会：`tenpay.com`、`wechatpay.com`、`weixin.qq.com` 等都已直连并加入白名单。
如果确实异常，先在请求记录里看是哪个域名被 `REJECT`，把对应规则删掉；或者暂时切回你原来的配置。

### 想完全恢复原样

在小火箭 **配置** 里切换回你原来的配置，或者删掉这条远程配置即可。本项目不改系统设置、不装证书、不改微信 App。

---

## 常见问题

### 1. 为什么 GitHub 每天更新，手机还要设置自动更新？

GitHub Actions 只负责“把新规则推到 release 分支”。手机上的小火箭必须重新下载这个文件才会用上新规则，所以两半都要开。

### 2. 需要装证书 / 开 HTTPS 解密吗？

**标准版不需要。** 配置里没有 `[MITM]`、没有 `[URL Rewrite]`、没有 `[Script]`，只做域名分流和域名拦截。
因此它不会解密你的 HTTPS 内容，也不会影响微信聊天加密。

### 3. 为什么配置有 3 MB、8 万多条规则？

这是上游 Top500 Banlist + 去广告规则的体量，属于正常范围。小火箭加载时会做索引，日常使用不会逐条匹配。第一次导入会慢一点。

### 4. 为什么还有广告？

域名拦截只能拦“发到广告域名的请求”。以下情况拦不到：

- 广告内容由小程序自己的业务接口返回；
- 广告已经缓存；
- 视频贴片、直播广告；
- 广告和小程序核心逻辑绑在同一个域名上（拦了会白屏）。

这套规则的目标是去掉大部分微信广告 SDK / 广点通广告，不是 100% 广告净化器。

### 5. 会不会影响微信语音、视频、支付？

微信核心域、支付域、小程序基础域都设为直连，并且有白名单保护。
如果遇到问题，按 [出问题怎么回滚](#出问题怎么回滚) 处理。

### 6. GitHub Actions 没跑 / 失败怎么办？

- 确认仓库是 **Public**；
- **Settings → Actions → General → Workflow permissions** 选 **Read and write**；
- 在 **Actions** 里点 **Run workflow** 手动跑；
- 如果是上游下载失败，等一会儿再跑。构建失败不会删除上一次成功的 `release`，手机仍能用旧版；
- Public 仓库的 Actions 免费，这套构建每天约 1 分钟，额度完全够用。

### 7. 可以私有仓库吗？

不建议。私有仓库的 `raw.githubusercontent.com` 链接需要 token，小火箭里不方便配置。用 Public 仓库，仓库里不要放任何密码/节点信息。

### 8. 这个配置包含节点吗？

不包含。它只有分流规则；`Proxy` 会使用你当前选中的节点。节点订阅过期/失效不是这套规则能解决的。

### 9. 能在 Loon / Quantumult X / Clash 用吗？

这是给小火箭的 `.conf` 格式。其他客户端规则语法不同，不能直接导入。

### 10. 为什么 `wxs.qq.com` 要拦？会不会误伤？

`wxs.qq.com` 是微信广告投放域（小程序广告位、公众号广告位）。社区模块长期用它做微信去广告，绝大多数情况下只影响广告。
如果某个小程序因此打不开，删掉 `config/wechat-ad.list` 里的 `DOMAIN-SUFFIX,wxs.qq.com,Reject` 即可。

### 11. GitHub 定时任务为什么晚了十几分钟？

GitHub 的 schedule 不保证精确，通常延迟几分钟到几十分钟。配置文件头部有构建时间，以那个为准。

### 12. 我用国外手机号注册的 WeChat，需要再改规则吗？

不用。规则不按手机号匹配，微信核心域名和腾讯 IP 已经直连；具体见 [国外手机号注册的 WeChat，能直连吗？](#国外手机号注册的-wechat能直连吗)。
注意：非 +86 账号可能被分配到新加坡/香港服务器，直连的物理延迟无法靠规则消除。

### 13. 仓库 60 天没动，定时任务会停吗？

GitHub 可能对长期无活动的仓库暂停 schedule。这个项目每天会向 `release` 分支提交，通常算活动；如果发现不更新了，打开 Actions 手动 Run 一次即可恢复。

---

## 规则来源与许可

许可是分开的，详细见 [NOTICE.md](NOTICE.md)：

- `scripts/`、`tests/`、`.github/` 里的代码：**MIT License**；
- 生成出来的 `shadowrocket-wechat.conf`：是在 Johnshall 规则基础上改编的衍生作品，按上游要求采用 **CC BY-SA 4.0**；配置头部和 `NOTICE.txt` 会保留署名。你再分发修改版时，请保留署名并以相同许可共享；
- `config/*.list` 里的微信域名清单：根据公开资料整理的域名事实，供本项目构建使用。

上游规则/数据来源：

- [Johnshall/Shadowrocket-ADBlock-Rules-Forever](https://github.com/Johnshall/Shadowrocket-ADBlock-Rules-Forever)：Top500 Banlist + 去广告基础规则；
- [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script)：WeChat 域名参考；
- [k6nfmm7dbr-commits/wechat-lite](https://github.com/k6nfmm7dbr-commits/wechat-lite)：微信广告域、GDT 域名与风险说明（MIT）；
- [TG-Twilight/AWAvenue-Ads-Rule](https://github.com/TG-Twilight/AWAvenue-Ads-Rule)：微信/GDT 广告域名交叉核对；
- [QingRex/LoonKissSurge](https://github.com/QingRex/LoonKissSurge)：微信广告接口与广告平台域名参考；
- [V2EX 讨论：微信 MMTLS 与海外 CDN IP](https://global.v2ex.co/t/1216412)：非 +86 账号的 AS132203 海外接入点参考。

这些上游项目各有自己的许可和维护者；本仓库只做规则合并、排序和自动化构建，不代表上游官方。规则可能误杀，请自己判断并保留回滚手段。

> 如果你把本项目 Fork 后公开使用，请不要删除配置头部的上游署名和 `NOTICE.txt`。

---

## 免责声明

本项目仅供学习、研究和提升日常上网体验。请遵守你所在地区的法律法规以及所使用网络服务商的条款。作者不对因使用本规则造成的任何直接或间接损失负责。
