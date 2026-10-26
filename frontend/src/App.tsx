import * as React from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import {
  CircleAlert,
  CircleCheck,
  ChevronRight,
  CloudOff,
  CloudUpload,
  FilePlus2,
  FileText,
  Folder,
  FolderPlus,
  ExternalLink,
  LoaderCircle,
  LogOut,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Save,
  Trash2,
  X,
  type LucideIcon,
} from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { GitHubLogin } from "@/components/github-login"
import { UpdateDialog } from "@/components/update-dialog"
import { request } from "@/lib/api"
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuGroup,
  ContextMenuItem,
  ContextMenuLabel,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "@/components/ui/context-menu"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarSeparator,
} from "@/components/ui/sidebar"
import { Textarea } from "@/components/ui/textarea"
import { Toaster } from "@/components/ui/sonner"
import { useIsMobile } from "@/hooks/use-mobile"
import {
  buildWorkspaceLocation,
  readWorkspaceRoute,
} from "@/lib/workspace-route"
import { remarkHeadingAnchors } from "@/lib/markdown-anchors"
import { extractFrontmatter } from "@/lib/markdown-frontmatter"

type Project = {
  protected?: boolean
  id: string
  name: string
  description: string
  document_count: number
}

type TreeNode = {
  type: "folder" | "document"
  name: string
  title?: string
  id?: string
  path?: string
  children?: TreeNode[]
}

type Document = {
  id: string
  title: string
  path: string
  content: string
  revision: number
}

type SyncStatus = {
  state?: string
  last_error?: string | null
  last_sync?: string | null
  authenticated?: boolean
  pending?: boolean
  has_local_changes?: boolean
  pending_count?: number
  workspace_version?: string
  conflicts?: string[]
}

type GitHubUser = {
  login: string
  name?: string | null
  avatar_url?: string | null
  html_url?: string | null
}

type GitHubRepository = {
  name: string
  full_name: string
  html_url?: string | null
  default_branch: string
}

type GitHubAuthStatus = {
  configured: boolean
  authenticated: boolean
  user: GitHubUser | null
  repository: GitHubRepository | null
  repository_error: string | null
}

type TreeActionTarget = {
  kind: "document" | "folder"
  path: string
  id?: string
  name: string
}

type WorkspaceHistoryMode = "push" | "replace" | "none"

function writeWorkspaceRoute(
  projectId: string | null,
  documentPath: string | null,
  mode: Exclude<WorkspaceHistoryMode, "none">
) {
  const nextLocation = buildWorkspaceLocation(
    new URL(window.location.href),
    projectId,
    documentPath
  )
  const currentLocation = `${window.location.pathname}${window.location.search}${window.location.hash}`
  if (nextLocation === currentLocation) return

  if (mode === "push") {
    window.history.pushState(window.history.state, "", nextLocation)
  } else {
    window.history.replaceState(window.history.state, "", nextLocation)
  }
}

