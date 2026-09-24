'use client';

import React, { useState, useRef, useEffect } from 'react';
import { Settings2, Clock, ArrowRight, CheckCircle, Trash2, Globe, Loader2, Cpu, ChevronDown, Check, Sparkles } from 'lucide-react';

/* 创作类型预设：一键应用「风格 + 画幅 + 分辨率」配方并填入示例创意 */
const PRESET_TYPES = [
  {
    id: 'anime',
    name: '动漫',
    color: '#f472b6',
    prompt: '樱花纷飞的放学路上，少年与青梅竹马在旧书店前重逢，风吹起她的发梢，两人相视而笑。',
    recipe: { style: 'anime', ratio: '9:16', resolution: '1080P' },
  },
  {
    id: 'ink',
    name: '水墨国风',
    color: '#334155',
    prompt: '云雾缭绕的青山之间，一叶扁舟穿行于江面，船头老者抚琴，白鹤掠过水面，墨色晕染如画。',
    recipe: { style: 'chinese-ink', ratio: '16:9', resolution: '1080P' },
  },
  {
    id: 'cyber',
    name: '科幻赛博',
    color: '#a855f7',
    prompt: '霓虹闪烁的未来都市雨夜，机械义体侦探在小巷追踪线索，全息广告在楼宇间闪烁，雨滴折射出紫色光斑。',
    recipe: { style: 'cyberpunk', ratio: '21:9', resolution: '1080P' },
  },
  {
    id: 'real',
    name: '写实电影',
    color: '#64748b',
    prompt: '黄昏的海边小镇，老渔夫在码头修补渔网，远处灯塔亮起，海鸥盘旋，光影细腻如电影胶片。',
    recipe: { style: 'realistic', ratio: '16:9', resolution: '1080P' },
  },
  {
    id: '3d',
    name: '3D 动画',
    color: '#60a5fa',
    prompt: '圆滚滚的小机器人掉进糖果森林，被会说话的兔子与蘑菇精灵包围，开启一场软萌的冒险。',
    recipe: { style: '3d-disney', ratio: '16:9', resolution: '1080P' },
  },
  {
    id: 'heal',
    name: '治愈日常',
    color: '#34d399',
    prompt: '午后阳光洒进窗台，橘猫蜷在绿植旁打盹，一杯热茶冒着热气，画面温暖安静而治愈。',
    recipe: { style: 'watercolor', ratio: '4:3', resolution: '720P' },
  },
];

/* 风格色标：高级设置面板中风格选择的视觉标识 */
const STYLE_COLORS: Record<string, string> = {
  'comic-book': '#ff6b6b',
  anime: '#f472b6',
  realistic: '#64748b',
  '3d-disney': '#60a5fa',
  watercolor: '#34d399',
  'oil-painting': '#f59e0b',
  cyberpunk: '#a855f7',
  'chinese-ink': '#334155',
};
import clsx from 'clsx';
import { PROMPT_EXAMPLES } from '@/config/examples';
import {
  STYLES,
  VIDEO_RATIOS,
  VIDEO_RESOLUTIONS,
  VIDEO_GENERATION_MODES,
  type ProviderGroup,
  type VideoGenerationMode,
} from '@/config/models';
import { STAGES } from './TopBar';
import { fetchModelGroupsByType, fetchVideoModelGroupsByAbility } from '@/lib/modelRegistry';
import { fetchVideoSkus, type VideoSku, type VideoSkuResponse } from '@/lib/workflowApi';
import { BRAND } from '@/config/brand';
import GradientBlob from './GradientBlob';
import SplashCursor from './SplashCursor';
import LaserFlow from './LaserFlow';
import BorderGlow from './BorderGlow';
import MaskedHeading from './MaskedHeading';
import TiltCard from './TiltCard';

export interface ProjectParams {
  idea: string;
  file_path?: string; // 上传的文件路径 (由后端返回的文件名)
  style: string;
  video_ratio: string;
  video_resolution: string;
  llm_model: string;
  vlm_model: string;
  image_t2i_model: string;
  image_it2i_model: string;
  video_model: string;
  video_first_frame_model: string;
  video_start_end_model: string;
  video_reference_model: string;
  video_generation_mode: VideoGenerationMode;
  expand_idea?: boolean;
  enable_concurrency?: boolean;
  web_search?: boolean;
  episodes?: number;
}

interface HistoryItem {
  id: string;
  idea: string;
  style?: string;
  date: string;
  status: string;
  stages?: Record<string, string>;
}

interface HomePageProps {
  onStartProject: (params: ProjectParams, autoMode?: boolean) => void;
  onResumeProject: (sessionId: string) => void;
  onDeleteSession: (sessionId: string) => Promise<void>;
  history: HistoryItem[];
}

const INSPIRATION_IMAGES = [
  '/ui/inspiration-space.png',
  '/ui/inspiration-ink.png',
  '/ui/inspiration-detective.png',
  '/ui/inspiration-cat.png',
  '/ui/inspiration-mars.png',
  '/ui/inspiration-wuxia.png',
];

/* 根据 status 映射生成进度文本 */
function stageProgressLabel(statusMap?: Record<string, string>): { text: string; color: string } {
  const map = statusMap || {};
  const completed = Object.keys(map).filter(k => ["completed", "session_completed"].includes(map[k]));
  if (completed.length === 0) return { text: '未开始', color: 'text-gray-400' };
  if (completed.length >= STAGES.length) return { text: '已完成', color: 'text-green-600' };
  
  // 对比 STAGES 获取最后一个已完成的
  const lastStageId = STAGES.filter(s => completed.includes(s.id)).pop()?.id || completed[completed.length - 1];
  const stageDef = STAGES.find(s => s.id === lastStageId);
  const name = stageDef?.shortName || lastStageId;
  return { text: `已完成：${name} (${completed.length}/${STAGES.length})`, color: 'text-blue-600' };
}

