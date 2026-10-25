import * as React from "react"
import { Download, LoaderCircle, RefreshCw } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { request } from "@/lib/api"

type UpdateStatus = {
  current_version: string
  available_version: string | null
  release_name: string | null
  state: "idle" | "available" | "downloading" | "restarting" | "error"
  error: string | null
  supported: boolean
  deferred_until: number
}

export function UpdateDialog({
  beforeInstall,
  hasUnsavedChanges,
}: {
  beforeInstall: () => Promise<boolean>
  hasUnsavedChanges: boolean
}) {
  const [clientId] = React.useState(() => crypto.randomUUID())
  const [status, setStatus] = React.useState<UpdateStatus | null>(null)
  const [seconds, setSeconds] = React.useState(30)
  const [preparing, setPreparing] = React.useState(false)
  const [paused, setPaused] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [eligible, setEligible] = React.useState(false)
  const beforeInstallRef = React.useRef(beforeInstall)
  const offered = React.useRef("")
  const installingVersion = React.useRef<string | null>(null)

  React.useEffect(() => {
    async function updateHold(dirty: boolean) {
      await request("/updates/hold", {
        method: "POST",
        body: JSON.stringify({ client_id: clientId, dirty }),
        keepalive: true,
      })
    }
    void updateHold(hasUnsavedChanges).catch(() => undefined)
    const timer = hasUnsavedChanges
      ? window.setInterval(
          () => void updateHold(true).catch(() => undefined),
          5000
        )
      : undefined
    return () => {
      window.clearInterval(timer)
      void updateHold(false).catch(() => undefined)
    }
  }, [clientId, hasUnsavedChanges])

  React.useEffect(() => {
    beforeInstallRef.current = beforeInstall
  }, [beforeInstall])

  React.useEffect(() => {
    let active = true
    let timer: number
    async function poll() {
      try {
        const next = await request<UpdateStatus>("/updates/status")
        if (!active) return
        if (
          installingVersion.current &&
          next.current_version !== installingVersion.current
        ) {
          window.location.reload()
          return
        }
        const key = `${next.available_version}:${next.deferred_until}`
        setEligible(next.deferred_until <= Date.now() / 1000)
        if (
          next.available_version &&
          next.supported &&
          next.deferred_until <= Date.now() / 1000 &&
          offered.current !== key
        ) {
          offered.current = key
          setSeconds(30)
          setPaused(false)
          setError(null)
        }
        setStatus(next)
      } catch {
        // The local server is temporarily unavailable while the executable restarts.
      } finally {
        if (active) timer = window.setTimeout(poll, 5000)
      }
    }
    void poll()
    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [])

  const open = !!status?.supported && !!status.available_version && eligible
  const installing =
    preparing ||
    status?.state === "downloading" ||
    status?.state === "restarting"

  async function install() {
    if (installing || !status) return
    setPreparing(true)
    setError(null)
    try {
      if (!(await beforeInstallRef.current())) {
        setPaused(true)
        setError(
          "A atualização foi pausada porque o documento aberto não pôde ser salvo. Resolva o salvamento e tente novamente."
        )
        return
      }
      installingVersion.current = status.current_version
      await request("/updates/hold", {
        method: "POST",
        body: JSON.stringify({ client_id: clientId, dirty: false }),
      })
      const next = await request<UpdateStatus>("/updates/install", {
        method: "POST",
      })
      setStatus(next)
    } catch (failure) {
      installingVersion.current = null
      setPaused(true)
      setError(
        failure instanceof Error
          ? failure.message
          : "Não foi possível iniciar a atualização."
      )
    } finally {
      setPreparing(false)
    }
  }

  const installAutomatically = React.useEffectEvent(() => void install())
  React.useEffect(() => {
    if (!open || paused || installing || status?.state !== "available") return
    if (seconds <= 0) {
      const timer = window.setTimeout(() => installAutomatically(), 0)
      return () => window.clearTimeout(timer)
    }
    const timer = window.setTimeout(
      () => setSeconds((remaining) => remaining - 1),
      1000
    )
    return () => window.clearTimeout(timer)
  }, [open, paused, installing, seconds, status?.state])

  async function defer() {
    if (installing) return
    setPaused(true)
    try {
      setStatus(
        await request<UpdateStatus>("/updates/defer", { method: "POST" })
      )
      setEligible(false)
    } catch {
      setError("Não foi possível adiar a atualização. Tente novamente.")
    }
  }

  return (
    <Dialog open={open} onOpenChange={(nextOpen) => !nextOpen && void defer()}>
      <DialogContent showCloseButton={!installing}>
        <DialogHeader>
          <DialogTitle>
            {installing ? "Atualizando o Docs Local" : "Nova versão disponível"}
          </DialogTitle>
          <DialogDescription>
            {status?.release_name ?? status?.available_version} está disponível.
            O Docs Local salvará o documento aberto, baixará e verificará a
            atualização, fechará o aplicativo e reiniciará automaticamente. Os
            arquivos e a fila de backup serão preservados.
          </DialogDescription>
        </DialogHeader>
        <p role="status" className="text-sm text-muted-foreground">
          {preparing
            ? "Salvando o documento aberto..."
            : status?.state === "downloading"
              ? "Baixando e verificando a atualização..."
              : status?.state === "restarting"
                ? "Reiniciando. Esta página será recarregada quando o aplicativo voltar."
                : paused || status?.state === "error"
                  ? "Atualização automática pausada."
                  : `A atualização começará automaticamente em ${seconds} segundos.`}
        </p>
        {(error || status?.error) && (
          <p role="alert" className="text-sm text-destructive">
            {error ?? status?.error}
          </p>
        )}
        <DialogFooter>
          <Button
            variant="ghost"
            disabled={installing}
            onClick={() => void defer()}
          >
            Adiar por 1 hora
          </Button>
          <Button disabled={installing} onClick={() => void install()}>
            {installing ? (
              <LoaderCircle data-icon="inline-start" className="animate-spin" />
            ) : status?.state === "error" ? (
              <RefreshCw data-icon="inline-start" />
            ) : (
              <Download data-icon="inline-start" />
            )}
            {installing ? "Atualizando..." : "Atualizar agora"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
