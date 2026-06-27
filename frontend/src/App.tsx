import { useEffect, useMemo, useState } from "react";
import type { CSSProperties, FormEvent } from "react";
import {
  AlertTriangle,
  Check,
  ChevronLeft,
  ChevronRight,
  ClipboardCheck,
  Download,
  FileText,
  FolderOpen,
  Loader2,
  RefreshCw,
  Save,
  Search,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import {
  API_BASE_URL,
  createProject,
  createSampleProject,
  deleteFinding,
  exportProject,
  getApiErrorMessage,
  getProject,
  listFindings,
  listProjects,
  listSheets,
  resolveAssetUrl,
  updateFinding,
} from "./api";
import type {
  ExportResponse,
  Finding,
  FindingStatus,
  FindingUpdate,
  Project,
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

interface ImageSize {
  width: number;
  height: number;
}

function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [projectDetails, setProjectDetails] = useState<Project | null>(null);
  const [sheets, setSheets] = useState<Sheet[]>([]);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [selectedSheetId, setSelectedSheetId] = useState<string | null>(null);
  const [selectedFindingId, setSelectedFindingId] = useState<string | null>(null);
  const [loadingProjects, setLoadingProjects] = useState(false);
  const [loadingReview, setLoadingReview] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [creatingSample, setCreatingSample] = useState(false);
  const [savingFindingId, setSavingFindingId] = useState<string | null>(null);
  const [deletingFindingId, setDeletingFindingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selectedProject =
    projectDetails ?? projects.find((project) => project.id === selectedProjectId) ?? null;
  const selectedSheet = sheets.find((sheet) => sheet.id === selectedSheetId) ?? null;
  const selectedFinding =
    findings.find((finding) => finding.id === selectedFindingId) ?? null;

  const findingsForSelectedSheet = useMemo(() => {
    if (!selectedSheet) {
      return [];
    }

    return findings.filter((finding) => findingMatchesSheet(finding, selectedSheet));
  }, [findings, selectedSheet]);

  useEffect(() => {
    void refreshProjects();
  }, []);

  useEffect(() => {
    if (!selectedProjectId) {
      setProjectDetails(null);
      setSheets([]);
      setFindings([]);
      setSelectedSheetId(null);
      setSelectedFindingId(null);
      return;
    }

    void refreshReview(selectedProjectId);
  }, [selectedProjectId]);

  useEffect(() => {
    if (!selectedFinding) {
      return;
    }

    const sheet = getFindingSheet(selectedFinding, sheets);
    if (sheet && sheet.id !== selectedSheetId) {
      setSelectedSheetId(sheet.id);
    }
  }, [selectedFinding, selectedSheetId, sheets]);

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
      const [project, nextSheets, nextFindings] = await Promise.all([
        getProject(projectId),
        listSheets(projectId),
        listFindings(projectId),
      ]);

      setProjectDetails(project);
      setSheets(nextSheets);
      setFindings(nextFindings);
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

    try {
      const project = await createProject(name, file);
      setSelectedProjectId(project.id);
      await refreshProjects();
      await refreshReview(project.id);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setUploading(false);
    }
  }

  async function handleSampleProject() {
    setCreatingSample(true);
    setError(null);

    try {
      const project = await createSampleProject();
      setSelectedProjectId(project.id);
      await refreshProjects();
      await refreshReview(project.id);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setCreatingSample(false);
    }
  }

  async function handlePatchFinding(findingId: string, update: FindingUpdate) {
    setSavingFindingId(findingId);
    setError(null);

    try {
      const updated = await updateFinding(findingId, update);
      setFindings((current) =>
        current.map((finding) => (finding.id === updated.id ? updated : finding)),
      );
      setSelectedFindingId(updated.id);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setSavingFindingId(null);
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
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setDeletingFindingId(null);
    }
  }

  function handleSelectFinding(finding: Finding) {
    setSelectedFindingId(finding.id);
    const sheet = getFindingSheet(finding, sheets);
    if (sheet) {
      setSelectedSheetId(sheet.id);
    }
  }

  function handleStepSheet(delta: number) {
    if (!selectedSheet) {
      return;
    }

    const index = sheets.findIndex((sheet) => sheet.id === selectedSheet.id);
    const next = sheets[index + delta];
    if (next) {
      setSelectedSheetId(next.id);
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">
            <ClipboardCheck size={22} />
          </div>
          <div>
            <strong>AutoQC</strong>
            <span>Natural Gas Engineering Copilot</span>
          </div>
        </div>

        <div className="topbar-actions">
          <span className="api-chip">{API_BASE_URL}</span>
          <button
            className="icon-button"
            type="button"
            onClick={() => {
              void refreshProjects();
              void refreshReview();
            }}
            title="Refresh"
            aria-label="Refresh"
          >
            <RefreshCw size={18} className={loadingProjects || loadingReview ? "spin" : ""} />
          </button>
        </div>
      </header>

      {error ? (
        <div className="system-banner" role="alert">
          <AlertTriangle size={18} />
          <span>{error}</span>
        </div>
      ) : null}

      <main className="workspace">
        <aside className="left-rail">
          <ProjectsPanel
            projects={projects}
            selectedProjectId={selectedProjectId}
            loading={loadingProjects}
            uploading={uploading}
            creatingSample={creatingSample}
            onSelectProject={setSelectedProjectId}
            onRefresh={refreshProjects}
            onUpload={handleUpload}
            onSampleProject={handleSampleProject}
          />

          <SheetsPanel
            sheets={sheets}
            findings={findings}
            selectedSheetId={selectedSheetId}
            disabled={!selectedProject}
            onSelectSheet={setSelectedSheetId}
          />
        </aside>

        <section className="viewer-pane">
          <Viewer
            project={selectedProject}
            sheet={selectedSheet}
            sheets={sheets}
            findings={findingsForSelectedSheet}
            selectedFinding={selectedFinding}
            loading={loadingReview}
            onSelectFinding={handleSelectFinding}
            onStepSheet={handleStepSheet}
          />
        </section>

        <aside className="right-rail">
          <FindingsPanel
            findings={findings}
            sheets={sheets}
            selectedFinding={selectedFinding}
            selectedProject={selectedProject}
            savingFindingId={savingFindingId}
            deletingFindingId={deletingFindingId}
            onSelectFinding={handleSelectFinding}
            onPatchFinding={handlePatchFinding}
            onDeleteFinding={handleDeleteFinding}
          />

          <ExportPanel project={selectedProject} findings={findings} />
        </aside>
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
  onSelectProject: (projectId: string) => void;
  onRefresh: () => Promise<void>;
  onUpload: (name: string, file: File) => Promise<void>;
  onSampleProject: () => Promise<void>;
}

function ProjectsPanel({
  projects,
  selectedProjectId,
  loading,
  uploading,
  creatingSample,
  onSelectProject,
  onRefresh,
  onUpload,
  onSampleProject,
}: ProjectsPanelProps) {
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file || uploading) {
      return;
    }

    const fallbackName = file.name.replace(/\.pdf$/i, "");
    void onUpload(name.trim() || fallbackName, file);
  }

  return (
    <section className="panel projects-panel">
      <div className="panel-header">
        <div>
          <span className="eyebrow">Projects</span>
          <h2>Drawing Reviews</h2>
        </div>
        <button
          className="icon-button"
          type="button"
          onClick={() => void onRefresh()}
          title="Refresh projects"
          aria-label="Refresh projects"
        >
          <RefreshCw size={17} className={loading ? "spin" : ""} />
        </button>
      </div>

      <form className="upload-form" onSubmit={handleSubmit}>
        <label className="field-label">
          Project name
          <input
            type="text"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Regulator station package"
          />
        </label>

        <label className="field-label">
          PDF drawing set
          <input
            type="file"
            accept="application/pdf,.pdf"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </label>

        <div className="button-row">
          <button className="primary-button" type="submit" disabled={!file || uploading}>
            {uploading ? <Loader2 size={17} className="spin" /> : <Upload size={17} />}
            Upload
          </button>
          <button
            className="secondary-button"
            type="button"
            onClick={() => void onSampleProject()}
            disabled={creatingSample}
          >
            {creatingSample ? <Loader2 size={17} className="spin" /> : <FolderOpen size={17} />}
            Sample
          </button>
        </div>
      </form>

      <div className="project-list" aria-label="Project list">
        {projects.length === 0 ? (
          <div className="empty-state compact">
            <FileText size={18} />
            <span>No projects found</span>
          </div>
        ) : (
          projects.map((project) => (
            <button
              className={`project-item ${project.id === selectedProjectId ? "selected" : ""}`}
              type="button"
              key={project.id}
              onClick={() => onSelectProject(project.id)}
            >
              <span className="project-name">{project.name}</span>
              <span className="project-meta">
                {formatStatus(project.status)}
                <span>{project.sheet_count ?? 0} sheets</span>
                <span>{project.finding_count ?? project.findings_count ?? 0} findings</span>
              </span>
              <span className="project-date">{formatDate(project.updated_at)}</span>
            </button>
          ))
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
    <section className="panel sheets-panel">
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
          <span>No project selected</span>
        </div>
      ) : sheets.length === 0 ? (
        <div className="empty-state compact">
          <FileText size={18} />
          <span>No sheets returned</span>
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
  loading: boolean;
  onSelectFinding: (finding: Finding) => void;
  onStepSheet: (delta: number) => void;
}

function Viewer({
  project,
  sheet,
  sheets,
  findings,
  selectedFinding,
  loading,
  onSelectFinding,
  onStepSheet,
}: ViewerProps) {
  const [imageSize, setImageSize] = useState<ImageSize | null>(null);
  const [imageFailed, setImageFailed] = useState(false);
  const imageUrl = resolveAssetUrl(sheet?.image_url ?? sheet?.image_path);
  const sheetIndex = sheet ? sheets.findIndex((item) => item.id === sheet.id) : -1;
  const canGoPrev = sheetIndex > 0;
  const canGoNext = sheetIndex >= 0 && sheetIndex < sheets.length - 1;

  useEffect(() => {
    setImageSize(null);
    setImageFailed(false);
  }, [sheet?.id, imageUrl]);

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
          <button
            className="icon-button"
            type="button"
            onClick={() => onStepSheet(-1)}
            disabled={!canGoPrev}
            title="Previous sheet"
            aria-label="Previous sheet"
          >
            <ChevronLeft size={18} />
          </button>
          <button
            className="icon-button"
            type="button"
            onClick={() => onStepSheet(1)}
            disabled={!canGoNext}
            title="Next sheet"
            aria-label="Next sheet"
          >
            <ChevronRight size={18} />
          </button>
        </div>
      </div>

      <div className="drawing-surface">
        {loading ? (
          <div className="empty-state">
            <Loader2 size={24} className="spin" />
            <span>Loading review data</span>
          </div>
        ) : !project ? (
          <div className="empty-state">
            <FolderOpen size={26} />
            <span>No project selected</span>
          </div>
        ) : !sheet ? (
          <div className="empty-state">
            <FileText size={26} />
            <span>No sheets available</span>
          </div>
        ) : imageUrl && !imageFailed ? (
          <div className="drawing-stage">
            <img
              src={imageUrl}
              alt={sheetLabel(sheet)}
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
                  onClick={() => onSelectFinding(finding)}
                />
              );
            })}
          </div>
        ) : (
          <div className="drawing-placeholder">
            <FileText size={32} />
            <strong>{sheetLabel(sheet)}</strong>
            <span>No drawing image available</span>
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
  selectedProject: Project | null;
  savingFindingId: string | null;
  deletingFindingId: string | null;
  onSelectFinding: (finding: Finding) => void;
  onPatchFinding: (findingId: string, update: FindingUpdate) => Promise<void>;
  onDeleteFinding: (finding: Finding) => Promise<void>;
}

function FindingsPanel({
  findings,
  sheets,
  selectedFinding,
  selectedProject,
  savingFindingId,
  deletingFindingId,
  onSelectFinding,
  onPatchFinding,
  onDeleteFinding,
}: FindingsPanelProps) {
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [query, setQuery] = useState("");

  const filteredFindings = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return findings.filter((finding) => {
      const matchesStatus = statusFilter === "all" || finding.status === statusFilter;
      if (!matchesStatus) {
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
  }, [findings, query, statusFilter]);

  return (
    <section className="panel findings-panel">
      <div className="panel-header">
        <div>
          <span className="eyebrow">Findings</span>
          <h2>QC Log</h2>
        </div>
        <span className="count-pill">{findings.length}</span>
      </div>

      <div className="status-summary">
        <StatusCounter label="Review" value={countFindingsByStatus(findings, "needs_review")} />
        <StatusCounter label="Accepted" value={countFindingsByStatus(findings, "accepted")} />
        <StatusCounter label="Rejected" value={countFindingsByStatus(findings, "rejected")} />
      </div>

      <div className="finding-tools">
        <div className="search-field">
          <Search size={16} />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search findings"
          />
        </div>

        <div className="segmented-control" aria-label="Finding status filter">
          {(["all", ...STATUSES] as StatusFilter[]).map((status) => (
            <button
              type="button"
              key={status}
              className={statusFilter === status ? "active" : ""}
              onClick={() => setStatusFilter(status)}
            >
              {status === "all" ? "All" : formatStatus(status)}
            </button>
          ))}
        </div>
      </div>

      <div className="finding-list" aria-label="Finding list">
        {!selectedProject ? (
          <div className="empty-state compact">
            <FolderOpen size={18} />
            <span>No project selected</span>
          </div>
        ) : filteredFindings.length === 0 ? (
          <div className="empty-state compact">
            <ClipboardCheck size={18} />
            <span>No findings match</span>
          </div>
        ) : (
          filteredFindings.map((finding) => {
            const sheet = getFindingSheet(finding, sheets);
            return (
              <button
                key={finding.id}
                type="button"
                className={`finding-item ${finding.id === selectedFinding?.id ? "selected" : ""}`}
                onClick={() => onSelectFinding(finding)}
              >
                <span className={`severity-dot severity-${severityClass(finding.severity)}`} />
                <span className="finding-item-main">
                  <strong>{finding.title}</strong>
                  <span>
                    {sheet ? `P${sheet.page_number}` : "Project"} | {finding.category}
                  </span>
                </span>
                <span className={`status-chip status-${statusClass(finding.status)}`}>
                  {formatStatus(finding.status)}
                </span>
              </button>
            );
          })
        )}
      </div>

      <FindingInspector
        finding={selectedFinding}
        sheet={selectedFinding ? getFindingSheet(selectedFinding, sheets) : undefined}
        saving={selectedFinding ? savingFindingId === selectedFinding.id : false}
        deleting={selectedFinding ? deletingFindingId === selectedFinding.id : false}
        onPatchFinding={onPatchFinding}
        onDeleteFinding={onDeleteFinding}
      />
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

interface FindingInspectorProps {
  finding: Finding | null;
  sheet?: Sheet;
  saving: boolean;
  deleting: boolean;
  onPatchFinding: (findingId: string, update: FindingUpdate) => Promise<void>;
  onDeleteFinding: (finding: Finding) => Promise<void>;
}

function FindingInspector({
  finding,
  sheet,
  saving,
  deleting,
  onPatchFinding,
  onDeleteFinding,
}: FindingInspectorProps) {
  const [draft, setDraft] = useState({
    title: "",
    category: CATEGORIES[0],
    severity: "Major" as Severity,
    confidence: 0.75,
    comment_text: "",
    reasoning_summary: "",
    suggested_correction: "",
  });

  useEffect(() => {
    if (!finding) {
      return;
    }

    setDraft({
      title: finding.title,
      category: finding.category,
      severity: finding.severity,
      confidence: finding.confidence,
      comment_text: finding.comment_text,
      reasoning_summary: finding.reasoning_summary,
      suggested_correction: finding.suggested_correction,
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

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void onPatchFinding(activeFinding.id, draft);
  }

  return (
    <form className="inspector" onSubmit={handleSubmit}>
      <div className="inspector-header">
        <div>
          <span className="eyebrow">Inspector</span>
          <h3>{sheet ? sheetLabel(sheet) : "Project finding"}</h3>
        </div>
        <span className={`status-chip status-${statusClass(finding.status)}`}>
          {formatStatus(finding.status)}
        </span>
      </div>

      <label className="field-label">
        Title
        <input
          type="text"
          value={draft.title}
          onChange={(event) => setDraft((current) => ({ ...current, title: event.target.value }))}
        />
      </label>

      <div className="field-grid">
        <label className="field-label">
          Severity
          <select
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

        <label className="field-label">
          Category
          <select
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

      <label className="field-label">
        PDF comment
        <textarea
          value={draft.comment_text}
          rows={3}
          onChange={(event) =>
            setDraft((current) => ({ ...current, comment_text: event.target.value }))
          }
        />
      </label>

      <label className="field-label">
        Suggested correction
        <textarea
          value={draft.suggested_correction}
          rows={3}
          onChange={(event) =>
            setDraft((current) => ({ ...current, suggested_correction: event.target.value }))
          }
        />
      </label>

      <label className="field-label">
        Reasoning
        <textarea
          value={draft.reasoning_summary}
          rows={4}
          onChange={(event) =>
            setDraft((current) => ({ ...current, reasoning_summary: event.target.value }))
          }
        />
      </label>

      <div className="finding-details">
        <span>
          <strong>Confidence</strong> {confidenceLabel(draft.confidence)}
        </span>
        <span>
          <strong>Source</strong> {finding.source || "unknown"}
        </span>
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

      <div className="inspector-actions">
        <button className="primary-button" type="submit" disabled={saving}>
          {saving ? <Loader2 size={17} className="spin" /> : <Save size={17} />}
          Save
        </button>
        <button
          className="secondary-button"
          type="button"
          disabled={saving}
          onClick={() => void onPatchFinding(finding.id, { status: "accepted" })}
        >
          <Check size={17} />
          Accept
        </button>
        <button
          className="secondary-button"
          type="button"
          disabled={saving}
          onClick={() => void onPatchFinding(finding.id, { status: "needs_review" })}
        >
          <ClipboardCheck size={17} />
          Review
        </button>
        <button
          className="secondary-button"
          type="button"
          disabled={saving}
          onClick={() => void onPatchFinding(finding.id, { status: "rejected" })}
        >
          <X size={17} />
          Reject
        </button>
        <button
          className="danger-button"
          type="button"
          disabled={deleting}
          onClick={() => void onDeleteFinding(finding)}
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
}

function ExportPanel({ project, findings }: ExportPanelProps) {
  const [statuses, setStatuses] = useState<FindingStatus[]>(["accepted"]);
  const [exporting, setExporting] = useState(false);
  const [result, setResult] = useState<ExportResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

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

    try {
      const response = await exportProject(project.id, { statuses });
      setResult(response);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setExporting(false);
    }
  }

  const outputRows = result
    ? [
        ["Marked PDF", result.marked_pdf],
        ["QC log", result.csv_log],
        ["Excel log", result.excel_log],
        ["JSON findings", result.json_findings],
        ["Markdown", result.markdown_summary],
        ["HTML", result.html_summary],
      ].filter(([, value]) => Boolean(value))
    : [];

  return (
    <section className="panel export-panel">
      <div className="panel-header">
        <div>
          <span className="eyebrow">Export</span>
          <h2>Review Package</h2>
        </div>
        <Download size={18} />
      </div>

      <div className="export-counts">
        {STATUSES.map((status) => (
          <label className="checkbox-row" key={status}>
            <input
              type="checkbox"
              checked={statuses.includes(status)}
              onChange={() => toggleStatus(status)}
            />
            <span>{formatStatus(status)}</span>
            <strong>{countFindingsByStatus(findings, status)}</strong>
          </label>
        ))}
      </div>

      <button
        className="primary-button full-width"
        type="button"
        disabled={!project || statuses.length === 0 || exporting}
        onClick={() => void handleExport()}
      >
        {exporting ? <Loader2 size={17} className="spin" /> : <Download size={17} />}
        Export
      </button>

      {error ? <div className="inline-error">{error}</div> : null}

      {result ? (
        <div className="output-list">
          <strong>Generated files</strong>
          {outputRows.map(([label, value]) => (
            <div className="output-row" key={label ?? String(value)}>
              <span>{label}</span>
              <code>{value}</code>
            </div>
          ))}
        </div>
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

function getOverlayRect(
  finding: Finding,
  sheet: Sheet,
  imageSize: ImageSize | null,
): CSSProperties | null {
  const bbox = extractBbox(finding.location);
  if (!bbox) {
    return null;
  }

  const [rawX0, rawY0, rawX1, rawY1] = bbox;
  const normalized = bbox.every((coordinate) => coordinate >= 0 && coordinate <= 1);
  const sourceWidth = sheet.width ?? imageSize?.width ?? null;
  const sourceHeight = sheet.height ?? imageSize?.height ?? null;

  if (normalized) {
    return {
      left: `${clamp(rawX0 * 100, 0, 100)}%`,
      top: `${clamp(rawY0 * 100, 0, 100)}%`,
      width: `${clamp((rawX1 - rawX0) * 100, 0.6, 100)}%`,
      height: `${clamp((rawY1 - rawY0) * 100, 0.6, 100)}%`,
    };
  }

  if (!sourceWidth || !sourceHeight) {
    return null;
  }

  const origin = typeof finding.location === "object" && !Array.isArray(finding.location)
    ? finding.location?.origin
    : "top_left";

  const y0 = origin === "bottom_left" ? sourceHeight - rawY1 : rawY0;
  const y1 = origin === "bottom_left" ? sourceHeight - rawY0 : rawY1;

  return {
    left: `${clamp((rawX0 / sourceWidth) * 100, 0, 100)}%`,
    top: `${clamp((y0 / sourceHeight) * 100, 0, 100)}%`,
    width: `${clamp(((rawX1 - rawX0) / sourceWidth) * 100, 0.6, 100)}%`,
    height: `${clamp(((y1 - y0) / sourceHeight) * 100, 0.6, 100)}%`,
  };
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export default App;
