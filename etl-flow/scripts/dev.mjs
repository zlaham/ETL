import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const python =
  process.platform === "win32"
    ? path.join(root, "backend", ".venv", "Scripts", "python.exe")
    : path.join(root, "backend", ".venv", "bin", "python");

if (!existsSync(python)) {
  console.error("Create the API virtualenv first:");
  console.error("  cd backend");
  console.error("  python -m venv .venv");
  console.error("  .venv\\Scripts\\python -m pip install -r requirements.txt");
  process.exit(1);
}

const api = spawn(
  python,
  ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8020"],
  { cwd: path.join(root, "backend"), stdio: "inherit" },
);

const web = spawn("npm", ["run", "dev"], {
  cwd: path.join(root, "frontend"),
  stdio: "inherit",
  shell: true,
});

function shutdown() {
  if (!api.killed) api.kill();
  if (!web.killed) web.kill();
}

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    shutdown();
    process.exit(0);
  });
}

api.on("exit", (code) => {
  shutdown();
  process.exit(code ?? 0);
});

web.on("exit", (code) => {
  shutdown();
  process.exit(code ?? 0);
});

console.log("API  http://127.0.0.1:8020/docs");
console.log("UI   http://127.0.0.1:5173");
