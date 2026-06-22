// -*- coding: utf-8 -*-
import React, { useState, useEffect } from "react";
import { X, Server, Network, Shield, Calendar, Settings } from "lucide-react";

interface HostModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: (hostData: {
    host_name: string;
    ip: string;
    ssh_port: number;
    db_port: number;
    cron_expression: string;
    is_active: boolean;
  }) => Promise<void>;
  editHost?: {
    host_name?: string;
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
  const [hostName, setHostName] = useState("");
  const [ip, setIp] = useState("");
  const [sshPort, setSshPort] = useState(22);
  const [dbPort, setDbPort] = useState(3306);
  const [cronExpression, setCronExpression] = useState("0 2 * * *");
  const [isActive, setIsActive] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 当传入 editHost 变更时，初始化表单数据
  useEffect(() => {
    if (editHost) {
      setHostName(editHost.host_name || "");
      setIp(editHost.ip || "");
      setSshPort(editHost.ssh_port ?? 22);
      setDbPort(editHost.db_port ?? 3306);
      setCronExpression(editHost.cron_expression || "0 2 * * *");
      setIsActive(editHost.is_active ?? true);
    } else {
      setHostName("");
      setIp("");
      setSshPort(22);
      setDbPort(3306);
      setCronExpression("0 2 * * *");
      setIsActive(true);
    }
    setError(null);
  }, [editHost, isOpen]);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!hostName.trim() || !ip.trim()) {
      setError("主机别名和 IP 地址不能为空。");
      return;
    }

    setIsSubmitting(true);
    setError(null);

    const payload = {
      host_name: hostName,
      ip: ip,
      ssh_port: Number(sshPort),
      db_port: Number(dbPort),
      cron_expression: cronExpression,
      is_active: isActive,
    };

    try {
      await onSave(payload);
      onClose();
    } catch (err: any) {
      setError(err.message || "保存主机配置时发生错误。");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs">
      {/* 弹窗面板 (浅色毛玻璃) */}
      <div className="w-full max-w-lg glass-panel rounded-2xl overflow-hidden shadow-2xl border border-slate-200/50 animate-in fade-in zoom-in-95 duration-200">
        
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

        {/* 表单内容 */}
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && (
            <div className="p-3 text-sm text-red-600 bg-red-500/10 rounded-lg border border-red-500/20">
              {error}
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            {/* 主机名称 */}
            <div className="col-span-2">
              <label className="block text-xs font-semibold text-slate-500 uppercase mb-1">
                主机别名 *
              </label>
              <div className="relative">
                <input
                  type="text"
                  required
                  placeholder="如: db-primary-01"
                  value={hostName}
                  onChange={(e) => setHostName(e.target.value)}
                  className="w-full pl-9 pr-3 py-2 bg-white border border-slate-200 rounded-lg focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 text-slate-800 placeholder-slate-400 text-sm transition"
                />
                <Server className="absolute left-3 top-2.5 w-4 h-4 text-slate-400" />
              </div>
            </div>

            {/* IP 地址 */}
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
          <div className="flex justify-end gap-3 pt-4 border-t border-slate-100 mt-6">
            <button
              type="button"
              onClick={onClose}
              disabled={isSubmitting}
              className="px-4 py-2 text-sm text-slate-600 hover:text-slate-800 bg-slate-100 hover:bg-slate-200 rounded-lg border border-slate-200 transition"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="px-4 py-2 text-sm text-white bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg font-medium shadow-lg shadow-blue-500/10 transition flex items-center gap-1.5"
            >
              {isSubmitting ? "保存中..." : "确认保存"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
