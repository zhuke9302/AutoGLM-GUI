import React, { useEffect, useRef, useState } from 'react';
import { Link, useMatchRoute } from '@tanstack/react-router';
import {
  MessageSquare,
  ListChecks,
  FileText,
  History,
  Clock,
  Terminal,
  type LucideIcon,
} from 'lucide-react';
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
} from '@/components/ui/tooltip';
import { useTranslation } from '../lib/i18n-context';
import { getSyncStatus, type SyncStatus } from '../api';
import logoImage from '@/assets/logo.png';

interface NavigationItem {
  id: string;
  icon: LucideIcon;
  label: string;
  path: string;
}

interface NavigationSidebarProps {
  className?: string;
}

export function NavigationSidebar({ className }: NavigationSidebarProps) {
  const t = useTranslation();
  const matchRoute = useMatchRoute();
  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    let timeoutId: number | null = null;

    const poll = async () => {
      try {
        const status = await getSyncStatus();
        if (mountedRef.current) {
          setSyncStatus(status);
        }
      } catch {
        // Endpoint may not exist in standalone mode; silently ignore
        if (mountedRef.current) {
          setSyncStatus(null);
        }
      }
      if (mountedRef.current) {
        timeoutId = window.setTimeout(poll, 30_000);
      }
    };

    void poll();

    return () => {
      mountedRef.current = false;
      if (timeoutId !== null) {
        window.clearTimeout(timeoutId);
      }
    };
  }, []);

  const navigationItems: NavigationItem[] = [
    {
      id: 'chat',
      icon: MessageSquare,
      label: t.navigation.chat,
      path: '/chat',
    },
    {
      id: 'workflows',
      icon: ListChecks,
      label: t.navigation.workflows,
      path: '/workflows',
    },
    {
      id: 'history',
      icon: History,
      label: t.navigation.history || '历史记录',
      path: '/history',
    },
    {
      id: 'scheduled-tasks',
      icon: Clock,
      label: t.navigation.scheduledTasks || '定时任务',
      path: '/scheduled-tasks',
    },
    {
      id: 'logs',
      icon: FileText,
      label: t.navigation.logs,
      path: '/logs',
    },
    {
      id: 'terminal',
      icon: Terminal,
      label: t.navigation.terminal,
      path: '/terminal',
    },
  ];

  // Determine sync indicator state
  const syncLabel =
    syncStatus?.active && syncStatus.connected
      ? (t.syncStatus?.connected ?? '已连接')
      : syncStatus?.active && !syncStatus.connected
        ? (t.syncStatus?.offline ?? '离线')
        : null;
  const syncDotColor =
    syncStatus?.active && syncStatus.connected
      ? 'bg-green-500'
      : syncStatus?.active && !syncStatus.connected
        ? 'bg-yellow-500'
        : null;

  return (
    <nav
      className={`w-16 h-full flex flex-col bg-white dark:bg-slate-950 border-r border-slate-200 dark:border-slate-800 ${className || ''}`}
    >
      <div className="flex flex-col items-center py-4 gap-2">
        {/* Logo at top - clickable to navigate to /chat */}
        <div className="mb-4 pb-4 border-b border-slate-200 dark:border-slate-800 w-full flex justify-center">
          <Tooltip>
            <TooltipTrigger asChild>
              <Link to="/chat" className="block">
                <img
                  src={logoImage}
                  alt="AutoGLM Logo"
                  className="w-10 h-10 object-contain cursor-pointer hover:opacity-80 transition-opacity"
                />
              </Link>
            </TooltipTrigger>
            <TooltipContent side="right" sideOffset={8}>
              {t.navigation?.backToHome || 'Back to Home'}
            </TooltipContent>
          </Tooltip>
        </div>

        {/* Navigation items */}
        {navigationItems.map(item => {
          const Icon = item.icon;
          const isActive = matchRoute({ to: item.path });

          return (
            <Tooltip key={item.id}>
              <TooltipTrigger asChild>
                <Link
                  to={item.path}
                  className={`w-10 h-10 rounded-lg transition-all flex items-center justify-center ${
                    isActive
                      ? 'bg-[#1d9bf0]/10 text-[#1d9bf0] hover:bg-[#1d9bf0]/20'
                      : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800'
                  }`}
                >
                  <Icon className="w-5 h-5" />
                </Link>
              </TooltipTrigger>
              <TooltipContent side="right" sideOffset={8}>
                {item.label}
              </TooltipContent>
            </Tooltip>
          );
        })}
      </div>

      {/* Sync status indicator at bottom */}
      {syncLabel && syncDotColor && (
        <div className="mt-auto pb-3 flex flex-col items-center gap-1">
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="flex flex-col items-center gap-1 cursor-default">
                <span
                  className={`inline-block w-2 h-2 rounded-full ${syncDotColor}`}
                />
                <span className="text-[10px] leading-none text-slate-500 dark:text-slate-400">
                  {syncLabel}
                </span>
              </div>
            </TooltipTrigger>
            <TooltipContent side="right" sideOffset={8}>
              {syncStatus?.server_url ?? ''}
            </TooltipContent>
          </Tooltip>
        </div>
      )}
    </nav>
  );
}
