import { useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, CSSProperties, DragEvent, FormEvent, KeyboardEvent as ReactKeyboardEvent, MouseEvent, TouchEvent, WheelEvent } from "react";
import {
  AlertTriangle,
  Archive,
  Check,
  ChevronLeft,
  ChevronRight,
  ClipboardCheck,
  ClipboardPaste,
  Download,
  ExternalLink,
  FileText,
  FolderOpen,
  HelpCircle,
  History,
  Loader2,
  Maximize2,
  RefreshCw,
  Save,
  Search,
  ShieldCheck,
  Sparkles,
  Trash2,
  Upload,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import {
  bulkUpdateFindings,
  clearMarkupMemory,
  createProject,
  createSampleProject,
  deleteFinding,
  deleteProject,
  deleteValidationProjects,
  exportProject,
  exportProjectPackage,
  getReadiness,
  getAIStatus,
  getApiErrorMessage,
  getMarkupMemorySettings,
  getMarkupMemoryStats,
  getManualAIPrompt,
  getManualReviewPlan,
  getProject,
  importProjectPackage,
  importManualAIPreview,
  listAIImportBatches,
  listFindingEvents,
  listFindings,
  listPromptTemplates,
  listProjects,
  listSheets,
  mergeFindingInto,
  previewMarkupMemoryContext,
  previewProjectPackageImport,
  previewImportBatchRollback,
  previewManualAIResponse,
  recalculateFindingPlacement,
  rebuildMarkupMemory,
  resolveAssetUrl,
  rollbackImportBatch,
  runAIReview,
  saveManualPlacement,
  saveAISettings,
  tagGeneratedValidationProjects,
  updateMarkupMemorySettings,
  updateFinding,
} from "./api";
import type {
  AIStatus,
  AIReviewResponse,
  AIImportBatch,
  AIPreviewResponse,
  BatchRollbackPreview,
  ExportResponse,
  Finding,
  FindingEvent,
  FindingStatus,
  FindingUpdate,
  ImportQualityReport,
  MarkupMemoryPreview,
  MarkupMemorySettings,
  MarkupMemorySettingsUpdate,
  MarkupMemoryStats,
  ManualReviewBatch,
  ManualReviewDeepDiveCandidate,
  ManualReviewPlan,
  PlacementSummary,
  ProjectPackageImportPreview,
  ReviewCoverageSummary,
  PromptTemplate,
  Project,
  ReadinessResponse,
  Severity,
  Sheet,
} from "./types";
import {
  CATEGORIES,
  SEVERITIES,
  STATUSES,
  confidenceLabel,
  countFindingsByStatus,
  extractBbox,
  formatDate,
  formatStatus,
  getFindingSheet,
  severityClass,
  sheetLabel,
  statusClass,
} from "./utils";

type StatusFilter = "all" | FindingStatus;
type PlacementFilter = "all" | "located" | "exact" | "fuzzy" | "page_level" | "manual" | "low_confidence";
type LeftRailCard = "review" | "projects" | "findings" | "export" | "advanced";
type PromptDepth = "fast" | "standard" | "comprehensive" | "exhaustive";
type LargePackageMode = "hybrid" | "package";
const PRIMARY_FINDING_STATUSES: FindingStatus[] = ["needs_review", "accepted", "rejected"];
type OperationStatus = "active" | "success" | "warning" | "error";
type WorkflowStepStatus = "done" | "ready" | "blocked" | "waiting";

interface OperationProgress {
  id: string;
  title: string;
  status: OperationStatus;
  steps: string[];
  currentStep: number;
  message: string;
  startedAt: number;
}

interface WorkflowStep {
  label: string;
  status: WorkflowStepStatus;
  detail: string;
  actionLabel?: string;
  onAction?: () => void;
}

interface RecoveryCard {
  id: string;
  severity: "warning" | "error" | "info";
  title: string;
  message: string;
  dataState: string;
  nextAction: string;
  actionLabel?: string;
  onAction?: () => void;
  secondaryLabel?: string;
  onSecondaryAction?: () => void;
}

const PRIMARY_WORKFLOW_CARDS: LeftRailCard[] = ["projects", "review", "findings", "export"];

interface ImageSize {
  width: number;
  height: number;
}

interface OverlayBoxPercent {
  left: number;
  top: number;
  width: number;
  height: number;
}

type ViewerMode = "focus" | "sheet" | "marked";

interface NoticeItem {
  title: string;
  detail: string;
}

interface FindingStatusUndo {
  findingId: string;
  title: string;
  previousStatus: FindingStatus;
  nextStatus: FindingStatus;
}

interface UploadAssessment {
  errors: string[];
  warnings: NoticeItem[];
}

interface AIResponseAssessment {
  blocking: string[];
  warnings: NoticeItem[];
  confirmations: string[];
}

const MAX_UPLOAD_MB = 250;
const LARGE_UPLOAD_WARNING_MB = 100;

function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [projectDetails, setProjectDetails] = useState<Project | null>(null);
  const [sheets, setSheets] = useState<Sheet[]>([]);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [events, setEvents] = useState<FindingEvent[]>([]);
  const [aiImportBatches, setAIImportBatches] = useState<AIImportBatch[]>([]);
  const [aiStatus, setAIStatus] = useState<AIStatus | null>(null);
  const [promptTemplates, setPromptTemplates] = useState<PromptTemplate[]>([]);
  const [selectedPromptTemplateId, setSelectedPromptTemplateId] = useState<string | null>(null);
  const [selectedPromptDepth, setSelectedPromptDepth] = useState<PromptDepth>("exhaustive");
  const [largePackageMode, setLargePackageMode] = useState<LargePackageMode>("hybrid");
  const [largePackageBatchSize, setLargePackageBatchSize] = useState(8);
  const [manualReviewPlan, setManualReviewPlan] = useState<ManualReviewPlan | null>(null);
  const [readiness, setReadiness] = useState<ReadinessResponse | null>(null);
  const [markupMemorySettings, setMarkupMemorySettings] = useState<MarkupMemorySettings | null>(null);
  const [markupMemoryStats, setMarkupMemoryStats] = useState<MarkupMemoryStats | null>(null);
  const [markupMemoryPreview, setMarkupMemoryPreview] = useState<MarkupMemoryPreview | null>(null);
  const [selectedSheetId, setSelectedSheetId] = useState<string | null>(null);
  const [selectedFindingId, setSelectedFindingId] = useState<string | null>(null);
  const [lastSelectedFindingId, setLastSelectedFindingId] = useState<string | null>(null);
  const [leftRailCard, setLeftRailCard] = useState<LeftRailCard>("projects");
  const [leftRailCollapsed, setLeftRailCollapsed] = useState(false);
  const [loadingProjects, setLoadingProjects] = useState(false);
  const [loadingReview, setLoadingReview] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [creatingSample, setCreatingSample] = useState(false);
  const [runningAIReview, setRunningAIReview] = useState(false);
  const [generatingManualPrompt, setGeneratingManualPrompt] = useState(false);
  const [importingManualAI, setImportingManualAI] = useState(false);
  const [manualAIPrompt, setManualAIPrompt] = useState<string | null>(null);
  const [manualAIPromptId, setManualAIPromptId] = useState<string | null>(null);
  const [manualAIPromptVersion, setManualAIPromptVersion] = useState<string | null>(null);
  const [manualAIResponse, setManualAIResponse] = useState("");
  const [manualAICopied, setManualAICopied] = useState(false);
  const [manualAIPreview, setManualAIPreview] = useState<AIPreviewResponse | null>(null);
  const [previewingManualAI, setPreviewingManualAI] = useState(false);
  const [manualAIImportMessage, setManualAIImportMessage] = useState<string | null>(null);
  const [missedIssueAuditPrompt, setMissedIssueAuditPrompt] = useState<string | null>(null);
  const [missedIssueAuditCopied, setMissedIssueAuditCopied] = useState(false);
  const [missedIssueAuditSourceBatchId, setMissedIssueAuditSourceBatchId] = useState<string | null>(null);
  const [missedIssueAuditSuggestedRound, setMissedIssueAuditSuggestedRound] = useState<number | null>(null);
  const [pendingMissedIssueAuditBatchId, setPendingMissedIssueAuditBatchId] = useState<string | null>(null);
  const [pendingMissedIssueAuditRound, setPendingMissedIssueAuditRound] = useState<number | null>(null);
  const [savingFindingId, setSavingFindingId] = useState<string | null>(null);
  const [deletingFindingId, setDeletingFindingId] = useState<string | null>(null);
  const [deletingProjectId, setDeletingProjectId] = useState<string | null>(null);
  const [exportingPackage, setExportingPackage] = useState(false);
  const [importingPackage, setImportingPackage] = useState(false);
  const [showValidationProjects, setShowValidationProjects] = useState(false);
  const [taggingValidationProjects, setTaggingValidationProjects] = useState(false);
  const [cleaningValidationProjects, setCleaningValidationProjects] = useState(false);
  const [rollingBackBatchId, setRollingBackBatchId] = useState<string | null>(null);
  const [mergingFindingId, setMergingFindingId] = useState<string | null>(null);
  const [activeMarkedPdfUrl, setActiveMarkedPdfUrl] = useState<string | null>(null);
  const [autoAdvanceReview, setAutoAdvanceReview] = useState(true);
  const [recalculatingPlacement, setRecalculatingPlacement] = useState(false);
  const [placementMessage, setPlacementMessage] = useState<string | null>(null);
  const [placementSummary, setPlacementSummary] = useState<PlacementSummary | null>(null);
  const [manualPlacementFindingId, setManualPlacementFindingId] = useState<string | null>(null);
  const [savingManualPlacement, setSavingManualPlacement] = useState(false);
  const [loadingMarkupMemory, setLoadingMarkupMemory] = useState(false);
  const [savingMarkupMemory, setSavingMarkupMemory] = useState(false);
  const [rebuildingMarkupMemory, setRebuildingMarkupMemory] = useState(false);
  const [clearingMarkupMemory, setClearingMarkupMemory] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [operation, setOperation] = useState<OperationProgress | null>(null);
  const [statusUndo, setStatusUndo] = useState<FindingStatusUndo | null>(null);

  const selectedProject =
    projectDetails ?? projects.find((project) => project.id === selectedProjectId) ?? null;
  const selectedSheet = sheets.find((sheet) => sheet.id === selectedSheetId) ?? null;
  const selectedFinding =
    findings.find((finding) => finding.id === selectedFindingId) ?? null;
  const selectedProjectSourcePdfUrl = resolveAssetUrl(
    selectedProject?.source_pdf_url ?? selectedProject?.source_pdf_path,
  );

  const findingsForSelectedSheet = useMemo(() => {
    if (!selectedSheet) {
      return [];
    }

    return findings.filter((finding) => findingMatchesSheet(finding, selectedSheet));
  }, [findings, selectedSheet]);
  const reviewQueueFindings = useMemo(
    () => findings.filter((finding) => finding.status === "needs_review"),
    [findings],
  );
  const reviewProgress = {
    total: findings.length,
    remaining: reviewQueueFindings.length,
    resolved: Math.max(0, findings.length - reviewQueueFindings.length),
  };
  const selectedPromptTemplate = promptTemplates.find((template) => template.id === selectedPromptTemplateId) ?? promptTemplates[0] ?? null;
  const manualAIResponseAssessment = useMemo(() => assessManualAIResponse(manualAIResponse), [manualAIResponse]);

  function startOperation(title: string, steps: string[], message = steps[0] ?? "Working") {
    setOperation({
      id: `${Date.now()}-${title}`,
      title,
      status: "active",
      steps,
      currentStep: 0,
      message,
      startedAt: Date.now(),
    });
  }

  function advanceOperation(currentStep: number, message?: string) {
    setOperation((current) => {
      if (!current) {
        return current;
      }
      const nextStep = clamp(currentStep, 0, Math.max(0, current.steps.length - 1));
      return {
        ...current,
        status: "active",
        currentStep: nextStep,
        message: message ?? current.steps[nextStep] ?? current.message,
      };
    });
  }

  function finishOperation(status: Exclude<OperationStatus, "active">, message: string) {
    setOperation((current) => current ? { ...current, status, currentStep: Math.max(0, current.steps.length - 1), message } : current);
  }

  function clearOperation() {
    setOperation(null);
  }

  useEffect(() => {
    void refreshProjects();
    void refreshAIStatus();
    void refreshPromptTemplates();
    void refreshReadiness();
  }, []);

  useEffect(() => {
    if (!selectedProjectId) {
      setProjectDetails(null);
      setSheets([]);
      setFindings([]);
      setEvents([]);
      setAIImportBatches([]);
      setManualReviewPlan(null);
      setSelectedSheetId(null);
      setSelectedFindingId(null);
      setManualAIImportMessage(null);
      setManualAIPreview(null);
      setMissedIssueAuditPrompt(null);
      setMissedIssueAuditCopied(false);
      setMissedIssueAuditSourceBatchId(null);
      setMissedIssueAuditSuggestedRound(null);
      setPendingMissedIssueAuditBatchId(null);
      setPendingMissedIssueAuditRound(null);
      setActiveMarkedPdfUrl(null);
      setPlacementMessage(null);
      setPlacementSummary(null);
      setManualPlacementFindingId(null);
      setMarkupMemoryPreview(null);
      return;
    }

    setManualAIImportMessage(null);
    setManualAIPreview(null);
    setMissedIssueAuditPrompt(null);
    setMissedIssueAuditCopied(false);
    setMissedIssueAuditSourceBatchId(null);
    setMissedIssueAuditSuggestedRound(null);
    setPendingMissedIssueAuditBatchId(null);
    setPendingMissedIssueAuditRound(null);
    setActiveMarkedPdfUrl(null);
    setPlacementMessage(null);
    setPlacementSummary(null);
    setManualPlacementFindingId(null);
    void refreshReview(selectedProjectId);
  }, [selectedProjectId]);

  useEffect(() => {
    void refreshProjects();
  }, [showValidationProjects]);

  useEffect(() => {
    if (leftRailCard === "advanced") {
      void refreshMarkupMemory();
    }
  }, [leftRailCard, selectedProjectId]);

  useEffect(() => {
    if (!selectedProjectId) {
      return;
    }
    void refreshManualReviewPlan(selectedProjectId);
  }, [largePackageBatchSize, selectedProjectId]);

  useEffect(() => {
    if (!selectedFinding) {
      return;
    }

    const sheet = getFindingSheet(selectedFinding, sheets);
    if (sheet) {
      setSelectedSheetId((current) => (current === sheet.id ? current : sheet.id));
    }
  }, [selectedFinding?.id, sheets]);

  async function refreshAIStatus() {
    try {
      setAIStatus(await getAIStatus());
    } catch {
      setAIStatus(null);
    }
  }

  async function promptForAIReviewSettings(): Promise<boolean> {
    const product = window.prompt(
      "AI product for Deep Review. Enter OpenAI or DeepSeek.",
      formatAIProvider(aiStatus?.provider),
    );
    if (product === null) {
      return false;
    }
    const provider = normalizeAIProvider(product);
    if (!provider) {
      setError("Choose OpenAI or DeepSeek before running AI Deep Review.");
      return false;
    }

    const model = window.prompt(
      `Model to use for ${formatAIProvider(provider)} AI Deep Review. Recommended strong models: ${strongAIModelExamples(provider)}.`,
      aiStatus?.provider === provider ? aiStatus?.model || defaultAIModelForProvider(provider) : defaultAIModelForProvider(provider),
    );
    if (model === null) {
      return false;
    }
    if (!model.trim()) {
      setError("Enter a model before running AI Deep Review.");
      return false;
    }

    const keyMessage = aiStatus?.api_key_saved && aiStatus.provider === provider
      ? `Saved ${formatAIProvider(provider)} key found. Leave blank to keep ${aiStatus.api_key_hint || "the saved key"}.`
      : `${formatAIProvider(provider)} key for AI Deep Review. Saved for this OS user only.`;
    const apiKey = window.prompt(keyMessage, "");
    if (apiKey === null) {
      return false;
    }
    if (!apiKey.trim() && !(aiStatus?.api_key_saved && aiStatus.provider === provider)) {
      setError(`Enter a ${formatAIProvider(provider)} key before running AI Deep Review.`);
      return false;
    }

    const savedStatus = await saveAISettings({
      api_key: apiKey.trim(),
      model: model.trim(),
      provider,
    });
    setAIStatus(savedStatus);
    return true;
  }

  async function refreshPromptTemplates() {
    try {
      const templates = await listPromptTemplates();
      setPromptTemplates(templates);
      setSelectedPromptTemplateId((current) => current ?? templates[0]?.id ?? null);
    } catch {
      setPromptTemplates([]);
    }
  }

  async function refreshReadiness() {
    try {
      setReadiness(await getReadiness());
    } catch {
      setReadiness(null);
    }
  }

  async function refreshManualReviewPlan(projectId = selectedProjectId) {
    if (!projectId) {
      setManualReviewPlan(null);
      return;
    }
    try {
      setManualReviewPlan(await getManualReviewPlan(projectId, largePackageBatchSize));
    } catch {
      setManualReviewPlan(null);
    }
  }

  async function refreshMarkupMemory(projectId = selectedProjectId) {
    setLoadingMarkupMemory(true);
    try {
      const [settings, stats, preview] = await Promise.all([
        getMarkupMemorySettings(),
        getMarkupMemoryStats(),
        projectId ? previewMarkupMemoryContext(projectId) : Promise.resolve(null),
      ]);
      setMarkupMemorySettings(settings);
      setMarkupMemoryStats(stats);
      setMarkupMemoryPreview(preview);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setLoadingMarkupMemory(false);
    }
  }

  async function handleUpdateMarkupMemorySettings(update: MarkupMemorySettingsUpdate) {
    setSavingMarkupMemory(true);
    setError(null);
    try {
      const settings = await updateMarkupMemorySettings(update);
      setMarkupMemorySettings(settings);
      setMarkupMemoryStats(await getMarkupMemoryStats());
      if (selectedProjectId) {
        setMarkupMemoryPreview(await previewMarkupMemoryContext(selectedProjectId));
      }
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setSavingMarkupMemory(false);
    }
  }

  async function handleRebuildMarkupMemory() {
    if (rebuildingMarkupMemory) {
      return;
    }
    setRebuildingMarkupMemory(true);
    setError(null);
    try {
      const result = await rebuildMarkupMemory();
      setMarkupMemoryStats(result.stats);
      if (selectedProjectId) {
        setMarkupMemoryPreview(await previewMarkupMemoryContext(selectedProjectId));
      }
      setManualAIImportMessage(`Markup Memory rebuilt from ${result.memory_examples_upserted} historical outcome${result.memory_examples_upserted === 1 ? "" : "s"}.`);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setRebuildingMarkupMemory(false);
    }
  }

  async function handleClearMarkupMemory() {
    if (clearingMarkupMemory) {
      return;
    }
    const confirmed = window.confirm("Clear Markup Memory? This removes learned local examples but does not delete projects, findings, or exports.");
    if (!confirmed) {
      return;
    }
    setClearingMarkupMemory(true);
    setError(null);
    try {
      const result = await clearMarkupMemory();
      setMarkupMemoryStats(result.stats);
      if (selectedProjectId) {
        setMarkupMemoryPreview(await previewMarkupMemoryContext(selectedProjectId));
      } else {
        setMarkupMemoryPreview(null);
      }
      setManualAIImportMessage(`Cleared ${result.deleted} Markup Memory example${result.deleted === 1 ? "" : "s"}.`);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setClearingMarkupMemory(false);
    }
  }

  async function refreshProjects() {
    setLoadingProjects(true);
    setError(null);

    try {
      const nextProjects = await listProjects(showValidationProjects);
      setProjects(nextProjects);
      setSelectedProjectId((current) => {
        if (current && nextProjects.some((project) => project.id === current)) {
          return current;
        }

        return nextProjects[0]?.id ?? null;
      });
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setLoadingProjects(false);
    }
  }

  async function refreshReview(projectId = selectedProjectId) {
    if (!projectId) {
      return;
    }

    setLoadingReview(true);
    setError(null);

    try {
      const [project, nextSheets, nextFindings, nextEvents, nextBatches, nextReviewPlan] = await Promise.all([
        getProject(projectId),
        listSheets(projectId),
        listFindings(projectId),
        listFindingEvents(projectId),
        listAIImportBatches(projectId),
        getManualReviewPlan(projectId, largePackageBatchSize).catch(() => null),
      ]);

      setProjectDetails(project);
      setSheets(nextSheets);
      setFindings(nextFindings);
      setEvents(nextEvents);
      setAIImportBatches(nextBatches);
      setManualReviewPlan(nextReviewPlan);
      setSelectedSheetId((current) => {
        if (current && nextSheets.some((sheet) => sheet.id === current)) {
          return current;
        }

        const findingSheet = nextFindings[0] ? getFindingSheet(nextFindings[0], nextSheets) : null;
        return findingSheet?.id ?? nextSheets[0]?.id ?? null;
      });
      setSelectedFindingId((current) => {
        if (current && nextFindings.some((finding) => finding.id === current)) {
          return current;
        }

        return nextFindings[0]?.id ?? null;
      });
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setLoadingReview(false);
    }
  }

  async function handleUpload(name: string, file: File) {
    setUploading(true);
    setError(null);
    setManualAIImportMessage(null);
    setManualAIPreview(null);
    startOperation("Upload and extract package", ["Validating PDF", "Extracting sheets", "Rendering page images", "Refreshing workspace"]);

    try {
      advanceOperation(0, "Validating the uploaded PDF and saving it into project storage.");
      const project = await createProject(name, file);
      advanceOperation(3, "Extraction finished. Refreshing the project workspace.");
      setSelectedProjectId(project.id);
      await refreshProjects();
      await refreshReview(project.id);
      finishOperation("success", "PDF package uploaded, extracted, and ready for Chat Prompt review.");
    } catch (requestError) {
      const message = getApiErrorMessage(requestError);
      setError(message);
      finishOperation("error", `Upload failed. ${message}`);
    } finally {
      setUploading(false);
    }
  }

  async function handleSampleProject() {
    setCreatingSample(true);
    setError(null);
    setManualAIImportMessage(null);
    setManualAIPreview(null);
    startOperation("Create sample project", ["Creating sample", "Extracting sheets", "Refreshing workspace"]);

    try {
      advanceOperation(0, "Creating the local sample project.");
      const project = await createSampleProject();
      advanceOperation(2, "Sample project created. Refreshing the workspace.");
      setSelectedProjectId(project.id);
      await refreshProjects();
      await refreshReview(project.id);
      finishOperation("success", "Sample project is ready for the manual AI workflow.");
    } catch (requestError) {
      const message = getApiErrorMessage(requestError);
      setError(message);
      finishOperation("error", `Sample project failed. ${message}`);
    } finally {
      setCreatingSample(false);
    }
  }

  async function handleDeleteProject(project: Project) {
    if (deletingProjectId) {
      return;
    }

    const confirmed = window.confirm(
      `Delete "${project.name}"? This removes the uploaded package, extracted sheets, AI findings, import history, exports, and stored files.`,
    );
    if (!confirmed) {
      return;
    }

    setDeletingProjectId(project.id);
    setError(null);

    try {
      await deleteProject(project.id);
      const nextProjects = projects.filter((candidate) => candidate.id !== project.id);
      setProjects(nextProjects);
      if (selectedProjectId === project.id) {
        setSelectedProjectId(nextProjects[0]?.id ?? null);
      }
      await refreshProjects();
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setDeletingProjectId(null);
    }
  }

  async function handleClearValidationProjects() {
    const confirmed = window.confirm(
      "Remove generated validation projects from the local AutoQC library? This deletes only projects marked as validation/test runs.",
    );
    if (!confirmed) {
      return;
    }

    setCleaningValidationProjects(true);
    setError(null);
    startOperation("Clean validation projects", ["Finding generated validation projects", "Deleting validation records", "Refreshing project library"]);

    try {
      advanceOperation(1, "Deleting generated validation project records and files.");
      const result = await deleteValidationProjects();
      advanceOperation(2, "Refreshing the project library.");
      await refreshProjects();
      setManualAIImportMessage(`Removed ${result.deleted_count} generated validation project${result.deleted_count === 1 ? "" : "s"}.`);
      finishOperation("success", `Removed ${result.deleted_count} generated validation project${result.deleted_count === 1 ? "" : "s"}.`);
    } catch (requestError) {
      const message = getApiErrorMessage(requestError);
      setError(message);
      finishOperation("error", `Validation cleanup failed. ${message}`);
    } finally {
      setCleaningValidationProjects(false);
    }
  }

  async function handleTagGeneratedValidationProjects() {
    const confirmed = window.confirm(
      "Tag historical smoke, stress, and real-PDF regression projects as generated validation runs? This does not delete any project files.",
    );
    if (!confirmed) {
      return;
    }

    setTaggingValidationProjects(true);
    setError(null);
    startOperation("Tag generated validation projects", ["Scanning project names", "Tagging generated runs", "Refreshing project library"]);

    try {
      advanceOperation(1, "Tagging known generated smoke, stress, and regression projects.");
      const result = await tagGeneratedValidationProjects(false);
      advanceOperation(2, "Refreshing the project library.");
      await refreshProjects();
      setManualAIImportMessage(`Tagged ${result.tagged_count} historical generated validation project${result.tagged_count === 1 ? "" : "s"}.`);
      finishOperation("success", `Tagged ${result.tagged_count} historical generated validation project${result.tagged_count === 1 ? "" : "s"}.`);
    } catch (requestError) {
      const message = getApiErrorMessage(requestError);
      setError(message);
      finishOperation("error", `Validation tagging failed. ${message}`);
    } finally {
      setTaggingValidationProjects(false);
    }
  }

  async function handleExportProjectPackage() {
    if (!selectedProjectId || exportingPackage) {
      return;
    }
    setExportingPackage(true);
    setError(null);
    startOperation("Export project package", ["Collecting project records", "Copying package files", "Writing checksum manifest", "Opening package download"]);
    try {
      advanceOperation(1, "Copying project files and export artifacts into a package.");
      const result = await exportProjectPackage(selectedProjectId);
      const url = resolveAssetUrl(result.download_url) ?? result.download_url;
      window.open(url, "_blank", "noopener,noreferrer");
      setManualAIImportMessage(`Project package exported: ${result.filename}`);
      advanceOperation(3, "Package created. Refreshing audit activity.");
      await refreshReview(selectedProjectId);
      finishOperation("success", `Project package exported: ${result.filename}`);
    } catch (requestError) {
      const message = getApiErrorMessage(requestError);
      setError(message);
      finishOperation("error", `Project package export failed. ${message}`);
    } finally {
      setExportingPackage(false);
    }
  }

  async function handleImportProjectPackage(file: File | null) {
    if (!file || importingPackage) {
      return;
    }
    setImportingPackage(true);
    setError(null);
    startOperation("Import project package", ["Validating zip", "Previewing restore", "Confirming restore", "Refreshing workspace"]);
    try {
      advanceOperation(0, "Validating package structure, paths, files, and manifest before restore.");
      const preview = await previewProjectPackageImport(file);
      if (!preview.valid) {
        const message = `Project package preview failed: ${(preview.errors ?? []).join(" ") || "Package did not pass validation."}`;
        setError(message);
        finishOperation("error", `${message} No project records were restored.`);
        return;
      }
      advanceOperation(1, "Package preview passed. Waiting for reviewer confirmation.");
      const confirmed = window.confirm(projectPackagePreviewMessage(preview));
      if (!confirmed) {
        finishOperation("warning", "Package import was cancelled before restore. No project records were changed.");
        return;
      }
      advanceOperation(2, "Restoring project records and files from the validated package.");
      const result = await importProjectPackage(file);
      setSelectedProjectId(result.restored_project_id);
      setManualAIImportMessage(
        result.remapped_ids
          ? "Project package imported with remapped IDs to avoid overwriting an existing project."
          : "Project package imported.",
      );
      advanceOperation(3, "Package restored. Refreshing the workspace.");
      await refreshProjects();
      await refreshReview(result.restored_project_id);
      finishOperation("success", result.remapped_ids ? "Project package imported with remapped IDs." : "Project package imported.");
    } catch (requestError) {
      const message = getApiErrorMessage(requestError);
      setError(message);
      finishOperation("error", `Package import failed. ${message}`);
    } finally {
      setImportingPackage(false);
    }
  }

  async function handleRunAIReview() {
    if (!selectedProjectId || runningAIReview) {
      return;
    }
    const directConfirmed = window.confirm(
      "Direct AI Review is experimental and uses extracted text context only. It is not equivalent to the manual Chat Prompt workflow with the actual PDF attached. Continue?",
    );
    if (!directConfirmed) {
      return;
    }
    setError(null);
    startOperation("Direct AI Review", ["Confirming AI settings", "Sending text context", "Checking coverage gates", "Refreshing findings"], "Checking Direct AI settings.");
    try {
      const settingsReady = await promptForAIReviewSettings();
      if (!settingsReady) {
        finishOperation("warning", "Direct AI Review was cancelled before any text context was sent.");
        return;
      }
      setRunningAIReview(true);
      advanceOperation(1, "Sending extracted text context only. This is not the PDF-attached workflow.");
      const result = await runAIReview(selectedProjectId);
      advanceOperation(2, "Direct AI response passed coverage and quality gates.");
      setProjectDetails(result.project);
      setFindings(result.findings);
      setSelectedFindingId(result.findings[0]?.id ?? null);
      await refreshReview(selectedProjectId);
      finishOperation("success", "Direct AI Review imported through the same coverage gates. Verify findings against the source PDF.");
    } catch (requestError) {
      const message = getApiErrorMessage(requestError);
      setError(message);
      finishOperation("error", `Direct AI Review failed. ${message}`);
    } finally {
      setRunningAIReview(false);
    }
  }

  function projectPackagePreviewMessage(preview: ProjectPackageImportPreview): string {
    const warnings = preview.warnings?.length ? `\nWarnings: ${preview.warnings.slice(0, 3).join(" ")}` : "";
    const remap = preview.remapped_ids
      ? "\nIDs will be remapped because the original project already exists."
      : "\nIDs can be restored without remapping.";
    const sourcePdf = preview.source_pdf_included
      ? `\nSource PDF: ${preview.source_pdf_valid ? "included and valid" : "included but not valid"}`
      : "\nSource PDF: not included";
    return [
      `Import AutoQC project package "${preview.project_name ?? "Unnamed project"}"?`,
      `Sheets: ${preview.sheet_count}`,
      `Findings: ${preview.finding_count}`,
      `AI import batches: ${preview.import_batches_count}`,
      `Export records: ${preview.export_record_count ?? 0}`,
      `Export artifact files: ${preview.export_artifact_count}`,
      remap,
      sourcePdf,
      warnings,
    ].join("\n");
  }

  async function handleGenerateManualAIPrompt(options: {
    reviewScope?: "package" | "batch" | "sheet";
    pageNumber?: number | null;
    pageNumbers?: number[] | null;
    message?: string;
  } = {}) {
    if (!selectedProjectId || generatingManualPrompt) {
      return;
    }
    setGeneratingManualPrompt(true);
    setManualAICopied(false);
    setError(null);
    setManualAIImportMessage(null);
    setManualAIPreview(null);
    setMissedIssueAuditPrompt(null);
    setMissedIssueAuditCopied(false);
    setMissedIssueAuditSourceBatchId(null);
    setMissedIssueAuditSuggestedRound(null);
    setPendingMissedIssueAuditBatchId(null);
    setPendingMissedIssueAuditRound(null);
    startOperation("Generate Chat Prompt", ["Selecting review scope", "Building prompt context", "Copying prompt"], "Selecting the next review scope.");
    try {
      const scopeOptions =
        options.reviewScope
          ? {
              reviewScope: options.reviewScope,
              pageNumber: options.pageNumber ?? undefined,
              pageNumbers: options.pageNumbers ?? undefined,
              batchSize: largePackageBatchSize,
            }
          : defaultManualPromptScopeOptions();
      advanceOperation(1, "Building prompt context from extracted sheets, metadata, and review coverage.");
      const result = await getManualAIPrompt(selectedProjectId, selectedPromptTemplateId, selectedPromptDepth, scopeOptions);
      if (!result.prompt?.trim()) {
        throw new Error("Manual AI prompt response was empty. Refresh the project and try again.");
      }
      setManualAIPrompt(result.prompt);
      setManualAIPromptId(result.prompt_id ?? null);
      setManualAIPromptVersion(result.prompt_version ?? null);
      setManualReviewPlan(result.review_plan ?? manualReviewPlan);
      setManualAIResponse("");
      setLeftRailCard("review");
      try {
        await navigator.clipboard.writeText(result.prompt);
        setManualAICopied(true);
        setManualAIImportMessage(options.message ?? promptCopiedMessage(result.prompt_metadata));
        finishOperation("success", "Prompt generated and copied. Attach the source PDF in ChatGPT/Copilot before running it.");
      } catch {
        setManualAICopied(false);
        finishOperation("warning", "Prompt generated. Copy it manually, then attach the source PDF in ChatGPT/Copilot.");
      }
    } catch (requestError) {
      const message = getApiErrorMessage(requestError);
      setError(message);
      finishOperation("error", `Prompt generation failed. ${message}`);
    } finally {
      setGeneratingManualPrompt(false);
    }
  }

  function defaultManualPromptScopeOptions() {
    if (largePackageMode !== "hybrid" || sheets.length <= 1) {
      return { reviewScope: "package" as const, batchSize: largePackageBatchSize };
    }
    const nextBatch = nextUnreviewedBatch(manualReviewPlan);
    return {
      reviewScope: "batch" as const,
      pageNumbers: nextBatch?.page_numbers ?? sheets.slice(0, largePackageBatchSize).map((sheet) => sheet.page_number),
      batchSize: largePackageBatchSize,
    };
  }

  function promptCopiedMessage(metadata?: Record<string, unknown>): string {
    const scope = String(metadata?.review_scope ?? "");
    const label = typeof metadata?.scope_label === "string" ? metadata.scope_label : "";
    if (scope === "batch") {
      return `Batch prompt copied for ${label || "selected pages"}. Attach the PDF in ChatGPT/Copilot, run the prompt, then paste the JSON.`;
    }
    if (scope === "sheet") {
      return `Single-sheet deep dive prompt copied for ${label || "the selected sheet"}. Attach the PDF, run the prompt, then paste the JSON.`;
    }
    return "Prompt copied. Open ChatGPT or Copilot, attach the PDF, and paste/run the prompt.";
  }

  function handleGenerateNextBatchPrompt() {
    const batch = nextUnreviewedBatch(manualReviewPlan);
    const pageNumbers = batch?.page_numbers ?? sheets.slice(0, largePackageBatchSize).map((sheet) => sheet.page_number);
    void handleGenerateManualAIPrompt({
      reviewScope: "batch",
      pageNumbers,
      message: `Next batch prompt copied for ${batch?.label ?? "selected pages"}.`,
    });
  }

  function handleDeepDiveSheet(sheet: Sheet | null = selectedSheet) {
    if (!sheet) {
      return;
    }
    void handleGenerateManualAIPrompt({
      reviewScope: "sheet",
      pageNumber: sheet.page_number,
      message: `Deep-dive prompt copied for Page ${sheet.page_number}.`,
    });
  }

  async function handleCopyManualAIPrompt() {
    if (!manualAIPrompt) {
      return;
    }
    try {
      await navigator.clipboard.writeText(manualAIPrompt);
      setManualAICopied(true);
    } catch {
      setManualAICopied(false);
    }
  }

  async function handleOpenManualAI(target: "chatgpt" | "copilot") {
    if (manualAIPrompt) {
      try {
        await navigator.clipboard.writeText(manualAIPrompt);
        setManualAICopied(true);
      } catch {
        setManualAICopied(false);
      }
    }

    const url = target === "chatgpt" ? "https://chatgpt.com/" : "https://copilot.microsoft.com/";
    window.open(url, "_blank", "noopener,noreferrer");
  }

  async function handlePasteManualAIResponse() {
    try {
      const text = await navigator.clipboard.readText();
      setManualAIResponse(text);
      setManualAIPreview(null);
      setMissedIssueAuditPrompt(null);
      setMissedIssueAuditCopied(false);
      setManualAIImportMessage(text.trim() ? "Pasted AI response from clipboard." : "Clipboard was empty.");
    } catch {
      setError("Could not read from clipboard. Paste the AI JSON manually or import a .json/.txt file.");
    }
  }

  async function handleManualAIResponseFile(file: File | null) {
    if (!file) {
      return;
    }

    try {
      const text = await file.text();
      setManualAIResponse(text);
      setManualAIPreview(null);
      setMissedIssueAuditPrompt(null);
      setMissedIssueAuditCopied(false);
      setManualAIImportMessage(`Loaded AI response from ${file.name}.`);
    } catch {
      setError(`Could not read ${file.name}. Paste the AI JSON manually instead.`);
    }
  }

  function handleManualAIDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    void handleManualAIResponseFile(event.dataTransfer.files?.[0] ?? null);
  }

  function handleManualAIFileInput(event: ChangeEvent<HTMLInputElement>) {
    void handleManualAIResponseFile(event.target.files?.[0] ?? null);
    event.target.value = "";
  }

  async function handlePreviewManualAIResponse() {
    if (!selectedProjectId || !manualAIResponse.trim() || previewingManualAI) {
      return;
    }
    const blockingIssue = manualAIResponseAssessment.blocking[0];
    if (blockingIssue) {
      setError(blockingIssue);
      return;
    }
    setPreviewingManualAI(true);
    setError(null);
    setManualAIImportMessage(null);
    startOperation("Preview AI response", ["Parsing pasted response", "Checking reviewed_pages coverage", "Checking duplicates and placement"], "Parsing the pasted ChatGPT/Copilot response.");
    try {
      const sourceType = pendingMissedIssueAuditBatchId ? "missed_issue_audit" : "manual_chat_prompt";
      const preview = await previewManualAIResponse(
        selectedProjectId,
        manualAIResponse,
        manualAIPromptVersion,
        manualAIPromptId,
        sourceType,
        pendingMissedIssueAuditBatchId,
        pendingMissedIssueAuditRound,
        "manual_pdf_attached_external",
      );
      advanceOperation(1, "Checking reviewed_pages against the expected review scope.");
      setManualAIPreview(preview);
      updateMissedIssueAuditPrompt(preview);
      setManualAIImportMessage(
        preview.review_coverage_status !== "complete"
          ? `Preview found ${preview.valid_recoverable_updates} valid AI update${preview.valid_recoverable_updates === 1 ? "" : "s"}, but import is blocked until reviewed_pages confirms every expected page.`
          : preview.valid_recoverable_updates === 0
            ? "Preview confirms the expected pages were reviewed with no importable updates."
            : `Preview found ${preview.valid_recoverable_updates} valid AI update${preview.valid_recoverable_updates === 1 ? "" : "s"} (${preview.skipped_updates} skipped).`,
      );
      setAIImportBatches(await listAIImportBatches(selectedProjectId));
      await refreshManualReviewPlan(selectedProjectId);
      finishOperation(
        preview.review_coverage_status === "complete" ? "success" : "warning",
        preview.review_coverage_status === "complete"
          ? "Preview passed coverage checks and is ready to import."
          : `Preview is blocked until reviewed_pages confirms missing pages: ${formatPageList(preview.missing_review_pages)}.`,
      );
    } catch (requestError) {
      setManualAIPreview(null);
      const message = getApiErrorMessage(requestError);
      setError(message);
      finishOperation("error", `Preview failed. ${message}`);
    } finally {
      setPreviewingManualAI(false);
    }
  }

  async function handleImportManualAIResponse() {
    if (!selectedProjectId || importingManualAI) {
      return;
    }
    setImportingManualAI(true);
    setError(null);
    setManualAIImportMessage(null);
    startOperation("Import reviewed AI updates", ["Rechecking preview", "Writing findings", "Recording coverage", "Refreshing workspace"], "Rechecking preview coverage before import.");
    try {
      const preview =
        manualAIPreview ??
        (manualAIResponse.trim()
          ? await previewManualAIResponse(
              selectedProjectId,
              manualAIResponse,
              manualAIPromptVersion,
              manualAIPromptId,
              pendingMissedIssueAuditBatchId ? "missed_issue_audit" : "manual_chat_prompt",
              pendingMissedIssueAuditBatchId,
              pendingMissedIssueAuditRound,
              "manual_pdf_attached_external",
            )
          : null);
      if (!preview || preview.review_coverage_status !== "complete" || (preview.valid_recoverable_updates === 0 && !preview.scoped_review_complete)) {
        throw new Error("Preview AI Updates before importing. Every expected page must be confirmed complete in reviewed_pages.");
      }
      advanceOperation(1, "Writing valid AI updates and preserving raw response trace metadata.");
      const result = await importManualAIPreview(selectedProjectId, preview.batch_id);
      updateMissedIssueAuditPrompt(result);
      const importedFindingIds = new Set(result.imported_finding_ids ?? []);
      const importedStableIds = new Set(result.imported_stable_ids ?? []);
      const aiFinding =
        result.findings.find((finding) => importedFindingIds.has(finding.id)) ??
        result.findings.find((finding) => importedStableIds.has(finding.stable_id ?? "")) ??
        [...result.findings].reverse().find((finding) => finding.source === "ai");
      setProjectDetails(result.project);
      setFindings(result.findings);
      setPlacementSummary(computePlacementSummary(result.findings));
      setSelectedFindingId(aiFinding?.id ?? result.findings[0]?.id ?? null);
      const findingSheet = aiFinding ? getFindingSheet(aiFinding, sheets) : null;
      if (findingSheet) {
        setSelectedSheetId(findingSheet.id);
      }
      const importedCount = result.ai_updates_imported ?? result.ai_findings_created;
      const skippedCount = Math.max(0, result.raw_ai_count - importedCount);
      const importMessage = pendingMissedIssueAuditBatchId
        ? `Imported ${importedCount} missed-issue audit update${importedCount === 1 ? "" : "s"}${skippedCount ? ` (${skippedCount} skipped)` : ""}.`
        : importedCount === 0 && preview.review_coverage_status === "complete"
          ? "Recorded scoped review as complete with no AI updates."
          : `Imported ${importedCount} AI update${importedCount === 1 ? "" : "s"}${skippedCount ? ` (${skippedCount} skipped)` : ""}.`;
      setManualAIImportMessage(importMessage);
      setManualAIResponse("");
      setManualAIPrompt(null);
      setManualAIPromptId(null);
      setManualAIPromptVersion(null);
      setManualAIPreview(null);
      setPendingMissedIssueAuditBatchId(null);
      setPendingMissedIssueAuditRound(null);
      advanceOperation(3, "Import complete. Refreshing coverage, findings, and review plan.");
      await refreshReview(selectedProjectId);
      const nextPlan = await getManualReviewPlan(selectedProjectId, largePackageBatchSize).catch(() => null);
      if (nextPlan) {
        setManualReviewPlan(nextPlan);
        const nextBatch = nextUnreviewedBatch(nextPlan);
        const nextPage = nextBatch?.page_numbers[0];
        const nextSheet = nextPage ? sheets.find((sheet) => sheet.page_number === nextPage) : null;
        if (nextSheet) {
          setSelectedSheetId(nextSheet.id);
        }
      }
      finishOperation("success", importedCount === 0 ? "Clean review confirmation recorded." : `Imported ${importedCount} AI update${importedCount === 1 ? "" : "s"} through coverage gates.`);
    } catch (requestError) {
      const message = getApiErrorMessage(requestError);
      setError(message);
      finishOperation("error", `Import failed. AutoQC will keep or restore the last recoverable project state where possible. ${message}`);
    } finally {
      setImportingManualAI(false);
    }
  }

  function updateMissedIssueAuditPrompt(payload: AIPreviewResponse | AIReviewResponse | null | undefined) {
    const prompt = typeof payload?.missed_issue_audit_prompt === "string" ? payload.missed_issue_audit_prompt.trim() : "";
    if (prompt) {
      const audit = payload?.missed_issue_audit && typeof payload.missed_issue_audit === "object" ? payload.missed_issue_audit : {};
      const priorBatchId =
        typeof audit.prior_import_batch_id === "string"
          ? audit.prior_import_batch_id
          : "batch_id" in (payload ?? {}) && typeof (payload as AIPreviewResponse).batch_id === "string"
            ? (payload as AIPreviewResponse).batch_id
            : payload?.batch?.id ?? null;
      const nextRound = typeof audit.next_audit_round === "number" ? audit.next_audit_round : 1;
      setMissedIssueAuditPrompt(prompt);
      setMissedIssueAuditCopied(false);
      setMissedIssueAuditSourceBatchId(priorBatchId);
      setMissedIssueAuditSuggestedRound(nextRound);
    }
  }

  async function handleCopyMissedIssueAuditPrompt() {
    if (!missedIssueAuditPrompt) {
      return;
    }
    try {
      await navigator.clipboard.writeText(missedIssueAuditPrompt);
      setMissedIssueAuditCopied(true);
      setManualAIImportMessage("Copied the second-pass missed-issue audit prompt.");
    } catch {
      setError("Could not copy the missed-issue audit prompt. Select the prompt text and copy it manually.");
    }
  }

  async function handleRollbackImportBatch(batch: AIImportBatch) {
    if (!selectedProjectId || rollingBackBatchId) {
      return;
    }
    setRollingBackBatchId(batch.id);
    setError(null);
    try {
      const preview = await previewImportBatchRollback(selectedProjectId, batch.id);
      const removeCount = preview.findings_to_remove ?? 0;
      const reviewedCount = preview.reviewed_or_edited_findings ?? 0;
      const confirmed = window.confirm(
        `Remove imported batch?\n\n${removeCount} finding${removeCount === 1 ? "" : "s"} created by this batch will be removed.\n${reviewedCount} accepted, edited, or reviewer-noted finding${reviewedCount === 1 ? "" : "s"} will be affected.\n\nUnrelated findings and updated pre-existing findings will not be deleted.`,
      );
      if (!confirmed) {
        return;
      }
      const result: BatchRollbackPreview = await rollbackImportBatch(selectedProjectId, batch.id);
      setFindings(result.findings ?? []);
      setSelectedFindingId(result.findings?.[0]?.id ?? null);
      setManualAIImportMessage(
        `Rolled back import batch and removed ${result.findings_removed ?? 0} finding${result.findings_removed === 1 ? "" : "s"}.`,
      );
      await refreshReview(selectedProjectId);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setRollingBackBatchId(null);
    }
  }

  async function handlePatchFinding(findingId: string, update: FindingUpdate, options: { suppressUndo?: boolean } = {}) {
    const previous = findings.find((finding) => finding.id === findingId) ?? null;
    const isStatusOnlyUpdate = Boolean(update.status) && Object.keys(update).length === 1;
    setSavingFindingId(findingId);
    setError(null);

    try {
      const updated = await updateFinding(findingId, update);
      setFindings((current) => {
        const nextFindings = current.map((finding) => (finding.id === updated.id ? updated : finding));
        if (autoAdvanceReview && update.status && update.status !== "needs_review") {
          const nextReview = nextUnreviewedFinding(nextFindings, updated.id);
          setSelectedFindingId(nextReview?.id ?? updated.id);
          if (nextReview) {
            const sheet = getFindingSheet(nextReview, sheets);
            if (sheet) {
              setSelectedSheetId(sheet.id);
            }
          }
        } else {
          setSelectedFindingId(updated.id);
        }
        return nextFindings;
      });
      if (
        isStatusOnlyUpdate &&
        !options.suppressUndo &&
        previous &&
        update.status &&
        previous.status !== updated.status
      ) {
        setStatusUndo({
          findingId,
          title: updated.title,
          previousStatus: previous.status,
          nextStatus: updated.status,
        });
      } else if (!isStatusOnlyUpdate) {
        setStatusUndo(null);
      }
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setSavingFindingId(null);
    }
  }

  async function handleUndoFindingStatus() {
    if (!statusUndo) {
      return;
    }

    const undo = statusUndo;
    setStatusUndo(null);
    await handlePatchFinding(undo.findingId, { status: undo.previousStatus }, { suppressUndo: true });
  }

  async function handleBulkPatchFindings(targetFindings: Finding[], update: FindingUpdate) {
    if (targetFindings.length === 0) {
      return;
    }

    setError(null);
    try {
      const response = await bulkUpdateFindings(targetFindings.map((finding) => finding.id), update);
      const updatedById = new Map(response.updated.map((finding) => [finding.id, finding]));
      setFindings((current) => current.map((finding) => updatedById.get(finding.id) ?? finding));
      if (selectedProjectId) {
        setEvents(await listFindingEvents(selectedProjectId));
      }
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    }
  }

  async function handleRecalculatePlacement() {
    if (!selectedProjectId) {
      return;
    }

    setRecalculatingPlacement(true);
    setPlacementMessage(null);
    setError(null);
    startOperation("Recalculate placement", ["Opening source PDF", "Searching target text", "Saving placement summary"], "Opening the source PDF and recalculating markup locations.");
    try {
      const result = await recalculateFindingPlacement(selectedProjectId);
      advanceOperation(2, "Placement recalculation finished. Saving updated placement statuses.");
      setFindings(result.findings);
      setPlacementSummary(result.summary);
      setPlacementMessage(`Recalculated locations for ${result.updated_count} finding${result.updated_count === 1 ? "" : "s"}.`);
      finishOperation("success", `Recalculated placement for ${result.updated_count} finding${result.updated_count === 1 ? "" : "s"}.`);
    } catch (requestError) {
      const message = getApiErrorMessage(requestError);
      setError(message);
      finishOperation("error", `Placement recalculation failed. ${message}`);
    } finally {
      setRecalculatingPlacement(false);
    }
  }

  async function handleSaveManualPlacement(
    finding: Finding,
    pageNumber: number,
    rect: number[],
    imageWidth: number,
    imageHeight: number,
  ) {
    setSavingManualPlacement(true);
    setError(null);
    startOperation("Save manual placement", ["Validating rectangle", "Saving reviewer placement", "Refreshing audit trail"], "Validating the manual markup rectangle.");
    try {
      advanceOperation(1, "Saving reviewer-selected placement for final export.");
      const updated = await saveManualPlacement(finding.id, pageNumber, rect, imageWidth, imageHeight);
      setFindings((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      setSelectedFindingId(updated.id);
      setManualPlacementFindingId(null);
      setPlacementMessage("Manual markup placement saved for export.");
      if (selectedProjectId) {
        setEvents(await listFindingEvents(selectedProjectId));
      }
      finishOperation("success", "Manual markup placement saved for export.");
    } catch (requestError) {
      const message = getApiErrorMessage(requestError);
      setError(message);
      finishOperation("error", `Manual placement could not be saved. ${message}`);
    } finally {
      setSavingManualPlacement(false);
    }
  }

  async function handleDeleteFinding(finding: Finding) {
    const confirmed = window.confirm(`Delete finding "${finding.title}"?`);
    if (!confirmed) {
      return;
    }

    setDeletingFindingId(finding.id);
    setError(null);

    try {
      await deleteFinding(finding.id);
      const remaining = findings.filter((item) => item.id !== finding.id);
      setFindings(remaining);
      setSelectedFindingId(remaining[0]?.id ?? null);
      if (selectedProjectId) {
        setEvents(await listFindingEvents(selectedProjectId));
      }
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setDeletingFindingId(null);
    }
  }

  async function handleMergeFinding(finding: Finding, targetFindingId: string) {
    if (!selectedProjectId || mergingFindingId || !targetFindingId || targetFindingId === finding.id) {
      return;
    }
    const target = findings.find((item) => item.id === targetFindingId);
    const confirmed = window.confirm(
      `Merge "${finding.title}" into "${target?.title ?? "selected finding"}"? The source finding will be marked duplicate and hidden from accepted-only exports.`,
    );
    if (!confirmed) {
      return;
    }
    setMergingFindingId(finding.id);
    setError(null);
    try {
      await mergeFindingInto(finding.id, targetFindingId);
      setManualAIImportMessage("Duplicate finding merged and preserved in the audit trail.");
      await refreshReview(selectedProjectId);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setMergingFindingId(null);
    }
  }

  function handleSelectFinding(finding: Finding) {
    setSelectedFindingId(finding.id);
    setLastSelectedFindingId(finding.id);
    setLeftRailCard("findings");
    setLeftRailCollapsed(false);
    const sheet = getFindingSheet(finding, sheets);
    if (sheet) {
      setSelectedSheetId(sheet.id);
    }
  }

  function handleSelectPdfMarkup(finding: Finding) {
    setSelectedFindingId(finding.id);
    setLastSelectedFindingId(finding.id);
    setLeftRailCard("findings");
    setLeftRailCollapsed(false);
    const sheet = getFindingSheet(finding, sheets);
    if (sheet) {
      setSelectedSheetId(sheet.id);
    }
  }

  function handleSelectSheet(sheetId: string) {
    setSelectedFindingId(null);
    setActiveMarkedPdfUrl(null);
    setSelectedSheetId(sheetId);
  }

  function handleStepSheet(delta: number) {
    if (!selectedSheet) {
      return;
    }

    const index = sheets.findIndex((sheet) => sheet.id === selectedSheet.id);
    const next = sheets[index + delta];
    if (next) {
      handleSelectSheet(next.id);
    }
  }

  function handleStepFinding(delta: number, queueOnly = false) {
    const source = queueOnly ? reviewQueueFindings : findings;
    if (source.length === 0) {
      return;
    }

    const currentIndex = Math.max(0, source.findIndex((finding) => finding.id === selectedFindingId));
    const next = source[clamp(currentIndex + delta, 0, source.length - 1)];
    if (next) {
      handleSelectFinding(next);
    }
  }

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) {
        return;
      }

      const target = event.target as HTMLElement | null;
      const tagName = target?.tagName?.toLowerCase();
      if (tagName === "input" || tagName === "textarea" || tagName === "select" || target?.isContentEditable) {
        return;
      }

      if (event.key === "Escape" && manualPlacementFindingId) {
        event.preventDefault();
        setManualPlacementFindingId(null);
        setPlacementMessage(null);
      } else if (event.key === "a" && selectedFinding) {
        event.preventDefault();
        void handlePatchFinding(selectedFinding.id, { status: "accepted" });
      } else if (event.key === "x" && selectedFinding) {
        event.preventDefault();
        void handlePatchFinding(selectedFinding.id, { status: "rejected" });
      } else if (event.key === "r" && selectedFinding) {
        event.preventDefault();
        void handlePatchFinding(selectedFinding.id, { status: "needs_review" });
      } else if (event.key === "j") {
        event.preventDefault();
        handleStepFinding(1);
      } else if (event.key === "k") {
        event.preventDefault();
        handleStepFinding(-1);
      } else if (event.key === "n") {
        event.preventDefault();
        handleStepFinding(1, true);
      } else if (event.key === "]") {
        event.preventDefault();
        handleStepSheet(1);
      } else if (event.key === "[") {
        event.preventDefault();
        handleStepSheet(-1);
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [selectedFinding, selectedFindingId, findings, reviewQueueFindings, selectedSheet, sheets, autoAdvanceReview, manualPlacementFindingId]);

  const leftRailPanelTitle =
    leftRailCard === "projects"
      ? "Home"
      : leftRailCard === "review"
        ? "Review"
      : leftRailCard === "findings"
        ? "Findings"
      : leftRailCard === "export"
        ? "Export"
      : "Advanced";
  const leftRailPanelSubtitle =
    leftRailCard === "projects"
      ? `${projects.length} projects`
      : leftRailCard === "findings"
        ? `${findings.length} findings`
      : leftRailCard === "export"
        ? "Marked PDF and logs"
      : leftRailCard === "advanced"
        ? "Experimental tools"
      : "AI prompt bridge";

  function openLeftRailCard(card: LeftRailCard) {
    setLeftRailCard(card);
    setLeftRailCollapsed(false);
  }

  function handlePrimaryTabKeyDown(event: ReactKeyboardEvent<HTMLElement>) {
    const current = event.target as HTMLElement | null;
    const currentCard = current?.dataset.leftRailCard as LeftRailCard | undefined;
    if (!currentCard || !PRIMARY_WORKFLOW_CARDS.includes(currentCard)) {
      return;
    }

    const currentIndex = PRIMARY_WORKFLOW_CARDS.indexOf(currentCard);
    let nextIndex = currentIndex;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      nextIndex = (currentIndex + 1) % PRIMARY_WORKFLOW_CARDS.length;
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      nextIndex = (currentIndex - 1 + PRIMARY_WORKFLOW_CARDS.length) % PRIMARY_WORKFLOW_CARDS.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = PRIMARY_WORKFLOW_CARDS.length - 1;
    } else {
      return;
    }

    event.preventDefault();
    const nextCard = PRIMARY_WORKFLOW_CARDS[nextIndex];
    openLeftRailCard(nextCard);
    window.requestAnimationFrame(() => {
      document.querySelector<HTMLButtonElement>(`[data-left-rail-card="${nextCard}"]`)?.focus();
    });
  }

  return (
    <div className={`app-shell document-app ${leftRailCollapsed ? "left-rail-collapsed" : ""}`}>
      <aside className="app-nav" aria-label="Primary navigation">
        <button
          className="app-logo"
          type="button"
          title="Go to review library"
          aria-label="Go to review library"
          onClick={() => openLeftRailCard("projects")}
        >
          <ClipboardCheck size={18} />
        </button>
        <nav className="nav-stack" role="tablist" aria-label="Primary workflow panels" onKeyDown={handlePrimaryTabKeyDown}>
          <button
            className={`nav-item ${leftRailCard === "projects" && !leftRailCollapsed ? "active" : ""}`}
            type="button"
            role="tab"
            aria-selected={leftRailCard === "projects" && !leftRailCollapsed}
            data-left-rail-card="projects"
            title="Go to the review library and upload area"
            aria-label="Projects"
            onClick={() => openLeftRailCard("projects")}
          >
            <FolderOpen size={17} />
            <span>Projects</span>
          </button>
          <button
            className={`nav-item ${leftRailCard === "review" && !leftRailCollapsed ? "active" : ""}`}
            type="button"
            role="tab"
            aria-selected={leftRailCard === "review" && !leftRailCollapsed}
            data-left-rail-card="review"
            title="Go to the AI review bridge and import history"
            aria-label="Review"
            onClick={() => openLeftRailCard("review")}
          >
            <Sparkles size={17} />
            <span>Review</span>
          </button>
          <button
            className={`nav-item ${leftRailCard === "findings" && !leftRailCollapsed ? "active" : ""}`}
            type="button"
            role="tab"
            aria-selected={leftRailCard === "findings" && !leftRailCollapsed}
            data-left-rail-card="findings"
            title="Open the findings list"
            aria-label="Findings"
            onClick={() => openLeftRailCard("findings")}
          >
            <Search size={17} />
            <span>Findings</span>
          </button>
          <button
            className={`nav-item ${leftRailCard === "export" && !leftRailCollapsed ? "active" : ""}`}
            type="button"
            role="tab"
            aria-selected={leftRailCard === "export" && !leftRailCollapsed}
            data-left-rail-card="export"
            title="Export marked PDF and logs"
            aria-label="Export"
            onClick={() => openLeftRailCard("export")}
          >
            <Download size={17} />
            <span>Export</span>
          </button>
        </nav>
        <button
          className="nav-item nav-help"
          type="button"
          title="Open AutoQC workflow help"
          aria-label="Open AutoQC help"
          onClick={() => setHelpOpen(true)}
        >
          <HelpCircle size={17} />
          <span>Help</span>
        </button>
        <button
          className={`nav-item nav-advanced ${leftRailCard === "advanced" && !leftRailCollapsed ? "active" : ""}`}
          type="button"
          title="Open power-user and diagnostic tools"
          aria-label="Open Advanced tools"
          data-left-rail-card="advanced"
          onClick={() => openLeftRailCard("advanced")}
        >
          <ShieldCheck size={17} />
          <span>Advanced</span>
        </button>
        <div className="usage-widget">
          <strong>{projects.length}</strong>
          <span>projects</span>
        </div>
      </aside>

      {error ? (
        <div className="global-status-banner" role="alert" aria-live="assertive">
          <AlertTriangle size={17} />
          <span>{error}</span>
          <button type="button" onClick={() => setError(null)} aria-label="Dismiss error">
            <X size={15} />
          </button>
        </div>
      ) : null}

      {operation ? <OperationProgressPanel operation={operation} onDismiss={operation.status === "active" ? undefined : clearOperation} /> : null}

      {statusUndo ? (
        <div className="status-undo-banner" role="status" aria-live="polite">
          <Check size={16} />
          <span>
            {formatStatus(statusUndo.nextStatus)} saved for {statusUndo.title}.
          </span>
          <button type="button" onClick={() => void handleUndoFindingStatus()}>
            Undo
          </button>
        </div>
      ) : null}

      {helpOpen ? (
        <HelpDialog
          onClose={() => setHelpOpen(false)}
          onOpenAdvanced={() => {
            setHelpOpen(false);
            openLeftRailCard("advanced");
          }}
        />
      ) : null}

      <section className={`library-pane tabbed-rail ${leftRailCollapsed ? "collapsed" : ""}`} id="review-library">
        <div className="rail-pane-header">
          <div>
            <strong>{leftRailPanelTitle}</strong>
            <span>{leftRailPanelSubtitle}</span>
          </div>
          <button
            className="rail-collapse-button"
            type="button"
            title="Collapse left panel"
            aria-label="Collapse left panel"
            onClick={() => setLeftRailCollapsed(true)}
          >
            <ChevronLeft size={16} />
          </button>
        </div>
        <div className="rail-card-scroll left-card-scroll">
          {leftRailCard === "review" ? (
            <section className="panel dashboard-card review-actions-card" aria-label="Review actions and AI bridge">
              <div className="library-topbar">
                <div>
                  <strong>AutoQC</strong>
                  <span>{sheets.length || projects.length} results from drawing reviews</span>
                </div>
                <div className="topbar-button-row">
                  <button
                    className="ai-action manual-ai-action"
                    type="button"
                    disabled={!selectedProjectId || generatingManualPrompt}
                    title="Generate a ChatGPT/Copilot prompt using the selected large-package review mode"
                    onClick={() => void handleGenerateManualAIPrompt()}
                  >
                    <Sparkles size={14} className={generatingManualPrompt ? "spin" : ""} />
                    {generatingManualPrompt ? "Building prompt" : "Chat Prompt"}
                  </button>
                  <button
                    className="blue-action"
                    type="button"
                    title="Refresh projects, sheets, findings, and audit activity from the backend"
                    onClick={() => {
                      void refreshProjects();
                      void refreshReview();
                      void refreshAIStatus();
                    }}
                  >
                    <RefreshCw size={14} className={loadingProjects || loadingReview ? "spin" : ""} />
                    Sync
                  </button>
                </div>
              </div>
              {sheets.length > 1 ? (
                <div className="inline-helper">
                  Large package review: hybrid mode reviews every page in adaptive batches, then queues text-heavy sheets for single-sheet deep dives.
                </div>
              ) : null}

              <CurrentWorkSummary
                project={selectedProject}
                sheet={selectedSheet}
                findings={findings}
                reviewProgress={reviewProgress}
                coverage={selectedProject?.review_coverage ?? latestImportCoverage(aiImportBatches.find((batch) => batch.import_status === "imported") ?? aiImportBatches[0])}
              />

              <WorkflowGuide
                project={selectedProject}
                sheets={sheets}
                findings={findings}
                batches={aiImportBatches}
                events={events}
                preview={manualAIPreview}
                onOpenProjects={() => openLeftRailCard("projects")}
                onOpenReview={() => openLeftRailCard("review")}
                onOpenFindings={() => openLeftRailCard("findings")}
                onOpenExport={() => openLeftRailCard("export")}
                onGeneratePrompt={() => void handleGenerateManualAIPrompt()}
              />

              <RecoveryCenter
                project={selectedProject}
                findings={findings}
                batches={aiImportBatches}
                events={events}
                preview={manualAIPreview}
                onOpenProjects={() => openLeftRailCard("projects")}
                onOpenReview={() => openLeftRailCard("review")}
                onOpenFindings={() => openLeftRailCard("findings")}
                onOpenExport={() => openLeftRailCard("export")}
                onGeneratePrompt={() => void handleGenerateManualAIPrompt()}
                onRecalculatePlacement={() => void handleRecalculatePlacement()}
              />

              <details className="collapsible-section workstation-detail-panel">
                <summary>
                  <span>
                    <strong>Review dashboard</strong>
                    <small>Counts, placement quality, latest import/export, and readiness warnings</small>
                  </span>
                </summary>
                <DashboardSummary
                  project={selectedProject}
                  findings={findings}
                  batches={aiImportBatches}
                  events={events}
                  placementSummary={placementSummary ?? computePlacementSummary(findings)}
                />
              </details>

              <details className="collapsible-section advanced-prompt-options">
                <summary>
                  <span>
                    <strong>Advanced prompt options</strong>
                    <small>Defaults use Exhaustive Deep Review with adaptive batching</small>
                  </span>
                </summary>
              <div className="template-manager compact-section" aria-label="Prompt template manager">
                <label className="field-label">
                  Prompt template
                  <select
                    value={selectedPromptTemplateId ?? ""}
                    onChange={(event) => setSelectedPromptTemplateId(event.target.value || null)}
                    title="Choose the company-ready prompt template used for the next Chat Prompt"
                  >
                    {promptTemplates.map((template) => (
                      <option key={template.id} value={template.id}>
                        {template.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field-label">
                  Review depth
                  <select
                    value={selectedPromptDepth}
                    onChange={(event) => setSelectedPromptDepth(event.target.value as PromptDepth)}
                    title="Choose how much review coverage to ask ChatGPT or Copilot for"
                  >
                    <option value="fast">Fast Review</option>
                    <option value="standard">Standard Review</option>
                    <option value="comprehensive">Comprehensive Review</option>
                    <option value="exhaustive">Exhaustive Deep Review</option>
                  </select>
                </label>
                {selectedPromptTemplate ? (
                  <div className="template-preview" aria-label="Prompt template comparison preview">
                    <div className="template-preview-header">
                      <strong>{selectedPromptTemplate.name}</strong>
                      <span>{selectedPromptTemplate.version}</span>
                    </div>
                    <span>{selectedPromptTemplate.category ?? "General"} | {selectedPromptTemplate.review_depth ?? "Standard Review"}</span>
                    <p>{selectedPromptTemplate.description}</p>
                    <dl>
                      <dt>Intended use</dt>
                      <dd>{selectedPromptTemplate.intended_use ?? "General AutoQC prompt generation."}</dd>
                      <dt>Review priorities</dt>
                      <dd>{(selectedPromptTemplate.review_priorities ?? []).slice(0, 3).join(" ")}</dd>
                      <dt>When to use it</dt>
                      <dd>{selectedPromptTemplate.when_to_use ?? "Use when this template matches the package review goal."}</dd>
                      <dt>When not to use it</dt>
                      <dd>{selectedPromptTemplate.when_not_to_use ?? "Use another template when a narrower or client-specific review is needed."}</dd>
                    </dl>
                  </div>
                ) : (
                  <small>Templates are stored locally.</small>
                )}
              </div>

              {sheets.length > 1 ? (
                <LargePackageReviewPanel
                  plan={manualReviewPlan}
                  mode={largePackageMode}
                  batchSize={largePackageBatchSize}
                  selectedSheet={selectedSheet}
                  onModeChange={setLargePackageMode}
                  onBatchSizeChange={setLargePackageBatchSize}
                  onGenerateNextBatch={handleGenerateNextBatchPrompt}
                  onDeepDiveSheet={handleDeepDiveSheet}
                />
              ) : null}

              </details>

              {manualAIImportMessage ? (
                <div className="system-banner success-banner" role="status">
                  <Check size={16} />
                  <span>{manualAIImportMessage}</span>
                </div>
              ) : null}

              {manualAIPrompt !== null ? (
                <section className="manual-ai-panel manual-review-panel" aria-label="Manual ChatGPT or Copilot AI review bridge">
                  <div className="manual-ai-header">
                    <div>
                      <strong>Manual AI Review</strong>
                      <span>AutoQC guides the no-API workflow: copy/open ChatGPT or Copilot, attach the same PDF, then paste or drop the JSON response for validation and import.</span>
                    </div>
                    <button
                      className="secondary-button"
                      type="button"
                      title="Close the manual AI review panel"
                      onClick={() => {
                        setManualAIPrompt(null);
                        setManualAIPromptId(null);
                        setManualAIPromptVersion(null);
                        setManualAIResponse("");
                        setManualAIPreview(null);
                      }}
                    >
                      Close
                    </button>
                  </div>

                  <div className="manual-review-steps" aria-label="Manual AI review progress steps">
                    <span className={manualAIPrompt ? "done" : ""}><Check size={13} /> Prompt generated</span>
                    <span className={manualAICopied ? "done" : ""}><Check size={13} /> Prompt copied</span>
                    <span><Upload size={13} /> Attach PDF in ChatGPT/Copilot</span>
                    <span className={manualAIResponse.trim() ? "done" : ""}><Check size={13} /> JSON response loaded</span>
                    <span className={manualAIPreview?.valid_recoverable_updates ? "done" : ""}><Check size={13} /> Preview valid</span>
                  </div>

                  <div className="button-row manual-ai-buttons manual-launch-buttons">
                    <button className="primary-button" type="button" onClick={() => void handleOpenManualAI("chatgpt")} title="Copy the prompt and open ChatGPT in a new tab">
                      <ExternalLink size={16} />
                      Open ChatGPT
                    </button>
                    <button className="primary-button" type="button" onClick={() => void handleOpenManualAI("copilot")} title="Copy the prompt and open Copilot in a new tab">
                      <ExternalLink size={16} />
                      Open Copilot
                    </button>
                    <button className="secondary-button" type="button" onClick={() => void handleCopyManualAIPrompt()} title="Copy the generated prompt to your clipboard">
                      <ClipboardCheck size={16} />
                      {manualAICopied ? "Prompt Copied" : "Copy Prompt"}
                    </button>
                    <a
                      className="secondary-button inline-download-button"
                      href={`data:text/plain;charset=utf-8,${encodeURIComponent(manualAIPrompt)}`}
                      download={`autoqc-chat-prompt-${manualAIPromptId ?? "latest"}.txt`}
                      title="Download the generated prompt as a text file"
                    >
                      <Download size={16} />
                      Download Prompt
                    </a>
                    {selectedProjectSourcePdfUrl ? (
                      <a className="secondary-button source-pdf-button" href={selectedProjectSourcePdfUrl} target="_blank" rel="noreferrer" title="Open the source PDF to attach in ChatGPT or Copilot">
                        <FileText size={16} />
                        Open Source PDF
                      </a>
                    ) : null}
                  </div>

                  <label className="field-label" title="Copy this instruction prompt into ChatGPT or Copilot Chat along with the actual drawing package PDF.">
                    Prompt to paste into ChatGPT/Copilot with the attached PDF
                    <textarea className="manual-ai-textarea" readOnly value={manualAIPrompt} rows={8} />
                  </label>

                  {pendingMissedIssueAuditBatchId ? (
                    <div className="inline-helper success-helper" role="status">
                      Second-pass audit import armed for batch {pendingMissedIssueAuditBatchId.slice(0, 8)}. The next preview/import will record missed-issue audit lineage and yield.
                    </div>
                  ) : null}

                  <div
                    className="manual-import-dropzone"
                    onDragOver={(event) => event.preventDefault()}
                    onDrop={handleManualAIDrop}
                  >
                    <label className="field-label" title="Paste, drag, or import the update JSON from ChatGPT or Copilot Chat here.">
                      Paste AI update JSON
                      <textarea
                        className="manual-ai-textarea"
                        value={manualAIResponse}
                        rows={7}
                        onChange={(event) => {
                          setManualAIResponse(event.target.value);
                          setManualAIPreview(null);
                        }}
                        placeholder='Paste JSON like {"updates":[...]}, or drag a .json/.txt response file here.'
                      />
                    </label>
                    <AIResponsePreflightPanel assessment={manualAIResponseAssessment} />
                    <div className="manual-import-tools">
                      <button className="secondary-button" type="button" onClick={() => void handlePasteManualAIResponse()} title="Read the AI response JSON from your clipboard">
                        <ClipboardPaste size={16} />
                        Paste from Clipboard
                      </button>
                      <label className="secondary-button file-import-button" title="Import a saved ChatGPT/Copilot JSON or text response file">
                        <Upload size={16} />
                        Import JSON/TXT
                        <input type="file" accept="application/json,.json,.txt,text/plain" onChange={handleManualAIFileInput} aria-label="Import AI JSON or text response file" />
                      </label>
                      <span>Drop a response file here, then preview before importing.</span>
                    </div>
                  </div>

                  <div className="button-row manual-ai-buttons">
                    <button
                      className="primary-button"
                      type="button"
                      disabled={!manualAIResponse.trim() || previewingManualAI}
                      title="Parse the pasted ChatGPT/Copilot output before creating findings"
                      onClick={() => void handlePreviewManualAIResponse()}
                    >
                      <Sparkles size={17} className={previewingManualAI ? "spin" : ""} />
                      {previewingManualAI ? "Previewing" : "Preview AI Updates"}
                    </button>
                    <button
                      className="download-pdf-button inline-download-button"
                      type="button"
                      disabled={manualAIPreview?.review_coverage_status !== "complete" || !(manualAIPreview?.valid_recoverable_updates || manualAIPreview?.scoped_review_complete) || importingManualAI}
                      title={manualAIPreview?.review_coverage_status !== "complete" ? "Import is blocked until reviewed_pages confirms every expected page complete" : manualAIPreview?.scoped_review_complete && !manualAIPreview.valid_recoverable_updates ? "Record the scoped review as complete with no updates" : "Import only the valid recoverable updates from the preview"}
                      onClick={() => void handleImportManualAIResponse()}
                    >
                      <Sparkles size={18} className={importingManualAI ? "spin" : ""} />
                      {importingManualAI ? "Importing AI Updates" : manualAIPreview?.scoped_review_complete && !manualAIPreview.valid_recoverable_updates ? "Mark Reviewed / No Updates" : "Import Valid Updates"}
                    </button>
                  </div>
                  <AIPreviewPanel preview={manualAIPreview} />
                </section>
              ) : null}

            </section>
          ) : null}

          {leftRailCard === "projects" ? (
            <ProjectsPanel
              projects={projects}
              selectedProjectId={selectedProjectId}
              loading={loadingProjects}
              uploading={uploading}
              deletingProjectId={deletingProjectId}
              showValidationProjects={showValidationProjects}
              taggingValidationProjects={taggingValidationProjects}
              cleaningValidationProjects={cleaningValidationProjects}
              onSelectProject={setSelectedProjectId}
              onRefresh={refreshProjects}
              onShowValidationProjectsChange={setShowValidationProjects}
              onUpload={handleUpload}
              onDeleteProject={handleDeleteProject}
              onTagGeneratedValidationProjects={handleTagGeneratedValidationProjects}
              onClearValidationProjects={handleClearValidationProjects}
            />
          ) : null}

          {leftRailCard === "findings" ? (
            <FindingsPanel
              findings={findings}
              sheets={sheets}
              selectedFinding={selectedFinding}
              scrollFindingId={selectedFinding?.id ?? lastSelectedFindingId}
              selectedProject={selectedProject}
              reviewProgress={reviewProgress}
              autoAdvanceReview={autoAdvanceReview}
              onAutoAdvanceChange={setAutoAdvanceReview}
              onSelectFinding={handleSelectFinding}
              onBulkPatchFindings={handleBulkPatchFindings}
            />
          ) : null}

          {leftRailCard === "findings" ? (
            <FindingInspector
              finding={selectedFinding}
              findings={findings}
              sheet={selectedFinding ? getFindingSheet(selectedFinding, sheets) : undefined}
              saving={selectedFinding ? savingFindingId === selectedFinding.id : false}
              deleting={selectedFinding ? deletingFindingId === selectedFinding.id : false}
              merging={selectedFinding ? mergingFindingId === selectedFinding.id : false}
              manualPlacementActive={Boolean(selectedFinding && manualPlacementFindingId === selectedFinding.id)}
              savingManualPlacement={savingManualPlacement}
              onPatchFinding={handlePatchFinding}
              onDeleteFinding={handleDeleteFinding}
              onMergeFinding={handleMergeFinding}
              onStartManualPlacement={(finding) => {
                setManualPlacementFindingId(finding.id);
                setPlacementMessage("Manual placement mode: drag a rectangle on the drawing image, then release to save.");
              }}
              onCancelManualPlacement={() => {
                setManualPlacementFindingId(null);
                setPlacementMessage(null);
              }}
            />
          ) : null}

          {leftRailCard === "export" ? (
            <ExportPanel
              project={selectedProject}
              findings={findings}
              events={events}
              onExportComplete={(response) => {
                setActiveMarkedPdfUrl(response.marked_pdf ?? null);
                setLeftRailCard("export");
                setLeftRailCollapsed(false);
                return refreshReview();
              }}
            />
          ) : null}

          {leftRailCard === "advanced" ? (
            <AdvancedFeaturesPanel
              project={selectedProject}
              batches={aiImportBatches}
              events={events}
              readiness={readiness}
              settings={markupMemorySettings}
              stats={markupMemoryStats}
              preview={markupMemoryPreview}
              loading={loadingMarkupMemory}
              saving={savingMarkupMemory}
              rebuilding={rebuildingMarkupMemory}
              clearing={clearingMarkupMemory}
              runningAIReview={runningAIReview}
              creatingSample={creatingSample}
              exportingPackage={exportingPackage}
              importingPackage={importingPackage}
              rollingBackBatchId={rollingBackBatchId}
              onRefresh={refreshMarkupMemory}
              onUpdateSettings={handleUpdateMarkupMemorySettings}
              onRebuild={handleRebuildMarkupMemory}
              onClear={handleClearMarkupMemory}
              onRunAIReview={handleRunAIReview}
              onRefreshReadiness={refreshReadiness}
              onRollbackBatch={handleRollbackImportBatch}
              onSampleProject={handleSampleProject}
              onExportPackage={handleExportProjectPackage}
              onImportPackage={handleImportProjectPackage}
            />
          ) : null}
        </div>
      </section>

      <main className="workspace">
        <section className="viewer-pane">
          <Viewer
            project={selectedProject}
            sheet={selectedSheet}
            sheets={sheets}
            findings={findingsForSelectedSheet}
            selectedFinding={selectedFinding}
            markedPdfUrl={activeMarkedPdfUrl}
            loading={loadingReview}
            placementMessage={placementMessage}
            placementSummary={placementSummary}
            manualPlacementFindingId={manualPlacementFindingId}
            savingManualPlacement={savingManualPlacement}
            savingFindingId={savingFindingId}
            onSelectFinding={handleSelectPdfMarkup}
            onPatchFindingStatus={(finding, status) => handlePatchFinding(finding.id, { status })}
            onSelectSheet={handleSelectSheet}
            onSaveManualPlacement={handleSaveManualPlacement}
            onStepSheet={handleStepSheet}
            onDeepDiveSheet={handleDeepDiveSheet}
          />
        </section>
      </main>

      <MissedIssueAuditPromptPanel
        prompt={missedIssueAuditPrompt}
        copied={missedIssueAuditCopied}
        sourceBatchId={missedIssueAuditSourceBatchId}
        auditRound={missedIssueAuditSuggestedRound}
        onCopy={handleCopyMissedIssueAuditPrompt}
        onUseAsPrompt={() => {
          if (!missedIssueAuditPrompt) {
            return;
          }
          setManualAIPrompt(missedIssueAuditPrompt);
          setManualAIPromptId(null);
          setManualAIPromptVersion(null);
          setManualAIResponse("");
          setManualAIPreview(null);
          setPendingMissedIssueAuditBatchId(missedIssueAuditSourceBatchId);
          setPendingMissedIssueAuditRound(missedIssueAuditSuggestedRound);
          setLeftRailCard("review");
        }}
        onClose={() => {
          setMissedIssueAuditPrompt(null);
          setMissedIssueAuditCopied(false);
          setMissedIssueAuditSourceBatchId(null);
          setMissedIssueAuditSuggestedRound(null);
          setPendingMissedIssueAuditBatchId(null);
          setPendingMissedIssueAuditRound(null);
        }}
      />
    </div>
  );
}

interface ProjectsPanelProps {
  projects: Project[];
  selectedProjectId: string | null;
  loading: boolean;
  uploading: boolean;
  deletingProjectId: string | null;
  showValidationProjects: boolean;
  taggingValidationProjects: boolean;
  cleaningValidationProjects: boolean;
  onSelectProject: (projectId: string) => void;
  onRefresh: () => Promise<void>;
  onShowValidationProjectsChange: (value: boolean) => void;
  onUpload: (name: string, file: File) => Promise<void>;
  onDeleteProject: (project: Project) => Promise<void>;
  onTagGeneratedValidationProjects: () => Promise<void>;
  onClearValidationProjects: () => Promise<void>;
}

function OperationProgressPanel({ operation, onDismiss }: { operation: OperationProgress; onDismiss?: () => void }) {
  const active = operation.status === "active";
  const elapsedSeconds = Math.max(0, Math.round((Date.now() - operation.startedAt) / 1000));
  return (
    <section className={`operation-progress operation-${operation.status}`} role="status" aria-live="polite">
      <div className="operation-progress-header">
        <div>
          <strong>{operation.title}</strong>
          <span>{operation.message}</span>
        </div>
        {active ? <Loader2 size={17} className="spin" /> : onDismiss ? (
          <button type="button" onClick={onDismiss} aria-label="Dismiss operation message">
            <X size={15} />
          </button>
        ) : null}
      </div>
      <div className="operation-step-list">
        {operation.steps.map((step, index) => {
          const done = operation.status !== "active" || index < operation.currentStep;
          const current = active && index === operation.currentStep;
          return (
            <span className={done ? "done" : current ? "active" : ""} key={step}>
              {done ? <Check size={12} /> : current ? <Loader2 size={12} className="spin" /> : <ChevronRight size={12} />}
              {step}
            </span>
          );
        })}
      </div>
      <small>{active ? `${elapsedSeconds}s elapsed` : formatStatus(operation.status)}</small>
    </section>
  );
}

function MissedIssueAuditPromptPanel({
  prompt,
  copied,
  sourceBatchId,
  auditRound,
  onCopy,
  onUseAsPrompt,
  onClose,
}: {
  prompt: string | null;
  copied: boolean;
  sourceBatchId: string | null;
  auditRound: number | null;
  onCopy: () => void;
  onUseAsPrompt: () => void;
  onClose: () => void;
}) {
  if (!prompt) {
    return null;
  }

  return (
    <aside className="missed-issue-audit-panel" aria-label="Second-pass missed issue audit prompt">
      <div className="missed-issue-audit-header">
        <div>
          <strong>Second-pass audit recommended</strong>
          <span>AutoQC generated a follow-up prompt to search for issues missed in the first AI response.</span>
        </div>
        <button type="button" className="ghost-button" onClick={onClose}>
          Close
        </button>
      </div>
      <textarea className="missed-issue-audit-textarea" value={prompt} readOnly />
      <div className="missed-issue-audit-actions">
        <button type="button" className="primary-button" onClick={onCopy}>
          {copied ? "Copied" : "Copy missed-issue audit prompt"}
        </button>
        <button type="button" className="secondary-button" onClick={onUseAsPrompt}>
          Use as next prompt
        </button>
        <span>
          Paste this into the same ChatGPT/Copilot chat with the same PDF attached, then import the second JSON back into AutoQC.
          {sourceBatchId ? ` The next import will be linked as audit round ${auditRound ?? 1} for batch ${sourceBatchId.slice(0, 8)}.` : ""}
        </span>
      </div>
    </aside>
  );
}

function CurrentWorkSummary({
  project,
  sheet,
  findings,
  reviewProgress,
  coverage,
}: {
  project: Project | null;
  sheet: Sheet | null;
  findings: Finding[];
  reviewProgress: { total: number; remaining: number; resolved: number };
  coverage: ReviewCoverageSummary | null;
}) {
  const acceptedCount = countFindingsByStatus(findings, "accepted");
  const manualPlacementCount = findings.filter(
    (finding) => finding.status === "accepted" && findingPlacementStatus(finding) === "manual_placement_needed",
  ).length;
  const exportReady = Boolean(project && acceptedCount > 0);
  const finalReady = Boolean(
    exportReady &&
    coverage?.review_coverage_status === "complete" &&
    manualPlacementCount === 0,
  );
  const exportReadiness = !project
    ? "Select a project"
    : finalReady
      ? "Final-ready"
      : exportReady
        ? "Draft-ready"
        : "Needs accepted findings";

  return (
    <section className="current-work-summary compact-section" aria-label="Current work summary">
      <div className="section-inline-header">
        <div>
          <strong>Current work</strong>
          <span>{project ? project.name : "No review selected"}</span>
        </div>
      </div>
      <div className="current-work-grid">
        <CurrentWorkMetric label="Sheet" value={sheet ? `P${sheet.page_number}` : "None"} detail={sheet ? sheet.drawing_number || sheet.sheet_title || "Untitled" : "Choose a sheet"} />
        <CurrentWorkMetric label="Findings" value={String(findings.length)} detail={`${reviewProgress.remaining} left to review`} />
        <CurrentWorkMetric label="Coverage" value={coverage ? `${coverage.review_coverage_percent}%` : "None"} detail={coverage ? formatStatus(coverage.review_coverage_status) : "not confirmed"} />
        <CurrentWorkMetric label="Export readiness" value={exportReadiness} detail={manualPlacementCount ? `${manualPlacementCount} placement blocker${manualPlacementCount === 1 ? "" : "s"}` : `${acceptedCount} accepted`} />
      </div>
    </section>
  );
}

function CurrentWorkMetric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="current-work-metric">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}

function WorkflowGuide({
  project,
  sheets,
  findings,
  batches,
  events,
  preview,
  onOpenProjects,
  onOpenReview,
  onOpenFindings,
  onOpenExport,
  onGeneratePrompt,
}: {
  project: Project | null;
  sheets: Sheet[];
  findings: Finding[];
  batches: AIImportBatch[];
  events: FindingEvent[];
  preview: AIPreviewResponse | null;
  onOpenProjects: () => void;
  onOpenReview: () => void;
  onOpenFindings: () => void;
  onOpenExport: () => void;
  onGeneratePrompt: () => void;
}) {
  const steps = workflowSteps(project, sheets, findings, batches, events, preview, {
    onOpenProjects,
    onOpenReview,
    onOpenFindings,
    onOpenExport,
    onGeneratePrompt,
  });
  const nextStep = steps.find((step) => step.status === "blocked" || step.status === "ready") ?? steps.find((step) => step.status === "waiting");
  return (
    <section className="workflow-guide compact-section" aria-label="What should I do next">
      <div className="section-inline-header next-action-header">
        <div>
          <strong>What should I do next?</strong>
          <span>{nextStep ? nextStep.label : "Workflow ready"}</span>
          <small>{nextStep ? nextStep.detail : "Workflow is ready for final review records."}</small>
        </div>
        {nextStep?.onAction && nextStep.actionLabel ? (
          <button className="primary-button compact-action" type="button" onClick={nextStep.onAction}>
            <ChevronRight size={14} />
            {nextStep.actionLabel}
          </button>
        ) : null}
      </div>
      <details className="workflow-step-details">
        <summary>Workflow steps</summary>
        <div className="workflow-stepper">
          {steps.map((step) => (
            <button
              type="button"
              className={`workflow-step status-${step.status}`}
              key={step.label}
              onClick={step.onAction}
              disabled={!step.onAction}
              title={step.detail}
            >
              {workflowStatusIcon(step.status)}
              <span>{step.label}</span>
              <small>{formatStatus(step.status)}</small>
            </button>
          ))}
        </div>
      </details>
    </section>
  );
}

function RecoveryCenter({
  project,
  findings,
  batches,
  events,
  preview,
  onOpenProjects,
  onOpenReview,
  onOpenFindings,
  onOpenExport,
  onGeneratePrompt,
  onRecalculatePlacement,
}: {
  project: Project | null;
  findings: Finding[];
  batches: AIImportBatch[];
  events: FindingEvent[];
  preview: AIPreviewResponse | null;
  onOpenProjects: () => void;
  onOpenReview: () => void;
  onOpenFindings: () => void;
  onOpenExport: () => void;
  onGeneratePrompt: () => void;
  onRecalculatePlacement: () => void;
}) {
  const cards = recoveryCards(project, findings, batches, events, preview, {
    onOpenProjects,
    onOpenReview,
    onOpenFindings,
    onOpenExport,
    onGeneratePrompt,
    onRecalculatePlacement,
  });
  return (
    <section className="recovery-center compact-section" aria-label="Recovery Center">
      <div className="section-inline-header">
        <div>
          <strong>Recovery Center</strong>
          <span>{cards.length ? "Items that need attention before a clean final package." : "No active recovery items. Keep reviewing normally."}</span>
        </div>
      </div>
      {cards.length ? (
        <div className="recovery-card-list">
          {cards.map((card) => (
            <div className={`recovery-card severity-${card.severity}`} key={card.id}>
              <div className="recovery-card-header">
                {card.severity === "error" ? <AlertTriangle size={15} /> : card.severity === "warning" ? <AlertTriangle size={15} /> : <ShieldCheck size={15} />}
                <strong>{card.title}</strong>
              </div>
              <p>{card.message}</p>
              <small>State: {card.dataState}</small>
              <small>Next: {card.nextAction}</small>
              <div className="recovery-actions">
                {card.onAction && card.actionLabel ? (
                  <button className="secondary-button compact-action" type="button" onClick={card.onAction}>
                    {card.actionLabel}
                  </button>
                ) : null}
                {card.onSecondaryAction && card.secondaryLabel ? (
                  <button className="secondary-button compact-action" type="button" onClick={card.onSecondaryAction}>
                    {card.secondaryLabel}
                  </button>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function LargePackageReviewPanel({
  plan,
  mode,
  batchSize,
  selectedSheet,
  onModeChange,
  onBatchSizeChange,
  onGenerateNextBatch,
  onDeepDiveSheet,
}: {
  plan: ManualReviewPlan | null;
  mode: LargePackageMode;
  batchSize: number;
  selectedSheet: Sheet | null;
  onModeChange: (mode: LargePackageMode) => void;
  onBatchSizeChange: (size: number) => void;
  onGenerateNextBatch: () => void;
  onDeepDiveSheet: (sheet?: Sheet | null) => void;
}) {
  const nextBatch = nextUnreviewedBatch(plan);
  const nextDeepDive = nextUnreviewedDeepDive(plan);
  const reviewedCount = plan?.reviewed_pages.length ?? 0;
  const sheetCount = plan?.sheet_count ?? 0;
  return (
    <section className="large-package-review compact-section" aria-label="Large Package Review">
      <div className="large-package-header">
        <div>
          <strong>Large Package Review</strong>
          <span>{reviewedCount} of {sheetCount || "?"} pages have review confirmation</span>
        </div>
        <button className="secondary-button compact-action" type="button" onClick={onGenerateNextBatch} disabled={mode !== "hybrid" || !nextBatch} title="Generate the next adaptive batch prompt">
          <Sparkles size={14} />
          Generate Next Batch Prompt
        </button>
      </div>

      <div className="field-grid">
        <label className="field-label">
          Mode
          <select value={mode} onChange={(event) => onModeChange(event.target.value as LargePackageMode)}>
            <option value="hybrid">Hybrid adaptive review</option>
            <option value="package">Whole package prompt</option>
          </select>
        </label>
        <label className="field-label">
          Batch size
          <select value={batchSize} onChange={(event) => onBatchSizeChange(Number(event.target.value))} disabled={mode !== "hybrid"}>
            <option value={3}>3 pages</option>
            <option value={5}>5 pages</option>
            <option value={8}>8 pages</option>
            <option value={10}>10 pages</option>
          </select>
        </label>
      </div>

      <div className="inline-helper">
        Hybrid adaptive review runs every page in batches, then uses single-sheet deep dives for text-heavy or high-risk sheets.
      </div>

      {mode === "hybrid" ? (
        <>
          <div className="review-queue-section">
            <div className="review-queue-heading">
              <strong>Batch Coverage</strong>
              <span>{plan?.batches.length ?? 0} batches</span>
            </div>
            <div className="review-scope-list">
              {(plan?.batches ?? []).slice(0, 8).map((batch) => (
                <div className={`review-scope-row status-${statusClass(batch.status)}`} key={batch.id}>
                  <span>{batch.label}</span>
                  <small>{formatStatus(batch.status)}</small>
                </div>
              ))}
              {(plan?.batches.length ?? 0) > 8 ? <small>{(plan?.batches.length ?? 0) - 8} more batch scopes queued</small> : null}
            </div>
          </div>

          <div className="review-queue-section">
            <div className="review-queue-heading">
              <strong>Sheet Deep Dives</strong>
              <span>{plan?.deep_dive_candidates.length ?? 0} flagged</span>
            </div>
            <div className="review-scope-list">
              {nextDeepDive ? (
                <div className={`review-scope-row status-${statusClass(nextDeepDive.status)}`}>
                  <span>{nextDeepDive.label}</span>
                  <small>{nextDeepDive.reasons.slice(0, 2).join(" | ")}</small>
                </div>
              ) : (
                <small>No unreviewed deep-dive candidates are queued.</small>
              )}
            </div>
          </div>
        </>
      ) : (
        <div className="inline-helper">
          Whole package prompt keeps the original one-pass workflow. Use it only when fewer copy/paste steps matter more than recall.
        </div>
      )}

      <div className="button-row manual-ai-buttons">
        <button className="secondary-button" type="button" onClick={() => onDeepDiveSheet(selectedSheet)} disabled={!selectedSheet} title="Generate a single-sheet prompt for the currently visible sheet">
          <FileText size={15} />
          Deep Dive This Sheet
        </button>
      </div>
    </section>
  );
}

function AIPreviewPanel({ preview }: { preview: AIPreviewResponse | null }) {
  if (!preview) {
    return null;
  }

  const decision = previewImportDecision(preview);

  return (
    <div className="ai-preview-panel" aria-label="AI import preview">
      <div className="preview-summary">
        <strong>{preview.valid_recoverable_updates}</strong>
        <span>valid</span>
        <strong>{preview.skipped_updates}</strong>
        <span>skipped</span>
        <strong>{preview.total_candidate_updates}</strong>
        <span>candidates</span>
      </div>
      <div className="preview-metadata">
        <span>{preview.schema_version ?? "autoqc-ai-updates-v1"}</span>
        <span>{formatStatus(preview.parser_mode ?? "parser unknown")}</span>
        <span>{formatStatus(preview.response_shape ?? "shape unknown")}</span>
        {preview.review_scope ? <span>{formatStatus(preview.review_scope)}</span> : null}
      </div>
      <div className={`preview-decision ${decision.status}`} role={decision.status === "blocked" ? "alert" : "status"}>
        {decision.status === "ready" ? <Check size={15} /> : <AlertTriangle size={15} />}
        <div>
          <strong>{decision.title}</strong>
          <span>{decision.detail}</span>
        </div>
      </div>
      <div className={`coverage-banner coverage-${statusClass(preview.review_coverage_status ?? "not_confirmed")}`} role="status">
        <strong>Review coverage {formatStatus(preview.review_coverage_status ?? "not_confirmed")}</strong>
        <span>{preview.review_coverage_percent ?? 0}% | expected {formatPageList(preview.expected_review_pages)} | confirmed {formatPageList(preview.reviewed_pages_confirmed ?? preview.reviewed_page_numbers)}</span>
        {preview.missing_review_pages?.length ? <small>Missing: {formatPageList(preview.missing_review_pages)}</small> : null}
        {preview.incomplete_review_pages?.length ? <small>Incomplete: {formatPageList(preview.incomplete_review_pages)}</small> : null}
        {preview.not_readable_pages?.length ? <small>Not readable: {formatPageList(preview.not_readable_pages)}</small> : null}
      </div>

      {preview.quality_report ? (
        <div className="import-quality-report" aria-label="Import Quality Report">
          <strong>Import Quality Report</strong>
          <div className="quality-grid">
            {importQualityRows(preview.quality_report).map((row) => (
              <span key={row.label}>
                <strong>{row.value}</strong>
                {row.label}
              </span>
            ))}
          </div>
          <div className="inline-helper">
            AI response coverage: pages with returned updates {formatPageList(preview.quality_report.pages_with_returned_updates)}.
            Pages confirmed reviewed {formatPageList(preview.quality_report.reviewed_pages_confirmed ?? preview.quality_report.pages_reviewed)}.
            Pages with no returned updates {formatPageList(preview.quality_report.pages_without_returned_updates)}.
            This is response coverage only; it does not prove those pages are clean. Clean pages only count when reviewed_pages confirms review_status complete.
          </div>
          {preview.scoped_review_complete ? (
            <div className="inline-helper success-helper">
              Scoped review complete for {formatPageList(preview.scope_pages)}.
            </div>
          ) : preview.pages_without_review_confirmation?.length ? (
            <div className="inline-helper warning-helper">
              Missing reviewed_pages confirmation for {formatPageList(preview.pages_without_review_confirmation)}.
            </div>
          ) : null}
        </div>
      ) : null}

      {preview.parser_repairs_applied.length > 0 ? (
        <div className="preview-note-list">
          <strong>Parser repairs</strong>
          {preview.parser_repairs_applied.map((repair) => (
            <span key={repair}>{repair}</span>
          ))}
        </div>
      ) : null}

      {preview.warnings.length > 0 ? (
        <div className="preview-note-list warning-list">
          <strong>Warnings</strong>
          {preview.warnings.slice(0, 8).map((warning) => (
            <span key={warning}>{warning}</span>
          ))}
        </div>
      ) : null}

      <div className="preview-update-list">
        {preview.updates.map((update) => (
          <div className={`preview-update ${update.will_import ? "importable" : "skipped"}`} key={`${preview.batch_id}-${update.index}`}>
            <div className="preview-update-header">
              <strong>
                #{update.index} {previewActionLabel(update.action)}
              </strong>
              <span>{update.page_number ? `Page ${update.page_number}` : "No page"}</span>
            </div>
            <span>{update.target_text || "No target text"}</span>
            <small>{update.required_update || update.skipped_reason || "No required update"}</small>
            <small>{[update.category, update.severity, confidenceText(update.confidence)].filter(Boolean).join(" | ")}</small>
            {update.duplicate_reason ? (
              <small>
                {update.duplicate_kind === "exact" ? "Exact duplicate" : "Likely duplicate"}: {update.duplicate_reason}
                {update.related_update_indices?.length ? ` Related update ${update.related_update_indices.join(", ")}` : ""}
              </small>
            ) : null}
            {update.missing_or_weak_fields?.length ? (
              <small>Weak fields: {update.missing_or_weak_fields.join(", ")}</small>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}

function AIResponsePreflightPanel({ assessment }: { assessment: AIResponseAssessment }) {
  const hasContent = assessment.blocking.length > 0 || assessment.warnings.length > 0 || assessment.confirmations.length > 0;
  if (!hasContent) {
    return null;
  }

  return (
    <div className="ai-response-preflight" role="status" aria-label="AI response preflight">
      {assessment.blocking.map((item) => (
        <span className="preflight-blocking" key={item}>
          <AlertTriangle size={13} />
          {item}
        </span>
      ))}
      {assessment.warnings.map((warning) => (
        <span className="preflight-warning" key={`${warning.title}-${warning.detail}`}>
          <AlertTriangle size={13} />
          <strong>{warning.title}</strong>
          {warning.detail}
        </span>
      ))}
      {assessment.confirmations.map((item) => (
        <span className="preflight-ok" key={item}>
          <Check size={13} />
          {item}
        </span>
      ))}
    </div>
  );
}

function AIImportHistory({
  batches,
  rollingBackBatchId,
  onRollbackBatch,
}: {
  batches: AIImportBatch[];
  rollingBackBatchId: string | null;
  onRollbackBatch: (batch: AIImportBatch) => Promise<void>;
}) {
  if (!batches.length) {
    return null;
  }

  return (
    <details className="ai-history-panel collapsible-section" aria-label="Recent AI import batches">
      <summary>
        <span>
          <strong>AI Import History</strong>
          <small>{batches.length} batch{batches.length === 1 ? "" : "es"}</small>
        </span>
      </summary>
      <div className="history-list">
        {batches.slice(0, 5).map((batch) => (
          <div className="history-row" key={batch.id}>
            <div>
              <strong>{formatStatus(batch.import_status)}</strong>
              <span>
                {batch.valid_count} valid | {batch.skipped_count} skipped | {batch.created_count} new | {batch.updated_count} updated
              </span>
            </div>
            <small>{batch.prompt_version || batch.source_type || "unknown"} | {formatDate(batch.imported_at || batch.created_at)}</small>
            {batch.metadata?.prompt_template_name ? <small>{String(batch.metadata.prompt_template_name)}</small> : null}
            {batch.raw_response_stored ? (
              <small>Raw response stored server-side ({batch.raw_response_length ?? 0} chars, sha256 {String(batch.raw_response_sha256 ?? "").slice(0, 12) || "unavailable"})</small>
            ) : null}
            {batch.metadata?.review_modality ? <small>Review modality: {reviewModalityLabel(String(batch.metadata.review_modality))}</small> : null}
            {batch.metadata?.audit_of_batch_id ? (
              <small>
                Missed-issue audit round {String(batch.metadata.audit_round ?? 1)} of batch {String(batch.metadata.audit_of_batch_id).slice(0, 8)}
                {" | "}yield {String(batch.metadata.audit_yield_count ?? 0)}
              </small>
            ) : null}
            {batch.metadata?.direct_review_mode === "text_context_only" ? <small>Direct AI Review: text-context-only, experimental.</small> : null}
            {batch.parser_warnings?.length ? <small>{batch.parser_warnings[0]}</small> : null}
            {batch.import_status === "imported" ? (
              <button
                className="danger-button compact-action"
                type="button"
                disabled={rollingBackBatchId === batch.id}
                onClick={() => void onRollbackBatch(batch)}
                title="Remove findings created by this imported AI batch after confirmation"
              >
                {rollingBackBatchId === batch.id ? <Loader2 size={14} className="spin" /> : <Trash2 size={14} />}
                Remove imported batch
              </button>
            ) : null}
          </div>
        ))}
      </div>
    </details>
  );
}

function previewActionLabel(action?: string): string {
  if (action === "create_new") {
    return "Create new";
  }
  if (action === "update_existing") {
    return "Update existing";
  }
  if (action === "duplicate_in_response") {
    return "Duplicate";
  }
  return "Skipped";
}

function previewImportDecision(preview: AIPreviewResponse): { status: "ready" | "blocked" | "warning"; title: string; detail: string } {
  if (preview.review_coverage_status !== "complete") {
    return {
      status: "blocked",
      title: "Import blocked by coverage",
      detail: `Ask the AI tool to return reviewed_pages for every expected page. Missing pages: ${formatPageList(preview.missing_review_pages)}.`,
    };
  }
  if (preview.valid_recoverable_updates === 0 && preview.scoped_review_complete) {
    return {
      status: "ready",
      title: "Ready to record clean review",
      detail: "The response confirmed the scoped pages were reviewed and returned no importable updates.",
    };
  }
  if (preview.valid_recoverable_updates === 0) {
    return {
      status: "blocked",
      title: "No importable updates",
      detail: "Review skipped reasons below. Most often this means missing target_text, required_update, or usable page numbers.",
    };
  }
  if (preview.skipped_updates > 0 || preview.duplicate_updates) {
    return {
      status: "warning",
      title: "Ready with review warnings",
      detail: `${preview.valid_recoverable_updates} update${preview.valid_recoverable_updates === 1 ? "" : "s"} can import; ${preview.skipped_updates} skipped and ${preview.duplicate_updates ?? 0} duplicate.`,
    };
  }
  return {
    status: "ready",
    title: "Ready to import",
    detail: `${preview.valid_recoverable_updates} AI update${preview.valid_recoverable_updates === 1 ? "" : "s"} passed field, duplicate, and coverage checks.`,
  };
}

function reviewModalityLabel(value: string): string {
  if (value === "manual_pdf_attached_external") {
    return "manual PDF-attached external";
  }
  if (value === "text_context_only") {
    return "text-context-only";
  }
  if (value === "pdf_image_direct") {
    return "direct PDF/image";
  }
  return value;
}

function confidenceText(value?: number | null): string {
  return typeof value === "number" ? confidenceLabel(value) : "";
}

function importQualityRows(report: ImportQualityReport): Array<{ label: string; value: number }> {
  return [
    { label: "parsed", value: report.total_updates_parsed },
    { label: "importable", value: report.total_importable_updates },
    { label: "imported", value: report.imported_findings },
    { label: "skipped", value: report.skipped_updates },
    { label: "duplicates", value: report.duplicate_count },
    { label: "missing page", value: report.missing_page_number_count },
    { label: "missing target", value: report.missing_target_text_count },
    { label: "exact", value: report.exact_placement_count },
    { label: "fuzzy", value: report.fuzzy_placement_count },
    { label: "page-level", value: report.page_level_fallback_count },
    { label: "manual needed", value: report.manual_placement_needed_count },
    { label: "low confidence", value: report.low_confidence_count },
    { label: "pages w/ updates", value: report.pages_with_imported_updates_count ?? report.pages_with_returned_updates_count ?? 0 },
    { label: "pages no return", value: report.pages_without_returned_updates_count ?? 0 },
  ];
}

function formatPageList(pages?: number[]): string {
  if (!pages || pages.length === 0) {
    return "none";
  }
  const shown = pages.slice(0, 12).join(", ");
  return pages.length > 12 ? `${shown}, +${pages.length - 12} more` : shown;
}

function assessUploadInput(projectName: string, file: File | null): UploadAssessment {
  const errors: string[] = [];
  const warnings: NoticeItem[] = [];
  const trimmedName = projectName.trim();
  if (trimmedName.length > 120) {
    errors.push("Keep the project name under 120 characters so exports and packages have readable filenames.");
  }
  if (/[<>:"\/\\|?*\x00-\x1F]/.test(trimmedName)) {
    errors.push("Project names cannot contain path characters such as /, \\, :, *, ?, <, >, or |.");
  }
  if (/^(test|demo|sample|project|review)$/i.test(trimmedName)) {
    warnings.push({
      title: "Generic project name",
      detail: "Use a package, station, or job identifier so exported reports are traceable.",
    });
  }

  if (!file) {
    errors.push("Select a PDF drawing package before uploading.");
    return { errors, warnings };
  }

  const lowerName = file.name.toLowerCase();
  const looksLikePdf = file.type === "application/pdf" || lowerName.endsWith(".pdf");
  if (!looksLikePdf) {
    errors.push("AutoQC only accepts PDF drawing packages. Choose a .pdf file.");
  }
  if (file.size <= 0) {
    errors.push("The selected PDF is empty. Choose the actual drawing package file.");
  }
  const maxBytes = MAX_UPLOAD_MB * 1024 * 1024;
  if (file.size > maxBytes) {
    errors.push(`The selected PDF is ${formatBytes(file.size)}, above the ${MAX_UPLOAD_MB} MB local upload limit.`);
  }
  if (file.size > LARGE_UPLOAD_WARNING_MB * 1024 * 1024 && file.size <= maxBytes) {
    warnings.push({
      title: "Large package",
      detail: "Extraction can take several minutes. Keep the browser open until the upload operation finishes.",
    });
  }
  if (/\.(pdf)\.[a-z0-9]+$/i.test(file.name)) {
    warnings.push({
      title: "Unexpected filename",
      detail: "The file has another extension after .pdf. Confirm this is the original drawing package, not a renamed export.",
    });
  }
  if (/(draft|prelim|preliminary|not[-_\s]?for[-_\s]?construction|superseded|void|obsolete)/i.test(file.name) || /(draft|prelim|preliminary|superseded|void|obsolete)/i.test(trimmedName)) {
    warnings.push({
      title: "Issue-status caution",
      detail: "This package name suggests a draft or superseded set. Keep exports in draft mode unless the responsible reviewer confirms it is appropriate for final signoff.",
    });
  }
  return { errors, warnings };
}

function assessManualAIResponse(text: string): AIResponseAssessment {
  const trimmed = text.trim();
  const blocking: string[] = [];
  const warnings: NoticeItem[] = [];
  const confirmations: string[] = [];
  if (!trimmed) {
    return { blocking, warnings, confirmations };
  }

  const lower = trimmed.toLowerCase();
  const looksLikePrompt =
    /you are acting as|manual review instructions|required response schema|autoqc enhanced manual review prompt|pages in scope/i.test(trimmed)
    && /attach(ed)? pdf|chatgpt|copilot|return only valid json/i.test(trimmed);
  if (looksLikePrompt) {
    blocking.push("This looks like the prompt text, not the AI response. Run it in ChatGPT/Copilot with the PDF attached, then paste the returned JSON.");
    return { blocking, warnings, confirmations };
  }

  if (!trimmed.startsWith("{") && !trimmed.startsWith("[") && !trimmed.startsWith("```")) {
    warnings.push({
      title: "Response wrapper",
      detail: "Preview can sometimes recover JSON from surrounding text, but safest input is the raw JSON object only.",
    });
  }
  if (!lower.includes("reviewed_pages")) {
    warnings.push({
      title: "Missing reviewed_pages",
      detail: "Imports and final coverage need reviewed_pages entries for every scoped page, including clean pages.",
    });
  } else {
    confirmations.push("reviewed_pages field detected.");
  }
  if (!lower.includes("updates")) {
    warnings.push({
      title: "Missing updates array",
      detail: "The response should include an updates array, even when no issues were found.",
    });
  } else {
    confirmations.push("updates field detected.");
  }
  if (!lower.includes("schema_version")) {
    warnings.push({
      title: "Schema version not visible",
      detail: "Expected schema_version is autoqc-ai-updates-v1. Preview will still try to parse compatible JSON.",
    });
  }
  if (!lower.includes("target_text")) {
    warnings.push({
      title: "No target_text found",
      detail: "Updates without exact visible drawing text are skipped because they cannot be placed credibly on the PDF.",
    });
  }
  if (!lower.includes("required_update") && !lower.includes("recommended_update")) {
    warnings.push({
      title: "No required_update found",
      detail: "Each update needs a specific drawing change request before it can become a useful finding.",
    });
  }
  if (/"confidence"\s*:\s*"(high|medium|low)"/i.test(trimmed)) {
    warnings.push({
      title: "Text confidence",
      detail: "The preferred confidence format is numeric from 0.0 to 1.0; preview may still normalize common values.",
    });
  }
  if (trimmed.length > 1_500_000) {
    warnings.push({
      title: "Very large response",
      detail: "Large pasted responses are slower to parse. Consider using smaller page batches if preview feels sluggish.",
    });
  }
  return { blocking, warnings, confirmations };
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value >= 10 || index === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[index]}`;
}

function nextUnreviewedBatch(plan: ManualReviewPlan | null): ManualReviewBatch | null {
  return plan?.batches.find((batch) => batch.status !== "reviewed") ?? null;
}

function nextUnreviewedDeepDive(plan: ManualReviewPlan | null): ManualReviewDeepDiveCandidate | null {
  return plan?.deep_dive_candidates.find((candidate) => candidate.status !== "reviewed") ?? null;
}

function latestImportCoverage(batch?: AIImportBatch | null): ReviewCoverageSummary | null {
  const coverage = batch?.metadata?.review_coverage;
  if (typeof coverage === "object" && coverage) {
    return coverage as ReviewCoverageSummary;
  }
  return null;
}

function workflowStatusIcon(status: WorkflowStepStatus) {
  if (status === "done") {
    return <Check size={14} />;
  }
  if (status === "blocked") {
    return <AlertTriangle size={14} />;
  }
  if (status === "ready") {
    return <ChevronRight size={14} />;
  }
  return <History size={14} />;
}

function workflowSteps(
  project: Project | null,
  sheets: Sheet[],
  findings: Finding[],
  batches: AIImportBatch[],
  events: FindingEvent[],
  preview: AIPreviewResponse | null,
  actions: {
    onOpenProjects: () => void;
    onOpenReview: () => void;
    onOpenFindings: () => void;
    onOpenExport: () => void;
    onGeneratePrompt: () => void;
  },
): WorkflowStep[] {
  const importedBatch = batches.find((batch) => batch.import_status === "imported");
  const promptGenerated = events.some((event) => event.action === "manual_ai_prompt_generated");
  const draftExported = events.some((event) => event.action === "draft_export_created" || event.action === "export_created");
  const latestFinalEvent = events.find((event) => event.action === "final_export_created" || event.action === "final_export_blocked");
  const finalExported = latestFinalEvent?.action === "final_export_created";
  const coverage = project?.review_coverage ?? latestImportCoverage(importedBatch);
  const coverageComplete = coverage?.review_coverage_status === "complete";
  const needsReview = countFindingsByStatus(findings, "needs_review");
  const accepted = countFindingsByStatus(findings, "accepted");
  const manualPlacement = manualPlacementBlockerCount(findings);

  return [
    {
      label: "Upload PDF",
      status: project && sheets.length ? "done" : "ready",
      detail: project && sheets.length ? `${sheets.length} sheets extracted.` : "Upload a PDF drawing package or create the sample project.",
      actionLabel: project && sheets.length ? undefined : "Open Projects",
      onAction: project && sheets.length ? undefined : actions.onOpenProjects,
    },
    {
      label: "Build Prompt",
      status: !project ? "blocked" : promptGenerated || preview || importedBatch ? "done" : "ready",
      detail: !project ? "Select or upload a project first." : "Generate the manual Chat Prompt for ChatGPT/Copilot and attach the source PDF there.",
      actionLabel: !project ? "Open Projects" : "Generate Prompt",
      onAction: !project ? actions.onOpenProjects : actions.onGeneratePrompt,
    },
    {
      label: "Attach PDF externally",
      status: promptGenerated || preview || importedBatch ? "ready" : "waiting",
      detail: "Open ChatGPT/Copilot, attach the same source PDF, paste the prompt, and copy the JSON response back into AutoQC.",
      actionLabel: "Open Review",
      onAction: actions.onOpenReview,
    },
    {
      label: "Preview JSON",
      status: preview ? (preview.review_coverage_status === "complete" ? "done" : "blocked") : importedBatch ? "done" : "waiting",
      detail: preview
        ? preview.review_coverage_status === "complete"
          ? "Preview coverage is complete."
          : `Preview is missing reviewed_pages confirmation for ${formatPageList(preview.missing_review_pages)}.`
        : "Paste or import the AI JSON response, then preview before importing.",
      actionLabel: "Open Review",
      onAction: actions.onOpenReview,
    },
    {
      label: "Import Updates",
      status: importedBatch ? "done" : preview?.review_coverage_status === "complete" ? "ready" : preview ? "blocked" : "waiting",
      detail: importedBatch ? "At least one AI batch has been imported." : preview?.review_coverage_status === "complete" ? "Preview is ready to import." : "Import remains blocked until coverage is complete.",
      actionLabel: "Open Review",
      onAction: actions.onOpenReview,
    },
    {
      label: "Review Findings",
      status: findings.length === 0 ? "waiting" : needsReview === 0 ? "done" : "ready",
      detail: findings.length === 0 ? "No AI findings are imported yet." : `${needsReview} finding${needsReview === 1 ? "" : "s"} still need reviewer disposition.`,
      actionLabel: "Open Findings",
      onAction: findings.length ? actions.onOpenFindings : actions.onOpenReview,
    },
    {
      label: "Resolve Placement",
      status: findings.length === 0 ? "waiting" : manualPlacement === 0 ? "done" : "blocked",
      detail: manualPlacement === 0 ? "No manual placement blockers are currently detected." : `${manualPlacement} finding${manualPlacement === 1 ? "" : "s"} still need placement attention.`,
      actionLabel: manualPlacement ? "Open Findings" : undefined,
      onAction: manualPlacement ? actions.onOpenFindings : undefined,
    },
    {
      label: "Draft Export",
      status: draftExported ? "done" : findings.length ? "ready" : "waiting",
      detail: draftExported ? "A draft export has been created." : "Create a draft export for internal review when findings are ready.",
      actionLabel: "Open Export",
      onAction: actions.onOpenExport,
    },
    {
      label: "Final Export",
      status: finalExported ? "done" : coverageComplete && accepted > 0 && manualPlacement === 0 ? "ready" : "blocked",
      detail: finalExported
        ? "A final export has been created."
        : finalExportBlockerSummary(coverage, accepted, manualPlacement),
      actionLabel: "Open Export",
      onAction: actions.onOpenExport,
    },
  ];
}

function recoveryCards(
  project: Project | null,
  findings: Finding[],
  batches: AIImportBatch[],
  events: FindingEvent[],
  preview: AIPreviewResponse | null,
  actions: {
    onOpenProjects: () => void;
    onOpenReview: () => void;
    onOpenFindings: () => void;
    onOpenExport: () => void;
    onGeneratePrompt: () => void;
    onRecalculatePlacement: () => void;
  },
): RecoveryCard[] {
  const cards: RecoveryCard[] = [];
  const latestFailedBatch = batches.find((batch) => batch.import_status === "failed");
  const latestFinalEvent = events.find((event) => event.action === "final_export_created" || event.action === "final_export_blocked");
  const latestFinalBlock = latestFinalEvent?.action === "final_export_blocked" ? latestFinalEvent : undefined;
  const coverage = project?.review_coverage;
  const manualPlacement = manualPlacementBlockerCount(findings);
  const importedBatch = batches.find((batch) => batch.import_status === "imported");

  if (latestFailedBatch) {
    const failure = latestFailedBatch.metadata?.import_failure as Record<string, unknown> | undefined;
    cards.push({
      id: `failed-import-${latestFailedBatch.id}`,
      severity: "error",
      title: "AI import failed",
      message: String(failure?.message ?? "The latest import did not complete."),
      dataState: String(failure?.recovery ?? "Check the import batch before retrying."),
      nextAction: "Preview the AI response again or generate a fresh Chat Prompt before importing.",
      actionLabel: "Open Review",
      onAction: actions.onOpenReview,
      secondaryLabel: "Generate Prompt",
      onSecondaryAction: actions.onGeneratePrompt,
    });
  }

  if (preview && preview.review_coverage_status !== "complete") {
    cards.push({
      id: `preview-coverage-${preview.batch_id}`,
      severity: "warning",
      title: "Preview coverage incomplete",
      message: `Missing reviewed_pages confirmation for ${formatPageList(preview.missing_review_pages)}.`,
      dataState: "No findings have been imported from this preview.",
      nextAction: "Ask the AI tool to return reviewed_pages for every expected page, then preview the response again.",
      actionLabel: "Open Review",
      onAction: actions.onOpenReview,
      secondaryLabel: "Generate Prompt",
      onSecondaryAction: actions.onGeneratePrompt,
    });
  }

  if (project && coverage && coverage.review_coverage_status !== "complete") {
    cards.push({
      id: "package-coverage",
      severity: "warning",
      title: "Package coverage incomplete",
      message: reviewCoverageBlockerText(coverage),
      dataState: importedBatch ? "Imported coverage is partial." : "No imported complete coverage confirmation yet.",
      nextAction: "Generate the next Chat Prompt scope and import a response with complete reviewed_pages.",
      actionLabel: "Generate Prompt",
      onAction: actions.onGeneratePrompt,
      secondaryLabel: "Open Review",
      onSecondaryAction: actions.onOpenReview,
    });
  }

  if (manualPlacement > 0) {
    cards.push({
      id: "manual-placement",
      severity: "warning",
      title: "Manual placement needed",
      message: `${manualPlacement} finding${manualPlacement === 1 ? "" : "s"} need placement attention before final export.`,
      dataState: "Draft export can continue; final export will block until placement is resolved.",
      nextAction: "Recalculate placement or open the findings list and place markups manually.",
      actionLabel: "Recalculate",
      onAction: actions.onRecalculatePlacement,
      secondaryLabel: "Open Findings",
      onSecondaryAction: actions.onOpenFindings,
    });
  }

  if (latestFinalBlock) {
    cards.push({
      id: `final-block-${latestFinalBlock.id}`,
      severity: "warning",
      title: "Final export was blocked",
      message: String((latestFinalBlock.changes as Record<string, unknown> | undefined)?.reason ?? "Final export readiness was not complete."),
      dataState: "No final export was created from the blocked attempt.",
      nextAction: "Open the export requirements and resolve the blocked item before trying again.",
      actionLabel: "Open Export",
      onAction: actions.onOpenExport,
    });
  }

  if (project && !project.source_pdf_url && !project.source_pdf_path) {
    cards.push({
      id: "missing-source-pdf",
      severity: "error",
      title: "Source PDF missing",
      message: "AutoQC cannot open the original PDF for source review or marked export.",
      dataState: "Project metadata exists, but the source PDF path is unavailable.",
      nextAction: "Restore a valid project package with source PDF or upload the package again.",
      actionLabel: "Open Projects",
      onAction: actions.onOpenProjects,
    });
  }

  if (project && findings.length === 0 && !importedBatch) {
    cards.push({
      id: "no-ai-findings",
      severity: "info",
      title: "No AI findings imported yet",
      message: "Upload/extraction does not create reviewer-visible findings by itself.",
      dataState: "The app is waiting for imported AI JSON or clean reviewed_pages confirmation.",
      nextAction: "Generate a Chat Prompt, attach the source PDF externally, preview the response, then import.",
      actionLabel: "Generate Prompt",
      onAction: actions.onGeneratePrompt,
    });
  }

  return cards.slice(0, 5);
}

function manualPlacementBlockerCount(findings: Finding[]): number {
  return findings.filter((finding) => finding.status === "needs_manual_placement" || findingPlacementStatus(finding) === "manual_placement_needed").length;
}

function reviewCoverageBlockerText(coverage: ReviewCoverageSummary): string {
  const parts = [
    coverage.missing_review_pages.length ? `missing pages ${formatPageList(coverage.missing_review_pages)}` : null,
    coverage.incomplete_review_pages.length ? `incomplete pages ${formatPageList(coverage.incomplete_review_pages)}` : null,
    coverage.not_readable_pages.length ? `not-readable pages ${formatPageList(coverage.not_readable_pages)}` : null,
  ].filter((item): item is string => Boolean(item));
  if (parts.length === 0) {
    return `Coverage is ${formatStatus(coverage.review_coverage_status)} at ${coverage.review_coverage_percent}%.`;
  }
  return `Coverage is ${formatStatus(coverage.review_coverage_status)}: ${parts.join("; ")}.`;
}

function finalExportBlockerSummary(coverage: ReviewCoverageSummary | null | undefined, acceptedCount: number, manualPlacementCount: number): string {
  const blockers = [];
  if (!coverage || coverage.review_coverage_status !== "complete") {
    blockers.push(coverage ? reviewCoverageBlockerText(coverage) : "review coverage is not confirmed");
  }
  if (acceptedCount === 0) {
    blockers.push("no accepted findings are selected");
  }
  if (manualPlacementCount > 0) {
    blockers.push(`${manualPlacementCount} finding${manualPlacementCount === 1 ? "" : "s"} need manual placement`);
  }
  return blockers.length ? `Final export blocked: ${blockers.join("; ")}.` : "Final export readiness is complete.";
}

function finalReviewerNameIssue(value: string): string | null {
  const trimmed = value.trim();
  if (trimmed.length < 2) {
    return "Enter the responsible reviewer name before creating a final export.";
  }
  if (/^(local reviewer|reviewer|engineer|user|test|demo)$/i.test(trimmed)) {
    return "Replace the placeholder reviewer name with the responsible reviewer or engineer.";
  }
  if (/[<>:"\/\\|?*\x00-\x1F]/.test(trimmed)) {
    return "Reviewer name cannot contain path characters such as /, \\, :, *, ?, <, >, or |.";
  }
  return null;
}

function exportResultTitle(result: ExportResponse): string {
  const mode = result.export_mode === "final" ? "Final export" : "Draft export";
  const validation = validationStatusLabel(result.validation?.status ?? "not_reported").toLowerCase();
  return `${mode} created with ${validation} validation`;
}

function exportResultExplanation(result: ExportResponse): string {
  const count = result.findings_exported ?? 0;
  const validation = result.validation?.status ?? "not_reported";
  if (result.export_mode === "final") {
    return `Final package includes ${count} accepted finding${count === 1 ? "" : "s"} with reviewer signoff. Open the marked PDF and QA report before external issue.`;
  }
  if (validation === "failed") {
    return `Draft package was written, but PDF validation failed. Do not rely on the marked PDF until the validation errors are resolved.`;
  }
  if (validation === "warning") {
    return `Draft package includes ${count} finding${count === 1 ? "" : "s"} and has validation warnings. Review the warnings before using the PDF.`;
  }
  return `Draft package includes ${count} finding${count === 1 ? "" : "s"}. Use final export only after accepted findings, complete coverage, placement cleanup, and signoff.`;
}

function DashboardSummary({
  project,
  findings,
  batches,
  events,
  placementSummary,
}: {
  project: Project | null;
  findings: Finding[];
  batches: AIImportBatch[];
  events: FindingEvent[];
  placementSummary: PlacementSummary;
}) {
  const latestImport = batches.find((batch) => batch.import_status === "imported") ?? batches[0];
  const latestExport = events.find((event) => ["draft_export_created", "final_export_created", "export_created"].includes(event.action));
  const statusCounts = {
    total: findings.length,
    needsReview: countFindingsByStatus(findings, "needs_review"),
    accepted: countFindingsByStatus(findings, "accepted"),
    rejected: countFindingsByStatus(findings, "rejected"),
  };
  const manualPlacement = placementSummary.manual_placement_needed ?? 0;
  const accepted = statusCounts.accepted;
  const reviewCoverage = project?.review_coverage ?? latestImportCoverage(latestImport);
  const warnings = [
    findings.length === 0 ? "No AI findings imported." : null,
    reviewCoverage && reviewCoverage.review_coverage_status !== "complete" ? "Package review coverage is incomplete." : null,
    manualPlacement > Math.max(2, findings.length * 0.35) ? "Many findings need manual placement." : null,
    accepted === 0 ? "No accepted findings selected for accepted-only export." : null,
    project && !project.source_pdf_url && !project.source_pdf_path ? "Source PDF missing or unavailable." : null,
    latestImport?.metadata?.direct_review_mode === "text_context_only" ? "Latest imported batch used text-context-only Direct AI Review." : null,
    latestExport?.changes?.validation_status === "failed" ? "Latest export validation failed." : null,
  ].filter((item): item is string => Boolean(item));

  return (
    <section className="dashboard-summary compact-section" aria-label="Management review dashboard">
      <div className="dashboard-grid">
        <DashboardMetric label="Total" value={statusCounts.total} />
        <DashboardMetric label="Needs review" value={statusCounts.needsReview} />
        <DashboardMetric label="Accepted" value={statusCounts.accepted} />
        <DashboardMetric label="Rejected" value={statusCounts.rejected} />
      </div>
      <div className="dashboard-detail">
        <span>{placementSummaryText(placementSummary)}</span>
        <span>Review coverage: {reviewCoverage ? `${formatStatus(reviewCoverage.review_coverage_status)} ${reviewCoverage.review_coverage_percent}%` : "not confirmed"}</span>
        <span>Latest import: {latestImport ? `${formatStatus(latestImport.import_status)} ${formatDate(latestImport.imported_at || latestImport.created_at)}` : "none"}</span>
        <span>Latest export: {latestExport ? formatDate(latestExport.created_at) : "none"}</span>
      </div>
      {warnings.length ? (
        <div className="dashboard-warnings" role="status">
          {warnings.map((warning) => (
            <span key={warning}><AlertTriangle size={13} /> {warning}</span>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function DashboardMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="dashboard-metric">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

function ReadinessPanel({ readiness, onRefresh }: { readiness: ReadinessResponse | null; onRefresh: () => Promise<void> }) {
  return (
    <details className="readiness-panel collapsible-section" aria-label="System Check panel">
      <summary>
        <span>
          <strong>System Check</strong>
          <small>{readiness ? formatStatus(readiness.status) : "Not loaded"}</small>
        </span>
      </summary>
      <div className="readiness-actions">
        <button className="secondary-button compact-action" type="button" onClick={() => void onRefresh()} title="Run local readiness checks again">
          <RefreshCw size={14} />
          Refresh
        </button>
      </div>
      {readiness?.summary ? <div className="inline-helper">{readiness.summary}</div> : null}
      <div className="readiness-list">
        {(readiness?.checks ?? []).map((check) => (
          <div className={`readiness-row ${check.ok ? "passed" : "warning"}`} key={check.name}>
            {check.ok ? <Check size={14} /> : <AlertTriangle size={14} />}
            <span>{check.name}</span>
            <small>{check.detail}</small>
          </div>
        ))}
      </div>
      {readiness?.instructions ? (
        <div className="readiness-instructions">
          {Object.entries(readiness.instructions).map(([label, command]) => (
            <code key={label}>{command}</code>
          ))}
        </div>
      ) : null}
    </details>
  );
}

function AuditLogPanel({ events }: { events: FindingEvent[] }) {
  if (!events.length) {
    return null;
  }
  return (
    <details className="audit-log-panel collapsible-section" aria-label="Full audit log">
      <summary>
        <span>
          <strong>Audit Log</strong>
          <small>{events.length} recent event{events.length === 1 ? "" : "s"}</small>
        </span>
      </summary>
      <div className="audit-log-list">
        {events.map((event) => (
          <div className="audit-row full" key={event.id}>
            <span>{humanAuditAction(event)}</span>
            <small>Local reviewer | {formatDate(event.created_at)}</small>
            {event.changes ? <code>{auditChangeSummary(event.changes)}</code> : null}
          </div>
        ))}
      </div>
    </details>
  );
}

interface AdvancedFeaturesPanelProps {
  project: Project | null;
  batches: AIImportBatch[];
  events: FindingEvent[];
  readiness: ReadinessResponse | null;
  settings: MarkupMemorySettings | null;
  stats: MarkupMemoryStats | null;
  preview: MarkupMemoryPreview | null;
  loading: boolean;
  saving: boolean;
  rebuilding: boolean;
  clearing: boolean;
  runningAIReview: boolean;
  creatingSample: boolean;
  exportingPackage: boolean;
  importingPackage: boolean;
  rollingBackBatchId: string | null;
  onRefresh: () => Promise<void>;
  onUpdateSettings: (update: MarkupMemorySettingsUpdate) => Promise<void>;
  onRebuild: () => Promise<void>;
  onClear: () => Promise<void>;
  onRunAIReview: () => Promise<void>;
  onRefreshReadiness: () => Promise<void>;
  onRollbackBatch: (batch: AIImportBatch) => Promise<void>;
  onSampleProject: () => Promise<void>;
  onExportPackage: () => Promise<void>;
  onImportPackage: (file: File | null) => Promise<void>;
}

function AdvancedFeaturesPanel({
  project,
  batches,
  events,
  readiness,
  settings,
  stats,
  preview,
  loading,
  saving,
  rebuilding,
  clearing,
  runningAIReview,
  creatingSample,
  exportingPackage,
  importingPackage,
  rollingBackBatchId,
  onRefresh,
  onUpdateSettings,
  onRebuild,
  onClear,
  onRunAIReview,
  onRefreshReadiness,
  onRollbackBatch,
  onSampleProject,
  onExportPackage,
  onImportPackage,
}: AdvancedFeaturesPanelProps) {
  const disabled = loading || saving || !settings;
  const categoryRows = Object.entries(stats?.examples_by_category ?? {}).slice(0, 6);

  return (
    <section className="panel advanced-features-panel" aria-label="Advanced Features">
      <div className="panel-header">
        <div>
          <span className="eyebrow">Experimental / Power User Tools</span>
          <h2>Advanced Features</h2>
        </div>
        <ShieldCheck size={18} />
      </div>

      <div className="advanced-body">
        <section className="advanced-section" aria-label="Advanced review tools">
          <div className="advanced-section-header">
            <div>
              <strong>Power-user review tools</strong>
              <span>Diagnostics and experimental workflows outside the normal MVP path</span>
            </div>
          </div>
          <div className="button-row advanced-actions">
            <button
              className="secondary-button experimental-ai-action"
              type="button"
              disabled={!project || runningAIReview}
              title="Experimental text-only review. The normal workflow remains Chat Prompt with the PDF attached."
              onClick={() => void onRunAIReview()}
            >
              {runningAIReview ? <Sparkles size={16} className="spin" /> : <AlertTriangle size={16} />}
              {runningAIReview ? "AI reviewing" : "Direct AI Text Only"}
            </button>
            <button
              className="secondary-button"
              type="button"
              disabled={creatingSample}
              onClick={() => void onSampleProject()}
              title="Create the built-in synthetic sample drawing package"
            >
              {creatingSample ? <Loader2 size={16} className="spin" /> : <FolderOpen size={16} />}
              Sample Project
            </button>
          </div>
          <ReadinessPanel readiness={readiness} onRefresh={onRefreshReadiness} />
          <AIImportHistory batches={batches} rollingBackBatchId={rollingBackBatchId} onRollbackBatch={onRollbackBatch} />
          <AuditLogPanel events={events} />
        </section>

        <section className="advanced-section" aria-label="Project package backup and restore">
          <div className="advanced-section-header">
            <div>
              <strong>Backup / Restore</strong>
              <span>Portable AutoQC project packages for power users</span>
            </div>
          </div>
          <div className="package-tools">
            <button
              className="secondary-button"
              type="button"
              disabled={!project || exportingPackage}
              onClick={() => void onExportPackage()}
              title="Export this project's metadata, AI findings, audit history, and safe local files"
            >
              {exportingPackage ? <Loader2 size={16} className="spin" /> : <Archive size={16} />}
              Export Project Package
            </button>
            <label className="secondary-button file-import-button" title="Import a portable AutoQC project package zip">
              {importingPackage ? <Loader2 size={16} className="spin" /> : <Upload size={16} />}
              Import Project Package
              <input
                type="file"
                accept="application/zip,.zip"
                aria-label="Import AutoQC project package"
                disabled={importingPackage}
                onChange={(event) => {
                  void onImportPackage(event.target.files?.[0] ?? null);
                  event.target.value = "";
                }}
              />
            </label>
          </div>
        </section>

        <section className="advanced-section" aria-label="Markup Memory settings">
          <div className="advanced-section-header">
            <div>
              <strong>Markup Memory</strong>
              <span>{loading ? "Loading" : "Past Review Knowledge Base"}</span>
            </div>
            <button className="secondary-button compact-action" type="button" onClick={() => void onRefresh()} disabled={loading} title="Refresh Markup Memory settings, stats, and preview">
              <RefreshCw size={14} className={loading ? "spin" : ""} />
              Refresh
            </button>
          </div>

          <div className="inline-warning">
            Past examples are guidance only. The attached PDF remains the source of truth, and memory never creates findings by itself.
          </div>
          <div className="inline-helper">
            Memory is local: Markup Memory is stored in AutoQC's local database, does not train a model, does not send past examples anywhere by itself, and only appears in generated prompts when explicitly enabled.
          </div>

          <label className="checkbox-row advanced-toggle">
            <input
              type="checkbox"
              checked={settings?.advanced_feature_enabled ?? false}
              disabled={disabled}
              onChange={(event) => void onUpdateSettings({ advanced_feature_enabled: event.target.checked })}
            />
            <span>Enable Advanced Features</span>
            <strong>{settings?.advanced_feature_enabled ? "On" : "Off"}</strong>
          </label>
          <label className="checkbox-row advanced-toggle">
            <input
              type="checkbox"
              checked={settings?.enabled ?? false}
              disabled={disabled}
              onChange={(event) => void onUpdateSettings({ enabled: event.target.checked })}
            />
            <span>Enable Markup Memory</span>
            <strong>{settings?.enabled ? "On" : "Off"}</strong>
          </label>
          <label className="checkbox-row advanced-toggle">
            <input
              type="checkbox"
              checked={settings?.include_in_prompts ?? false}
              disabled={disabled}
              onChange={(event) => void onUpdateSettings({ include_in_prompts: event.target.checked })}
            />
            <span>Include Markup Memory in generated prompts</span>
            <strong>{settings?.include_in_prompts ? "On" : "Off"}</strong>
          </label>
          <label className="checkbox-row advanced-toggle">
            <input
              type="checkbox"
              checked={settings?.include_accepted_examples ?? true}
              disabled={disabled}
              onChange={(event) => void onUpdateSettings({ include_accepted_examples: event.target.checked })}
            />
            <span>Include accepted examples</span>
            <strong>{settings?.include_accepted_examples ? "On" : "Off"}</strong>
          </label>
          <label className="checkbox-row advanced-toggle">
            <input
              type="checkbox"
              checked={settings?.include_edited_examples ?? true}
              disabled={disabled}
              onChange={(event) => void onUpdateSettings({ include_edited_examples: event.target.checked })}
            />
            <span>Include edited examples</span>
            <strong>{settings?.include_edited_examples ? "On" : "Off"}</strong>
          </label>
          <label className="checkbox-row advanced-toggle">
            <input
              type="checkbox"
              checked={settings?.include_rejected_examples ?? true}
              disabled={disabled}
              onChange={(event) => void onUpdateSettings({ include_rejected_examples: event.target.checked })}
            />
            <span>Include rejected/duplicate avoid examples</span>
            <strong>{settings?.include_rejected_examples ? "On" : "Off"}</strong>
          </label>
          <label className="checkbox-row advanced-toggle">
            <input
              type="checkbox"
              checked={settings?.include_current_project_examples ?? false}
              disabled={disabled}
              onChange={(event) => void onUpdateSettings({ include_current_project_examples: event.target.checked })}
            />
            <span>Include current project examples</span>
            <strong>{settings?.include_current_project_examples ? "On" : "Off"}</strong>
          </label>

          <div className="advanced-number-grid">
            <label className="field-label">
              Max examples per prompt
              <input
                type="number"
                min={1}
                max={25}
                value={settings?.max_examples_per_prompt ?? 8}
                disabled={disabled}
                onChange={(event) => void onUpdateSettings({ max_examples_per_prompt: Number(event.target.value) })}
              />
            </label>
            <label className="field-label">
              Max avoid examples
              <input
                type="number"
                min={1}
                max={25}
                value={settings?.max_avoid_examples_per_prompt ?? 5}
                disabled={disabled}
                onChange={(event) => void onUpdateSettings({ max_avoid_examples_per_prompt: Number(event.target.value) })}
              />
            </label>
            <label className="field-label">
              Minimum usefulness score
              <input
                type="number"
                min={0}
                max={5}
                step={0.1}
                value={settings?.min_usefulness_score ?? 0}
                disabled={disabled}
                onChange={(event) => void onUpdateSettings({ min_usefulness_score: Number(event.target.value) })}
              />
            </label>
          </div>

          <div className="button-row advanced-actions">
            <button className="primary-button" type="button" disabled={rebuilding} onClick={() => void onRebuild()} title="Rebuild Markup Memory from existing reviewed findings and exports">
              {rebuilding ? <Loader2 size={16} className="spin" /> : <RefreshCw size={16} />}
              Rebuild Memory From Existing Findings
            </button>
            <button className="danger-button" type="button" disabled={clearing} onClick={() => void onClear()} title="Clear all learned Markup Memory examples after confirmation">
              {clearing ? <Loader2 size={16} className="spin" /> : <Trash2 size={16} />}
              Clear Markup Memory
            </button>
          </div>
        </section>

        <section className="advanced-section" aria-label="Markup Memory stats">
          <div className="advanced-section-header">
            <div>
              <strong>Memory Stats</strong>
              <span>{stats?.total_memory_examples ?? 0} total memory examples</span>
            </div>
          </div>
          <div className="memory-stats-grid">
            <MemoryMetric label="Total" value={stats?.total_memory_examples ?? 0} />
            <MemoryMetric label="Accepted" value={stats?.accepted_examples ?? 0} />
            <MemoryMetric label="Edited" value={stats?.edited_examples ?? 0} />
            <MemoryMetric label="Rejected" value={stats?.rejected_examples ?? 0} />
            <MemoryMetric label="Duplicate" value={stats?.duplicate_examples ?? 0} />
            <MemoryMetric label="Exported" value={stats?.exported_examples ?? 0} />
          </div>
          {categoryRows.length ? (
            <div className="memory-category-list">
              {categoryRows.map(([category, count]) => (
                <span key={category}>{formatStatus(category)}: {count}</span>
              ))}
            </div>
          ) : (
            <div className="empty-state compact">
              <strong>No memory examples yet</strong>
              <small>Review or export AI findings, then rebuild or continue working.</small>
            </div>
          )}
        </section>

        <section className="advanced-section" aria-label="Markup Memory prompt preview">
          <div className="advanced-section-header">
            <div>
              <strong>Memory examples that would be included in the next prompt</strong>
              <span>{project ? project.name : "Select a project"}</span>
            </div>
          </div>
          {!project ? (
            <div className="empty-state compact">
              <strong>No project selected</strong>
              <small>Select a project to preview prompt memory context.</small>
            </div>
          ) : preview?.prompt_section ? (
            <pre className="memory-preview-text">{preview.prompt_section}</pre>
          ) : (
            <div className="inline-helper">{preview?.disabled_reason ?? "No Markup Memory prompt context would be injected."}</div>
          )}
          <MemoryExampleList title="Examples to emulate" examples={preview?.positive_examples ?? []} />
          <MemoryExampleList title="Examples to avoid" examples={preview?.avoid_examples ?? []} />
        </section>
      </div>
    </section>
  );
}

function MemoryMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="dashboard-metric memory-metric">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

function MemoryExampleList({ title, examples }: { title: string; examples: MarkupMemoryPreview["positive_examples"] }) {
  if (!examples.length) {
    return null;
  }
  return (
    <div className="memory-example-list">
      <strong>{title}</strong>
      {examples.slice(0, 8).map((example) => (
        <div className="memory-example-row" key={`${example.id}-${example.status_outcome}`}>
          <div className="preview-update-header">
            <span>{memoryOutcomeLabel(example.status_outcome)} | {example.drawing_number || "Drawing unknown"} | Page {example.page_number ?? "?"}</span>
            <small>{typeof example.similarity_score === "number" ? example.similarity_score.toFixed(2) : ""}</small>
          </div>
          <span>{example.target_text || example.sheet_title || "No target text stored"}</span>
          <small>{example.final_comment_text || example.required_update || example.rationale || "No comment text stored"}</small>
        </div>
      ))}
    </div>
  );
}

function memoryOutcomeLabel(value: string): string {
  return formatStatus(value.replace(/_/g, " "));
}

function HelpDialog({ onClose, onOpenAdvanced }: { onClose: () => void; onOpenAdvanced: () => void }) {
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="How to use AutoQC">
      <section className="help-dialog">
        <div className="manual-ai-header">
          <div>
            <strong>How to use AutoQC</strong>
            <span>Local drawing QC tracker workflow</span>
          </div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="Close help">
            <X size={16} />
          </button>
        </div>
        <ol className="help-steps">
          <li>Upload PDF.</li>
          <li>Generate Chat Prompt.</li>
          <li>Attach the same PDF in ChatGPT or Copilot.</li>
          <li>Paste the returned JSON into AutoQC.</li>
          <li>Preview and import valid updates.</li>
          <li>Review findings and accept, reject, or edit them.</li>
          <li>Export the marked PDF.</li>
        </ol>
        <div className="inline-warning">
          AutoQC is a workflow aid, not engineering authority. Final judgment remains with the responsible reviewer, and the prompt alone is not the drawing source of truth.
        </div>
        <div className="help-secondary-actions">
          <button className="secondary-button compact-action" type="button" onClick={onOpenAdvanced} title="Open experimental power-user settings">
            <ShieldCheck size={14} />
            Advanced Features
          </button>
        </div>
      </section>
    </div>
  );
}

function ProjectsPanel({
  projects,
  selectedProjectId,
  loading,
  uploading,
  deletingProjectId,
  showValidationProjects,
  taggingValidationProjects,
  cleaningValidationProjects,
  onSelectProject,
  onRefresh,
  onShowValidationProjectsChange,
  onUpload,
  onDeleteProject,
  onTagGeneratedValidationProjects,
  onClearValidationProjects,
}: ProjectsPanelProps) {
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const validationProjectCount = projects.filter((project) => project.project_type === "validation").length;
  const uploadAssessment = assessUploadInput(name, file);
  const blockingUploadError = uploadAssessment.errors[0] ?? null;
  const displayedUploadError = uploadError ?? (file ? blockingUploadError : null);

  function handleFileChange(candidate: File | null) {
    setFile(candidate);
    setUploadError(null);
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (uploading) {
      return;
    }

    const assessment = assessUploadInput(name, file);
    const validationMessage = assessment.errors[0] ?? null;
    if (validationMessage || !file) {
      setUploadError(validationMessage ?? "Select a PDF drawing package before uploading.");
      return;
    }

    const fallbackName = file.name.replace(/\.pdf$/i, "");
    void onUpload(name.trim() || fallbackName, file);
  }

  return (
    <section className="panel projects-panel" aria-label="Review library and upload area">
      <div className="panel-header">
        <div>
          <span className="eyebrow">Projects</span>
          <h2>Drawing Reviews</h2>
        </div>
        <button
          className="icon-button"
          type="button"
          onClick={() => void onRefresh()}
          title="Refresh the project list from the backend"
          aria-label="Refresh projects"
        >
          <RefreshCw size={17} className={loading ? "spin" : ""} />
        </button>
      </div>

      <details className="collapsible-section upload-collapsible" open={!selectedProjectId || projects.length === 0}>
        <summary>
          <span>
            <strong>Upload PDF</strong>
            <small>{selectedProjectId ? "Collapsed after a project is selected" : "Start a new review"}</small>
          </span>
        </summary>
        <form className="upload-form" onSubmit={handleSubmit}>
          <label className="field-label" title="Optional. If left blank, the PDF filename will be used as the project name.">
            Project name
            <input
              type="text"
              value={name}
              onChange={(event) => {
                setName(event.target.value);
                setUploadError(null);
              }}
              placeholder="Regulator station package"
              title="Optional project name for this drawing review"
            />
          </label>

          <label className="field-label" title="Choose a searchable or scanned PDF drawing package to upload and review.">
            PDF drawing set
            <input
              type="file"
              accept="application/pdf,.pdf"
              title="Select a PDF drawing set to upload"
              onChange={(event) => handleFileChange(event.target.files?.[0] ?? null)}
            />
          </label>

          {file && !displayedUploadError ? (
            <div className="inline-helper" role="status">Ready to upload: {file.name} ({formatBytes(file.size)}).</div>
          ) : null}

          {displayedUploadError ? (
            <div className="inline-error compact-error" role="alert">{displayedUploadError}</div>
          ) : null}

          {uploadAssessment.warnings.length ? (
            <div className="risk-list" role="status" aria-label="Upload cautions">
              {uploadAssessment.warnings.map((warning) => (
                <span key={`${warning.title}-${warning.detail}`}>
                  <AlertTriangle size={13} />
                  <strong>{warning.title}</strong>
                  {warning.detail}
                </span>
              ))}
            </div>
          ) : null}

          <div className="button-row">
            <button
              className="primary-button"
              type="submit"
              disabled={!file || Boolean(blockingUploadError) || uploading}
              title={blockingUploadError ? blockingUploadError : file ? "Upload this PDF and extract sheets, page images, and prompt context" : "Select a PDF before uploading"}
            >
              {uploading ? <Loader2 size={17} className="spin" /> : <Upload size={17} />}
              Upload
            </button>
          </div>
        </form>
      </details>

      <div className="project-list" aria-label="Project list">
        <div className="validation-project-controls">
          <label className="toggle-row compact-toggle" title="Validation scripts mark their generated projects so normal reviews stay uncluttered.">
            <input
              type="checkbox"
              checked={showValidationProjects}
              onChange={(event) => onShowValidationProjectsChange(event.target.checked)}
            />
            <span>Show generated validation projects</span>
          </label>
          <button
            className="secondary-button compact-action"
            type="button"
            disabled={taggingValidationProjects || cleaningValidationProjects}
            onClick={() => void onTagGeneratedValidationProjects()}
            title="Tag historical smoke, stress, and real-PDF regression projects as generated validation runs"
          >
            {taggingValidationProjects ? <Loader2 size={14} className="spin" /> : <ShieldCheck size={14} />}
            Tag old validation runs
          </button>
          <button
            className="secondary-button compact-action"
            type="button"
            disabled={cleaningValidationProjects || taggingValidationProjects}
            onClick={() => void onClearValidationProjects()}
            title="Delete projects marked as generated validation/test runs"
          >
            {cleaningValidationProjects ? <Loader2 size={14} className="spin" /> : <Trash2 size={14} />}
            Clean validation runs
          </button>
          <small>
            {showValidationProjects
              ? `${validationProjectCount} generated validation project${validationProjectCount === 1 ? "" : "s"} shown.`
              : "Generated validation projects are hidden by default."}
          </small>
        </div>
        {projects.length === 0 ? (
          <div className="empty-state compact">
            <FileText size={18} />
            <strong>No projects yet</strong>
            <small>{showValidationProjects ? "Upload a PDF drawing set or create the sample project to start the AutoQC workflow." : "Upload a PDF drawing set, create the sample project, or show generated validation projects."}</small>
          </div>
        ) : (
          projects.map((project) => {
            const isDeleting = deletingProjectId === project.id;

            return (
              <div
                className={`project-item ${project.id === selectedProjectId ? "selected" : ""} ${project.project_type === "validation" ? "validation-project" : ""}`}
                key={project.id}
              >
                <button
                  className="project-select-button"
                  type="button"
                  onClick={() => onSelectProject(project.id)}
                  disabled={isDeleting}
                  title={`Open ${project.name} and load its sheets, findings, and audit history`}
                >
                  <span className="project-name">{project.name}</span>
                  <span className="project-meta">
                    {formatStatus(project.status)}
                    {project.project_type === "validation" ? <span>Validation</span> : null}
                    <span>{project.sheet_count ?? 0} sheets</span>
                    <span>{project.finding_count ?? project.findings_count ?? 0} AI findings</span>
                  </span>
                  <span className="project-date">{formatDate(project.updated_at)}</span>
                </button>
                <button
                  className="project-delete-button"
                  type="button"
                  onClick={() => void onDeleteProject(project)}
                  disabled={isDeleting}
                  title={`Delete ${project.name}`}
                  aria-label={`Delete ${project.name}`}
                >
                  {isDeleting ? <Loader2 size={14} className="spin" /> : <Trash2 size={14} />}
                </button>
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}

interface ViewerProps {
  project: Project | null;
  sheet: Sheet | null;
  sheets: Sheet[];
  findings: Finding[];
  selectedFinding: Finding | null;
  markedPdfUrl: string | null;
  loading: boolean;
  placementMessage: string | null;
  placementSummary: PlacementSummary | null;
  manualPlacementFindingId: string | null;
  savingManualPlacement: boolean;
  savingFindingId: string | null;
  onSelectFinding: (finding: Finding) => void;
  onPatchFindingStatus: (finding: Finding, status: FindingStatus) => Promise<void>;
  onSelectSheet: (sheetId: string) => void;
  onSaveManualPlacement: (finding: Finding, pageNumber: number, rect: number[], imageWidth: number, imageHeight: number) => Promise<void>;
  onStepSheet: (delta: number) => void;
  onDeepDiveSheet: (sheet?: Sheet | null) => void;
}

type ViewerWheelLikeEvent = Pick<
  WheelEvent<HTMLDivElement>,
  "clientX" | "clientY" | "ctrlKey" | "deltaX" | "deltaY" | "metaKey" | "preventDefault" | "shiftKey"
>;

type ViewerGestureLikeEvent = Event & {
  clientX?: number;
  clientY?: number;
  scale?: number;
};

function Viewer({
  project,
  sheet,
  sheets,
  findings,
  selectedFinding,
  markedPdfUrl,
  loading,
  placementMessage,
  placementSummary,
  manualPlacementFindingId,
  savingManualPlacement,
  savingFindingId,
  onSelectFinding,
  onPatchFindingStatus,
  onSelectSheet,
  onSaveManualPlacement,
  onStepSheet,
  onDeepDiveSheet,
}: ViewerProps) {
  const [imageSize, setImageSize] = useState<ImageSize | null>(null);
  const [imageFailed, setImageFailed] = useState(false);
  const [zoom, setZoom] = useState(0.75);
  const [viewerMode, setViewerMode] = useState<ViewerMode>("sheet");
  const [manualPlacementDraft, setManualPlacementDraft] = useState<number[] | null>(null);
  const panViewportRef = useRef<HTMLDivElement | null>(null);
  const drawingStageRef = useRef<HTMLDivElement | null>(null);
  const imageElementRef = useRef<HTMLImageElement | null>(null);
  const panDragRef = useRef({ active: false, startX: 0, startY: 0, scrollLeft: 0, scrollTop: 0 });
  const placementDragRef = useRef<{ active: boolean; startX: number; startY: number } | null>(null);
  const touchPanRef = useRef({ active: false, startX: 0, startY: 0, scrollLeft: 0, scrollTop: 0 });
  const pinchRef = useRef({ active: false, startDistance: 0, startZoom: 1, centerX: 0, centerY: 0, scrollLeft: 0, scrollTop: 0 });
  const zoomRef = useRef(zoom);
  const wheelZoomFrameRef = useRef<number | null>(null);
  const wheelZoomDeltaRef = useRef(0);
  const wheelZoomAnchorRef = useRef({ centerX: 0, centerY: 0 });
  const gestureZoomRef = useRef({ active: false, startScale: 1, startZoom: 1, centerX: 0, centerY: 0 });
  const imageUrl = resolveAssetUrl(sheet?.image_url ?? sheet?.image_path);
  const sourcePdfUrl = resolveAssetUrl(project?.source_pdf_url ?? project?.source_pdf_path);
  const markedPdfAssetUrl = resolveAssetUrl(markedPdfUrl);
  const markedPdfViewerUrl = markedPdfAssetUrl
    ? `${markedPdfAssetUrl}#page=${sheet?.page_number ?? 1}&view=FitH`
    : undefined;
  const sheetIndex = sheet ? sheets.findIndex((item) => item.id === sheet.id) : -1;
  const canGoPrev = sheetIndex > 0;
  const canGoNext = sheetIndex >= 0 && sheetIndex < sheets.length - 1;
  const selectedFindingOnSheet = sheet && selectedFinding && findingMatchesSheet(selectedFinding, sheet) ? selectedFinding : null;
  const manualPlacementTarget =
    selectedFindingOnSheet && manualPlacementFindingId === selectedFindingOnSheet.id ? selectedFindingOnSheet : null;
  const selectedFindingBox = useMemo(
    () => (selectedFindingOnSheet && sheet ? getOverlayBoxPercent(selectedFindingOnSheet, sheet, imageSize) : null),
    [selectedFindingOnSheet, sheet, imageSize],
  );
  const activeViewerMode: ViewerMode = viewerMode === "focus" && !selectedFindingOnSheet
    ? "sheet"
    : viewerMode === "marked" && !markedPdfViewerUrl
      ? "sheet"
      : viewerMode;
  useEffect(() => {
    setImageSize(null);
    setImageFailed(false);
    zoomRef.current = 0.75;
    setZoom(0.75);
  }, [sheet?.id, imageUrl]);

  useEffect(() => {
    if (!imageSize) {
      return;
    }

    const fitZoom = getFitZoom();
    if (fitZoom) {
      zoomRef.current = fitZoom;
      setZoom(fitZoom);
    }
  }, [imageSize?.width, imageSize?.height]);

  useEffect(() => {
    if (selectedFinding) {
      setViewerMode("focus");
    }
  }, [selectedFinding?.id]);

  useEffect(() => {
    setManualPlacementDraft(null);
    placementDragRef.current = null;
  }, [manualPlacementFindingId, sheet?.id]);

  useEffect(() => {
    if (viewerMode === "focus" && !selectedFindingOnSheet) {
      setViewerMode("sheet");
    }
  }, [viewerMode, selectedFindingOnSheet]);

  useEffect(() => {
    zoomRef.current = zoom;
  }, [zoom]);

  useEffect(() => {
    return () => {
      if (wheelZoomFrameRef.current !== null) {
        cancelAnimationFrame(wheelZoomFrameRef.current);
      }
    };
  }, []);

  useEffect(() => {
    const viewport = panViewportRef.current;
    if (!viewport || !imageUrl || imageFailed) {
      return undefined;
    }

    const handleNativeWheel = (event: Event) => {
      const wheelEvent = event as unknown as ViewerWheelLikeEvent;
      if (!wheelEvent.ctrlKey && !wheelEvent.metaKey) {
        return;
      }
      handleViewportWheel(wheelEvent);
    };

    const handleGestureStart = (event: Event) => {
      const gestureEvent = event as ViewerGestureLikeEvent;
      gestureEvent.preventDefault();
      const rect = viewport.getBoundingClientRect();
      gestureZoomRef.current = {
        active: true,
        startScale: gestureEvent.scale || 1,
        startZoom: zoomRef.current,
        centerX: typeof gestureEvent.clientX === "number" ? gestureEvent.clientX - rect.left : viewport.clientWidth / 2,
        centerY: typeof gestureEvent.clientY === "number" ? gestureEvent.clientY - rect.top : viewport.clientHeight / 2,
      };
    };

    const handleGestureChange = (event: Event) => {
      const gestureEvent = event as ViewerGestureLikeEvent;
      gestureEvent.preventDefault();
      if (!gestureZoomRef.current.active) {
        handleGestureStart(event);
      }
      const gesture = gestureZoomRef.current;
      const scale = clamp((gestureEvent.scale || 1) / gesture.startScale, 0.2, 5);
      applyZoom(gesture.startZoom * scale, gesture.centerX, gesture.centerY);
    };

    const handleGestureEnd = (event: Event) => {
      event.preventDefault();
      gestureZoomRef.current.active = false;
    };

    const wheelOptions: AddEventListenerOptions = { passive: false, capture: true };
    const gestureOptions: AddEventListenerOptions = { passive: false, capture: true };
    viewport.addEventListener("wheel", handleNativeWheel, wheelOptions);
    viewport.addEventListener("gesturestart", handleGestureStart, gestureOptions);
    viewport.addEventListener("gesturechange", handleGestureChange, gestureOptions);
    viewport.addEventListener("gestureend", handleGestureEnd, gestureOptions);
    return () => {
      viewport.removeEventListener("wheel", handleNativeWheel, wheelOptions);
      viewport.removeEventListener("gesturestart", handleGestureStart, gestureOptions);
      viewport.removeEventListener("gesturechange", handleGestureChange, gestureOptions);
      viewport.removeEventListener("gestureend", handleGestureEnd, gestureOptions);
    };
  }, [imageUrl, imageFailed]);

  useEffect(() => {
    if (activeViewerMode !== "focus" || !imageSize || !selectedFindingBox || !panViewportRef.current) {
      return;
    }

    const viewport = panViewportRef.current;
    const targetWidth = Math.max(24, imageSize.width * (selectedFindingBox.width / 100));
    const targetHeight = Math.max(24, imageSize.height * (selectedFindingBox.height / 100));
    const fitZoom = getFitZoom() ?? minZoom;
    const focusZoom = clamp(
      Math.min(viewport.clientWidth / (targetWidth * 3), viewport.clientHeight / (targetHeight * 3)),
      Math.max(fitZoom, 0.35),
      4,
    );
    zoomRef.current = focusZoom;
    setZoom(focusZoom);

    requestAnimationFrame(() => {
      const scaledWidth = imageSize.width * focusZoom;
      const scaledHeight = imageSize.height * focusZoom;
      const centerX = scaledWidth * ((selectedFindingBox.left + selectedFindingBox.width / 2) / 100);
      const centerY = scaledHeight * ((selectedFindingBox.top + selectedFindingBox.height / 2) / 100);
      viewport.scrollLeft = Math.max(0, centerX - viewport.clientWidth / 2);
      viewport.scrollTop = Math.max(0, centerY - viewport.clientHeight / 2);
    });
  }, [activeViewerMode, imageSize?.width, imageSize?.height, selectedFindingBox?.left, selectedFindingBox?.top, selectedFindingBox?.width, selectedFindingBox?.height, selectedFindingOnSheet?.id]);

  const minZoom = 0.1;
  const maxZoom = 5;
  const zoomPercent = Math.round(zoom * 100);
  const canZoomOut = zoom > minZoom;
  const canZoomIn = zoom < maxZoom;
  const selectedFindingIssueText = selectedFindingOnSheet
    ? selectedFindingOnSheet.reasoning_summary.trim() ||
      selectedFindingOnSheet.comment_text.trim() ||
      selectedFindingOnSheet.suggested_correction.trim() ||
      "No issue description is saved for this finding yet."
    : "";
  const selectedFindingCorrectionText = selectedFindingOnSheet?.suggested_correction.trim() || "";
  const selectedFindingCommentText = selectedFindingOnSheet?.comment_text.trim() || "";
  const selectedFindingSecondaryText =
    selectedFindingCorrectionText && selectedFindingCorrectionText !== selectedFindingIssueText
      ? selectedFindingCorrectionText
      : selectedFindingCommentText && selectedFindingCommentText !== selectedFindingIssueText
        ? selectedFindingCommentText
        : "";
  const selectedFindingSecondaryLabel = selectedFindingSecondaryText === selectedFindingCorrectionText
    ? "Suggested fix"
    : "PDF comment";

  function getFitZoom() {
    if (!imageSize || !panViewportRef.current) {
      return null;
    }

    const viewport = panViewportRef.current;
    const availableWidth = Math.max(240, viewport.clientWidth - 48);
    const availableHeight = Math.max(180, viewport.clientHeight - 48);
    const nextZoom = Math.min(availableWidth / imageSize.width, availableHeight / imageSize.height);
    return clamp(Math.round(nextZoom * 100) / 100, minZoom, 2);
  }

  function fitToViewport() {
    const fitZoom = getFitZoom() ?? 0.75;
    zoomRef.current = fitZoom;
    setZoom(fitZoom);
    requestAnimationFrame(() => {
      if (!panViewportRef.current) {
        return;
      }
      panViewportRef.current.scrollLeft = 0;
      panViewportRef.current.scrollTop = 0;
    });
  }

  function applyZoom(nextZoom: number, centerX?: number, centerY?: number) {
    const viewport = panViewportRef.current;
    const previousZoom = zoomRef.current;
    const boundedZoom = clamp(Math.round(nextZoom * 1000) / 1000, minZoom, maxZoom);

    if (boundedZoom === previousZoom) {
      return;
    }

    zoomRef.current = boundedZoom;

    if (!viewport || centerX === undefined || centerY === undefined) {
      setZoom(boundedZoom);
      return;
    }

    const previousScrollLeft = viewport.scrollLeft;
    const previousScrollTop = viewport.scrollTop;
    setZoom(boundedZoom);

    requestAnimationFrame(() => {
      const scale = boundedZoom / previousZoom;
      viewport.scrollLeft = (previousScrollLeft + centerX) * scale - centerX;
      viewport.scrollTop = (previousScrollTop + centerY) * scale - centerY;
    });
  }

  function changeZoom(delta: number) {
    applyZoom(zoom + delta);
  }

  function focusFindingInViewer(finding: Finding) {
    if (!sheet || !imageSize || !panViewportRef.current) {
      return;
    }

    const box = getOverlayBoxPercent(finding, sheet, imageSize);
    if (!box) {
      return;
    }

    const viewport = panViewportRef.current;
    const targetWidth = Math.max(24, imageSize.width * (box.width / 100));
    const targetHeight = Math.max(24, imageSize.height * (box.height / 100));
    const fitZoom = getFitZoom() ?? minZoom;
    const focusZoom = clamp(
      Math.min(viewport.clientWidth / (targetWidth * 3), viewport.clientHeight / (targetHeight * 3)),
      Math.max(fitZoom, 0.35),
      4,
    );

    setViewerMode("focus");
    zoomRef.current = focusZoom;
    setZoom(focusZoom);

    requestAnimationFrame(() => {
      const scaledWidth = imageSize.width * focusZoom;
      const scaledHeight = imageSize.height * focusZoom;
      const centerX = scaledWidth * ((box.left + box.width / 2) / 100);
      const centerY = scaledHeight * ((box.top + box.height / 2) / 100);
      viewport.scrollLeft = Math.max(0, centerX - viewport.clientWidth / 2);
      viewport.scrollTop = Math.max(0, centerY - viewport.clientHeight / 2);
    });
  }

  function handleOverlayFindingClick(finding: Finding) {
    onSelectFinding(finding);
    focusFindingInViewer(finding);
  }

  function handlePanWheel(event: WheelEvent<HTMLDivElement>) {
    if (event.ctrlKey || event.metaKey) {
      return;
    }
    handleViewportWheel(event);
  }

  function handleViewportWheel(event: ViewerWheelLikeEvent) {
    const viewport = panViewportRef.current;
    if (!viewport || !imageUrl) {
      return;
    }

    if (event.ctrlKey || event.metaKey) {
      event.preventDefault();
      const rect = viewport.getBoundingClientRect();
      wheelZoomAnchorRef.current = {
        centerX: event.clientX - rect.left,
        centerY: event.clientY - rect.top,
      };
      wheelZoomDeltaRef.current += clamp(event.deltaY, -80, 80);

      if (wheelZoomFrameRef.current !== null) {
        return;
      }

      wheelZoomFrameRef.current = requestAnimationFrame(() => {
        wheelZoomFrameRef.current = null;
        const delta = wheelZoomDeltaRef.current;
        wheelZoomDeltaRef.current = 0;
        const scale = Math.exp(-delta * 0.0016);
        const anchor = wheelZoomAnchorRef.current;
        applyZoom(zoomRef.current * scale, anchor.centerX, anchor.centerY);
      });
      return;
    }
  }

  function handlePanMouseDown(event: MouseEvent<HTMLDivElement>) {
    if (manualPlacementTarget && imageSize) {
      const point = clientPointToImagePixelPoint(event, imageElementRef.current);
      if (!point) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      placementDragRef.current = { active: true, startX: point.x, startY: point.y };
      setManualPlacementDraft(normalizedImagePixelRect(point.x, point.y, point.x, point.y));
      return;
    }
    if (event.button !== 0 || !panViewportRef.current) {
      return;
    }
    panDragRef.current = {
      active: true,
      startX: event.clientX,
      startY: event.clientY,
      scrollLeft: panViewportRef.current.scrollLeft,
      scrollTop: panViewportRef.current.scrollTop,
    };
  }

  function handlePanMouseMove(event: MouseEvent<HTMLDivElement>) {
    if (placementDragRef.current?.active && manualPlacementTarget) {
      const point = clientPointToImagePixelPoint(event, imageElementRef.current);
      if (!point) {
        return;
      }
      event.preventDefault();
      const drag = placementDragRef.current;
      setManualPlacementDraft(normalizedImagePixelRect(drag.startX, drag.startY, point.x, point.y));
      return;
    }
    const drag = panDragRef.current;
    if (!drag.active || !panViewportRef.current) {
      return;
    }
    panViewportRef.current.scrollLeft = drag.scrollLeft - (event.clientX - drag.startX);
    panViewportRef.current.scrollTop = drag.scrollTop - (event.clientY - drag.startY);
  }

  function stopPanning() {
    if (placementDragRef.current?.active && manualPlacementTarget && manualPlacementDraft && imageSize && sheet) {
      const rect = normalizedImagePixelRect(manualPlacementDraft[0], manualPlacementDraft[1], manualPlacementDraft[2], manualPlacementDraft[3]);
      placementDragRef.current = null;
      setManualPlacementDraft(null);
      if (rect && Math.abs(rect[2] - rect[0]) >= 2 && Math.abs(rect[3] - rect[1]) >= 2) {
        void onSaveManualPlacement(manualPlacementTarget, sheet.page_number, rect, imageSize.width, imageSize.height);
      }
    } else {
      placementDragRef.current = null;
    }
    panDragRef.current.active = false;
  }

  const manualPlacementDraftBox = manualPlacementDraft && imageSize
    ? imagePixelRectToOverlayPercent(manualPlacementDraft, imageSize)
    : null;

  function clientPointToImagePixelPoint(event: MouseEvent<HTMLDivElement>, imageElement: HTMLImageElement | null): { x: number; y: number } | null {
    if (!imageElement || !imageElement.naturalWidth || !imageElement.naturalHeight) {
      return null;
    }
    const rect = imageElement.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) {
      return null;
    }
    const x = clamp(((event.clientX - rect.left) / rect.width) * imageElement.naturalWidth, 0, imageElement.naturalWidth);
    const y = clamp(((event.clientY - rect.top) / rect.height) * imageElement.naturalHeight, 0, imageElement.naturalHeight);
    return { x, y };
  }

  function normalizedImagePixelRect(x0: number, y0: number, x1: number, y1: number): number[] {
    return [roundRectCoord(Math.min(x0, x1)), roundRectCoord(Math.min(y0, y1)), roundRectCoord(Math.max(x0, x1)), roundRectCoord(Math.max(y0, y1))];
  }

  function getTouchDistance(event: TouchEvent<HTMLDivElement>) {
    const first = event.touches.item(0);
    const second = event.touches.item(1);
    if (!first || !second) {
      return 0;
    }

    return Math.hypot(second.clientX - first.clientX, second.clientY - first.clientY);
  }

  function getTouchCenter(event: TouchEvent<HTMLDivElement>) {
    const first = event.touches.item(0);
    const second = event.touches.item(1);
    const viewport = panViewportRef.current;
    if (!first || !second || !viewport) {
      return { x: 0, y: 0 };
    }

    const rect = viewport.getBoundingClientRect();
    return {
      x: (first.clientX + second.clientX) / 2 - rect.left,
      y: (first.clientY + second.clientY) / 2 - rect.top,
    };
  }

  function handlePanTouchStart(event: TouchEvent<HTMLDivElement>) {
    const viewport = panViewportRef.current;
    if (!viewport) {
      return;
    }

    if (event.touches.length === 2) {
      const center = getTouchCenter(event);
      pinchRef.current = {
        active: true,
        startDistance: getTouchDistance(event),
        startZoom: zoom,
        centerX: center.x,
        centerY: center.y,
        scrollLeft: viewport.scrollLeft,
        scrollTop: viewport.scrollTop,
      };
      touchPanRef.current.active = false;
      return;
    }

    if (event.touches.length === 1) {
      const touch = event.touches.item(0);
      if (!touch) {
        return;
      }
      touchPanRef.current = {
        active: true,
        startX: touch.clientX,
        startY: touch.clientY,
        scrollLeft: viewport.scrollLeft,
        scrollTop: viewport.scrollTop,
      };
      pinchRef.current.active = false;
    }
  }

  function handlePanTouchMove(event: TouchEvent<HTMLDivElement>) {
    const viewport = panViewportRef.current;
    if (!viewport) {
      return;
    }

    if (event.touches.length === 2 && pinchRef.current.active) {
      event.preventDefault();
      const pinch = pinchRef.current;
      const nextDistance = getTouchDistance(event);
      if (!pinch.startDistance || !nextDistance) {
        return;
      }
      const nextZoom = clamp(Math.round((pinch.startZoom * (nextDistance / pinch.startDistance)) * 100) / 100, minZoom, maxZoom);
      const scale = nextZoom / pinch.startZoom;
      setZoom(nextZoom);
      requestAnimationFrame(() => {
        viewport.scrollLeft = (pinch.scrollLeft + pinch.centerX) * scale - pinch.centerX;
        viewport.scrollTop = (pinch.scrollTop + pinch.centerY) * scale - pinch.centerY;
      });
      return;
    }

    if (event.touches.length === 1 && touchPanRef.current.active) {
      event.preventDefault();
      const touch = event.touches.item(0);
      if (!touch) {
        return;
      }
      const pan = touchPanRef.current;
      viewport.scrollLeft = pan.scrollLeft - (touch.clientX - pan.startX);
      viewport.scrollTop = pan.scrollTop - (touch.clientY - pan.startY);
    }
  }

  function stopTouchPanning() {
    touchPanRef.current.active = false;
    pinchRef.current.active = false;
  }

  return (
    <div className="viewer">
      <div className="viewer-toolbar">
        <div className="viewer-title">
          <span className="eyebrow">{project?.name || "Review"}</span>
          <h1>{sheet ? sheetLabel(sheet) : "No sheet selected"}</h1>
          {sheet ? (
            <div className="sheet-facts">
              <span>Page {sheet.page_number}</span>
              <span>{formatStatus(sheet.sheet_type)}</span>
              <span>{formatStatus(sheet.extraction_status)}</span>
              {sheet.revision ? <span>Rev {sheet.revision}</span> : null}
            </div>
          ) : null}
        </div>

        <div className="viewer-actions">
          <div className="viewer-control-group viewer-navigation-group" aria-label="Sheet navigation">
            <label className="viewer-sheet-jump" title="Jump to another extracted drawing sheet">
              <span>Sheet</span>
              <select
                aria-label="Jump to sheet"
                value={sheet?.id ?? ""}
                disabled={sheets.length === 0}
                onChange={(event) => {
                  if (event.target.value) {
                    onSelectSheet(event.target.value);
                  }
                }}
              >
                {sheets.length === 0 ? (
                  <option value="">No sheets</option>
                ) : (
                  sheets.map((candidate) => (
                    <option key={candidate.id} value={candidate.id}>
                      P{candidate.page_number} {candidate.drawing_number || candidate.sheet_title || "Untitled"}
                    </option>
                  ))
                )}
              </select>
            </label>
            <button
              className="icon-button"
              type="button"
              onClick={() => onStepSheet(-1)}
              disabled={!canGoPrev}
              title="Show the previous drawing sheet in this package"
              aria-label="Previous sheet"
            >
              <ChevronLeft size={18} />
            </button>
            <button
              className="icon-button"
              type="button"
              onClick={() => onStepSheet(1)}
              disabled={!canGoNext}
              title="Show the next drawing sheet in this package"
              aria-label="Next sheet"
            >
              <ChevronRight size={18} />
            </button>
          </div>
          <div className="viewer-control-group viewer-mode-toggle" role="tablist" aria-label="Viewer mode">
            <button
              className={activeViewerMode === "focus" ? "active" : ""}
              type="button"
              role="tab"
              aria-selected={activeViewerMode === "focus"}
              onClick={() => setViewerMode("focus")}
              disabled={!selectedFindingOnSheet}
              title={selectedFindingOnSheet ? "Focus on the selected finding" : "Select a finding to use Finding Focus"}
            >
              Finding Focus
            </button>
            <button
              className={activeViewerMode === "sheet" ? "active" : ""}
              type="button"
              role="tab"
              aria-selected={activeViewerMode === "sheet"}
              onClick={() => setViewerMode("sheet")}
            >
              Full Sheet
            </button>
            <button
              className={activeViewerMode === "marked" ? "active" : ""}
              type="button"
              role="tab"
              aria-selected={activeViewerMode === "marked"}
              onClick={() => setViewerMode("marked")}
              disabled={!markedPdfViewerUrl}
              title={markedPdfViewerUrl ? "Preview the exported marked PDF" : "Export a marked PDF before using this preview"}
            >
              Marked PDF
            </button>
          </div>
          <div className="viewer-control-group zoom-controls" aria-label="Drawing zoom controls">
            <button className="icon-button" type="button" onClick={() => changeZoom(-0.15)} disabled={!imageUrl || !canZoomOut} title="Zoom out" aria-label="Zoom out">
              <ZoomOut size={17} />
            </button>
            <button className="zoom-level" type="button" onClick={() => setZoom(1)} disabled={!imageUrl} title="Reset to 100% zoom" aria-label="Reset zoom to 100 percent">
              {zoomPercent}%
            </button>
            <button className="icon-button" type="button" onClick={() => changeZoom(0.15)} disabled={!imageUrl || !canZoomIn} title="Zoom in" aria-label="Zoom in">
              <ZoomIn size={17} />
            </button>
            <button className="icon-button" type="button" onClick={fitToViewport} disabled={!imageUrl} title="Fit drawing to the review canvas" aria-label="Fit drawing to review canvas">
              <Maximize2 size={16} />
            </button>
            {imageUrl ? (
              <a className="icon-button viewer-open-link" href={imageUrl} target="_blank" rel="noreferrer" title="Open the page image in a new browser tab" aria-label="Open page image in a new browser tab">
                <ExternalLink size={16} />
              </a>
            ) : null}
            {sourcePdfUrl ? (
              <a className="icon-button viewer-open-link" href={sourcePdfUrl} target="_blank" rel="noreferrer" title="Open the source PDF in a new browser tab" aria-label="Open source PDF in a new browser tab">
                <FileText size={16} />
              </a>
            ) : null}
            <button className="icon-button" type="button" onClick={() => onDeepDiveSheet(sheet)} disabled={!sheet} title="Generate a single-sheet deep-dive prompt for this sheet" aria-label="Deep dive this sheet">
              <Sparkles size={16} />
            </button>
          </div>
        </div>
      </div>

      {manualPlacementTarget ? (
        <div className="manual-placement-banner" role="status">
          <Maximize2 size={15} />
          <strong>Manual placement active</strong>
          <span>Drag a rectangle on the drawing. Press Escape to cancel.</span>
        </div>
      ) : null}

      {(placementMessage || placementSummary || savingManualPlacement) ? (
        <div className="viewer-placement-summary" role="status">
          {savingManualPlacement ? <strong>Saving manual placement...</strong> : null}
          {placementMessage ? <strong>{placementMessage}</strong> : null}
          {placementSummary ? <span>{placementSummaryText(placementSummary)}</span> : null}
        </div>
      ) : null}

      <div className="drawing-surface">
        {loading ? (
          <div className="empty-state">
            <Loader2 size={24} className="spin" />
            <span>Loading review data</span>
          </div>
        ) : !project ? (
          <div className="empty-state">
            <FolderOpen size={26} />
            <strong>No project selected</strong>
            <small>Choose a review from Projects, upload a PDF, or create the sample project to begin.</small>
          </div>
        ) : !sheet ? (
          <div className="empty-state">
            <FileText size={26} />
            <strong>No sheets available</strong>
            <small>AutoQC could not find extracted sheets for this project. Refresh or re-upload the package.</small>
          </div>
        ) : activeViewerMode === "marked" && markedPdfViewerUrl ? (
          <div className="pdf-preview-stage">
            <iframe
              className="marked-pdf-frame"
              src={markedPdfViewerUrl}
              title={`Marked PDF preview - ${sheetLabel(sheet)}`}
            />
          </div>
        ) : imageUrl && !imageFailed ? (
          <div
            className={`drawing-pan-viewport ${manualPlacementTarget ? "manual-placement-active" : ""}`}
            ref={panViewportRef}
            aria-label="Scrollable drawing preview. Use the zoom controls, mouse wheel, trackpad pinch, or touch gestures to zoom and pan."
            onWheel={handlePanWheel}
            onMouseDown={handlePanMouseDown}
            onMouseMove={handlePanMouseMove}
            onMouseUp={stopPanning}
            onMouseLeave={stopPanning}
            onTouchStart={handlePanTouchStart}
            onTouchMove={handlePanTouchMove}
            onTouchEnd={stopTouchPanning}
            onTouchCancel={stopTouchPanning}
          >
            <div
              ref={drawingStageRef}
              className={`drawing-stage ${manualPlacementTarget ? "manual-placement-active" : ""}`}
              style={{
                width: imageSize ? imageSize.width * zoom : undefined,
                minWidth: imageSize ? imageSize.width * zoom : undefined,
                height: imageSize ? imageSize.height * zoom : undefined,
                minHeight: imageSize ? imageSize.height * zoom : undefined,
              }}
            >
              <img
                ref={imageElementRef}
                src={imageUrl}
                alt={sheetLabel(sheet)}
                draggable={false}
                onLoad={(event) => {
                  setImageSize({
                    width: event.currentTarget.naturalWidth,
                    height: event.currentTarget.naturalHeight,
                  });
                }}
                onError={() => setImageFailed(true)}
              />
              {findings.map((finding) => {
                const rect = getOverlayRect(finding, sheet, imageSize);
                if (!rect) {
                  return null;
                }

                return (
                  <button
                    key={finding.id}
                    type="button"
                    className={`finding-overlay severity-${severityClass(
                      finding.severity,
                    )} status-${statusClass(finding.status)} ${
                      finding.id === selectedFinding?.id ? "selected" : ""
                    }`}
                    style={rect}
                    title={finding.title}
                    aria-label={finding.title}
                    onClick={() => handleOverlayFindingClick(finding)}
                  />
                );
              })}
              {manualPlacementDraftBox ? (
                <div
                  className="manual-placement-draft"
                  data-coordinate-space="image_pixel"
                  style={{
                    left: `${manualPlacementDraftBox.left}%`,
                    top: `${manualPlacementDraftBox.top}%`,
                    width: `${manualPlacementDraftBox.width}%`,
                    height: `${manualPlacementDraftBox.height}%`,
                  }}
                />
              ) : null}
            </div>
          </div>
        ) : (
          <div className="drawing-placeholder">
            <FileText size={32} />
            <strong>{sheetLabel(sheet)}</strong>
            <span>No drawing image available</span>
            <small>Use the extracted text below or open the source PDF from the toolbar to verify this sheet.</small>
          </div>
        )}

        {selectedFindingOnSheet ? (
          <section className="viewer-selected-finding-bar" aria-label="Selected finding quick actions" aria-live="polite">
            <span className={`severity-dot severity-${severityClass(selectedFindingOnSheet.severity)}`} />
            <div className="viewer-selected-finding-main">
              <div className="viewer-selected-finding-title-row">
                <strong>{selectedFindingOnSheet.title}</strong>
                <span className={`status-chip status-${statusClass(selectedFindingOnSheet.status)}`}>
                  {formatStatus(selectedFindingOnSheet.status)}
                </span>
              </div>
              <dl className="viewer-selected-finding-details">
                <div>
                  <dt>Issue</dt>
                  <dd>{selectedFindingIssueText}</dd>
                </div>
                {selectedFindingSecondaryText ? (
                  <div>
                    <dt>{selectedFindingSecondaryLabel}</dt>
                    <dd>{selectedFindingSecondaryText}</dd>
                  </div>
                ) : null}
              </dl>
            </div>
            <div className="viewer-selected-finding-actions">
              <button
                className="primary-button compact-action"
                type="button"
                disabled={savingFindingId === selectedFindingOnSheet.id}
                onClick={() => void onPatchFindingStatus(selectedFindingOnSheet, "accepted")}
                title="Accept this selected PDF markup finding"
              >
                {savingFindingId === selectedFindingOnSheet.id ? <Loader2 size={14} className="spin" /> : <Check size={14} />}
                Accept
              </button>
              <button
                className="secondary-button compact-action"
                type="button"
                disabled={savingFindingId === selectedFindingOnSheet.id}
                onClick={() => void onPatchFindingStatus(selectedFindingOnSheet, "needs_review")}
                title="Keep this selected PDF markup finding in review"
              >
                <ClipboardCheck size={14} />
                Review
              </button>
              <button
                className="secondary-button compact-action"
                type="button"
                disabled={savingFindingId === selectedFindingOnSheet.id}
                onClick={() => void onPatchFindingStatus(selectedFindingOnSheet, "rejected")}
                title="Reject this selected PDF markup finding"
              >
                <X size={14} />
                Reject
              </button>
            </div>
          </section>
        ) : null}

      </div>

      {sheet?.text_content ? (
        <div className="sheet-text-strip">
          <strong>Extracted text</strong>
          <span>{sheet.text_content.slice(0, 360)}</span>
        </div>
      ) : null}
    </div>
  );
}

interface FindingsPanelProps {
  findings: Finding[];
  sheets: Sheet[];
  selectedFinding: Finding | null;
  scrollFindingId: string | null;
  selectedProject: Project | null;
  reviewProgress: { total: number; remaining: number; resolved: number };
  autoAdvanceReview: boolean;
  onAutoAdvanceChange: (enabled: boolean) => void;
  onSelectFinding: (finding: Finding) => void;
  onBulkPatchFindings: (targetFindings: Finding[], update: FindingUpdate) => Promise<void>;
}

function FindingsPanel({
  findings,
  sheets,
  selectedFinding,
  scrollFindingId,
  selectedProject,
  reviewProgress,
  autoAdvanceReview,
  onAutoAdvanceChange,
  onSelectFinding,
  onBulkPatchFindings,
}: FindingsPanelProps) {
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [placementFilter, setPlacementFilter] = useState<PlacementFilter>("all");
  const [query, setQuery] = useState("");
  const findingButtonRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  const filteredFindings = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return findings.filter((finding) => {
      const matchesStatus = statusFilter === "all" || finding.status === statusFilter;
      if (!matchesStatus || !matchesPlacementFilter(finding, placementFilter)) {
        return false;
      }

      if (!needle) {
        return true;
      }

      return [
        finding.title,
        finding.category,
        finding.severity,
        finding.comment_text,
        finding.reasoning_summary,
        finding.suggested_correction,
      ]
        .filter(Boolean)
        .some((value) => value.toLowerCase().includes(needle));
    });
  }, [findings, query, statusFilter, placementFilter]);

  const hasActiveFindingFilters = statusFilter !== "all" || placementFilter !== "all" || query.trim().length > 0;
  useEffect(() => {
    if (!scrollFindingId || filteredFindings.every((finding) => finding.id !== scrollFindingId)) {
      return;
    }

    requestAnimationFrame(() => {
      findingButtonRefs.current[scrollFindingId]?.scrollIntoView({ block: "center", behavior: "smooth" });
    });
  }, [scrollFindingId, filteredFindings]);

  return (
    <section className="panel findings-panel" id="qc-log" aria-label="QC findings log">
      <div className="panel-header">
        <div>
          <span className="eyebrow">Findings</span>
          <h2>AI QC Log</h2>
        </div>
        <span className="count-pill">{findings.length}</span>
      </div>

      <div className="status-summary">
        {PRIMARY_FINDING_STATUSES.map((status) => (
          <StatusCounter key={status} label={formatStatus(status)} value={countFindingsByStatus(findings, status)} />
        ))}
      </div>

      <div className="review-queue-card" role="status">
        <div>
          <strong>{reviewProgress.remaining} left to review</strong>
          <span>{reviewProgress.resolved} resolved of {reviewProgress.total}</span>
        </div>
        <label className="checkbox-row compact-checkbox" title="After accepting or rejecting a finding, automatically select the next needs-review finding">
          <input type="checkbox" checked={autoAdvanceReview} onChange={(event) => onAutoAdvanceChange(event.target.checked)} />
          <span>Auto-advance</span>
        </label>
      </div>

      <div className="finding-tools primary-finding-tools">
        <div className="search-field">
          <Search size={16} />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search findings"
            title="Filter findings by title, category, severity, comment, reasoning, or correction"
          />
        </div>

        <div className="segmented-control" aria-label="Finding status filter">
          {(["all", ...PRIMARY_FINDING_STATUSES] as StatusFilter[]).map((status) => (
            <button
              type="button"
              key={status}
              className={statusFilter === status ? "active" : ""}
              onClick={() => setStatusFilter(status)}
              title={status === "all" ? "Show every finding" : `Show only ${formatStatus(status).toLowerCase()} findings`}
            >
              {status === "all" ? "All" : formatStatus(status)}
            </button>
          ))}
        </div>
      </div>

      <details className="collapsible-section finding-secondary-controls">
        <summary>
          <span>
            <strong>Filters and bulk actions</strong>
            <small>{filteredFindings.length} in view. Shortcuts and placement filters live here.</small>
          </span>
        </summary>
        <div className="shortcut-hints" aria-label="Reviewer keyboard shortcuts">
          <span><kbd>A</kbd> Accept</span>
          <span><kbd>X</kbd> Reject</span>
          <span><kbd>R</kbd> Review</span>
          <span><kbd>J/K</kbd> Finding</span>
          <span><kbd>[ ]</kbd> Sheet</span>
        </div>
        <div className="segmented-control placement-filter" aria-label="Finding placement filter">
          {(["all", "located", "exact", "fuzzy", "page_level", "manual", "low_confidence"] as PlacementFilter[]).map((placement) => (
            <button
              type="button"
              key={placement}
              className={placementFilter === placement ? "active" : ""}
              onClick={() => setPlacementFilter(placement)}
              title="Filter findings by placement quality"
            >
              {placementFilterLabel(placement)}
            </button>
          ))}
        </div>

        <div className="bulk-actions" aria-label="Bulk finding actions">
          <span>{filteredFindings.length} in view</span>
          <button
            className="secondary-button"
            type="button"
            disabled={filteredFindings.length === 0}
            onClick={() => void onBulkPatchFindings(filteredFindings, { status: "accepted" })}
            title="Mark all currently filtered findings as accepted"
          >
            Accept view
          </button>
          <button
            className="secondary-button"
            type="button"
            disabled={filteredFindings.length === 0}
            onClick={() => void onBulkPatchFindings(filteredFindings, { status: "needs_review" })}
            title="Return all currently filtered findings to needs review"
          >
            Review view
          </button>
          <button
            className="secondary-button"
            type="button"
            disabled={filteredFindings.length === 0}
            onClick={() => void onBulkPatchFindings(filteredFindings, { status: "rejected" })}
            title="Mark all currently filtered findings as rejected or not applicable"
          >
            Reject view
          </button>
        </div>
      </details>

      <div className="finding-list" aria-label="Finding list">
        {!selectedProject ? (
          <div className="empty-state compact">
            <FolderOpen size={18} />
            <strong>No project selected</strong>
            <small>Select a review before filtering or editing AI findings.</small>
          </div>
        ) : findings.length === 0 ? (
          <div className="empty-state compact">
            <ClipboardCheck size={18} />
            <strong>No AI findings imported yet</strong>
            <small>Use Review, then Chat Prompt, then preview and import the AI update JSON.</small>
          </div>
        ) : filteredFindings.length === 0 ? (
          <div className="empty-state compact">
            <Search size={18} />
            <strong>No findings match</strong>
            <small>{hasActiveFindingFilters ? "Clear the search or switch the status filter to All." : "No findings are available in this view."}</small>
          </div>
        ) : (
          filteredFindings.map((finding) => {
            const sheet = getFindingSheet(finding, sheets);
            return (
              <button
                key={finding.id}
                ref={(node) => {
                  findingButtonRefs.current[finding.id] = node;
                }}
                type="button"
                className={`finding-item ${finding.id === selectedFinding?.id ? "selected" : ""}`}
                onClick={() => onSelectFinding(finding)}
                title={`Open finding: ${finding.title}`}
              >
                <span className={`severity-dot severity-${severityClass(finding.severity)}`} />
                <span className="finding-item-main">
                  <strong>{finding.title}</strong>
                  <span>
                    AI | {sheet ? `P${sheet.page_number}` : "Project"} | {finding.category}
                  </span>
                </span>
                <span className={`status-chip status-${statusClass(finding.status)}`}>
                  {formatStatus(finding.status)}
                </span>
                {finding.placement_status ? (
                  <span className={`placement-chip placement-${statusClass(finding.placement_status)}`}>
                    {placementLabel(finding.placement_status)}
                  </span>
                ) : null}
              </button>
            );
          })
        )}
      </div>

    </section>
  );
}

function StatusCounter({ label, value }: { label: string; value: number }) {
  return (
    <div className="status-counter">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

function placementLabel(status?: string | null): string {
  if (status === "exact_target_found") {
    return "Placed";
  }
  if (status === "fuzzy_target_found") {
    return "Fuzzy placed";
  }
  if (status === "page_level_fallback") {
    return "Page note";
  }
  if (status === "manual_placement") {
    return "Manually placed";
  }
  if (status === "manual_placement_needed") {
    return "Needs manual placement";
  }
  return "Placement unknown";
}

function targetTextFromFinding(finding: Finding): string {
  for (const item of finding.evidence ?? []) {
    const value = item.target_text || item.markup_text || item.text_excerpt;
    if (value?.trim()) {
      return value.trim();
    }
  }
  return "";
}

interface FindingInspectorProps {
  finding: Finding | null;
  findings: Finding[];
  sheet?: Sheet;
  saving: boolean;
  deleting: boolean;
  merging: boolean;
  manualPlacementActive: boolean;
  savingManualPlacement: boolean;
  onPatchFinding: (findingId: string, update: FindingUpdate) => Promise<void>;
  onDeleteFinding: (finding: Finding) => Promise<void>;
  onMergeFinding: (finding: Finding, targetFindingId: string) => Promise<void>;
  onStartManualPlacement: (finding: Finding) => void;
  onCancelManualPlacement: () => void;
}

function FindingInspector({
  finding,
  findings,
  sheet,
  saving,
  deleting,
  merging,
  manualPlacementActive,
  savingManualPlacement,
  onPatchFinding,
  onDeleteFinding,
  onMergeFinding,
  onStartManualPlacement,
  onCancelManualPlacement,
}: FindingInspectorProps) {
  const [draft, setDraft] = useState({
    title: "",
    category: CATEGORIES[0],
    severity: "Major" as Severity,
    status: "needs_review" as FindingStatus,
    confidence: 0.75,
    page_number: 1,
    target_text: "",
    comment_text: "",
    reasoning_summary: "",
    suggested_correction: "",
    reviewer_note: "",
    merge_target_id: "",
  });

  useEffect(() => {
    if (!finding) {
      return;
    }

    setDraft({
      title: finding.title,
      category: finding.category,
      severity: finding.severity,
      status: finding.status,
      confidence: finding.confidence,
      page_number: finding.page_number ?? 1,
      target_text: targetTextFromFinding(finding),
      comment_text: finding.comment_text,
      reasoning_summary: finding.reasoning_summary,
      suggested_correction: finding.suggested_correction,
      reviewer_note: finding.reviewer_note ?? "",
      merge_target_id: "",
    });
  }, [finding]);

  if (!finding) {
    return (
      <div className="inspector empty-inspector">
        <ClipboardCheck size={20} />
        <span>No finding selected</span>
      </div>
    );
  }

  const categoryOptions = CATEGORIES.includes(draft.category)
    ? CATEGORIES
    : [draft.category, ...CATEGORIES];
  const activeFinding = finding;
  const titleIsMissing = draft.title.trim().length === 0;
  const commentIsMissing = draft.comment_text.trim().length === 0;
  const saveDisabled = saving || titleIsMissing || commentIsMissing;
  const mergeTargets = findings.filter((candidate) => candidate.id !== finding.id && candidate.source === "ai");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saveDisabled) {
      return;
    }
    const { merge_target_id: _mergeTargetId, ...findingDraft } = draft;
    void onPatchFinding(activeFinding.id, findingDraft);
  }

  return (
    <form className="inspector" onSubmit={handleSubmit}>
      <div className="inspector-header">
        <div>
          <span className="eyebrow">Inspector</span>
          <h3>{sheet ? sheetLabel(sheet) : "Project finding"}</h3>
        </div>
        <div className="inspector-badges">
          <span className={`status-chip status-${statusClass(finding.status)}`}>
            {formatStatus(finding.status)}
          </span>
          {finding.placement_status ? (
            <span className={`placement-chip placement-${statusClass(finding.placement_status)}`}>
              {placementLabel(finding.placement_status)}
            </span>
          ) : null}
        </div>
      </div>

      <label className="field-label">
        Title
        <input
          type="text"
          title="Edit the finding title shown in the QC log and exports"
          value={draft.title}
          onChange={(event) => setDraft((current) => ({ ...current, title: event.target.value }))}
        />
      </label>

      <div className="field-grid">
        <label className="field-label">
          Status
          <select
            title="Set the reviewer disposition for this AI finding"
            value={draft.status}
            onChange={(event) =>
              setDraft((current) => ({ ...current, status: event.target.value as FindingStatus }))
            }
          >
            {PRIMARY_FINDING_STATUSES.map((status) => (
              <option key={status} value={status}>
                {formatStatus(status)}
              </option>
            ))}
          </select>
        </label>

        <label className="field-label">
          Severity
          <select
            title="Set how serious this finding is before saving or exporting"
            value={draft.severity}
            onChange={(event) =>
              setDraft((current) => ({ ...current, severity: event.target.value as Severity }))
            }
          >
            {SEVERITIES.map((severity) => (
              <option key={severity} value={severity}>
                {severity}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="field-grid">
        <label className="field-label">
          Page
          <input
            type="number"
            min="1"
            title="Change the PDF page used for markup placement and export"
            value={draft.page_number}
            onChange={(event) =>
              setDraft((current) => ({ ...current, page_number: Math.max(1, Number(event.target.value) || 1) }))
            }
          />
        </label>

        <label className="field-label">
          Category
          <select
            title="Classify the finding so exported logs can be sorted and filtered"
            value={draft.category}
            onChange={(event) =>
              setDraft((current) => ({ ...current, category: event.target.value }))
            }
          >
            {categoryOptions.map((category) => (
              <option key={category} value={category}>
                {category}
              </option>
            ))}
          </select>
        </label>
      </div>

      <label className="field-label confidence-field">
        Confidence
        <div className="confidence-control">
          <input
            type="range"
            title="Adjust how confident AutoQC or the reviewer is in this finding"
            min="0.05"
            max="0.98"
            step="0.01"
            value={draft.confidence}
            onChange={(event) =>
              setDraft((current) => ({ ...current, confidence: Number(event.target.value) }))
            }
          />
          <span>{confidenceLabel(draft.confidence)}</span>
        </div>
      </label>

      <details className="collapsible-section inspector-collapsible">
        <summary>
          <span>
            <strong>Markup target text</strong>
            <small>{draft.target_text ? "Text search target saved" : "No target text"}</small>
          </span>
        </summary>
        <label className="field-label">
          Target text / evidence
          <textarea
            title="Exact text AutoQC should search for when placing the PDF markup"
            value={draft.target_text}
            rows={2}
            onChange={(event) =>
              setDraft((current) => ({ ...current, target_text: event.target.value }))
            }
          />
        </label>
      </details>

      <label className="field-label">
        Final PDF comment
        <textarea
          title="This is the comment that will appear in the marked PDF and review exports"
          value={draft.comment_text}
          rows={3}
          onChange={(event) =>
            setDraft((current) => ({ ...current, comment_text: event.target.value }))
          }
        />
      </label>

      <label className="field-label">
        Required update
        <textarea
          title="Describe what the drafter or reviewer should change to close this finding"
          value={draft.suggested_correction}
          rows={3}
          onChange={(event) =>
            setDraft((current) => ({ ...current, suggested_correction: event.target.value }))
          }
          />
        </label>

      <section className="manual-placement-tools" aria-label="Manual markup placement">
        <div>
          <strong>Manual markup placement</strong>
          <span>{placementQualityLabel(findingPlacementStatus(finding))}</span>
        </div>
        <button
          className={manualPlacementActive ? "secondary-button active" : "secondary-button"}
          type="button"
          disabled={savingManualPlacement}
          onClick={() => (manualPlacementActive ? onCancelManualPlacement() : onStartManualPlacement(finding))}
          title="For page-level or poorly placed findings, drag a rectangle on the drawing image to set the export cloud location"
        >
          {savingManualPlacement ? <Loader2 size={16} className="spin" /> : <Maximize2 size={16} />}
          {manualPlacementActive ? "Cancel placement" : "Place on drawing"}
        </button>
      </section>

      <details className="collapsible-section inspector-collapsible">
        <summary>
          <span>
            <strong>Rationale, reviewer note, and evidence</strong>
            <small>{finding.evidence?.length ? `${finding.evidence.length} evidence item${finding.evidence.length === 1 ? "" : "s"}` : "Collapsed details"}</small>
          </span>
        </summary>
        <label className="field-label">
          Rationale
          <textarea
            title="Document why this finding exists and what evidence supports it"
            value={draft.reasoning_summary}
            rows={4}
            onChange={(event) =>
              setDraft((current) => ({ ...current, reasoning_summary: event.target.value }))
            }
          />
        </label>

        <label className="field-label">
          Reviewer note
          <textarea
            title="Internal reviewer note for audit/debugging; it is included in the QA report"
            value={draft.reviewer_note}
            rows={3}
            onChange={(event) =>
              setDraft((current) => ({ ...current, reviewer_note: event.target.value }))
            }
          />
        </label>

        <div className="finding-details">
          <span>
            <strong>Confidence</strong> {confidenceLabel(draft.confidence)}
          </span>
          <span>
            <strong>Source</strong> {finding.source === "ai" ? "AI-sourced finding" : finding.source || "unknown"}
          </span>
          <span>
            <strong>Placement</strong> {placementLabel(finding.placement_status)}
          </span>
          {finding.ai_batch_id ? (
            <span>
              <strong>AI batch</strong> {finding.ai_batch_id}
            </span>
          ) : null}
          {finding.prompt_version ? (
            <span>
              <strong>Prompt</strong> {finding.prompt_version}
            </span>
          ) : null}
          {finding.stable_id ? (
            <span>
              <strong>ID</strong> {finding.stable_id}
            </span>
          ) : null}
        </div>

        {finding.evidence?.length ? (
          <div className="evidence-list">
            <strong>Evidence</strong>
            {finding.evidence.map((item, index) => (
              <div className="evidence-item" key={`${finding.id}-${index}`}>
                <span>{item.observation || item.text_excerpt || "Evidence item"}</span>
                <small>
                  {item.drawing_number || (item.page_number ? `Page ${item.page_number}` : "Project")}
                </small>
              </div>
            ))}
          </div>
        ) : null}
      </details>

      {(finding.duplicate_of || finding.status === "duplicate") ? (
      <details className="collapsible-section inspector-collapsible">
        <summary>
          <span>
            <strong>Duplicate / merge</strong>
            <small>{finding.duplicate_of ? "Duplicate link saved" : "Optional dedupe tools"}</small>
          </span>
        </summary>
        <div className="dedupe-tools">
          <button
            className="secondary-button"
            type="button"
            disabled={saving || finding.status === "duplicate"}
            onClick={() => void onPatchFinding(finding.id, { status: "duplicate" })}
            title="Mark this finding as a duplicate and hide it from accepted-only exports"
          >
            <History size={16} />
            Mark as duplicate
          </button>
          <button
            className="secondary-button"
            type="button"
            disabled={saving || finding.status === "duplicate"}
            onClick={() => void onPatchFinding(finding.id, { status: "duplicate" })}
            title="Hide this duplicate from normal export selections by setting status to Duplicate"
          >
            <ShieldCheck size={16} />
            Hide duplicate from export
          </button>
          <label className="field-label">
            Merge into selected finding
            <select
              value={draft.merge_target_id}
              onChange={(event) => setDraft((current) => ({ ...current, merge_target_id: event.target.value }))}
              title="Choose the finding that should receive this duplicate's evidence"
            >
              <option value="">Choose target finding</option>
              {mergeTargets.map((target) => (
                <option key={target.id} value={target.id}>
                  {target.title}
                </option>
              ))}
            </select>
          </label>
          <button
            className="secondary-button"
            type="button"
            disabled={!draft.merge_target_id || merging}
            onClick={() => void onMergeFinding(finding, draft.merge_target_id)}
            title="Preserve this finding as duplicate and merge its evidence into the selected target"
          >
            {merging ? <Loader2 size={16} className="spin" /> : <Archive size={16} />}
            Merge
          </button>
        </div>
      </details>
      ) : null}

      {titleIsMissing || commentIsMissing ? (
        <div className="inline-warning" role="alert">
          Add a title and final PDF comment before saving. These fields keep the findings log and marked PDF readable.
        </div>
      ) : null}

      <div className="inspector-actions">
        <button
          className="primary-button"
          type="submit"
          disabled={saveDisabled}
          title={saveDisabled ? "Add a title and final PDF comment before saving" : "Save title, severity, category, confidence, comments, correction, and reasoning edits"}
        >
          {saving ? <Loader2 size={17} className="spin" /> : <Save size={17} />}
          Save
        </button>
        <button
          className="secondary-button"
          type="button"
          disabled={saving}
          onClick={() => void onPatchFinding(finding.id, { status: "accepted" })}
          title="Mark this finding as valid and include it in accepted exports"
        >
          <Check size={17} />
          Accept
        </button>
        <button
          className="secondary-button"
          type="button"
          disabled={saving}
          onClick={() => void onPatchFinding(finding.id, { status: "needs_review" })}
          title="Keep this finding open for more review"
        >
          <ClipboardCheck size={17} />
          Review
        </button>
        <button
          className="secondary-button"
          type="button"
          disabled={saving}
          onClick={() => void onPatchFinding(finding.id, { status: "rejected" })}
          title="Mark this finding as not applicable or not a real issue"
        >
          <X size={17} />
          Reject
        </button>
        <button
          className="danger-button"
          type="button"
          disabled={deleting}
          onClick={() => void onDeleteFinding(finding)}
          title="Permanently remove this finding from the project after confirmation"
        >
          {deleting ? <Loader2 size={17} className="spin" /> : <Trash2 size={17} />}
          Delete
        </button>
      </div>
    </form>
  );
}

interface ExportPanelProps {
  project: Project | null;
  findings: Finding[];
  events: FindingEvent[];
  onExportComplete?: (response: ExportResponse) => Promise<void>;
}

function ExportPanel({ project, findings, events, onExportComplete }: ExportPanelProps) {
  const [statuses, setStatuses] = useState<FindingStatus[]>(["accepted"]);
  const [exportMode, setExportMode] = useState<"draft" | "final">("draft");
  const [reviewerName, setReviewerName] = useState("Local reviewer");
  const [finalConfirmed, setFinalConfirmed] = useState(false);
  const [acknowledgeValidationWarnings, setAcknowledgeValidationWarnings] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [result, setResult] = useState<ExportResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [exportOperation, setExportOperation] = useState<OperationProgress | null>(null);

  function toggleStatus(status: FindingStatus) {
    setStatuses((current) => {
      if (current.includes(status)) {
        return current.filter((item) => item !== status);
      }

      return [...current, status];
    });
  }

  async function handleExport() {
    if (!project || statuses.length === 0) {
      return;
    }

    setExporting(true);
    setResult(null);
    setError(null);
    setExportOperation({
      id: `${Date.now()}-export`,
      title: exportMode === "final" ? "Export Final Marked PDF" : "Export Draft Marked PDF",
      status: "active",
      steps: exportMode === "final"
        ? ["Checking readiness", "Writing marked PDF", "Validating PDF", "Writing reports"]
        : ["Collecting selected findings", "Writing marked PDF", "Validating PDF", "Writing reports"],
      currentStep: 0,
      message: exportMode === "final" ? "Checking final export readiness gates." : "Collecting selected findings for draft export.",
      startedAt: Date.now(),
    });

    try {
      setExportOperation((current) => current ? { ...current, currentStep: 1, message: "Writing the marked PDF and QA artifacts." } : current);
      const response = await exportProject(project.id, {
        statuses: exportMode === "final" ? ["accepted"] : statuses,
        export_mode: exportMode,
        reviewer_name: reviewerName,
        final_export_confirmed: exportMode === "final" ? finalConfirmed : false,
        acknowledge_validation_warnings: acknowledgeValidationWarnings,
      });
      setExportOperation((current) => current ? { ...current, currentStep: 3, status: "success", message: `${exportMode === "final" ? "Final" : "Draft"} export created and validated: ${response.validation?.status ?? "not reported"}.` } : current);
      setResult(response);
      await onExportComplete?.(response);
    } catch (requestError) {
      const message = getApiErrorMessage(requestError);
      setError(message);
      setExportOperation((current) => current ? { ...current, currentStep: 0, status: "error", message: `${exportMode === "final" ? "Final" : "Draft"} export failed. ${message}` } : current);
    } finally {
      setExporting(false);
    }
  }

  const outputRows = result
    ? [
        { label: "Marked PDF", value: result.marked_pdf },
        { label: "QA report", value: result.qa_report ?? result.csv_log },
        { label: "Excel log", value: result.excel_log },
        { label: "JSON findings", value: result.json_findings },
        { label: "Markdown", value: result.markdown_summary },
        { label: "HTML", value: result.html_summary },
      ].filter((row): row is { label: string; value: string } => Boolean(row.value))
    : [];
  const selectedFindingCount = findings.filter((finding) => statuses.includes(finding.status)).length;
  const effectiveStatuses = exportMode === "final" ? (["accepted"] as FindingStatus[]) : statuses;
  const effectiveFindingCount = findings.filter((finding) => effectiveStatuses.includes(finding.status)).length;
  const reviewCoverage = project?.review_coverage ?? null;
  const finalCoverageReady = reviewCoverage?.review_coverage_status === "complete";
  const finalManualPlacementCount = findings.filter(
    (finding) =>
      effectiveStatuses.includes(finding.status) &&
      (finding.status === "needs_manual_placement" || finding.placement_status === "manual_placement_needed"),
  ).length;
  const reviewerNameIssue = exportMode === "final" ? finalReviewerNameIssue(reviewerName) : null;
  const finalBlockerText = finalExportBlockerSummary(reviewCoverage, effectiveFindingCount, finalManualPlacementCount);
  const finalReady = exportMode !== "final" || (finalCoverageReady && finalManualPlacementCount === 0 && finalConfirmed && !reviewerNameIssue);
  const exportDisabled = !project || effectiveStatuses.length === 0 || effectiveFindingCount === 0 || exporting || !finalReady;
  const exportTitle = !project
    ? "Select a project before exporting"
    : effectiveStatuses.length === 0
      ? "Choose at least one finding status to export"
      : effectiveFindingCount === 0
        ? "No findings match the selected export statuses"
        : reviewerNameIssue
          ? reviewerNameIssue
        : exportMode === "final" && !finalReady
          ? "Complete the final export readiness requirements first"
        : "Generate marked PDF, logs, and summaries for the selected finding statuses";
  const markedPdfHref = resolveAssetUrl(result?.marked_pdf);
  const qaReportHref = resolveAssetUrl(result?.qa_report ?? result?.csv_log);
  const htmlSummaryHref = resolveAssetUrl(result?.html_summary);

  return (
    <section className="panel export-panel">
      <div className="panel-header">
        <div>
          <span className="eyebrow">Export</span>
          <h2>Marked PDF</h2>
        </div>
        <Download size={18} />
      </div>

      <div className="export-helper" role="status">
        Default: export accepted findings to a marked PDF. Use advanced options only when you need draft/final controls or a different status set.
      </div>

      <details className="collapsible-section advanced-export-options">
        <summary>
          <span>
            <strong>Advanced export options</strong>
            <small>Statuses, draft/final mode, reviewer signoff, generated files, and audit activity</small>
          </span>
        </summary>

      <div className="segmented-control export-mode-control" role="radiogroup" aria-label="Export mode">
        <button
          type="button"
          className={exportMode === "draft" ? "active" : ""}
          onClick={() => setExportMode("draft")}
          title="Draft exports may include selected reviewer statuses and are clearly marked as draft"
        >
          Draft
        </button>
        <button
          type="button"
          className={exportMode === "final" ? "active" : ""}
          onClick={() => {
            setExportMode("final");
            setStatuses(["accepted"]);
          }}
          title="Final exports require complete review coverage, accepted findings, validation, and reviewer signoff"
        >
          Final
        </button>
      </div>

      <div className={`export-mode-explanation mode-${exportMode}`} role="status">
        {exportMode === "final" ? (
          <>
            <strong>Final package controls are strict.</strong>
            <span>Final exports include accepted findings only, require complete imported review coverage, block manual-placement findings, and record reviewer signoff.</span>
          </>
        ) : (
          <>
            <strong>Draft package for working review.</strong>
            <span>Draft exports can include selected statuses for coordination. They are not a final engineering signoff package.</span>
          </>
        )}
      </div>

      <div className="export-counts">
        {STATUSES.map((status) => (
          <label
            className="checkbox-row"
            key={status}
            title={`Include ${formatStatus(status).toLowerCase()} findings in the generated review package`}
          >
            <input
              type="checkbox"
              checked={(exportMode === "final" ? status === "accepted" : statuses.includes(status))}
              disabled={exportMode === "final"}
              onChange={() => toggleStatus(status)}
            />
            <span>{formatStatus(status)}</span>
            <strong>{countFindingsByStatus(findings, status)}</strong>
          </label>
        ))}
      </div>

      <div className="export-helper" role="status">
        {project ? `${effectiveFindingCount} finding${effectiveFindingCount === 1 ? "" : "s"} selected for ${exportMode} export.` : "Select a project to prepare exports."}
      </div>

      {exportMode === "final" ? (
        <div className="final-readiness-requirements" aria-label="Final export readiness requirements">
          <strong>Final export readiness</strong>
          <span className={finalCoverageReady ? "done" : "blocked"}><Check size={13} /> Review coverage {reviewCoverage ? `${formatStatus(reviewCoverage.review_coverage_status)} ${reviewCoverage.review_coverage_percent}%` : "not confirmed"}</span>
          <span className={effectiveFindingCount > 0 ? "done" : "blocked"}><Check size={13} /> Accepted findings selected</span>
          <span className={finalManualPlacementCount === 0 ? "done" : "blocked"}><Check size={13} /> No manual placement blockers</span>
          <details className="why-blocked-details">
            <summary>Why blocked?</summary>
            <small>{finalBlockerText}</small>
          </details>
          <label className="field-label">
            Reviewer
            <input value={reviewerName} onChange={(event) => setReviewerName(event.target.value)} placeholder="Responsible reviewer name" />
          </label>
          {reviewerNameIssue ? <div className="inline-warning compact-error" role="alert">{reviewerNameIssue}</div> : null}
          <label className="checkbox-row">
            <input type="checkbox" checked={finalConfirmed} onChange={(event) => setFinalConfirmed(event.target.checked)} />
            <span>Confirm final export signoff</span>
          </label>
          <label className="checkbox-row">
            <input type="checkbox" checked={acknowledgeValidationWarnings} onChange={(event) => setAcknowledgeValidationWarnings(event.target.checked)} />
            <span>Acknowledge generated PDF validation warnings if any remain</span>
          </label>
        </div>
      ) : null}
      </details>

      {exportOperation ? <OperationProgressPanel operation={exportOperation} onDismiss={exportOperation.status === "active" ? undefined : () => setExportOperation(null)} /> : null}

      {project && effectiveStatuses.length > 0 && effectiveFindingCount === 0 ? (
        <div className="inline-warning" role="alert">
          No findings match the selected status filters. Choose another status or update findings before exporting.
        </div>
      ) : null}

      <button
        className="primary-button full-width"
        type="button"
        disabled={exportDisabled}
        onClick={() => void handleExport()}
        title={exportTitle}
      >
        {exporting ? <Loader2 size={17} className="spin" /> : <Download size={17} />}
        {exporting ? "Exporting Marked PDF" : "Export Marked PDF"}
      </button>

      {error ? <div className="inline-error" role="alert">{error}</div> : null}

      {result ? (
        <div className={`export-result-summary validation-${statusClass(result.validation?.status ?? "not_reported")}`} role="status">
          <strong>{exportResultTitle(result)}</strong>
          <span>{exportResultExplanation(result)}</span>
        </div>
      ) : null}

      {result?.placement_summary ? (
        <div className="export-placement-summary" role="status">
          <strong>Export placement</strong>
          <span>{placementSummaryText(result.placement_summary)}</span>
        </div>
      ) : null}

      {result?.validation ? (
        <div className={`export-validation validation-${statusClass(result.validation.status)}`} role={result.validation.status === "failed" ? "alert" : "status"}>
          <strong>Validation {validationStatusLabel(result.validation.status)}</strong>
          <span>
            {result.validation.annotation_count ?? 0} annotation{result.validation.annotation_count === 1 ? "" : "s"} | {result.validation.marked_page_count ?? "?"}/{result.validation.source_page_count ?? "?"} pages
          </span>
          {result.validation.errors?.slice(0, 2).map((item) => <small key={item}>{item}</small>)}
          {result.validation.warnings?.slice(0, 2).map((item) => <small key={item}>{item}</small>)}
        </div>
      ) : null}

      {result?.review_coverage ? (
        <div className={`coverage-banner coverage-${statusClass(result.review_coverage.review_coverage_status)}`} role="status">
          <strong>Review coverage {formatStatus(result.review_coverage.review_coverage_status)}</strong>
          <span>{result.review_coverage.review_coverage_percent}% confirmed</span>
        </div>
      ) : null}

      {result?.signoff ? (
        <div className="export-validation" role="status">
          <strong>Reviewer signoff</strong>
          <span>{result.signoff.reviewer_name} | {formatDate(result.signoff.timestamp)}</span>
        </div>
      ) : null}

      {result ? (
        <div className="export-result-actions" aria-label="Generated report shortcuts">
          {markedPdfHref ? (
            <a href={markedPdfHref} target="_blank" rel="noreferrer" download title="Open or download the marked PDF">
              <FileText size={15} />
              Marked PDF
            </a>
          ) : null}
          {qaReportHref ? (
            <a href={qaReportHref} target="_blank" rel="noreferrer" title="Open the QA report or CSV log">
              <FileText size={15} />
              QA report
            </a>
          ) : null}
          {htmlSummaryHref ? (
            <a href={htmlSummaryHref} target="_blank" rel="noreferrer" title="Open the HTML review summary">
              <ExternalLink size={15} />
              HTML summary
            </a>
          ) : null}
        </div>
      ) : null}

      {result?.marked_pdf ? (
        <a
          className="download-pdf-button"
          href={markedPdfHref ?? result.marked_pdf}
          download
          target="_blank"
          rel="noreferrer"
          title="Download the marked-up PDF with AutoQC note comments"
        >
          <Download size={20} />
          Download Marked PDF
        </a>
      ) : null}

      {result ? (
        <details className="output-list collapsible-section">
          <summary>
            <span>
              <strong>Generated files</strong>
              <small>{typeof result.findings_exported === "number" ? `${result.findings_exported} findings exported` : `${outputRows.length} files`}</small>
            </span>
          </summary>
          {outputRows.map((row) => {
            const href = resolveAssetUrl(row.value);
            return (
              <div className="output-row" key={row.label}>
                <div className="output-row-header">
                  <span>{row.label}</span>
                  {href ? (
                    <a href={href} target="_blank" rel="noreferrer" title={`Open generated ${row.label.toLowerCase()}`}>
                      Open
                    </a>
                  ) : null}
                </div>
                <code>{row.value}</code>
              </div>
            );
          })}
        </details>
      ) : null}

      {events.length > 0 ? (
        <details className="audit-list collapsible-section">
          <summary>
            <span>
              <strong>Recent audit activity</strong>
              <small>{events.length} event{events.length === 1 ? "" : "s"}</small>
            </span>
          </summary>
          {events.slice(0, 5).map((event) => (
            <div className="audit-row" key={event.id}>
              <span>{formatStatus(event.action.replace(/_/g, " "))}</span>
              <small>{formatDate(event.created_at)}</small>
            </div>
          ))}
        </details>
      ) : null}
    </section>
  );
}

function findingMatchesSheet(finding: Finding, sheet: Sheet): boolean {
  if (finding.sheet_id && finding.sheet_id === sheet.id) {
    return true;
  }

  return Boolean(finding.page_number && finding.page_number === sheet.page_number);
}

function extractRectArray(value: unknown): number[] | null {
  if (!Array.isArray(value) || value.length < 4) {
    return null;
  }

  const coordinates = value.slice(0, 4).map((coordinate) => Number(coordinate));
  if (coordinates.some((coordinate) => !Number.isFinite(coordinate))) {
    return null;
  }

  return [
    Math.min(coordinates[0], coordinates[2]),
    Math.min(coordinates[1], coordinates[3]),
    Math.max(coordinates[0], coordinates[2]),
    Math.max(coordinates[1], coordinates[3]),
  ];
}

function extractPlacementBbox(placementDetails: Record<string, unknown> | null | undefined): number[] | null {
  if (!placementDetails || typeof placementDetails !== "object" || Array.isArray(placementDetails)) {
    return null;
  }

  return extractRectArray(placementDetails.rect_json);
}

function extractPlacementDisplayBbox(placementDetails: Record<string, unknown> | null | undefined): number[] | null {
  if (!placementDetails || typeof placementDetails !== "object" || Array.isArray(placementDetails)) {
    return null;
  }

  return extractRectArray(placementDetails.display_rect_json);
}

function extractManualImageBbox(
  location: Finding["location"],
  placementDetails: Record<string, unknown> | null | undefined,
): number[] | null {
  if (placementDetails && typeof placementDetails === "object" && !Array.isArray(placementDetails)) {
    const placementCoordinateSpace = String(placementDetails.coordinate_space ?? "");
    const manualImageRect = extractRectArray(placementDetails.manual_image_rect_json);
    if (placementCoordinateSpace === "image_pixel" && manualImageRect) {
      return manualImageRect;
    }
  }

  if (location && typeof location === "object" && !Array.isArray(location)) {
    const locationCoordinateSpace = String(location.coordinate_space ?? "");
    const manualImageRect = extractRectArray(location.manual_image_rect);
    const bbox = extractRectArray(location.bbox);
    if (locationCoordinateSpace === "image_pixel") {
      return manualImageRect ?? bbox;
    }
  }

  return null;
}

function numericDetail(placementDetails: Record<string, unknown> | null | undefined, key: string): number | null {
  if (!placementDetails || typeof placementDetails !== "object" || Array.isArray(placementDetails)) {
    return null;
  }
  const value = Number(placementDetails[key]);
  return Number.isFinite(value) ? value : null;
}

function normalizedRotation(value: unknown): number {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return 0;
  }
  const rotation = ((Math.round(numeric / 90) * 90) % 360 + 360) % 360;
  return rotation === 90 || rotation === 180 || rotation === 270 ? rotation : 0;
}

function sheetDisplayRotation(sheet: Sheet, placementDetails: Record<string, unknown> | null | undefined): number {
  return normalizedRotation(numericDetail(placementDetails, "page_rotation") ?? sheet.rotation ?? 0);
}

function rotateBboxForDisplay(
  bbox: number[],
  rotation: number,
  coordinateWidth: number,
  coordinateHeight: number,
): number[] {
  if (rotation === 0) {
    return bbox;
  }

  const corners = [
    [bbox[0], bbox[1]],
    [bbox[2], bbox[1]],
    [bbox[2], bbox[3]],
    [bbox[0], bbox[3]],
  ];
  const transformed = corners.map(([x, y]) => {
    if (rotation === 90) {
      return [coordinateHeight - y, x];
    }
    if (rotation === 180) {
      return [coordinateWidth - x, coordinateHeight - y];
    }
    return [y, coordinateWidth - x];
  });
  const xs = transformed.map(([x]) => x);
  const ys = transformed.map(([, y]) => y);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}

function getOverlayBoxPercent(
  finding: Finding,
  sheet: Sheet,
  imageSize: ImageSize | null,
): OverlayBoxPercent | null {
  const manualImageBbox = extractManualImageBbox(finding.location, finding.placement_details);
  if (manualImageBbox && imageSize) {
    return imagePixelRectToOverlayPercent(manualImageBbox, imageSize);
  }

  const locationBbox = extractBbox(finding.location);
  const placementDisplayBbox = extractPlacementDisplayBbox(finding.placement_details);
  const placementBbox = extractPlacementBbox(finding.placement_details);
  const bbox = locationBbox ?? placementDisplayBbox ?? placementBbox;
  if (!bbox) {
    return null;
  }

  const [rawX0, rawY0, rawX1, rawY1] = bbox;
  const normalized = bbox.every((coordinate) => coordinate >= 0 && coordinate <= 1);
  const displayWidth = sheet.width ?? imageSize?.width ?? null;
  const displayHeight = sheet.height ?? imageSize?.height ?? null;

  if (normalized) {
    return {
      left: clamp(rawX0 * 100, 0, 100),
      top: clamp(rawY0 * 100, 0, 100),
      width: clamp((rawX1 - rawX0) * 100, 0.6, 100),
      height: clamp((rawY1 - rawY0) * 100, 0.6, 100),
    };
  }

  if (!displayWidth || !displayHeight) {
    return null;
  }

  const bboxIsAlreadyDisplaySpace = !locationBbox && Boolean(placementDisplayBbox);
  const rotation = bboxIsAlreadyDisplaySpace ? 0 : sheetDisplayRotation(sheet, finding.placement_details);
  const coordinateWidth = numericDetail(finding.placement_details, "source_width")
    ?? sheet.source_width
    ?? (rotation === 90 || rotation === 270 ? displayHeight : displayWidth);
  const coordinateHeight = numericDetail(finding.placement_details, "source_height")
    ?? sheet.source_height
    ?? (rotation === 90 || rotation === 270 ? displayWidth : displayHeight);

  const origin = typeof finding.location === "object" && !Array.isArray(finding.location)
    ? finding.location?.origin
    : "top_left";

  const y0 = origin === "bottom_left" ? coordinateHeight - rawY1 : rawY0;
  const y1 = origin === "bottom_left" ? coordinateHeight - rawY0 : rawY1;
  const displayBbox = rotateBboxForDisplay([rawX0, y0, rawX1, y1], rotation, coordinateWidth, coordinateHeight);
  const [displayX0, displayY0, displayX1, displayY1] = displayBbox;

  return {
    left: clamp((displayX0 / displayWidth) * 100, 0, 100),
    top: clamp((displayY0 / displayHeight) * 100, 0, 100),
    width: clamp(((displayX1 - displayX0) / displayWidth) * 100, 0.6, 100),
    height: clamp(((displayY1 - displayY0) / displayHeight) * 100, 0.6, 100),
  };
}

function imagePixelRectToOverlayPercent(rect: number[], imageSize: ImageSize): OverlayBoxPercent | null {
  if (!imageSize.width || !imageSize.height) {
    return null;
  }

  const bbox = extractRectArray(rect);
  if (!bbox) {
    return null;
  }

  const [x0, y0, x1, y1] = bbox;
  return {
    left: clamp((x0 / imageSize.width) * 100, 0, 100),
    top: clamp((y0 / imageSize.height) * 100, 0, 100),
    width: clamp(((x1 - x0) / imageSize.width) * 100, 0.6, 100),
    height: clamp(((y1 - y0) / imageSize.height) * 100, 0.6, 100),
  };
}

function getOverlayRect(
  finding: Finding,
  sheet: Sheet,
  imageSize: ImageSize | null,
): CSSProperties | null {
  const box = getOverlayBoxPercent(finding, sheet, imageSize);
  if (!box) {
    return null;
  }

  return {
    left: `${box.left}%`,
    top: `${box.top}%`,
    width: `${box.width}%`,
    height: `${box.height}%`,
  };
}

function percentBoxToSourceRect(box: OverlayBoxPercent, sheet: Sheet, imageSize: ImageSize): number[] | null {
  const sourceWidth = sheet.source_width ?? sheet.width ?? imageSize.width;
  const sourceHeight = sheet.source_height ?? sheet.height ?? imageSize.height;
  if (!sourceWidth || !sourceHeight) {
    return null;
  }
  const x0 = (box.left / 100) * sourceWidth;
  const y0 = (box.top / 100) * sourceHeight;
  const x1 = ((box.left + box.width) / 100) * sourceWidth;
  const y1 = ((box.top + box.height) / 100) * sourceHeight;
  return [roundRectCoord(x0), roundRectCoord(y0), roundRectCoord(x1), roundRectCoord(y1)];
}

function roundRectCoord(value: number): number {
  return Math.round(value * 100) / 100;
}

function nextUnreviewedFinding(findings: Finding[], currentId: string): Finding | null {
  const currentIndex = Math.max(0, findings.findIndex((finding) => finding.id === currentId));
  const ordered = [...findings.slice(currentIndex + 1), ...findings.slice(0, currentIndex + 1)];
  return ordered.find((finding) => finding.status === "needs_review" && finding.id !== currentId) ?? null;
}

function findingPlacementStatus(finding: Finding): string {
  const hasBox = extractPlacementBbox(finding.placement_details) || extractBbox(finding.location);
  return String(finding.placement_status || finding.placement_details?.placement_status || (hasBox ? "exact_target_found" : "manual_placement_needed"));
}

function matchesPlacementFilter(finding: Finding, filter: PlacementFilter): boolean {
  if (filter === "all") {
    return true;
  }
  const status = findingPlacementStatus(finding);
  if (filter === "located") {
    return status === "exact_target_found" || status === "fuzzy_target_found" || status === "manual_placement";
  }
  if (filter === "exact") {
    return status === "exact_target_found";
  }
  if (filter === "fuzzy") {
    return status === "fuzzy_target_found";
  }
  if (filter === "page_level") {
    return status === "page_level_fallback";
  }
  if (filter === "low_confidence") {
    return finding.confidence < 0.6;
  }
  return status === "manual_placement_needed" || status === "manual_placement";
}

function placementFilterLabel(filter: PlacementFilter): string {
  return {
    all: "All placement",
    located: "Located",
    exact: "Exact",
    fuzzy: "Fuzzy",
    page_level: "Page-level",
    manual: "Manual",
    low_confidence: "Low confidence",
  }[filter];
}

function computePlacementSummary(findings: Finding[]): PlacementSummary {
  const summary: PlacementSummary = {
    exact_target_found: 0,
    fuzzy_target_found: 0,
    page_level_fallback: 0,
    manual_placement: 0,
    manual_placement_needed: 0,
  };
  for (const finding of findings) {
    const status = findingPlacementStatus(finding);
    summary[status] = (summary[status] ?? 0) + 1;
  }
  return summary;
}

function placementQualityLabel(status: string): string {
  return {
    exact_target_found: "Exact target found",
    fuzzy_target_found: "Fuzzy target found",
    page_level_fallback: "Page-level finding",
    manual_placement: "Manual placement saved",
    manual_placement_needed: "Manual placement needed",
  }[status] ?? formatStatus(status);
}

function validationStatusLabel(status: string): string {
  if (status === "passed") {
    return "Passed";
  }
  if (status === "warning") {
    return "Warning";
  }
  if (status === "failed") {
    return "Failed";
  }
  return formatStatus(status);
}

function placementSummaryText(summary: PlacementSummary): string {
  const exact = summary.exact_target_found ?? 0;
  const fuzzy = summary.fuzzy_target_found ?? 0;
  const page = summary.page_level_fallback ?? 0;
  const manualPlaced = summary.manual_placement ?? 0;
  const manual = summary.manual_placement_needed ?? 0;
  return `Placement: ${exact} exact, ${fuzzy} fuzzy, ${page} page-level, ${manualPlaced} manual placed, ${manual} manual needed.`;
}

function humanAuditAction(event: FindingEvent): string {
  const labels: Record<string, string> = {
    ai_import_previewed: "AI import preview created",
    ai_import_failed: "AI import preview failed",
    ai_import_imported: "AI updates imported",
    ai_import_batch_rolled_back: "AI import batch rolled back",
    ai_import_batch_rollback_removed_finding: "Imported finding removed by rollback",
    finding_edit: "Finding edited",
    status_change: "Finding status changed",
    bulk_update: "Bulk status change",
    bulk_status_rollback: "Bulk status rollback",
    placement_recalculated: "Placement recalculated",
    export_created: "Review package exported",
    draft_export_created: "Draft export created",
    final_export_created: "Final export created",
    final_export_blocked: "Final export blocked",
    delete: "Finding deleted",
    finding_marked_duplicate: "Finding marked as duplicate",
    finding_merged_duplicate_evidence: "Duplicate evidence merged",
    manual_ai_prompt_generated: "Chat Prompt generated",
    project_package_exported: "Project package exported",
    project_package_imported: "Project package imported",
  };
  return labels[event.action] ?? formatStatus(event.action.replace(/_/g, " "));
}

function auditChangeSummary(changes: Record<string, unknown>): string {
  const parts = Object.entries(changes)
    .slice(0, 5)
    .map(([key, value]) => {
      if (typeof value === "object" && value && "from" in value && "to" in value) {
        const typed = value as { from?: unknown; to?: unknown };
        return `${key}: ${auditChangeValueSummary(key, typed.from)} -> ${auditChangeValueSummary(key, typed.to)}`;
      }
      if (Array.isArray(value)) {
        return `${key}: ${value.length} item${value.length === 1 ? "" : "s"}`;
      }
      if (typeof value === "object" && value) {
        return `${key}: ${JSON.stringify(sanitizeAuditObject(value as Record<string, unknown>))}`;
      }
      return `${key}: ${auditChangeValueSummary(key, value)}`;
    });
  return parts.join(" | ");
}

function auditChangeValueSummary(key: string, value: unknown): string {
  if (typeof value !== "string") {
    return String(value ?? "");
  }
  if (!looksLikeLocalPathKey(key) && !looksLikeLocalPath(value)) {
    return value;
  }
  const parts = value.split(/[\\/]+/).filter(Boolean);
  const filename = parts[parts.length - 1];
  return filename ? `[local path hidden: ${filename}]` : "[local path hidden]";
}

function sanitizeAuditObject(value: Record<string, unknown>): Record<string, unknown> {
  const sanitized: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) {
    if (typeof item === "string") {
      sanitized[key] = auditChangeValueSummary(key, item);
    } else if (Array.isArray(item)) {
      sanitized[key] = item.map((entry) =>
        typeof entry === "object" && entry && !Array.isArray(entry)
          ? sanitizeAuditObject(entry as Record<string, unknown>)
          : entry,
      );
    } else if (typeof item === "object" && item) {
      sanitized[key] = sanitizeAuditObject(item as Record<string, unknown>);
    } else {
      sanitized[key] = item;
    }
  }
  return sanitized;
}

function looksLikeLocalPathKey(key: string): boolean {
  const normalized = key.toLowerCase();
  return normalized.includes("path") || normalized.endsWith("_dir") || normalized.includes("directory");
}

function looksLikeLocalPath(value: string): boolean {
  return /^[A-Za-z]:[\\/]/.test(value) || value.startsWith("\\\\") || /^\/(?:Users|home|var|tmp|mnt)\//.test(value);
}

function normalizeAIProvider(value?: string | null): "openai" | "deepseek" | null {
  const normalized = (value || "").trim().toLowerCase().replace(/[\s_-]+/g, "");
  if (normalized === "openai" || normalized === "openaicompatible") {
    return "openai";
  }
  if (normalized === "deepseek" || normalized === "deepseekai") {
    return "deepseek";
  }
  return null;
}

function formatAIProvider(value?: string | null): string {
  const provider = normalizeAIProvider(value) || "openai";
  return provider === "deepseek" ? "DeepSeek" : "OpenAI";
}

function strongAIModelExamples(provider: "openai" | "deepseek"): string {
  return provider === "deepseek"
    ? "deepseek-reasoner for deeper review, or deepseek-chat for faster review"
    : "gpt-5.5-thinking for deep review, or gpt-5.5-pro if available on your account";
}

function defaultAIModelForProvider(provider: "openai" | "deepseek"): string {
  return provider === "deepseek" ? "deepseek-reasoner" : "gpt-5.5-thinking";
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export default App;
