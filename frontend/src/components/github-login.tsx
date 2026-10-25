import * as React from "react"
import { Copy, ExternalLink, LoaderCircle } from "lucide-react"
import { toast } from "sonner"

import { GitHubIcon } from "@/components/github-icon"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { ApiError, request } from "@/lib/api"

type DeviceAuthorization = {
  attempt_id: string
  user_code: string
  verification_uri: string
  expires_in: number
  interval: number
  expiresAt: number
}

type AuthorizationResult =
  { status: "pending"; retry_after: number } | { status: "authenticated" }

function cancelAuthorization(attempt: DeviceAuthorization | null) {
  if (attempt) {
    void request("/github/auth/cancel", {
      method: "POST",
      body: JSON.stringify({ attempt_id: attempt.attempt_id }),
      keepalive: true,
    }).catch(() => undefined)
  }
}

export function GitHubLogin({
  onConnected,
}: {
  onConnected: () => Promise<void>
}) {
  const [starting, setStarting] = React.useState(false)
  const [attempt, setAttempt] = React.useState<DeviceAuthorization | null>(null)
  const [connectionError, setConnectionError] = React.useState<string | null>(
    null
  )
  const attemptRef = React.useRef<DeviceAuthorization | null>(null)
  const generation = React.useRef(0)
  const onConnectedRef = React.useRef(onConnected)

  React.useEffect(() => {
    onConnectedRef.current = onConnected
  }, [onConnected])

  React.useEffect(
    () => () => {
      generation.current += 1
      cancelAuthorization(attemptRef.current)
    },
    []
  )

  function cancelLogin() {
    generation.current += 1
    cancelAuthorization(attemptRef.current)
    attemptRef.current = null
    setAttempt(null)
    setStarting(false)
  }

  React.useEffect(() => {
    if (!attempt) return
    const authorization = attempt
    let active = true
    let timer: number

    function finish() {
      attemptRef.current = null
      setAttempt(null)
    }

    async function poll() {
      if (Date.now() >= authorization.expiresAt) {
        cancelAuthorization(attempt)
        finish()
        toast.error(
          "O código expirou. Clique em Logar com GitHub para tentar novamente."
        )
        return
      }
      try {
        const result = await request<AuthorizationResult>("/github/auth/poll", {
          method: "POST",
          body: JSON.stringify({ attempt_id: authorization.attempt_id }),
        })
        if (
          !active ||
          attemptRef.current?.attempt_id !== authorization.attempt_id
        )
          return
        setConnectionError(null)
        if (result.status === "authenticated") {
          finish()
          toast.success("Conta GitHub conectada")
          try {
            await onConnectedRef.current()
          } catch {
            toast.error(
              "Conta conectada. Recarregue a página para atualizar os dados da conta."
            )
          }
          return
        }
        timer = window.setTimeout(poll, result.retry_after * 1000)
      } catch (error) {
        if (!active) return
        if (!(error instanceof ApiError) || error.status >= 500) {
          setConnectionError("Sem conexão com o GitHub. Tentando novamente...")
          timer = window.setTimeout(poll, authorization.interval * 1000)
          return
        }
        finish()
        toast.error(error.message)
      }
    }

    timer = window.setTimeout(poll, attempt.interval * 1000)
    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [attempt])

  async function startLogin() {
    const currentGeneration = ++generation.current
    // Open a regular browser tab directly from the click, before awaiting the API.
    window.open(
      "https://github.com/login/device",
      "_blank",
      "noopener,noreferrer"
    )
    setStarting(true)
    setConnectionError(null)
    try {
      const result = await request<DeviceAuthorization>("/github/auth/start", {
        method: "POST",
      })
      const nextAttempt = {
        ...result,
        expiresAt: Date.now() + result.expires_in * 1000,
      }
      if (generation.current !== currentGeneration) {
        cancelAuthorization(nextAttempt)
        return
      }
      attemptRef.current = nextAttempt
      setAttempt(nextAttempt)
    } catch (error) {
      if (generation.current === currentGeneration) {
        toast.error(
          error instanceof Error
            ? error.message
            : "Não foi possível iniciar o login"
        )
      }
    } finally {
      if (generation.current === currentGeneration) setStarting(false)
    }
  }

  async function copyCode() {
    if (!attempt) return
    try {
      await navigator.clipboard.writeText(attempt.user_code)
      toast.success("Código copiado")
    } catch {
      toast.error(
        "Não foi possível copiar. Selecione o código e copie manualmente."
      )
    }
  }

  return (
    <>
      <Button
        size="sm"
        variant="github"
        disabled={starting || !!attempt}
        onClick={() => void startLogin()}
      >
        {starting ? (
          <LoaderCircle data-icon="inline-start" className="animate-spin" />
        ) : (
          <GitHubIcon data-icon="inline-start" />
        )}
        {starting ? "Abrindo GitHub..." : "Logar com GitHub"}
      </Button>
      <Dialog open={!!attempt} onOpenChange={(open) => !open && cancelLogin()}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Autorizar no GitHub</DialogTitle>
            <DialogDescription>
              Na aba do GitHub aberta no navegador, informe este código e
              autorize o Docs Local. Depois, volte a esta aba: a conexão será
              concluída automaticamente.
            </DialogDescription>
          </DialogHeader>
          <div className="flex items-center justify-center gap-3">
            <code
              className="font-mono text-2xl font-semibold tracking-widest select-all"
              aria-label="Código de autorização do GitHub"
            >
              {attempt?.user_code}
            </code>
            <Button
              variant="outline"
              size="icon"
              aria-label="Copiar código"
              onClick={() => void copyCode()}
            >
              <Copy />
            </Button>
          </div>
          <p
            className="text-center text-sm text-muted-foreground"
            role="status"
          >
            {connectionError ?? "Aguardando autorização no GitHub..."}
          </p>
          <DialogFooter>
            <Button variant="ghost" onClick={cancelLogin}>
              Cancelar
            </Button>
            <Button
              variant="github"
              render={
                <a
                  href={attempt?.verification_uri}
                  target="_blank"
                  rel="noopener noreferrer"
                />
              }
            >
              <ExternalLink data-icon="inline-start" /> Abrir GitHub
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
