export const publicQuestions = [
  {
    id: 'what-is-framefetch',
    question: '帧取 Framefetch 是什么？',
    answer:
      '帧取是 MIT 开源、可自托管的个人视频下载与分析工具。它支持检查公开、免费、非 DRM 的视频链接，导入有权处理的本地视频与剧本文档，并管理处理记录、AI 分析和报告导出。',
  },
  {
    id: 'ai-reports',
    question: 'AI 视频分析可以输出什么？',
    answer:
      '按所选分析能力生成场景、分镜、时间轴和关键帧证据等结构化结果，报告可导出为 Markdown 或 DOCX。AI 分析需要配置可用的模型服务与 AI Worker；模型结论需要结合原始素材复核。',
  },
  {
    id: 'local-import',
    question: '可以直接分析本地视频和剧本吗？',
    answer:
      '可以导入自己有权处理的本地视频与剧本文档。剧本支持 Markdown、Fountain、TXT、PDF 和 DOCX；导入后可在工作区阅读和发起分析，无需先提供第三方平台链接。',
  },
  {
    id: 'self-hosting',
    question: '开源免费是否意味着运行没有成本？',
    answer:
      '源代码以 MIT 许可证开放，可自行部署、使用和修改。服务器、对象存储、网络流量和外部 AI 模型可能产生费用；本项目不承诺免费托管或免费模型额度。',
  },
  {
    id: 'platform-support',
    question: '是否支持所有视频平台和所有链接？',
    answer:
      '不保证所有平台或链接可用。实际能力取决于部署实例的 Provider 配置、内容授权、访问条件和最近验证结果；应先检查链接再选择格式。公开可访问不等于获得使用授权。',
  },
  {
    id: 'mobile-app',
    question: '手机端是否能独立运行 AI 分析？',
    answer:
      'iOS 和 Android 客户端位于独立的 framefetch-app 仓库，使用 Flutter 构建并连接自托管 framefetch-server。媒体处理与 AI 推理由服务端执行，手机端不内置离线提取器或离线 AI 模型。',
  },
] as const;
