import type { NextConfig } from "next";

const backendApiUrl = (process.env.BACKEND_API_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');

const nextConfig: NextConfig = {
  agentRules: false,
  async rewrites() {
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
