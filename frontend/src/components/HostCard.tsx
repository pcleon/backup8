// -*- coding: utf-8 -*-
import React, { useState, useEffect, useCallback } from "react";
import { 
  Play, 
  History, 
  Edit3, 
  Trash2, 
  Server, 
  Calendar, 
  Clock, 
  AlertTriangle, 
  CheckCircle2, 
  XCircle, 
  Loader2, 
  HardDrive,
  X,
  Zap
} from "lucide-react";

interface BackupRecord {
  id: number;
  host_id: number;
  status: string;
  progress_status?: string;
  start_time: string;
  end_time?: string;
  backup_file?: string;
  file_size_bytes?: number;
  error_message?: string;
  created_at: string;
}

interface HostCardProps {
  host: {
    id: number;
    host_name: string;
    ip: string;
    ssh_port: number;
    db_port: number;
    cron_expression: string;
    is_active: boolean;
    last_heartbeat?: string;
    agent_version?: string;
    latest_record?: BackupRecord;
  };
  onEdit: (host: any) => void;
  onDelete: (id: number) => Promise<void>;
  onRefreshData: () => void;
  viewMode?: "grid" | "table";
}

export const HostCard: React.FC<HostCardProps> = ({
  host,
  onEdit,
  onDelete,
  onRefreshData,
  viewMode = "grid"
}) => {
  const [isBackingUp, setIsBackingUp] = useState(false);
  const [currentProgress, setCurrentProgress] = useState<string | undefined>(undefined);
  const [latestRecord, setLatestRecord] = useState<BackupRecord | undefined>(host.latest_record);
  const [isAborting, setIsAborting] = useState(false);
  const [isDeploying, setIsDeploying] = useState(false);
  
  // 弹窗状态管理
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [historyRecords, setHistoryRecords] = useState<BackupRecord[]>([]);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [activeErrorDetail, setActiveErrorDetail] = useState<string | null>(null);

  // 格式化文件大小
  const formatBytes = (bytes?: number): string => {
    if (bytes === undefined || bytes === null) return "-";
    if (bytes === 0) return "0 Bytes";
    const k = 1024;
    const sizes = ["Bytes", "KB", "MB", "GB", "TB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
  };

  // 格式化耗时
  const formatDuration = (start?: string, end?: string): string => {
    if (!start || !end) return "-";
    const diffMs = new Date(end).getTime() - new Date(start).getTime();
    const diffSecs = Math.floor(diffMs / 1000);
    if (diffSecs < 60) return `${diffSecs}秒`;
    const diffMins = Math.floor(diffSecs / 60);
    return `${diffMins}分${diffSecs % 60}秒`;
  };

  // 格式化日期时间
  const formatDateTime = (dateStr?: string): string => {
    if (!dateStr) return "-";
    const date = new Date(dateStr);
    return date.toLocaleString("zh-CN", { hour12: false });
  };

  // 轮询该主机的备份进度状态
  const pollBackupStatus = useCallback(async () => {
    try {
      const response = await fetch(`/api/hosts`);
      if (response.ok) {
        const hosts = await response.json();
        const self = hosts.find((h: any) => h.id === host.id);
        if (self && self.latest_record) {
          const rec = self.latest_record;
          setLatestRecord(rec);
          setCurrentProgress(rec.progress_status);
          
          if (rec.status !== "running") {
            // 备份结束，停止轮询并恢复状态
            setIsBackingUp(false);
            onRefreshData(); // 通知父组件刷新整体数据看板
            return true;
          }
        }
      }
    } catch (e) {
      console.error("轮询备份进度失败:", e);
    }
    return false;
  }, [host.id, onRefreshData]);

  // 处理轮询定时器
  useEffect(() => {
    setLatestRecord(host.latest_record);
    setCurrentProgress(host.latest_record?.progress_status);
    
    let intervalId: any;
    if (host.latest_record?.status === "running") {
      setIsBackingUp(true);
      intervalId = setInterval(async () => {
        const isDone = await pollBackupStatus();
        if (isDone) {
          clearInterval(intervalId);
        }
      }, 10000);
    } else {
      setIsBackingUp(false);
    }

    return () => {
      if (intervalId) clearInterval(intervalId);
    };
  }, [host.latest_record, pollBackupStatus]);

  // 手动触发立即备份
  const handleTriggerBackup = async () => {
    if (isBackingUp) return;
    
    setIsBackingUp(true);
    setCurrentProgress("INITIALIZING");
    
    try {
      const response = await fetch(`/api/hosts/${host.id}/backup`, {
        method: "POST"
      });
      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || "触发手动备份失败");
      }
      
      // 触发成功，启动本地轮询
      const intervalId = setInterval(async () => {
        const isDone = await pollBackupStatus();
        if (isDone) {
          clearInterval(intervalId);
        }
      }, 10000);
    } catch (err: any) {
      alert(err.message);
      setIsBackingUp(false);
      setCurrentProgress(undefined);
    }
  };

  // 手动中止备份任务
  const handleAbortBackup = async () => {
    if (isAborting) return;
    if (!latestRecord?.id) return;
    if (!confirm(`确定要强行中止当前主机的备份任务吗？这会将任务标记为失败。`)) return;
    
    setIsAborting(true);
    try {
      const response = await fetch(`/api/hosts/${host.id}/records/${latestRecord.id}/abort`, {
        method: "POST"
      });
      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || "强行中止备份任务失败");
      }
      
      // 中止成功，更新本地状态
      setIsBackingUp(false);
      setCurrentProgress(undefined);
      onRefreshData();
    } catch (err: any) {
      alert(err.message);
    } finally {
      setIsAborting(false);
    }
  };

  // 获取历史记录明细
  const handleViewHistory = async () => {
    setIsHistoryOpen(true);
    setIsLoadingHistory(true);
    try {
      const res = await fetch(`/api/hosts/${host.id}/records?limit=20`);
      if (res.ok) {
        const data = await res.json();
        setHistoryRecords(data);
      }
    } catch (e) {
      console.error("加载历史记录失败", e);
    } finally {
      setIsLoadingHistory(false);
    }
  };

  // 在历史记录弹窗里单独中止指定的任务
  const handleAbortHistoryRecord = async (recordId: number) => {
    if (!confirm(`确定要强行中止该备份任务吗？这会将任务标记为失败。`)) return;
    
    try {
      const response = await fetch(`/api/hosts/${host.id}/records/${recordId}/abort`, {
        method: "POST"
      });
      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || "中止失败");
      }
      
      // 更新历史记录里的状态，让界面立即反应
      setHistoryRecords(prev => 
        prev.map(r => r.id === recordId ? { ...r, status: 'failed', error_message: '备份任务已被管理员手动中止' } : r)
      );
      // 刷新外部卡片数据
      onRefreshData();
    } catch (err: any) {
      alert(err.message);
    }
  };

  // 处理删除确认
  const handleDelete = async () => {
    if (confirm(`确定要彻底删除目标主机配置【${host.host_name}】吗？这会同步注销该主机的自动备份定时任务，并清除所有相关的备份历史记录！`)) {
      await onDelete(host.id);
    }
  };

  // 部署 Agent
  const handleDeployAgent = async () => {
    if (isDeploying) return;
    if (!confirm(`将使用系统的全局 SSH 私钥向目标机 ${host.ip} 自动分发、安装并注册 Agent 服务。\n由于已实现免编译纯代码下发，部署将瞬间完成。\n\n是否确认部署？`)) return;

    setIsDeploying(true);
    try {
      const response = await fetch(`/api/hosts/${host.id}/deploy`, {
        method: "POST"
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "自动化部署发生错误");
      }
      alert("✅ " + data.detail);
      onRefreshData();
    } catch (err: any) {
      alert("❌ 部署失败: " + err.message);
    } finally {
      setIsDeploying(false);
    }
  };

  if (viewMode === "table") {
    return (
      <>
        <tr className="border-b border-slate-200/80 hover:bg-slate-50/50 transition-colors text-sm text-slate-700">
          {/* 第一列：IDC前缀 + 主机名 */}
          <td className="py-3 px-4 font-semibold">
            <div className="flex items-center gap-2">
              <span className="px-1.5 py-0.5 rounded-md text-[9px] font-bold uppercase tracking-wider bg-blue-50 border border-blue-200 text-blue-600">
                {host.host_name.split("-")[0] || "IDC"}
              </span>
              <div className="flex items-center gap-1.5">
                <span className="truncate max-w-[120px]" title={host.host_name}>{host.host_name}</span>
                {host.last_heartbeat ? (
                  (Date.now() - new Date(host.last_heartbeat).getTime() < 3 * 60 * 1000) ? (
                    <span className="w-2 h-2 rounded-full bg-emerald-500 shadow-[0_0_4px_rgba(16,185,129,0.5)] animate-pulse" title="Agent 在线"></span>
                  ) : (
                    <span className="w-2 h-2 rounded-full bg-red-500 shadow-[0_0_4px_rgba(239,68,68,0.5)]" title={`Agent 离线 (最后心跳: ${formatDateTime(host.last_heartbeat)})`}></span>
                  )
                ) : (
                  <span className="w-2 h-2 rounded-full bg-slate-300" title="Agent 状态未知"></span>
                )}
              </div>
            </div>
          </td>
          {/* 第二列：IP 与 DB Port */}
          <td className="py-3 px-4 font-mono text-xs text-slate-600">
            {host.ip}:{host.db_port}
          </td>
          {/* 第三列：自动计划表达式 */}
          <td className="py-3 px-4">
            <span className={`px-2 py-0.5 rounded-md text-xs ${
              host.is_active 
                ? "bg-indigo-50/80 border border-indigo-100 text-indigo-600 font-mono text-[11px]" 
                : "bg-slate-100 border border-slate-200 text-slate-400"
            }`}>
              {host.is_active ? host.cron_expression : "未启用"}
            </span>
          </td>
          {/* 第四列：最新备份结果（指示灯与进度） */}
          <td className="py-3 px-4">
            {isBackingUp ? (
              <div className="flex flex-col gap-1 w-32">
                <span className="flex items-center gap-1 text-xs text-blue-600 font-semibold animate-pulse-soft">
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  {currentProgress || "备份中"}
                </span>
                <div className="w-full bg-slate-200 rounded-full h-1 overflow-hidden">
                  <div 
                    className={`h-full bg-blue-600 rounded-full transition-all duration-500 ${
                      currentProgress?.includes("STARTING") ? "w-[10%]" : 
                      currentProgress?.includes("CLEANING") ? "w-[20%]" :
                      currentProgress?.includes("CLONE") ? "w-[50%]" :
                      currentProgress?.includes("COMPRESSING") ? "w-[75%]" :
                      currentProgress?.includes("RSYNCING") ? "w-[90%]" : "w-[95%]"
                    }`}
                  />
                </div>
              </div>
            ) : latestRecord?.status === "success" ? (
              <span className="flex items-center gap-1 text-xs text-emerald-600 font-semibold" title={latestRecord.backup_file}>
                <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
                成功 ({formatBytes(latestRecord.file_size_bytes)})
              </span>
            ) : latestRecord?.status === "failed" ? (
              <div className="flex items-center gap-2">
                <span className="flex items-center gap-1 text-xs text-red-600 font-semibold truncate max-w-[150px]" title={latestRecord.error_message}>
                  <XCircle className="w-3.5 h-3.5 shrink-0" />
                  失败
                </span>
                <button 
                  onClick={() => setActiveErrorDetail(latestRecord.error_message || "")} 
                  className="text-[10px] text-red-500 hover:text-red-700 underline font-medium shrink-0"
                >
                  日志
                </button>
              </div>
            ) : (
              <span className="text-xs text-slate-400">无备份</span>
            )}
          </td>
          {/* 第五列：上次备份启动时间 */}
          <td className="py-3 px-4 text-xs text-slate-500 font-mono">
            {latestRecord ? formatDateTime(latestRecord.start_time).split(" ")[0] : "-"}
          </td>
          {/* 第六列：备份耗时 */}
          <td className="py-3 px-4 text-xs text-slate-500">
            {latestRecord?.end_time ? formatDuration(latestRecord.start_time, latestRecord.end_time) : "-"}
          </td>
          {/* 第七列：操作栏 */}
          <td className="py-3 px-4 text-right">
            <div className="flex items-center justify-end gap-1.5">
              {isBackingUp ? (
                <button
                  onClick={handleAbortBackup}
                  disabled={isAborting}
                  className="px-2.5 py-1.5 rounded-lg text-xs font-semibold text-white bg-red-600 hover:bg-red-500 disabled:bg-red-600/50 disabled:cursor-not-allowed transition flex items-center gap-1"
                >
                  {isAborting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <XCircle className="w-3.5 h-3.5" />}
                  中止
                </button>
              ) : (
                <button
                  onClick={handleTriggerBackup}
                  className="px-2.5 py-1.5 rounded-lg text-xs font-semibold text-white bg-blue-600 hover:bg-blue-500 transition flex items-center gap-1"
                >
                  <Play className="w-3.5 h-3.5 fill-current" />
                  备份
                </button>
              )}
              <button
                onClick={handleViewHistory}
                className="px-2.5 py-1.5 rounded-lg text-xs text-slate-600 hover:text-slate-800 hover:bg-slate-100 border border-slate-200/85 transition flex items-center gap-0.5"
              >
                <History className="w-3 h-3 text-slate-500" />
                历史
              </button>
              <button
                onClick={() => onEdit(host)}
                disabled={isBackingUp}
                className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-700 transition disabled:opacity-30"
                title="编辑配置"
              >
                <Edit3 className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={handleDelete}
                disabled={isBackingUp}
                className="p-1.5 rounded-lg hover:bg-red-50/60 text-slate-400 hover:text-red-600 transition disabled:opacity-30"
                title="删除主机"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          </td>
        </tr>

        {/* 弹窗一：历史备份记录明细列表 */}
        {isHistoryOpen && (
          <div 
            onClick={() => setIsHistoryOpen(false)}
            className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs"
          >
            <div 
              onClick={(e) => e.stopPropagation()}
              className="w-full max-w-4xl glass-panel rounded-2xl overflow-hidden shadow-2xl border border-slate-200/50 flex flex-col max-h-[85vh]"
            >
              <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 bg-slate-50/50">
                <div className="flex items-center gap-2 text-slate-800 font-semibold">
                  <History className="w-5 h-5 text-blue-600" />
                  <span>主机【{host.host_name}】备份历史记录 (最近20次)</span>
                </div>
                <button
                  onClick={() => setIsHistoryOpen(false)}
                  className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              <div className="p-6 overflow-y-auto flex-1 bg-white">
                {isLoadingHistory ? (
                  <div className="flex items-center justify-center py-20 text-slate-500 gap-2">
                    <Loader2 className="w-5 h-5 animate-spin text-blue-600" />
                    <span>加载历史记录中...</span>
                  </div>
                ) : historyRecords.length === 0 ? (
                  <div className="text-center py-20 text-slate-400">
                    暂无任何备份记录。
                  </div>
                ) : (
                  <table className="w-full border-collapse text-left text-sm text-slate-700">
                    <thead>
                      <tr className="border-b border-slate-100 text-xs text-slate-500 uppercase bg-slate-50">
                        <th className="py-2.5 px-3">ID</th>
                        <th className="py-2.5 px-3">备份状态</th>
                        <th className="py-2.5 px-3">备份包文件名</th>
                        <th className="py-2.5 px-3">包大小</th>
                        <th className="py-2.5 px-3">开始时间</th>
                        <th className="py-2.5 px-3">备份耗时</th>
                        <th className="py-2.5 px-3 text-right">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {historyRecords.map((rec) => (
                        <tr key={rec.id} className="border-b border-slate-100 hover:bg-slate-50/50 transition">
                          <td className="py-3 px-3 font-mono text-xs text-slate-500">{rec.id}</td>
                          <td className="py-3 px-3">
                            {rec.status === "success" ? (
                              <span className="inline-flex items-center gap-1 text-emerald-600 text-xs font-semibold">
                                <CheckCircle2 className="w-3 h-3" />
                                成功
                              </span>
                            ) : rec.status === "failed" ? (
                              <span className="inline-flex items-center gap-1 text-red-600 text-xs font-semibold">
                                <XCircle className="w-3 h-3" />
                                失败
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1 text-blue-600 text-xs font-semibold animate-pulse">
                                <Loader2 className="w-3 h-3 animate-spin" />
                                运行中
                              </span>
                            )}
                          </td>
                          <td className="py-3 px-3 max-w-[220px] truncate font-mono text-xs text-slate-600" title={rec.backup_file}>
                            {rec.backup_file || "-"}
                          </td>
                          <td className="py-3 px-3 text-xs text-slate-600">{formatBytes(rec.file_size_bytes)}</td>
                          <td className="py-3 px-3 text-xs text-slate-600">{formatDateTime(rec.start_time)}</td>
                          <td className="py-3 px-3 text-xs text-slate-600">{formatDuration(rec.start_time, rec.end_time)}</td>
                          <td className="py-3 px-3 text-right">
                            {rec.error_message && (
                              <button
                                onClick={() => setActiveErrorDetail(rec.error_message || "")}
                                className="px-2 py-1 bg-red-500/10 hover:bg-red-500/20 text-red-600 border border-red-500/20 hover:border-red-500/30 text-xs rounded-md transition font-medium"
                              >
                                查看日志
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          </div>
        )}

        {/* 弹窗二：错误日志明细弹窗 */}
        {activeErrorDetail && (
          <div 
            onClick={() => setActiveErrorDetail(null)}
            className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs"
          >
            <div 
              onClick={(e) => e.stopPropagation()}
              className="w-full max-w-2xl glass-panel rounded-2xl overflow-hidden shadow-2xl border border-slate-200/50 flex flex-col max-h-[75vh]"
            >
              <div className="flex items-center justify-between px-6 py-4 border-b border-red-100 bg-red-50/50">
                <div className="flex items-center gap-2 text-red-600 font-semibold">
                  <AlertTriangle className="w-5 h-5" />
                  <span>备份故障详细错误堆栈</span>
                </div>
                <button
                  onClick={() => setActiveErrorDetail(null)}
                  className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
              <div className="p-6 bg-slate-50 overflow-auto flex-1 font-mono text-xs text-red-700 whitespace-pre-wrap leading-relaxed select-text select-all border-b border-slate-100">
                {activeErrorDetail}
              </div>
              <div className="px-6 py-3 border-t border-slate-100 text-right bg-slate-50/50">
                <button
                  onClick={() => setActiveErrorDetail(null)}
                  className="px-4 py-1.5 bg-slate-200 hover:bg-slate-300 text-xs rounded-lg text-slate-700 font-medium transition"
                >
                  关闭
                </button>
              </div>
            </div>
          </div>
        )}
      </>
    );
  }

  return (
    <>
      {/* 浅色毛玻璃卡片 */}
      <div className="glass-card rounded-xl p-5 flex flex-col justify-between min-h-[225px] h-fit gap-3">
        {/* 卡片头部 */}
        <div>
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-3">
              <div className="p-2.5 rounded-lg bg-blue-500/10 border border-blue-500/20 text-blue-600">
                <Server className="w-5 h-5" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h4 className="font-semibold text-slate-800 text-base leading-tight">
                    {host.host_name}
                  </h4>
                  {host.last_heartbeat ? (
                    (Date.now() - new Date(host.last_heartbeat).getTime() < 3 * 60 * 1000) ? (
                      <span className="flex items-center gap-1 text-[10px] font-bold text-emerald-600 bg-emerald-50 border border-emerald-200 px-1.5 py-0.5 rounded-md">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
                        ONLINE
                      </span>
                    ) : (
                      <span className="flex items-center gap-1 text-[10px] font-bold text-red-600 bg-red-50 border border-red-200 px-1.5 py-0.5 rounded-md" title={`最后心跳: ${formatDateTime(host.last_heartbeat)}`}>
                        <span className="w-1.5 h-1.5 rounded-full bg-red-500"></span>
                        OFFLINE
                      </span>
                    )
                  ) : (
                    <span className="flex items-center gap-1 text-[10px] font-bold text-slate-500 bg-slate-100 border border-slate-200 px-1.5 py-0.5 rounded-md">
                      <span className="w-1.5 h-1.5 rounded-full bg-slate-400"></span>
                      UNKNOWN
                    </span>
                  )}
                </div>
                <p className="text-xs text-slate-500 mt-1 flex items-center gap-1 font-mono">
                  {host.ip}:{host.db_port}
                  {host.agent_version && <span className="text-[10px] text-slate-400 bg-slate-100 px-1 rounded-sm ml-1">v{host.agent_version}</span>}
                </p>
              </div>
            </div>
            
            {/* 状态徽章 */}
            <div>
              {isBackingUp ? (
                <span className="flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-500/10 border border-blue-500/20 text-blue-600 animate-pulse-soft">
                  <Loader2 className="w-3 h-3 animate-spin" />
                  备份中
                </span>
              ) : latestRecord?.status === "success" ? (
                <span className="flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 border border-emerald-500/20 text-emerald-600">
                  <CheckCircle2 className="w-3 h-3" />
                  成功
                </span>
              ) : latestRecord?.status === "failed" ? (
                <span className="flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-red-500/10 border border-red-500/20 text-red-600">
                  <XCircle className="w-3 h-3" />
                  失败
                </span>
              ) : (
                <span className="flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-slate-100 border border-slate-200 text-slate-500">
                  无备份
                </span>
              )}
            </div>
          </div>

          {/* 定时配置 & 信息展示 - 改为横排紧凑流式展示 */}
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-slate-600 border-t border-slate-100/60 pt-2.5">
            <div className="flex items-center gap-1.5">
              <Calendar className="w-3.5 h-3.5 text-slate-400" />
              <span>
                计划: 
                <span className="ml-1 font-mono px-1.5 py-0.5 rounded bg-slate-50 border border-slate-200/60 text-slate-700">
                  {host.is_active ? host.cron_expression : "未启用"}
                </span>
              </span>
            </div>
            {latestRecord && (
              <>
                <div className="flex items-center gap-1.5">
                  <Clock className="w-3.5 h-3.5 text-slate-400" />
                  <span>上次: {formatDateTime(latestRecord.start_time)}</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <HardDrive className="w-3.5 h-3.5 text-slate-400" />
                  <span>
                    大小: {latestRecord.status === "success" ? formatBytes(latestRecord.file_size_bytes) : "-"}
                    {latestRecord.end_time && (
                      <span className="ml-1 text-slate-400 font-medium">
                        ({formatDuration(latestRecord.start_time, latestRecord.end_time)})
                      </span>
                    )}
                  </span>
                </div>
              </>
            )}
          </div>
        </div>

        {/* 下方进度或故障提示 */}
        <div className="my-2 min-h-[40px] flex items-center">
          {isBackingUp && currentProgress && (
            <div className="w-full space-y-1.5">
              <div className="flex justify-between text-[10px] text-blue-600 font-medium">
                <span className="flex items-center gap-1">
                  <Loader2 className="w-2.5 h-2.5 animate-spin" />
                  {currentProgress}
                </span>
              </div>
              <div className="w-full bg-slate-200 rounded-full h-1.5 overflow-hidden">
                <div 
                  className={`h-full bg-blue-600 rounded-full transition-all duration-500 ${
                    currentProgress.includes("STARTING") ? "w-[10%]" : 
                    currentProgress.includes("CLEANING") ? "w-[20%]" :
                    currentProgress.includes("CLONE") ? "w-[50%]" :
                    currentProgress.includes("COMPRESSING") ? "w-[75%]" :
                    currentProgress.includes("RSYNCING") ? "w-[90%]" : "w-[95%]"
                  }`}
                />
              </div>
            </div>
          )}
          {!isBackingUp && latestRecord?.status === "failed" && latestRecord.error_message && (
            <div className="flex gap-1.5 p-2 rounded bg-red-500/5 border border-red-500/10 text-[10px] text-red-500 w-full items-start overflow-hidden">
              <AlertTriangle className="w-3.5 h-3.5 text-red-500 shrink-0 mt-0.5" />
              <div className="truncate flex-1">
                <span className="font-semibold">错误:</span> {latestRecord.error_message}
              </div>
              <button 
                onClick={() => setActiveErrorDetail(latestRecord.error_message || "")} 
                className="underline hover:text-red-700 shrink-0 font-medium"
              >
                查看
              </button>
            </div>
          )}
        </div>

        {/* 卡片脚部操作栏 */}
        <div className="flex items-center justify-between border-t border-slate-100 pt-3">
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => onEdit(host)}
              disabled={isBackingUp}
              title="编辑配置"
              className="p-1.5 rounded text-slate-500 hover:text-slate-800 hover:bg-slate-100 transition disabled:opacity-30 disabled:pointer-events-none"
            >
              <Edit3 className="w-4 h-4" />
            </button>
            <button
              onClick={handleDelete}
              disabled={isBackingUp}
              title="删除主机"
              className="p-1.5 rounded text-slate-500 hover:text-red-600 hover:bg-red-500/5 transition disabled:opacity-30 disabled:pointer-events-none"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={handleDeployAgent}
              disabled={isDeploying || isBackingUp}
              className="px-2.5 py-1.5 rounded text-xs text-indigo-600 border border-indigo-200 hover:bg-indigo-50 transition flex items-center gap-1 disabled:opacity-50 disabled:cursor-not-allowed font-medium"
              title="自动化推送并注册 Agent"
            >
              {isDeploying ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Zap className="w-3.5 h-3.5 fill-current" />}
              部署 Agent
            </button>
            <button
              onClick={handleViewHistory}
              className="px-2.5 py-1.5 rounded text-xs text-slate-600 hover:text-slate-800 bg-white border border-slate-200 hover:border-slate-300 shadow-xs transition flex items-center gap-1"
            >
              <History className="w-3.5 h-3.5 text-slate-500" />
              历史
            </button>
            {isBackingUp ? (
              <button
                onClick={handleAbortBackup}
                disabled={isAborting}
                className="px-3 py-1.5 rounded text-xs text-white bg-red-600 hover:bg-red-500 disabled:bg-red-600/50 disabled:cursor-not-allowed font-medium shadow-md shadow-red-500/10 hover:shadow-red-500/20 transition flex items-center gap-1"
              >
                {isAborting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <XCircle className="w-3.5 h-3.5" />}
                中止备份
              </button>
            ) : (
              <button
                onClick={handleTriggerBackup}
                className="px-3 py-1.5 rounded text-xs text-white bg-blue-600 hover:bg-blue-500 font-medium shadow-md shadow-blue-500/10 hover:shadow-blue-500/20 transition flex items-center gap-1"
              >
                <Play className="w-3.5 h-3.5 fill-current" />
                立即备份
              </button>
            )}
          </div>
        </div>
      </div>

      {/* 弹窗一：历史备份记录明细列表 */}
      {isHistoryOpen && (
        <div 
          onClick={() => setIsHistoryOpen(false)}
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs"
        >
          <div 
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-4xl glass-panel rounded-2xl overflow-hidden shadow-2xl border border-slate-200/50 flex flex-col max-h-[85vh]"
          >
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 bg-slate-50/50">
              <div className="flex items-center gap-2 text-slate-800 font-semibold">
                <History className="w-5 h-5 text-blue-600" />
                <span>主机【{host.host_name}】备份历史记录 (最近20次)</span>
              </div>
              <button
                onClick={() => setIsHistoryOpen(false)}
                className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-6 overflow-y-auto flex-1 bg-white">
              {isLoadingHistory ? (
                <div className="flex items-center justify-center py-20 text-slate-500 gap-2">
                  <Loader2 className="w-5 h-5 animate-spin text-blue-600" />
                  <span>加载历史记录中...</span>
                </div>
              ) : historyRecords.length === 0 ? (
                <div className="text-center py-20 text-slate-400">
                  暂无任何备份记录。
                </div>
              ) : (
                <table className="w-full border-collapse text-left text-sm text-slate-700">
                  <thead>
                    <tr className="border-b border-slate-100 text-xs text-slate-500 uppercase bg-slate-50">
                      <th className="py-2.5 px-3">ID</th>
                      <th className="py-2.5 px-3">备份状态</th>
                      <th className="py-2.5 px-3">备份包文件名</th>
                      <th className="py-2.5 px-3">包大小</th>
                      <th className="py-2.5 px-3">开始时间</th>
                      <th className="py-2.5 px-3">备份耗时</th>
                      <th className="py-2.5 px-3 text-right">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {historyRecords.map((rec) => (
                      <tr key={rec.id} className="border-b border-slate-100 hover:bg-slate-50/50 transition">
                        <td className="py-3 px-3 font-mono text-xs text-slate-500">{rec.id}</td>
                        <td className="py-3 px-3">
                          {rec.status === "success" ? (
                            <span className="inline-flex items-center gap-1 text-emerald-600 text-xs font-semibold">
                              <CheckCircle2 className="w-3 h-3" />
                              成功
                            </span>
                          ) : rec.status === "failed" ? (
                            <span className="inline-flex items-center gap-1 text-red-600 text-xs font-semibold">
                              <XCircle className="w-3 h-3" />
                              失败
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 text-blue-600 text-xs font-semibold animate-pulse">
                              <Loader2 className="w-3 h-3 animate-spin" />
                              运行中
                            </span>
                          )}
                        </td>
                        <td className="py-3 px-3 max-w-[220px] truncate font-mono text-xs text-slate-600" title={rec.backup_file}>
                          {rec.backup_file || "-"}
                        </td>
                        <td className="py-3 px-3 text-xs text-slate-600">{formatBytes(rec.file_size_bytes)}</td>
                        <td className="py-3 px-3 text-xs text-slate-600">{formatDateTime(rec.start_time)}</td>
                        <td className="py-3 px-3 text-xs text-slate-600">{formatDuration(rec.start_time, rec.end_time)}</td>
                        <td className="py-3 px-3 text-right">
                          <div className="flex justify-end items-center gap-2">
                            {(rec.status === "pending" || rec.status === "running") && (
                              <button
                                onClick={() => handleAbortHistoryRecord(rec.id)}
                                className="px-2 py-1 bg-red-600 hover:bg-red-500 text-white border border-red-700 text-xs rounded-md transition font-medium shadow-sm flex items-center gap-1"
                              >
                                <XCircle className="w-3 h-3" />
                                中止
                              </button>
                            )}
                            {rec.error_message && (
                              <button
                                onClick={() => setActiveErrorDetail(rec.error_message || "")}
                                className="px-2 py-1 bg-red-500/10 hover:bg-red-500/20 text-red-600 border border-red-500/20 hover:border-red-500/30 text-xs rounded-md transition font-medium"
                              >
                                查看日志
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 弹窗二：错误日志明细弹窗 */}
      {activeErrorDetail && (
        <div 
          onClick={() => setActiveErrorDetail(null)}
          className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs"
        >
          <div 
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-2xl glass-panel rounded-2xl overflow-hidden shadow-2xl border border-slate-200/50 flex flex-col max-h-[75vh]"
          >
            <div className="flex items-center justify-between px-6 py-4 border-b border-red-100 bg-red-50/50">
              <div className="flex items-center gap-2 text-red-600 font-semibold">
                <AlertTriangle className="w-5 h-5" />
                <span>备份故障详细错误堆栈</span>
              </div>
              <button
                onClick={() => setActiveErrorDetail(null)}
                className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-6 bg-slate-50 overflow-auto flex-1 font-mono text-xs text-red-700 whitespace-pre-wrap leading-relaxed select-text select-all border-b border-slate-100">
              {activeErrorDetail}
            </div>
            <div className="px-6 py-3 border-t border-slate-100 text-right bg-slate-50/50">
              <button
                onClick={() => setActiveErrorDetail(null)}
                className="px-4 py-1.5 bg-slate-200 hover:bg-slate-300 text-xs rounded-lg text-slate-700 font-medium transition"
              >
                关闭
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};
