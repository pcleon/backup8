// -*- coding: utf-8 -*-
import React, { useState, useEffect } from "react";
import { X, Server, Network, Shield, Calendar, Settings, FileText, CheckCircle2, AlertTriangle, Loader2 } from "lucide-react";

interface HostModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: (payload: any, isBatch: boolean) => Promise<any>;
  editHost?: {
    id?: number;
    ip?: string;
    ssh_port?: number;
    db_port?: number;
    cron_expression?: string;
    is_active?: boolean;
  }; // 如果是编辑状态，传入要编辑的主机数据
}

export const HostModal: React.FC<HostModalProps> = ({
  isOpen,
  onClose,
  onSave,
  editHost,
}) => {
  // 单台/批量模式切换 ("single" | "batch")，有编辑数据时强制为 single
  const [mode, setMode] = useState<"single" | "batch">("single");
  
  // 单台表单属性
  const [ip, setIp] = useState("");
  
  // 批量表单属性
  const [ipsText, setIpsText] = useState("");
  
  // 公共模板属性
  const [sshPort, setSshPort] = useState(22);
  const [dbPort, setDbPort] = useState(3306);
  const [cronExpression, setCronExpression] = useState("0 2 * * *");
  const [isActive, setIsActive] = useState(true);
  
  // 运行状态与异常反馈
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  // 批量导入的结果汇总报告
  const [batchReport, setBatchReport] = useState<{
    total: number;
    success_count: number;
    failed_hosts: Array<{ ip: string; reason: string }>;
  } | null>(null);

  // 初始化或重置数据
  useEffect(() => {
    if (editHost) {
      setMode("single");
      setIp(editHost.ip || "");
      setSshPort(editHost.ssh_port ?? 22);
      setDbPort(editHost.db_port ?? 3306);
      setCronExpression(editHost.cron_expression || "0 2 * * *");
      setIsActive(editHost.is_active ?? true);
    } else {
      setMode("single");
      setIp("");
      setIpsText("");
      setSshPort(22);
      setDbPort(3306);
      setCronExpression("0 2 * * *");
      setIsActive(true);
    }
    setError(null);
    setBatchReport(null);
  }, [editHost, isOpen]);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBatchReport(null);

    const isBatchMode = mode === "batch" && !editHost;
    
    // 输入校验
    if (isBatchMode) {
      const splitIps = ipsText
        .split(/[\n,]+/)
        .map(x => x.trim())
        .filter(x => x.length > 0);
      
      if (splitIps.length === 0) {
        setError("IP 列表不能为空，请每行输入一个 IP 地址。");
        return;
      }
      
      setIsSubmitting(true);
      
      const payload = {
        ips: splitIps,
        ssh_port: Number(sshPort),
        db_port: Number(dbPort),
        cron_expression: cronExpression,
        is_active: isActive,
      };

      try {
        const result = await onSave(payload, true);
        
        // 判定批量结果
        if (result && result.failed_hosts && result.failed_hosts.length > 0) {
          // 有部分机器连接失败，不关闭弹框，渲染报告面板
          setBatchReport(result);
          
          // 智能友好设计：将 textarea 中的内容重置为仅包含那些连接失败的 IP，方便修改后重新提交
          const failedIps = result.failed_hosts.map((x: any) => x.ip).join("\n");
          setIpsText(failedIps);
          
          setError(`部分目标主机验证连接失败，已为您在输入框中保留了失败的 ${result.failed_hosts.length} 台 IP。`);
        } else {
          // 全部成功，关闭弹窗
          onClose();
        }
      } catch (err: any) {
        setError(err.message || "批量保存配置时发生错误。");
      } finally {
        setIsSubmitting(false);
      }
      
    } else {
      // 单台模式
      if (!ip.trim()) {
        setError("IP 地址不能为空。");
        return;
      }

      setIsSubmitting(true);
      
      const payload = {
        ip: ip.trim(),
        ssh_port: Number(sshPort),
        db_port: Number(dbPort),
        cron_expression: cronExpression,
        is_active: isActive,
      };

      try {
        await onSave(payload, false);
        onClose();
      } catch (err: any) {
        setError(err.message || "保存主机配置时发生错误。");
      } finally {
        setIsSubmitting(false);
      }
    }
  };

  return (
    <div 
      onClick={!isSubmitting ? onClose : undefined}
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs overflow-y-auto no-scrollbar"
    >
      {/* 弹窗面板 (浅色毛玻璃) */}
      <div 
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-xl glass-panel rounded-2xl overflow-hidden shadow-2xl border border-slate-200/50 animate-in fade-in zoom-in-95 duration-200 my-8"
      >
        
        {/* 头部 */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 bg-slate-50/50">
          <div className="flex items-center gap-2">
            <Server className="w-5 h-5 text-blue-600" />
            <h3 className="text-lg font-semibold text-slate-800">
              {editHost ? "编辑主机配置" : "添加目标主机"}
            </h3>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* 批量/单台 Tab 切换栏 (非编辑状态下展现) */}
        {!editHost && !batchReport && (
          <div className="flex border-b border-slate-100 bg-slate-50/30 p-1">
            <button
              type="button"
              onClick={() => { setMode("single"); setError(null); }}
              className={`flex-1 py-2 text-sm font-semibold rounded-lg transition ${
                mode === "single"
                  ? "bg-white text-blue-600 shadow-xs border border-slate-200/50"
                  : "text-slate-500 hover:text-slate-800"
              }`}
            >
              单台录入
            </button>
            <button
              type="button"
              onClick={() => { setMode("batch"); setError(null); }}
              className={`flex-1 py-2 text-sm font-semibold rounded-lg transition ${
                mode === "batch"
                  ? "bg-white text-blue-600 shadow-xs border border-slate-200/50"
                  : "text-slate-500 hover:text-slate-800"
              }`}
            >
              批量导入
            </button>
          </div>
        )}

        {/* 表单内容 */}
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          
          {error && (
            <div className={`p-3 text-sm rounded-lg border ${
              batchReport 
                ? "text-amber-700 bg-amber-500/10 border-amber-500/20" 
                : "text-red-600 bg-red-500/10 border-red-500/20"
            }`}>
              {error}
            </div>
          )}

          {/* 批量保存报告面板 */}
          {batchReport && (
            <div className="p-4 rounded-xl bg-slate-50 border border-slate-200 space-y-2">
              <div className="flex items-center justify-between text-xs font-semibold text-slate-700">
                <span className="flex items-center gap-1 text-emerald-600">
                  <CheckCircle2 className="w-4 h-4" />
                  导入成功: {batchReport.success_count} 台
                </span>
                <span className="flex items-center gap-1 text-red-500">
                  <AlertTriangle className="w-4 h-4" />
                  连接失败: {batchReport.failed_hosts.length} 台
                </span>
              </div>
              <div className="max-h-[140px] overflow-y-auto border border-slate-200/60 rounded bg-white p-2 divide-y divide-slate-100 text-xs no-scrollbar">
                {batchReport.failed_hosts.map((failed, idx) => (
                  <div key={idx} className="py-1.5 flex flex-col gap-0.5">
                    <span className="font-mono font-semibold text-slate-800">{failed.ip}</span>
                    <span className="text-red-500 text-[10px] leading-tight">{failed.reason}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            
            {/* IP地址输入部分 */}
            {mode === "single" ? (
              /* 单台录入 IP */
              <div className="col-span-2">
                <label className="block text-xs font-semibold text-slate-500 uppercase mb-1">
                  目标 IP 地址 *
                </label>
                <div className="relative">
                  <input
                    type="text"
                    required
                    placeholder="如: 192.168.1.100"
                    value={ip}
                    onChange={(e) => setIp(e.target.value)}
                    className="w-full pl-9 pr-3 py-2 bg-white border border-slate-200 rounded-lg focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 text-slate-800 placeholder-slate-400 text-sm transition"
                  />
                  <Network className="absolute left-3 top-2.5 w-4 h-4 text-slate-400" />
                </div>
              </div>
            ) : (
              /* 批量录入 IP Textarea */
              <div className="col-span-2">
                <label className="block text-xs font-semibold text-slate-500 uppercase mb-1">
                  批量目标 IP 列表 *
                </label>
                <div className="relative">
                  <textarea
                    required
                    rows={5}
                    placeholder="请输入 IP 地址列表，每行输入一个，例如:&#10;192.168.1.100&#10;192.168.1.101&#10;192.168.1.102"
                    value={ipsText}
                    onChange={(e) => setIpsText(e.target.value)}
                    className="w-full pl-9 pr-3 py-2 bg-white border border-slate-200 rounded-lg focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 text-slate-800 placeholder-slate-400 text-sm font-mono leading-normal transition no-scrollbar"
                  />
                  <FileText className="absolute left-3 top-3 w-4 h-4 text-slate-400" />
                </div>
                <p className="mt-1 text-[10px] text-slate-400">
                  支持换行或半角逗号分隔。批量模式下将自动使用下方配置作为公共模板应用到所有 IP 机器中。
                </p>
              </div>
            )}

            {/* SSH 端口 */}
            <div>
              <label className="block text-xs font-semibold text-slate-500 uppercase mb-1">
                SSH 端口 *
              </label>
              <div className="relative">
                <input
                  type="number"
                  required
                  value={sshPort}
                  onChange={(e) => setSshPort(Number(e.target.value))}
                  className="w-full pl-9 pr-3 py-2 bg-white border border-slate-200 rounded-lg focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 text-slate-800 text-sm transition"
                />
                <Shield className="absolute left-3 top-2.5 w-4 h-4 text-slate-400" />
              </div>
            </div>

            {/* MySQL 端口 */}
            <div>
              <label className="block text-xs font-semibold text-slate-500 uppercase mb-1">
                MySQL 端口 *
              </label>
              <div className="relative">
                <input
                  type="number"
                  required
                  value={dbPort}
                  onChange={(e) => setDbPort(Number(e.target.value))}
                  className="w-full pl-9 pr-3 py-2 bg-white border border-slate-200 rounded-lg focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 text-slate-800 text-sm transition"
                />
                <Settings className="absolute left-3 top-2.5 w-4 h-4 text-slate-400" />
              </div>
            </div>

            {/* Cron 表达式 */}
            <div className="col-span-2">
              <label className="block text-xs font-semibold text-slate-500 uppercase mb-1">
                备份 Cron 表达式 *
              </label>
              <div className="relative">
                <input
                  type="text"
                  required
                  value={cronExpression}
                  onChange={(e) => setCronExpression(e.target.value)}
                  className="w-full pl-9 pr-3 py-2 bg-white border border-slate-200 rounded-lg focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 text-slate-800 text-sm transition"
                />
                <Calendar className="absolute left-3 top-2.5 w-4 h-4 text-slate-400" />
              </div>
              <p className="mt-1 text-[10px] text-slate-400">
                标准 5 位 crontab 格式，如 &quot;0 2 * * *&quot; 表示每日凌晨 2:00 自动启动克隆物理备份。
              </p>
            </div>

            {/* 是否激活定时备份 */}
            <div className="col-span-2 flex items-center justify-between p-3 bg-slate-50 rounded-lg border border-slate-100">
              <div>
                <span className="text-sm font-medium text-slate-800">激活定时备份作业</span>
                <p className="text-[10px] text-slate-500 mt-0.5">关闭后将只支持手动触发，不会进入自动调度周期。</p>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={isActive}
                  onChange={(e) => setIsActive(e.target.checked)}
                  className="sr-only peer"
                />
                <div className="w-11 h-6 bg-slate-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
              </label>
            </div>
          </div>

          {/* 脚部操作按钮 */}
          <div className="flex justify-end gap-3 pt-4 border-t border-slate-100 mt-6 font-semibold">
            <button
              type="button"
              onClick={onClose}
              disabled={isSubmitting}
              className="px-4 py-2 text-sm text-slate-600 hover:text-slate-800 bg-slate-100 hover:bg-slate-200 rounded-lg border border-slate-200 transition"
            >
              {batchReport ? "关闭" : "取消"}
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="px-4 py-2 text-sm text-white bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg font-medium shadow-lg shadow-blue-500/10 transition flex items-center gap-1.5"
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  保存并预检中...
                </>
              ) : batchReport ? (
                "重新保存失败IP"
              ) : (
                "确认保存"
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
