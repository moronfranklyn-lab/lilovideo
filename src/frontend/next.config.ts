import type { NextConfig } from "next";

const backendApiUrl = (process.env.BACKEND_API_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');

/**
 * 单端口部署模式：把前端静态导出，交给后端（FastAPI）一起托管。
 *
 * 为什么值得这么做：
 *   现在前端靠 `rewrites()` 把 30 条 `/api/*` 逐条代理到后端。这套代理漏配过**三次**
 *   （/api/cost/*、/api/credits/*、/api/models/*），症状都是"直连后端 200、经前端 404"。
 *   静态导出后前端与后端**同源**，一个代理规则都不需要，这一整类问题从根上消失。
 *
 * 开启方式：构建时设 NEXT_OUTPUT=export。
 * 不开时（含 `next dev`）保持原样：前端 3000、后端 8000，走 rewrites 代理。
 */
const isStaticExport = process.env.NEXT_OUTPUT === 'export';

const nextConfig: NextConfig = {
  ...(isStaticExport ? { output: 'export' as const, trailingSlash: true } : {}),
  agentRules: false,
  async rewrites() {
    // 静态导出时前后端同源，没有可代理的对象；而且 output: 'export' 不允许 rewrites。
    if (isStaticExport) return [];
    return [
      {
        source: '/code/:path*',
        destination: `${backendApiUrl}/code/:path*`,
      },
      {
        source: '/api/sessions',
        destination: `${backendApiUrl}/api/sessions`,
      },
      {
        source: '/api/sessions/:path*',
        destination: `${backendApiUrl}/api/sessions/:path*`,
      },
      // 工作流 API
      {
        source: '/api/project/:path*',
        destination: `${backendApiUrl}/api/project/:path*`,
      },
      {
        source: '/api/stages',
        destination: `${backendApiUrl}/api/stages`,
      },
      {
        source: '/api/upload_media',
        destination: `${backendApiUrl}/api/upload_media`,
      },
      {
        source: '/api/upload_file',
        destination: `${backendApiUrl}/api/upload_file`,
      },
      {
        source: '/api/models',
        destination: `${backendApiUrl}/api/models`,
      },
      // 上面那条是**精确匹配**，不覆盖子路径。
      // `/api/models/available`、`/api/models/check` 要靠下面这条转发。
      // 这个坑踩过三次了（/api/cost/*、/api/credits/*、/api/models/*），
      // 现在有一条单测逐个前缀核对后端路由与这里是否对齐。
      {
        source: '/api/models/:path*',
        destination: `${backendApiUrl}/api/models/:path*`,
      },
      {
        source: '/api/config',
        destination: `${backendApiUrl}/api/config`,
      },
      {
        source: '/api/cache/:path*',
        destination: `${backendApiUrl}/api/cache/:path*`,
      },
      // 成本核算 API
      //
      // 注意：本文件是**逐条列举**代理路径的，后端新增接口不会自动生效。
      // 曾漏掉这一条，导致 /api/cost/* 经前端访问返回 404（直连后端正常），
      // 排查时容易误判为后端问题。新增后端路由时记得在这里同步加一条。
      {
        source: '/api/cost/:path*',
        destination: `${backendApiUrl}/api/cost/:path*`,
      },
      {
        source: '/api/credits/:path*',
        destination: `${backendApiUrl}/api/credits/:path*`,
      },
      {
        source: '/api/health',
        destination: `${backendApiUrl}/api/health`,
      },
      // 一键 pipeline API
      {
        source: '/api/pipelines',
        destination: `${backendApiUrl}/api/pipelines`,
      },
      {
        source: '/api/pipelines/:path*',
        destination: `${backendApiUrl}/api/pipelines/:path*`,
      },
      {
        source: '/api/tasks',
        destination: `${backendApiUrl}/api/tasks`,
      },
      {
        source: '/api/tasks/:path*',
        destination: `${backendApiUrl}/api/tasks/:path*`,
      },
      // 临时工作台 API
      {
        source: '/api/sandbox/:path*',
        destination: `${backendApiUrl}/api/sandbox/:path*`,
      },
    ];
  },
};

export default nextConfig;
