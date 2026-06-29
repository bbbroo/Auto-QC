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
  exportProject,
  exportProjectPackage,
  getReadiness,
  getAIStatus,
  getApiErrorMessage,
  getMarkupMemorySettings,
  getMarkupMemoryStats,
  getManualAIPrompt,
  getManualReviewPlan,
  getProjectChecklist,
  getProject,
  importProjectPackage,
  importManualAIPreview,
  listChecklistTemplates,
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
  selectProjectChecklist,
  updateProjectChecklistItem,
  updateMarkupMemorySettings,
  updateFinding,
} from "./api";
import type {
  AIStatus,
  AIImportBatch,
  AIPreviewResponse,
  BatchRollbackPreview,
  ChecklistItem,
  ChecklistItemUpdate,
  ChecklistStatus,
  ChecklistTemplate,
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
  ProjectChecklist,
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
type LeftRailCard = "review" | "projects" | "sheets" | "findings" | "inspector" | "checklist" | "export" | "advanced";
type PromptDepth = "fast" | "standard" | "comprehensive" | "exhaustive";
type LargePackageMode = "hybrid" | "package";
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

const PRIMARY_WORKFLOW_CARDS: LeftRailCard[] = ["projects", "sheets", "review", "findings", "inspector", "checklist", "export"];

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
  const [selectedPromptDepth, setSelectedPromptDepth] = useState<PromptDepth>("standard");
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
  const [savingFindingId, setSavingFindingId] = useState<string | null>(null);
  const [deletingFindingId, setDeletingFindingId] = useState<string | null>(null);
  const [deletingProjectId, setDeletingProjectId] = useState<string | null>(null);
  const [exportingPackage, setExportingPackage] = useState(false);
  const [importingPackage, setImportingPackage] = useState(false);
  const [rollingBackBatchId, setRollingBackBatchId] = useState<string | null>(null);
  const [mergingFindingId, setMergingFindingId] = useState<string | null>(null);
  const [activeMarkedPdfUrl, setActiveMarkedPdfUrl] = useState<string | null>(null);
  const [autoAdvanceReview, setAutoAdvanceReview] = useState(true);
  const [recalculatingPlacement, setRecalculatingPlacement] = useState(false);
  const [placementMessage, setPlacementMessage] = useState<string | null>(null);
  const [placementSummary, setPlacementSummary] = useState<PlacementSummary | null>(null);
  const [manualPlacementFindingId, setManualPlacementFindingId] = useState<string | null>(null);
  const [savingManualPlacement, setSavingManualPlacement] = useState(false);
  const [checklistTemplates, setChecklistTemplates] = useState<ChecklistTemplate[]>([]);
  const [projectChecklist, setProjectChecklist] = useState<ProjectChecklist | null>(null);
  const [loadingChecklist, setLoadingChecklist] = useState(false);
  const [savingChecklistItemId, setSavingChecklistItemId] = useState<string | null>(null);
  const [loadingMarkupMemory, setLoadingMarkupMemory] = useState(false);
  const [savingMarkupMemory, setSavingMarkupMemory] = useState(false);
  const [rebuildingMarkupMemory, setRebuildingMarkupMemory] = useState(false);
  const [clearingMarkupMemory, setClearingMarkupMemory] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [operation, setOperation] = useState<OperationProgress | null>(null);

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
    void refreshChecklistTemplates();
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
      setActiveMarkedPdfUrl(null);
      setPlacementMessage(null);
      setPlacementSummary(null);
      setManualPlacementFindingId(null);
      setProjectChecklist(null);
      setMarkupMemoryPreview(null);
      return;
    }

    setManualAIImportMessage(null);
    setManualAIPreview(null);
    setActiveMarkedPdfUrl(null);
    setPlacementMessage(null);
    setPlacementSummary(null);
    setManualPlacementFindingId(null);
    void refreshReview(selectedProjectId);
  }, [selectedProjectId]);

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

  async function refreshChecklistTemplates() {
    try {
      setChecklistTemplates(await listChecklistTemplates());
    } catch {
      setChecklistTemplates([]);
    }
  }

  async function refreshProjectChecklist(projectId = selectedProjectId) {
    if (!projectId) {
      setProjectChecklist(null);
      return;
    }
    setLoadingChecklist(true);
    try {
      setProjectChecklist(await getProjectChecklist(projectId));
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setLoadingChecklist(false);
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
      const nextProjects = await listProjects();
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
      const [project, nextSheets, nextFindings, nextEvents, nextBatches, nextChecklist, nextReviewPlan] = await Promise.all([
        getProject(projectId),
        listSheets(projectId),
        listFindings(projectId),
        listFindingEvents(projectId),
        listAIImportBatches(projectId),
        getProjectChecklist(projectId),
        getManualReviewPlan(projectId, largePackageBatchSize).catch(() => null),
      ]);

      setProjectDetails(project);
      setSheets(nextSheets);
      setFindings(nextFindings);
      setEvents(nextEvents);
      setAIImportBatches(nextBatches);
      setProjectChecklist(nextChecklist);
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
    startOperation("Create sample package", ["Creating sample", "Extracting sheets", "Refreshing workspace"]);

    try {
      advanceOperation(0, "Creating the local sample package.");
      const project = await createSampleProject();
      advanceOperation(2, "Sample package created. Refreshing the workspace.");
      setSelectedProjectId(project.id);
      await refreshProjects();
      await refreshReview(project.id);
      finishOperation("success", "Sample package is ready for the manual AI workflow.");
    } catch (requestError) {
      const message = getApiErrorMessage(requestError);
      setError(message);
      finishOperation("error", `Sample package failed. ${message}`);
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
      advanceOperation(1, "Building prompt context from extracted sheets, metadata, and checklist coverage.");
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
    setPreviewingManualAI(true);
    setError(null);
    setManualAIImportMessage(null);
    startOperation("Preview AI response", ["Parsing pasted response", "Checking reviewed_pages coverage", "Checking duplicates and placement"], "Parsing the pasted ChatGPT/Copilot response.");
    try {
      const preview = await previewManualAIResponse(
        selectedProjectId,
        manualAIResponse,
        manualAIPromptVersion,
        manualAIPromptId,
      );
      advanceOperation(1, "Checking reviewed_pages against the expected review scope.");
      setManualAIPreview(preview);
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
            )
          : null);
      if (!preview || preview.review_coverage_status !== "complete" || (preview.valid_recoverable_updates === 0 && !preview.scoped_review_complete)) {
        throw new Error("Preview AI Updates before importing. Every expected page must be confirmed complete in reviewed_pages.");
      }
      advanceOperation(1, "Writing valid AI updates and preserving raw response trace metadata.");
      const result = await importManualAIPreview(selectedProjectId, preview.batch_id);
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
      setManualAIImportMessage(
        importedCount === 0 && preview.review_coverage_status === "complete"
          ? "Recorded scoped review as complete with no AI updates."
          : `Imported ${importedCount} AI update${importedCount === 1 ? "" : "s"}${skippedCount ? ` (${skippedCount} skipped)` : ""}.`,
      );
      setManualAIResponse("");
      setManualAIPrompt(null);
      setManualAIPromptId(null);
      setManualAIPromptVersion(null);
      setManualAIPreview(null);
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

  async function handlePatchFinding(findingId: string, update: FindingUpdate) {
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
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setSavingFindingId(null);
    }
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

  async function handleSelectChecklist(checklistId: string) {
    if (!selectedProjectId || !checklistId) {
      return;
    }
    setLoadingChecklist(true);
    setError(null);
    try {
      setProjectChecklist(await selectProjectChecklist(selectedProjectId, checklistId));
      setManualAIImportMessage("Checklist selected. It will track coverage and linked findings only.");
      setEvents(await listFindingEvents(selectedProjectId));
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setLoadingChecklist(false);
    }
  }

  async function handleUpdateChecklistItem(item: ChecklistItem, update: ChecklistItemUpdate) {
    if (!selectedProjectId) {
      return;
    }
    setSavingChecklistItemId(item.id);
    setError(null);
    try {
      const updated = await updateProjectChecklistItem(selectedProjectId, item.id, update);
      setProjectChecklist((current) => {
        if (!current) {
          return current;
        }
        const items = current.items.map((candidate) => (candidate.id === updated.id ? updated : candidate));
        return { ...current, items, progress: computeChecklistProgress(items) };
      });
      setEvents(await listFindingEvents(selectedProjectId));
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setSavingChecklistItemId(null);
    }
  }

  function handleSelectFinding(finding: Finding) {
    setSelectedFindingId(finding.id);
    setLastSelectedFindingId(finding.id);
    setLeftRailCard("inspector");
    setLeftRailCollapsed(false);
    const sheet = getFindingSheet(finding, sheets);
    if (sheet) {
      setSelectedSheetId(sheet.id);
    }
  }

  function handleSelectPdfMarkup(finding: Finding) {
    setSelectedFindingId(finding.id);
    setLastSelectedFindingId(finding.id);
    setLeftRailCard("inspector");
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

      if (event.key === "a" && selectedFinding) {
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
  }, [selectedFinding, selectedFindingId, findings, reviewQueueFindings, selectedSheet, sheets, autoAdvanceReview]);

  const leftRailPanelTitle =
    leftRailCard === "projects"
      ? "Home"
      : leftRailCard === "sheets"
        ? "Sheets"
        : leftRailCard === "review"
          ? "Review"
        : leftRailCard === "findings"
          ? "Findings"
          : leftRailCard === "inspector"
            ? "Inspect"
            : leftRailCard === "checklist"
              ? "Checklist"
              : leftRailCard === "export"
                ? "Export"
                : "Advanced";
  const leftRailPanelSubtitle =
    leftRailCard === "projects"
      ? `${projects.length} projects`
      : leftRailCard === "sheets"
        ? `${sheets.length} sheets`
        : leftRailCard === "findings"
          ? `${findings.length} findings`
          : leftRailCard === "inspector"
            ? selectedFinding
              ? "Selected finding details"
              : "No finding selected"
            : leftRailCard === "checklist"
              ? "Coverage tracker"
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
            className={`nav-item ${leftRailCard === "sheets" && !leftRailCollapsed ? "active" : ""}`}
            type="button"
            role="tab"
            aria-selected={leftRailCard === "sheets" && !leftRailCollapsed}
            data-left-rail-card="sheets"
            title="Go to the sheet package index"
            aria-label="Sheets"
            onClick={() => openLeftRailCard("sheets")}
          >
            <FileText size={17} />
            <span>Sheets</span>
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
            className={`nav-item ${leftRailCard === "inspector" && !leftRailCollapsed ? "active" : ""}`}
            type="button"
            role="tab"
            aria-selected={leftRailCard === "inspector" && !leftRailCollapsed}
            data-left-rail-card="inspector"
            title="Open the selected finding inspector"
            aria-label="Inspector"
            onClick={() => openLeftRailCard("inspector")}
          >
            <ClipboardCheck size={17} />
            <span>Inspect</span>
          </button>
          <button
            className={`nav-item ${leftRailCard === "checklist" && !leftRailCollapsed ? "active" : ""}`}
            type="button"
            role="tab"
            aria-selected={leftRailCard === "checklist" && !leftRailCollapsed}
            data-left-rail-card="checklist"
            title="Open the checklist coverage tracker"
            aria-label="Checklist"
            onClick={() => openLeftRailCard("checklist")}
          >
            <ClipboardCheck size={17} />
            <span>Checklist</span>
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
                    className="ai-action"
                    type="button"
                    disabled={!selectedProjectId || runningAIReview}
                    title="Experimental direct AI review uses extracted text context only and is not equivalent to the PDF-attached Chat Prompt workflow"
                    onClick={() => void handleRunAIReview()}
                  >
                    <Sparkles size={14} className={runningAIReview ? "spin" : ""} />
                    {runningAIReview ? "AI reviewing" : "Direct AI (Text Only)"}
                  </button>
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
              <div className="inline-helper warning-helper">
                Direct AI Review is experimental and text-context-only. The manual Chat Prompt workflow with the actual PDF attached is the pilot review path.
              </div>

              <DashboardSummary
                project={selectedProject}
                findings={findings}
                batches={aiImportBatches}
                events={events}
                placementSummary={placementSummary ?? computePlacementSummary(findings)}
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

              {manualAIImportMessage ? (
                <div className="system-banner success-banner" role="status">
                  <Check size={16} />
                  <span>{manualAIImportMessage}</span>
                </div>
              ) : null}

              {manualAIPrompt !== null ? (
                <section className="manual-ai-panel manual-bridge-pro" aria-label="Manual ChatGPT or Copilot AI review bridge">
                  <div className="manual-ai-header">
                    <div>
                      <strong>Manual Bridge Pro</strong>
                      <span>AutoQC guides the no-API workflow: copy/open ChatGPT or Copilot, attach the same PDF, then paste or drop the JSON response for validation and import.</span>
                    </div>
                    <button
                      className="secondary-button"
                      type="button"
                      title="Close the manual AI bridge panel"
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

                  <div className="manual-bridge-checklist" aria-label="Manual bridge progress checklist">
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

              <AIImportHistory
                batches={aiImportBatches}
                rollingBackBatchId={rollingBackBatchId}
                onRollbackBatch={handleRollbackImportBatch}
              />
              <ReadinessPanel readiness={readiness} onRefresh={refreshReadiness} />
              <AuditLogPanel events={events} />
            </section>
          ) : null}

          {leftRailCard === "projects" ? (
            <ProjectsPanel
              projects={projects}
              selectedProjectId={selectedProjectId}
              loading={loadingProjects}
              uploading={uploading}
              creatingSample={creatingSample}
              deletingProjectId={deletingProjectId}
              exportingPackage={exportingPackage}
              importingPackage={importingPackage}
              onSelectProject={setSelectedProjectId}
              onRefresh={refreshProjects}
              onUpload={handleUpload}
              onSampleProject={handleSampleProject}
              onDeleteProject={handleDeleteProject}
              onExportPackage={handleExportProjectPackage}
              onImportPackage={handleImportProjectPackage}
            />
          ) : null}

          {leftRailCard === "sheets" ? (
            <SheetsPanel
              sheets={sheets}
              findings={findings}
              selectedSheetId={selectedSheetId}
              disabled={!selectedProject}
              onSelectSheet={handleSelectSheet}
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

          {leftRailCard === "inspector" ? (
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

          {leftRailCard === "checklist" ? (
            <ChecklistPanel
              project={selectedProject}
              templates={checklistTemplates}
              checklist={projectChecklist}
              findings={findings}
              loading={loadingChecklist}
              savingItemId={savingChecklistItemId}
              onRefresh={refreshProjectChecklist}
              onSelectChecklist={handleSelectChecklist}
              onUpdateItem={handleUpdateChecklistItem}
              onSelectFinding={handleSelectFinding}
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
              settings={markupMemorySettings}
              stats={markupMemoryStats}
              preview={markupMemoryPreview}
              loading={loadingMarkupMemory}
              saving={savingMarkupMemory}
              rebuilding={rebuildingMarkupMemory}
              clearing={clearingMarkupMemory}
              onRefresh={refreshMarkupMemory}
              onUpdateSettings={handleUpdateMarkupMemorySettings}
              onRebuild={handleRebuildMarkupMemory}
              onClear={handleClearMarkupMemory}
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
            onSelectFinding={handleSelectPdfMarkup}
            onSaveManualPlacement={handleSaveManualPlacement}
            onStepSheet={handleStepSheet}
            onDeepDiveSheet={handleDeepDiveSheet}
          />
        </section>
      </main>

    </div>
  );
}

interface ProjectsPanelProps {
  projects: Project[];
  selectedProjectId: string | null;
  loading: boolean;
  uploading: boolean;
  creatingSample: boolean;
  deletingProjectId: string | null;
  exportingPackage: boolean;
  importingPackage: boolean;
  onSelectProject: (projectId: string) => void;
  onRefresh: () => Promise<void>;
  onUpload: (name: string, file: File) => Promise<void>;
  onSampleProject: () => Promise<void>;
  onDeleteProject: (project: Project) => Promise<void>;
  onExportPackage: () => Promise<void>;
  onImportPackage: (file: File | null) => Promise<void>;
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
      <div className="section-inline-header">
        <div>
          <strong>What should I do next?</strong>
          <span>{nextStep ? nextStep.detail : "Workflow is ready for final review records."}</span>
        </div>
        {nextStep?.onAction && nextStep.actionLabel ? (
          <button className="secondary-button compact-action" type="button" onClick={nextStep.onAction}>
            <ChevronRight size={14} />
            {nextStep.actionLabel}
          </button>
        ) : null}
      </div>
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
  const finalExported = events.some((event) => event.action === "final_export_created");
  const coverage = project?.review_coverage ?? latestImportCoverage(importedBatch);
  const coverageComplete = coverage?.review_coverage_status === "complete";
  const needsReview = countFindingsByStatus(findings, "needs_review");
  const accepted = countFindingsByStatus(findings, "accepted");
  const manualPlacement = manualPlacementBlockerCount(findings);

  return [
    {
      label: "Upload PDF",
      status: project && sheets.length ? "done" : "ready",
      detail: project && sheets.length ? `${sheets.length} sheets extracted.` : "Upload a PDF drawing package or create the sample package.",
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
  const latestFinalBlock = events.find((event) => event.action === "final_export_blocked");
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
      nextAction: "Open the export checklist and resolve the blocked item before trying again.",
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
  settings: MarkupMemorySettings | null;
  stats: MarkupMemoryStats | null;
  preview: MarkupMemoryPreview | null;
  loading: boolean;
  saving: boolean;
  rebuilding: boolean;
  clearing: boolean;
  onRefresh: () => Promise<void>;
  onUpdateSettings: (update: MarkupMemorySettingsUpdate) => Promise<void>;
  onRebuild: () => Promise<void>;
  onClear: () => Promise<void>;
}

function AdvancedFeaturesPanel({
  project,
  settings,
  stats,
  preview,
  loading,
  saving,
  rebuilding,
  clearing,
  onRefresh,
  onUpdateSettings,
  onRebuild,
  onClear,
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
          <li>Upload PDF or create the sample project.</li>
          <li>Generate Chat Prompt.</li>
          <li>Attach the same PDF in ChatGPT or Copilot.</li>
          <li>Paste the returned JSON into AutoQC.</li>
          <li>Preview/import valid updates.</li>
          <li>Review, accept, reject, edit, merge, or defer findings.</li>
          <li>Recalculate placement if needed.</li>
          <li>Export the marked PDF and review package.</li>
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
  creatingSample,
  deletingProjectId,
  exportingPackage,
  importingPackage,
  onSelectProject,
  onRefresh,
  onUpload,
  onSampleProject,
  onDeleteProject,
  onExportPackage,
  onImportPackage,
}: ProjectsPanelProps) {
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);

  function validatePdf(candidate: File | null): string | null {
    if (!candidate) {
      return "Select a PDF drawing package before uploading.";
    }

    const looksLikePdf = candidate.type === "application/pdf" || candidate.name.toLowerCase().endsWith(".pdf");
    return looksLikePdf ? null : "AutoQC only accepts PDF drawing packages. Choose a .pdf file.";
  }

  function handleFileChange(candidate: File | null) {
    setFile(candidate);
    setUploadError(candidate ? validatePdf(candidate) : null);
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (uploading) {
      return;
    }

    const validationMessage = validatePdf(file);
    if (validationMessage || !file) {
      setUploadError(validationMessage);
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
            <strong>Upload / sample package</strong>
            <small>{selectedProjectId ? "Collapsed after a project is selected" : "Start a new review"}</small>
          </span>
        </summary>
        <form className="upload-form" onSubmit={handleSubmit}>
          <label className="field-label" title="Optional. If left blank, the PDF filename will be used as the project name.">
            Project name
            <input
              type="text"
              value={name}
              onChange={(event) => setName(event.target.value)}
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

          {file && !uploadError ? (
            <div className="inline-helper" role="status">Ready to upload: {file.name}</div>
          ) : null}

          {uploadError ? (
            <div className="inline-error compact-error" role="alert">{uploadError}</div>
          ) : null}

          <div className="button-row">
            <button
              className="primary-button"
              type="submit"
              disabled={!file || Boolean(uploadError) || uploading}
              title={uploadError ? uploadError : file ? "Upload this PDF and extract sheets, page images, and prompt context" : "Select a PDF before uploading"}
            >
              {uploading ? <Loader2 size={17} className="spin" /> : <Upload size={17} />}
              Upload
            </button>
            <button
              className="secondary-button"
              type="button"
              onClick={() => void onSampleProject()}
              disabled={creatingSample}
              title="Create the built-in synthetic sample drawing package and extract sheet context"
            >
              {creatingSample ? <Loader2 size={17} className="spin" /> : <FolderOpen size={17} />}
              Sample Package
            </button>
          </div>
        </form>
      </details>

      <details className="collapsible-section package-collapsible">
        <summary>
          <span>
            <strong>Backup / restore</strong>
            <small>Portable AutoQC project packages</small>
          </span>
        </summary>
        <div className="package-tools">
          <button
            className="secondary-button"
            type="button"
            disabled={!selectedProjectId || exportingPackage}
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
      </details>

      <div className="project-list" aria-label="Project list">
        {projects.length === 0 ? (
          <div className="empty-state compact">
            <FileText size={18} />
            <strong>No projects yet</strong>
            <small>Upload a PDF drawing set or create the sample package to start the AutoQC workflow.</small>
          </div>
        ) : (
          projects.map((project) => {
            const isDeleting = deletingProjectId === project.id;

            return (
              <div
                className={`project-item ${project.id === selectedProjectId ? "selected" : ""}`}
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

interface SheetsPanelProps {
  sheets: Sheet[];
  findings: Finding[];
  selectedSheetId: string | null;
  disabled: boolean;
  onSelectSheet: (sheetId: string) => void;
}

function SheetsPanel({
  sheets,
  findings,
  selectedSheetId,
  disabled,
  onSelectSheet,
}: SheetsPanelProps) {
  return (
    <section className="panel sheets-panel" id="sheet-index" aria-label="Sheet package index">
      <div className="panel-header">
        <div>
          <span className="eyebrow">Sheets</span>
          <h2>Package Index</h2>
        </div>
        <span className="count-pill">{sheets.length}</span>
      </div>

      {disabled ? (
        <div className="empty-state compact">
          <FileText size={18} />
          <strong>No project selected</strong>
          <small>Select or upload a drawing review before browsing sheets.</small>
        </div>
      ) : sheets.length === 0 ? (
        <div className="empty-state compact">
          <FileText size={18} />
          <strong>No sheets returned</strong>
          <small>The backend did not extract sheet pages for this project. Try refreshing or re-uploading the PDF.</small>
        </div>
      ) : (
        <div className="sheet-list" aria-label="Sheet list">
          {sheets.map((sheet) => {
            const count = findings.filter((finding) => findingMatchesSheet(finding, sheet)).length;

            return (
              <button
                className={`sheet-item ${sheet.id === selectedSheetId ? "selected" : ""}`}
                type="button"
                key={sheet.id}
                onClick={() => onSelectSheet(sheet.id)}
                title={`Preview ${sheet.drawing_number || `Sheet ${sheet.page_number}`} and show its related findings`}
              >
                <span className="sheet-page">P{sheet.page_number}</span>
                <span className="sheet-main">
                  <strong>{sheet.drawing_number || `Sheet ${sheet.page_number}`}</strong>
                  <span>{sheet.sheet_title || "Untitled sheet"}</span>
                </span>
                <span className="sheet-tags">
                  <span className="type-chip">{sheet.sheet_type || "unknown"}</span>
                  {count > 0 ? <span className="finding-count">{count}</span> : null}
                </span>
              </button>
            );
          })}
        </div>
      )}
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
  onSelectFinding: (finding: Finding) => void;
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
  onSelectFinding,
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
          <div className="viewer-mode-toggle" role="tablist" aria-label="Viewer mode">
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
          <div className="zoom-controls" aria-label="Drawing zoom controls">
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
      </div>

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
            <small>Choose a review from Projects, upload a PDF, or create the sample package to begin.</small>
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
            className="drawing-pan-viewport"
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
  const qualityCounts = {
    exact: findings.filter((finding) => findingPlacementStatus(finding) === "exact_target_found").length,
    fuzzy: findings.filter((finding) => findingPlacementStatus(finding) === "fuzzy_target_found").length,
    page: findings.filter((finding) => findingPlacementStatus(finding) === "page_level_fallback").length,
    manual: findings.filter((finding) => findingPlacementStatus(finding) === "manual_placement_needed").length,
    lowConfidence: findings.filter((finding) => finding.confidence < 0.6).length,
    accepted: countFindingsByStatus(findings, "accepted"),
    needsReview: countFindingsByStatus(findings, "needs_review"),
    rejected: countFindingsByStatus(findings, "rejected"),
    duplicate: countFindingsByStatus(findings, "duplicate"),
  };

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
        {STATUSES.map((status) => (
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

      <div className="finding-quality-dashboard" aria-label="Finding Quality and Placement dashboard">
        <button type="button" onClick={() => setPlacementFilter("exact")}>Exact placed findings <strong>{qualityCounts.exact}</strong></button>
        <button type="button" onClick={() => setPlacementFilter("fuzzy")}>Fuzzy placed findings <strong>{qualityCounts.fuzzy}</strong></button>
        <button type="button" onClick={() => setPlacementFilter("page_level")}>Page-level findings <strong>{qualityCounts.page}</strong></button>
        <button type="button" onClick={() => setPlacementFilter("manual")}>Manual placement needed <strong>{qualityCounts.manual}</strong></button>
        <button type="button" onClick={() => setPlacementFilter("low_confidence")}>Low confidence findings <strong>{qualityCounts.lowConfidence}</strong></button>
        <button type="button" onClick={() => setStatusFilter("accepted")}>Accepted <strong>{qualityCounts.accepted}</strong></button>
        <button type="button" onClick={() => setStatusFilter("needs_review")}>Needs review <strong>{qualityCounts.needsReview}</strong></button>
        <button type="button" onClick={() => setStatusFilter("duplicate")}>Duplicate/merged <strong>{qualityCounts.duplicate}</strong></button>
      </div>

      <div className="shortcut-hints" aria-label="Reviewer keyboard shortcuts">
        <span><kbd>A</kbd> Accept</span>
        <span><kbd>X</kbd> Reject</span>
        <span><kbd>R</kbd> Review</span>
        <span><kbd>J/K</kbd> Finding</span>
        <span><kbd>[ ]</kbd> Sheet</span>
      </div>

      <div className="finding-tools">
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
          {(["all", ...STATUSES] as StatusFilter[]).map((status) => (
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
            {STATUSES.map((status) => (
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

interface ChecklistPanelProps {
  project: Project | null;
  templates: ChecklistTemplate[];
  checklist: ProjectChecklist | null;
  findings: Finding[];
  loading: boolean;
  savingItemId: string | null;
  onRefresh: () => Promise<void>;
  onSelectChecklist: (checklistId: string) => Promise<void>;
  onUpdateItem: (item: ChecklistItem, update: ChecklistItemUpdate) => Promise<void>;
  onSelectFinding: (finding: Finding) => void;
}

function ChecklistPanel({
  project,
  templates,
  checklist,
  findings,
  loading,
  savingItemId,
  onRefresh,
  onSelectChecklist,
  onUpdateItem,
  onSelectFinding,
}: ChecklistPanelProps) {
  const [sectionFilter, setSectionFilter] = useState("All");
  const sections = ["All", ...Array.from(new Set((checklist?.items ?? []).map((item) => item.section)))];
  const visibleItems = (checklist?.items ?? []).filter((item) => sectionFilter === "All" || item.section === sectionFilter);
  const progress = checklist?.progress ?? computeChecklistProgress(checklist?.items ?? []);

  return (
    <section className="panel checklist-panel" aria-label="Checklist tracker">
      <div className="panel-header">
        <div>
          <span className="eyebrow">Checklist</span>
          <h2>Coverage Tracker</h2>
        </div>
        <button className="icon-button" type="button" onClick={() => void onRefresh()} title="Refresh checklist">
          <RefreshCw size={16} className={loading ? "spin" : ""} />
        </button>
      </div>

      <div className="checklist-body">
        <div className="inline-helper">
          Checklist items track review coverage and link evidence/findings. They do not create drawing findings by themselves.
        </div>

        {!project ? (
          <div className="empty-state compact">
            <FolderOpen size={18} />
            <strong>No project selected</strong>
            <small>Select a drawing package before choosing a checklist.</small>
          </div>
        ) : !checklist?.items?.length ? (
          <div className="checklist-select-card">
            <label className="field-label">
              Select checklist for project
              <select
                defaultValue=""
                disabled={loading || templates.length === 0}
                onChange={(event) => {
                  if (event.target.value) {
                    void onSelectChecklist(event.target.value);
                  }
                }}
              >
                <option value="">Choose checklist</option>
                {templates.map((template) => (
                  <option key={template.id} value={template.id}>
                    {template.name} {template.version}
                  </option>
                ))}
              </select>
            </label>
            <small>{templates[0]?.description ?? "Checklist templates are stored locally."}</small>
          </div>
        ) : (
          <>
            <div className="checklist-progress" role="status">
              <strong>{progress.percent_complete}% complete</strong>
              <span>{progress.completed_items}/{progress.total_items} checked | {progress.issue_items} issue items | {progress.linked_items} linked</span>
              <progress value={progress.completed_items} max={Math.max(progress.total_items, 1)} />
            </div>

            <div className="segmented-control checklist-sections" aria-label="Checklist section filter">
              {sections.map((section) => (
                <button
                  type="button"
                  key={section}
                  className={sectionFilter === section ? "active" : ""}
                  onClick={() => setSectionFilter(section)}
                  title={`Show ${section} checklist items`}
                >
                  {section}
                </button>
              ))}
            </div>

            <div className="checklist-item-list">
              {visibleItems.map((item) => (
                <ChecklistItemRow
                  key={item.id}
                  item={item}
                  findings={findings}
                  saving={savingItemId === item.id}
                  onUpdate={onUpdateItem}
                  onSelectFinding={onSelectFinding}
                />
              ))}
            </div>
          </>
        )}
      </div>
    </section>
  );
}

function ChecklistItemRow({
  item,
  findings,
  saving,
  onUpdate,
  onSelectFinding,
}: {
  item: ChecklistItem;
  findings: Finding[];
  saving: boolean;
  onUpdate: (item: ChecklistItem, update: ChecklistItemUpdate) => Promise<void>;
  onSelectFinding: (finding: Finding) => void;
}) {
  const linkedFindings = findings.filter((finding) => item.mapped_finding_ids.includes(finding.id));
  return (
    <div className="checklist-item-row">
      <div className="checklist-item-main">
        <span className={`status-chip status-${statusClass(item.status)}`}>{checklistStatusLabel(item.status)}</span>
        <strong>{item.item_text}</strong>
        <small>{item.section} | {item.sheet_type || "all sheets"} | {item.source_template_reference || "local checklist"}</small>
      </div>
      <label className="field-label">
        Status
        <select
          value={item.status}
          disabled={saving}
          onChange={(event) => void onUpdate(item, { status: event.target.value as ChecklistStatus })}
        >
          <option value="not_started">Not started</option>
          <option value="checked">Checked</option>
          <option value="issue_found">Issue found</option>
          <option value="not_applicable">Not applicable</option>
          <option value="needs_human_review">Needs human review</option>
        </select>
      </label>
      <label className="field-label">
        Link existing finding
        <select
          value=""
          disabled={saving || findings.length === 0}
          onChange={(event) => {
            const findingId = event.target.value;
            if (findingId && !item.mapped_finding_ids.includes(findingId)) {
              void onUpdate(item, { mapped_finding_ids: [...item.mapped_finding_ids, findingId] });
            }
          }}
        >
          <option value="">Choose finding</option>
          {findings.map((finding) => (
            <option key={finding.id} value={finding.id}>
              {finding.title}
            </option>
          ))}
        </select>
      </label>
      {linkedFindings.length ? (
        <div className="linked-finding-list">
          {linkedFindings.map((finding) => (
            <button type="button" key={finding.id} onClick={() => onSelectFinding(finding)}>
              {finding.title}
            </button>
          ))}
        </div>
      ) : null}
      <label className="field-label">
        Reviewer notes
        <textarea
          rows={2}
          defaultValue={item.reviewer_notes ?? ""}
          onBlur={(event) => {
            if (event.currentTarget.value !== (item.reviewer_notes ?? "")) {
              void onUpdate(item, { reviewer_notes: event.currentTarget.value });
            }
          }}
        />
      </label>
    </div>
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
      title: exportMode === "final" ? "Create Final Export" : "Create Draft Export",
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
  const finalBlockerText = finalExportBlockerSummary(reviewCoverage, effectiveFindingCount, finalManualPlacementCount);
  const finalReady = exportMode !== "final" || (finalCoverageReady && finalManualPlacementCount === 0 && finalConfirmed);
  const exportDisabled = !project || effectiveStatuses.length === 0 || effectiveFindingCount === 0 || exporting || !finalReady;
  const exportTitle = !project
    ? "Select a project before exporting"
    : effectiveStatuses.length === 0
      ? "Choose at least one finding status to export"
      : effectiveFindingCount === 0
        ? "No findings match the selected export statuses"
        : exportMode === "final" && !finalReady
          ? "Complete the final export readiness checklist first"
        : "Generate marked PDF, logs, and summaries for the selected finding statuses";

  return (
    <section className="panel export-panel">
      <div className="panel-header">
        <div>
          <span className="eyebrow">Export</span>
          <h2>Review Package</h2>
        </div>
        <Download size={18} />
      </div>

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
        <div className="final-readiness-checklist" aria-label="Final export readiness checklist">
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
            <input value={reviewerName} onChange={(event) => setReviewerName(event.target.value)} placeholder="Local reviewer" />
          </label>
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
        {exportMode === "final" ? "Create Final Export" : "Create Draft Export"}
      </button>

      {error ? <div className="inline-error" role="alert">{error}</div> : null}

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

      {result?.marked_pdf ? (
        <a
          className="download-pdf-button"
          href={resolveAssetUrl(result.marked_pdf) ?? result.marked_pdf}
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

function computeChecklistProgress(items: ChecklistItem[]) {
  const by_status: Record<string, number> = {};
  for (const item of items) {
    by_status[item.status] = (by_status[item.status] ?? 0) + 1;
  }
  const completed_items = (by_status.checked ?? 0) + (by_status.issue_found ?? 0) + (by_status.not_applicable ?? 0);
  return {
    total_items: items.length,
    completed_items,
    issue_items: by_status.issue_found ?? 0,
    linked_items: items.filter((item) => item.mapped_finding_ids.length > 0).length,
    percent_complete: items.length ? Math.round((completed_items / items.length) * 1000) / 10 : 0,
    by_status,
  };
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

function checklistStatusLabel(status: ChecklistStatus): string {
  return {
    not_started: "Not started",
    checked: "Checked",
    issue_found: "Issue found",
    not_applicable: "Not applicable",
    needs_human_review: "Needs human review",
  }[status];
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
        return `${key}: ${String(typed.from ?? "")} -> ${String(typed.to ?? "")}`;
      }
      if (Array.isArray(value)) {
        return `${key}: ${value.length} item${value.length === 1 ? "" : "s"}`;
      }
      if (typeof value === "object" && value) {
        return `${key}: ${JSON.stringify(value)}`;
      }
      return `${key}: ${String(value ?? "")}`;
    });
  return parts.join(" | ");
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