export default function HomePage({ onStartProject, onResumeProject, onDeleteSession, history }: HomePageProps) {
  const [idea, setIdea] = useState('');
  const [showSettings, setShowSettings] = useState(false);
  const [showModels, setShowModels] = useState(false); // 模型配置默认收起
  const [selectedStyle, setSelectedStyle] = useState('realistic');
  const [selectedLLM, setSelectedLLM] = useState('');
  const [selectedVLM, setSelectedVLM] = useState('');
  const [selectedT2I, setSelectedT2I] = useState('');
  const [selectedI2I, setSelectedI2I] = useState('');
  const [selectedFirstFrameVideo, setSelectedFirstFrameVideo] = useState('');
  const [selectedStartEndVideo, setSelectedStartEndVideo] = useState('');
  const [selectedReferenceVideo, setSelectedReferenceVideo] = useState('');
  const [selectedVideoMode, setSelectedVideoMode] = useState<VideoGenerationMode>('first_frame');
  const [selectedRatio, setSelectedRatio] = useState('');
  const [selectedResolution, setSelectedResolution] = useState('720P');
  const [modelPopOpen, setModelPopOpen] = useState(false);
  const [ratioPopOpen, setRatioPopOpen] = useState(false);
  const modelPopRef = useRef<HTMLDivElement>(null);
  const ratioPopRef = useRef<HTMLDivElement>(null);
  const [configLoading, setConfigLoading] = useState(true);
  const [configError, setConfigError] = useState('');
  const [enableConcurrency, setEnableConcurrency] = useState(true);
  const [webSearch, setWebSearch] = useState(false);
  const [episodes, setEpisodes] = useState(4);

  // 生成前报价：所选视频模型的档位参考价（5 秒基准）
  const [skuData, setSkuData] = useState<VideoSkuResponse | null>(null);
  const [skuLoading, setSkuLoading] = useState(false);

  // 上传相关状态
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadedFile, setUploadedFile] = useState<{name: string, path: string} | null>(null);

  // 管理模式状态
  const [manageMode, setManageMode] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [llmProviders, setLlmProviders] = useState<ProviderGroup[]>([]);
  const [vlmProviders, setVlmProviders] = useState<ProviderGroup[]>([]);
  const [t2iProviders, setT2iProviders] = useState<ProviderGroup[]>([]);
  const [i2iProviders, setI2iProviders] = useState<ProviderGroup[]>([]);
  const [firstFrameVideoProviders, setFirstFrameVideoProviders] = useState<ProviderGroup[]>([]);
  const [startEndVideoProviders, setStartEndVideoProviders] = useState<ProviderGroup[]>([]);
  const [referenceVideoProviders, setReferenceVideoProviders] = useState<ProviderGroup[]>([]);
  const activeVideoModel =
    selectedVideoMode === 'start_end_frame'
      ? selectedStartEndVideo
      : selectedVideoMode === 'reference'
        ? selectedReferenceVideo
        : selectedFirstFrameVideo;
  const modelConfigReady = Boolean(selectedLLM && selectedVLM && selectedT2I && selectedI2I && activeVideoModel && selectedRatio && selectedResolution);
  const canStart = Boolean((idea.trim() || uploadedFile) && modelConfigReady && !configLoading);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (modelPopRef.current && !modelPopRef.current.contains(e.target as Node)) setModelPopOpen(false);
      if (ratioPopRef.current && !ratioPopRef.current.contains(e.target as Node)) setRatioPopOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchModelGroupsByType('llm')
      .then(groups => { if (!cancelled) setLlmProviders(groups); })
      .catch(() => {});
    fetchModelGroupsByType('vlm')
      .then(groups => { if (!cancelled) setVlmProviders(groups); })
      .catch(() => {});
    fetchModelGroupsByType('t2i')
      .then(groups => { if (!cancelled) setT2iProviders(groups); })
      .catch(() => {});
    fetchModelGroupsByType('i2i')
      .then(groups => { if (!cancelled) setI2iProviders(groups); })
      .catch(() => {});
    fetchVideoModelGroupsByAbility('first_frame_i2v')
      .then(groups => { if (!cancelled) setFirstFrameVideoProviders(groups); })
      .catch(() => {});
    fetchVideoModelGroupsByAbility('start_end_frame_i2v')
      .then(groups => { if (!cancelled) setStartEndVideoProviders(groups); })
      .catch(() => {});
    fetchVideoModelGroupsByAbility('reference_to_video')
      .then(groups => { if (!cancelled) setReferenceVideoProviders(groups); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const loadDefaultConfig = async () => {
      setConfigLoading(true);
      setConfigError('');
      try {
        const resp = await fetch('/api/config');
        if (!resp.ok) throw new Error('读取默认模型配置失败');
        const data = await resp.json();
        const models = data.config?.models || {};
        const generation = data.config?.generation || {};
        // Legacy config compatibility: older config.yaml only has models.video, so treat it as first-frame video.
        const firstFrameModel = models.video_first_frame || models.video;
        const startEndModel = models.video_start_end || 'wan2.7-i2v';
        const referenceModel = models.video_reference || 'wan2.7-r2v';
        const videoMode = (generation.video_generation_mode || 'first_frame') as VideoGenerationMode;
        const selectedModel = videoMode === 'start_end_frame' ? startEndModel : videoMode === 'reference' ? referenceModel : firstFrameModel;
        if (!models.llm || !models.vlm || !models.image_t2i || !models.image_it2i || !selectedModel) {
          throw new Error('backend/config.yaml 缺少主流程默认模型');
        }
        if (cancelled) return;
        setSelectedStyle(generation.style || 'realistic');
        setSelectedLLM(models.llm);
        setSelectedVLM(models.vlm);
        setSelectedT2I(models.image_t2i);
        setSelectedI2I(models.image_it2i);
        setSelectedVideoMode(videoMode);
        setSelectedFirstFrameVideo(firstFrameModel);
        setSelectedStartEndVideo(startEndModel);
        setSelectedReferenceVideo(referenceModel);
        setSelectedRatio(generation.video_ratio || '16:9');
        setSelectedResolution(generation.video_resolution || '720P');
      } catch (e: any) {
        if (!cancelled) setConfigError(e.message || '读取默认模型配置失败');
      } finally {
        if (!cancelled) setConfigLoading(false);
      }
    };
    loadDefaultConfig();
    return () => { cancelled = true; };
  }, []);

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    setDeleteError('');
    try {
      await onDeleteSession(deleteTarget);
      setDeleteTarget(null);
    } catch (e: any) {
      setDeleteError(e.message || '删除失败');
    } finally {
      setDeleting(false);
    }
  };

  const activeVideoProviders =
    selectedVideoMode === 'start_end_frame'
      ? startEndVideoProviders
      : selectedVideoMode === 'reference'
        ? referenceVideoProviders
        : firstFrameVideoProviders;

  const setActiveVideoModel = (value: string) => {
    if (selectedVideoMode === 'start_end_frame') {
      setSelectedStartEndVideo(value);
    } else if (selectedVideoMode === 'reference') {
      setSelectedReferenceVideo(value);
    } else {
      setSelectedFirstFrameVideo(value);
    }
  };

  const activeVideoModelLabel = activeVideoProviders
    .flatMap(g => g.models)
    .find(m => m.id === activeVideoModel)?.label;

  // 模型展示名：去掉 " - API xxx" 这类技术后缀，只给用户看模型本身
  const displayModelLabel = (label: string) => label.replace(/\s*-\s*API.*$/, '');

  const selectedVideoModeLabel = VIDEO_GENERATION_MODES.find(item => item.id === selectedVideoMode)?.label || '首帧生视频';

  // 视频模型变化时拉取 5 秒档位报价
  useEffect(() => {
    let cancelled = false;
    if (!activeVideoModel) {
      setSkuData(null);
      return;
    }
    setSkuLoading(true);
    fetchVideoSkus(5)
      .then(data => { if (!cancelled) setSkuData(data); })
      .catch(() => { if (!cancelled) setSkuData(null); })
      .finally(() => { if (!cancelled) setSkuLoading(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeVideoModel]);
  const handleStart = (auto?: boolean) => {
    if (!canStart) return;
    onStartProject({
      idea,
      file_path: uploadedFile?.path, // 如果上传了文件，传给后端
      style: selectedStyle,
      video_ratio: selectedRatio,
      video_resolution: selectedResolution,
      llm_model: selectedLLM,
      vlm_model: selectedVLM,
      image_t2i_model: selectedT2I,
      image_it2i_model: selectedI2I,
      video_generation_mode: selectedVideoMode,
      video_first_frame_model: selectedFirstFrameVideo,
      video_start_end_model: selectedStartEndVideo,
      video_reference_model: selectedReferenceVideo,
      video_model: activeVideoModel,
      enable_concurrency: enableConcurrency,
      web_search: webSearch,
      episodes,
    }, auto);
  };

  const handleExampleClick = (text: string) => {
    setIdea(text);
  };

  // 创作类型预设：一键应用风格/画幅/分辨率配方 + 填入示例创意
  const [activePreset, setActivePreset] = useState<string | null>(null);
  const applyPreset = (preset: (typeof PRESET_TYPES)[number]) => {
    setIdea(preset.prompt);
    setSelectedStyle(preset.recipe.style);
    setSelectedRatio(preset.recipe.ratio);
    setSelectedResolution(preset.recipe.resolution);
    setActivePreset(preset.id);
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const allowedExtensions = ['.doc', '.docx', '.txt', '.md', '.pdf'];
    const extension = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
    
    if (!allowedExtensions.includes(extension)) {
      alert(`仅支持 ${allowedExtensions.join(', ')} 格式的文件`);
      return;
    }

    setUploading(true);
    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await fetch('/api/upload_file', {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        throw new Error('文件上传失败');
      }

      const data = await response.json();
      if (data.file_path) {
        // 记录已上传的文件信息，不修改输入框
        setUploadedFile({
          name: file.name,
          path: data.file_path
        });
      }
    } catch (error) {
      console.error('上传错误:', error);
      alert('上传提取内容失败，请重试');
    } finally {
      setUploading(false);
      // 清空 input 方便下次选择同一文件
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  return (
    <div className="lilo-home relative h-full flex flex-col items-center overflow-y-auto bg-gray-50/50">
      {/* 动态光晕背景（GradientBlob，紫色系参照参考图） */}
      <GradientBlob
        colors={{ primary: '#5227ff', secondary: '#ff9ffc', accent: '#b19eef', base: '#27c5ff' }}
        speed={0.6}
        morphIntensity={0.8}
        size={1.25}
        enableCursorMorph
        parallax
        parallaxStrength={0.4}
        quality="low"
        maxFPS={40}
        pauseWhenOffscreen
        className="absolute inset-0 z-0 h-full w-full"
      />

      {/* 抚摸光标（SplashCursor，光晕之上的视觉层） */}
      <SplashCursor
        DENSITY_DISSIPATION={2.2}
        VELOCITY_DISSIPATION={1.5}
        PRESSURE={0.1}
        CURL={0.2}
        SPLAT_RADIUS={0.4}
        SPLAT_FORCE={2500}
        COLOR_UPDATE_SPEED={10}
        SHADING
        RAINBOW_MODE={false}
        COLOR="#b497cf"
        className="z-[1]"
      />

      {/* 主区域 - 居中 */}
      <div className="lilo-home-main relative z-[2] w-full max-w-6xl px-6 pt-16 pb-8 flex-shrink-0">
        {/* 标题 */}
        <div className="lilo-hero-title text-center mb-10">
          <MaskedHeading
            text={`Hi，和 ${BRAND.name} 一起聊聊创作想法`}
            src="/ui/hero-title.jpg"
            fillScale={1.25}
            parallax={18}
            reveal="rise"
            trigger="view"
            brightness={1}
            saturation={1}
            duration={1.1}
            align="center"
            weight={600}
            tracking={-0.02}
            lineHeight={1.1}
            className="lilo-masked-title"
          />
          <p className="text-sm text-white/75">
            <span className="lilo-hero-accent">{BRAND.tagline}</span> · 从一句灵感开始，让 AI 陪你完成整部短片
          </p>
          {/* 首屏流程引导：一句话讲清产品价值 */}
          <div className="lilo-hero-flow mt-4">
            {['一句话创意', '剧本', '分镜', '参考图', '视频', '成片'].map((step, i) => (
              <span key={step} className="flex items-center">
                <span className="lilo-hero-flow-step">{step}</span>
                {i < 5 && <span className="lilo-hero-flow-arrow">→</span>}
              </span>
            ))}
          </div>
        </div>

        {/* 创作类型预设：一键应用配方 */}
        <div className="lilo-presets mb-5">
          <span className="lilo-presets-label">创作类型</span>
          <div className="lilo-presets-row">
            {PRESET_TYPES.map(preset => (
              <button
                key={preset.id}
                onClick={() => applyPreset(preset)}
                className={`lilo-preset-chip ${activePreset === preset.id ? 'active' : ''}`}
              >
                <span
                  className="w-2 h-2 rounded-full flex-shrink-0"
                  style={{ backgroundColor: preset.color }}
                />
                {preset.name}
                {activePreset === preset.id && <Check className="w-3 h-3 flex-shrink-0" />}
              </button>
            ))}
          </div>
        </div>

        {/* 输入区域（透明毛玻璃：紫色光晕 + 玻璃内流动的激光能量流） */}
        <div className="relative">
          {/* LaserFlow 激光能量流（输入框背后，透过毛玻璃可见） */}
          <div className="absolute inset-0 z-0 overflow-hidden opacity-35">
            <LaserFlow
              color="#CF9EFF"
              horizontalBeamOffset={0.1}
              verticalBeamOffset={0}
              wispDensity={0.7}
              wispSpeed={8}
              wispIntensity={2.5}
              flowSpeed={0.35}
              flowStrength={0.25}
              fogIntensity={0.25}
              fogScale={0.3}
              fogFallSpeed={0.6}
              decay={1.1}
              falloffStart={1.2}
              horizontalSizing={0.5}
              verticalSizing={2}
            />
          </div>
          <div className="relative z-[1] mb-6">
            <BorderGlow
              edgeSensitivity={30}
              glowColor="40 80 80"
              backgroundColor="#f7f5ff"
              borderRadius={28}
              glowRadius={40}
              glowIntensity={1}
              coneSpread={25}
              animated={false}
              colors={['#c084fc', '#f472b6', '#38bdf8']}
              className="lilo-border-glass"
            >
          <div className="lilo-composer p-5">
          <textarea
            value={idea}
            onChange={e => setIdea(e.target.value)}
            placeholder="描述你的想法，输入一段故事、一个画面或一句灵感……"
            className="lilo-prompt-input w-full bg-transparent text-sm text-gray-800 placeholder-gray-400 resize-none outline-none min-h-[100px]"
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey && (idea.trim() || uploadedFile)) {
                e.preventDefault();
                handleStart(false);
              }
            }}
          />



          <div className="lilo-composer-toolbar flex items-center justify-between mt-3 pt-3 border-t border-gray-200">
            {/* 左侧：低频操作。技术参数收进「高级设置」，默认不展开。 */}
            <div className="flex items-center gap-2">
              <input
                type="file"
                ref={fileInputRef}
                onChange={handleFileUpload}
                accept=".doc,.docx,.txt,.md,.pdf"
                className="hidden"
              />
              <button
                onClick={() => {
                  if (uploadedFile) {
                    setUploadedFile(null);
                  } else {
                    fileInputRef.current?.click();
                  }
                }}
                disabled={uploading}
                className={clsx(
                  'lilo-tool-button flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all active:scale-95',
                  uploading
                    ? 'text-gray-500 cursor-not-allowed'
                    : uploadedFile
                    ? 'bg-violet-50 text-violet-600'
                    : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                )}
                title={uploadedFile ? `已选择: ${uploadedFile.name} (点击取消)` : "上传文档 (Word/TXT/MD/PDF)"}
              >
                {uploading ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : uploadedFile ? (
                  <CheckCircle className="w-3.5 h-3.5" />
                ) : null}
                {uploading
                  ? '上传中……'
                  : uploadedFile
                  ? `${uploadedFile.name.length > 8 ? `${uploadedFile.name.substring(0, 8)}…` : uploadedFile.name}`
                  : '上传文档'}
              </button>

              <button
                onClick={() => setShowSettings(!showSettings)}
                className={clsx(
                  'lilo-tool-button flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
                  showSettings
                    ? 'bg-violet-50 text-violet-600'
                    : 'text-gray-400 hover:text-gray-600 hover:bg-gray-50'
                )}
                aria-expanded={showSettings}
              >
                <Settings2 className="w-3.5 h-3.5" />
                高级设置
              </button>
            </div>

            {/* 右侧：主次操作。主操作唯一，其余降级为文字按钮。 */}
            <div className="flex items-center gap-3">
              <button
                onClick={() => handleStart(true)}
                disabled={!canStart}
                className="flex items-center justify-center gap-1.5 h-12 px-5 rounded-[15px] bg-white border border-violet-200 text-violet-600 text-sm font-medium transition-all hover:bg-violet-50 hover:border-violet-300 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-white disabled:hover:border-violet-200"
                title="自动执行全部六个阶段，无需手动确认"
              >
                <Sparkles className="w-4 h-4" />
                一键生成
              </button>
              <button
                onClick={() => handleStart(false)}
                disabled={!canStart}
                className="cssbuttons-io-button"
              >
                开始创作
                <span className="icon">
                  <ArrowRight strokeWidth={2.5} />
                </span>
              </button>
            </div>
          </div>
          {(configLoading || configError) && (
            <div className={clsx('mt-3 text-xs', configError ? 'text-red-500' : 'text-gray-400')}>
              {configError || '正在读取默认模型……'}
            </div>
          )}

          {/* 高级设置：技术参数默认折叠，不给首次使用者制造决策负担 */}
          {showSettings && (
            <div className="lilo-generation-panel mt-4 p-4 bg-white/70 backdrop-blur-sm rounded-2xl border border-violet-100 space-y-4 text-xs">
              <div className="flex items-center justify-between pb-1">
                <span className="text-sm font-semibold text-gray-800">高级设置</span>
                <span className="text-[10px] text-gray-400">按需调整 · 默认值即可正常创作</span>
              </div>
              <div className="text-[11px] font-semibold text-violet-500 tracking-wide">创作</div>
              {/* 篇幅：只影响内容长度，用创作者语言表述 */}
              <div className="flex flex-col gap-2 pb-3 border-b border-gray-200">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-gray-700">篇幅</span>
                  <span className="text-[11px] text-gray-400">决定内容长度，集数越多耗时越长</span>
                </div>
                <div className="flex items-center gap-3">
                  <button
                    onClick={() => setEpisodes(Math.max(1, episodes - 1))}
                    className="w-7 h-7 flex items-center justify-center rounded-lg bg-gray-100 text-gray-600 hover:bg-gray-200 active:scale-95 transition-all text-sm font-bold"
                    aria-label="减少集数"
                  >
                    -
                  </button>
                  <input
                    type="range"
                    min={1}
                    max={10}
                    value={episodes}
                    onChange={(e) => setEpisodes(parseInt(e.target.value))}
                    className="flex-1 h-1.5 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-violet-500"
                    aria-label="总集数"
                  />
                  <button
                    onClick={() => setEpisodes(Math.min(10, episodes + 1))}
                    className="w-7 h-7 flex items-center justify-center rounded-lg bg-gray-100 text-gray-600 hover:bg-gray-200 active:scale-95 transition-all text-sm font-bold"
                    aria-label="增加集数"
                  >
                    +
                  </button>
                  <span className="w-12 text-right font-semibold text-gray-700">{episodes} 集</span>
                </div>
              </div>

              {/* 联网搜索 */}
              <div className="flex items-center justify-between px-1 py-0.5">
                <span className="flex items-center gap-2 text-gray-600">
                  <Globe className="w-3.5 h-3.5 text-violet-500" />
                  联网搜索
                </span>
                <button
                  onClick={() => setWebSearch(!webSearch)}
                  role="switch"
                  aria-checked={webSearch}
                  className={`relative w-9 h-5 rounded-full transition-colors active:scale-95 ${
                    webSearch ? 'bg-violet-500' : 'bg-gray-300'
                  }`}
                >
                  <span
                    className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${
                      webSearch ? 'translate-x-4' : ''
                    }`}
                  />
                </button>
              </div>
              <div className="flex flex-col gap-1.5">
                <span className="text-gray-500 font-medium">风格</span>
                <div className="grid grid-cols-2 gap-1.5">
                  {STYLES.map(s => (
                    <button
                      key={s.id}
                      onClick={() => setSelectedStyle(s.id)}
                      className={`flex items-center gap-1.5 px-2 py-1.5 rounded-lg border text-[11px] font-medium transition-all active:scale-95 ${
                        selectedStyle === s.id
                          ? 'border-violet-400 bg-violet-50 text-violet-700'
                          : 'border-gray-200 bg-white text-gray-600 hover:border-violet-300'
                      }`}
                    >
                      <span
                        className="w-2 h-2 rounded-full flex-shrink-0"
                        style={{ backgroundColor: STYLE_COLORS[s.id] || '#a78bfa' }}
                      />
                      {s.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="text-[11px] font-semibold text-violet-500 tracking-wide border-t border-gray-200/70 pt-4">画面</div>
              <div className="grid grid-cols-2 gap-3">
                <label className="flex flex-col gap-1.5">
                  <span className="text-gray-500 font-medium">视频分辨率</span>
                  <div className="flex gap-1.5">
                    {VIDEO_RESOLUTIONS.map(item => (
                      <button
                        key={item.id}
                        onClick={() => setSelectedResolution(item.id)}
                        className={`flex-1 px-2 py-2 rounded-lg border text-xs font-medium transition-all active:scale-95 ${
                          selectedResolution === item.id
                            ? 'border-violet-400 bg-violet-50 text-violet-700'
                            : 'border-gray-200 bg-white text-gray-600 hover:border-violet-300'
                        }`}
                      >
                        {item.label}
                      </button>
                    ))}
                  </div>
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-gray-500 font-medium">视频长宽比</span>
                  <div className="flex gap-1">
                    {VIDEO_RATIOS.map(r => (
                      <button
                        key={r.id}
                        onClick={() => setSelectedRatio(r.id)}
                        className={`flex flex-col items-center gap-1 p-2 rounded-lg border transition-all ${
                          selectedRatio === r.id
                            ? 'border-violet-400 bg-violet-50'
                            : 'border-gray-200 hover:border-gray-300'
                        }`}
                        title={r.label}
                      >
                        <div
                          className="bg-gray-700 rounded-sm"
                          style={{
                            width: r.ratio === '16:9' ? '32px' :
                                   r.ratio === '9:16' ? '18px' :
                                   r.ratio === '1:1' ? '24px' :
                                   r.ratio === '4:3' ? '28px' :
                                   r.ratio === '3:4' ? '20px' :
                                   '36px',
                            height: r.ratio === '16:9' ? '18px' :
                                   r.ratio === '9:16' ? '32px' :
                                   r.ratio === '1:1' ? '24px' :
                                   r.ratio === '4:3' ? '21px' :
                                   r.ratio === '3:4' ? '28px' :
                                   '15px',
                          }}
                        />
                        <span className="text-[10px] text-gray-500">{r.label}</span>
                      </button>
                    ))}
                  </div>
                </label>
              </div>

              <div className="border-t border-gray-200/70 pt-4">
                <button
                  onClick={() => setShowModels(!showModels)}
                  className="w-full flex items-center justify-between px-3 py-2.5 rounded-xl bg-gray-50 border border-gray-200 hover:border-violet-300 transition-all active:scale-[0.99]"
                  aria-expanded={showModels}
                >
                  <span className="flex items-center gap-2">
                    <Cpu className="w-4 h-4 text-violet-500" />
                    <span className="text-xs font-semibold text-gray-700">模型配置</span>
                    <span className="text-[10px] text-gray-400">已按默认选择 · 一般无需修改</span>
                  </span>
                  <ChevronDown
                    className={`w-4 h-4 text-gray-400 transition-transform ${showModels ? 'rotate-180' : ''}`}
                  />
                </button>
                {showModels && (
                <div className="grid grid-cols-2 gap-3 mt-3">
                <label className="flex flex-col gap-1">
                  <span className="text-gray-500 font-medium">LLM 模型</span>
                  <select
                    value={selectedLLM}
                    onChange={e => setSelectedLLM(e.target.value)}
                    className="bg-white border border-gray-200 rounded-lg px-2.5 py-2 text-gray-700 outline-none"
                  >
                    {llmProviders.map(pg => (
                      <optgroup key={pg.provider} label={pg.label}>
                        {pg.models.map(m => (
                          <option key={m.id} value={m.id}>{m.label}</option>
                        ))}
                      </optgroup>
                    ))}
                  </select>
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-gray-500 font-medium">VLM 评估模型</span>
                  <select
                    value={selectedVLM}
                    onChange={e => setSelectedVLM(e.target.value)}
                    className="bg-white border border-gray-200 rounded-lg px-2.5 py-2 text-gray-700 outline-none"
                  >
                    {vlmProviders.map(pg => (
                      <optgroup key={pg.provider} label={pg.label}>
                        {pg.models.map(m => (
                          <option key={m.id} value={m.id}>{m.label}</option>
                        ))}
                      </optgroup>
                    ))}
                  </select>
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-gray-500 font-medium">文生图</span>
                  <select
                    value={selectedT2I}
                    onChange={e => setSelectedT2I(e.target.value)}
                    className="bg-white border border-gray-200 rounded-lg px-2.5 py-2 text-gray-700 outline-none"
                  >
                    {t2iProviders.map(pg => (
                      <optgroup key={pg.provider} label={pg.label}>
                        {pg.models.map(m => (
                          <option key={m.id} value={m.id}>{m.label}</option>
                        ))}
                      </optgroup>
                    ))}
                  </select>
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-gray-500 font-medium">图生图</span>
                  <select
                    value={selectedI2I}
                    onChange={e => setSelectedI2I(e.target.value)}
                    className="bg-white border border-gray-200 rounded-lg px-2.5 py-2 text-gray-700 outline-none"
                  >
                    {i2iProviders.map(pg => (
                      <optgroup key={pg.provider} label={pg.label}>
                        {pg.models.map(m => (
                          <option key={m.id} value={m.id}>{m.label}</option>
                        ))}
                      </optgroup>
                    ))}
                  </select>
                </label>
                <label className="flex flex-col gap-1 col-span-2">
                  <span className="text-gray-500 font-medium">视频生成方式</span>
                  <select
                    value={selectedVideoMode}
                    onChange={e => setSelectedVideoMode(e.target.value as VideoGenerationMode)}
                    className="bg-white border border-gray-200 rounded-lg px-2.5 py-2 text-gray-700 outline-none"
                  >
                    {VIDEO_GENERATION_MODES.map(item => (
                      <option key={item.id} value={item.id}>{item.label}</option>
                    ))}
                  </select>
                </label>
                <label className="flex flex-col gap-1 col-span-2">
                  <span className="text-gray-500 font-medium">{selectedVideoModeLabel}模型</span>
                  <select
                    value={activeVideoModel}
                    onChange={e => setActiveVideoModel(e.target.value)}
                    className="bg-white border border-gray-200 rounded-lg px-2.5 py-2 text-gray-700 outline-none"
                  >
                    {activeVideoProviders.map(pg => (
                      <optgroup key={pg.provider} label={pg.label}>
                        {pg.models.map(m => (
                          <option key={m.id} value={m.id}>{m.label}</option>
                        ))}
                      </optgroup>
                    ))}
                  </select>
                </label>
                <label className="flex items-center gap-2 text-sm cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={enableConcurrency}
                    onChange={e => setEnableConcurrency(e.target.checked)}
                    className="w-4 h-4 rounded border-gray-300 text-blue-500 focus:ring-blue-500/30"
                  />
                  <span className="text-gray-600">并发生成</span>
                </label>
                </div>
                )}
              </div>

              {/* 生成前报价：所选视频模型的 5 秒档位参考价 */}
              <div className="border-t border-gray-200/70 pt-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-gray-500 font-semibold">生成前报价</span>
                  <span className="text-[10px] text-gray-400">5 秒样片基准价 · 未计入其他阶段</span>
                </div>
                {skuLoading ? (
                  <div className="text-xs text-gray-400 flex items-center gap-1.5 py-2">
                    <Loader2 className="w-3.5 h-3.5 animate-spin" /> 正在查询档位价格…
                  </div>
                ) : skuData && skuData.items.length > 0 ? (() => {
                  const matched = skuData.items.filter(sku => sku.model_id === activeVideoModel);
                  return matched.length > 0 ? (
                  <div className="space-y-1.5">
                    {matched.map(sku => (
                      <div
                        key={sku.key}
                        className="flex items-center justify-between px-3 py-2 rounded-lg bg-white border border-gray-200/80"
                      >
                        <div className="min-w-0">
                          <div className="text-xs font-medium text-gray-700 truncate">
                            {sku.display} · {sku.label}
                          </div>
                          <div className="text-[10px] text-gray-400">
                            {sku.verified ? `成本 ¥${sku.cost}` : '价格未核实'} · 实付 ¥{sku.revenue}
                          </div>
                        </div>
                        <div className="flex-shrink-0 ml-2 text-xs font-semibold text-violet-600 tabular-nums">
                          {sku.credits} 积分
                        </div>
                      </div>
                    ))}
                  </div>
                  ) : (
                    <div className="text-xs text-gray-400 py-2">该模型暂无可售档位或未登记定价</div>
                  );
                })() : (
                  <div className="text-xs text-gray-400 py-2">
                    {activeVideoModel ? '该模型暂无可售档位或未登记定价' : '选择视频模型后显示参考价'}
                  </div>
                )}
              </div>
            </div>
          )}
          </div>
            </BorderGlow>

          {/* 即梦式参数条：视频模式 / 模型 / 比例 / 分辨率 */}
          <div className="lilo-param-bar flex flex-wrap items-center gap-2 mt-3">
          {/* 视频模式切换 */}
          <div className="flex items-center gap-0.5 p-0.5 rounded-lg bg-white/60 border border-violet-100">
          {VIDEO_GENERATION_MODES.map(mode => {
          const modeActive = selectedVideoMode === mode.id;
          return (
          <button
          key={mode.id}
          onClick={() => { setSelectedVideoMode(mode.id); setModelPopOpen(false); }}
          className={`px-2 py-1 rounded-md text-[11px] font-medium transition-all ${
          modeActive ? 'bg-violet-500 text-white shadow-sm' : 'text-gray-500 hover:text-violet-600'
          }`}
          title={mode.label}
          >
          {mode.label}
          </button>
          );
          })}
          </div>

          {/* 模型选择（即梦式：按钮显示当前模型，弹层选模型） */}
          <div className="relative" ref={modelPopRef}>
          <button
          onClick={() => { setRatioPopOpen(false); setModelPopOpen(v => !v); }}
          className="lilo-param-chip flex items-center gap-1.5"
          title="选择视频生成模型"
          >
          <Sparkles className="w-3 h-3 text-violet-500 shrink-0" />
          <span className="max-w-[160px] truncate">{displayModelLabel(activeVideoModelLabel || activeVideoModel) || '选择模型'}</span>
          <ChevronDown className={`w-3 h-3 shrink-0 transition-transform ${modelPopOpen ? 'rotate-180' : ''}`} />
          </button>
          {modelPopOpen && (
          <div className="lilo-param-popover">
          {activeVideoProviders.length === 0 && (
          <div className="px-2 py-3 text-xs text-gray-400">模型加载中…</div>
          )}
          {activeVideoProviders.flatMap(group => group.models).map(m => {
          const modelActive = m.id === activeVideoModel;
          return (
          <button
          key={m.id}
          onClick={() => { setActiveVideoModel(m.id); setModelPopOpen(false); }}
          className={`lilo-model-item flex items-center justify-between gap-2 ${modelActive ? 'active' : ''}`}
          >
          <span className="truncate">{displayModelLabel(m.label)}</span>
          <span className="flex items-center gap-1.5 shrink-0">
          {m.default && <span className="text-[10px] bg-violet-100 text-violet-600 px-1.5 py-0.5 rounded">推荐</span>}
          {modelActive && <Check className="w-3.5 h-3.5 text-violet-500" />}
          </span>
          </button>
          );
          })}
          </div>
          )}
          </div>

          {/* 比例选择（弹层 6 宫格） */}
          <div className="relative" ref={ratioPopRef}>
          <button
          onClick={() => { setModelPopOpen(false); setRatioPopOpen(v => !v); }}
          className="lilo-param-chip flex items-center gap-1.5"
          title="选择视频长宽比"
          >
          <span className="w-3 h-3 rounded-[2px] border border-violet-400 inline-block shrink-0" />
          <span>{selectedRatio || '比例'}</span>
          <ChevronDown className={`w-3 h-3 shrink-0 transition-transform ${ratioPopOpen ? 'rotate-180' : ''}`} />
          </button>
          {ratioPopOpen && (
          <div className="lilo-param-popover">
          <div className="lilo-popover-group-title">视频长宽比</div>
          <div className="grid grid-cols-3 gap-1.5 p-2">
          {VIDEO_RATIOS.map(r => {
          const ratioActive = selectedRatio === r.id;
          return (
          <button
          key={r.id}
          onClick={() => { setSelectedRatio(r.id); setRatioPopOpen(false); }}
          className={`lilo-ratio-item ${ratioActive ? 'active' : ''}`}
          >
          {r.id}
          </button>
          );
          })}
          </div>
          </div>
          )}
          </div>

          {/* 分辨率切换 */}
          <div className="flex items-center gap-0.5 p-0.5 rounded-lg bg-white/60 border border-violet-100">
          {VIDEO_RESOLUTIONS.map(item => {
          const resActive = selectedResolution === item.id;
          return (
          <button
          key={item.id}
          onClick={() => setSelectedResolution(item.id)}
          className={`px-2 py-1 rounded-md text-[11px] font-medium transition-all ${
          resActive ? 'bg-violet-500 text-white shadow-sm' : 'text-gray-500 hover:text-violet-600'
          }`}
          >
          {item.label}
          </button>
          );
          })}
          </div>

          </div>


                    </div>
        </div>

        {/* 示例卡片 */}
        <div className="lilo-inspiration mb-10">
          <h3 className="text-sm font-semibold text-gray-900 mb-3">
            灵感示例
          </h3>
          <div className="lilo-inspiration-grid grid grid-cols-2 md:grid-cols-3 gap-2.5">
            {PROMPT_EXAMPLES.map((ex, idx) => (
              <TiltCard key={idx}>
                <button
                  onClick={() => handleExampleClick(ex.text)}
                  className="lilo-inspiration-card text-left bg-white rounded-xl border border-gray-200 group"
                >
                  <div
                    className="lilo-inspiration-media"
                    style={{ backgroundImage: `url(${INSPIRATION_IMAGES[idx]})` }}
                  />
                  <div className="lilo-inspiration-copy">
                    <div className="text-sm font-medium text-gray-800 transition-colors mb-1">
                      {ex.title}
                    </div>
                    <div className="text-xs text-gray-500 line-clamp-2">
                      {ex.description}
                    </div>
                  </div>
                </button>
              </TiltCard>
            ))}
          </div>
        </div>
      </div>

      {/* 历史记录区域 */}
      {history.length > 0 && (
        <div className="lilo-history w-full max-w-6xl px-6 pb-12 flex-shrink-0">
          <div className="flex items-center gap-2 mb-4">
            <Clock className="w-4 h-4 text-gray-400" />
            <h3 className="text-sm font-medium text-gray-600">历史记录</h3>
            <button
              onClick={() => setManageMode(m => !m)}
              className={`ml-auto text-xs px-2 py-0.5 rounded transition-colors ${
                manageMode ? 'bg-red-100 text-red-600' : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
              }`}
            >
              {manageMode ? '完成' : '管理'}
            </button>
          </div>
          <div className="max-h-[60vh] overflow-y-auto pr-1">
            <div className="grid grid-cols-2 gap-3">
              {history.map(item => {
                const progress = stageProgressLabel(item.stages);
                return (
                <div key={item.id} className="relative group">
                  <div
                    onClick={() => !manageMode && onResumeProject(item.id)}
                    className={`lilo-history-card w-full text-left p-4 bg-white rounded-xl border border-gray-200 hover:shadow-sm transition-all ${!manageMode ? 'cursor-pointer' : ''}`}
                  >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-gray-700 group-hover:text-blue-600 transition-colors truncate">
                        {item.idea}
                      </div>
                      <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                        {item.style && (
                          <span className="text-[10px] bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded">
                            {item.style}
                          </span>
                        )}
                        <span className="text-[10px] text-gray-400">{item.date}</span>
                      </div>
                      <div className={`flex items-center gap-1 mt-1.5 text-[10px] font-medium ${progress.color}`}>
                        {item.stages && Object.keys(item.stages).filter(k => ["completed", "session_completed"].includes(item.stages![k])).length >= STAGES.length ? (
                          <CheckCircle className="w-3 h-3" />
                        ) : (
                          <span className="w-1.5 h-1.5 rounded-full bg-current flex-shrink-0" />
                        )}
                        <span>{progress.text}</span>
                      </div>
                    </div>
                    {manageMode ? (
                      <button
                        onClick={(e) => { e.stopPropagation(); setDeleteTarget(item.id); setDeleteError(''); }}
                        className="w-6 h-6 rounded-full bg-red-500 text-white flex items-center justify-center hover:bg-red-600 transition-colors flex-shrink-0 mt-0.5"
                        title="删除"
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    ) : (
                      <ArrowRight className="w-4 h-4 text-gray-300 group-hover:text-blue-400 transition-colors flex-shrink-0 mt-0.5" />
                    )}
                  </div>
                </div>
                </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* 删除确认弹窗 */}
      {deleteTarget && (
        <div className="lilo-dialog-scrim fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="lilo-delete-dialog bg-white rounded-2xl shadow-xl w-80 p-6 relative" role="dialog" aria-modal="true" aria-labelledby="delete-dialog-title">
            <div className="flex items-center gap-2 mb-4">
              <Trash2 className="w-4 h-4 text-red-500" />
              <h4 id="delete-dialog-title" className="text-sm font-semibold text-gray-700">删除项目</h4>
            </div>
            <p className="text-xs text-gray-500 mb-6">确认删除这个项目吗？此操作不可撤销。</p>
            {deleteError && <p className="text-xs text-red-500 mb-2">{deleteError}</p>}
            <div className="flex gap-2">
              <button
                onClick={() => { setDeleteTarget(null); setDeleteError(''); }}
                className="flex-1 text-sm py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50"
              >
                取消
              </button>
              <button
                onClick={handleDelete}
                disabled={deleting}
                className="flex-1 text-sm py-1.5 rounded-lg bg-red-500 text-white hover:bg-red-600 disabled:opacity-50"
              >
                {deleting ? '删除中…' : '确认删除'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
