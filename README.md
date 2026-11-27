# A股权益策略投研驾驶舱 (Equity Strategy Cockpit)

面向主观多头基金经理与买方策略投研人员的**零服务器卖方策略研报聚合、边际转向监测、申万拥挤度对齐与段号溯源工作台**。

底层沿用经生产验证的 **Cloudflare Worker 准点调度 + GitHub Actions 流水线 + Google Drive 双通道归档（自动备份 + 手动免改名拖入） + OpenAI `gpt-6.2-sol` 两阶段段号锚定抽取（含图表页视觉直读与周度跨篇精炼） + GitHub Pages 纯静态发布** 架构。

---

## 一、 核心买方功能模块

1. **大势与边际转向雷达（Tab 1）**
   - **全部卖方 vs ★核心首席白名单切换**：一键剔除中小券商同质化看多噪音，实时重算大势四档温度计、DDM 共振家数与行业象限位置。
   - **跨周自身观点注入对比（Stitch #1）**：每次抽取自动注入该团队上一期入库摘要，精准识别“由守转攻 / 常年多头罕见降温 / 风格切换”，过滤维持原判的水词周报。
   - **DDM 三因子多空正面对撞台**：将宏观周期、资金流、政策博弈等异构框架统一拆解至「分子盈利宏观 / 分母流动性筹码 / 分母政策风偏」三维度聚类对撞。
   - **Stage 3 买方策略总监级周度交锋提炼**：自动提炼当周多空核心假设分歧眼与新兴野生主题。
2. **中观主线：「申万一级行业 × 卖方叙事」四象限拥挤度矩阵（Tab 2）**
   - 强制双轨映射标准 **31 个申万一级行业** 与卖方原生主题词，联动盘后自动更新的 **申万一级行业近 3 年成交额占比分位数**，直观区分「★ 左上低共识·新升温 Alpha 区」与「右上强共识·高拥挤主线区」。
3. **去水词「增量数据抓手」与未来 45 天催化验证日历（Tab 3）**
   - 含图页选择性多模态视觉直读（自动提取 4–6 张核心图表页），剥离常规涨跌流水账，仅保留极值分位与高频排产数据，支持原报告页码定位与 Google Drive 原件直跳。
4. **月度金股与标的共振池（Tab 4）**
   - 自动比对前期金股集合，区分「★ 本期首次新进黑马」与「🔥 多家扎堆共识股」。
5. **3 秒段号溯源抽屉 + 首席历史定调轨迹 × 沪深300叠加图 + 投委会周报素材篮**
   - Stage 0 `[P页-S段]` 全文零截断自然段回填验真；用直观的「近 12 周定调档位柱状图 × 沪深300走势折线」替代易受口径质疑的胜率百分比；支持收藏任意卡片一键复制内部周会汇报 Markdown 初稿。

---

## 二、 云端部署配置清单（与债券项目完全隔离）

进入仓库 `Settings → Secrets and variables → Actions` 配置以下凭据：

| 类型 | 名称 | 说明 |
| :--- | :--- | :--- |
| **Secret** | `OPENAI_API_KEY` | OpenAI Platform API 密钥 |
| **Secret** | `TINYFISH_API_KEY` | TinyFish API 密钥 |
| **Secret** | `TINYFISH_PROFILE_ID` | 已登录 `nxny.com` 的云浏览器 Profile ID |
| **Secret** | `GDRIVE_OAUTH_JSON` | Google Drive 用户 OAuth JSON（`{"client_id":"...","client_secret":"...","refresh_token":"..."}`） |
| **Variable** | `GDRIVE_FOLDER_ID` | **新建的股票策略专属** Google Drive 文件夹 ID（严禁与债券目录混用） |
| **Variable** | `OPENAI_MODEL` | 可选，默认 `gpt-6.2-sol` |
| **Variable** | `ENABLE_REPORT_PIPELINE` | 配妥上述凭据验收时填 `true` |
| **Variable** | `MAX_NEW_PDFS` | 单次增量新下载上限（默认 `18`，首次单篇验收可设 `1`） |
| **Variable** | `SCHEDULER` | 正式运行填 `cloudflare`（防止原生 `schedule` 重复触发） |
| **Variable** | `DEPLOY_GITHUB_PAGES` | 填 `true`（并在 `Settings → Pages → Source` 选 `GitHub Actions`） |

### Google Drive 手动免改名上传通道
对于 `nxny.com` 未收录的站外独门核心周报（如 **中信证券、国联民生证券、中金公司长篇深度**），直接将原生 PDF 拖入 `GDRIVE_FOLDER_ID` 文件夹即可自动识别入库，支持以下任意命名：
- `A股策略聚焦20261122—标题.pdf` / `A股策略聚焦 20261124 - 标题.pdf` / `亮马桥策略聚焦 20261124 - 标题.pdf`
- `中信证券-20261124-标题.pdf` / `国联民生证券-标题-261128.pdf` / `中金公司-12月金股组合-261128.pdf`

---

## 三、 Cloudflare Worker 准点调度部署

`cloudflare/wrangler.toml` 已预设独立 Worker 名称 `equity-cockpit-dispatch`，采用一周七天 `* * *` 覆盖周日发报高峰及国内调休交易日（北京时间 `08:23 / 12:23 / 17:23` 扫描研报，`16:37` 更新盘后申万拥挤度与沪深300基准），并使用 `redirect: "manual"` 严格校验 HTTP `204`：

```bash
# 在本地或部署终端进入 cloudflare 目录后执行：
npx wrangler secret put GITHUB_TOKEN   # 填入仅授本仓库 Actions: Read & Write 的 Fine-grained PAT
npx wrangler deploy
```

---

## 四、 验收与温和历史回填 SOP

1. **三项连通性自检**：在 GitHub Actions 依次手动运行 `Verify Google Drive backup`、`Verify TinyFish NXNY login`、`Verify OpenAI Stage 0-2 equity extraction`。
2. **首篇实盘验收**：设 `MAX_NEW_PDFS=1`、`ENABLE_REPORT_PIPELINE=true`，手动触发 `Update equity cockpit` (`trigger_source=manual`)，确认首篇真实研报入库后前端顶部黄色演示横幅自动消失（演示数据 100% 自动隔离）。
3. **历史盘点与温和回填**：运行 `Backfill equity report date range`，**先保持 `dry_run=true`** 查看 Step Summary 输出的逐家缺口盘点表，随后设 `dry_run=false`、`max_downloads=4` 分批温和补齐近 6–8 周历史以充实首席 12 周轨迹曲线。

---

## 五、 本地开发与测试

```bash
python3 -m pip install -r requirements.txt
python3 scripts/seed_generator.py
python3 scripts/build_snapshot.py
python3 -m unittest discover -s tests -v
python3 -m http.server 8000 --directory web --bind 127.0.0.1
```