function App() {
  const isMobile = useIsMobile()
  const [githubAuth, setGithubAuth] = React.useState<GitHubAuthStatus | null>(
    null
  )
  const [projects, setProjects] = React.useState<Project[]>([])
  const [project, setProject] = React.useState<Project | null>(null)
  const [tree, setTree] = React.useState<TreeNode[]>([])
  const [document, setDocument] = React.useState<Document | null>(null)
  const [draft, setDraft] = React.useState("")
  const [editing, setEditing] = React.useState(false)
  const [loading, setLoading] = React.useState(true)
  const [saving, setSaving] = React.useState(false)
  const [syncStatus, setSyncStatus] = React.useState<SyncStatus>({})
  const [syncRequesting, setSyncRequesting] = React.useState(false)
  const [projectDialogOpen, setProjectDialogOpen] = React.useState(false)
  const [projectRenameTarget, setProjectRenameTarget] =
    React.useState<Project | null>(null)
  const [projectRenameName, setProjectRenameName] = React.useState("")
  const [projectDeleteTarget, setProjectDeleteTarget] =
    React.useState<Project | null>(null)
  const [documentDialogOpen, setDocumentDialogOpen] = React.useState(false)
  const [folderDialogParent, setFolderDialogParent] = React.useState<
    string | null
  >(null)
  const [folderName, setFolderName] = React.useState("")
  const [documentParent, setDocumentParent] = React.useState("docs")
  const [renameTarget, setRenameTarget] =
    React.useState<TreeActionTarget | null>(null)
  const [renamePath, setRenamePath] = React.useState("")
  const [deleteTarget, setDeleteTarget] =
    React.useState<TreeActionTarget | null>(null)
  const [deleteConfirmation, setDeleteConfirmation] = React.useState("")
  const [projectName, setProjectName] = React.useState("")
  const [projectDescription, setProjectDescription] = React.useState("")
  const [documentName, setDocumentName] = React.useState("")
  const [searchQuery, setSearchQuery] = React.useState("")
  const workspaceNavigation = React.useRef(0)
  const appliedWorkspaceVersion = React.useRef<string | null>(null)
  React.useEffect(() => {
    if (!document || editing || !window.location.hash) return
    let anchor: string
    try {
      anchor = decodeURIComponent(window.location.hash.slice(1))
    } catch {
      return
    }
    const frame = window.requestAnimationFrame(() => {
      window.document.getElementById(anchor)?.scrollIntoView()
    })
    return () => window.cancelAnimationFrame(frame)
  }, [document, editing])
  const syncInProgress =
    syncRequesting ||
    syncStatus.state === "queued" ||
    syncStatus.state === "syncing"

  async function selectProject(
    selected: Project,
    options: {
      documentId?: string
      documentPath?: string
      openFirstDocument?: boolean
      historyMode?: WorkspaceHistoryMode
    } = {}
  ) {
    const navigationId = ++workspaceNavigation.current
    const historyMode = options.historyMode ?? "push"
    setProject(selected)
    setDocument(null)
    setDraft("")
    setEditing(false)

    try {
      const [freshProject, nextTree] = await Promise.all([
        request<Project>(`/projects/${selected.id}`),
        request<TreeNode[]>(`/projects/${selected.id}/tree`),
      ])
      if (navigationId !== workspaceNavigation.current) return
      setProject({ ...freshProject, document_count: countDocuments(nextTree) })
      setTree(nextTree)

      const linkedDocument = options.documentPath
        ? findDocumentByPath(nextTree, options.documentPath)
        : options.documentId
          ? findDocumentById(nextTree, options.documentId)
          : undefined
      const hasDocumentLink = Boolean(
        options.documentPath || options.documentId
      )
      const targetDocument = hasDocumentLink
        ? linkedDocument
        : options.openFirstDocument === false
          ? undefined
          : findFirstDocument(nextTree)

      if (targetDocument?.id) {
        await openDocument(
          selected.id,
          targetDocument.id,
          historyMode,
          navigationId
        )
      } else {
        if (hasDocumentLink) {
          toast.error("O arquivo deste link não existe mais neste projeto.")
        }
        if (historyMode !== "none" || hasDocumentLink) {
          writeWorkspaceRoute(
            selected.id,
            null,
            historyMode === "none" ? "replace" : historyMode
          )
        }
      }
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : "Não foi possível abrir o projeto"
      )
    }
  }

  async function openDocument(
    projectId: string,
    documentId: string,
    historyMode: WorkspaceHistoryMode = "push",
    navigationId = ++workspaceNavigation.current
  ) {
    try {
      const nextDocument = await request<Document>(
        `/projects/${projectId}/documents/${documentId}`
      )
      if (navigationId !== workspaceNavigation.current) return false
      setDocument(nextDocument)
      setDraft(nextDocument.content)
      setEditing(false)
      writeWorkspaceRoute(
        projectId,
        nextDocument.path,
        historyMode === "none" ? "replace" : historyMode
      )
      return true
    } catch (error) {
      if (navigationId !== workspaceNavigation.current) return false
      toast.error(
        error instanceof Error
          ? error.message
          : "Não foi possível abrir o documento"
      )
    }
  }

  async function refreshWorkspace(projectId: string) {
    const [nextTree, freshProject] = await Promise.all([
      request<TreeNode[]>(`/projects/${projectId}/tree`),
      request<Project>(`/projects/${projectId}`),
    ])
    setTree(nextTree)
    const projectWithCount = {
      ...freshProject,
      document_count: countDocuments(nextTree),
    }
    setProject(projectWithCount)
    setProjects((items) =>
      items.map((item) =>
        item.id === freshProject.id ? projectWithCount : item
      )
    )
  }

  async function refreshSyncStatus() {
    try {
      setSyncStatus(await request<SyncStatus>("/sync/status"))
    } catch {
      setSyncStatus({ state: "unavailable" })
    }
  }

  const refreshRestoredWorkspace = React.useEffectEvent(async (version: string, isActive: () => boolean) => {
    try {
      const [items, account] = await Promise.all([
        request<Project[]>("/projects"),
        request<GitHubAuthStatus>("/github/auth/status"),
      ])
      if (!isActive()) return
      appliedWorkspaceVersion.current = version
      setProjects(items)
      setGithubAuth(account)
      const selected = items.find((item) => item.id === project?.id) ?? items[0]
      if (selected) {
        await selectProject(selected, {
          documentId: selected.id === project?.id ? document?.id : undefined,
          historyMode: "replace",
        })
      } else {
        setProject(null)
        setDocument(null)
        setTree([])
      }
      if (syncStatus.conflicts?.length) {
        toast.info(`Backup restaurado. ${syncStatus.conflicts.length} edição(ões) local(is) preservada(s) em arquivos de conflito.`)
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Não foi possível carregar os arquivos restaurados.")
    }
  })

  React.useEffect(() => {
    const version = syncStatus.workspace_version
    if (!version || appliedWorkspaceVersion.current === version || editing || saving) return
    let active = true
    void refreshRestoredWorkspace(version, () => active)
    return () => { active = false }
  }, [syncStatus.workspace_version, editing, saving])

  React.useEffect(() => {
    let active = true
    async function initializeWorkspace() {
      try {
        const items = await request<Project[]>("/projects")
        if (!active) return
        setProjects(items)

        const route = readWorkspaceRoute(new URL(window.location.href))
        if (route.invalid) {
          toast.error("O caminho deste link não é válido.")
          return
        }
        if (route.projectId) {
          const selected = items.find((item) => item.id === route.projectId)
          if (selected) {
            await selectProject(selected, {
              documentId: route.documentId ?? undefined,
              documentPath: route.documentPath ?? undefined,
              openFirstDocument: false,
              historyMode: "replace",
            })
          } else {
            toast.error("O projeto deste link não existe mais.")
            writeWorkspaceRoute(null, null, "replace")
          }
        } else if (route.documentId) {
          toast.error("O link do arquivo precisa informar o projeto.")
          writeWorkspaceRoute(null, null, "replace")
        } else if (items[0]) {
          await selectProject(items[0], { historyMode: "replace" })
        }
      } catch (error) {
        toast.error(
          error instanceof Error
            ? error.message
            : "Não foi possível carregar os projetos"
        )
      } finally {
        if (active) setLoading(false)
      }
    }

    void initializeWorkspace()
    const initialSyncStatusTimer = window.setTimeout(() => {
      void refreshSyncStatus()
    }, 0)
    const syncTimer = window.setInterval(() => {
      void refreshSyncStatus()
    }, 5000)

    void request<GitHubAuthStatus>("/github/auth/status")
      .then((status) => {
        if (!active) return
        setGithubAuth(status)
        if (status.repository_error) toast.error(status.repository_error)
      })
      .catch((error) => {
        if (!active) return
        toast.error(
          error instanceof Error
            ? error.message
            : "Não foi possível verificar a conta GitHub"
        )
      })

    return () => {
      active = false
      window.clearTimeout(initialSyncStatusTimer)
      window.clearInterval(syncTimer)
    }
  }, [])

  React.useEffect(() => {
    async function restoreWorkspaceFromHistory() {
      const route = readWorkspaceRoute(new URL(window.location.href))
      if (route.invalid) {
        toast.error("O caminho deste link não é válido.")
        return
      }
      if (!route.projectId) {
        workspaceNavigation.current += 1
        setProject(null)
        setTree([])
        setDocument(null)
        setDraft("")
        setEditing(false)
        if (route.documentId) {
          toast.error("O link do arquivo precisa informar o projeto.")
          writeWorkspaceRoute(null, null, "replace")
        }
        return
      }

      const selected = projects.find((item) => item.id === route.projectId)
      if (!selected) {
        workspaceNavigation.current += 1
        setProject(null)
        setTree([])
        setDocument(null)
        setDraft("")
        setEditing(false)
        toast.error("O projeto deste link não existe mais.")
        writeWorkspaceRoute(null, null, "replace")
        return
      }

      await selectProject(selected, {
        documentId: route.documentId ?? undefined,
        documentPath: route.documentPath ?? undefined,
        openFirstDocument: false,
        historyMode: "none",
      })
    }

    window.addEventListener("popstate", restoreWorkspaceFromHistory)
    return () =>
      window.removeEventListener("popstate", restoreWorkspaceFromHistory)
  }, [projects])

  async function saveDocument() {
    if (!project || !document || draft === document.content) {
      setEditing(false)
      return true
    }
    setSaving(true)
    try {
      const saved = await request<Document>(
        `/projects/${project.id}/documents/${document.id}`,
        {
          method: "PUT",
          body: JSON.stringify({ content: draft, revision: document.revision }),
        }
      )
      setDocument(saved)
      setDraft(saved.content)
      setEditing(false)
      await refreshWorkspace(project.id)
      await refreshSyncStatus()
      toast.success("Documento salvo")
      return true
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Não foi possível salvar"
      )
      return false
    } finally {
      setSaving(false)
    }
  }

  async function createProject(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    try {
      const created = await request<Project>("/projects", {
        method: "POST",
        body: JSON.stringify({
          name: projectName,
          description: projectDescription,
        }),
      })
      setProjectDialogOpen(false)
      setProjectName("")
      setProjectDescription("")
      const items = await request<Project[]>("/projects")
      setProjects(items)
      await selectProject(
        items.find((item) => item.id === created.id) ?? created
      )
      toast.success("Projeto criado")
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : "Não foi possível criar o projeto"
      )
    }
  }

  async function createDocument(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!project) return
    const filename = documentName.trim().replace(/\\/g, "/")
    const path = filename.toLowerCase().endsWith(".md")
      ? filename
      : `${filename}.md`
    const title = path.split("/").pop()?.replace(/\.md$/i, "") ?? "Sem título"
    try {
      const created = await request<Document>(
        `/projects/${project.id}/documents`,
        {
          method: "POST",
          body: JSON.stringify({
            path: `${documentParent}/${path}`,
            title,
          }),
        }
      )
      setDocumentDialogOpen(false)
      setDocumentName("")
      setDocumentParent("docs")
      await refreshWorkspace(project.id)
      await openDocument(project.id, created.id)
      toast.success("Documento criado")
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : "Não foi possível criar o documento"
      )
    }
  }

  async function createFolder(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!project || folderDialogParent === null) return

    const name = normalizePath(folderName)
    const path = [folderDialogParent, name].filter(Boolean).join("/")

    try {
      await request(`/projects/${project.id}/folders`, {
        method: "POST",
        body: JSON.stringify({ path }),
      })
      setFolderDialogParent(null)
      setFolderName("")
      await refreshWorkspace(project.id)
      toast.success("Pasta criada")
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : "Não foi possível criar a pasta"
      )
    }
  }

  async function renameTreeTarget(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!project || !renameTarget) return

    const invalidNameMessage = getInvalidWindowsNameMessage(renamePath)
    if (invalidNameMessage) {
      toast.error(invalidNameMessage)
      return
    }

    const parentPath = renameTarget.path.split("/").slice(0, -1).join("/")
    const newName = normalizePath(renamePath).split("/").pop() ?? ""
    if (renameTarget.kind === "document" && !newName.replace(/\.md$/i, "")) {
      toast.error("Informe um nome antes da extensão .md.")
      return
    }
    const filename =
      renameTarget.kind === "document"
        ? `${newName.replace(/\.md$/i, "")}.md`
        : newName
    const newPath = parentPath ? `${parentPath}/${filename}` : filename

    try {
      if (renameTarget.kind === "document" && renameTarget.id) {
        const title = filename.replace(/\.md$/i, "")
        const renamed = await request<Document>(
          `/projects/${project.id}/documents/${renameTarget.id}`,
          {
            method: "PATCH",
            body: JSON.stringify({ path: newPath, title }),
          }
        )
        if (document?.id === renamed.id) {
          setDocument(renamed)
          setDraft(renamed.content)
        }
      } else {
        await request(`/projects/${project.id}/folders`, {
          method: "PATCH",
          body: JSON.stringify({ path: renameTarget.path, new_path: newPath }),
        })
      }

      await refreshWorkspace(project.id)
      if (document?.id) await openDocument(project.id, document.id)
      setRenameTarget(null)
      toast.success(
        renameTarget.kind === "document"
          ? "Arquivo renomeado"
          : "Pasta renomeada"
      )
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Não foi possível renomear"
      )
    }
  }

  async function deleteTreeTarget() {
    if (!project || !deleteTarget || deleteConfirmation !== "Deletar") return

    try {
      if (deleteTarget.kind === "document" && deleteTarget.id) {
        await request(`/projects/${project.id}/documents/${deleteTarget.id}`, {
          method: "DELETE",
        })
        if (document?.id === deleteTarget.id) setDocument(null)
      } else {
        await request(
          `/projects/${project.id}/folders?path=${encodeURIComponent(deleteTarget.path)}`,
          { method: "DELETE" }
        )
        if (
          document?.path === deleteTarget.path ||
          document?.path.startsWith(`${deleteTarget.path}/`)
        ) {
          setDocument(null)
        }
      }

      if (
        (deleteTarget.kind === "document" &&
          document?.id === deleteTarget.id) ||
        (deleteTarget.kind === "folder" &&
          (document?.path === deleteTarget.path ||
            document?.path.startsWith(`${deleteTarget.path}/`)))
      ) {
        writeWorkspaceRoute(project.id, null, "replace")
        setDraft("")
      }

      setEditing(false)
      await refreshWorkspace(project.id)
      setDeleteTarget(null)
      setDeleteConfirmation("")
      toast.success(
        deleteTarget.kind === "document" ? "Arquivo excluído" : "Pasta excluída"
      )
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Não foi possível excluir"
      )
    }
  }

  function openDocumentCreator(parentPath = "docs") {
    setDocumentParent(parentPath)
    setDocumentName("")
    setDocumentDialogOpen(true)
  }

  function openFolderCreator(parentPath: string) {
    setFolderDialogParent(parentPath)
    setFolderName("")
  }

  function openRenameDialog(target: TreeActionTarget) {
    setRenameTarget(target)
    const filename = target.path.split("/").pop() ?? target.path
    setRenamePath(
      target.kind === "document" ? filename.replace(/\.md$/i, "") : filename
    )
  }

  function openDeleteDialog(target: TreeActionTarget) {
    setDeleteConfirmation("")
    setProjectDeleteTarget(null)
    setDeleteTarget(target)
  }

  function openProjectRenameDialog(target: Project) {
    setProjectRenameTarget(target)
    setProjectRenameName(target.name)
  }

  function openProjectDeleteDialog(target: Project) {
    setDeleteConfirmation("")
    setDeleteTarget(null)
    setProjectDeleteTarget(target)
  }

  async function renameProject(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!projectRenameTarget) return

    const name = projectRenameName.trim()
    if (!name) return

    try {
      const updated = await request<Project>(
        `/projects/${projectRenameTarget.id}`,
        {
          method: "PATCH",
          body: JSON.stringify({ name }),
        }
      )
      setProjects((items) =>
        items.map((item) =>
          item.id === updated.id ? { ...item, ...updated } : item
        )
      )
      setProject((current) =>
        current?.id === updated.id ? { ...current, ...updated } : current
      )
      setProjectRenameTarget(null)
      toast.success("Projeto renomeado")
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Não foi possível renomear"
      )
    }
  }

  async function deleteProject() {
    if (!projectDeleteTarget || deleteConfirmation !== "Deletar") return

    try {
      const deletedProject = projectDeleteTarget
      await request(`/projects/${deletedProject.id}?confirm=true`, {
        method: "DELETE",
      })

      const remainingProjects = projects.filter(
        (item) => item.id !== deletedProject.id
      )
      setProjects(remainingProjects)
      setProjectDeleteTarget(null)
      setDeleteConfirmation("")

      if (project?.id === deletedProject.id) {
        setProject(null)
        setTree([])
        setDocument(null)
        setDraft("")
        setEditing(false)
        if (remainingProjects[0]) {
          await selectProject(remainingProjects[0], { historyMode: "replace" })
        } else {
          writeWorkspaceRoute(null, null, "replace")
        }
      }

      toast.success("Projeto removido da lista")
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Não foi possível excluir"
      )
    }
  }

  async function triggerSync() {
    if (!githubAuth?.authenticated) {
      toast.error("Entre na sua conta do GitHub para sincronizar.")
      return
    }
    if (syncInProgress) return

    setSyncRequesting(true)
    try {
      const queuedStatus = await request<SyncStatus>("/sync/trigger", {
        method: "POST",
      })
      setSyncStatus(queuedStatus)
      await refreshSyncStatus()
      toast.success("Sincronização solicitada")
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Falha na sincronização"
      )
    } finally {
      setSyncRequesting(false)
    }
  }

  async function refreshGitHubAccount() {
    const status = await request<GitHubAuthStatus>("/github/auth/status")
    setGithubAuth(status)
    if (status.repository_error) toast.error(status.repository_error)
    await refreshSyncStatus()
  }

  async function logoutFromGitHub() {
    try {
      await request("/github/auth", { method: "DELETE" })
      setGithubAuth((current) =>
        current
          ? { ...current, authenticated: false, user: null, repository: null }
          : current
      )
      await refreshSyncStatus()
      toast.success("Você saiu da conta GitHub")
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : "Não foi possível sair da conta"
      )
    }
  }

  const filteredTree = React.useMemo(
    () => filterTree(tree, searchQuery.trim().toLocaleLowerCase("pt-BR")),
    [tree, searchQuery]
  )

  return (
    <SidebarProvider
      defaultOpen
      className="h-svh overflow-hidden bg-background font-sans text-foreground"
    >
      <Sidebar collapsible="none" className="border-r border-border">
        <SidebarHeader className="gap-5 p-5">
          <div className="flex items-center gap-3">
            <img src="/static/docs-local.ico" alt="" className="size-10 shrink-0 object-contain" />
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold tracking-tight">
                Docs Local
              </p>
              <p className="text-xs text-muted-foreground">
                Sua documentação, local
              </p>
            </div>
          </div>
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold tracking-wider text-muted-foreground uppercase">
              Projetos
            </p>
            <Dialog
              open={projectDialogOpen}
              onOpenChange={setProjectDialogOpen}
            >
              <DialogTrigger
                render={
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Criar projeto"
                  />
                }
              >
                <Plus className="size-4" />
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Novo projeto</DialogTitle>
                  <DialogDescription>
                    Crie um espaço para organizar seus documentos Markdown.
                  </DialogDescription>
                </DialogHeader>
                <form className="grid gap-4" onSubmit={createProject}>
                  <Input
                    autoFocus
                    required
                    maxLength={120}
                    placeholder="Nome do projeto"
                    value={projectName}
                    onChange={(event) => setProjectName(event.target.value)}
                  />
                  <Textarea
                    maxLength={2000}
                    placeholder="Descrição (opcional)"
                    value={projectDescription}
                    onChange={(event) =>
                      setProjectDescription(event.target.value)
                    }
                  />
                  <DialogFooter>
                    <Button type="submit">Criar projeto</Button>
                  </DialogFooter>
                </form>
              </DialogContent>
            </Dialog>
          </div>
        </SidebarHeader>
        <SidebarSeparator />
        <SidebarContent>
          <SidebarGroup className="px-3 py-3">
            <SidebarGroupContent>
              <SidebarMenu>
                {projects.map((item) => (
                  <SidebarMenuItem key={item.id}>
                    <ContextMenu>
                      <ContextMenuTrigger
                        render={<div className="w-full min-w-0" />}
                      >
                        <SidebarMenuButton
                          isActive={project?.id === item.id}
                          onClick={() => selectProject(item)}
                          tooltip={item.name}
                        >
                          <Folder className="size-4" />
                          <span>{item.name}</span>
                          <span className="ml-auto text-xs text-muted-foreground">
                            {item.document_count}
                          </span>
                        </SidebarMenuButton>
                      </ContextMenuTrigger>
                      <ContextMenuContent>
                        <ContextMenuGroup>
                          <ContextMenuLabel>{item.name}</ContextMenuLabel>
                          <ContextMenuItem
                            disabled={item.protected}
                            onClick={() => openProjectRenameDialog(item)}
                          >
                            <Pencil /> Renomear projeto
                          </ContextMenuItem>
                          <ContextMenuItem
                            variant="destructive"
                            disabled={item.protected}
                            onClick={() => openProjectDeleteDialog(item)}
                          >
                            <Trash2 /> Excluir projeto
                          </ContextMenuItem>
                        </ContextMenuGroup>
                      </ContextMenuContent>
                    </ContextMenu>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
              {!loading && projects.length === 0 && (
                <div className="rounded-lg border border-dashed border-sidebar-border p-4 text-center text-xs leading-relaxed text-muted-foreground">
                  Seus projetos aparecerão aqui. Crie um para começar.
                </div>
              )}
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>
        <SidebarFooter className="p-4">
          <SyncStatusIndicator status={syncStatus} />
        </SidebarFooter>
      </Sidebar>

      <SidebarInset className="h-full min-h-0 min-w-0 overflow-hidden bg-background">
        <header className="flex h-16 shrink-0 items-center justify-between gap-3 border-b border-border px-5 sm:pl-4 sm:pr-8">
          <div className="flex min-w-0 items-center gap-3">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">
                {project?.name ?? "Workspace"}
              </p>
              <p className="text-xs text-muted-foreground">
                {project?.description || "Documentação e arquivos do projeto"}
              </p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={triggerSync}
              disabled={syncInProgress}
              className="hidden sm:inline-flex"
            >
              <RefreshCw
                data-icon="inline-start"
                className={cn(syncInProgress && "animate-spin")}
              />
              {syncInProgress ? "Sincronizando..." : "Sincronizar"}
            </Button>
            {githubAuth?.authenticated && githubAuth.user ? (
              <DropdownMenu>
                <DropdownMenuTrigger
                  render={
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Conta GitHub ${githubAuth.user.login}`}
                    >
                      <Avatar>
                        <AvatarImage
                          src={githubAuth.user.avatar_url ?? undefined}
                          alt={`Foto de ${githubAuth.user.login}`}
                        />
                        <AvatarFallback>
                          {githubAuth.user.login.slice(0, 2).toUpperCase()}
                        </AvatarFallback>
                      </Avatar>
                    </Button>
                  }
                />
                <DropdownMenuContent align="end" className="w-64">
                  <DropdownMenuGroup>
                    <DropdownMenuLabel>
                      <span className="block truncate">
                        {githubAuth.user.name || githubAuth.user.login}
                      </span>
                      <span className="block truncate font-normal text-muted-foreground">
                        @{githubAuth.user.login}
                      </span>
                    </DropdownMenuLabel>
                  </DropdownMenuGroup>
                  <DropdownMenuSeparator />
                  <DropdownMenuGroup>
                    <DropdownMenuItem
                      disabled={!githubAuth.user.html_url}
                      onClick={() =>
                        githubAuth.user?.html_url &&
                        window.open(
                          githubAuth.user.html_url,
                          "_blank",
                          "noopener,noreferrer"
                        )
                      }
                    >
                      <ExternalLink /> Perfil no GitHub
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      disabled={!githubAuth.repository?.html_url}
                      onClick={() =>
                        githubAuth.repository?.html_url &&
                        window.open(
                          githubAuth.repository.html_url,
                          "_blank",
                          "noopener,noreferrer"
                        )
                      }
                    >
                      <ExternalLink /> Repositório de backup
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      disabled={syncInProgress}
                      onClick={triggerSync}
                    >
                      <RefreshCw
                        className={cn(syncInProgress && "animate-spin")}
                      />
                      {syncInProgress
                        ? "Sincronizando..."
                        : "Sincronizar agora"}
                    </DropdownMenuItem>
                  </DropdownMenuGroup>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    variant="destructive"
                    onClick={logoutFromGitHub}
                  >
                    <LogOut /> Sair da conta
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            ) : (
              <GitHubLogin onConnected={refreshGitHubAccount} />
            )}
            <Dialog
              open={documentDialogOpen}
              onOpenChange={setDocumentDialogOpen}
            >
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Novo documento</DialogTitle>
                  <DialogDescription>
                    Informe o nome do arquivo dentro de {documentParent}/.
                  </DialogDescription>
                </DialogHeader>
                <form className="grid gap-4" onSubmit={createDocument}>
                  <Input
                    autoFocus
                    required
                    placeholder="ex.: guia/instalacao.md"
                    value={documentName}
                    onChange={(event) => setDocumentName(event.target.value)}
                  />
                  <DialogFooter>
                    <Button type="submit">Criar documento</Button>
                  </DialogFooter>
                </form>
              </DialogContent>
            </Dialog>
          </div>
        </header>

        <ResizablePanelGroup
          orientation={isMobile ? "vertical" : "horizontal"}
          className="min-h-0 flex-1"
        >
          <ResizablePanel
            defaultSize={isMobile ? 260 : 250}
            minSize={isMobile ? 150 : 200}
            maxSize={480}
            className="min-h-0 min-w-0"
          >
            <aside className="flex h-full min-h-0 min-w-0 flex-col border-b border-border bg-card/30 md:border-r md:border-b-0">
              <div className="flex h-14 shrink-0 items-center justify-between px-4">
                <div>
                  <p className="text-sm font-medium">Arquivos</p>
                  <p className="text-xs text-muted-foreground">
                    {project?.document_count ?? 0} documentos
                  </p>
                </div>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Criar documento"
                  disabled={!project || project.protected}
                  onClick={() => openDocumentCreator("docs")}
                >
                  <Plus className="size-4" />
                </Button>
              </div>
              <div className="px-3 pb-3">
                <div className="relative">
                  <Search className="pointer-events-none absolute top-2.5 left-2.5 size-4 text-muted-foreground" />
                  <Input
                    className="h-9 pl-8"
                    placeholder="Filtrar arquivos..."
                    value={searchQuery}
                    onChange={(event) => setSearchQuery(event.target.value)}
                  />
                </div>
              </div>
              <Separator />
              <ScrollArea className="min-h-0 flex-1 px-2 py-3">
                {loading ? (
                  <div className="flex items-center justify-center py-10 text-muted-foreground">
                    <LoaderCircle className="size-4 animate-spin" />
                  </div>
                ) : filteredTree.length ? (
                  <FileTree
                    nodes={filteredTree}
                    protectedProject={project?.protected ?? false}
                    selectedId={document?.id}
                    onSelect={(id) => project && openDocument(project.id, id)}
                    onRename={openRenameDialog}
                    onDelete={openDeleteDialog}
                    onCreateDocument={openDocumentCreator}
                    onCreateFolder={openFolderCreator}
                  />
                ) : (
                  <div className="px-3 py-8 text-center text-xs text-muted-foreground">
                    {tree.length
                      ? "Nenhum arquivo encontrado."
                      : "Este projeto ainda não tem arquivos."}
                  </div>
                )}
              </ScrollArea>
              <div className="border-t border-border px-4 py-3 text-xs text-muted-foreground">
                Salvo localmente · sincronização Git
              </div>
            </aside>
          </ResizablePanel>
          <ResizableHandle withHandle />
          <ResizablePanel
            minSize={isMobile ? 160 : 300}
            className="min-h-0 min-w-0"
          >
            <main className="flex h-full min-h-0 min-w-0 flex-col">
              {document ? (
                <>
                  <div className="flex min-h-14 shrink-0 flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-2 sm:px-8">
                    <div className="min-w-0">
                      <p className="truncate text-xs text-muted-foreground">
                        {document.path}
                      </p>
                      <h1 className="truncate text-sm font-semibold">
                        {document.title}
                      </h1>
                    </div>
                    <div className="flex items-center gap-2">
                      {editing ? (
                        <>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                              setDraft(document.content)
                              setEditing(false)
                            }}
                            disabled={saving}
                          >
                            <X className="size-4" /> Cancelar
                          </Button>
                          <Button
                            size="sm"
                            onClick={saveDocument}
                            disabled={saving || draft === document.content}
                          >
                            {saving ? (
                              <LoaderCircle className="size-4 animate-spin" />
                            ) : (
                              <Save className="size-4" />
                            )}{" "}
                            Salvar
                          </Button>
                        </>
                      ) : (
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={project?.protected}
                          onClick={() => setEditing(true)}
                        >
                          <Pencil className="size-4" /> {project?.protected ? "Somente leitura" : "Editar Markdown"}
                        </Button>
                      )}
                    </div>
                  </div>
                  <ScrollArea className="min-h-0 flex-1">
                    {editing ? (
                      <div className="mx-auto flex h-full w-full max-w-5xl flex-col p-5 sm:p-8">
                        <div className="mb-3 flex items-center justify-between text-xs text-muted-foreground">
                          <span>Markdown</span>
                          <span>Revisão {document.revision}</span>
                        </div>
                        <Textarea
                          className="min-h-[60vh] flex-1 resize-y font-mono text-sm leading-7 md:min-h-[70vh]"
                          spellCheck={false}
                          value={draft}
                          onChange={(event) => setDraft(event.target.value)}
                        />
                      </div>
                    ) : (
                      <article className="mx-auto max-w-4xl px-6 py-10 sm:px-12 sm:py-14">
                        <Markdown content={document.content} />
                      </article>
                    )}
                  </ScrollArea>
                </>
              ) : (
                <div className="flex min-h-[60vh] flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
                  {loading ? (
                    <LoaderCircle className="size-6 animate-spin text-muted-foreground" />
                  ) : (
                    <FileText className="size-8 text-muted-foreground" />
                  )}
                  <div>
                    <h2 className="font-medium">
                      {loading
                        ? "Carregando workspace"
                        : project
                          ? "Selecione um arquivo"
                          : "Crie seu primeiro projeto"}
                    </h2>
                    <p className="mt-1 max-w-sm text-sm text-muted-foreground">
                      {project
                        ? "Escolha um documento na árvore à esquerda para visualizar e editar."
                        : "Organize seus arquivos Markdown em projetos locais."}
                    </p>
                  </div>
                  {!project && !loading && (
                    <Button onClick={() => setProjectDialogOpen(true)}>
                      <Plus className="size-4" /> Criar projeto
                    </Button>
                  )}
                </div>
              )}
            </main>
          </ResizablePanel>
        </ResizablePanelGroup>
      </SidebarInset>

      <Dialog
        open={folderDialogParent !== null}
        onOpenChange={(open) => !open && setFolderDialogParent(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Nova pasta</DialogTitle>
            <DialogDescription>
              Criar dentro de {folderDialogParent ?? "docs"}.
            </DialogDescription>
          </DialogHeader>
          <form className="grid gap-4" onSubmit={createFolder}>
            <Input
              autoFocus
              required
              placeholder="Nome da pasta"
              value={folderName}
              onChange={(event) => setFolderName(event.target.value)}
            />
            <DialogFooter>
              <Button type="submit">Criar pasta</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog
        open={renameTarget !== null}
        onOpenChange={(open) => {
          if (!open) setRenameTarget(null)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              Renomear {renameTarget?.kind === "folder" ? "pasta" : "arquivo"}
            </DialogTitle>
            <DialogDescription>
              Edite somente o nome. A pasta pai será mantida
              {renameTarget?.kind === "document"
                ? " e a extensão .md permanecerá fixa."
                : "."}{" "}
              A alteração será salva pela API.
            </DialogDescription>
          </DialogHeader>
          <form className="grid gap-4" onSubmit={renameTreeTarget}>
            <div className="relative">
              <Input
                autoFocus
                required
                aria-label={
                  renameTarget?.kind === "document"
                    ? "Nome do arquivo sem extensão"
                    : "Nome da pasta"
                }
                className={
                  renameTarget?.kind === "document" ? "pr-12" : undefined
                }
                value={renamePath}
                onChange={(event) => setRenamePath(event.target.value)}
              />
              {renameTarget?.kind === "document" && (
                <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-sm text-muted-foreground">
                  .md
                </span>
              )}
            </div>
            {renameTarget?.kind === "document" && (
              <p className="-mt-3 text-xs text-muted-foreground">
                A extensão .md é fixa e não pode ser alterada.
              </p>
            )}
            <DialogFooter>
              <Button type="submit">Salvar nome</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog
        open={projectRenameTarget !== null}
        onOpenChange={(open) => {
          if (!open) setProjectRenameTarget(null)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Renomear projeto</DialogTitle>
            <DialogDescription>
              O novo nome será atualizado na lista e na API.
            </DialogDescription>
          </DialogHeader>
          <form className="grid gap-4" onSubmit={renameProject}>
            <Input
              autoFocus
              required
              maxLength={120}
              value={projectRenameName}
              onChange={(event) => setProjectRenameName(event.target.value)}
            />
            <DialogFooter>
              <Button type="submit">Salvar nome</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={deleteTarget !== null || projectDeleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) {
            setDeleteTarget(null)
            setProjectDeleteTarget(null)
            setDeleteConfirmation("")
          }
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {projectDeleteTarget
                ? "Excluir projeto?"
                : `Excluir ${deleteTarget?.kind === "folder" ? "pasta" : "arquivo"}?`}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {projectDeleteTarget
                ? `O projeto “${projectDeleteTarget.name}” será arquivado e removido da lista. Os dados permanecerão no armazenamento local.`
                : deleteTarget?.kind === "folder"
                  ? `A pasta “${deleteTarget.name}” e todos os arquivos e pastas dentro dela serão removidos.`
                  : `“${deleteTarget?.name}” será removido do projeto.`}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="grid gap-2">
            <label
              htmlFor="delete-confirmation"
              className="text-sm font-medium"
            >
              Digite: <span className="font-mono">Deletar</span> para deletar
            </label>
            <Input
              id="delete-confirmation"
              autoComplete="off"
              value={deleteConfirmation}
              onChange={(event) => setDeleteConfirmation(event.target.value)}
            />
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => setDeleteConfirmation("")}>
              Cancelar
            </AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              disabled={deleteConfirmation !== "Deletar"}
              onClick={projectDeleteTarget ? deleteProject : deleteTreeTarget}
            >
              Excluir
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <UpdateDialog
        beforeInstall={async () => !saving && await saveDocument()}
        hasUnsavedChanges={saving || (editing && draft !== document?.content)}
      />
      <Toaster richColors position="bottom-right" />
    </SidebarProvider>
  )
}

function countDocuments(nodes: TreeNode[]): number {
  return nodes.reduce((total, node) => {
    if (node.type === "document") return total + 1
    return total + countDocuments(node.children ?? [])
  }, 0)
}

function normalizePath(path: string): string {
  return path
    .trim()
    .replace(/\\/g, "/")
    .replace(/^\/+|\/+$/g, "")
}

function getInvalidWindowsNameMessage(name: string): string | null {
  if (!name.trim()) return "Informe um nome."
  if (/[<>:"/\\|?*\p{Cc}]/u.test(name)) {
    return "O nome contém caracteres que o Windows não permite."
  }
  if (/[ .]$/.test(name)) {
    return "O nome não pode terminar com ponto ou espaço."
  }

  const firstNamePart = name.split(".", 1)[0]
  const reservedName =
    /^(CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|CLOCK\$|COM[1-9¹²³]|LPT[1-9¹²³])$/i
  if (reservedName.test(firstNamePart)) {
    return "Esse nome é reservado pelo Windows. Escolha outro nome."
  }

  return null
}

function findFirstDocument(nodes: TreeNode[]): TreeNode | undefined {
  for (const node of nodes) {
    if (node.type === "document") return node
    const nested = findFirstDocument(node.children ?? [])
    if (nested) return nested
  }
  return undefined
}

function findDocumentById(
  nodes: TreeNode[],
  documentId: string
): TreeNode | undefined {
  for (const node of nodes) {
    if (node.type === "document" && node.id === documentId) return node
    const nested = findDocumentById(node.children ?? [], documentId)
    if (nested) return nested
  }
  return undefined
}

function findDocumentByPath(
  nodes: TreeNode[],
  path: string
): TreeNode | undefined {
  for (const node of nodes) {
    if (node.type === "document" && node.path === path) return node
    const nested = findDocumentByPath(node.children ?? [], path)
    if (nested) return nested
  }
  return undefined
}

function filterTree(nodes: TreeNode[], query: string): TreeNode[] {
  if (!query) return nodes
  return nodes.flatMap((node) => {
    if (node.type === "document") {
      const label =
        `${node.title ?? ""} ${node.name} ${node.path ?? ""}`.toLocaleLowerCase(
          "pt-BR"
        )
      return label.includes(query) ? [node] : []
    }
    const children = filterTree(node.children ?? [], query)
    return children.length ? [{ ...node, children }] : []
  })
}

function FileTree({
  nodes,
  selectedId,
  onSelect,
  onRename,
  onDelete,
  onCreateDocument,
  onCreateFolder,
  protectedProject = false,
  depth = 0,
  parentPath = "",
}: {
  nodes: TreeNode[]
  selectedId?: string
  onSelect: (id: string) => void
  onRename: (target: TreeActionTarget) => void
  onDelete: (target: TreeActionTarget) => void
  onCreateDocument: (parentPath: string) => void
  onCreateFolder: (parentPath: string) => void
  protectedProject?: boolean
  depth?: number
  parentPath?: string
}) {
  return (
    <div className="grid gap-0.5">
      {nodes.map((node) =>
        node.type === "folder" ? (
          <FolderTreeItem
            key={`${parentPath}/${node.name}`}
            node={node}
            selectedId={selectedId}
            onSelect={onSelect}
            onRename={onRename}
            onDelete={onDelete}
            protectedProject={protectedProject}
            onCreateDocument={onCreateDocument}
            onCreateFolder={onCreateFolder}
            depth={depth}
            path={parentPath ? `${parentPath}/${node.name}` : node.name}
          />
        ) : (
          <ContextMenu key={node.id}>
            <ContextMenuTrigger render={<div className="w-full min-w-0" />}>
              <button
                key={node.id}
                type="button"
                onClick={() => node.id && onSelect(node.id)}
                className={`flex h-8 w-full min-w-0 items-center gap-2 rounded-md pr-2 text-left text-sm transition-colors outline-none hover:bg-accent hover:text-accent-foreground focus-visible:ring-2 focus-visible:ring-ring ${selectedId === node.id ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground"}`}
                style={{ paddingLeft: `${26 + depth * 14}px` }}
              >
                <FileText className="size-4 shrink-0" />
                <span className="truncate">{node.title || node.name}</span>
              </button>
            </ContextMenuTrigger>
            <ContextMenuContent>
              <ContextMenuGroup>
                <ContextMenuLabel>{node.title || node.name}</ContextMenuLabel>
                <ContextMenuItem onClick={() => node.id && onSelect(node.id)}>
                  <FileText /> Abrir
                </ContextMenuItem>
                <ContextMenuItem
                  disabled={protectedProject || node.path === "index.md"}
                  onClick={() =>
                    node.path &&
                    onRename({
                      kind: "document",
                      path: node.path,
                      id: node.id,
                      name: node.title || node.name,
                    })
                  }
                >
                  <Pencil /> Renomear
                </ContextMenuItem>
              </ContextMenuGroup>
              <ContextMenuSeparator />
              <ContextMenuGroup>
                <ContextMenuItem
                  variant="destructive"
                  disabled={protectedProject || node.path === "index.md"}
                  onClick={() =>
                    node.path &&
                    onDelete({
                      kind: "document",
                      path: node.path,
                      id: node.id,
                      name: node.title || node.name,
                    })
                  }
                >
                  <Trash2 /> Excluir
                </ContextMenuItem>
              </ContextMenuGroup>
            </ContextMenuContent>
          </ContextMenu>
        )
      )}
    </div>
  )
}

function FolderTreeItem({
  node,
  path,
  selectedId,
  onSelect,
  onRename,
  onDelete,
  onCreateDocument,
  onCreateFolder,
  protectedProject = false,
  depth,
}: {
  node: TreeNode
  path: string
  selectedId?: string
  onSelect: (id: string) => void
  onRename: (target: TreeActionTarget) => void
  onDelete: (target: TreeActionTarget) => void
  onCreateDocument: (parentPath: string) => void
  onCreateFolder: (parentPath: string) => void
  protectedProject?: boolean
  depth: number
}) {
  const [open, setOpen] = React.useState(true)
  const target: TreeActionTarget = {
    kind: "folder",
    path,
    name: node.name,
  }

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <ContextMenu>
        <ContextMenuTrigger render={<div className="w-full min-w-0" />}>
          <CollapsibleTrigger
            className="flex h-8 w-full items-center gap-2 rounded-md px-2 text-left text-sm text-muted-foreground outline-none hover:bg-accent hover:text-accent-foreground focus-visible:ring-2 focus-visible:ring-ring"
            style={{ paddingLeft: `${8 + depth * 14}px` }}
          >
            <ChevronRight
              className={`size-3.5 transition-transform ${open ? "rotate-90" : ""}`}
            />
            <Folder className="size-4" />
            <span className="truncate">{node.name}</span>
          </CollapsibleTrigger>
        </ContextMenuTrigger>
        <ContextMenuContent>
          <ContextMenuGroup>
            <ContextMenuLabel>{node.name}</ContextMenuLabel>
            <ContextMenuItem disabled={protectedProject} onClick={() => onCreateDocument(path)}>
              <FilePlus2 /> Novo documento
            </ContextMenuItem>
            <ContextMenuItem disabled={protectedProject} onClick={() => onCreateFolder(path)}>
              <FolderPlus /> Nova pasta
            </ContextMenuItem>
          </ContextMenuGroup>
          <ContextMenuSeparator />
          <ContextMenuGroup>
            <ContextMenuItem disabled={protectedProject} onClick={() => onRename(target)}>
              <Pencil /> Renomear
            </ContextMenuItem>
            <ContextMenuItem
              variant="destructive"
              disabled={protectedProject}
              onClick={() => onDelete(target)}
            >
              <Trash2 /> Excluir
            </ContextMenuItem>
          </ContextMenuGroup>
        </ContextMenuContent>
      </ContextMenu>
      <CollapsibleContent className="grid gap-0.5">
        <FileTree
          nodes={node.children ?? []}
          selectedId={selectedId}
          onSelect={onSelect}
          onRename={onRename}
          onDelete={onDelete}
          protectedProject={protectedProject}
          onCreateDocument={onCreateDocument}
          onCreateFolder={onCreateFolder}
          depth={depth + 1}
          parentPath={path}
        />
      </CollapsibleContent>
    </Collapsible>
  )
}

function Markdown({ content }: { content: string }) {
  const { metadata, body } = extractFrontmatter(content)
  return (
    <>
      {metadata !== null && (
        <section aria-label="Metadados do documento" className="mb-6 rounded-lg border border-border bg-muted/50 p-4">
          <p className="text-[10px] font-medium tracking-wider text-muted-foreground uppercase">Metadados</p>
          <pre className="mt-2 font-mono text-xs leading-5 break-words whitespace-pre-wrap text-muted-foreground">{metadata}</pre>
        </section>
      )}
      <div className="text-[15px] leading-7 break-words text-foreground [&_a]:text-primary [&_a]:underline [&_a]:underline-offset-4 [&_blockquote]:my-6 [&_blockquote]:border-l-2 [&_blockquote]:border-primary/50 [&_blockquote]:pl-4 [&_blockquote]:text-muted-foreground [&_code]:rounded-md [&_code]:bg-muted [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-[0.9em] [&_h1]:mt-0 [&_h1]:mb-8 [&_h1]:text-4xl [&_h1]:font-semibold [&_h1]:tracking-tight [&_h2]:mt-10 [&_h2]:mb-4 [&_h2]:border-b [&_h2]:pb-2 [&_h2]:text-2xl [&_h2]:font-semibold [&_h3]:mt-8 [&_h3]:mb-3 [&_h3]:text-xl [&_h3]:font-semibold [&_hr]:my-8 [&_hr]:border-border [&_li]:my-1 [&_ol]:my-4 [&_ol]:list-decimal [&_ol]:pl-6 [&_p]:my-4 [&_pre]:my-5 [&_pre]:overflow-x-auto [&_pre]:rounded-xl [&_pre]:border [&_pre]:bg-muted/60 [&_pre]:p-4 [&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_table]:my-6 [&_table]:w-full [&_table]:border-collapse [&_td]:border [&_td]:px-3 [&_td]:py-2 [&_th]:border [&_th]:bg-muted [&_th]:px-3 [&_th]:py-2 [&_th]:text-left [&_ul]:my-4 [&_ul]:list-disc [&_ul]:pl-6">
        <ReactMarkdown remarkPlugins={[remarkGfm, remarkHeadingAnchors]}>
          {body}
        </ReactMarkdown>
      </div>
    </>
  )
}

type SyncPresentation = {
  label: string
  variant: "secondary" | "outline" | "destructive" | "default"
  icon: LucideIcon
  spinning?: boolean,
  className?: string
}

function syncPresentation(status: SyncStatus): SyncPresentation {
  if (status.state === "unavailable") {
    return {
      label: "Status indisponível",
      variant: "outline",
      icon: CircleAlert,
    }
  }

  if (status.state === "conflict") {
    return {
      label: "Conflito no GitHub",
      variant: "destructive",
      icon: CircleAlert,
    }
  }

  if (status.state === "error" || status.last_error) {
    return {
      label: "Erro ao enviar para o GitHub",
      variant: "destructive",
      icon: CircleAlert,
    }
  }

  if (status.state === "disabled") {
    return {
      label: "Sincronização desativada",
      variant: "outline",
      icon: CloudOff,
    }
  }

  if (status.state === "syncing") {
    return {
      label: "Sincronizando com o GitHub",
      variant: "secondary",
      icon: LoaderCircle,
      spinning: true,
    }
  }

  if (status.state === "queued" || status.pending || status.has_local_changes) {
    return {
      label: "Aguardando envio ao GitHub",
      variant: "secondary",
      icon: CloudUpload,
    }
  }

  if (status.state === "synced") {
    return {
      label: "Sincronizado no GitHub",
      variant: "default",
      icon: CircleCheck,
      className: "bg-green-800 text-white"
    }
  }

  if (status.state === "unauthenticated" || status.state === "idle") {
    return {
      label: "Salvo só neste computador",
      variant: "secondary",
      icon: CloudOff,
    }
  }

  return {
    label: "Verificando sincronização",
    variant: "outline",
    icon: LoaderCircle,
    spinning: true,
  }
}

function SyncStatusIndicator({ status }: { status: SyncStatus }) {
  const presentation = syncPresentation(status)
  const Icon = presentation.icon
  const lastSync = status.last_sync
    ? new Date(status.last_sync).toLocaleString("pt-BR")
    : undefined

  return (
    <Badge
      aria-live="polite"
      className={`w-full justify-start py-3 ${presentation.className}`}
      title={
        status.last_error ??
        (lastSync ? `Última sincronização: ${lastSync}` : undefined)
      }
      variant={presentation.variant}
    >
      <Icon
        data-icon="inline-start"
        className={presentation.spinning ? "animate-spin" : undefined}
      />
      <span className="truncate">{presentation.label}</span>
    </Badge>
  )
}

export default App
