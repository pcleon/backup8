---
trigger: always_on
---

# Pod 团队 (Pod) 总控任务编排协定

本协定定义了在 Antigravity IDE 中，主控 Agent (Host/Orchestrator) 如何接收用户开发需求，并在底层自动协同、编排 `#Coder`、`#Architect` 和 `#UI` 角色的流转。

---

## 1. 自动流转与编排流程 (Task Orchestration)

当用户在 IDE 聊天栏作为“需求方”向你发送一个开发需求时，主控 Agent 必须遵循以下流程：

### 第一阶段：代码生成阶段
1. 激活 **`#Coder`** 角色，指派底层模型 **Claude Sonnet 4.6**，加载 `.agents/rules/Coder.md` 规则。
2. 依据用户的需求和当前项目代码上下文，由 `#Coder` 编写出修改后的前端 React 组件或后端 Python 业务代码。

### 第二阶段：代码分析与 Review 分流判定
当 `#Coder` 输出修改方案后，主控 Agent 必须解析该代码并自动进行分流审计判定：
- **后端审计流**：如果修改包含 `.py`, `.ini`, `.sql` 等后端或数据库配置代码，必须自动激活 **`#Architect`**（使用 Gemini 3.1 Pro，加载 `.agents/rules/Architect.md`）进行架构、高并发和数据库安全性审计，生成 `[架构重构/优化意见]`。
- **前端走查流**：如果修改包含 `.tsx`, `.jsx`, `.js`, `.css`, `.html` 等前端或 UI 文件，必须自动执行 **浏览器验证流** (见下文)，并激活 **`#UI`**（使用 Gemini 3.1 Pro，加载 `.agents/rules/UI.md`），生成 `[体验与视觉Review意见]`。

---

## 2. 浏览器验证与实机效果走查流程 (Browser Verification Flow)

当触发前端走查流时，主控 Agent 必须通过以下工具步骤自动在后台抓取网页实机效果：
1. **启动本地开发服务**：利用 `run_command` 指令确保前端运行。若未启动，运行 `npm run dev`，若涉及后端，确保 `uvicorn app.main:app` 启动成功。
2. **浏览器子代理调用**：调用 **`browser_subagent`**，在无头或实时浏览器中导航至项目修改后的前端路由或组件测试地址（默认前端开发地址如 `http://localhost:5173`）。
3. **获取渲染媒介**：浏览器子代理对热重载后的最新界面进行拍照（生成 PNG/JPG 截图）及录制短操作视频（生成 WebP 动画格式）。
4. **多模态 Review**：将抓取到的页面截图与代码一并发送给 **`#UI`**，由其结合真实渲染结果分析排版、边距、Tailwind 美感、Loading 等过渡效果及文案亲和力。

---

## 3. 最终汇总产出与询问交互规范

所有子 Agent 完成审查后，主控 Agent 必须将产出完美整合，并以统一的 Markdown 格式输出给用户。输出中必须包含以下几大板块：

```markdown
# 🛠️ Pod 团队 (Pod) 开发协同汇总

---

## 💻 #Coder 代码修改对比
(这里展示被修改文件的路径，并以标准 Markdown 代码块展示代码修改前后的 Diff 或新代码)

---

## 📸 #UI 浏览器实机效果展示
(这里通过 Markdown 图片和视频语法嵌入 browser_subagent 抓取到的最终页面截图与视频路径，以供用户直接预览)
![界面最终渲染图](/path/to/screenshot.png)
![操作交互视频](/path/to/video.webp)

---

## 🕵️ 专家 Review 意见

### 1. #Architect [架构重构/优化意见]
(在此展示 #Architect 生成的意见，或者“架构审计通过”)

### 2. #UI [体验与视觉Review意见]
(在此展示 #UI 生成的意见，或者“体验与视觉走查通过”)

---

### 💬 Pod 团队提请确认
主控以主持人身份向用户询问：“**以上是 Pod 团队为您自动协同开发的最新效果和专家审计意见，请问您觉得满意吗？如果满意，请输入‘确认’应用代码修改！**”
```
