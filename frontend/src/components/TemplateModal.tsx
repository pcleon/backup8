import React, { useState, useEffect } from "react";
import { X, Save, FileCode2, Loader2 } from "lucide-react";

interface TemplateModalProps {
  onClose: () => void;
}

export const TemplateModal: React.FC<TemplateModalProps> = ({ onClose }) => {
  const [content, setContent] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // 挂载时拉取现有配置
  useEffect(() => {
    const fetchTemplate = async () => {
      try {
        const response = await fetch("/api/settings/template");
        if (response.ok) {
          const data = await response.json();
          setContent(data.content);
        } else {
          const err = await response.json();
          setErrorMsg(err.detail || "读取模板失败");
        }
      } catch (err: any) {
        setErrorMsg(err.message || "网络请求失败");
      } finally {
        setIsLoading(false);
      }
    };
    fetchTemplate();
  }, []);

  const handleSave = async () => {
    if (!content.trim()) {
      alert("模板内容不能为空！");
      return;
    }
    
    setIsSaving(true);
    setErrorMsg(null);
    try {
      const response = await fetch("/api/settings/template", {
        method: "PUT",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ content })
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "保存模板失败");
      }
      alert("✅ " + data.detail);
      onClose();
    } catch (err: any) {
      setErrorMsg(err.message || "网络请求失败");
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div 
      onClick={!isSaving ? onClose : undefined}
      className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm"
    >
      <div 
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-4xl bg-white rounded-2xl overflow-hidden shadow-2xl border border-slate-200/50 flex flex-col h-[85vh]"
      >
        
        {/* 头部区域 */}
        <div className="flex items-start justify-between px-6 py-5 border-b border-slate-100 bg-white shrink-0 relative overflow-hidden">
          {/* 背景光晕点缀 */}
          <div className="absolute top-0 right-0 -mr-16 -mt-16 w-48 h-48 bg-indigo-500/10 rounded-full blur-3xl pointer-events-none" />
          
          <div className="flex items-start gap-4 relative z-10">
            <div className="p-3 rounded-xl bg-gradient-to-br from-indigo-50 to-blue-50 border border-indigo-100/50 text-indigo-600 shadow-sm">
              <FileCode2 className="w-6 h-6" />
            </div>
            <div className="pt-0.5">
              <h2 className="text-xl font-bold text-slate-800 tracking-tight">Agent Systemd 部署模板</h2>
              <p className="text-sm text-slate-500 mt-1.5 leading-relaxed max-w-xl">
                此模板将在执行部署时作为 <code className="px-1.5 py-0.5 bg-slate-100 rounded text-slate-600 text-xs font-mono">backup-agent.service</code> 自动分发到目标主机。
                您可在此预设任意原生的 Systemd 高级属性。
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-xl text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors relative z-10"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* 错误提示 */}
        {errorMsg && (
          <div className="px-6 py-3 bg-red-50 border-b border-red-100 text-sm text-red-600 shrink-0">
            <strong>加载/保存出错：</strong>{errorMsg}
          </div>
        )}

        {/* 编辑区域 */}
        <div className="p-6 flex-1 bg-slate-50/50 overflow-hidden flex flex-col min-h-0 gap-4">
          
          {/* 纯静态架构温馨提示 */}
          <div className="shrink-0 p-4 rounded-xl bg-indigo-50/50 border border-indigo-200/60 flex items-start gap-3">
            <div className="shrink-0 p-1 bg-indigo-100 text-indigo-600 rounded-md mt-0.5">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <div className="text-sm text-indigo-800/90 leading-relaxed">
              <strong>完全静态架构模式：</strong> 本模板将<strong>原封不动</strong>地部署到所有目标主机。请确保在模板内正确填写 <code className="px-1.5 py-0.5 bg-indigo-100/80 rounded font-mono text-indigo-700">API_BASE</code> 与 <code className="px-1.5 py-0.5 bg-indigo-100/80 rounded font-mono text-indigo-700">TOKEN</code>。如果不显式配置 <code className="px-1.5 py-0.5 bg-indigo-100/80 rounded font-mono text-indigo-700">HOSTNAME</code>，Agent 将自动读取目标机的系统原生 Hostname（请务必确保与其在管理端注册的别名绝对一致）。
            </div>
          </div>

          {isLoading ? (
            <div className="flex-1 flex flex-col items-center justify-center text-slate-400 gap-3 bg-white rounded-xl border border-slate-200 shadow-sm">
              <Loader2 className="w-8 h-8 animate-spin text-indigo-500" />
              <span className="font-medium">正在读取模板文件...</span>
            </div>
          ) : (
            <div className="flex-1 relative rounded-xl shadow-inner border border-slate-800 bg-[#0f172a] overflow-hidden flex flex-col">
              <div className="flex items-center px-4 py-2 bg-slate-900/50 border-b border-slate-800/80">
                <div className="flex gap-1.5">
                  <div className="w-2.5 h-2.5 rounded-full bg-red-500/80" />
                  <div className="w-2.5 h-2.5 rounded-full bg-amber-500/80" />
                  <div className="w-2.5 h-2.5 rounded-full bg-emerald-500/80" />
                </div>
                <span className="ml-4 text-xs font-mono text-slate-500">backup-agent.service</span>
              </div>
              <textarea
                className="flex-1 w-full p-4 bg-transparent text-emerald-400 font-mono text-[13px] leading-relaxed focus:outline-none focus:ring-0 resize-none whitespace-pre selection:bg-indigo-500/30"
                value={content}
                onChange={(e) => setContent(e.target.value)}
                placeholder="请输入 Systemd 服务配置内容..."
                spellCheck={false}
              />
            </div>
          )}
        </div>

        {/* 底部按钮 */}
        <div className="px-6 py-4 border-t border-slate-100 bg-white flex justify-end gap-3 shrink-0">
          <button
            onClick={onClose}
            className="px-5 py-2.5 rounded-xl text-sm font-semibold text-slate-600 hover:text-slate-800 hover:bg-slate-100 transition"
          >
            取消
          </button>
          <button
            onClick={handleSave}
            disabled={isLoading || isSaving}
            className="px-5 py-2.5 rounded-xl text-sm font-semibold text-white bg-indigo-600 hover:bg-indigo-500 shadow-md shadow-indigo-500/20 disabled:opacity-50 disabled:cursor-not-allowed transition flex items-center gap-2"
          >
            {isSaving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
            保存模板
          </button>
        </div>
      </div>
    </div>
  );
};
