import React, { useState } from "react";
import { X, Send, Loader2, CheckCircle2, XCircle, Terminal, AlertTriangle } from "lucide-react";

interface BatchDeployModalProps {
  onClose: () => void;
  onRefresh: () => void;
}

export const BatchDeployModal: React.FC<BatchDeployModalProps> = ({ onClose, onRefresh }) => {
  const [isDeploying, setIsDeploying] = useState(false);
  const [results, setResults] = useState<any>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const handleDeploy = async () => {
    setIsDeploying(true);
    setErrorMsg(null);
    try {
      const response = await fetch("/api/hosts/batch-deploy", {
        method: "POST",
        headers: { "Content-Type": "application/json" }
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "批量部署请求失败");
      }
      setResults(data);
      onRefresh();
    } catch (err: any) {
      setErrorMsg(err.message || "网络错误，请稍后重试");
    } finally {
      setIsDeploying(false);
    }
  };

  return (
    <div 
      onClick={!isDeploying ? onClose : undefined}
      className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm"
    >
      <div 
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-3xl bg-white rounded-2xl overflow-hidden shadow-2xl border border-slate-200/50 flex flex-col max-h-[85vh]"
      >
        
        {/* 头部 */}
        <div className="flex items-start justify-between px-6 py-5 border-b border-slate-100 relative overflow-hidden shrink-0">
          <div className="absolute top-0 right-0 -mr-16 -mt-16 w-48 h-48 bg-indigo-500/10 rounded-full blur-3xl pointer-events-none" />
          <div className="flex items-start gap-4 relative z-10">
            <div className="p-3 rounded-xl bg-gradient-to-br from-indigo-50 to-blue-50 border border-indigo-100/50 text-indigo-600 shadow-sm">
              <Send className="w-6 h-6" />
            </div>
            <div className="pt-0.5">
              <h2 className="text-xl font-bold text-slate-800 tracking-tight">批量推送 Agent 部署</h2>
              <p className="text-sm text-slate-500 mt-1.5 leading-relaxed max-w-xl">
                一键向所有启用的主机推送最新的 Agent 源码及 Systemd 模板。请在修改了部署模板或更新系统后使用此功能。
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-xl text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors relative z-10"
            disabled={isDeploying}
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* 错误提示 */}
        {errorMsg && (
          <div className="px-6 py-3 bg-red-50 border-b border-red-100 text-sm text-red-600 shrink-0 font-medium flex items-center gap-2">
            <XCircle className="w-4 h-4" />
            {errorMsg}
          </div>
        )}

        {/* 内容区域 */}
        <div className="p-6 flex-1 bg-slate-50/50 overflow-y-auto min-h-0 flex flex-col gap-6">
          
          {!results && !isDeploying && (
            <div className="text-center py-10 space-y-4">
              <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-indigo-100 text-indigo-600 mb-2">
                <Terminal className="w-8 h-8" />
              </div>
              <h3 className="text-lg font-semibold text-slate-800">确认批量推送部署？</h3>
              <p className="text-slate-500 max-w-md mx-auto text-sm">
                此操作将并发连接到所有已启用的目标机器，下发最新的 Agent 安装包和配置文件，并重启相关服务。该过程可能需要几十秒。
              </p>
            </div>
          )}

          {isDeploying && (
            <div className="flex flex-col items-center justify-center py-16 text-slate-500 gap-4">
              <Loader2 className="w-10 h-10 animate-spin text-indigo-600" />
              <div className="space-y-1 text-center">
                <span className="font-semibold text-slate-700 block text-lg">正在全量并发部署中...</span>
                <span className="text-sm">通过 SSH 连接并执行更新，请耐心等待</span>
              </div>
            </div>
          )}

          {results && !isDeploying && (
            <div className="space-y-4">
              <div className={`p-4 rounded-xl border flex items-center gap-4 ${results.failed_hosts?.length > 0 ? 'bg-amber-50 border-amber-200' : 'bg-emerald-50 border-emerald-200'}`}>
                <div className={`p-2 rounded-full ${results.failed_hosts?.length > 0 ? 'bg-amber-100 text-amber-600' : 'bg-emerald-100 text-emerald-600'}`}>
                  {results.failed_hosts?.length > 0 ? <AlertTriangle className="w-6 h-6" /> : <CheckCircle2 className="w-6 h-6" />}
                </div>
                <div>
                  <h4 className="font-bold text-slate-800">{results.detail}</h4>
                  <p className="text-sm text-slate-600 mt-1">共处理 {results.total} 台主机配置。</p>
                </div>
              </div>

              {results.failed_hosts && results.failed_hosts.length > 0 && (
                <div className="mt-6">
                  <h5 className="font-semibold text-slate-700 mb-3 text-sm px-1">失败明细日志：</h5>
                  <div className="space-y-3">
                    {results.failed_hosts.map((host: any, idx: number) => (
                      <div key={idx} className="bg-white border border-red-100 rounded-lg p-4 shadow-sm">
                        <div className="flex items-center gap-2 mb-2">
                          <span className="font-mono text-xs font-bold bg-slate-100 px-2 py-0.5 rounded text-slate-700">{host.host_name}</span>
                          <span className="text-xs text-slate-500">{host.ip}</span>
                        </div>
                        <div className="text-xs font-mono text-red-600 bg-red-50/50 p-2 rounded whitespace-pre-wrap">
                          {host.reason || "未知原因"}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* 底部按钮 */}
        <div className="px-6 py-4 border-t border-slate-100 bg-white flex justify-end gap-3 shrink-0">
          <button
            onClick={onClose}
            disabled={isDeploying}
            className="px-5 py-2.5 rounded-xl text-sm font-semibold text-slate-600 hover:text-slate-800 hover:bg-slate-100 transition"
          >
            {results ? "关闭" : "取消"}
          </button>
          {!results && (
            <button
              onClick={handleDeploy}
              disabled={isDeploying}
              className="px-6 py-2.5 rounded-xl text-sm font-semibold text-white bg-indigo-600 hover:bg-indigo-500 shadow-md shadow-indigo-500/20 disabled:opacity-50 transition flex items-center gap-2"
            >
              {isDeploying ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
              开始推送
            </button>
          )}
        </div>

      </div>
    </div>
  );
};


