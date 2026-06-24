// -*- coding: utf-8 -*-
import React, { useState, useEffect, useCallback, useMemo } from "react";
import {
  Plus,
  RotateCw,
  Database,
  CheckCircle2,
  AlertOctagon,
  Activity,
  Loader2,
  Grid,
  List,
  Search,
  Settings,
  Send
} from "lucide-react";

import { HostCard } from "./components/HostCard";
import { HostModal } from "./components/HostModal";
import { TemplateModal } from "./components/TemplateModal";
import { BatchDeployModal } from "./components/BatchDeployModal";

interface Host {
  id: number;
  host_name: string;
  ip: string;
  ssh_port: number;
  db_port: number;
  cron_expression: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  latest_record?: any;
}

const App: React.FC = () => {
  const [hosts, setHosts] = useState<Host[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingHost, setEditingHost] = useState<Host | undefined>(undefined);
  const [isTemplateModalOpen, setIsTemplateModalOpen] = useState(false);
  const [isBatchDeployModalOpen, setIsBatchDeployModalOpen] = useState(false);

  // 搜索和过滤状态
  const [searchTerm, setSearchTerm] = useState("");
  const [idcFilter, setIdcFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [viewMode, setViewMode] = useState<"grid" | "table">("grid");

  // 获取主机列表数据
  const fetchHosts = useCallback(async () => {
    setIsLoading(true);
    try {
      const response = await fetch("/api/hosts");
      if (response.ok) {
        const data = await response.json();
        setHosts(data);
      }
    } catch (e) {
      console.error("加载主机列表失败:", e);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // 页面首次载入加载数据
  useEffect(() => {
    fetchHosts();
    // 每一分钟自动整体静默更新一次数据看板
    const timer = setInterval(() => {
      fetchHosts();
    }, 60000);
    return () => clearInterval(timer);
  }, [fetchHosts]);

  // 新增或更新主机配置
  const handleSaveHost = async (payload: any, isBatch: boolean = false) => {
    const isEdit = !!editingHost;
    const url = isBatch
      ? "/api/hosts/batch"
      : (isEdit ? `/api/hosts/${editingHost.id}` : "/api/hosts");
    const method = isBatch ? "POST" : (isEdit ? "PUT" : "POST");

    const response = await fetch(url, {
      method: method,
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    const resData = await response.json();
    if (!response.ok) {
      throw new Error(resData.detail || "保存主机配置失败。");
    }

    // 保存成功后重新拉取
    fetchHosts();
    return resData;
  };

  // 删除主机配置
  const handleDeleteHost = async (id: number) => {
    try {
      const response = await fetch(`/api/hosts/${id}`, {
        method: "DELETE",
      });
      if (response.ok) {
        fetchHosts();
      } else {
        const errData = await response.json();
        alert(errData.detail || "删除失败");
      }
    } catch (e) {
      console.error("删除主机发生异常", e);
    }
  };

  // 触发编辑弹窗
  const triggerEditModal = (host: Host) => {
    setEditingHost(host);
    setIsModalOpen(true);
  };

  // 触发添加弹窗
  const triggerAddModal = () => {
    setEditingHost(undefined);
    setIsModalOpen(true);
  };

  // 自动提取IDC前缀列表与计数
  const { idcList, idcCounts } = useMemo(() => {
    const counts: Record<string, number> = {};
    const list: string[] = [];
    hosts.forEach((h) => {
      const prefix = (h.host_name.split("-")[0] || "unknown").toLowerCase();
      if (!counts[prefix]) {
        counts[prefix] = 0;
        list.push(prefix);
      }
      counts[prefix]++;
    });
    list.sort();
    return { idcList: list, idcCounts: counts };
  }, [hosts]);

  // 过滤后的主机列表
  const filteredHosts = useMemo(() => {
    return hosts.filter((h) => {
      // 1. 搜索词过滤
      if (searchTerm) {
        const term = searchTerm.toLowerCase();
        const matchName = h.host_name?.toLowerCase().includes(term);
        const matchIp = h.ip?.toLowerCase().includes(term);
        if (!matchName && !matchIp) return false;
      }
      // 2. 机房过滤
      if (idcFilter !== "all") {
        const prefix = (h.host_name.split("-")[0] || "").toLowerCase();
        if (prefix !== idcFilter) return false;
      }
      // 3. 状态过滤
      if (statusFilter !== "all") {
        const status = h.latest_record?.status;
        if (statusFilter === "running") {
          if (status !== "running") return false;
        } else if (statusFilter === "success") {
          if (status !== "success" || status === "running") return false;
        } else if (statusFilter === "failed") {
          if (status !== "failed" || status === "running") return false;
        } else if (statusFilter === "inactive") {
          if (h.is_active) return false;
        }
      }
      return true;
    });
  }, [hosts, searchTerm, idcFilter, statusFilter]);

  // 计算全局统计汇总指标（始终基于所有主机）
  const totalHosts = hosts.length;
  const activeSchedulers = hosts.filter(h => h.is_active).length;

  // 今日备份的统计
  const successBackups = hosts.filter(h => h.latest_record?.status === "success").length;
  const failedBackups = hosts.filter(h => h.latest_record?.status === "failed").length;
  const runningBackups = hosts.filter(h => h.latest_record?.status === "running").length;

  const successRate = totalHosts > 0
    ? Math.round((successBackups / (successBackups + failedBackups || 1)) * 100)
    : 100;

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">

      {/* 顶部标题与操作栏 */}
      <header className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-6 border-b border-slate-200">
        <div>
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-xl bg-gradient-to-tr from-blue-600 to-indigo-600 text-white shadow-lg shadow-blue-500/25">
              <Database className="w-6 h-6" />
            </div>
            <h1 className="text-2xl font-bold tracking-tight text-slate-800 font-sans">
              MySQL 自动物理克隆备份系统
            </h1>
          </div>
          <p className="text-sm text-slate-500 mt-1">
            免 Agent 远程控制，基于 MySQL 8.0 CLONE 物理复制的高并发自动备份及智能清理系统
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={fetchHosts}
            disabled={isLoading}
            className="p-2.5 rounded-xl text-slate-500 hover:text-slate-800 bg-white border border-slate-200 hover:bg-slate-50 shadow-xs transition flex items-center justify-center disabled:opacity-50"
            title="手动刷新状态"
          >
            <RotateCw className={`w-4 h-4 ${isLoading ? "animate-spin text-blue-600" : ""}`} />
          </button>

          <button
            onClick={() => setIsTemplateModalOpen(true)}
            className="p-2.5 rounded-xl text-slate-500 hover:text-indigo-600 bg-white border border-slate-200 hover:border-indigo-200 hover:bg-indigo-50 shadow-xs transition flex items-center justify-center"
            title="全局模板设置"
          >
            <Settings className="w-4 h-4" />
          </button>

          <button
            onClick={() => setIsBatchDeployModalOpen(true)}
            className="p-2.5 rounded-xl text-slate-500 hover:text-indigo-600 bg-white border border-slate-200 hover:border-indigo-200 hover:bg-indigo-50 shadow-xs transition flex items-center justify-center"
            title="批量重新部署所有 Agent"
          >
            <Send className="w-4 h-4" />
          </button>

          <button
            onClick={triggerAddModal}
            className="px-4 py-2.5 rounded-xl text-sm font-semibold text-white bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 shadow-lg shadow-blue-500/20 hover:shadow-blue-500/30 transition flex items-center gap-2"
          >
            <Plus className="w-4 h-4" />
            添加目标主机
          </button>
        </div>
      </header>

      {/* 统计指标卡片看板 (浅色毛玻璃) */}
      <section className="grid grid-cols-1 md:grid-cols-4 gap-4">
        {/* 指标一：主机总数 */}
        <div className="glass-card rounded-2xl p-5 flex items-center justify-between">
          <div>
            <span className="text-xs font-semibold text-slate-500 uppercase">管理的数据库主机</span>
            <h3 className="text-3xl font-bold text-slate-800 mt-1 font-mono">{totalHosts}</h3>
          </div>
          <div className="p-3 bg-blue-500/10 border border-blue-500/20 text-blue-600 rounded-xl">
            <Database className="w-6 h-6" />
          </div>
        </div>

        {/* 指标二：计划任务 */}
        <div className="glass-card rounded-2xl p-5 flex items-center justify-between">
          <div>
            <span className="text-xs font-semibold text-slate-500 uppercase">定时备份计划</span>
            <h3 className="text-3xl font-bold text-slate-800 mt-1 font-mono">
              {activeSchedulers} <span className="text-xs font-normal text-slate-400">/ {totalHosts}</span>
            </h3>
          </div>
          <div className="p-3 bg-indigo-500/10 border border-indigo-500/20 text-indigo-600 rounded-xl">
            <Activity className="w-6 h-6" />
          </div>
        </div>

        {/* 指标三：今日运行状态 */}
        <div className="glass-card rounded-2xl p-5 flex items-center justify-between">
          <div>
            <span className="text-xs font-semibold text-slate-500 uppercase">运行中 / 失败</span>
            <h3 className="text-3xl font-bold mt-1 font-mono">
              <span className="text-blue-600">{runningBackups}</span>
              <span className="text-slate-300 mx-2">/</span>
              <span className={failedBackups > 0 ? "text-red-600" : "text-slate-400"}>{failedBackups}</span>
            </h3>
          </div>
          <div className={`p-3 rounded-xl border ${failedBackups > 0
              ? "bg-red-500/10 border-red-500/20 text-red-600 animate-pulse"
              : "bg-slate-100 border-slate-200 text-slate-500"
            }`}>
            <AlertOctagon className="w-6 h-6" />
          </div>
        </div>

        {/* 指标四：最新备份成功率 */}
        <div className="glass-card rounded-2xl p-5 flex items-center justify-between">
          <div>
            <span className="text-xs font-semibold text-slate-500 uppercase">备份成功率</span>
            <h3 className="text-3xl font-bold text-emerald-600 mt-1 font-mono">
              {successRate}%
            </h3>
          </div>
          <div className="p-3 bg-emerald-500/10 border border-emerald-500/20 text-emerald-600 rounded-xl">
            <CheckCircle2 className="w-6 h-6" />
          </div>
        </div>
      </section>

      {/* 检索与排版控制面板 */}
      <section className="glass-card rounded-2xl p-4 flex flex-col md:flex-row md:items-center justify-between gap-4">
        {/* 左侧：搜索与状态筛选 */}
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 flex-1 max-w-2xl">
          {/* 搜索框 */}
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <input
              type="text"
              placeholder="搜索主机名/IP地址..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-9 pr-4 py-2 text-sm bg-slate-50 border border-slate-200/80 rounded-xl focus:outline-hidden focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all placeholder:text-slate-400 text-slate-700"
            />
          </div>
          {/* 状态筛选下拉框 */}
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="px-3 py-2 text-sm bg-slate-50 border border-slate-200/80 rounded-xl focus:outline-hidden focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all text-slate-700 cursor-pointer"
          >
            <option value="all">全部状态</option>
            <option value="running">运行中</option>
            <option value="success">备份成功</option>
            <option value="failed">备份失败</option>
            <option value="inactive">未启用</option>
          </select>
        </div>

        {/* 右侧：机房 Tabs & 视图切换 */}
        <div className="flex items-center justify-between md:justify-end gap-4 overflow-x-auto no-scrollbar shrink-0">
          {/* 机房 Tabs */}
          <div className="flex items-center gap-1.5 bg-slate-100/85 p-1 rounded-xl">
            <button
              onClick={() => setIdcFilter("all")}
              className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all ${idcFilter === "all"
                  ? "bg-white text-slate-800 shadow-xs"
                  : "text-slate-500 hover:text-slate-700"
                }`}
            >
              全部机房
              <span className="ml-1 px-1.5 py-0.2 rounded-md text-[10px] bg-slate-200/60 text-slate-600 font-mono">
                {hosts.length}
              </span>
            </button>
            {idcList.map((idc) => (
              <button
                key={idc}
                onClick={() => setIdcFilter(idc)}
                className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all uppercase ${idcFilter === idc
                    ? "bg-white text-slate-800 shadow-xs border border-slate-200/50"
                    : "text-slate-500 hover:text-slate-700"
                  }`}
              >
                {idc}
                <span className="ml-1 px-1.5 py-0.2 rounded-md text-[10px] bg-slate-200/60 text-slate-600 font-mono">
                  {idcCounts[idc] || 0}
                </span>
              </button>
            ))}
          </div>

          {/* 视图切换按钮 */}
          <div className="flex items-center gap-1 bg-slate-100/85 p-1 rounded-xl border border-slate-200/20">
            <button
              onClick={() => setViewMode("grid")}
              className={`p-1.5 rounded-lg transition-all ${viewMode === "grid"
                  ? "bg-white text-blue-600 shadow-xs"
                  : "text-slate-500 hover:text-slate-700"
                }`}
              title="网格卡片"
            >
              <Grid className="w-4 h-4" />
            </button>
            <button
              onClick={() => setViewMode("table")}
              className={`p-1.5 rounded-lg transition-all ${viewMode === "table"
                  ? "bg-white text-blue-600 shadow-xs"
                  : "text-slate-500 hover:text-slate-700"
                }`}
              title="紧凑表格"
            >
              <List className="w-4 h-4" />
            </button>
          </div>
        </div>
      </section>

      {/* 主机显示区域 */}
      <main className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold text-slate-800">主机监控看板</h3>
          {filteredHosts.length > 0 && (
            <span className="text-xs text-slate-500 font-medium">
              当前展示: {filteredHosts.length} / {totalHosts} 台主机
            </span>
          )}
        </div>

        {isLoading && hosts.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-24 gap-3 text-slate-500">
            <Loader2 className="w-8 h-8 animate-spin text-blue-600" />
            <span>加载主机配置中...</span>
          </div>
        ) : hosts.length === 0 ? (
          <div className="text-center py-24 glass-card rounded-2xl border border-dashed border-slate-200/50 space-y-3">
            <Database className="w-10 h-10 text-slate-400 mx-auto" />
            <p className="text-slate-500 text-sm">暂无任何配置的主机。点击右上方“添加目标主机”开始。</p>
          </div>
        ) : filteredHosts.length === 0 ? (
          <div className="text-center py-20 glass-card rounded-2xl border border-dashed border-slate-200/50 space-y-2">
            <Search className="w-8 h-8 text-slate-400 mx-auto" />
            <p className="text-slate-500 text-sm font-medium">没有找到符合筛选条件的主机</p>
            <p className="text-xs text-slate-400">请尝试清除或调整搜索关键字与过滤选项</p>
          </div>
        ) : viewMode === "grid" ? (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {filteredHosts.map((host) => (
              <HostCard
                key={host.id}
                host={host}
                onEdit={triggerEditModal}
                onDelete={handleDeleteHost}
                onRefreshData={fetchHosts}
                viewMode="grid"
              />
            ))}
          </div>
        ) : (
          <div className="overflow-x-auto bg-white rounded-2xl border border-slate-200/80 shadow-xs">
            <table className="w-full border-collapse text-left">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  <th className="py-3 px-4">主机别名</th>
                  <th className="py-3 px-4">IP & 端口</th>
                  <th className="py-3 px-4">自动备份计划</th>
                  <th className="py-3 px-4">最新备份结果</th>
                  <th className="py-3 px-4">上次备份日期</th>
                  <th className="py-3 px-4">备份耗时</th>
                  <th className="py-3 px-4 text-right">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filteredHosts.map((host) => (
                  <HostCard
                    key={host.id}
                    host={host}
                    onEdit={triggerEditModal}
                    onDelete={handleDeleteHost}
                    onRefreshData={fetchHosts}
                    viewMode="table"
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>

      {/* 新增/编辑主机模态弹窗 */}
      <HostModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onSave={handleSaveHost}
        editHost={editingHost}
      />
      
      {isTemplateModalOpen && (
        <TemplateModal onClose={() => setIsTemplateModalOpen(false)} />
      )}

      {isBatchDeployModalOpen && (
        <BatchDeployModal
          onClose={() => setIsBatchDeployModalOpen(false)}
          onRefresh={fetchHosts}
        />
      )}
    </div>
  );
};

export default App;
