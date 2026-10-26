import { spawn } from "node:child_process"
import { existsSync } from "node:fs"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const scriptsDir = dirname(fileURLToPath(import.meta.url))
const root = resolve(scriptsDir, "..")
const frontend = resolve(root, "frontend")
const python = process.platform === "win32"
  ? resolve(root, ".venv", "Scripts", "python.exe")
  : resolve(root, ".venv", "bin", "python")
const vite = resolve(frontend, "node_modules", "vite", "bin", "vite.js")

for (const requiredPath of [python, vite]) {
  if (!existsSync(requiredPath)) {
    console.error(`Dependência não encontrada: ${requiredPath}`)
    console.error("Crie .venv e instale as dependências do front-end antes de iniciar.")
    process.exit(1)
  }
}

const services = [
  { name: "API", command: python, args: ["-m", "app.main"], cwd: root },
  { name: "Front-end", command: process.execPath, args: [vite, "--host", "127.0.0.1"], cwd: frontend },
]
const children = []
let stopping = false

function stopAll() {
  for (const child of children) {
    if (child.exitCode === null && child.signalCode === null) {
      child.kill("SIGTERM")
    }
  }
}

function stop(exitCode, reason) {
  if (stopping) return
  stopping = true
  process.exitCode = exitCode
  console.log(`\n${reason}; encerrando os serviços...`)
  stopAll()
}

process.once("SIGINT", () => stop(130, "Interrupção recebida"))
process.once("SIGTERM", () => stop(143, "Encerramento solicitado"))

for (const service of services) {
  console.log(`[${service.name}] iniciando...`)
  const child = spawn(service.command, service.args, {
    cwd: service.cwd,
    stdio: "inherit",
    windowsHide: true,
  })
  children.push(child)
  child.once("error", (error) => {
    console.error(`[${service.name}] falha ao iniciar: ${error.message}`)
    stop(1, "Falha ao iniciar um serviço")
  })
  child.once("exit", (code, signal) => {
    if (!stopping) {
      const status = signal ? `sinal ${signal}` : `código ${code}`
      stop(code ?? 1, `${service.name} terminou (${status})`)
    }
  })
}

console.log("Desenvolvimento iniciado. Acesse http://127.0.0.1:5173. Use Ctrl+C para encerrar.")
